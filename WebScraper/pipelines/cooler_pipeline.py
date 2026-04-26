import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import COOLER_CATEGORY_URL
from scrapers.pic_bg.cooler_page import parse_cooler_page
from ai.cooler_parser import parse_cooler
from ai.cooler_normalization import (
    normalize_cooler_brand,
    normalize_cooler_model,
    normalize_cooler_type,
    normalize_cooler_sockets,
    normalize_cooler_height_mm,
    normalize_cooler_tdp_w,
    normalize_cooler_fan_size_mm,
    normalize_cooler_fan_count,
    normalize_cooler_noise_db,
    normalize_cooler_rpm_max,
)
from storage.cooler_repository import upsert_cooler

logger = logging.getLogger("cooler_pipeline")
if not logger.handlers:
    fh = logging.FileHandler(os.environ.get("SCRAPER_ERROR_LOG", "scraper_errors.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


async def _retry(coro_fn, *args, attempts: int = 3, delay: float = 1.0, **kwargs):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Attempt %d failed for %s: %s",
                attempt,
                getattr(coro_fn, "__name__", str(coro_fn)),
                exc,
            )
            if attempt < attempts:
                await asyncio.sleep(delay)
    raise last_exc


async def accept_cookies(page):
    try:
        await page.click("button:has-text('Приемам')", timeout=4000)
        await asyncio.sleep(1)
    except Exception:
        pass


async def collect_cooler_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href]:not([href^='/cart/'])")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if href and href.startswith("/"):
            full = "https://www.pic.bg" + href
            if full not in urls:
                urls.append(full)

    print(f"  -> Coolers on page: {len(urls)}")
    return urls


async def get_next_page_button(page, current_page: int):
    next_page = current_page + 1
    selector = f"div.pages button.page_link[data-page='{next_page}']"
    btn = page.locator(selector)

    if await btn.count() == 0:
        return None
    disabled = await btn.first.get_attribute("disabled")
    if disabled is not None:
        return None
    return btn.first


def _normalize_brand(value: str | None) -> Optional[str]:
    return normalize_cooler_brand(value)


def _infer_brand_from_text(*texts: str | None) -> Optional[str]:
    joined = " ".join(str(t) for t in texts if t)
    return normalize_cooler_brand(joined)


def _normalize_model(value: str | None, brand: str | None = None) -> Optional[str]:
    return normalize_cooler_model(value, brand)


def _spec_lookup(specs: dict, *needles: str) -> tuple[Optional[str], Optional[str]]:
    for needle in needles:
        for key, value in (specs or {}).items():
            if needle in str(key).lower():
                return str(key), str(value)
    return None, None


def _build_ai_source(specs: dict, raw: str) -> str:
    if specs:
        preferred = (
            "модел",
            "тип",
            "вид",
            "сокет",
            "съвместим",
            "височина",
            "tdp",
            "капацитет",
            "мощност",
            "разсейване",
            "вентилатор",
            "размер на вентилатора",
            "диаметър",
            "брой вентилатори",
            "fan",
            "шум",
            "noise",
            "обороти",
            "оборот",
            "rpm",
        )
        lines = [
            f"{k}: {v}"
            for k, v in specs.items()
            if any(p in str(k).lower() for p in preferred)
        ]
        if not lines:
            lines = [f"{k}: {v}" for k, v in specs.items()]
        return "\n".join(lines)[:8000]
    return (raw or "")[:8000]


def _extract_cooler_type(*texts: str | None) -> Optional[str]:
    for text in texts:
        value = normalize_cooler_type(text)
        if value is not None:
            return value
    return None


def _extract_cooler_sockets(*texts: str | None) -> Optional[str]:
    for text in texts:
        value = normalize_cooler_sockets(text)
        if value is not None:
            return value
    return None


