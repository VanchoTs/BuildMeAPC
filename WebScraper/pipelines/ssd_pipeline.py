import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import SSD_CATEGORY_URL
from scrapers.pic_bg.ssd_page import parse_ssd_page
from ai.ssd_parser import parse_ssd
from storage.ssd_repository import upsert_ssd

logger = logging.getLogger("ssd_pipeline")
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
        except Exception as e:
            last_exc = e
            logger.warning(
                "Attempt %d failed for %s: %s",
                attempt,
                getattr(coro_fn, "__name__", str(coro_fn)),
                e,
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


async def collect_ssd_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href^='/ssd']")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if href:
            full = "https://www.pic.bg" + href if href.startswith("/") else href
            if full not in urls:
                urls.append(full)

    print(f"  -> SSDs on page: {len(urls)}")
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


def _clean_str(value: str | None) -> Optional[str]:
    if value is None:
        return None
    s = " ".join(str(value).replace("™", "").replace("®", "").split()).strip()
    if not s or s.upper() in ("NULL", "NONE", "N/A", "UNKNOWN"):
        return None
    return s


def _normalize_brand(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    brand_map = {
        "SAMSUNG": "Samsung",
        "CRUCIAL": "Crucial",
        "KINGSTON": "Kingston",
        "WD": "WD",
        "WESTERN DIGITAL": "WD",
        "ADATA": "ADATA",
        "XPG": "ADATA",
        "APACER": "Apacer",
        "MICRON": "Micron",
        "TEAMGROUP": "TeamGroup",
        "TEAM GROUP": "TeamGroup",
        "TEAM": "TeamGroup",
        "SILICON POWER": "Silicon Power",
        "LEXAR": "Lexar",
        "GIGABYTE": "GIGABYTE",
        "VERBATIM": "Verbatim",
        "KIOXIA": "Kioxia",
        "SEAGATE": "Seagate",
        "INTEL": "Intel",
        "CORSAIR": "Corsair",
        "PATRIOT": "Patriot",
        "GOODRAM": "Goodram",
        "SK HYNIX": "SK hynix",
        "HYNIX": "SK hynix",
        "MSI": "MSI",
        "HP": "HP",
        "SYNOLOGY": "Synology",
    }
    for token, normalized in brand_map.items():
        if token in upper:
            return normalized
    return None


def _infer_brand_from_text(*texts: str | None) -> Optional[str]:
    joined = " ".join(str(t) for t in texts if t)
    return _normalize_brand(joined)


def _normalize_model(value: str | None, brand: str | None = None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    if brand:
        s = re.sub(re.escape(brand), "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"(?i)^SSD\s*", "", s).strip()
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\b\d+(?:[\.,]\d+)?\s*TB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+(?:[\.,]\d+)?\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bREAD\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bWRITE\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(PCIE|PCIE|NVME|M\.2|SATA(?:\s*III)?|SSD)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(2230|2242|2260|2280|22110|2\.5\"|2\.5INCH|2\.5)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bGEN\s*[345]\b", "", s, flags=re.IGNORECASE)
    s = " ".join(s.split()).strip("- ,")
    return s or None


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value).replace(" ", ""))
    if m:
        return int(m.group(0))
    return None


def _normalize_storage_size_gb(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v if 32 <= v <= 16000 else None
    s = str(value).upper().replace(" ", "")
    m = re.search(r"(\d+(?:[\.,]\d+)?)TB", s)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1000)
    m = re.search(r"(\d{2,5})GB", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\((\d+(?:[\.,]\d+)?)TB\)", s)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1000)
    if re.fullmatch(r"\d{2,5}", s):
        v = int(s)
        return v if 32 <= v <= 16000 else None
    return None


def _extract_storage_size_gb(*texts: str | None) -> Optional[int]:
    for text in texts:
        v = _normalize_storage_size_gb(text)
        if v is not None:
            return v
    return None


def _normalize_physical_size(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper().replace(" ", "")
    if "MSATA" in upper:
        return "mSATA"
    m = re.search(r"M\.2\(?([0-9]{4,5})\)?", upper)
    if m:
        return m.group(1)
    m = re.search(r"\b(2230|2242|2260|2280|22110)\b", upper)
    if m:
        return m.group(1)
    m = re.search(r"22X(30|42|60|80|110)", upper)
    if m:
        return f"22{m.group(1)}"
    if any(token in upper for token in ('2.5"', '2.5INCH', '2,5"', '2.5')):
        return '2.5"'
    return None


def _extract_physical_size(*texts: str | None) -> Optional[str]:
    for text in texts:
        v = _normalize_physical_size(text)
        if v is not None:
            return v
    return None


def _normalize_interface(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper().replace(",", " ")
    upper = re.sub(r"\s+", " ", upper)
    if upper == "SATA":
        return "SATA"
    if upper == "PCIE":
        return "PCIe"
    if "MSATA" in upper:
        return "SATA III 6Gb/s"
    if "SATA" in upper and "PCIE" not in upper and "PCI EXPRESS" not in upper:
        return "SATA III 6Gb/s"
    gen_match = re.search(r"(?:PCIE|PCI-E|PCI EXPRESS)(?:\s+NVME)?(?:\s+GEN)?\s*([345])(?:\.0)?", upper)
    if not gen_match:
        gen_match = re.search(r"GEN\s*([345])(?:\.0)?", upper)
    lane_match = re.search(r"X\s*([1248])\b", upper)
    if gen_match:
        gen = gen_match.group(1)
        lane = lane_match.group(1) if lane_match else "4"
        return f"PCIe Gen {gen} x{lane}"
    return None


def _extract_interface(*texts: str | None) -> Optional[str]:
    for text in texts:
        v = _normalize_interface(text)
        if v is not None:
            return v
    return None


def _normalize_speed_mbps(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v if 50 <= v <= 200000 else None
    s = str(value).upper().replace(" ", "")
    m = re.search(r"(\d{2,6})(?:MB/S|MBS|MBPS)", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{2,6})\b", s)
    if m:
        v = int(m.group(1))
        return v if 50 <= v <= 200000 else None
    return None


def _extract_speed_mbps(*texts: str | None) -> Optional[int]:
    for text in texts:
        v = _normalize_speed_mbps(text)
        if v is not None:
            return v
    return None


def _normalize_tbw_tb(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v if 1 <= v <= 100000 else None

    def _parse_tbw_number(token: str) -> Optional[float]:
        token = token.strip()
        if not token:
            return None
        try:
            if re.fullmatch(r"\d{1,3}(?:[\.,]\d{3})+", token):
                return float(re.sub(r"[\.,]", "", token))
            return float(token.replace(",", "."))
        except ValueError:
            return None

    def _to_tb(match: re.Match[str]) -> Optional[int]:
        parsed = _parse_tbw_number(match.group("value"))
        if parsed is None:
            return None
        unit = match.group("unit").upper()
        if unit == "PB":
            return int(round(parsed * 1000))
        return int(parsed)

    s = str(value).upper()
    compact = re.sub(r"\s+", "", s)
    tbw_patterns = (
        r"TBW[^0-9]{0,10}(?P<value>\d[\d\.,]*)\s*(?P<unit>PB|TB)\b",
        r"(?P<value>\d[\d\.,]*)\s*(?P<unit>PB|TB)W\b",
    )
    for pattern in tbw_patterns:
        m = re.search(pattern, compact)
        if m:
            tbw_value = _to_tb(m)
            if tbw_value is not None:
                return tbw_value

    m = re.search(r"(?P<value>\d[\d\.,]*)\s*(?P<unit>PB|TB)\b", compact)
    if m:
        tbw_value = _to_tb(m)
        if tbw_value is not None:
            return tbw_value
    return None


def _extract_tbw_tb(*texts: str | None) -> Optional[int]:
    for text in texts:
        v = _normalize_tbw_tb(text)
        if v is not None:
            return v
    return None


def _normalize_nand_type(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    canonical = re.sub(r"[\s_-]+", " ", upper).strip()
    if canonical in {"NULL", "NONE", "N/A", "UNKNOWN", "UNSPECIFIED"}:
        return None
    if ("SAMSUNG" in canonical and "V NAND" in canonical) or canonical == "V NAND":
        return "V-NAND"
    if re.search(r"\bMLC\b", canonical) or "MULTI LEVEL CELL" in canonical:
        return "MLC"
    if re.search(r"\bQLC\b", canonical) or "QUAD LEVEL CELL" in canonical:
        return "QLC"
    if re.search(r"\bSLC\b", canonical) or "SINGLE LEVEL CELL" in canonical:
        return "SLC"
    if re.search(r"\bTLC\b", canonical) or "TRIPLE LEVEL CELL" in canonical:
        return "TLC"
    if re.fullmatch(r"3D NAND(?: FLASH)?", canonical) or canonical == "NAND FLASH":
        return "NAND"
    placeholder_tokens = set(canonical.replace("PCI EXPRESS", "PCIE").split())
    if placeholder_tokens and placeholder_tokens.issubset({"NVME", "M.2", "M2", "PCIE", "SATA", "SSD"}):
        return None
    if "NVME" in canonical and ("M.2" in upper or re.search(r"\bM2\b", canonical)):
        return None
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 80:
        s = s[:80].rstrip()
    return s or None


def _normalize_has_heatsink(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).upper()
    if any(token in s for token in ("HEATSINK", "HEAT SINK", "ОХЛАДИТЕЛ", "РАДИАТОР")):
        return True
    return None


def _normalize_type(value: str | None, *, physical_size: str | None = None, interface: str | None = None) -> Optional[str]:
    s = _clean_str(value)
    upper = s.upper() if s else ""
    if physical_size in {"2230", "2242", "2260", "2280", "22110"}:
        return "M.2"
    if physical_size == "mSATA":
        return "SATA"
    if "M.2" in upper or "NVME" in upper or re.search(r"\b(2230|2242|2260|2280|22110)\b", upper):
        return "M.2"
    if "MSATA" in upper:
        return "SATA"
    if "SATA" in upper or physical_size == '2.5"':
        return "SATA"
    if interface in ("SATA III 6Gb/s", "SATA"):
        return "SATA"
    if interface and (interface.startswith("PCIe Gen") or interface == "PCIe"):
        return "M.2"
    return None


def _normalize_internal_external_status(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if re.search(r"ВЪТРЕШЕН\s*/\s*ВЪНШЕН\s*[:=-]\s*ВЪТРЕШЕН", upper):
        return "internal"
    if re.search(r"ВЪТРЕШЕН\s*/\s*ВЪНШЕН\s*[:=-]\s*ВЪНШЕН", upper):
        return "external"
    if re.search(r"INTERNAL\s*/\s*EXTERNAL\s*[:=-]\s*INTERNAL", upper):
        return "internal"
    if re.search(r"INTERNAL\s*/\s*EXTERNAL\s*[:=-]\s*EXTERNAL", upper):
        return "external"
    if re.fullmatch(r"(?:ВЪТРЕШЕН|INTERNAL)", upper):
        return "internal"
    if re.fullmatch(r"(?:ВЪНШЕН|EXTERNAL|PORTABLE)", upper):
        return "external"
    return None


def _is_external_drive(*texts: str | None) -> bool:
    statuses = [_normalize_internal_external_status(t) for t in texts if t is not None]
    if "internal" in statuses:
        return False
    if "external" in statuses:
        return True

    joined = " ".join(str(t) for t in texts if t)
    joined_upper = joined.upper()
    scrubbed = re.sub(
        r"(?:ВЪТРЕШЕН\s*/\s*ВЪНШЕН|INTERNAL\s*/\s*EXTERNAL)",
        " ",
        joined_upper,
    )
    if re.search(r"\b(ENCLOSURE|ADAPTER|BRACKET|CADDY|DOCK)\b", scrubbed):
        return True
    if re.search(r"\b(EXTERNAL|PORTABLE)\b", scrubbed):
        return True
    if re.search(r"\b(USB\s*3|USB-C|TYPE-C|THUNDERBOLT)\b", scrubbed) and re.search(
        r"\bSSD\b", scrubbed
    ):
        return True
    return False


def _is_accessory_or_non_ssd(*texts: str | None) -> bool:
    joined = " ".join(str(t) for t in texts if t).upper()
    if re.search(r"\b(HDD|HARD\s*DISK|ХАРД\s*ДИСК|МЕХАНИЧЕН\s*ДИСК)\b", joined):
        return True
    if re.search(r"\b(ENCLOSURE|BRACKET|ADAPTER|CADDY|DOCK|КУТИЯ|АДАПТЕР|СКОБА|ПРЕХОДНИК)\b", joined):
        return True
    if re.search(r"\bHEATSINK\b|\bHEAT\s*SINK\b|ОХЛАДИТЕЛ|РАДИАТОР", joined):
        has_ssd_evidence = bool(
            re.search(r"\bSSD\b|\bNVME\b|\bM\.2\b|\bSATA\b|\bPCIE\b|\bPCIE\b", joined)
            and re.search(r"\b\d+(?:[\.,]\d+)?\s*(TB|GB)\b", joined)
        )
        if not has_ssd_evidence:
            return True
    return False


def _is_low_signal_ssd_page(
    parsed: dict,
    det: dict,
    final: dict,
    strong_fields: set[str],
) -> bool:
    specs = parsed.get("specs") or {}
    raw = parsed.get("raw_specs") or ""
    signal_fields = sum(
        1
        for field in (
            "type",
            "storage_size_gb",
            "physical_size",
            "interface",
            "read_speed_mbps",
            "write_speed_mbps",
            "tbw_tb",
            "nand_type",
        )
        if final.get(field) is not None or det.get(field) is not None
    )
    model = final.get("model") or det.get("model") or parsed.get("model") or ""
    has_specs_signal = bool(specs) and any(
        key in strong_fields
        for key in (
            "storage_size_gb",
            "physical_size",
            "interface",
            "read_speed_mbps",
            "write_speed_mbps",
            "tbw_tb",
            "nand_type",
        )
    )
    if has_specs_signal:
        return False
    if len(model) > 120 and signal_fields < 5:
        return True
    if len(specs) <= 1 and signal_fields < 4:
        return True
    if not specs and len(raw) < 200 and signal_fields < 4:
        return True
    return False


def _spec_lookup(specs: dict, *needles: str) -> tuple[Optional[str], Optional[str]]:
    for key, value in (specs or {}).items():
        key_s = str(key)
        key_l = key_s.lower()
        if any(n in key_l for n in needles):
            return key_s, str(value)
    return None, None


def _build_ai_source(specs: dict, raw: str) -> str:
    if specs:
        preferred = (
            "размер",
            "физически",
            "форм",
            "интерф",
            "четене",
            "запис",
            "последов",
            "tbw",
            "терабайти",
            "тип",
            "nand",
            "вътрешен",
            "series",
            "серия",
        )
        lines = [
            f"{k}: {v}"
            for k, v in specs.items()
            if any(p in str(k).lower() for p in preferred)
        ]
        if not lines:
            lines = [f"{k}: {v}" for k, v in specs.items()]
        ai_source = "\n".join(lines)
        return ai_source[:8000]
    return (raw or "")[:8000]


def _extract_ssd_data(name: str, specs: dict, raw: str, url: str) -> tuple[dict, set[str]]:
    strong = set()

    brand = _infer_brand_from_text(name, raw)
    series_key, series_val = _spec_lookup(specs, "серия ssd", "серия")
    model = _normalize_model(series_val or name, brand)
    if series_val:
        strong.add("model")

    size_key, size_val = _spec_lookup(specs, "размер")
    storage_size_gb = _extract_storage_size_gb(size_val, name, raw, url)
    if size_val:
        strong.add("storage_size_gb")

    phys_key, phys_val = _spec_lookup(specs, "физически размер", "форм фактор", "съвместим отсек", "размери")
    physical_size = _extract_physical_size(phys_val, name, raw)
    if phys_key and physical_size is not None:
        strong.add("physical_size")

    iface_key, iface_val = _spec_lookup(specs, "интерфейс")
    interface = _extract_interface(iface_val, name, raw)
    if iface_val:
        strong.add("interface")

    read_key, read_val = _spec_lookup(specs, "скорост на четене", "последователно четене")
    read_speed_mbps = _extract_speed_mbps(read_val)
    if read_val:
        strong.add("read_speed_mbps")

    write_key, write_val = _spec_lookup(specs, "скорост на запис", "последователен запис", "последователно запис")
    write_speed_mbps = _extract_speed_mbps(write_val)
    if write_val:
        strong.add("write_speed_mbps")

    internal_key, internal_val = _spec_lookup(specs, "вътрешен/външен")

    tbw_key, tbw_val = _spec_lookup(specs, "tbw", "общо записани терабайти")
    tbw_tb = _extract_tbw_tb(tbw_val)
    if tbw_val:
        strong.add("tbw_tb")

    nand_key, nand_val = _spec_lookup(specs, "тип флаш памет", "тип на паметта", "тип памет")
    nand_type = _normalize_nand_type(nand_val)
    if nand_val:
        strong.add("nand_type")

    has_heatsink = _normalize_has_heatsink(f"{name} {raw}")
    if has_heatsink is not None:
        strong.add("has_heatsink")

    det_type = _normalize_type(
        f"{name} {phys_val or ''} {iface_val or ''} {raw}",
        physical_size=physical_size,
        interface=interface,
    )
    if det_type is not None:
        strong.add("type")

    return {
        "brand": brand,
        "model": model,
        "type": det_type,
        "storage_size_gb": storage_size_gb,
        "physical_size": physical_size,
        "read_speed_mbps": read_speed_mbps,
        "write_speed_mbps": write_speed_mbps,
        "interface": interface,
        "tbw_tb": tbw_tb,
        "nand_type": nand_type,
        "has_heatsink": has_heatsink,
        "internal_external": internal_val,
    }, strong


def _merge_value(field: str, ai_value, det_value, strong_fields: set[str]):
    if field in strong_fields and det_value is not None:
        return det_value
    return ai_value if ai_value is not None else det_value


async def run_ssd_pipeline(
    headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None
):
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

        print(f"Opening {SSD_CATEGORY_URL}")
        await page.goto(SSD_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")
            urls = await collect_ssd_urls(page)
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
            print(f"  -> New SSD products added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("No enabled next page button, stopping.")
                break

            print(f"Clicking page {current_page + 1}")
            await next_button.click()
            try:
                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href^='/ssd']");
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
        with open("ssd_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_urls_list)} SSD links to ssd_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\nProcessing collected SSD pages and inserting into DB...")
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
                parsed = parse_ssd_page(html, url)
                name = parsed.get("name") or ""
                raw = parsed.get("raw_specs") or ""
                specs = parsed.get("specs") or {}

                if _is_external_drive(name, raw, specs.get("Вътрешен/Външен")):
                    print(f"    Skipping external SSD/accessory: {url}")
                    continue
                if _is_accessory_or_non_ssd(name, raw, str(specs)):
                    print(f"    Skipping non-SSD/accessory: {url}")
                    continue

                det, strong_fields = _extract_ssd_data(name, specs, raw, url)
                if det.get("internal_external") and "ВЪНШЕН" in str(det["internal_external"]).upper():
                    print(f"    Skipping non-internal device: {url}")
                    continue

                try:
                    ai_source = _build_ai_source(specs, raw)
                    ai_data = parse_ssd(ai_source, name, parsed.get("price", 0.0), url)
                except Exception as e:
                    logger.exception("AI parsing failed for %s", url)
                    print(f"    AI parse error for {url}: {e}")
                    ai_data = {}

                final = {}
                final["brand"] = (
                    _normalize_brand(parsed.get("brand"))
                    or _normalize_brand(det.get("brand"))
                    or _normalize_brand(ai_data.get("brand"))
                    or _infer_brand_from_text(name, raw)
                )

                final["model"] = _normalize_model(
                    _merge_value("model", ai_data.get("model"), det.get("model"), strong_fields)
                    or parsed.get("model")
                    or name,
                    final.get("brand"),
                )
                final["storage_size_gb"] = _normalize_storage_size_gb(
                    _merge_value(
                        "storage_size_gb",
                        ai_data.get("storage_size_gb"),
                        det.get("storage_size_gb"),
                        strong_fields,
                    )
                )
                final["physical_size"] = _normalize_physical_size(
                    _merge_value(
                        "physical_size",
                        ai_data.get("physical_size"),
                        det.get("physical_size"),
                        strong_fields,
                    )
                )
                final["interface"] = _normalize_interface(
                    _merge_value(
                        "interface",
                        ai_data.get("interface"),
                        det.get("interface"),
                        strong_fields,
                    )
                )
                final["type"] = _normalize_type(
                    det.get("type") or ai_data.get("type"),
                    physical_size=final.get("physical_size"),
                    interface=final.get("interface"),
                )
                if final.get("interface") is None:
                    if final.get("type") == "M.2":
                        final["interface"] = "PCIe"
                    elif final.get("type") == "SATA":
                        final["interface"] = "SATA"
                final["read_speed_mbps"] = _normalize_speed_mbps(
                    _merge_value(
                        "read_speed_mbps",
                        ai_data.get("read_speed_mbps"),
                        det.get("read_speed_mbps"),
                        strong_fields,
                    )
                )
                final["write_speed_mbps"] = _normalize_speed_mbps(
                    _merge_value(
                        "write_speed_mbps",
                        ai_data.get("write_speed_mbps"),
                        det.get("write_speed_mbps"),
                        strong_fields,
                    )
                )
                final["tbw_tb"] = _normalize_tbw_tb(
                    _merge_value("tbw_tb", ai_data.get("tbw_tb"), det.get("tbw_tb"), strong_fields)
                )
                final["nand_type"] = _normalize_nand_type(
                    _merge_value("nand_type", ai_data.get("nand_type"), det.get("nand_type"), strong_fields)
                )
                final["has_heatsink"] = _merge_value(
                    "has_heatsink",
                    _normalize_has_heatsink(ai_data.get("has_heatsink")),
                    det.get("has_heatsink"),
                    strong_fields,
                )

                if final.get("type") not in ("M.2", "SATA"):
                    print(f"    Skipping unsupported SSD type for {url}: {final.get('type')}")
                    continue
                if final.get("interface") is None:
                    print(f"    Skipping SSD with unknown interface for {url}")
                    continue
                if not final.get("model") or not final.get("storage_size_gb"):
                    print(f"    Skipping incomplete SSD record for {url}")
                    continue
                if (
                    parsed.get("brand_source") == "breadcrumb" or final.get("brand") is None
                ) and _is_low_signal_ssd_page(parsed, det, final, strong_fields):
                    print(f"    Skipping low-signal SSD page for {url}")
                    continue
                if final.get("has_heatsink") is True and not (
                    final.get("storage_size_gb") and final.get("type") and final.get("interface")
                ):
                    print(f"    Skipping likely heatsink-only accessory for {url}")
                    continue

                final["price"] = parsed.get("price") if parsed.get("price") is not None else ai_data.get("price")
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_ssd(final)
                    print(f"    Upserted: {final.get('model')}")
                except Exception as e:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {e}")

                processed += 1
            except Exception as e:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {e}")
