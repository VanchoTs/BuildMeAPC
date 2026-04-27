"""
Case Pipeline Module.

This module provides the scraping and normalization logic for computer cases
from the pic.bg retailer. It extracts data on physical dimensions, form factor
compatibility (ATX, ITX, etc.), internal clearance, and front panel I/O ports.
It integrates deterministic extraction with LLM-based parsing for robust data collection.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import CASE_CATEGORY_URL
from scrapers.pic_bg.case_page import parse_case_page
from ai.case_parser import parse_case
from ai.case_normalization import (
    normalize_case_brand,
    normalize_case_model,
    normalize_case_size,
    normalize_motherboard_form_factors,
    normalize_included_fans,
    normalize_max_mm,
    normalize_max_radiator_mm,
    normalize_io_json,
    _dedup_usb_ports,
    _apply_type_c_version_default,
)
from storage.case_repository import upsert_case

logger = logging.getLogger("case_pipeline")
if not logger.handlers:
    fh = logging.FileHandler(os.environ.get("SCRAPER_ERROR_LOG", "scraper_errors.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


async def _retry(coro_fn, *args, attempts: int = 3, delay: float = 1.0, **kwargs):
    """
    Generic retry wrapper for asynchronous functions.
    """
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
    """
    Attempts to click the cookie acceptance button on the retailer's page.
    """
    try:
        await page.click("button:has-text('Приемам')", timeout=4000)
        await asyncio.sleep(1)
    except Exception:
        pass


async def collect_case_urls(page) -> list[str]:
    """
    Collects all computer case product URLs from the current category page.
    Handles lazy-loading by scrolling down.
    """
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

    print(f"  -> Cases on page: {len(urls)}")
    return urls


async def get_next_page_button(page, current_page: int):
    """
    Locates and returns the button for the next page in the pagination.
    """
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
    """Wrapper for case brand normalization."""
    return normalize_case_brand(value)


def _infer_brand_from_text(*texts: str | None) -> Optional[str]:
    """Attempts to identify a case brand from a collection of raw strings."""
    joined = " ".join(str(t) for t in texts if t)
    return normalize_case_brand(joined)


def _normalize_model(value: str | None, brand: str | None = None) -> Optional[str]:
    """Wrapper for case model normalization, optionally using brand context."""
    return normalize_case_model(value, brand)


def _normalize_case_size(value: str | None) -> Optional[str]:
    """Wrapper for case size (e.g., Mid Tower) normalization."""
    return normalize_case_size(value)


def _normalize_motherboard_form_factors(value) -> Optional[list]:
    """Wrapper for motherboard compatibility normalization."""
    return normalize_motherboard_form_factors(value)


def _normalize_included_fans(value) -> Optional[int]:
    """Wrapper for included fan count normalization."""
    return normalize_included_fans(value)


def _normalize_max_mm(value) -> Optional[int]:
    """Wrapper for internal clearance (CPU/GPU/PSU) normalization in mm."""
    return normalize_max_mm(value)


def _normalize_max_radiator_mm(value) -> Optional[int]:
    """Wrapper for radiator support normalization."""
    return normalize_max_radiator_mm(value)


def _normalize_io_json(value, apply_type_c_default: bool = True) -> Optional[dict]:
    """Wrapper for front panel I/O port normalization into structured JSON."""
    return normalize_io_json(value, apply_type_c_default=apply_type_c_default)


def _looks_like_sku(value: str | None, name: str | None) -> bool:
    """
    Heuristic to identify Manufacturer SKU-style tokens.
    Rejected as user-facing models because they are often cryptic strings.
    """
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
    """
    Strips 'junk' words from a raw model string when better normalization fails.
    Ensures a reasonably clean fallback value.
    """
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


def _is_accessory_or_non_case(*texts: str | None) -> bool:
    """
    Filters out cables, lighting kits, vertical mounts, and other case accessories.
    Uses regex patterns to verify if the product is a primary computer case.
    """
    title = str(texts[0]) if texts else ""
    title_upper = title.upper()
    joined = " ".join(str(t) for t in texts if t).upper()

    has_strong_case_evidence = bool(
        re.search(r"\bMID(?:DLE)?\s+TOWER\b", joined)
        or re.search(r"\bFULL\s+TOWER\b", joined)
        or re.search(r"\bMINI\s+TOWER\b", joined)
        or re.search(r"\bSFF\b", joined)
        or re.search(r"\bATX\b", joined)
        or re.search(r"\bITX\b", joined)
        or re.search(r"\bM-?ATX\b", joined)
    )

    if re.search(r"\bPOWER\s+CORD\b", joined) or re.search(r"\bЗАХРАНВАЩ\s+КАБЕЛ\b", joined):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bUSB[-\s]?C?\s+CABLE\b", title_upper):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bКАБЕЛ\b", title_upper):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bSTANDOFF\b", joined) or re.search(r"\bDUST\s+FILTER\b", joined):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bFAN\s+CONTROLLER\b", joined) or re.search(r"\bКОНТРОЛЕР\b", joined):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bBRACKET\b", joined) or re.search(r"\bСКОБА\b", joined):
        if not has_strong_case_evidence:
            return True
    if (
        re.search(r"\bLIGHTING\s+KIT\b", joined)
        or re.search(r"\bARGB\s+KIT\b", joined)
        or re.search(r"\bRGB\s+KIT\b", joined)
    ):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bLED\s+STRIP\b", joined) or re.search(r"\bLED\s+KIT\b", joined):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bFAN\s+KIT\b", joined) or re.search(r"\bFAN\s+PACK\b", joined):
        if not has_strong_case_evidence:
            return True
    if re.search(r"\bPCI[-\s]?E(?:XPRESS)?\s+RISER\b", title_upper):
        return True
    if re.search(r"\bRISER\s+(?:CABLE|KIT|BRACKET|CARD)\b", title_upper):
        return True
    if re.search(r"\bRISER\b", title_upper) and not has_strong_case_evidence:
        return True
    if re.search(r"\bVERTICAL\s+(?:GPU|VGA|MOUNT)\b", title_upper):
        return True
    if re.search(r"\b(?:GPU|VGA)\s+(?:MOUNT|HOLDER|BRACKET)\b", title_upper):
        return True
    if re.search(r"\bFD[-\s]?A[-\s]?FLX\w*", title_upper):
        return True
    if re.search(r"\bFLEX\s*\d+\b", title_upper) and re.search(r"\bPCI[-\s]?E", title_upper):
        return True
    if re.search(r"\bPCI[-\s]?E(?:XPRESS)?\s+\d", title_upper) and not re.search(
        r"\b(?:MID|FULL|MINI)\s+TOWER\b|\bATX\b|\bITX\b|\bSFF\b", title_upper
    ):
        return True
    return False


_STRONG_CASE_FIELDS = (
    "case_size",
    "motherboard_form_factors",
    "included_fans",
    "max_cpu_cooler_mm",
    "max_gpu_length_mm",
    "max_psu_length_mm",
    "max_radiator_mm",
    "io_json",
)


def _is_low_signal_case_page(parsed: dict, det: dict, final: dict, strong_fields: set[str]) -> bool:
    """
    Determines if a page has enough data to be useful.
    Ensures that records have sufficient motherboard and dimension context.
    """
    populated = sum(1 for field in _STRONG_CASE_FIELDS if final.get(field) is not None)
    det_strong = sum(1 for field in _STRONG_CASE_FIELDS if field in strong_fields)
    if det_strong >= 3:
        return False
    if det_strong >= 2 and populated >= 3:
        return False
    return True


def _spec_lookup(specs: dict, *needles: str) -> tuple[Optional[str], Optional[str]]:
    """
    Searches a dictionary for keys containing specific substrings (needles).
    Returns the first matching key and value.
    """
    for needle in needles:
        for key, value in (specs or {}).items():
            if needle in str(key).lower():
                return str(key), str(value)
    return None, None


_FAN_BLOCKED_NEEDLES = (
    "максимален брой вентилатор",
    "макс. брой вентилатор",
    "max fan",
    "maximum fan",
)


def _build_ai_source(specs: dict, raw: str) -> str:
    """
    Constructs a condensed string of specifications for AI parsing input.
    Filters for relevant case keywords (dimensions, compatibility, ports).
    """
    if specs:
        preferred = (
            "размер",
            "формат",
            "форм фактор",
            "форм-фактор",
            "вид",
            "вентилатор",
            "охладител",
            "видеокарт",
            "захранван",
            "водно охлаждане",
            "радиатор",
            "портове",
            "интерфейс",
            "предни портове",
            "i/o",
            "front",
            "tower",
            "atx",
            "itx",
        )
        lines = [
            f"{k}: {v}"
            for k, v in specs.items()
            if any(p in str(k).lower() for p in preferred)
            and not any(b in str(k).lower() for b in _FAN_BLOCKED_NEEDLES)
        ]
        if not lines:
            lines = [
                f"{k}: {v}"
                for k, v in specs.items()
                if not any(b in str(k).lower() for b in _FAN_BLOCKED_NEEDLES)
            ]
        return "\n".join(lines)[:8000]
    return (raw or "")[:8000]


def _preprocess_io_value(value: str) -> str:
    """Cleans I/O port descriptions to improve extraction accuracy."""
    s = str(value)
    s = re.sub(r"(\d+)\s*[-\u2013\u2014]\s*(USB)", r"\1 x \2", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\(\s*type\s*([ac])\s*\)",
        lambda m: f" Type-{m.group(1).upper()}",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"(\d+)\s*\(\s*(USB[^)]*)\)", r"\1 \2", s, flags=re.IGNORECASE)
    return s


def _extract_io_json(specs: dict, raw: str) -> Optional[dict]:
    """
    Extracts structured I/O port data from multiple specification fields.
    Handles deduplication of ports and applies defaults (e.g., for Type-C).
    """
    all_ports: list[dict] = []
    audio: Optional[bool] = None
    consumed_keys: set[str] = set()

    def _consume(parsed: Optional[dict]) -> None:
        nonlocal audio
        if not parsed:
            return
        for port in parsed.get("usb_ports") or []:
            if not isinstance(port, dict):
                continue
            try:
                count = int(port.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                all_ports.append(port)
        if parsed.get("audio") is True:
            audio = True
        elif parsed.get("audio") is False and audio is None:
            audio = False

    for needle in ("портове", "предни портове", "front panel", "front i/o", "i/o", "интерфейс"):
        for key, value in (specs or {}).items():
            if key in consumed_keys:
                continue
            if needle in str(key).lower():
                _consume(_normalize_io_json(_preprocess_io_value(value), apply_type_c_default=False))
                consumed_keys.add(key)

    for key, value in (specs or {}).items():
        if key in consumed_keys:
            continue
        k_up = str(key).upper()
        v_up = str(value).upper()
        if "USB" in k_up or "USB" in v_up:
            _consume(_normalize_io_json(_preprocess_io_value(value), apply_type_c_default=False))
            consumed_keys.add(key)

    if not all_ports and audio is None:
        return _normalize_io_json(raw)

    deduped = _dedup_usb_ports(all_ports)
    deduped = [_apply_type_c_version_default(p) for p in deduped]
    return {"usb_ports": deduped, "audio": audio}


def _extract_case_data(name: str, specs: dict, raw: str, url: str) -> tuple[dict, set[str]]:
    """
    Extracts structured Case data using deterministic logic (regex, lookup tables).
    Returns the extracted data and a set of 'strong' fields that are high confidence.
    """
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

    size_key, size_val = _spec_lookup(specs, "физически размер", "форм фактор", "форм-фактор")
    case_size = _normalize_case_size(size_val)
    if size_val and case_size is not None:
        strong.add("case_size")

    mb_key, mb_val = _spec_lookup(specs, "формат", "вид")
    motherboard_form_factors = _normalize_motherboard_form_factors(mb_val)
    if mb_val and motherboard_form_factors is not None:
        strong.add("motherboard_form_factors")

    fan_specs = {
        k: v
        for k, v in (specs or {}).items()
        if not any(b in str(k).lower() for b in _FAN_BLOCKED_NEEDLES)
    }
    fans_key, fans_val = _spec_lookup(
        fan_specs, "брой на включените вентилатори", "включени вентилатори"
    )
    included_fans = _normalize_included_fans(fans_val)
    if fans_val and included_fans is not None:
        strong.add("included_fans")

    cpu_key, cpu_val = _spec_lookup(
        specs,
        "максимална височина на охладителя",
        "макс. размер охладител",
        "cpu cooler max height",
    )
    max_cpu_cooler_mm = _normalize_max_mm(cpu_val)
    if cpu_val and max_cpu_cooler_mm is not None:
        strong.add("max_cpu_cooler_mm")

    gpu_key, gpu_val = _spec_lookup(
        specs,
        "максимален размер на gpu",
        "макс. размер видеокарта",
        "vga max length",
    )
    max_gpu_length_mm = _normalize_max_mm(gpu_val)
    if gpu_val and max_gpu_length_mm is not None:
        strong.add("max_gpu_length_mm")

    psu_key, psu_val = _spec_lookup(
        specs,
        "максимален размер на захранването",
        "psu max length",
    )
    max_psu_length_mm = _normalize_max_mm(psu_val)
    if psu_val and max_psu_length_mm is not None:
        strong.add("max_psu_length_mm")

    rad_key, rad_val = _spec_lookup(
        specs,
        "място за водно охлаждане",
        "поддръжка на водно охлаждане",
    )
    max_radiator_mm = _normalize_max_radiator_mm(rad_val)
    if rad_val and max_radiator_mm is not None:
        strong.add("max_radiator_mm")

    io_json = _extract_io_json(specs, raw)
    if io_json is not None and (io_json.get("usb_ports") or io_json.get("audio") is not None):
        strong.add("io_json")

    return {
        "brand": brand,
        "model": model,
        "case_size": case_size,
        "motherboard_form_factors": motherboard_form_factors,
        "included_fans": included_fans,
        "max_cpu_cooler_mm": max_cpu_cooler_mm,
        "max_gpu_length_mm": max_gpu_length_mm,
        "max_psu_length_mm": max_psu_length_mm,
        "max_radiator_mm": max_radiator_mm,
        "io_json": io_json,
    }, strong


def _merge_value(field: str, ai_value, det_value, strong_fields: set[str]):
    """
    Merges data from AI parsing and deterministic extraction.
    Prioritizes deterministic values for 'strong' fields.
    """
    if field in strong_fields and det_value is not None:
        return det_value
    return ai_value if ai_value is not None else det_value


async def run_case_pipeline(headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None):
    """
    Main entry point for the Case scraper pipeline.
    1. Collects all product URLs from category pages.
    2. Navigates to product pages to extract structured specifications.
    3. Normalizes and merges extracted data.
    4. Upserts results into the database.
    """
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

        print(f"Opening {CASE_CATEGORY_URL}")
        await page.goto(CASE_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")
            urls = await collect_case_urls(page)
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
            print(f"  -> New case products added: {len(all_urls) - before}")

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
        with open("case_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_urls_list)} case links to case_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\nProcessing collected case pages and inserting into DB...")
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
                parsed = parse_case_page(html, url)
                name = parsed.get("name") or ""
                raw = parsed.get("raw_specs") or ""
                specs = parsed.get("specs") or {}

                if _is_accessory_or_non_case(name, raw, str(specs)):
                    print(f"    Skipping non-case/accessory: {url}")
                    continue

                det, strong_fields = _extract_case_data(name, specs, raw, url)

                try:
                    ai_source = _build_ai_source(specs, raw)
                    ai_data = parse_case(ai_source, name, parsed.get("price", 0.0), url)
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
                            "Unrecognized case brand candidates for %s: %s",
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
                final["case_size"] = _normalize_case_size(
                    _merge_value("case_size", ai_data.get("case_size"), det.get("case_size"), strong_fields)
                )
                final["motherboard_form_factors"] = _normalize_motherboard_form_factors(
                    _merge_value(
                        "motherboard_form_factors",
                        ai_data.get("motherboard_form_factors"),
                        det.get("motherboard_form_factors"),
                        strong_fields,
                    )
                )
                final["included_fans"] = _normalize_included_fans(
                    _merge_value("included_fans", ai_data.get("included_fans"), det.get("included_fans"), strong_fields)
                )
                final["max_cpu_cooler_mm"] = _normalize_max_mm(
                    _merge_value(
                        "max_cpu_cooler_mm",
                        ai_data.get("max_cpu_cooler_mm"),
                        det.get("max_cpu_cooler_mm"),
                        strong_fields,
                    )
                )
                final["max_gpu_length_mm"] = _normalize_max_mm(
                    _merge_value(
                        "max_gpu_length_mm",
                        ai_data.get("max_gpu_length_mm"),
                        det.get("max_gpu_length_mm"),
                        strong_fields,
                    )
                )
                final["max_psu_length_mm"] = _normalize_max_mm(
                    _merge_value(
                        "max_psu_length_mm",
                        ai_data.get("max_psu_length_mm"),
                        det.get("max_psu_length_mm"),
                        strong_fields,
                    )
                )
                final["max_radiator_mm"] = _normalize_max_radiator_mm(
                    _merge_value(
                        "max_radiator_mm",
                        ai_data.get("max_radiator_mm"),
                        det.get("max_radiator_mm"),
                        strong_fields,
                    )
                )
                final["io_json"] = _normalize_io_json(
                    _merge_value("io_json", ai_data.get("io_json"), det.get("io_json"), strong_fields)
                )

                if "included_fans" not in strong_fields and final.get("included_fans") is not None:
                    if final["included_fans"] > 6:
                        final["included_fans"] = None

                io_final = final.get("io_json")
                if isinstance(io_final, dict):
                    usb_ports = io_final.get("usb_ports") or []
                    audio = io_final.get("audio")
                    if not usb_ports and audio is None:
                        final["io_json"] = None

                if not final.get("brand") or not final.get("model") or not (
                    final.get("case_size") or final.get("motherboard_form_factors")
                ):
                    print(f"    Skipping incomplete case record for {url}")
                    continue
                if _is_low_signal_case_page(parsed, det, final, strong_fields):
                    print(f"    Skipping low-signal case page for {url}")
                    continue

                final["price"] = parsed.get("price") if parsed.get("price") is not None else ai_data.get("price")
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_case(final)
                    print(f"    Upserted: {final.get('model')}")
                except Exception as exc:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {exc}")

                processed += 1
            except Exception as exc:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {exc}")