def _extract_cooler_data(name: str, specs: dict, raw: str, url: str) -> tuple[dict, set[str]]:
    strong = set()

    brand = _infer_brand_from_text(name, raw)
    model_key, model_val = _spec_lookup(specs, "модел")
    cand_spec = _normalize_model(model_val, brand) if model_val else None
    cand_name = _normalize_model(name, brand) if name else None
    if cand_spec and not _looks_like_sku(cand_spec, name):
        model = cand_spec
    elif cand_name:
        model = cand_name
    else:
        model = cand_spec
    if model is not None:
        strong.add("model")

    type_key, type_val = _spec_lookup(specs, "тип", "вид", "type")
    cooler_type = normalize_cooler_type(type_val) if type_val else None
    if cooler_type is None:
        cooler_type = _extract_cooler_type(name, raw)
    elif type_val:
        strong.add("cooler_type")

    socket_key, socket_val = _spec_lookup(
        specs, "сокет", "съвместимост", "socket", "compatibility"
    )
    socket_compatibility = normalize_cooler_sockets(socket_val) if socket_val else None
    if socket_compatibility is None:
        socket_compatibility = _extract_cooler_sockets(name, raw)
    elif socket_val:
        strong.add("socket_compatibility")

    height_key, height_val = _spec_lookup(specs, "височина", "height")
    cooler_height_mm = normalize_cooler_height_mm(height_val) if height_val else None
    if height_val and cooler_height_mm is not None:
        strong.add("cooler_height_mm")

    tdp_key, tdp_val = _spec_lookup(
        specs, "tdp", "капацитет", "разсейване", "мощност"
    )
    tdp_w = normalize_cooler_tdp_w(tdp_val) if tdp_val else None
    if tdp_val and tdp_w is not None:
        strong.add("tdp_w")

    fan_size_key, fan_size_val = _spec_lookup(
        specs, "размер на вентилатор", "диаметър", "fan size"
    )
    fan_size_mm = normalize_cooler_fan_size_mm(fan_size_val) if fan_size_val else None
    if fan_size_val and fan_size_mm is not None:
        strong.add("fan_size_mm")

    fan_count_key, fan_count_val = _spec_lookup(
        specs, "брой вентилатори", "fans", "вентилатор"
    )
    # Avoid double-match with fan_size_key: if key matched fan_size, skip it
    if fan_count_key and fan_size_key and fan_count_key == fan_size_key:
        fan_count_val = None
    fan_count = normalize_cooler_fan_count(fan_count_val) if fan_count_val else None
    if fan_count_val and fan_count is not None:
        strong.add("fan_count")

    noise_key, noise_val = _spec_lookup(specs, "шум", "noise", "dba", "db")
    noise_db = normalize_cooler_noise_db(noise_val) if noise_val else None
    if noise_val and noise_db is not None:
        strong.add("noise_db")

    rpm_key, rpm_val = _spec_lookup(specs, "оборот", "rpm")
    rpm_max = normalize_cooler_rpm_max(rpm_val) if rpm_val else None
    if rpm_val and rpm_max is not None:
        strong.add("rpm_max")

    return {
        "brand": brand,
        "model": model,
        "cooler_type": cooler_type,
        "socket_compatibility": socket_compatibility,
        "cooler_height_mm": cooler_height_mm,
        "tdp_w": tdp_w,
        "fan_size_mm": fan_size_mm,
        "fan_count": fan_count,
        "noise_db": noise_db,
        "rpm_max": rpm_max,
    }, strong


def _merge_value(field: str, ai_value, det_value, strong_fields: set[str]):
    if field in strong_fields and det_value is not None:
        return det_value
    return ai_value if ai_value is not None else det_value


