import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import MOTHERBOARD_CATEGORY_URL
from scrapers.pic_bg.motherboard_page import parse_motherboard_page
from ai.motherboard_parser import parse_motherboard
from ai.llm_utils import LLMConfigurationError
from storage.motherboard_repository import (
    upsert_motherboard,
    get_common_socket_for_chipset,
    get_dominant_memory_type_for_chipset,
)

logger = logging.getLogger("motherboard_pipeline")
if not logger.handlers:
    fh = logging.FileHandler(os.environ.get("SCRAPER_ERROR_LOG", "scraper_errors.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


_MAX_PCIE_SLOT_COUNT = 16


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


async def collect_motherboard_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href]")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if not href:
            continue
        href_l = href.lower()
        if "plat" not in href_l:
            continue
        if "/c/" in href_l:
            continue
        if href.startswith("http"):
            urls.append(href)
        else:
            urls.append("https://www.pic.bg" + href)

    print(f"  -> Motherboards on page: {len(urls)}")
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
    if not value:
        return None
    s = str(value).strip()
    upper = s.upper()
    if any(
        x in upper
        for x in (
            "SOUP.FIND",
            "RE.SEARCH",
            "FIND(",
            "PATTERN",
            "TITLE.SPLIT",
            "TITLE[",
            "SPLIT()[0",
        )
    ):
        return None
    if re.search(r"[\[\]{}]", s):
        return None
    if upper in ("UNKNOWN", "N/A", "NONE", "NULL"):
        return None
    if "ASUS" in upper:
        return "ASUS"
    if "ASROCK" in upper:
        return "ASRock"
    if "MSI" in upper:
        return "MSI"
    if "GIGABYTE" in upper:
        return "GIGABYTE"
    if upper in ("GB", "G.B", "GIGA", "GIGA BYTE") or upper.startswith("GB "):
        return "GIGABYTE"
    if "BIOSTAR" in upper:
        return "Biostar"
    if "SAPPHIRE" in upper:
        return "Sapphire"
    if "SUPERMICRO" in upper:
        return "Supermicro"
    if "NZXT" in upper:
        return "NZXT"
    if upper == "INTEL":
        return "Intel"
    return None


def _normalize_model(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    upper = s.upper()
    if any(x in upper for x in ("SOUP.FIND", "RE.SEARCH", "FIND(", "PATTERN")):
        return None
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"(?i)дънна\s*платка|dynna\s*platka|motherboard|mainboard", "", s)
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def _normalize_form_factor(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    upper = s.upper()
    if any(x in upper for x in ("SOUP.FIND", "RE.SEARCH", "FIND(", "PATTERN")):
        return None
    if upper in ("UNKNOWN", "N/A", "NONE", "NULL", "NOT PRESENT", "NOT AVAILABLE"):
        return None
    s = upper
    if re.search(r"\b(?:SSI[- ]?)?EEB\b", s):
        return "EEB"
    if "E-ATX" in s:
        return "E-ATX"
    if "XL-ATX" in s:
        return "XL-ATX"
    if "MICRO" in s and "ATX" in s:
        return "mATX"
    if "M-ATX" in s or "MATX" in s:
        return "mATX"
    if "MINI" in s and "ITX" in s:
        return "ITX"
    if "ITX" in s:
        return "ITX"
    if "ATX" in s:
        return "ATX"
    return None


def _normalize_socket(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if re.search(r"\bID\s*:\s*\d{4,}\b", s):
        return None
    if any(
        x in s
        for x in (
            "RE.SEARCH",
            "SOUP.FIND",
            "FIND(",
            "PATTERN",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
        )
    ):
        return None
    if "AMD *" in s or s in (
        "NOT PRESENT",
        "NOT AVAILABLE",
        "N/A",
        "NONE",
        "NULL",
        "UNKNOWN",
        "AMD",
        "INTEL",
        "SOCKET",
        "CPU",
        "CHIPSET",
    ):
        return None
    if any(x in s for x in ("REALTEK", "ALC", "RTL", "I225", "I226")):
        return None
    if re.fullmatch(
        r"(?:[ABHQXZCW]\d{2,4}[A-Z]{0,2}|TRX\d{2,3}|WRX\d{2,3}|X\d{2,4}[A-Z]{0,1}|W\d{2,4})",
        s,
    ):
        return None
    if re.fullmatch(r"(AMD|INTEL)\s+[ABHXZCW]\d{3,4}", s):
        return None
    m = re.fullmatch(r"(\d{3,5})", s)
    if m:
        return f"LGA {m.group(1)}"
    s = s.replace("FCLGA", "LGA ").replace("LGA", "LGA ")
    s = re.sub(r"\s+", " ", s).strip()
    if "STRX4" in s or "STR 5" in s or "STR5" in s:
        return "sTR5"
    m = re.search(r"LGA\s*(\d{3,5})", s)
    if m:
        return f"LGA {m.group(1)}"
    m = re.search(r"SOCKET\s*(\d{3,5})", s)
    if m:
        return f"LGA {m.group(1)}"
    m = re.search(r"\b(\d{3,5})\b", s)
    if m and len(s) <= 32:
        return f"LGA {m.group(1)}"
    m = re.search(r"\b(AM[345]|TR4)\b", s)
    if m:
        return m.group(1)
    m = re.search(r"\bS?TR5\b", s)
    if m:
        return "sTR5"
    return None


def _normalize_memory_type(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    found = []
    for t in re.findall(r"DDR[3-5]", s):
        if t not in found:
            found.append(t)
    if not found:
        return None
    return "/".join(found)


def _resolve_memory_type(
    memory_candidates,
    chipset: str | None,
    chipset_memory_lookup=get_dominant_memory_type_for_chipset,
) -> Optional[str]:
    for value in memory_candidates:
        normalized = _normalize_memory_type(value)
        if normalized is not None:
            return normalized
    if not chipset:
        return None
    return _normalize_memory_type(chipset_memory_lookup(chipset))


def _normalize_chipset(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if s in ("CHIPSET", "SOCKET", "CPU", "MB", "MOTHERBOARD"):
        return None
    if any(x in s for x in ("REALTEK", "ALC", "RTL", "I225", "I226")):
        return None
    if any(x in s for x in ("SOUP.FIND", "RE.SEARCH", "PATTERN", "FIND(")):
        return None
    s = s.replace("INTEL", " ").replace("AMD", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if re.fullmatch(r"X(?:1|4|8|16|32)", s):
        return None
    if s in ("CHIPSET", "SOCKET", "CPU", "MB", "MOTHERBOARD"):
        return None
    m = re.search(r"\b(TRX\d{2,3}|WRX\d{2,3})\b", s)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([ABHQXZCW]\d{2,4})([A-Z]{0,2})\b", s)
    if m:
        base = m.group(1).upper()
        suffix = (m.group(2) or "").upper()
        # Preserve only chipset suffixes that are real (e.g. X670E/B650E), drop board-form/model suffixes.
        if suffix == "E" and base[0] in {"A", "B", "X"}:
            return f"{base}E"
        return base
    return None


def _correct_chipset_alias(
    chipset: str | None,
    model: str | None,
    name: str | None,
    url: str | None,
    socket: str | None = None,
    memory_type: str | None = None,
) -> Optional[str]:
    if not chipset:
        return chipset
    c = str(chipset).upper().strip()
    if c == "H61":
        return "H610"
    context = " ".join(
        [str(x) for x in (model, name, url, socket, memory_type) if x]
    ).upper()
    has_modern_context = bool(
        re.search(
            r"\b(?:AM5|DDR5|B850[A-Z0-9-]*|X870E?[A-Z0-9-]*|RYZEN(?:™)?\s*(?:7000|8000|9000)|RYZEN(?:™)?\s*[579]\b)\b",
            context,
        )
    )
    if has_modern_context and c == "B85":
        return "B850"
    if has_modern_context and c == "X87":
        return "X870E"
    return chipset


def _extract_chipset_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    upper = str(text).upper()
    # Prefer explicit chipset class patterns and ignore LAN/audio/controller tokens.
    for pat in (
        r"\b([ABHQXZCW]\d{2,4}[A-Z]{0,2})\b",
        r"\b([ABHXZ]\d{2,4})\b",
        r"\b(TRX\d{2,3})\b",
        r"\b(WRX\d{2,3})\b",
        r"\b(W\d{3,4})\b",
        r"\b(C\d{3,4})\b",
        r"\b(X\d{3,4})\b",
    ):
        m = re.search(pat, upper)
        if m:
            return _normalize_chipset(m.group(1))
    return None


def _infer_brand(model: str | None, name: str | None, url: str | None) -> Optional[str]:
    pool = " ".join([str(x) for x in (model, name, url) if x]).upper()
    if "GIGABYTE" in pool or "-GIGABYTE-" in pool:
        return "GIGABYTE"
    if url and re.search(r"/dynna-platka-(?:gb|gigabyte)[-/]", str(url).lower()):
        return "GIGABYTE"
    if name and re.search(r"\b(?:ДЪННА\s+ПЛАТКА\s+)?GB\b", str(name), re.IGNORECASE):
        return "GIGABYTE"
    if re.search(r"(^|[^A-Z])GB([^A-Z]|$)", pool):
        return "GIGABYTE"
    if "ASROCK" in pool:
        return "ASRock"
    if "ASUS" in pool:
        return "ASUS"
    if "MSI" in pool:
        return "MSI"
    if "BIOSTAR" in pool:
        return "Biostar"
    if "SAPPHIRE" in pool:
        return "Sapphire"
    if "SUPERMICRO" in pool:
        return "Supermicro"
    if "NZXT" in pool:
        return "NZXT"
    return None


def _prefer_inferred_brand(
    current_brand: str | None, model: str | None, name: str | None, url: str | None
) -> Optional[str]:
    inferred = _infer_brand(model, name, url)
    if not inferred:
        return current_brand
    if current_brand is None:
        return inferred
    current_upper = str(current_brand).upper()
    if any(
        token in current_upper
        for token in (
            "SOUP.FIND",
            "RE.SEARCH",
            "TITLE.SPLIT",
            "PATTERN",
            "SPLIT()[0",
            "UNKNOWN",
            "NULL",
        )
    ):
        return inferred
    if current_brand == inferred:
        return current_brand
    # In this dataset, AI sometimes labels GIGABYTE boards as Intel due "GB" in titles.
    if current_upper == "INTEL" and inferred == "GIGABYTE":
        return inferred
    allowed = {
        "ASUS",
        "ASROCK",
        "MSI",
        "GIGABYTE",
        "BIOSTAR",
        "SUPERMICRO",
        "NZXT",
        "SAPPHIRE",
    }
    if current_upper not in allowed:
        return inferred
    return current_brand


def _looks_like_placeholder_slug(*values: str | None) -> bool:
    for value in values:
        if not value:
            continue
        raw = str(value).strip()
        if not raw:
            continue
        normalized = raw.replace("™", "").replace("®", "")
        normalized = re.sub(
            r"(?i)\b(?:дънна\s*платка|motherboard|mainboard)\b", " ", normalized
        )
        normalized = re.sub(r"[^A-Z0-9]+", " ", normalized.upper())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            continue
        tokens = normalized.split()
        half = len(tokens) // 2
        if len(tokens) >= 4 and len(tokens) % 2 == 0 and tokens[:half] == tokens[half:]:
            return True
        if re.fullmatch(r"([A-Z0-9][A-Z0-9 ]{2,64}) \1", normalized):
            return True
        if "_" in raw and len(tokens) <= 6 and len(set(tokens)) <= max(1, len(tokens) // 2):
            return True
    return False


def _is_low_signal_placeholder_page(
    brand: str | None,
    model: str | None,
    name: str | None,
    specs: dict | None,
    raw: str | None,
) -> bool:
    if brand is not None:
        return False

    spec_values = [
        re.sub(r"\s+", " ", str(v)).strip()
        for v in (specs or {}).values()
        if str(v).strip()
    ]
    nonempty_spec_count = len(spec_values)
    specs_text = " ".join(f"{k}: {v}" for k, v in (specs or {}).items() if str(v).strip())
    evidence_text = f"{specs_text} {raw or ''}".upper()

    evidence_hits = 0
    if re.search(r"\b(?:CHIPSET|PLATFORM|ЧИПСЕТ)\b", evidence_text):
        evidence_hits += 1
    if re.search(r"\b(?:SOCKET|LGA\s*\d{3,5}|AM[345]|S?TR5|СОКЕТ)\b", evidence_text):
        evidence_hits += 1
    if re.search(r"\b(?:DDR[3-5]|DIMM|MEMORY|RAM|ПАМЕТ)\b", evidence_text):
        evidence_hits += 1
    if re.search(r"\b(?:E-ATX|ATX|MATX|M-ATX|MICRO ATX|MINI-ITX|ITX|FORM FACTOR|ФОРМ|РАЗМЕР)\b", evidence_text):
        evidence_hits += 1
    if re.search(
        r"\b\d+\s*[X×*]?\s*(?:USB|HDMI|DISPLAYPORT|RJ-?45|LAN|M\.?2|SATA|PCI(?:E|[- ]E|\s*EXPRESS))\b",
        evidence_text,
    ):
        evidence_hits += 1

    placeholder_like = _looks_like_placeholder_slug(model, name)
    almost_empty = nonempty_spec_count <= 1 and len((raw or "").strip()) < 80
    return (placeholder_like and evidence_hits <= 1) or (almost_empty and evidence_hits == 0)


def _normalize_ram_slots(value) -> Optional[int]:
    v = _to_int(value)
    if v is None:
        return None
    if v <= 0 or v > 8:
        return None
    if v % 2 == 1 and v != 1:
        return None
    return v


def _normalize_max_ram_amount(value) -> Optional[int]:
    v = _to_int(value)
    if v is None:
        return None
    if v <= 0 or v == 10 or v > 4096:
        return None
    return v


def _normalize_max_ram_speed_mhz(value) -> Optional[int]:
    v = _to_int(value)
    if v is None:
        return None
    if v < 1600 or v > 10000:
        return None
    return v


def _is_non_motherboard_item(
    brand: str | None, model: str | None, name: str | None, url: str | None
) -> bool:
    text = " ".join([str(x) for x in (brand, model, name, url) if x]).upper()
    if "THERMAL GRIZZLY" in text:
        return True
    if "TEST BOARD" in text:
        return True
    return False


def _is_integrated_cpu_board(
    name: str | None,
    model: str | None,
    chipset: str | None,
    raw: str | None,
    specs: dict | None,
    url: str | None,
) -> bool:
    pool = " ".join(
        [str(x) for x in (name, model, chipset, raw, url) if x]
        + [f"{k}: {v}" for k, v in (specs or {}).items() if k and v]
    ).upper()
    if not pool:
        return False
    if re.search(r"\b(?:J|N)\d{3,4}\b", str(chipset or "").upper()):
        return True
    strong_cpu_token = bool(
        re.search(
            r"\b(?:CELERON|PENTIUM|ATOM|INTEL)\s+(?:J|N)\d{3,4}\b|\b(?:J|N)(?:95|97|100|200|305|4105|4125|5005|6412)\b",
            pool,
        )
    )
    onboard_phrase = bool(
        re.search(
            r"\b(?:INTEGRATED|ONBOARD|EMBEDDED|SOLDERED)\s+CPU\b|\bCPU\s+ONBOARD\b|\bPROCESSOR\s+ONBOARD\b",
            pool,
        )
    )
    embedded_hint = bool(
        re.search(r"\bEMBEDDED\b|\bINDUSTRIAL\b|\bTHIN CLIENT\b|\bFANLESS\b", pool)
    )
    if strong_cpu_token:
        return True
    if onboard_phrase and (strong_cpu_token or embedded_hint):
        return True
    return False


def _extract_socket_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    upper = str(text).upper()
    if re.search(r"\bID\s*:\s*\d{4,}\b", upper):
        return None
    m = re.search(r"\bLGA\s*(\d{3,5})\b", upper)
    if m:
        num = int(m.group(1))
        if num <= 9999:
            return f"LGA {m.group(1)}"
        return None
    m = re.search(r"\b(?:SOCKET\s*)?(\d{3,5})\b", upper)
    if m and len(upper) < 80:
        num = int(m.group(1))
        if num <= 9999:
            return f"LGA {m.group(1)}"
        return None
    m = re.search(r"\b(AM[345]|TR4)\b", upper)
    if m:
        return m.group(1)
    if re.search(r"\bS?TR5\b|\bSTRX4\b", upper):
        return "sTR5"
    return None


def _normalize_wifi(value: str | None) -> str:
    if not value:
        return "Not present"
    s = str(value).strip()
    upper = s.upper()
    antenna_or_accessory_only = bool(
        re.search(r"\bANTENNA(?:S)?\b|\bАНТЕН", upper)
        or re.search(r"\bMOUNTING\s+POINTS?\b", upper)
        or re.search(r"\bINCLUDED\s+ANTENNA(?:S)?\b", upper)
    )
    upgrade_slot_only = bool(
        re.search(r"\bWI[ -]?FI\s+CONTROLLER\b", upper)
        or re.search(r"\bCNVIO2?\b", upper)
        or (
            "M.2" in upper
            and "KEY E" in upper
            and re.search(r"\b(WI[ -]?FI|MODULE|BT|BLUETOOTH)\b", upper)
        )
    )
    generic_wifi_capability = bool(
        re.search(r"\bWI[ -]?FI\b", upper)
        and not re.search(
            r"\bWI[ -]?FI\s+(?:CONTROLLER|ANTENNAS?|MODULE)\b", upper
        )
    )
    actual_wireless_evidence = bool(
        re.search(r"WI[ -]?FI\s*(6E|[4-7])", upper)
        or "802.11" in upper
        or generic_wifi_capability
        or re.search(r"\b(WIRELESS\s+LAN|WLAN)\b", upper)
        or re.search(
            r"\bWI[ -]?FI\b[^\n\r]{0,30}\bBLUETOOTH\b|\bBLUETOOTH\b[^\n\r]{0,30}\bWI[ -]?FI\b",
            upper,
        )
    )
    if (upgrade_slot_only or antenna_or_accessory_only) and not actual_wireless_evidence:
        return "Not present"
    if any(k in upper for k in ("NOT", "NONE", "NO WIFI", "N/A", "НЕ", "NULL")):
        return "Not present"
    versions = []
    for ver in re.findall(r"WI[ -]?FI\s*(6E|[4-7])", upper):
        v = ver.replace(" ", "")
        if v not in versions:
            versions.append(v)
    if "802.11BE" in upper and "7" not in versions:
        versions.append("7")
    if "802.11AX" in upper and "6" not in versions and "6E" not in versions:
        versions.append("6")
    if "802.11AC" in upper and "5" not in versions:
        versions.append("5")
    if "802.11N" in upper and "4" not in versions:
        versions.append("4")
    if versions:
        rank = {"4": 4.0, "5": 5.0, "6": 6.0, "6E": 6.5, "7": 7.0}
        best = max(versions, key=lambda x: rank.get(x, 0))
        return f"Wi-Fi {best}"
    if re.search(r"\b(4|5|6|7|6E)\b", upper) and re.fullmatch(
        r"\s*(4|5|6|7|6E)\s*", upper
    ):
        return f"Wi-Fi {upper.strip()}"
    if actual_wireless_evidence:
        return "Wi-Fi"
    return "Not present"


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    if m:
        return int(m.group(0))
    return None


def _extract_max_ram_speed_mhz(text: str) -> Optional[int]:
    vals = [
        int(x)
        for x in re.findall(r"\b(\d{4,5})\s*(?:MT/s|MHz)\b", text, flags=re.IGNORECASE)
    ]
    vals += [
        int(x) for x in re.findall(r"DDR[3-5][- ]?(\d{4,5})", text, flags=re.IGNORECASE)
    ]
    vals = [v for v in vals if 1600 <= v <= 10000]
    return max(vals) if vals else None


def _extract_max_ram_amount_gb(text: str) -> Optional[int]:
    vals = [
        int(x) for x in re.findall(r"\b(\d{2,4})\s*GB\b", text, flags=re.IGNORECASE)
    ]
    vals = [v for v in vals if 8 <= v <= 1024]
    return max(vals) if vals else None


def _extract_ram_slots(text: str) -> Optional[int]:
    if not text:
        return None
    source = str(text).replace("®", "").replace("™", "")
    upper = source.upper()
    if not re.search(
        r"\b(DIMM|DDR[3-5]|MEMORY|RAM|СЛОТ(?:А|ОВЕ)?|ПАМЕТ)\b", upper
    ):
        return None
    vals = []
    patterns = (
        r"\b(?:СЛОТОВЕ?\s+ЗА\s+ПАМЕТ|DIMM\s+SLOTS?|MEMORY\s+SLOTS?|RAM\s+SLOTS?)\s*[:=]?\s*(\d+)\b",
        r"\b(\d+)\s*[xX×*]\s*DDR[3-5]\b",
        r"\b(\d+)\s*[xX×*]\s*DIMM\b",
        r"\b(\d+)\s*(?:DIMM|MEMORY|RAM)\s+SLOTS?\b",
        r"\b(\d+)\s*(?:DIMM|DDR[3-5])\s+SLOTS?\b",
        r"\b(?:DIMM|MEMORY|RAM)\s+SLOTS?\s*[:=]?\s*(\d+)\b",
        r"\b(?:СЛОТ|СЛОТА|СЛОТОВЕ)(?:\s+ЗА\s+ПАМЕТ)?\s*[:=]?\s*(\d+)\b",
    )
    for pat in patterns:
        for match in re.findall(pat, upper, flags=re.IGNORECASE):
            vals.append(int(match))
    vals = [v for v in vals if 1 <= v <= 8 and (v == 1 or v % 2 == 0)]
    return max(vals) if vals else None


def _is_explicit_ram_slot_key(key: str | None) -> bool:
    if not key:
        return False
    upper = re.sub(r"\s+", " ", str(key).upper()).strip()
    if "DIMM" in upper:
        return True
    if "SLOT" in upper and ("MEMORY" in upper or "RAM" in upper):
        return True
    if "СЛОТ" in upper and "ПАМЕТ" in upper:
        return True
    return False


def _extract_ram_slots_from_specs(specs: dict | None, raw: str | None) -> Optional[int]:
    vals = []
    for k, v in (specs or {}).items():
        key = str(k)
        value = str(v)
        row_text = f"{key}: {value}"
        if _is_explicit_ram_slot_key(key):
            slot_count = _extract_ram_slots(row_text)
            if slot_count is None:
                slot_count = _normalize_ram_slots(_to_int(value))
            if slot_count is not None:
                vals.append(slot_count)
            continue
        if re.search(
            r"\b\d+\s*[xX×*]?\s*(?:DDR[3-5]|DIMM)\b",
            value,
            flags=re.IGNORECASE,
        ) and re.search(
            r"\b(?:SLOTS?|DIMM|DDR[3-5]|MEMORY|RAM)\b",
            value,
            flags=re.IGNORECASE,
        ):
            slot_count = _extract_ram_slots(row_text)
            if slot_count is not None:
                vals.append(slot_count)
    if vals:
        return max(vals)
    raw_text = str(raw or "")
    if re.search(
        r"\b(?:DIMM|DDR[3-5])\b.*\bSLOTS?\b|\b(?:MEMORY|RAM)\s+SLOTS?\b|\bСЛОТ(?:А|ОВЕ)?\s+ЗА\s+ПАМЕТ\b",
        raw_text,
        flags=re.IGNORECASE,
    ):
        return _extract_ram_slots(raw_text)
    return None


def _extract_wifi(text: str) -> str:
    return _normalize_wifi(text)


def _extract_wifi_from_product_text(text: str) -> str:
    if not text:
        return "Not present"
    upper = str(text).upper()
    if re.search(r"\b(?:WF6E|WIFI\s*6E|WI-FI\s*6E)\b", upper):
        return "Wi-Fi 6E"
    for version in ("7", "6", "5", "4"):
        if re.search(
            rf"\b(?:WF{version}|WIFI\s*{version}|WI-FI\s*{version}|WIFI{version})\b",
            upper,
        ):
            return f"Wi-Fi {version}"
    if re.search(r"\b(?:WF|WIFI|WI-FI)\b", upper):
        return "Wi-Fi"
    return "Not present"


def _extract_m2_info(text: str) -> list:
    if not text:
        return []

    def _extract_gen_numbers(upper: str) -> list[int]:
        vals: list[int] = []
        for g in re.findall(r"GEN\s*([3-7])", upper):
            gv = int(g)
            if gv not in vals:
                vals.append(gv)
        for g in re.findall(
            r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?",
            upper,
        ):
            gv = int(g)
            if gv not in vals:
                vals.append(gv)
        return vals

    def _extract_slot_ids(upper: str) -> list[str]:
        slot_ids: list[str] = []
        for sid in re.findall(r"\bM\.?2[_-]?(\d+)\b", upper):
            token = f"N{sid}"
            if token not in slot_ids:
                slot_ids.append(token)
        for sid in re.findall(
            r"\bM\.?2[_-]?([A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b", upper
        ):
            token = re.sub(r"[^A-Z0-9]+", "_", sid).strip("_")
            if token and token not in slot_ids:
                slot_ids.append(token)
        return slot_ids

    def _normalize_context(seg: str, current: str) -> tuple[str, str]:
        context = current
        cleaned = seg.strip()
        m = re.match(r"^\s*(CPU|CHIPSET|PCH)\s*:\s*", cleaned, flags=re.IGNORECASE)
        if m:
            context = m.group(1).upper()
            cleaned = cleaned[m.end() :]
        else:
            generic_label = re.match(r"^\s*([^:]{1,48})\s*:\s*", cleaned)
            if generic_label:
                label_upper = generic_label.group(1).upper()
                if any(
                    token in label_upper
                    for token in ("M.2", "STORAGE", "DISK", "SLOT", "INTERFACE", "CONTROLLER")
                ):
                    context = "GENERIC"
                    cleaned = cleaned[generic_label.end() :]
        cleaned = cleaned.strip(" -")
        return cleaned, context

    def _family_key(upper: str) -> str:
        family = upper
        family = re.sub(r"\b(CPU|CHIPSET|PCH)\s*:\s*", "", family)
        family = re.sub(r"\bAMD\s+RYZEN[^,;()]{0,90}", "", family)
        family = re.sub(r"\bINTEL\s+CORE[^,;()]{0,90}", "", family)
        family = re.sub(
            r"\(\s*M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)"
            r"(?:\s*,\s*M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*))*\s*\)",
            "",
            family,
        )
        family = re.sub(
            r"\bM\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b", "", family
        )
        family = re.sub(r"\b\d+\s*[xX×*]?\s*M\.?2\b", "M2", family)
        family = re.sub(r"\s+", " ", family).strip(" -,;")
        return family or "GENERIC"

    source = str(text).replace("\r", "\n")
    source = source.replace("®", "").replace("™", "")
    # Cope with tuple/list string representations from spec extraction.
    source = re.sub(r"^\s*[\(\[]\s*", "", source)
    source = re.sub(r"\s*[\)\]]\s*$", "", source)
    source = source.replace("', '", "; ").replace('", "', "; ")
    source = source.replace("'; '", "; ").replace('"; "', "; ")
    source = re.sub(
        r"\b(CPU|CHIPSET|PCH)\s*-\s*(?=\d+\s*[xX×*]?\s*M\.?2\s+(?:CONNECTORS?|SOCKETS?|SLOTS?)\b)",
        r"\1: ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"\n(?=\s*(?:CPU\b|CHIPSET\b|PCH\b|STORAGE CONTROLLER\b|"
        r"M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b|"
        r"\d+\s*[xX×*]?\s*M\.?2\b|"
        r"PCI(?:E|[- ]E|\s*EXPRESS)?\s*[3-7](?:\.0)?\s*-?\s*CONNECTORS?\s*:))",
        ";",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(r"[\r\n]+", " ", source)
    source = re.sub(r"\s+", " ", source).strip()
    source = re.sub(
        r"\s+(?=(?:CPU|CHIPSET|PCH|STORAGE CONTROLLER)\s*:)",
        ";",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"\)\s+(?=PCI(?:E|[- ]E|\s*EXPRESS)?\s*[3-7](?:\.0)?\s*X\d+\s*\(\s*\d+\s*[xX×*]?\s*M\.?2\b)",
        "); ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"\)\s*(?=M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\s+SLOT\b)",
        "); ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"(?<=[A-Z0-9\)])\s+(?="
        r"M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b"
        r"\s*(?:\(|TYPE\b|SUPPORTS\b|PCI))",
        "; ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"\)\s*[-•*]\s*(?=\d+\s*[xX×*]?\s*M\.?2\s+(?:CONNECTORS?|SOCKETS?|SLOTS?)\b)",
        "); ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"(?<=[A-Z0-9\)])\s*(?:[-•*]\s*)?(?=(?:\d+\s*[xX×*]?\s*M\.?2\b(?:\s*(?:SLOTS?|SOCKETS?|CONNECTORS?))|"
        r"M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\s+SLOT\b))",
        "; ",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r",\s*(?=(?:PCI(?:E|[- ]E|\s*EXPRESS)?\s*[3-7](?:\.0)?\s*-?\s*CONNECTORS?\s*:|"
        r"\d+\s*[xX×*]?\s*M\.?2\b))",
        ";",
        source,
        flags=re.IGNORECASE,
    )
    raw_clauses = []
    for clause in re.split(r"[;|]+", source):
        if not clause or not clause.strip(" -,"):
            continue
        split_parts = re.split(
            r",\s*(?=(?:"
            r"M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\s+SLOT\b|"
            r"M\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b\s*(?:\(|TYPE\b|SUPPORTS\b|PCI)|"
            r"(?:\d+\s*[xX×*]?\s*)?(?:BLAZING|HYPER|ULTRA|TURBO)?\s*M\.?2\s+(?:SLOT|SOCKET|CONNECTOR)\b|"
            r"\d+\s*[xX×*]?\s*M\.?2\b"
            r"))",
            clause,
            flags=re.IGNORECASE,
        )
        for part in split_parts:
            cleaned = part.strip(" -,")
            if cleaned:
                raw_clauses.append(cleaned)

    slot_best_gen: dict[tuple[str, str], int] = {}
    slot_seen_without_gen: set[tuple[str, str]] = set()
    summary_caps: dict[tuple[str, Optional[int], str], int] = {}
    summary_signatures: dict[tuple[str, Optional[int], str], set[str]] = {}
    controller_entries: dict[str, tuple[int, int]] = {}
    pending_slot_keys: list[tuple[str, str]] = []
    count_only_caps: list[int] = []
    current_context = "GENERIC"
    last_context_version: dict[str, int] = {}

    for clause in raw_clauses:
        clause, current_context = _normalize_context(clause, current_context)
        upper = clause.upper()
        has_m2 = "M.2" in upper or re.search(r"\bM2(?:_|-|\d|[A-Z])", upper)
        gens = _extract_gen_numbers(upper)

        if not has_m2:
            if pending_slot_keys and gens:
                version = max(gens)
                for slot_key in pending_slot_keys:
                    slot_seen_without_gen.add(slot_key)
                    prev = slot_best_gen.get(slot_key)
                    if prev is None or version > prev:
                        slot_best_gen[slot_key] = version
                continue
            pending_slot_keys = []
            continue

        if "DIMM.2" in upper or re.search(r"\bDIMM2[_-]?\d*\b", upper):
            pending_slot_keys = []
            continue
        if re.search(r"\bSHARES?\s+BANDWIDTH\b|\bBANDWIDTH\s+WITH\b", upper):
            pending_slot_keys = []
            continue
        if "KEY E" in upper and "KEY M" not in upper:
            pending_slot_keys = []
            continue
        if "KEY M" not in upper and re.search(
            r"\b(CNVIO2?|WI-?FI/?BT|WIFI/BT|WIFI MODULE|WI-FI MODULE|WIRELESS MODULE)\b",
            upper,
            flags=re.IGNORECASE,
        ):
            pending_slot_keys = []
            continue
        if any(
            token in upper
            for token in (
                "THERMAL PAD",
                "BACKPLATE",
                "Q-LATCH",
                "Q-SLIDE",
                "STICKER",
                "BOTTLE",
                "PACKAGE",
                "CABLE",
                "HOLDER",
                "WIFI MODULE",
            )
        ):
            pending_slot_keys = []
            continue

        explicit_count = None
        for pat in (
            r"\b(\d+)\s*[xX×*]?\s*M\.?2\b(?:\s*(?:SLOTS?|SOCKETS?|CONNECTORS?))?",
            r"\(\s*(\d+)\s*[xX×*]?\s*M\.?2(?:\s*\(KEY M\))?\s*\)",
        ):
            m_count = re.search(pat, upper, flags=re.IGNORECASE)
            if m_count:
                explicit_count = int(m_count.group(1))
                break

        if explicit_count is not None and not gens and not _extract_slot_ids(upper):
            count_only_caps.append(max(1, min(explicit_count, 10)))
            pending_slot_keys = []
            continue

        slot_ids = _extract_slot_ids(upper)
        if (
            not slot_ids
            and explicit_count is None
            and re.search(
                r"\bFOR\s+M\.?2\b|\bM\.?2\s+NVME\s+STORAGE\s+DEVICES\b",
                upper,
                flags=re.IGNORECASE,
            )
        ):
            pending_slot_keys = []
            continue
        version = max(gens) if gens else None
        if version is not None:
            last_context_version[current_context] = version

        if slot_ids:
            if version is None and current_context in last_context_version:
                version = last_context_version[current_context]
            pending_slot_keys = []
            slot_keys = [(current_context, sid) for sid in slot_ids]
            pending_slot_keys = slot_keys
            for slot_key in slot_keys:
                slot_seen_without_gen.add(slot_key)
                if version is not None:
                    prev = slot_best_gen.get(slot_key)
                    if prev is None or version > prev:
                        slot_best_gen[slot_key] = version
            # Preserve explicit clause count as cap for anonymous extras in that exact family.
            extra = max(0, (explicit_count or len(slot_ids)) - len(slot_ids))
            if extra > 0:
                family = _family_key(upper)
                summary_key = (current_context, version, family)
                summary_caps[summary_key] = max(summary_caps.get(summary_key, 0), extra)
            continue

        if (
            explicit_count is not None
            and version is not None
            and re.search(
                r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+NVME)?\s*[3-7](?:\.0)?\s*X\d+",
                upper,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\(\s*\d+\s*[xX×*]?\s*M\.?2\b",
                upper,
                flags=re.IGNORECASE,
            )
            and not re.search(
                r"\b(CPU|PROCESSORS?|RYZEN|CORE|THREADRIPPER|XEON|KEY E|WI-?FI|CNVIO)\b",
                upper,
                flags=re.IGNORECASE,
            )
        ):
            signature = re.sub(r"\s+", " ", upper).strip(" -,;")
            controller_entries[signature] = (version, explicit_count)
            pending_slot_keys = []
            continue

        pending_slot_keys = []
        count = explicit_count or 1
        if count <= 0 or count > 10:
            continue
        if version is not None:
            last_context_version[current_context] = version
        family = _family_key(upper)
        summary_key = (current_context, version, family)
        signature = re.sub(r"\s+", " ", upper).strip(" -,;")
        seen_signatures = summary_signatures.setdefault(summary_key, set())
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        if re.search(
            r"\b(CPU|PROCESSORS?|RYZEN|CORE|THREADRIPPER|XEON)\b",
            upper,
            flags=re.IGNORECASE,
        ):
            summary_caps[summary_key] = max(summary_caps.get(summary_key, 0), count)
        else:
            summary_caps[summary_key] = summary_caps.get(summary_key, 0) + count

    gen_counts: dict[str, int] = {}
    unknown_count = 0

    for slot_key in slot_seen_without_gen:
        version = slot_best_gen.get(slot_key)
        if version is None:
            unknown_count += 1
            continue
        token = f"Gen{version}"
        gen_counts[token] = gen_counts.get(token, 0) + 1

    for (_, version, _), count in summary_caps.items():
        if version is None:
            unknown_count += count
        else:
            token = f"Gen{version}"
            gen_counts[token] = gen_counts.get(token, 0) + count

    for version, count in controller_entries.values():
        token = f"Gen{version}"
        gen_counts[token] = gen_counts.get(token, 0) + count

    if count_only_caps:
        cap = min(count_only_caps)
        total_slots = sum(gen_counts.values()) + unknown_count
        if total_slots == 0:
            unknown_count = cap
        elif total_slots > cap:
            overflow = total_slots - cap
            trimmed_unknown = min(unknown_count, overflow)
            unknown_count -= trimmed_unknown
            overflow -= trimmed_unknown
            if overflow > 0:
                for gen in sorted(
                    gen_counts.keys(),
                    key=lambda token: int(re.search(r"\d+", token).group(0)),
                    reverse=True,
                ):
                    if overflow <= 0:
                        break
                    take = min(gen_counts[gen], overflow)
                    gen_counts[gen] -= take
                    overflow -= take
        elif total_slots < cap and not gen_counts:
            unknown_count = cap

    unknown_count = min(10, max(0, unknown_count))
    out = [
        {"count": count, "version": gen}
        for gen, count in sorted(
            gen_counts.items(),
            key=lambda item: int(re.search(r"\d+", item[0]).group(0)),
            reverse=True,
        )
        if count > 0
    ]
    if unknown_count > 0:
        out.append({"count": unknown_count, "version": None})
    return out


def _extract_sata_slots(text: str) -> Optional[int]:
    if not text:
        return None
    vals = []
    patterns = (
        r"\b(\d+)\s*[xX×*]\s*SATA(?:\s*III|3(?:\.0)?)?(?:\s*6(?:\.0)?\s*G(?:B/S|BPS|BIT/S)?)?\b",
        r"\bSATA(?:\s*(?:III|3(?:\.0)?))?\s*(?:PORTS?|CONNECTORS?)\s*[:=]?\s*(\d+)\b",
        r"\b(\d+)\s*(?:SATA\s*(?:PORTS?|CONNECTORS?))\b",
        r"\bSATA(?:\s*III|\s*3(?:\.0)?|\s*6G(?:B/S|BPS)?|[-\s])*?\s*\((\d{1,2})\)",
        r"\bSATA[^\n\r]{0,36}?\((\d{1,2})\)",
    )
    for pat in patterns:
        for m in re.findall(pat, text, flags=re.IGNORECASE):
            vals.append(int(m))
    vals = [v for v in vals if 1 <= v <= 16]
    return max(vals) if vals else None


def _extract_pcie_slots(text: str) -> list:
    raw_lines = [
        re.sub(
            r"\bX\s+(1|4|8|16)\b",
            r"X\1",
            re.sub(r"\s+", " ", line).strip(),
            flags=re.IGNORECASE,
        )
        for line in re.split(r"[\n\r]+", text)
        if line and line.strip()
    ]
    lines = list(dict.fromkeys(raw_lines))
    narrative_out = []
    key_value_out = []
    slot_id_narrative_lanes: set[str] = set()

    slot_def_re = re.compile(
        r"\b(\d+)\s*[xX×*]?\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(1|4|8|16)\b[^\n\r]{0,80}\bSLOTS?\b",
        flags=re.IGNORECASE,
    )
    key_value_re = re.compile(
        r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*X(1|4|8|16)\b\s*[:：]\s*(.+)$",
        flags=re.IGNORECASE,
    )

    def _append_slot(per_line: dict, lane: str, count: int, version: str | None):
        if lane not in ("x1", "x4", "x8", "x16"):
            return
        count = max(1, min(int(count), _MAX_PCIE_SLOT_COUNT))
        key = (lane, version)
        per_line[key] = min(_MAX_PCIE_SLOT_COUNT, per_line.get(key, 0) + count)

    def _explicit_lane_mentions(block_upper: str) -> int:
        return len(
            re.findall(
                r"\b\d+\s*[xX×*]?\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(?:1|4|8|16)\b",
                block_upper,
                flags=re.IGNORECASE,
            )
        )

    def _extract_slot_id_lanes(block_upper: str) -> tuple[int, Optional[str], set[str]]:
        id_matches = re.finditer(
            # Infer lane from IDs only when the ID itself contains an explicit X-lane token
            # (e.g. PCIEX1_1/PCIEX4). IDs like PCIE1/PCIE2 are ordinal labels and should not infer lane.
            r"\b((?:PCIEX|PCI[_\s-]?EX)\s*(1|4|8|16)(?:[_-]\d+)?)(?!\.\d)\b",
            block_upper,
        )
        lane_counts = {}
        id_tokens = set()
        lane_set: set[str] = set()
        for m in id_matches:
            token = re.sub(r"\s+", "", m.group(1))
            lane = f"x{m.group(2)}"
            id_tokens.add(token)
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
            lane_set.add(lane)
        if not id_tokens:
            return 0, None, set()
        best_lane = sorted(
            lane_counts.items(), key=lambda kv: (kv[1], int(kv[0][1:])), reverse=True
        )[0][0]
        return len(id_tokens), best_lane, lane_set

    def _block_context_group(block_upper: str) -> Optional[str]:
        if re.search(
            r"\b(CHIPSET|PCH|FROM\s+AMD\s+[A-Z0-9-]+\s+CHIPSET|FROM\s+INTEL\s+[A-Z0-9-]+\s+CHIPSET)\b",
            block_upper,
            flags=re.IGNORECASE,
        ):
            return "CHIPSET"
        if re.search(
            r"\b(CPU|PROCESSORS?|RYZEN|CORE|THREADRIPPER|XEON|FROM\s+CPU|INTEGRATED\s+IN\s+THE\s+CPU)\b",
            block_upper,
            flags=re.IGNORECASE,
        ):
            return "CPU"
        return None

    def _parse_key_value_line(line: str) -> Optional[list[dict]]:
        m_key = key_value_re.search(line)
        if not m_key:
            return None
        lane_num = m_key.group(1)
        default_lane = f"x{lane_num}"
        rhs = m_key.group(2).strip()
        if not rhs:
            return []
        if ";" in rhs and (
            re.search(
                r"\b(CHIPSET|PCH|RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
                rhs,
                flags=re.IGNORECASE,
            )
            or re.search(r"\b(PCIEX\d+|PCI[_\s-]?EX?\d+)\b", rhs, flags=re.IGNORECASE)
        ):
            return None

        per_line = {}
        clauses = []
        for chunk in re.split(r"[;]+", rhs):
            clauses.extend(
                [x.strip() for x in re.split(r",\s*", chunk) if x and x.strip()]
            )
        if not clauses:
            clauses = [rhs]

        explicit_pattern = re.compile(
            r"\b(\d+)\s*[xX×*]?\s*PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\s*X(1|4|8|16)\b",
            flags=re.IGNORECASE,
        )
        version_only_pattern = re.compile(
            r"\b(\d+)\s*[xX×*]?\s*PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\b",
            flags=re.IGNORECASE,
        )
        for clause in clauses:
            clause_u = clause.upper()
            matched = False
            for c, g, lane in explicit_pattern.findall(clause_u):
                _append_slot(per_line, f"x{lane}", int(c), f"PCIe {g}.0")
                matched = True
            if matched:
                continue

            for c, g in version_only_pattern.findall(clause_u):
                _append_slot(per_line, default_lane, int(c), f"PCIe {g}.0")
                matched = True
            if matched:
                continue

            m_count_only = re.fullmatch(r"\s*(\d+)\s*", clause_u)
            if m_count_only:
                _append_slot(per_line, default_lane, int(m_count_only.group(1)), None)
                continue

            m_count_slot = re.search(
                r"\b(\d+)\s*[xX×*]?\s*(?:SLOT|SLOTS)\b", clause_u
            )
            if m_count_slot:
                gens = [
                    int(g)
                    for g in re.findall(
                        r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?", clause_u
                    )
                ]
                ver = f"PCIe {max(gens)}.0" if gens else None
                _append_slot(per_line, default_lane, int(m_count_slot.group(1)), ver)
                continue

            if re.search(
                rf"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*X{lane_num}\b", clause_u,
                flags=re.IGNORECASE,
            ):
                gens = [
                    int(g)
                    for g in re.findall(
                        r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?", clause_u
                    )
                ]
                ver = f"PCIe {max(gens)}.0" if gens else None
                _append_slot(per_line, default_lane, 1, ver)

        if not per_line:
            m_fallback_count = re.search(r"\b(\d+)\b", rhs)
            if m_fallback_count:
                _append_slot(
                    per_line, default_lane, int(m_fallback_count.group(1)), None
                )

        return [
            {"count": count, "lane": lane, "version": ver}
            for (lane, ver), count in per_line.items()
        ]

    def _parse_compact_narrative_line(line: str) -> Optional[list[dict]]:
        line_u = line.upper()
        if re.search(r"\b(PCIEX\d+|PCI[_\s-]?E\d+)\b", line_u) and "SLOT" in line_u:
            return None
        if ";" in line and (
            re.search(
                r"\bSPECIFICATIONS?\s+VARY\s+BY\s+CPU\b|\bVARY\s+BY\s+CPU\s+TYPES?\b",
                line_u,
                flags=re.IGNORECASE,
            )
            or (
                re.search(
                    r"\b(RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
                    line_u,
                    flags=re.IGNORECASE,
                )
                and re.search(r"\b(CHIPSET|PCH)\b", line_u, flags=re.IGNORECASE)
            )
        ):
            return None
        per_line = {}

        # Handles compact forms like:
        # "3x PCI Express 3.0 x1, 1x PCI Express 4.0 x16"
        explicit_with_version = list(
            re.finditer(
                r"\b(\d+)\s*[xX×*]\s*PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\s*X(1|4|8|16)\b",
                line_u,
                flags=re.IGNORECASE,
            )
        )
        for m in explicit_with_version:
            _append_slot(
                per_line,
                f"x{m.group(3)}",
                int(m.group(1)),
                f"PCIe {m.group(2)}.0",
            )

        # Handles compact forms like:
        # "1x PCI-E x16 slot 2x PCI-E x1 slot"
        lane_decl = list(
            re.finditer(
                r"\b(\d+)\s*[xX×*]\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*X(1|4|8|16)\s*SLOTS?\b",
                line_u,
                flags=re.IGNORECASE,
            )
        )
        declared_by_lane: dict[str, int] = {}
        for m in lane_decl:
            lane = f"x{m.group(2)}"
            declared_by_lane[lane] = declared_by_lane.get(lane, 0) + int(m.group(1))

        # Handles slot-id generation details like:
        # "PCI_E1 Gen PCIe 3.0 supports up to x1 ... PCI_E2 Gen PCIe 4.0 supports up to x16 ..."
        slot_segments = list(
            re.finditer(
                r"\b(PCI[_\s-]?E\d+)\b(.*?)(?=\bPCI[_\s-]?E\d+\b|$)",
                line_u,
                flags=re.IGNORECASE,
            )
        )
        if (
            len(explicit_with_version) <= 1
            and len(lane_decl) <= 1
            and len(slot_segments) <= 1
        ):
            return None
        slot_map: dict[str, tuple[str | None, str | None]] = {}
        for seg in slot_segments:
            slot_id = re.sub(r"\s+", "", seg.group(1))
            chunk = seg.group(0)
            chunk_u = chunk.upper()
            explicit_lane = None
            m_size = re.search(
                r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*X(1|4|8|16)\s*SLOTS?\b",
                chunk,
                flags=re.IGNORECASE,
            )
            if m_size:
                explicit_lane = f"x{m_size.group(1)}"
            lane = explicit_lane
            if lane is None:
                _, id_lane, _ = _extract_slot_id_lanes(chunk)
                if id_lane is not None:
                    lane = id_lane
            has_cpu_family_context = bool(
                re.search(
                    r"\b(RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
                    chunk_u,
                    flags=re.IGNORECASE,
                )
            )
            if lane is None and not has_cpu_family_context:
                m_lane = re.search(
                    r"\bSUPPORTS\s+UP\s+TO\s+X(1|4|8|16)\b",
                    chunk,
                    flags=re.IGNORECASE,
                )
                if not m_lane:
                    m_lane = re.search(
                        r"\bRUNNING\s+AT\s+X(1|4|8|16)\b",
                        chunk,
                        flags=re.IGNORECASE,
                    )
                if not m_lane:
                    m_lane = re.search(r"\bX(1|4|8|16)\s*MODE\b", chunk, flags=re.IGNORECASE)
                if m_lane:
                    lane = f"x{m_lane.group(1)}"
            if lane is None and not has_cpu_family_context:
                m_lane = re.search(r"\bX(1|4|8|16)\b", chunk, flags=re.IGNORECASE)
                if m_lane:
                    lane = f"x{m_lane.group(1)}"
            m_gen = re.search(
                r"\bGEN\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*([3-7])(?:\.0)?\b",
                chunk,
                flags=re.IGNORECASE,
            )
            if not m_gen:
                m_gen = re.search(
                    r"\bPCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\b",
                    chunk,
                    flags=re.IGNORECASE,
                )
            ver = f"PCIe {m_gen.group(1)}.0" if m_gen else None
            prev_lane, prev_ver = slot_map.get(slot_id, (None, None))
            if prev_lane is None or explicit_lane is not None:
                prev_lane = lane
            if prev_ver is None:
                prev_ver = ver
            elif ver is not None:
                prev_gen = int(re.search(r"\d+", prev_ver).group(0)) if re.search(r"\d+", prev_ver) else 0
                curr_gen = int(re.search(r"\d+", ver).group(0)) if re.search(r"\d+", ver) else 0
                if curr_gen > prev_gen:
                    prev_ver = ver
            slot_map[slot_id] = (prev_lane, prev_ver)

        for lane, _ in slot_map.values():
            if lane in ("x1", "x4", "x8", "x16"):
                slot_id_narrative_lanes.add(lane)
        for lane, ver in slot_map.values():
            if lane:
                _append_slot(per_line, lane, 1, ver)

        # Top up lane declarations for slots that have no explicit per-slot generation evidence.
        for lane, declared_count in declared_by_lane.items():
            known_count = sum(
                count for (ln, _), count in per_line.items() if ln == lane
            )
            remaining = declared_count - known_count
            if remaining <= 0:
                continue
            lane_versions = {
                ver for (ln, ver), _ in per_line.items() if ln == lane and ver is not None
            }
            inferred_ver = next(iter(lane_versions)) if len(lane_versions) == 1 else None
            _append_slot(per_line, lane, remaining, inferred_ver)

        if not per_line:
            return None
        if len(explicit_with_version) + len(lane_decl) + len(slot_segments) < 2:
            return None
        return [
            {"count": count, "lane": lane, "version": ver}
            for (lane, ver), count in per_line.items()
        ]

    def _parse_contextual_semicolon_line(line: str) -> Optional[list[dict]]:
        line_u = line.upper()
        if ";" not in line:
            return None
        if not re.search(
            r"\b(CHIPSET|PCH|RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
            line_u,
            flags=re.IGNORECASE,
        ):
            return None
        if re.search(r"\b(PCIEX\d+|PCI[_\s-]?E\d+)\b", line_u):
            return None

        contextual_best: dict[tuple[str, str], tuple[int, str | None]] = {}
        merged: dict[tuple[str, str | None], int] = {}
        current_context: str | None = None
        current_physical_lane: str | None = None
        saw_slot = False

        for seg in re.split(r"[;]+", line):
            seg = re.sub(r"\s+", " ", seg).strip()
            if not seg:
                continue
            seg_u = seg.upper()
            m_label = re.match(
                r"^\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*:\s*(.+)$",
                seg,
                flags=re.IGNORECASE,
            )
            if m_label and not re.search(r"\bX(1|4|8|16)\b", seg_u):
                seg = m_label.group(1).strip()
                seg_u = seg.upper()
            if re.search(r"\bSHARES?\s+BANDWIDTH\s+WITH\b", seg_u, flags=re.IGNORECASE):
                continue

            context_group = _block_context_group(seg_u)
            if context_group is not None and "PCI" not in seg_u:
                current_context = context_group
                continue
            if (
                re.search(
                    r"\b(RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
                    seg_u,
                    flags=re.IGNORECASE,
                )
                and "PCI" not in seg_u
            ):
                current_context = "CPU"
                continue
            if "PCI" not in seg_u:
                continue
            if any(
                token in seg_u
                for token in (
                    "STORAGE CONTROLLER",
                    "SSD SUPPORT",
                    "SOCKET 3",
                    "RAID",
                    "WIFI MODULE",
                    "CNVIO",
                    "CNVIO2",
                )
            ):
                continue

            m_def = slot_def_re.search(seg_u)
            explicit_lane = None
            if m_def:
                count = int(m_def.group(1))
                explicit_lane = f"x{m_def.group(2)}"
            else:
                m_size = re.search(
                    r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(1|4|8|16)\b[^\n\r]{0,40}\bSLOTS?\b",
                    seg_u,
                    flags=re.IGNORECASE,
                )
                if m_size:
                    explicit_lane = f"x{m_size.group(1)}"
                    count = 1
                elif current_physical_lane is None:
                    continue
                else:
                    count = 1

            _, id_lane, _ = _extract_slot_id_lanes(seg_u)
            lane = explicit_lane or id_lane or current_physical_lane
            if lane is None:
                continue
            if explicit_lane or id_lane:
                current_physical_lane = lane

            saw_slot = True
            gens = [
                int(g)
                for g in re.findall(
                    r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?",
                    seg_u,
                )
            ]
            version = f"PCIe {max(gens)}.0" if gens else None
            effective_context = context_group or current_context
            if context_group is not None:
                current_context = context_group

            if effective_context == "CPU" and count == 1:
                dedupe_key = (effective_context, lane)
                prev_count, prev_version = contextual_best.get(dedupe_key, (0, None))
                prev_gen = (
                    int(re.search(r"\d+", prev_version).group(0))
                    if isinstance(prev_version, str) and re.search(r"\d+", prev_version)
                    else 0
                )
                curr_gen = (
                    int(re.search(r"\d+", version).group(0))
                    if isinstance(version, str) and re.search(r"\d+", version)
                    else 0
                )
                if count > prev_count or curr_gen > prev_gen:
                    contextual_best[dedupe_key] = (count, version)
                continue

            merged[(lane, version)] = max(merged.get((lane, version), 0), count)

        if not saw_slot:
            return None

        out_counts = dict(merged)
        for (_, lane), (count, version) in contextual_best.items():
            key = (lane, version)
            out_counts[key] = min(
                _MAX_PCIE_SLOT_COUNT, out_counts.get(key, 0) + count
            )
        out = [
            {"count": count, "lane": lane, "version": version}
            for (lane, version), count in out_counts.items()
        ]
        return out

    for line in lines:
        line_u = line.upper()
        if "PCI" not in line_u:
            continue
        if any(
            token in line_u
            for token in (
                "STORAGE CONTROLLER",
                "SSD SUPPORT",
                "SSD SUPPORT)",
                "SSD",
                "SOCKET 3",
                "RAID",
                "WIFI MODULE",
                "CNVIO",
                "CNVIO2",
            )
        ) and not re.search(r"\b(PCIEX\d+|PCI[_\s-]?E\d+)\b", line_u):
            continue
        if "KEY E" in line_u and not re.search(
            r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(?:1|4|8|16)\b[^\n\r]{0,40}\bSLOTS?\b",
            line_u,
            flags=re.IGNORECASE,
        ):
            continue
        if ("M.2" in line_u or "M2" in line_u) and not (
            re.search(
                r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(?:1|4|8|16)\b[^\n\r]{0,40}\bSLOTS?\b",
                line_u,
                flags=re.IGNORECASE,
            )
            or _explicit_lane_mentions(line_u) >= 2
        ):
            continue
        if not any(x in line_u for x in ("SLOT", "SLOTS", "СЛОТ", "PCI", "EXPRESS")):
            continue

        key_value_slots = _parse_key_value_line(line)
        if key_value_slots is not None:
            key_value_out.extend(key_value_slots)
            continue

        contextual_slots = _parse_contextual_semicolon_line(line)
        if contextual_slots is not None:
            narrative_out.extend(contextual_slots)
            continue

        compact_slots = _parse_compact_narrative_line(line)
        if compact_slots is not None:
            narrative_out.extend(compact_slots)
            continue

        if ("M.2" in line_u or "M2" in line_u) and not any(
            x in line_u
            for x in (
                "PCI SLOTS",
                "РАЗШИРИТЕЛ",
                "EXPANSION",
                "PCI_E",
                "PCIEX",
            )
        ):
            if not re.search(r"\bX(1|4|8|16)\s+SLOTS?\b", line_u):
                continue

        slot_clause_start_re = re.compile(
            r"(?=(?:\b(?:CPU|CHIPSET|PCH)\s*:)?\s*[-*•]?\s*\d+\s*[xX×*]?\s*"
            r"PCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(?:1|4|8|16)\b"
            r"[^\n\r]{0,40}\bSLOTS?\b)",
            flags=re.IGNORECASE,
        )
        segments = []
        for seg in re.split(r"[;]+", line):
            seg = re.sub(r"\s+", " ", seg).strip()
            if not seg:
                continue
            starts = [m.start() for m in slot_clause_start_re.finditer(seg)]
            if starts and starts[0] != 0:
                starts.insert(0, 0)
            if len(starts) <= 1:
                segments.append(seg)
                continue
            starts.append(len(seg))
            for idx in range(len(starts) - 1):
                part = seg[starts[idx] : starts[idx + 1]].strip(" -,")
                if part:
                    segments.append(part)
        blocks: list[list[str]] = []
        current_block: list[str] | None = None
        pending_context_segments: list[str] = []
        for seg in segments:
            seg_u = seg.upper()
            if re.search(r"\bSHARES?\s+BANDWIDTH\s+WITH\b", seg_u, flags=re.IGNORECASE):
                if current_block:
                    blocks.append(current_block)
                    current_block = None
                pending_context_segments = []
                continue
            if re.search(
                r"\b(SPECIFICATIONS?\s+VARY\s+BY\s+CPU|VARY\s+BY\s+CPU\s+TYPES?|CPU|CHIPSET|PCH|RYZEN|CORE|THREADRIPPER|XEON|PROCESSORS?)\b",
                seg_u,
                flags=re.IGNORECASE,
            ) and "PCI" not in seg_u:
                pending_context_segments.append(seg)
                continue
            if slot_def_re.search(seg_u):
                if current_block:
                    blocks.append(current_block)
                current_block = pending_context_segments + [seg]
                pending_context_segments = []
            elif current_block is not None:
                current_block.append(seg)
            elif "PCI" in seg_u:
                blocks.append(pending_context_segments + [seg])
                pending_context_segments = []
        if current_block:
            blocks.append(current_block)
        if not blocks:
            blocks = [[line]]

        per_line = {}
        contextual_slot_best: dict[tuple[str, str], tuple[int, str | None]] = {}
        for block in blocks:
            block_text = "; ".join(block)
            block_u = block_text.upper()
            if "PCI" not in block_u:
                continue
            if any(
                token in block_u
                for token in (
                    "STORAGE CONTROLLER",
                    "SSD SUPPORT",
                    "SOCKET 3",
                    "RAID",
                    "WIFI MODULE",
                    "CNVIO",
                    "CNVIO2",
                )
            ) and not re.search(r"\b(PCIEX\d+|PCI[_\s-]?E\d+)\b", block_u):
                continue
            if re.search(r"\bSHARES?\s+BANDWIDTH\s+WITH\b", block_u, flags=re.IGNORECASE):
                continue

            count = None
            explicit_lane = None
            m_def = slot_def_re.search(block_u)
            if m_def:
                count = int(m_def.group(1))
                explicit_lane = f"x{m_def.group(2)}"
            else:
                m_size = re.search(
                    r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*(?:[3-7](?:\.0)?\s*)?X(1|4|8|16)\b[^\n\r]{0,40}\bSLOTS?\b",
                    block_u,
                    flags=re.IGNORECASE,
                )
                if m_size:
                    explicit_lane = f"x{m_size.group(1)}"
                m_count = re.search(
                    r"\b(\d+)\s*[xX×*]?\s*PCI(?:E|[- ]E|\s*EXPRESS)?\b",
                    block_u,
                    flags=re.IGNORECASE,
                )
                if m_count:
                    count = int(m_count.group(1))

            id_count, id_lane, id_lane_set = _extract_slot_id_lanes(block_u)
            if count is None:
                count = id_count if id_count > 0 else 1
            elif id_count > count:
                # If explicit id list names more distinct slots, trust id count.
                count = id_count
            count = max(1, min(count, _MAX_PCIE_SLOT_COUNT))

            lane = explicit_lane
            if lane is None and id_lane is not None:
                lane = id_lane
            if lane not in ("x1", "x4", "x8", "x16"):
                continue
            if id_count > 0:
                slot_id_narrative_lanes.add(lane)
                slot_id_narrative_lanes.update(id_lane_set)

            gens = [
                int(g)
                for g in re.findall(
                    r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?",
                    block_u,
                )
            ]
            version = f"PCIe {max(gens)}.0" if gens else None
            context_group = _block_context_group(block_u)
            if context_group == "CPU" and id_count == 0 and count == 1:
                dedupe_key = (context_group, lane)
                prev_count, prev_version = contextual_slot_best.get(dedupe_key, (0, None))
                prev_gen = (
                    int(re.search(r"\d+", prev_version).group(0))
                    if isinstance(prev_version, str) and re.search(r"\d+", prev_version)
                    else 0
                )
                curr_gen = (
                    int(re.search(r"\d+", version).group(0))
                    if isinstance(version, str) and re.search(r"\d+", version)
                    else 0
                )
                if count > prev_count or curr_gen > prev_gen:
                    contextual_slot_best[dedupe_key] = (count, version)
                continue
            key = (lane, version)
            per_line[key] = min(8, per_line.get(key, 0) + count)

        for (_, lane), (count, version) in contextual_slot_best.items():
            narrative_out.append({"count": count, "lane": lane, "version": version})

        for (lane, ver), count in per_line.items():
            narrative_out.append({"count": count, "lane": lane, "version": ver})

    known_lane_totals: dict[str, int] = {}
    for item in narrative_out:
        lane = item.get("lane")
        count = _to_int(item.get("count"))
        if lane in ("x1", "x4", "x8", "x16") and count:
            known_lane_totals[lane] = known_lane_totals.get(lane, 0) + count

    def _prune_null_lane_duplicates(entries: list[dict]) -> list[dict]:
        versioned_by_lane: dict[str, int] = {}
        for item in entries:
            lane = item.get("lane")
            count = _to_int(item.get("count"))
            if lane in ("x1", "x4", "x8", "x16") and count and item.get("version") is not None:
                versioned_by_lane[lane] = versioned_by_lane.get(lane, 0) + count
        pruned = []
        for item in entries:
            lane = item.get("lane")
            count = _to_int(item.get("count"))
            if (
                lane in versioned_by_lane
                and item.get("version") is None
                and count is not None
                and count > 0
            ):
                remaining = count - versioned_by_lane[lane]
                if remaining <= 0:
                    continue
                item = {**item, "count": remaining}
            pruned.append(item)
        return pruned

    adjusted_key_value = []
    for item in key_value_out:
        lane = item.get("lane")
        count = _to_int(item.get("count"))
        if lane not in ("x1", "x4", "x8", "x16") or count is None or count <= 0:
            continue
        if lane in slot_id_narrative_lanes:
            continue
        known_count = known_lane_totals.get(lane, 0)
        remaining = count - known_count
        if remaining <= 0:
            continue
        adjusted_key_value.append(
            {
                "count": remaining,
                "lane": lane,
                "version": item.get("version"),
            }
        )

    return _prune_null_lane_duplicates(narrative_out + adjusted_key_value)


def _extract_usb_ports(text: str) -> list:
    out = []
    raw_lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in re.split(r"[\n\r;]+", text)
        if line and line.strip()
    ]
    lines = []
    for line in raw_lines:
        parts = re.split(
            r",\s*(?=(?:\d+\s*[xX×*]?\s*)?(?:USB|THUNDERBOLT)\b)",
            line,
            flags=re.IGNORECASE,
        )
        if len(parts) <= 1:
            lines.append(line)
            continue
        for part in parts:
            part = part.strip(" ,")
            if part:
                lines.append(part)
    indexed_lines = list(enumerate(lines))

    def _usb_entry(
        count,
        version,
        gen,
        usb_type,
        matched_text: str,
        *,
        specificity: int = 3,
    ):
        version_val = version
        if (
            version_val
            and re.search(r"G(?:BPS|BIT/S|B/S)", matched_text, flags=re.IGNORECASE)
            and re.fullmatch(r"\d{1,2}(?:\.\d)?", str(version_val))
        ):
            version_val = f"{version_val}Gbps"
        return {
            "count": count,
            "type": (
                usb_type.upper().replace(" ", "").replace("(", "").replace(")", "")
                if usb_type
                else "USB"
            ),
            "version": version_val if version_val else None,
            "gen": gen.title() if gen else None,
            "_specificity": specificity,
        }

    def _rear_adjusted_count(clause: str, base_count: int) -> Optional[int]:
        clause_u = clause.upper()
        rear_counts = []
        for pat in (
            r"\b(\d+)\s*(?:REAR|ON THE BACK PANEL|BACK PANEL|НА ЗАДНИЯ ПАНЕЛ|ЗАДНИ ПОРТОВЕ)\b",
            r"\b(\d+)\s+ON\s+REAR(?:\s+I/?OS?)?\b",
            r"\b(\d+)\s+ON\s+THE\s+REAR\b",
        ):
            rear_counts.extend(int(x) for x in re.findall(pat, clause_u))
        front_only = bool(
            re.search(
                r"\b(FRONT|FRONT PANEL|INTERNAL|HEADER|HEADERS|ВЪТРЕШ|ПРЕДЕН ПАНЕЛ)\b",
                clause_u,
            )
        )
        if rear_counts:
            return max(rear_counts)
        if front_only:
            return None
        return base_count

    def _match_fragment(line: str, match, lookahead: int = 96) -> str:
        return line[match.start() : min(len(line), match.end() + lookahead)]

    def _append_typed_breakout_entries(
        line: str,
        match_end: int,
        base_count: int,
        version: str | None,
        gen: str | None,
        matched_text: str,
    ) -> int:
        fragment = line[match_end : match_end + 220]
        seen: set[tuple[int, str]] = set()
        entries = 0
        paren_details = re.findall(r"\(([^)]{1,180})\)", fragment)
        for detail in paren_details[:3]:
            explicit_matches = re.findall(
                r"(?:^|[+,/;])\s*(\d+)\s*[xX×*]?\s*(?:USB(?:\s*\d{1,2}(?:\.\d)?)?(?:\s*GEN\s*\d(?:X\d)?)?\s*)?\(?\s*TYPE[- ]?(A|B|C|MINI)\b",
                detail,
                flags=re.IGNORECASE,
            )
            if explicit_matches:
                for c, t in explicit_matches:
                    cnt = int(c)
                    sig = (cnt, t.upper())
                    if sig in seen or not (1 <= cnt <= 30):
                        continue
                    seen.add(sig)
                    out.append(
                        _usb_entry(
                            cnt,
                            version,
                            gen,
                            f"TYPE-{t.upper()}",
                            matched_text,
                            specificity=4,
                        )
                    )
                    entries += 1
                continue

            type_match = re.search(
                r"TYPE[- ]?(A|B|C|MINI)\b", detail, flags=re.IGNORECASE
            )
            if not type_match or not (1 <= base_count <= 30):
                continue
            sig = (base_count, type_match.group(1).upper())
            if sig in seen:
                continue
            seen.add(sig)
            out.append(
                _usb_entry(
                    base_count,
                    version,
                    gen,
                    f"TYPE-{type_match.group(1).upper()}",
                    matched_text,
                    specificity=4,
                )
            )
            entries += 1
        return entries

    explicit_port_pattern = re.compile(
        r"\b(\d+)\s*[xX×*]?\s*USB\s*(\d{1,2}(?:\.\d)?)\s*(Gen\s*\d(?:x\d)?)?\s*(Type[- ]?(?:A|B|C|Mini)|USB[- ]?C)?(?:\s*PORTS?)?\b",
        flags=re.IGNORECASE,
    )
    explicit_speed_pattern = re.compile(
        r"\b(\d+)\s*[xX×*]?\s*USB\s*(\d{1,2}\s*G(?:BPS|BIT/S|B/S))\s*(?:\((Type[- ]?(?:A|B|C|Mini))\))?(?:\s*PORTS?)?\b",
        flags=re.IGNORECASE,
    )
    key_row_breakout_pattern = re.compile(
        r"\bUSB\s*(\d{1,2}(?:\.\d)?)\s*(Gen\s*\d(?:x\d)?)?\s*[:=]\s*(\d+)\b",
        flags=re.IGNORECASE,
    )
    tb_pattern = re.compile(
        r"(\d+)\s*[xX×*]?\s*THUNDERBOLT\s*(4|5)\b", flags=re.IGNORECASE
    )
    consumed_lines: set[int] = set()
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        matched_any = False
        for m in key_row_breakout_pattern.finditer(line):
            count = _rear_adjusted_count(_match_fragment(line, m), int(m.group(3)))
            if count is None or count <= 0 or count > 30:
                continue
            typed_entries = _append_typed_breakout_entries(
                line, m.end(), count, m.group(1), m.group(2), m.group(0)
            )
            if typed_entries:
                matched_any = True
        if matched_any:
            consumed_lines.add(idx)

    for idx, line in indexed_lines:
        matched_any = False
        if idx in consumed_lines:
            continue
        for m in explicit_port_pattern.finditer(line):
            count = _rear_adjusted_count(_match_fragment(line, m), int(m.group(1)))
            if count is None or count <= 0 or count > 30:
                continue
            if m.group(4) is None:
                typed_entries = _append_typed_breakout_entries(
                    line, m.end(), count, m.group(2), m.group(3), m.group(0)
                )
                if typed_entries:
                    matched_any = True
                    continue
            out.append(
                _usb_entry(
                    count,
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(0),
                    specificity=4 if m.group(4) else 3,
                )
            )
            matched_any = True
        for m in explicit_speed_pattern.finditer(line):
            count = _rear_adjusted_count(_match_fragment(line, m), int(m.group(1)))
            if count is None or count <= 0 or count > 30:
                continue
            if m.group(3) is None:
                typed_entries = _append_typed_breakout_entries(
                    line, m.end(), count, m.group(2), None, m.group(0)
                )
                if typed_entries:
                    matched_any = True
                    continue
            out.append(
                _usb_entry(
                    count,
                    m.group(2),
                    None,
                    m.group(3),
                    m.group(0),
                    specificity=4 if m.group(3) else 3,
                )
            )
            matched_any = True
        if matched_any:
            consumed_lines.add(idx)

    # Treat Thunderbolt 4/5 ports as USB4-class Type-C ports and consume the clause
    # so generic USB-C matchers do not double-count the embedded USB4 wording.
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        matched_any = False
        for m in tb_pattern.finditer(line):
            count = _rear_adjusted_count(_match_fragment(line, m), int(m.group(1)))
            if count is None:
                continue
            if count <= 0 or count > 12:
                continue
            out.append(
                _usb_entry(count, "4.0", None, "TYPE-C", m.group(0), specificity=4)
            )
            matched_any = True
        if matched_any:
            consumed_lines.add(idx)

    # Explicit USB-C / Type-C segments often appear separately from generic USB counts.
    usb_c_pattern = re.compile(
        r"\b(\d+)\s*[xX×*]?\s*(?:USB[- ]?C|USB\s*TYPE[- ]?C|TYPE[- ]?C)\s*(?:(\d{1,2}(?:\.\d)?)\b(?!\s*G(?:BPS|BIT/S|B/S)))?\s*(?:\(?\s*(\d{1,2}\s*G(?:BPS|BIT/S|B/S))\s*\)?)?\s*(Gen\s*\d(?:x\d)?)?",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in usb_c_pattern.finditer(line):
            count = int(m.group(1))
            if count <= 0 or count > 30:
                continue
            version = m.group(3) or m.group(2)
            gen = m.group(4)
            out.append(
                _usb_entry(count, version, gen, "TYPE-C", m.group(0), specificity=4)
            )

    usb_c_support_pattern = re.compile(
        r"(\d+)\s*[xX×*]?\s*USB\s*TYPE[- ]?C[^\n\r;]{0,120}?\bUSB\s*(\d{1,2}(?:\.\d)?)\s*(Gen\s*\d(?:x\d)?)?",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in usb_c_support_pattern.finditer(line):
            count = int(m.group(1))
            if count <= 0 or count > 30:
                continue
            version = m.group(2)
            gen = m.group(3)
            out.append(
                _usb_entry(count, version, gen, "TYPE-C", m.group(0), specificity=4)
            )

    structured_pattern = re.compile(
        r"(\d+)\s*[xX×*]?\s*USB\s*(?:(\d{1,2}(?:\.\d)?)\b(?!\s*G(?:BPS|BIT/S|B/S)))?\s*(?:\(?\s*(\d{1,2}\s*G(?:BPS|BIT/S|B/S))\s*\)?)?\s*PORT(?:S|\(S\))?",
        flags=re.IGNORECASE,
    )
    for idx, raw_line in indexed_lines:
        if idx in consumed_lines:
            continue
        line = raw_line.replace("®", "").replace("™", "")
        line_entries = 0
        for m in structured_pattern.finditer(line):
            base_count = int(m.group(1))
            base_count = _rear_adjusted_count(_match_fragment(line, m), base_count)
            if base_count is None:
                continue
            if base_count <= 0 or base_count > 30:
                continue
            usb_num = m.group(2)
            speed = m.group(3)
            version = speed or usb_num
            # Parse typed breakouts in the nearest parenthesized detail after this USB segment.
            typed_entries = _append_typed_breakout_entries(
                line, m.end(), base_count, version, None, m.group(0)
            )
            if typed_entries:
                line_entries += typed_entries
                continue
            tail = line[m.end() :]
            detail = ""
            paren = re.match(r"\s*\(([^)]{1,180})\)", tail)
            if paren:
                detail = paren.group(1)
            lookahead = f"{detail} {tail[:90]}"
            if re.search(r"USB\s*TYPE[- ]?C|TYPE[- ]?C", lookahead, re.IGNORECASE):
                out.append(
                    _usb_entry(
                        base_count,
                        version,
                        None,
                        "TYPE-C",
                        m.group(0),
                        specificity=4,
                    )
                )
            elif re.search(r"USB\s*TYPE[- ]?B|TYPE[- ]?B", lookahead, re.IGNORECASE):
                out.append(
                    _usb_entry(
                        base_count,
                        version,
                        None,
                        "TYPE-B",
                        m.group(0),
                        specificity=4,
                    )
                )
            elif re.search(r"USB\s*TYPE[- ]?A|TYPE[- ]?A", lookahead, re.IGNORECASE):
                out.append(
                    _usb_entry(
                        base_count,
                        version,
                        None,
                        "TYPE-A",
                        m.group(0),
                        specificity=4,
                    )
                )
            else:
                out.append(
                    _usb_entry(
                        base_count,
                        version,
                        None,
                        None,
                        m.group(0),
                        specificity=3,
                    )
                )
            line_entries += 1
        if line_entries > 0:
            consumed_lines.add(idx)

    pattern = re.compile(
        r"(\d+)\s*[xX×*]?\s*USB\s*(\d{1,2}(?:\.\d)?)?\s*(?:G(?:BPS|BIT/S|B/S))?\s*(Gen\s*\d(?:x\d)?)?\s*\(?\s*(Type[- ]?(?:A|B|C|Mini))?\s*\)?",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in pattern.finditer(line):
            count = int(m.group(1))
            count = _rear_adjusted_count(m.group(0), count)
            if count is None:
                continue
            version = m.group(2)
            gen = m.group(3)
            usb_type = m.group(4)
            if count <= 0 or count > 30:
                continue
            out.append(
                _usb_entry(
                    count,
                    version,
                    gen,
                    usb_type,
                    m.group(0),
                    specificity=4 if usb_type else 3,
                )
            )

    implicit_port_pattern = re.compile(
        r"\bUSB\s*(\d{1,2}(?:\.\d)?)\s*(Gen\s*\d(?:x\d)?)?\s*(Type[- ]?(?:A|B|C|Mini)|USB[- ]?C)?\s*PORTS?\b",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in implicit_port_pattern.finditer(line):
            count = _rear_adjusted_count(_match_fragment(line, m), 1)
            if count is None:
                continue
            version = m.group(1)
            gen = m.group(2)
            usb_type = m.group(3)
            out.append(
                _usb_entry(
                    count,
                    version,
                    gen,
                    usb_type,
                    m.group(0),
                    specificity=4 if usb_type else 3,
                )
            )
            consumed_lines.add(idx)
    tail_count_pattern = re.compile(
        r"USB\s*(\d{1,2}(?:\.\d)?)?\s*(?:G(?:BPS|BIT/S|B/S))?\s*(Gen\s*\d(?:x\d)?)?\s*\(?\s*(Type[- ]?(?:A|B|C|Mini))?\s*\)?[^\n\r,;]{0,40}?[xX×*]\s*(\d+)",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in tail_count_pattern.finditer(line):
            count = int(m.group(4))
            count = _rear_adjusted_count(m.group(0), count)
            if count is None:
                continue
            version = m.group(1)
            gen = m.group(2)
            usb_type = m.group(3)
            if count <= 0 or count > 30:
                continue
            out.append(
                _usb_entry(
                    count,
                    version,
                    gen,
                    usb_type,
                    m.group(0),
                    specificity=4 if usb_type else 3,
                )
            )

    key_first_pattern = re.compile(
        r"\bUSB\s*(\d{1,2}(?:\.\d)?)?\s*(?:G(?:BPS|BIT/S|B/S))?\s*(Gen\s*\d(?:x\d)?)?\s*(?:Type[- ]?(?:A|B|C|Mini))?\s*[:=]\s*(\d+)",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for m in key_first_pattern.finditer(line):
            version = m.group(1)
            gen = m.group(2)
            count = _rear_adjusted_count(m.group(0), int(m.group(3)))
            if count is None:
                continue
            if count <= 0 or count > 30:
                continue
            typed_entries = _append_typed_breakout_entries(
                line, m.end(), count, version, gen, m.group(0)
            )
            if typed_entries:
                consumed_lines.add(idx)
                continue
            out.append(
                _usb_entry(count, version, gen, None, m.group(0), specificity=1)
            )

    type_only_key_pattern = re.compile(
        r"\bUSB\s*TYPE[- ]?(A|B|C|MINI)\b\s*[:=]?\s*(\d+)",
        flags=re.IGNORECASE,
    )
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        for usb_type, raw_count in type_only_key_pattern.findall(line):
            count = _rear_adjusted_count(line, int(raw_count))
            if count is None or count <= 0 or count > 30:
                continue
            out.append(
                _usb_entry(
                    count,
                    None,
                    None,
                    f"TYPE-{usb_type.upper()}",
                    line,
                    specificity=1,
                )
            )

    # Lines/tokens like "USB 20Gbps" often imply a single rear USB port.
    for idx, line in indexed_lines:
        if idx in consumed_lines:
            continue
        m = re.fullmatch(
            r"USB\s*(\d{1,2}(?:\.\d)?)\s*(G(?:BPS|BIT/S|B/S))\s*(Gen\s*\d(?:x\d)?)?\s*\(?\s*(Type[- ]?(?:A|B|C|Mini))?\s*\)?",
            line,
            flags=re.IGNORECASE,
        )
        if not m:
            for m2 in re.finditer(
                r"(?:^|[:;,])\s*USB\s*(\d{1,2}(?:\.\d)?)\s*(G(?:BPS|BIT/S|B/S))\s*(Gen\s*\d(?:x\d)?)?\s*\(?\s*(Type[- ]?(?:A|B|C|Mini))?\s*\)?",
                line,
                flags=re.IGNORECASE,
            ):
                count = _rear_adjusted_count(m2.group(0), 1)
                if count is None:
                    continue
                out.append(
                    _usb_entry(
                        count,
                        m2.group(1),
                        m2.group(3),
                        m2.group(4),
                        m2.group(0),
                        specificity=4 if m2.group(4) else 3,
                    )
                )
            continue
        count = _rear_adjusted_count(line, 1)
        if count is None:
            continue
        out.append(
            _usb_entry(
                count,
                m.group(1),
                m.group(3),
                m.group(4),
                line,
                specificity=4 if m.group(4) else 3,
            )
        )
    return out


def _extract_count(label: str, text: str) -> Optional[int]:
    if not text:
        return None
    normalized_text = (
        str(text)
        .replace("HDMI™", "HDMI")
        .replace("HDMITM", "HDMI")
        .replace("HDMI TM", "HDMI")
        .replace("Display Port", "DisplayPort")
        .replace("DISPLAY PORT", "DISPLAYPORT")
        .replace("Display Ports", "DisplayPorts")
        .replace("DISPLAY PORTS", "DISPLAYPORTS")
    )
    if label.upper() == "DISPLAYPORT":
        pattern_label = r"DISPLAYPORTS?"
    else:
        pattern_label = r"HDMI(?:TM|™)?" if label.upper() == "HDMI" else re.escape(label)
    segments = [
        re.sub(r"\s+", " ", seg).strip()
        for seg in re.split(r"[\n\r,;|]+", normalized_text)
        if seg and seg.strip()
    ]
    segments = list(dict.fromkeys(segments))

    vals = []
    mention = False
    mention_without_digits = False
    mention_with_version_only = False
    for seg in segments:
        if not re.search(rf"\b{pattern_label}\b", seg, flags=re.IGNORECASE):
            continue
        mention = True
        if not re.search(r"\d", seg):
            mention_without_digits = True
        elif re.search(rf"\b{pattern_label}\b\s*\d+\.\d+\b", seg, flags=re.IGNORECASE):
            mention_with_version_only = True
        m0 = re.search(
            rf"\b(\d+)\s*(?:[x×*]\s*)?(?:MINI\s+)?{pattern_label}\b",
            seg,
            flags=re.IGNORECASE,
        )
        if m0:
            vals.append(int(m0.group(1)))
            continue
        m1 = re.search(
            rf"\b(\d+)\s*[x×*]\s*{pattern_label}\b", seg, flags=re.IGNORECASE
        )
        if m1:
            vals.append(int(m1.group(1)))
            continue
        m2 = re.search(
            rf"\b{pattern_label}\b\s*[:=]?\s*(\d+)(?!\s*\.)\b",
            seg,
            flags=re.IGNORECASE,
        )
        if m2:
            vals.append(int(m2.group(1)))

    vals = [v for v in vals if 0 < v <= 16]
    if vals:
        return max(vals)
    if mention and (mention_without_digits or mention_with_version_only):
        return 1
    return None


def _extract_video_info(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None

    normalized_text = (
        str(text)
        .replace("HDMI™", "HDMI")
        .replace("HDMITM", "HDMI")
        .replace("HDMI TM", "HDMI")
        .replace("DISPLAY PORT", "DISPLAYPORT")
        .replace("DISPLAY PORTS", "DISPLAYPORTS")
    )
    normalized_text = re.sub(
        r"(?<=[A-Z0-9\)])\s+(?=\d+\s*[x×*]?\s*(?:THUNDERBOLT|USB(?:\s*\d(?:\.\d)?)?(?:\s*GEN\s*\d(?:X\d)?)?\s*TYPE[- ]?C|USB[- ]?C|TYPE[- ]?C|(?:MINI\s+)?DISPLAYPORTS?))",
        "; ",
        normalized_text,
        flags=re.IGNORECASE,
    )
    clauses = [
        re.sub(r"\s+", " ", clause).strip()
        for clause in re.split(r"[\n\r;|]+", normalized_text)
        if clause and clause.strip()
    ]
    clauses = list(dict.fromkeys(clauses))

    def _is_front_only(clause_u: str) -> bool:
        has_front = bool(
            re.search(r"\bFRONT(?:\s+PANEL)?\b|НА\s+ПРЕДНИЯ\s+ПАНЕЛ", clause_u)
        )
        has_rear = bool(
            re.search(
                r"\bREAR\b|\bBACK PANEL\b|\bI/O\b|НА\s+ЗАДНИЯ\s+ПАНЕЛ|ЗАДНИЯ\s+ПАНЕЛ",
                clause_u,
            )
        )
        return has_front and not has_rear

    def _clause_count(clause_u: str, token_pattern: str) -> Optional[int]:
        m = re.search(
            rf"\b(\d+)\s*(?:[x×*]\s*)?(?:MINI\s+)?{token_pattern}\b",
            clause_u,
            flags=re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
        m = re.search(
            rf"\b(?:MINI\s+)?{token_pattern}\b\s*[:=]?\s*(\d+)(?!\s*\.)\b",
            clause_u,
            flags=re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
        if re.search(rf"\b(?:MINI\s+)?{token_pattern}\b", clause_u, flags=re.IGNORECASE):
            return 1
        return None

    hdmi_counts = []
    fallback_video_clauses: list[str] = []
    physical_dp_counts: dict[str, int] = {}
    dp_alt_mode_counts: dict[str, int] = {}

    def _physical_dp_signature(clause_u: str, count: int) -> str:
        kind = "MINI" if "MINI DISPLAYPORT" in clause_u else "DISPLAYPORT"
        return f"{kind}:{count}"

    def _is_support_only_dp_clause(clause_u: str) -> bool:
        if not re.search(r"DISPLAYPORT", clause_u, flags=re.IGNORECASE):
            return False
        if re.search(
            r"\b\d+\s*(?:[x×*]\s*)?(?:MINI\s+)?DISPLAYPORTS?\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            return False
        if re.search(
            r"\b(?:MINI\s+)?DISPLAYPORTS?\b\s*(?:PORT|CONNECTOR|OUTPUT)\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            return False
        return bool(
            re.match(r"^\s*SUPPORTS?\b", clause_u, flags=re.IGNORECASE)
            or re.search(r"\bVERSION\b", clause_u, flags=re.IGNORECASE)
        )

    def _dp_alt_signature(clause_u: str, count: int) -> str:
        signature = re.sub(r"\s+", " ", clause_u).strip(" ,;")
        signature = re.sub(r"\bSUPPORTS?\b", "", signature, flags=re.IGNORECASE)
        signature = re.sub(r"\s+", " ", signature).strip(" ,;")
        return f"{signature}:{count}"

    def _dp_alt_count(clause_u: str) -> int:
        patterns = (
            r"\b(\d+)\s*(?:[x×*]\s*)?[^;\n]{0,24}?THUNDERBOLT(?:\s*\d+)?\b",
            r"\b(\d+)\s*(?:[x×*]\s*)?[^;\n]{0,24}?USB4\b",
            r"\b(\d+)\s*(?:[x×*]\s*)?USB(?:\s*\d(?:\.\d)?)?(?:\s*GEN\s*\d(?:X\d)?)?[^;\n]{0,32}?TYPE[- ]?C\b",
            r"\b(\d+)\s*(?:[x×*]\s*)?USB[- ]?C\b",
            r"\b(\d+)\s*(?:[x×*]\s*)?TYPE[- ]?C\b",
        )
        for pat in patterns:
            m = re.search(pat, clause_u, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
        return 1

    for clause in clauses:
        clause_u = clause.upper()
        if _is_front_only(clause_u):
            continue

        fallback_video_clauses.append(clause)

        hdmi_count = _clause_count(clause_u, r"HDMI(?:TM|™)?S?")
        if hdmi_count is not None:
            hdmi_counts.append(hdmi_count)

        has_usb_dp_context = bool(
            re.search(r"THUNDERBOLT|USB4|USB[- ]?C|TYPE[- ]?C", clause_u)
        )
        explicit_physical_dp = bool(
            re.search(
                r"\b\d+\s*(?:[x×*]\s*)?(?:MINI\s+)?DISPLAYPORTS?\b",
                clause_u,
                flags=re.IGNORECASE,
            )
            or (
                not has_usb_dp_context
                and re.search(
                    r"\b(?:MINI\s+)?DISPLAYPORTS?\b",
                    clause_u,
                    flags=re.IGNORECASE,
                )
            )
        )
        physical_dp_count = None
        if not _is_support_only_dp_clause(clause_u) and (
            not has_usb_dp_context or explicit_physical_dp
        ):
            physical_dp_count = _clause_count(clause_u, r"DISPLAYPORTS?")
            if physical_dp_count is None:
                physical_dp_count = _clause_count(clause_u, r"MINI\s+DISPLAYPORTS?")
        if physical_dp_count is not None:
            signature = _physical_dp_signature(clause_u, physical_dp_count)
            physical_dp_counts[signature] = max(
                physical_dp_counts.get(signature, 0), physical_dp_count
            )

        if not re.search(
            r"DISPLAYPORT|VIDEO OUTPUT|DP(?:-ALT|\s*ALT)|\bDP1\.4A?\b|\bDP\s*1\.4A?\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            continue
        if not re.search(r"THUNDERBOLT|USB4|USB[- ]?C|TYPE[- ]?C", clause_u):
            continue
        dp_count = _dp_alt_count(clause_u)
        signature = _dp_alt_signature(clause_u, dp_count)
        dp_alt_mode_counts[signature] = max(dp_alt_mode_counts.get(signature, 0), dp_count)

    hdmi = max(hdmi_counts) if hdmi_counts else None
    dp_total = None
    if physical_dp_counts or dp_alt_mode_counts:
        dp_total = sum(physical_dp_counts.values()) + sum(dp_alt_mode_counts.values())
    elif fallback_video_clauses:
        dp_total = _extract_count("DISPLAYPORT", "\n".join(fallback_video_clauses))
    return dp_total, hdmi


def _extract_lan_info(text: str) -> tuple[Optional[int], Optional[str]]:
    if not text:
        return None, None

    text = re.sub(
        r"(?<=[A-ZА-Я0-9\)])(?=\d+\s*[x×*]?\s*(?:INTEL|REALTEK|MARVELL|AQUANTIA|BROADCOM|KILLER|RTL\d+[A-Z0-9]*|AQC\d+[A-Z0-9]*|RJ-?45)\b)",
        "; ",
        str(text).upper(),
        flags=re.IGNORECASE,
    )

    segments = [
        re.sub(r"\s+", " ", seg).strip()
        for seg in re.split(r"[\n\r;|]+", text)
        if seg and seg.strip()
    ]
    segments = list(dict.fromkeys(segments))
    lan_segments = [
        seg
        for seg in segments
        if re.search(
            r"\b(LAN|RJ-?45|ETHERNET|GBE|GIGABIT)\b", seg, flags=re.IGNORECASE
        )
        and not re.search(r"\bWAKE\s+ON\s+LAN\b", seg, flags=re.IGNORECASE)
    ]
    if not lan_segments and not re.search(
        r"\b(LAN|RJ-?45|ETHERNET|GBE|GIGABIT)\b", text, flags=re.IGNORECASE
    ):
        return None, None
    if not lan_segments:
        lan_segments = [text]

    lan_clauses = []
    for seg in lan_segments:
        for clause in re.split(r",", seg):
            clause = re.sub(r"\s+", " ", clause).strip()
            if not clause:
                continue
            if re.search(r"\bWAKE\s+ON\s+LAN\b", clause, flags=re.IGNORECASE):
                continue
            if re.search(
                r"\b(LAN|RJ-?45|ETHERNET|GBE|GIGABIT)\b", clause, flags=re.IGNORECASE
            ):
                lan_clauses.append(clause)
    if not lan_clauses:
        lan_clauses = lan_segments

    def _extract_vendor(raw: str) -> Optional[str]:
        m = re.search(
            r"\b(INTEL|REALTEK|MARVELL|AQUANTIA|BROADCOM|KILLER|RTL\d+[A-Z0-9]*|AQC\d+[A-Z0-9]*)\b",
            raw,
            flags=re.IGNORECASE,
        )
        return m.group(1).upper() if m else None

    def _extract_speed_token(raw: str) -> Optional[str]:
        m = re.search(
            r"\b(10|5|2\.5|1)\s*G(?:IGABIT|B)?(?:\s*ETHERNET)?\b",
            raw,
            flags=re.IGNORECASE,
        )
        if m:
            return m.group(1)
        m = re.search(
            r"((?:\d{2,5}\s*/\s*)+\d{2,5})\s*M(?:BIT|B)(?:/S|PS)?",
            raw,
            flags=re.IGNORECASE,
        )
        if not m:
            return None
        nums = [int(x) for x in re.findall(r"\d{2,5}", m.group(1))]
        if not nums:
            return None
        top = max(nums)
        if top >= 1000:
            return f"{top / 1000:g}"
        return None

    def _endpoint_signature(raw_sig: str, vendor: str | None, speed: str | None) -> str:
        sig = str(raw_sig).upper().replace("®", "").replace("™", "")
        sig = re.sub(
            r"\b(LAN|ETHERNET|RJ-?45|PORT|PORTS|CONTROLLER|CHIP|SUPPORTS?|WAKE|ON)\b",
            " ",
            sig,
        )
        sig = re.sub(r"\b\d+\s*[X×*]\s*", " ", sig)
        sig = re.sub(r"[^A-Z0-9.]+", " ", sig)
        sig = re.sub(r"\s+", " ", sig).strip()
        return f"{vendor or ''}|{speed or ''}|{sig}"

    explicit_endpoints: dict[str, int] = {}
    rj45_cap = 0
    single_adapter_hints = False
    multiplier_map = {"DUAL": 2, "TRIPLE": 3, "QUAD": 4}
    vendor_token = (
        r"(?:INTEL|REALTEK|MARVELL|AQUANTIA|BROADCOM|KILLER|RTL\d+[A-Z0-9]*|AQC\d+[A-Z0-9]*)"
    )

    for clause in lan_clauses:
        clause_u = clause.upper().replace("®", "").replace("™", "")
        clause_u = re.sub(r"\s+", " ", clause_u).strip()
        if re.search(r"\bLAN\s*GUARD\b|\bLANGUARD\b", clause_u, flags=re.IGNORECASE):
            continue

        for m in re.finditer(
            rf"\b(?:{vendor_token}\s+)?(DUAL|TRIPLE|QUAD)\b[^,;\n]{{0,40}}?\b(10|5|2\.5|1)\s*G(?:IGABIT|B)?(?:\s*ETHERNET)?\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            cnt = multiplier_map.get(m.group(1).upper(), 1)
            speed = m.group(2)
            vendor = _extract_vendor(m.group(0))
            sig = _endpoint_signature(m.group(0), vendor, speed)
            explicit_endpoints[sig] = max(explicit_endpoints.get(sig, 0), cnt)

        for m in re.finditer(
            rf"(?<!\d)(\d+)\s*[x×*]?\s*(?:{vendor_token}\b[^,;\n]{{0,96}}?)?\b(?:ETHERNET|GIGABIT)\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            cnt = int(m.group(1))
            if not (1 <= cnt <= 8):
                continue
            vendor = _extract_vendor(m.group(0))
            speed = _extract_speed_token(m.group(0))
            sig = _endpoint_signature(m.group(0), vendor, speed)
            explicit_endpoints[sig] = max(explicit_endpoints.get(sig, 0), cnt)

        for m in re.finditer(
            r"\b(\d+)\s*[x×*]?\s*(?:RJ-?45|LAN)\b", clause_u, flags=re.IGNORECASE
        ):
            cnt = int(m.group(1))
            if not (1 <= cnt <= 8):
                continue
            rj45_cap = max(rj45_cap, cnt)

        vendor_speed_matches = list(
            re.finditer(
                rf"\b{vendor_token}\b[^,;\n]{{0,52}}?\b(10|5|2\.5|1)\s*G(?:IGABIT|B)?\s*(?:ETHERNET)?\b",
                clause_u,
                flags=re.IGNORECASE,
            )
        )
        if len(vendor_speed_matches) > 1:
            for m in vendor_speed_matches:
                vendor = _extract_vendor(m.group(0))
                speed = m.group(1)
                sig = _endpoint_signature(m.group(0), vendor, speed)
                explicit_endpoints[sig] = max(explicit_endpoints.get(sig, 0), 1)

        if re.search(
            r"\b(?:GBE|GIGABIT)\s+LAN\b|\bLAN\s+(?:CHIP|CONTROLLER)\b|\bETHERNET\s+CONTROLLER\b",
            clause_u,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"\b{vendor_token}\b[^,;\n]{{0,40}}\bLAN\b",
            clause_u,
            flags=re.IGNORECASE,
        ):
            single_adapter_hints = True

    lan_ports = None
    if explicit_endpoints:
        lan_ports = min(8, max(sum(explicit_endpoints.values()), rj45_cap))
    elif single_adapter_hints:
        lan_ports = max(1, rj45_cap)
    elif rj45_cap or any(re.search(r"RJ-?45", seg, flags=re.IGNORECASE) for seg in lan_segments):
        lan_ports = max(1, rj45_cap)

    speeds: list[float] = []
    lane_text = " ".join(lan_clauses)
    for m in re.findall(
        r"(10|5|2\.5|1)\s*G(?:b(?:/s|ps|E)?|BASE-T)", lane_text, flags=re.IGNORECASE
    ):
        speeds.append(float(m))
    for m in re.findall(
        r"(10|5|2\.5|1)\s*G(?:IGABIT)?\s*ETHERNET",
        lane_text,
        flags=re.IGNORECASE,
    ):
        speeds.append(float(m))
    for m in re.findall(
        r"(10|5|2\.5|1)\s*G\s*LAN", lane_text, flags=re.IGNORECASE
    ):
        speeds.append(float(m))
    for m in re.findall(
        r"(10|5|2\.5|1)\s*GIGABIT\b", lane_text, flags=re.IGNORECASE
    ):
        speeds.append(float(m))
    for m in re.findall(
        r"((?:\d{2,5}\s*/\s*)+\d{2,5})\s*M(?:BIT|B)(?:/S|PS)?",
        lane_text,
        flags=re.IGNORECASE,
    ):
        nums = [int(x) for x in re.findall(r"\d{2,5}", m)]
        if not nums:
            continue
        top = max(nums)
        if top >= 1000:
            speeds.append(top / 1000)
    if re.search(r"\bGIGABIT\s+ETHERNET\b", lane_text, flags=re.IGNORECASE):
        speeds.append(1.0)
    if re.search(r"\bGBE\b", lane_text, flags=re.IGNORECASE):
        speeds.append(1.0)
    if re.search(r"\b10000\s*M(?:BIT|B)?(?:/S|PS)?\b", lane_text, flags=re.IGNORECASE):
        speeds.append(10.0)
    if re.search(r"\b5000\s*M(?:BIT|B)?(?:/S|PS)?\b", lane_text, flags=re.IGNORECASE):
        speeds.append(5.0)
    if re.search(r"\b2500\s*M(?:BIT|B)?(?:/S|PS)?\b", lane_text, flags=re.IGNORECASE):
        speeds.append(2.5)
    if re.search(r"\b1000\s*M(?:BIT|B)?(?:/S|PS)?\b", lane_text, flags=re.IGNORECASE):
        speeds.append(1.0)

    if lan_ports is None:
        return None, None
    if not speeds:
        return lan_ports, None
    top = max(speeds)
    if float(int(top)) == top:
        return lan_ports, f"{int(top)} Gb"
    return lan_ports, f"{top:g} Gb"


_IO_JSON_KEYS = (
    "m2_slots",
    "sata_slots",
    "pcie_slots",
    "usb_ports",
    "displayport_ports",
    "hdmi_ports",
    "lan_ports",
    "lan_max_speed",
)
_EXTERNAL_IO_KEYS = (
    "usb_ports",
    "displayport_ports",
    "hdmi_ports",
    "lan_ports",
    "lan_max_speed",
)


def _has_io_value(value) -> bool:
    return value not in (None, "", [], {})


def _merge_io(ai_io: Optional[dict], extracted_io: dict) -> dict:
    ai_io = ai_io if isinstance(ai_io, dict) else {}
    out = {}
    for key in _IO_JSON_KEYS:
        extracted_value = extracted_io.get(key)
        ai_value = ai_io.get(key)
        if _has_io_value(extracted_value):
            out[key] = extracted_value
            continue
        if key in _EXTERNAL_IO_KEYS:
            out[key] = extracted_value
            continue
        out[key] = ai_value if _has_io_value(ai_value) else extracted_value
    return out


def _normalize_m2_version(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    if "KEY" in s:
        return None
    gens = []
    for g in re.findall(r"GEN\s*([3-7])", s):
        token = f"Gen{g}"
        if token not in gens:
            gens.append(token)
    for g in re.findall(
        r"PCI(?:E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?", s
    ):
        token = f"Gen{g}"
        if token not in gens:
            gens.append(token)
    if not gens:
        return None
    gens = sorted(dict.fromkeys(gens), key=lambda x: int(re.search(r"\d+", x).group(0)))
    return gens[-1]


def _normalize_m2_slots(value) -> list:
    entries = []
    if isinstance(value, dict):
        entries = [value]
    elif isinstance(value, list):
        entries = value
    else:
        return []

    merged: dict[tuple[Optional[str]], int] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        count = _to_int(e.get("count"))
        version = _normalize_m2_version(e.get("version"))
        if count is None or count <= 0 or count > 10:
            continue
        if version is None and isinstance(e.get("version"), str):
            if "KEY" in e.get("version", "").upper():
                continue
        key = (version,)
        merged[key] = merged.get(key, 0) + count

    out = [
        {"count": count, "version": version}
        for (version,), count in merged.items()
        if count > 0
    ]
    out.sort(
        key=lambda x: (
            -int(re.search(r"\d+", x["version"]).group(0))
            if isinstance(x.get("version"), str) and re.search(r"\d+", x["version"])
            else -1
        )
    )
    return out


def _normalize_pcie_version(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    m = re.search(r"GEN\s*([3-7])", s)
    if m:
        return f"Gen{m.group(1)}"
    m = re.search(
        r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?", s
    )
    if m:
        return f"Gen{m.group(1)}"
    return None


def _normalize_lan_ports(value) -> Optional[int]:
    v = _to_int(value)
    if v is None:
        return None
    if v in (10, 45):
        return 1
    if v <= 0:
        return None
    if v > 4:
        return 1
    return v


def _normalize_lan_speed(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip().upper().replace("GBE", "GB")
    if re.search(r"\bGIGABIT\s+ETHERNET\b", s):
        return "1 Gb"
    slash_match = re.search(
        r"((?:\d{2,5}\s*/\s*)+\d{2,5})\s*M(?:BIT|B)(?:/S|PS)?", s
    )
    if slash_match:
        nums = [int(x) for x in re.findall(r"\d{2,5}", slash_match.group(1))]
        if nums:
            top = max(nums)
            if top >= 1000:
                return f"{top / 1000:g} Gb"
    m = re.search(r"(10|5|2\.5|1)\s*GB", s)
    if m:
        return f"{m.group(1)} Gb"
    m = re.search(r"(10|5|2\.5|1)\s*G", s)
    if m:
        return f"{m.group(1)} Gb"
    if re.search(r"\b10000\s*M", s):
        return "10 Gb"
    if re.search(r"\b2500\s*M", s):
        return "2.5 Gb"
    if re.search(r"\b1000\s*M", s):
        return "1 Gb"
    return None


def _normalize_usb_type(
    value: str | None, normalized_version: str | None = None
) -> Optional[str]:
    if not value:
        return "Type-C" if normalized_version == "4.0" else "Type-A"
    s = str(value).strip().upper().replace(" ", "")
    if s in ("NULL", "NONE", "N/A"):
        return "Type-C" if normalized_version == "4.0" else "Type-A"
    if "TYPE-C" in s or s == "TYPEC":
        return "Type-C"
    if "TYPE-A" in s or s == "TYPEA":
        return "Type-A"
    if "TYPE-B" in s or s == "TYPEB":
        return "Type-B"
    if "TYPE-MINI" in s or "MINIUSB" in s or s == "TYPEMINI":
        return "Type-Mini"
    if "USB" in s:
        return "Type-C" if normalized_version == "4.0" else "Type-A"
    return None


def _normalize_usb_version(value: str | None, gen: str | None = None) -> Optional[str]:
    raw = " ".join([str(x) for x in (value, gen) if x]).strip()
    if not raw:
        return None
    s = raw.upper()
    if s in ("NULL", "NONE", "N/A"):
        return None
    if re.search(r"\b20\s*G(?:BPS|BIT/S|B/S)\b", s):
        return "3.2 Gen2x2"
    if re.search(r"\b10\s*G(?:BPS|BIT/S|B/S)\b", s):
        return "3.2 Gen2"
    if re.search(r"\b5\s*G(?:BPS|BIT/S|B/S)\b", s):
        return "3.2 Gen1"
    if re.search(r"\b40\s*G(?:BPS|BIT/S|B/S)\b", s):
        return "4.0"
    m = re.search(r"(\d{1,2}(?:\.\d)?)", s)
    if not m:
        return None
    base = m.group(1)
    if "." not in base:
        if base == "5":
            return None
        base = f"{base}.0"
    if base in ("0.0", "0", "00.0"):
        return None
    if base in ("5.0",):
        return None
    try:
        if float(base) > 4.0:
            return None
    except Exception:
        return None
    gen_match = re.search(r"GEN\s*(\d(?:X\d)?)", s)
    if gen_match and base in ("3.2",):
        return f"{base} Gen{gen_match.group(1).replace('X', 'x')}"
    return base


def _normalize_usb_ports(entries) -> list:
    if not isinstance(entries, list):
        return []
    merged = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        count = _to_int(e.get("count"))
        version = _normalize_usb_version(e.get("version"), e.get("gen"))
        usb_type = _normalize_usb_type(e.get("type"), version)
        if count is None or count <= 0 or count > 14:
            continue
        if usb_type is None or version is None:
            continue
        key = (usb_type, version)
        merged[key] = merged.get(key, 0) + count
    out = []
    for (usb_type, version), count in merged.items():
        count = min(count, 20)
        out.append(
            {
                "count": count,
                "type": usb_type,
                "version": version,
            }
        )
    return out


def _normalize_pcie_slots(entries) -> list:
    if not isinstance(entries, list):
        return []
    merged = {}
    lane_order = {"x16": 0, "x8": 1, "x4": 2, "x1": 3}
    for e in entries:
        if not isinstance(e, dict):
            continue
        count = _to_int(e.get("count"))
        lane = str(e.get("lane") or "").lower().strip()
        version = _normalize_pcie_version(e.get("version"))
        if count is None or count <= 0 or count > _MAX_PCIE_SLOT_COUNT:
            continue
        if lane not in ("x1", "x4", "x8", "x16"):
            continue
        key = (lane, version)
        merged[key] = max(merged.get(key, 0), count)
    out = [
        {"count": count, "lane": lane, "version": version}
        for (lane, version), count in merged.items()
    ]
    out.sort(
        key=lambda item: (
            lane_order.get(item["lane"], 99),
            -(
                int(re.search(r"\d+", item["version"]).group(0))
                if isinstance(item.get("version"), str)
                and re.search(r"\d+", item["version"])
                else -1
            ),
        )
    )
    return out


def _normalize_io_json(io_data: dict | None) -> dict:
    io_data = io_data if isinstance(io_data, dict) else {}
    out = {key: io_data.get(key) for key in _IO_JSON_KEYS}

    out["m2_slots"] = _normalize_m2_slots(out.get("m2_slots"))

    sata = _to_int(out.get("sata_slots"))
    if sata is not None and (sata <= 0 or sata > 16):
        sata = None
    out["sata_slots"] = sata

    out["pcie_slots"] = _normalize_pcie_slots(out.get("pcie_slots"))
    out["usb_ports"] = _normalize_usb_ports(out.get("usb_ports"))

    dp = _to_int(out.get("displayport_ports"))
    if dp is not None and (dp <= 0 or dp > 4):
        dp = None
    out["displayport_ports"] = dp

    hdmi = _to_int(out.get("hdmi_ports"))
    if hdmi is not None and (hdmi <= 0 or hdmi > 4):
        hdmi = None
    out["hdmi_ports"] = hdmi

    out["lan_ports"] = _normalize_lan_ports(out.get("lan_ports"))
    out["lan_max_speed"] = _normalize_lan_speed(out.get("lan_max_speed"))
    if out.get("lan_ports") is None:
        out["lan_max_speed"] = None
    return out


def _extract_io_json(raw: str, specs: dict, ai_io: Optional[dict]) -> dict:
    lines = [f"{k}: {v}" for k, v in (specs or {}).items()]
    specs_text = "\n".join(lines)
    raw_text = (raw or "").strip()
    text = raw_text or specs_text

    spec_items = list((specs or {}).items())

    def _is_internal_io_key(key_l: str) -> bool:
        return any(
            token in key_l
            for token in (
                "конектор",
                "connector",
                "header",
                "internal",
                "front panel",
                "вътреш",
                "jfp",
                "jaud",
                "jtbt",
                "jargb",
                "jrgb",
                "fan",
                "cooling",
                "power",
            )
        )

    def _is_external_io_key(key_l: str) -> bool:
        if _is_internal_io_key(key_l):
            return False
        if any(
            token in key_l
            for token in (
                "back panel",
                "rear",
                "i/o",
                "lan",
                "ethernet",
                "rj-45",
                "hdmi",
                "displayport",
                "display port",
                "video",
                "видео",
                "graphics",
                "usb",
                "thunderbolt",
            )
        ):
            return True
        if re.search(r"\bports?\b", key_l):
            return True
        if re.search(r"\bпорт(?:ове)?\b", key_l):
            return True
        return False

    def _key_matches(key_l: str, needle: str) -> bool:
        if needle in {"port", "ports"}:
            return bool(re.search(r"\bports?\b", key_l))
        if needle in {"порт", "портове"}:
            return bool(re.search(r"\bпорт(?:ове)?\b", key_l))
        return needle in key_l

    def _spec_join(*needles: str, external_only: bool = False) -> str:
        out = []
        for k, v in spec_items:
            k_l = str(k).lower()
            if external_only and not _is_external_io_key(k_l):
                continue
            if any(_key_matches(k_l, n) for n in needles):
                out.append(f"{k}: {v}")
        return "\n".join(out)

    def _has_explicit_pcie_slot_evidence(value: str | None) -> bool:
        if not value:
            return False
        upper = str(value).upper()
        if re.search(r"\b(PCIEX\d+(?:_\d+)?|PCI[_\s-]?E\d+)\b", upper):
            return True
        if re.search(r"^\s*PCI(?:E|[- ]E|\s*EXPRESS)?\s*X(?:1|4|8|16)\b", upper):
            return True
        return bool(
            re.search(
                r"\bPCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)?[3-7]?(?:\.0)?\s*X(?:1|4|8|16)\b"
                r"[^\n\r]{0,48}\bSLOTS?\b",
                upper,
                flags=re.IGNORECASE,
            )
        )

    def _m2_metrics(entries) -> dict[str, int]:
        versioned_slots = 0
        unknown_slots = 0
        distinct_versions = set()
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            count = _to_int(entry.get("count"))
            if count is None or count <= 0:
                continue
            version = entry.get("version")
            if isinstance(version, str):
                versioned_slots += count
                distinct_versions.add(version)
            else:
                unknown_slots += count
        return {
            "versioned_slots": versioned_slots,
            "unknown_slots": unknown_slots,
            "total_slots": versioned_slots + unknown_slots,
            "distinct_versions": len(distinct_versions),
        }

    def _m2_source_richness(source_name: str, source_text: str) -> int:
        upper = str(source_text or "").upper()
        has_gen = bool(
            re.search(
                r"\bGEN\s*[3-7]\b|\bPCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        has_slot_ids = bool(
            re.search(
                r"\bM\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        has_connector_detail = bool(
            re.search(
                r"\b\d+\s*[xX×*]?\s*M\.?2\b[^\n\r]{0,96}\b(?:CONNECTORS?|SOCKETS?|SLOTS?)\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        has_count_only_slot_row = bool(
            re.search(
                r"\b\d+\s*[xX×*]?\s*M\.?2\b[^\n\r]{0,24}\bSLOTS?\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        is_controller_only = bool(
            re.search(
                r"\bPCI(?:E|[- ]E|\s*EXPRESS)?\s*[3-7](?:\.0)?\s*X\d+\s*\(\s*\d+\s*[xX×*]?\s*M\.?2",
                upper,
                flags=re.IGNORECASE,
            )
        ) and not (has_slot_ids or has_connector_detail)

        if has_slot_ids or (has_connector_detail and has_gen):
            return 5
        if has_connector_detail:
            return 4
        if has_count_only_slot_row or (
            source_name in {"m2_slot_rows", "secondary"}
            and re.search(r"\bM\.?2\b", upper, flags=re.IGNORECASE)
            and re.search(r"\b(?:SLOT|SLOTS|SOCKET|SOCKETS|CONNECTOR|CONNECTORS)\b", upper)
        ):
            return 3
        if has_gen and not is_controller_only:
            return 2
        if is_controller_only or has_gen:
            return 1
        return 0

    def _m2_source_score(
        entries, priority: int, source_name: str, source_text: str
    ) -> tuple[int, int, int, int, int, int]:
        m = _m2_metrics(entries)
        return (
            _m2_source_richness(source_name, source_text),
            m["versioned_slots"],
            m["distinct_versions"],
            -m["unknown_slots"],
            m["total_slots"],
            priority,
        )

    def _m2_text_has_strong_version_evidence(source_text: str) -> bool:
        upper = str(source_text or "").upper()
        has_gen = bool(
            re.search(
                r"\bGEN\s*[3-7]\b|\bPCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        has_slot_ids = bool(
            re.search(
                r"\bM\.?2[_-]?(?:\d+|[A-Z][A-Z0-9]*(?:[_-][A-Z0-9]+)*)\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        has_connector_detail = bool(
            re.search(
                r"\bM\.?2\b[^\n\r]{0,96}\b(?:CONNECTORS?|SOCKETS?)\b",
                upper,
                flags=re.IGNORECASE,
            )
        )
        return has_gen and (has_slot_ids or has_connector_detail)

    def _extract_storage_controller_m2_entries(source_text: str) -> list[dict]:
        if not source_text:
            return []
        entries: dict[str, int] = {}
        seen_signatures: set[str] = set()
        for clause in re.split(r"[\n\r;]+", source_text):
            clause_u = re.sub(r"\s+", " ", str(clause).upper()).strip(" -,;")
            if not clause_u:
                continue
            if re.search(
                r"\b(KEY E|WI-?FI|CNVIO|CNVIO2|RAID|SUPPORTS?:)\b",
                clause_u,
                flags=re.IGNORECASE,
            ):
                continue
            m = re.search(
                r"PCI(?:E|[- ]E|\s*EXPRESS)?(?:\s+NVME)?\s*([3-7])(?:\.0)?\s*X\d+(?:/SATA)?\s*\(\s*(\d+)\s*[xX×*]?\s*M\.?2\b",
                clause_u,
                flags=re.IGNORECASE,
            )
            if not m:
                continue
            signature = clause_u
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            version = f"Gen{m.group(1)}"
            count = int(m.group(2))
            if 1 <= count <= 10:
                entries[version] = entries.get(version, 0) + count
        return [
            {"count": count, "version": version}
            for version, count in sorted(
                entries.items(),
                key=lambda item: int(re.search(r"\d+", item[0]).group(0)),
                reverse=True,
            )
        ]

    m2_disk = _spec_join(
        "дисков интерфейс",
        "storage interface",
        "disk interface",
        "дисков",
        "storage",
        "disk",
    )
    m2_storage_controller = _spec_join(
        "storage controller",
        "контролер на съхран",
        "контролер",
        "съхран",
    )
    m2_secondary = _spec_join("m.2", "m2")
    m2_slot_rows = "\n".join(
        f"{k}: {v}"
        for k, v in spec_items
        if (
            re.search(r"\b(?:slot|slots|слот|слотове)\b", str(k), flags=re.IGNORECASE)
            and (
                re.search(
                    r"\bM\.?2[_-]?(?:\d+|[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)*)\b",
                    str(v),
                    flags=re.IGNORECASE,
                )
                or re.search(
                    r"\b\d+\s*[xX×*]?\s*M\.?2\b",
                    str(v),
                    flags=re.IGNORECASE,
                )
            )
        )
    )
    m2_candidates = []
    if m2_disk:
        m2_candidates.append(("disk_interface", m2_disk, _extract_m2_info(m2_disk)))
    if m2_slot_rows:
        m2_candidates.append(
            ("m2_slot_rows", m2_slot_rows, _extract_m2_info(m2_slot_rows))
        )
    if m2_storage_controller:
        m2_candidates.append(
            (
                "storage_controller",
                m2_storage_controller,
                _extract_m2_info(m2_storage_controller),
            )
        )
    if m2_secondary:
        m2_candidates.append(("secondary", m2_secondary, _extract_m2_info(m2_secondary)))
    raw_m2_text = raw_text or ""
    raw_m2 = _extract_m2_info(raw_m2_text)
    storage_controller_precise = _extract_storage_controller_m2_entries(
        m2_storage_controller
    )

    source_priority = {
        "disk_interface": 5,
        "m2_slot_rows": 4,
        "storage_controller": 3,
        "secondary": 2,
    }
    m2 = []
    best_name = None
    best_text = ""
    best_score = None
    for source_name, source_text, entries in m2_candidates:
        if not entries:
            continue
        score = _m2_source_score(
            entries, source_priority.get(source_name, 0), source_name, source_text
        )
        if best_score is None or score > best_score:
            best_score = score
            best_name = source_name
            best_text = source_text
            m2 = entries

    if m2 and best_name:
        base_metrics = _m2_metrics(m2)
        for source_name, source_text, entries in m2_candidates:
            if source_name == best_name or not entries:
                continue
            candidate_metrics = _m2_metrics(entries)
            if (
                candidate_metrics["total_slots"] == base_metrics["total_slots"]
                and _m2_source_score(
                    entries,
                    source_priority.get(source_name, 0),
                    source_name,
                    source_text,
                )
                > _m2_source_score(
                    m2,
                    source_priority.get(best_name, 0),
                    best_name,
                    best_text,
                )
            ):
                m2 = entries
                best_name = source_name
                best_text = source_text
                base_metrics = candidate_metrics
    if not m2:
        m2 = raw_m2
    elif (
        storage_controller_precise
        and (
            best_name in {None, "storage_controller", "secondary"}
            or not _m2_text_has_strong_version_evidence(best_text)
        )
        and _m2_metrics(storage_controller_precise)["total_slots"]
        > _m2_metrics(m2)["total_slots"]
    ):
        m2 = storage_controller_precise
    elif (
        raw_m2
        and _m2_metrics(m2)["versioned_slots"] == 0
        and _m2_metrics(raw_m2)["versioned_slots"] > 0
        and _m2_text_has_strong_version_evidence(raw_m2_text)
        and _m2_source_score(raw_m2, 0, "raw", raw_m2_text)
        > _m2_source_score(
            m2,
            source_priority.get(best_name, 0),
            best_name or "unknown",
            best_text,
        )
        and (
            _m2_metrics(raw_m2)["total_slots"] <= _m2_metrics(m2)["total_slots"]
            or _m2_metrics(m2)["total_slots"] == 0
        )
    ):
        m2 = raw_m2
    m2 = _normalize_m2_slots(m2)

    sata_text = _spec_join("sata", "дисков", "storage", "disk") or text
    sata = _extract_sata_slots(sata_text)

    pcie_rows = []
    for k, v in spec_items:
        key = str(k)
        key_l = key.lower()
        value = str(v)
        if any(
            token in key_l
            for token in (
                "m.2",
                "m2",
                "wifi controller",
                "wi-fi controller",
                "key e",
                "storage controller",
                "контролер на съхран",
                "дисков интерфейс",
            )
        ):
            continue
        if (
            any(token in key_l for token in ("разширител", "pcie", "pci"))
            or (
                re.search(r"\b(?:slot|slots|слот|слотове)\b", key_l, flags=re.IGNORECASE)
                and _has_explicit_pcie_slot_evidence(value)
            )
            or _has_explicit_pcie_slot_evidence(key)
        ):
            pcie_rows.append(f"{k}: {v}")
    pcie_text = "\n".join(pcie_rows) or text
    pcie = _extract_pcie_slots(pcie_text)
    if not pcie and raw_text and _has_explicit_pcie_slot_evidence(raw_text):
        pcie = _extract_pcie_slots(raw_text)

    external_io_text = "\n".join(
        f"{k}: {v}"
        for k, v in spec_items
        if _is_external_io_key(str(k).lower())
    )

    def _map_usb(entries: list) -> dict[tuple[str, str], int]:
        mapped: dict[tuple[str, str], int] = {}
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            usb_type = entry.get("type")
            version = entry.get("version")
            count = _to_int(entry.get("count"))
            if (
                usb_type not in ("Type-A", "Type-B", "Type-C", "Type-Mini")
                or version is None
                or count is None
                or count <= 0
            ):
                continue
            mapped[(usb_type, version)] = mapped.get((usb_type, version), 0) + count
        return mapped

    def _usb_version_family(version: str | None) -> Optional[str]:
        if not isinstance(version, str):
            return None
        return version.split()[0]

    def _explicit_usb_type_from_text(text: str) -> Optional[str]:
        text_u = str(text).upper()
        if re.search(r"USB[- ]?TYPE[- ]?C|USB[- ]?C|TYPE[- ]?C", text_u):
            return "Type-C"
        if re.search(r"USB[- ]?TYPE[- ]?A|TYPE[- ]?A", text_u):
            return "Type-A"
        if re.search(r"USB[- ]?TYPE[- ]?B|TYPE[- ]?B", text_u):
            return "Type-B"
        if re.search(r"USB[- ]?TYPE[- ]?MINI|TYPE[- ]?MINI|MINIUSB", text_u):
            return "Type-Mini"
        return None

    def _usb_cap_scope_count(
        merged: dict[tuple[str, str], int],
        usb_type: Optional[str],
        version: Optional[str],
        *,
        default_type_only: bool = False,
    ) -> int:
        total = 0
        version_family = _usb_version_family(version)
        scope_type = usb_type
        if default_type_only and version is not None:
            scope_type = _normalize_usb_type(None, version)
        elif scope_type is None and version is not None:
            scope_type = _normalize_usb_type(None, version)
        for (existing_type, existing_version), existing_count in merged.items():
            if scope_type and existing_type != scope_type:
                continue
            if version is not None:
                if "GEN" in version:
                    if existing_version != version:
                        continue
                elif version in ("2.0", "4.0"):
                    if existing_version != version:
                        continue
                elif _usb_version_family(existing_version) != version_family:
                    continue
            total += existing_count
        return total

    def _extract_usb_caps() -> list[dict]:
        caps: list[dict] = []
        for key, value in spec_items:
            key_l = str(key).lower()
            if not _is_external_io_key(key_l) or _is_internal_io_key(key_l):
                continue
            if not re.search(
                r"\b(?:usb|thunderbolt)\b", f"{key} {value}", flags=re.IGNORECASE
            ):
                continue

            raw_value = re.sub(r"\s+", " ", str(value)).strip()
            is_simple_numeric = bool(re.fullmatch(r"\d+", raw_value))
            is_generic_ports_row = bool(
                re.search(r"\bports?\b|\bпорт(?:ове)?\b", str(key), flags=re.IGNORECASE)
            )
            explicit_type = _explicit_usb_type_from_text(str(key))
            explicit_version = _normalize_usb_version(str(key))

            if is_simple_numeric and not is_generic_ports_row and (
                explicit_type is not None or explicit_version is not None
            ):
                caps.append(
                    {
                        "count": int(raw_value),
                        "type": explicit_type,
                        "version": explicit_version,
                    }
                )
        return caps

    def _merge_usb_sources(ports_entries: list, dedicated_entries: list) -> list:
        caps = _extract_usb_caps()
        generic_cap_versions = {
            cap.get("version")
            for cap in caps
            if cap.get("type") is None
            and isinstance(cap.get("version"), str)
            and "GEN" not in cap["version"].upper()
            and cap["version"] not in ("2.0", "4.0")
        }
        type_only_caps = {
            cap.get("type")
            for cap in caps
            if cap.get("type") is not None and cap.get("version") is None
        }
        ports_map = _map_usb(ports_entries)
        dedicated_map = _map_usb(dedicated_entries)
        merged = dict(ports_map)
        for key, count in dedicated_map.items():
            usb_type, version = key
            if (
                version in generic_cap_versions
                and usb_type == _normalize_usb_type(None, version)
            ):
                continue
            if key not in merged:
                merged[key] = count
                continue
            merged[key] = max(merged[key], count)

        # Generic family entries like "USB 3.2 Type-A" from broad ports rows are
        # weaker than explicit Gen1/Gen2 rows. Keep only unexplained residuals.
        for (usb_type, version), count in list(merged.items()):
            if (
                not isinstance(version, str)
                or "GEN" in version.upper()
                or version in ("2.0", "4.0")
            ):
                continue
            version_family = _usb_version_family(version)
            explained = sum(
                existing_count
                for (existing_type, existing_version), existing_count in merged.items()
                if existing_type == usb_type
                and existing_version != version
                and _usb_version_family(existing_version) == version_family
                and isinstance(existing_version, str)
                and "GEN" in existing_version.upper()
            )
            residual = count - explained
            if residual <= 0:
                del merged[(usb_type, version)]
                continue
            merged[(usb_type, version)] = residual
        caps.sort(
            key=lambda cap: (
                0 if cap.get("type") and cap.get("version") else 1,
                0 if cap.get("version") else 1,
                0 if cap.get("type") else 1,
            )
        )
        for cap in caps:
            count = _to_int(cap.get("count"))
            usb_type = cap.get("type")
            version = cap.get("version")
            if count is None or count <= 0:
                continue
            default_type_only = (
                usb_type is None
                and version in generic_cap_versions
                and "Type-C" in type_only_caps
            )
            residual = count - _usb_cap_scope_count(
                merged,
                usb_type,
                version,
                default_type_only=default_type_only,
            )
            if residual <= 0:
                continue
            if usb_type and version:
                key = (usb_type, version)
                merged[key] = merged.get(key, 0) + residual
            elif version:
                default_type = _normalize_usb_type(None, version)
                if default_type is None:
                    continue
                key = (default_type, version)
                merged[key] = merged.get(key, 0) + residual
        return [
            {"type": usb_type, "version": version, "count": count}
            for (usb_type, version), count in sorted(merged.items())
        ]

    def _extract_lan_port_clauses(source_text: str) -> str:
        if not source_text:
            return ""
        clauses = []
        for part in re.split(r"[\n\r;]+", source_text):
            part = re.sub(r"\s+", " ", part).strip()
            if not part:
                continue
            sub_parts = [x.strip() for x in re.split(r",", part) if x and x.strip()]
            if not sub_parts:
                sub_parts = [part]
            for clause in sub_parts:
                if re.search(
                    r"\b(LAN|ETHERNET|RJ-?45|GBE|GIGABIT|REALTEK|INTEL|MARVELL|AQUANTIA|BROADCOM|KILLER|RTL\d+[A-Z0-9]*|AQC\d+[A-Z0-9]*)\b",
                    clause,
                    flags=re.IGNORECASE,
                ):
                    clauses.append(clause)
        return "\n".join(dict.fromkeys(clauses))

    def _extract_external_usb_clauses(source_text: str) -> str:
        if not source_text:
            return ""
        clauses = []
        for part in re.split(r"[\n\r;]+", source_text):
            part = re.sub(r"\s+", " ", part).strip()
            if not part:
                continue
            sub_parts = re.split(
                r",\s*(?=(?:\d+\s*[xX×*]?\s*)?(?:USB|THUNDERBOLT)\b)",
                part,
                flags=re.IGNORECASE,
            )
            if len(sub_parts) <= 1:
                clauses.append(part)
                continue
            for sub_clause in sub_parts:
                sub_clause = sub_clause.strip(" ,")
                if sub_clause:
                    clauses.append(sub_clause)
        out_clauses = []
        for clause in clauses:
            clause_u = clause.upper()
            if not re.search(r"\b(?:USB|THUNDERBOLT)\b", clause_u):
                continue
            has_front = bool(re.search(r"\bFRONT\b", clause_u))
            rear_matches = []
            for pat in (
                r"\b(\d+)\s*(?:REAR|ON THE BACK PANEL|BACK PANEL|НА ЗАДНИЯ ПАНЕЛ|ЗАДНИ ПОРТОВЕ)\b",
                r"\b(\d+)\s+ON\s+REAR(?:\s+I/?OS?)?\b",
                r"\b(\d+)\s+ON\s+THE\s+REAR\b",
            ):
                rear_matches.extend(re.findall(pat, clause_u))
            has_internal = bool(
                re.search(
                    r"\bINTERNAL|HEADER|HEADERS|FRONT PANEL|ВЪТРЕШ|ХЕДЪР|ХЕДЕР\b",
                    clause_u,
                )
            )
            has_back_panel = bool(
                re.search(
                    r"\bBACK PANEL|REAR|I/O|НА ЗАДНИЯ ПАНЕЛ|ЗАДНИЯ ПАНЕЛ\b",
                    clause_u,
                )
            )
            if has_internal and not has_back_panel:
                continue
            if has_front and not rear_matches and not has_back_panel:
                continue
            rear_count = None
            normalized_with_rear_count = False
            if rear_matches:
                rear_count = max(int(x) for x in rear_matches)
            if rear_count is not None:
                normalized = re.sub(
                    r"\b\d+\s*[xX×*]?\s*(?=USB\b)",
                    f"{rear_count} x ",
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if normalized == clause and re.search(r"\bUSB\b", clause, flags=re.IGNORECASE):
                    normalized = f"{rear_count} x {clause}"
                clause = normalized
                normalized_with_rear_count = True
            if has_internal and has_back_panel:
                back_count = None
                if rear_count is not None:
                    back_count = rear_count
                m_back = re.search(
                    r"\((\d+)\s*PORTS?\s*ON\s*THE\s*BACK\s*PANEL",
                    clause_u,
                    flags=re.IGNORECASE,
                )
                if m_back:
                    back_count = int(m_back.group(1))
                if back_count is not None:
                    if not normalized_with_rear_count:
                        normalized = re.sub(
                            r"\b\d+\s*[xX×*]?\s*(?=USB\b)",
                            f"{back_count} x ",
                            clause,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                        if normalized == clause:
                            normalized = f"{back_count} x {clause}"
                        clause = normalized
                    if not re.search(r"\bREAR\b|\bBACK PANEL\b", clause, flags=re.IGNORECASE):
                        clause = f"{clause} on the back panel"
                else:
                    continue
            out_clauses.append(clause)
        return "\n".join(out_clauses)

    usb_ports_rows_source = _spec_join(
        "порт",
        "ports",
        "back panel",
        "rear",
        "i/o",
        external_only=True,
    )
    usb_dedicated_source = _spec_join("usb", "thunderbolt", external_only=True)
    usb_from_ports = _normalize_usb_ports(
        _extract_usb_ports(_extract_external_usb_clauses(usb_ports_rows_source))
    )
    usb_from_dedicated = _normalize_usb_ports(
        _extract_usb_ports(_extract_external_usb_clauses(usb_dedicated_source))
    )
    usb = _merge_usb_sources(usb_from_ports, usb_from_dedicated)
    if not usb:
        usb = _normalize_usb_ports(
            _extract_usb_ports(_extract_external_usb_clauses(external_io_text))
        )

    av_text = _spec_join(
        "порт",
        "ports",
        "hdmi",
        "display",
        "video",
        "видео",
        "graphics",
        "back panel",
        "rear",
        "i/o",
        external_only=True,
    )
    if not av_text:
        av_text = external_io_text
    dp, hdmi = _extract_video_info(av_text)
    if dp is None:
        dp_fallback = _extract_count("DISPLAYPORT", av_text)
        if dp_fallback is not None:
            dp = dp_fallback
    lan_rows = [
        f"{k}: {v}"
        for k, v in spec_items
        if _is_external_io_key(str(k).lower())
        and re.search(
            r"\b(lan|ethernet|rj-?45|мреж)\b", str(k), flags=re.IGNORECASE
        )
    ]
    port_rows = [
        f"{k}: {v}"
        for k, v in spec_items
        if _is_external_io_key(str(k).lower())
        and (
            re.search(r"\bports?\b", str(k), flags=re.IGNORECASE)
            or re.search(r"\bпорт(?:ове)?\b", str(k), flags=re.IGNORECASE)
            or any(
                token in str(k).lower()
                for token in ("back panel", "rear", "i/o")
            )
        )
    ]
    lan_text = "\n".join(dict.fromkeys(lan_rows + [_extract_lan_port_clauses(x) for x in port_rows if x]))
    if not lan_text:
        lan_text = "\n".join(
            line.strip()
            for line in re.split(r"[\n\r]+", external_io_text)
            if line.strip()
            and re.search(r"LAN|ETHERNET|RJ-?45|МРЕЖ", line, flags=re.IGNORECASE)
        )
    lan_ports, lan_speed = _extract_lan_info(lan_text)

    extracted = {
        "m2_slots": m2,
        "sata_slots": sata,
        "pcie_slots": pcie,
        "usb_ports": usb,
        "displayport_ports": dp,
        "hdmi_ports": hdmi,
        "lan_ports": lan_ports,
        "lan_max_speed": lan_speed,
    }
    return _normalize_io_json(_merge_io(ai_io, extracted))


def _build_ai_source(specs: dict, raw: str) -> str:
    if specs:
        preferred = (
            "chipset",
            "socket",
            "form",
            "size",
            "memory",
            "dimm",
            "ram",
            "wifi",
            "wireless",
            "bluetooth",
            "802.11",
            "sata",
            "m.2",
            "m2",
            "pci",
            "usb",
            "ports",
            "hdmi",
            "displayport",
            "video",
            "graphics",
            "lan",
            "network",
            "ethernet",
            "storage",
            "disk",
            "slot",
            "чипсет",
            "сокет",
            "памет",
            "слот",
            "слотов",
            "порт",
            "размер",
            "дисков",
            "интерфейс",
            "антен",
            "видео",
        )
        lines = [
            f"{k}: {v}"
            for k, v in specs.items()
            if any(p in str(k).lower() for p in preferred)
        ]
        if not lines:
            lines = [f"{k}: {v}" for k, v in specs.items()]
        text = "\n".join(lines)
        if raw:
            raw_lines = [
                line.strip()
                for line in re.split(r"[\n\r]+", raw)
                if line.strip()
                and any(
                    p in line.lower()
                    for p in (
                        "wifi",
                        "wi-fi",
                        "bluetooth",
                        "802.11",
                        "anten",
                        "порт",
                        "ports",
                        "usb",
                        "m.2",
                        "m2",
                        "pcie",
                        "pci",
                        "video",
                        "graphics",
                        "видео",
                        "lan",
                        "rj-45",
                        "дисков",
                        "интерфейс",
                    )
                )
            ]
            if raw_lines:
                text = text + "\n" + "\n".join(raw_lines[:120])
        return text[:16000]
    return (raw or "")[:16000]


async def run_motherboard_pipeline(
    headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None
):
    counters = {
        "collected_urls": 0,
        "fetched_pages": 0,
        "successful_upserts": 0,
        "ai_parse_failures": 0,
        "fallback_only_upserts": 0,
        "skipped_ambiguous_model": 0,
        "skipped_non_motherboard": 0,
        "skipped_low_signal_page": 0,
        "skipped_integrated_cpu": 0,
        "skipped_missing_chipset": 0,
        "skipped_invalid_socket": 0,
        "skipped_missing_memory_type": 0,
        "processing_errors": 0,
        "db_upsert_errors": 0,
    }
    ai_enabled = True
    ai_disabled_reason = None
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

        print(f"Opening {MOTHERBOARD_CATEGORY_URL}")
        await page.goto(
            MOTHERBOARD_CATEGORY_URL,
            wait_until="domcontentloaded",
            timeout=90000,
        )
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")

            urls = await collect_motherboard_urls(page)
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
            print(f"  -> New motherboards added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("No enabled next page button, stopping.")
                break

            print(f"Clicking page {current_page + 1}")
            await next_button.click()

            try:
                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href]");
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

        print(f"\nTotal motherboards collected: {len(all_urls)}")
        counters["collected_urls"] = len(all_urls)
        for u in sorted(all_urls):
            print(" ", u)

        all_urls_list = [{"url": url} for url in sorted(all_urls)]
        with open("motherboard_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(
            f"\nSaved {len(all_urls_list)} motherboard links to motherboard_links.json"
        )

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            print(
                "Summary: "
                f"collected_urls={counters['collected_urls']}, "
                f"fetched_pages=0, successful_upserts=0, ai_parse_failures=0, "
                f"fallback_only_upserts=0, ai_status=not_run, "
                f"skipped_ambiguous_model=0, skipped_non_motherboard=0, "
                f"skipped_low_signal_page=0, skipped_integrated_cpu=0, "
                f"skipped_missing_chipset=0, skipped_invalid_socket=0, skipped_missing_memory_type=0"
            )
            return

        print("\nProcessing collected motherboard pages and inserting into DB...")
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
                counters["fetched_pages"] += 1
                parsed = parse_motherboard_page(html, url)
                ai_used = False

                ai_data = {}
                if ai_enabled:
                    try:
                        ai_source = _build_ai_source(
                            parsed.get("specs") or {}, parsed.get("raw_specs") or ""
                        )
                        ai_data = parse_motherboard(
                            ai_source,
                            parsed.get("name", ""),
                            parsed.get("price", 0.0),
                            url,
                        )
                        ai_used = True
                    except LLMConfigurationError as e:
                        logger.exception("AI configuration failed for %s", url)
                        counters["ai_parse_failures"] += 1
                        ai_enabled = False
                        ai_disabled_reason = str(e)
                        print(
                            "    AI disabled for remainder of run: "
                            f"{ai_disabled_reason}. Using deterministic fallback only."
                        )
                    except Exception as e:
                        logger.exception("AI parsing failed for %s", url)
                        print(f"    AI parse error for {url}: {e}")
                        counters["ai_parse_failures"] += 1
                else:
                    ai_data = {}

                raw = parsed.get("raw_specs", "") or ""
                specs = parsed.get("specs") or {}
                specs_lc = {str(k).lower(): str(v) for k, v in specs.items() if k and v}

                def _spec_value(keys):
                    for k, v in specs_lc.items():
                        if any(key in k for key in keys):
                            return v
                    return None

                def _spec_values(keys):
                    values = []
                    for k, v in specs_lc.items():
                        if any(key in k for key in keys):
                            values.append(v)
                    return values

                def _first_normalized(normalizer, *values):
                    for value in values:
                        normalized = normalizer(value)
                        if normalized is not None:
                            return normalized
                    return None

                final = {}
                final["model"] = (
                    _normalize_model(ai_data.get("model"))
                    or _normalize_model(parsed.get("model"))
                    or _normalize_model(parsed.get("name"))
                )
                if not final["model"]:
                    print(f"    Skipping ambiguous model for {url}: {final['model']}")
                    counters["skipped_ambiguous_model"] += 1
                    continue

                final["brand"] = _first_normalized(
                    _normalize_brand,
                    ai_data.get("brand"),
                    parsed.get("brand"),
                    parsed.get("name"),
                    parsed.get("model"),
                )
                final["brand"] = _prefer_inferred_brand(
                    final.get("brand"),
                    final.get("model"),
                    parsed.get("name"),
                    url,
                )

                if _is_non_motherboard_item(
                    final.get("brand"), final.get("model"), parsed.get("name"), url
                ):
                    print(
                        f"    Skipping non-motherboard item for {url}: {parsed.get('name')}"
                    )
                    counters["skipped_non_motherboard"] += 1
                    continue
                if _is_low_signal_placeholder_page(
                    final.get("brand"),
                    final.get("model"),
                    parsed.get("name"),
                    specs,
                    raw,
                ):
                    print(
                        f"    Skipping low-signal placeholder page for {url}: {parsed.get('name')}"
                    )
                    counters["skipped_low_signal_page"] += 1
                    continue

                final["form_factor"] = _first_normalized(
                    _normalize_form_factor,
                    ai_data.get("form_factor"),
                    _spec_value(["form", "size", "форм", "размер"]),
                    parsed.get("name"),
                    parsed.get("model"),
                    url,
                )

                chipset_candidates = [
                    ai_data.get("chipset"),
                    *_spec_values(["chipset", "чипсет", "platform", "платформ"]),
                    parsed.get("name"),
                    parsed.get("model"),
                    url,
                    raw,
                    " ".join(str(v) for v in specs.values() if v),
                ]
                final["chipset"] = None
                for candidate in chipset_candidates:
                    chipset_value = _normalize_chipset(candidate)
                    if chipset_value is None:
                        chipset_value = _extract_chipset_from_text(str(candidate or ""))
                    if chipset_value is not None:
                        final["chipset"] = chipset_value
                        break
                if final["chipset"] is None:
                    socket_hint = _spec_value(["socket", "сокет", "cpu"])
                    final["chipset"] = _extract_chipset_from_text(socket_hint or "")
                final["chipset"] = _correct_chipset_alias(
                    final.get("chipset"),
                    final.get("model"),
                    parsed.get("name"),
                    url,
                    final.get("socket"),
                )
                if _is_integrated_cpu_board(
                    parsed.get("name"),
                    final.get("model"),
                    final.get("chipset"),
                    raw,
                    specs,
                    url,
                ):
                    print(f"    Skipping integrated-CPU board for {url}")
                    counters["skipped_integrated_cpu"] += 1
                    continue
                if final["chipset"] is None:
                    print(
                        f"    Skipping motherboard with missing/invalid chipset for {url}: {final.get('model')}"
                    )
                    counters["skipped_missing_chipset"] += 1
                    continue

                final["socket"] = _normalize_socket(
                    ai_data.get("socket") or _spec_value(["socket", "сокет"])
                )
                if final["socket"] is None:
                    socket_val = _spec_value(["socket", "сокет"])
                    final["socket"] = _extract_socket_from_text(socket_val or "")
                if final["socket"] is None:
                    final["socket"] = _extract_socket_from_text(
                        parsed.get("name") or ""
                    )
                if final["socket"] is None:
                    final["socket"] = _extract_socket_from_text(url)
                if final["socket"] is None:
                    final["socket"] = _extract_socket_from_text(raw)
                if final["socket"] is None and final.get("chipset"):
                    final["socket"] = get_common_socket_for_chipset(final["chipset"])
                final["chipset"] = _correct_chipset_alias(
                    final.get("chipset"),
                    final.get("model"),
                    parsed.get("name"),
                    url,
                    final.get("socket"),
                )
                if final["socket"] is None:
                    print(
                        f"    Skipping motherboard with missing/invalid socket for {url}: {final.get('model')}"
                    )
                    counters["skipped_invalid_socket"] += 1
                    continue

                memory_candidates = [
                    ai_data.get("memory_type"),
                    *_spec_values(["memory", "ddr", "ram", "памет"]),
                    " ".join(str(v) for v in specs.values() if v),
                    raw,
                ]
                final["memory_type"] = _resolve_memory_type(
                    memory_candidates,
                    final.get("chipset"),
                )
                final["chipset"] = _correct_chipset_alias(
                    final.get("chipset"),
                    final.get("model"),
                    parsed.get("name"),
                    url,
                    final.get("socket"),
                    final.get("memory_type"),
                )
                if final["memory_type"] is None:
                    print(
                        f"    Skipping motherboard with missing/ambiguous memory type for {url}: {final.get('model')}"
                    )
                    counters["skipped_missing_memory_type"] += 1
                    continue

                ram_slot_rows = []
                for k, v in specs.items():
                    key = str(k).lower()
                    value = str(v)
                    if any(
                        token in key
                        for token in (
                            "dimm",
                            "memory slot",
                            "memory slots",
                            "ram slot",
                            "ram slots",
                            "слот",
                            "слотов",
                        )
                    ):
                        ram_slot_rows.append(f"{k}: {v}")
                        continue
                    if re.search(
                        r"\b\d+\s*[xX×*]?\s*(?:DDR[3-5]|DIMM)\b",
                        value,
                        flags=re.IGNORECASE,
                    ):
                        ram_slot_rows.append(f"{k}: {v}")
                ram_slot_text = "\n".join(dict.fromkeys(ram_slot_rows))
                if raw and re.search(
                    r"\b\d+\s*[xX×*]?\s*(?:DDR[3-5]|DIMM)\b|\b(?:DIMM|MEMORY|RAM)\s+SLOTS?\b",
                    raw,
                    flags=re.IGNORECASE,
                ):
                    ram_slot_text = f"{ram_slot_text}\n{raw}".strip()
                final["ram_slots"] = _normalize_ram_slots(_extract_ram_slots(ram_slot_text))
                final["ram_slots_evidence"] = final["ram_slots"] is not None

                speed_text = " ".join(
                    _spec_values(["speed", "oc", "mhz", "mt/s", "честот", "memory", "ddr"])
                )
                final["max_ram_speed_mhz"] = _extract_max_ram_speed_mhz(
                    f"{speed_text} {raw}"
                )
                if final["max_ram_speed_mhz"] is None:
                    final["max_ram_speed_mhz"] = _normalize_max_ram_speed_mhz(
                        ai_data.get("max_ram_speed_mhz")
                    )

                final["max_ram_amount_gb"] = _normalize_max_ram_amount(
                    ai_data.get("max_ram_amount_gb")
                )
                if final["max_ram_amount_gb"] is None:
                    max_mem_val = _spec_value(["max", "capacity", "памет"])
                    extracted_max_ram = _extract_max_ram_amount_gb(
                        f"{max_mem_val or ''} {raw}"
                    )
                    final["max_ram_amount_gb"] = _normalize_max_ram_amount(
                        extracted_max_ram
                    )

                wifi_rows = []
                for k, v in specs.items():
                    key = str(k)
                    value = str(v)
                    if re.search(
                        r"WI[ -]?FI|WIRELESS|БЕЗЖИЧ|BLUETOOTH|802\.11|ANTEN|CNVIO",
                        key,
                        flags=re.IGNORECASE,
                    ) or re.search(
                        r"WI[ -]?FI|802\.11|BLUETOOTH|ANTEN|CNVIO",
                        value,
                        flags=re.IGNORECASE,
                    ):
                        wifi_rows.append(f"{k}: {v}")
                wifi_text = "\n".join(dict.fromkeys(wifi_rows))
                spec_wifi = _normalize_wifi(wifi_text)
                product_wifi = _extract_wifi_from_product_text(
                    f"{final.get('model') or ''} {parsed.get('name') or ''} {url}"
                )
                text_wifi = _normalize_wifi(
                    _extract_wifi(
                        f"{wifi_text} {final.get('model') or ''} {parsed.get('name') or ''} {raw} {url}"
                    )
                )
                final["onboard_wifi"] = spec_wifi
                if (
                    final["onboard_wifi"] == "Not present"
                    and product_wifi != "Not present"
                ):
                    final["onboard_wifi"] = product_wifi
                if (
                    final["onboard_wifi"] == "Not present"
                    and text_wifi != "Not present"
                ):
                    final["onboard_wifi"] = text_wifi
                ai_wifi = _normalize_wifi(ai_data.get("onboard_wifi"))
                if final["onboard_wifi"] == "Not present" and ai_wifi != "Not present":
                    final["onboard_wifi"] = ai_wifi

                final["io_json"] = _extract_io_json(raw, specs, ai_data.get("io_json"))

                final["price"] = (
                    parsed.get("price")
                    if parsed.get("price") is not None
                    else ai_data.get("price")
                )
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_motherboard(final)
                    counters["successful_upserts"] += 1
                    if not ai_used:
                        counters["fallback_only_upserts"] += 1
                    print(f"    Upserted: {final.get('model')}")
                except Exception as e:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {e}")
                    counters["db_upsert_errors"] += 1

                processed += 1

            except Exception as e:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {e}")
                counters["processing_errors"] += 1

        print(
            "\nSummary: "
            f"collected_urls={counters['collected_urls']}, "
            f"fetched_pages={counters['fetched_pages']}, "
            f"successful_upserts={counters['successful_upserts']}, "
            f"ai_parse_failures={counters['ai_parse_failures']}, "
            f"fallback_only_upserts={counters['fallback_only_upserts']}, "
            f"ai_status={'disabled' if ai_disabled_reason else 'enabled'}, "
            f"skipped_ambiguous_model={counters['skipped_ambiguous_model']}, "
            f"skipped_non_motherboard={counters['skipped_non_motherboard']}, "
            f"skipped_low_signal_page={counters['skipped_low_signal_page']}, "
            f"skipped_integrated_cpu={counters['skipped_integrated_cpu']}, "
            f"skipped_missing_chipset={counters['skipped_missing_chipset']}, "
            f"skipped_invalid_socket={counters['skipped_invalid_socket']}, "
            f"skipped_missing_memory_type={counters['skipped_missing_memory_type']}, "
            f"db_upsert_errors={counters['db_upsert_errors']}, "
            f"processing_errors={counters['processing_errors']}"
        )
        if ai_disabled_reason:
            print(f"AI disabled reason: {ai_disabled_reason}")
