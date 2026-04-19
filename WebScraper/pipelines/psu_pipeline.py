import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import PSU_CATEGORY_URL
from scrapers.pic_bg.psu_page import parse_psu_page
from ai.psu_parser import parse_psu
from ai.psu_normalization import (
    normalize_psu_brand,
    normalize_psu_model,
    normalize_psu_physical_size,
    normalize_psu_power_w,
    normalize_psu_efficiency,
    normalize_psu_certificate,
    normalize_psu_modularity,
    normalize_psu_fan_size_mm,
)
from storage.psu_repository import upsert_psu

logger = logging.getLogger("psu_pipeline")
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


async def collect_psu_urls(page) -> list[str]:
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

    print(f"  -> PSUs on page: {len(urls)}")
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
    return normalize_psu_brand(value)


def _infer_brand_from_text(*texts: str | None) -> Optional[str]:
    joined = " ".join(str(t) for t in texts if t)
    return normalize_psu_brand(joined)


def _normalize_model(value: str | None, brand: str | None = None) -> Optional[str]:
    return normalize_psu_model(value, brand)


def _normalize_physical_size(value: str | None) -> Optional[str]:
    return normalize_psu_physical_size(value)


def _extract_physical_size(*texts: str | None) -> Optional[str]:
    for index, text in enumerate(texts):
        value = normalize_psu_physical_size(text)
        if value is not None:
            if value == "ATX" and index > 0:
                upper = str(text).upper()
                explicit_context = any(
                    token in upper
                    for token in ("FORM FACTOR", "ФОРМ ФАКТОР", "ФИЗИЧЕСКИ РАЗМЕР", "SIZE")
                )
                if not explicit_context:
                    continue
            return value
    return None


def _normalize_power_w(value) -> Optional[int]:
    return normalize_psu_power_w(value)


def _extract_power_w(*texts: str | None) -> Optional[int]:
    for text in texts:
        value = normalize_psu_power_w(text)
        if value is not None:
            return value
    return None


def _normalize_efficiency(value: str | None) -> Optional[str]:
    return normalize_psu_efficiency(value)


def _normalize_certificate(value: str | None) -> Optional[str]:
    return normalize_psu_certificate(value)


def _normalize_modularity(value: str | None) -> Optional[str]:
    return normalize_psu_modularity(value)


def _normalize_fan_size_mm(value) -> Optional[int]:
    return normalize_psu_fan_size_mm(value)


def _is_accessory_or_non_psu(*texts: str | None) -> bool:
    joined = " ".join(str(t) for t in texts if t).upper()
    if re.search(r"\b(UPS|НЕПРЕКЪСВАЕМО|UNINTERRUPTIBLE)\b", joined):
        return True
    if re.search(r"\b(BATTERY|BATTERIES|БАТЕРИЯ|АКУМУЛАТОР)\b", joined):
        return True
    if re.search(r"\b(CABLE|CABLES|EXTENSION|EXTENDER|SPLITTER|ADAPTER|TESTER|BRACKET|COVER|SLEEVE|SLEEVED|КАБЕЛ|АДАПТЕР|ПРЕХОДНИК|ТЕСТЕР|СКОБА)\b", joined):
        has_strong_psu_evidence = bool(
            re.search(r"\b\d{3,4}\s*(?:W(?:ATT)?|ВАТТ?)\b", joined)
            and (
                re.search(r"\b80\s*(?:\+|PLUS)\b", joined)
                or re.search(r"\b(?:ATX|SFX|SFX-L|TFX|FLEX\s*ATX|ITX)\b", joined)
                or re.search(r"\b(?:MODULAR|SEMI[-\s]?MODULAR|NON[-\s]?MODULAR)\b", joined)
            )
        )
        if not has_strong_psu_evidence:
            return True
    return False


def _is_low_signal_psu_page(parsed: dict, det: dict, final: dict, strong_fields: set[str]) -> bool:
    specs = parsed.get("specs") or {}
    raw = parsed.get("raw_specs") or ""
    signal_fields = sum(
        1
        for field in (
            "physical_size",
            "power_w",
            "efficiency",
            "certificate",
            "modularity",
            "fan_size_mm",
        )
        if final.get(field) is not None or det.get(field) is not None
    )
    model = final.get("model") or det.get("model") or parsed.get("model") or ""
    has_specs_signal = bool(specs) and any(
        key in strong_fields
        for key in (
            "power_w",
            "physical_size",
            "certificate",
            "modularity",
            "fan_size_mm",
        )
    )
    if has_specs_signal:
        return False
    if len(model) > 120 and signal_fields < 4:
        return True
    if len(specs) <= 1 and signal_fields < 3:
        return True
    if not specs and len(raw) < 200 and signal_fields < 3:
        return True
    return False


def _spec_lookup(specs: dict, *needles: str) -> tuple[Optional[str], Optional[str]]:
    # Iterate needles first so earlier needles win even if a later-matching
    # key appears earlier in dict insertion order (e.g. "Сертификати" before
    # "Сертификация 80 Plus").
    for needle in needles:
        for key, value in (specs or {}).items():
            if needle in str(key).lower():
                return str(key), str(value)
    return None, None