def _looks_like_sku(value: str | None, name: str | None) -> bool:
    """Manufacturer SKU-style token — reject as user-facing model.
    (a) no space, >=8 chars, >=30% digits;
    (b) hyphen-chain (>=3 hyphens + digit);
    (c) R-prefix pattern."""
    if not value or " " in value:
        return False
    if len(value) < 5:
        return False
    if value.lower() in (name or "").lower():
        return False
    digits = sum(c.isdigit() for c in value)
    if digits == 0:
        return False
    hyphens = value.count("-")
    if len(value) >= 8 and digits / len(value) >= 0.3:
        return True
    if hyphens >= 3:
        return True
    if re.match(r"^R-[A-Z0-9]+-[A-Z0-9]+", value):
        return True
    # (d) short hyphenated code with interspersed digits (letter between digits)
    if hyphens >= 1 and re.search(r"\d[A-Z]+\d", value.upper()):
        return True
    # (e) trailing 2-3 all-letter color code after hyphen (e.g. "PA401-TG-BK")
    if hyphens >= 2:
        last = value.split("-")[-1]
        if last.isalpha() and 2 <= len(last) <= 3:
            return True
    # (f) short all-caps-alnum, no hyphens, digit-heavy — "BW020", "EY3B001"
    if ("-" not in value and value.isupper()
            and 5 <= len(value) <= 10
            and digits / len(value) >= 0.3):
        return True
    # (g) underscore-containing → retailer-mangled form
    if "_" in value:
        return True
    return False


def _sanitize_raw_model_fallback(raw: str | None) -> str | None:
    """Junk-strip rules applied to raw value before truncating to 50 chars.
    Used only when the normalizer returned None. Guarantees non-NULL."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^[\s,\-]+", "", s)
    s = re.sub(r"(?:\.{3,}|…)", " ", s)
    s = re.sub(
        r"\b(?:Panel|PC\s+Case|Power\s+Supply(?:\s+(?:AC|DC))?|\d{2,4}\s*mm\s+Radiator|Radiator|NVIDIA\s+Limit\w*(?:\s+Edition)?|Limited\s+Edition)\b",
        " ", s, flags=re.IGNORECASE,
    )
    s = re.sub(r"\b\d{2,4}(?:\s*/\s*\d{2,4})?\s*V\b[\s_/]*", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"_(?:WITHOUT|WITH|NO)[_\s]+CABLE[_A-Z0-9]*", "", s, flags=re.IGNORECASE)
    # Round 6: packaging suffix, socket-list strip, underscore-reject
    s = re.sub(r"\s*/\s*(?:Bulk|Retail|OEM|Tray|Box)\b.*$", "", s, flags=re.IGNORECASE)
    _SOCKET_ATOM = r"(?:LGA\s*\d{3,4}(?:-\d)?|AM[0-9](?:\+)?|FM[12](?:\+)?|TR[45]|sTRX?\d|SP[356]|Intel|AMD)"
    s = re.sub(rf"^\s*{_SOCKET_ATOM}(?:\s*/\s*{_SOCKET_ATOM})*\s*[-,]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(rf"\s*{_SOCKET_ATOM}(?:\s*/\s*{_SOCKET_ATOM})+\s*$", "", s, flags=re.IGNORECASE)
    if "_" in s:
        return None
    s = " ".join(s.split()).strip("- ,/")
    if not s:
        s = raw.strip()
    if len(s) > 50:
        s = s[:50].rsplit(" ", 1)[0].strip(" -,")
    return s or None


def _is_accessory_or_non_cooler(*texts: str | None) -> bool:
    joined = " ".join(str(t) for t in texts if t).upper()

    strong_cooler_evidence = bool(
        re.search(r"\bAIO\b", joined)
        or re.search(r"\bTOWER\b", joined)
        or re.search(r"\bHEATPIPE\b", joined)
        or re.search(r"\bHEATSINK\b", joined)
        or re.search(r"\bTDP\b", joined)
        or re.search(r"\bLGA\d{3,4}\b", joined)
        or re.search(r"\bAM[45]\b", joined)
        or "ВОДНО" in joined
        or "РАДИАТОР" in joined
    )

    # Thermal paste / grease
    if re.search(
        r"\b(THERMAL\s+PASTE|THERMAL\s+GREASE|ТЕРМОПАСТА|ТЕРМО\s+ПАСТА)\b",
        joined,
    ):
        if not strong_cooler_evidence:
            return True
    # Generic "PASTE" keyword without AIO/tower context
    if re.search(r"\bPASTE\b", joined) and not strong_cooler_evidence:
        return True

    # Cables / adapters
    if re.search(r"\b(CABLE|КАБЕЛ)\b", joined):
        if not strong_cooler_evidence:
            return True

    # Standalone fans without heatsink/AIO signal
    if re.search(r"\b(CASE\s+FAN|CHASSIS\s+FAN)\b", joined):
        if not strong_cooler_evidence:
            return True

    return False


def _is_low_signal_cooler_page(parsed: dict, det: dict, final: dict, strong_fields: set[str]) -> bool:
    specs = parsed.get("specs") or {}
    raw = parsed.get("raw_specs") or ""
    signal_fields = sum(
        1
        for field in (
            "cooler_type",
            "socket_compatibility",
            "cooler_height_mm",
            "tdp_w",
            "fan_size_mm",
            "fan_count",
        )
        if final.get(field) is not None or det.get(field) is not None
    )
    model = final.get("model") or det.get("model") or parsed.get("model") or ""
    has_specs_signal = bool(specs) and any(
        key in strong_fields
        for key in (
            "cooler_type",
            "socket_compatibility",
            "cooler_height_mm",
            "tdp_w",
            "fan_size_mm",
            "fan_count",
        )
    )
    if has_specs_signal:
        return False
    if not specs and signal_fields < 3:
        return True
    if len(model) > 120 and signal_fields < 4:
        return True
    if len(specs) <= 1 and signal_fields < 3:
        return True
    if not specs and len(raw) < 200 and signal_fields < 3:
        return True
    return False


async def run_cooler_pipeline(headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None):
    async with Browser(headless=headless) as page:
        await page.set_extra_http_headers(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                )
            }
        )

        print(f"Opening {COOLER_CATEGORY_URL}")
        await page.goto(COOLER_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")
            urls = await collect_cooler_urls(page)
            if not urls:
                print("No products found, stopping.")
                break

            first_url = urls[0]
            if first_url == last_first_url:
                print("Page content did not change, stopping.")
                break

            last_first_url = first_url
            before = len(all_urls)
            all_urls.update(urls)
            print(f"  -> New Cooler products added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("No enabled next page button, stopping.")
                break

            print(f"Clicking page {current_page + 1}")
            await next_button.click()
            try:
                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href]:not([href^='/cart/'])");
                        return el && el.href !== prev;
                    }""",
                    arg=first_url,
                    timeout=15000,
                )
            except Exception:
                print("Products did not update after click, stopping.")
                break

            current_page += 1
            await asyncio.sleep(1.5)

        all_urls_list = [{"url": url} for url in sorted(all_urls)]
        with open("cooler_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_urls_list)} Cooler links to cooler_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\nProcessing collected Cooler pages and inserting into DB...")
        processed = 0
        for url in sorted(all_urls):
            if page_limit and processed >= page_limit:
                break
            try:
                print(f"  -> Fetching: {url}")
                await _retry(
                    page.goto,
                    url,
                    wait_until="domcontentloaded",
                    timeout=90000,
                    attempts=3,
                    delay=1.5,
                )
                await asyncio.sleep(0.6)
                html = await _retry(page.content, attempts=2, delay=0.5)
                parsed = parse_cooler_page(html, url)
                name = parsed.get("name") or ""
                raw = parsed.get("raw_specs") or ""
                specs = parsed.get("specs") or {}

                if _is_accessory_or_non_cooler(name, raw, str(specs)):
                    print(f"    Skipping non-cooler/accessory: {url}")
                    continue

                det, strong_fields = _extract_cooler_data(name, specs, raw, url)

                try:
                    ai_source = _build_ai_source(specs, raw)
                    ai_data = parse_cooler(ai_source, name, parsed.get("price", 0.0), url)
                except Exception as exc:
                    logger.exception("AI parsing failed for %s", url)
                    print(f"    AI parse error for {url}: {exc}")
                    ai_data = {}

                final = {}
                final["brand"] = (
                    _normalize_brand(parsed.get("brand"))
                    or _normalize_brand(det.get("brand"))
                    or _normalize_brand(ai_data.get("brand"))
                    or _infer_brand_from_text(name, raw)
                )
                if final["brand"] is None:
                    raw_candidates = [
                        parsed.get("brand"),
                        ai_data.get("brand"),
                    ]
                    raw_candidates = [b for b in raw_candidates if b]
                    if raw_candidates:
                        logger.info(
                            "Unrecognized cooler brand candidates for %s: %s",
                            url,
                            raw_candidates,
                        )

                final_model = _normalize_model(
                    _merge_value("model", ai_data.get("model"), det.get("model"), strong_fields)
                    or parsed.get("model")
                    or name,
                    final.get("brand"),
                )
                if final_model is None:
                    final_model = _sanitize_raw_model_fallback(parsed.get("model") or name)
                final["model"] = final_model
                final["cooler_type"] = normalize_cooler_type(
                    _merge_value("cooler_type", ai_data.get("cooler_type"), det.get("cooler_type"), strong_fields)
                )
                final["socket_compatibility"] = normalize_cooler_sockets(
                    _merge_value(
                        "socket_compatibility",
                        ai_data.get("socket_compatibility"),
                        det.get("socket_compatibility"),
                        strong_fields,
                    )
                )
                final["cooler_height_mm"] = normalize_cooler_height_mm(
                    _merge_value(
                        "cooler_height_mm",
                        ai_data.get("cooler_height_mm"),
                        det.get("cooler_height_mm"),
                        strong_fields,
                    )
                )
                final["tdp_w"] = normalize_cooler_tdp_w(
                    _merge_value("tdp_w", ai_data.get("tdp_w"), det.get("tdp_w"), strong_fields)
                )
                final["fan_size_mm"] = normalize_cooler_fan_size_mm(
                    _merge_value(
                        "fan_size_mm",
                        ai_data.get("fan_size_mm"),
                        det.get("fan_size_mm"),
                        strong_fields,
                    )
                )
                final["fan_count"] = normalize_cooler_fan_count(
                    _merge_value(
                        "fan_count", ai_data.get("fan_count"), det.get("fan_count"), strong_fields
                    )
                )
                final["noise_db"] = normalize_cooler_noise_db(
                    _merge_value("noise_db", ai_data.get("noise_db"), det.get("noise_db"), strong_fields)
                )
                final["rpm_max"] = normalize_cooler_rpm_max(
                    _merge_value("rpm_max", ai_data.get("rpm_max"), det.get("rpm_max"), strong_fields)
                )

                if not final.get("brand") or not final.get("model") or not final.get("cooler_type"):
                    print(f"    Skipping incomplete cooler record for {url}")
                    continue

                if (
                    parsed.get("brand_source") == "breadcrumb" or final.get("brand") is None
                ) and _is_low_signal_cooler_page(parsed, det, final, strong_fields):
                    print(f"    Skipping low-signal cooler page for {url}")
                    continue

                if _is_low_signal_cooler_page(parsed, det, final, strong_fields):
                    print(f"    Skipping low-signal cooler page for {url}")
                    continue

                final["price"] = parsed.get("price") if parsed.get("price") is not None else ai_data.get("price")
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_cooler(final)
                    print(f"    Upserted: {final.get('model')}")
                except Exception as exc:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {exc}")

                processed += 1
            except Exception as exc:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {exc}")