def _build_ai_source(specs: dict, raw: str) -> str:
    if specs:
        preferred = (
            "модел",
            "размер",
            "мощност",
            "ефектив",
            "сертифик",
            "80 plus",
            "модул",
            "кабел",
            "вентилатор",
            "гаранц",
            "pcie",
            "12vhpwr",
            "atx",
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


def _looks_like_sku(value: str | None, name: str | None) -> bool:
    """Manufacturer SKU-style token — reject as user-facing model.
    (a) no space, >=8 chars, >=30% digits;
    (b) hyphen-chain (>=3 hyphens + digit);
    (c) R-prefix pattern."""
    if not value or " " in value:
        return False
    if len(value) < 6:
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
    s = " ".join(s.split()).strip("- ,")
    if not s:
        s = raw.strip()
    if len(s) > 50:
        s = s[:50].rsplit(" ", 1)[0].strip(" -,")
    return s or None


def _extract_psu_data(name: str, specs: dict, raw: str, url: str) -> tuple[dict, set[str]]:
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

    size_key, size_val = _spec_lookup(specs, "физически размер", "форм фактор", "форм-фактор", "form factor")
    physical_size = _extract_physical_size(size_val, name, raw)
    if size_val and physical_size is not None:
        strong.add("physical_size")

    power_key, power_val = _spec_lookup(specs, "мощност")
    power_w = _extract_power_w(power_val, name, raw)
    if power_val and power_w is not None:
        strong.add("power_w")

    eff_key, eff_val = _spec_lookup(specs, "ефективност")
    efficiency = _normalize_efficiency(eff_val)
    if eff_val and efficiency is not None:
        strong.add("efficiency")

    cert_key, cert_val = _spec_lookup(specs, "сертификация 80 plus", "сертификати", "сертификат")
    certificate = _normalize_certificate(cert_val)
    if cert_val and certificate is not None:
        strong.add("certificate")

    mod_key, mod_val = _spec_lookup(specs, "модулен", "информация за кабела")
    modularity = _normalize_modularity(mod_val)
    if mod_val and modularity is not None:
        strong.add("modularity")

    fan_key, fan_val = _spec_lookup(specs, "размер на вентилатора", "охлаждане", "вентилатор")
    fan_size_mm = _normalize_fan_size_mm(fan_val)
    if fan_val and fan_size_mm is not None:
        strong.add("fan_size_mm")

    return {
        "brand": brand,
        "model": model,
        "physical_size": physical_size,
        "power_w": power_w,
        "efficiency": efficiency,
        "certificate": certificate,
        "modularity": modularity,
        "fan_size_mm": fan_size_mm,
    }, strong


def _merge_value(field: str, ai_value, det_value, strong_fields: set[str]):
    if field in strong_fields and det_value is not None:
        return det_value
    return ai_value if ai_value is not None else det_value


async def run_psu_pipeline(headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None):
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

        print(f"Opening {PSU_CATEGORY_URL}")
        await page.goto(PSU_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")
            urls = await collect_psu_urls(page)
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
            print(f"  -> New PSU products added: {len(all_urls) - before}")

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
        with open("psu_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_urls_list)} PSU links to psu_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\nProcessing collected PSU pages and inserting into DB...")
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
                parsed = parse_psu_page(html, url)
                name = parsed.get("name") or ""
                raw = parsed.get("raw_specs") or ""
                specs = parsed.get("specs") or {}

                if _is_accessory_or_non_psu(name, raw, str(specs)):
                    print(f"    Skipping non-PSU/accessory: {url}")
                    continue

                det, strong_fields = _extract_psu_data(name, specs, raw, url)

                try:
                    ai_source = _build_ai_source(specs, raw)
                    ai_data = parse_psu(ai_source, name, parsed.get("price", 0.0), url)
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
                            "Unrecognized PSU brand candidates for %s: %s",
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
                final["physical_size"] = _normalize_physical_size(
                    _merge_value("physical_size", ai_data.get("physical_size"), det.get("physical_size"), strong_fields)
                )
                final["power_w"] = _normalize_power_w(
                    _merge_value("power_w", ai_data.get("power_w"), det.get("power_w"), strong_fields)
                )
                final["efficiency"] = _normalize_efficiency(
                    _merge_value("efficiency", ai_data.get("efficiency"), det.get("efficiency"), strong_fields)
                )
                final["certificate"] = _normalize_certificate(
                    _merge_value("certificate", ai_data.get("certificate"), det.get("certificate"), strong_fields)
                )
                final["modularity"] = _normalize_modularity(
                    _merge_value("modularity", ai_data.get("modularity"), det.get("modularity"), strong_fields)
                )
                final["fan_size_mm"] = _normalize_fan_size_mm(
                    _merge_value("fan_size_mm", ai_data.get("fan_size_mm"), det.get("fan_size_mm"), strong_fields)
                )

                if not final.get("brand") or not final.get("model") or not final.get("power_w"):
                    print(f"    Skipping incomplete PSU record for {url}")
                    continue
                if (
                    parsed.get("brand_source") == "breadcrumb" or final.get("brand") is None
                ) and _is_low_signal_psu_page(parsed, det, final, strong_fields):
                    print(f"    Skipping low-signal PSU page for {url}")
                    continue

                final["price"] = parsed.get("price") if parsed.get("price") is not None else ai_data.get("price")
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_psu(final)
                    print(f"    Upserted: {final.get('model')}")
                except Exception as exc:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {exc}")

                processed += 1
            except Exception as exc:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {exc}")
