"""
Motherboard Repository Module.

This module manages database interactions for Motherboard records. It includes
comprehensive normalization for brands, form factors, sockets, chipsets, and
peripheral interfaces. A key feature is the frequency-based inference logic
that predicts the correct CPU socket or dominant memory type (DDR4 vs DDR5)
based on the motherboard's chipset using existing database records.
"""

from database.session import SessionLocal
from models.motherboard import Motherboard
import json
import re
from sqlalchemy import func

_chipset_socket_cache = {}


def _clean_str(value):
    """Basic string cleaning: strip whitespace and quotes."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.strip('"').strip("'").strip()
    s = " ".join(s.split())
    return s or None


def _normalize_brand(value):
    """Normalizes motherboard manufacturer brands (ASUS, MSI, GIGABYTE, etc.)."""
    if value is None:
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


def _infer_brand(model, name, url):
    """Infers the manufacturer brand from multiple text sources including the URL slug."""
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


def _normalize_form_factor(value):
    """Standardizes motherboard form factors (ATX, mATX, ITX, etc.)."""
    if value is None:
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


def _normalize_socket(value):
    """
    Standardizes CPU socket names (e.g., LGA 1700, AM5).
    Includes logic to clean up noisy retailer strings.
    """
    if value is None:
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


def _normalize_chipset(value):
    """Extracts and standardizes the motherboard chipset (e.g., B760, X670E)."""
    if value is None:
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
        if base == "H61":
            return "H610"
        if suffix == "E" and base[0] in {"A", "B", "X"}:
            return f"{base}E"
        return base
    return None


def _correct_chipset_alias(chipset, model=None, name=None, url=None, socket=None, memory_type=None):
    """
    Handles chipset aliasing and context-aware corrections.
    For example, standardizes 'H61' to 'H610' or identifies modern AM5 chipsets 
    that might be mislabeled in legacy patterns.
    """
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


def _normalize_memory_type(value):
    """Extracts supported memory types (DDR4, DDR5) and handles dual-support strings."""
    if value is None:
        return None
    s = str(value).upper()
    vals = []
    for t in re.findall(r"DDR[3-5]", s):
        if t not in vals:
            vals.append(t)
    if not vals:
        return None
    return "/".join(vals)


def _normalize_wifi(value):
    """
    Standardizes onboard Wi-Fi information.
    Distinguishes between actual Wi-Fi chips, versioned support (Wi-Fi 6, 7),
    and mere accessory/antenna points.
    """
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


def _to_int(value):
    """Helper to convert various types/formats to an integer."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    if m:
        return int(m.group(0))
    return None


def _normalize_max_ram_speed(value):
    """Standardizes maximum RAM frequency in MHz."""
    v = _to_int(value)
    if v is None:
        return None
    if v < 1600 or v > 10000:
        return None
    return v


def _normalize_ram_slots(value, explicit: bool = False):
    """
    Standardizes the number of RAM slots.
    Filters out unlikely values and assumes standard pairs (2, 4, 8) unless explicit.
    """
    v = _to_int(value)
    if v is None:
        return None
    if v == 1 and not explicit:
        return None
    if v <= 0 or v > 8:
        return None
    if v % 2 == 1 and v != 1:
        return None
    return v


def _normalize_m2_version(value):
    """Identifies the PCIe generation for M.2 slots (Gen3, Gen4, Gen5, etc.)."""
    if not value:
        return None
    s = str(value).upper()
    if "KEY" in s:
        return None
    vals = []
    for g in re.findall(r"GEN\s*([3-7])", s):
        token = f"Gen{g}"
        if token not in vals:
            vals.append(token)
    for g in re.findall(
        r"PCI(?:E|\s*EXPRESS)?(?:\s+GEN\s*|\s+)([3-7])(?:\.0)?", s
    ):
        token = f"Gen{g}"
        if token not in vals:
            vals.append(token)
    if not vals:
        return None
    vals = sorted(dict.fromkeys(vals), key=lambda x: int(re.search(r"\d+", x).group(0)))
    return vals[-1]


def _normalize_m2_slots(value):
    """Standardizes M.2 slot configuration into a list of count and version objects."""
    if isinstance(value, dict):
        entries = [value]
    elif isinstance(value, list):
        entries = value
    else:
        return []
    merged = {}
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
        merged[key] = max(merged.get(key, 0), count)
    out = [{"count": c, "version": v} for (v,), c in merged.items() if c > 0]
    out.sort(
        key=lambda x: (
            -int(re.search(r"\d+", x["version"]).group(0))
            if isinstance(x.get("version"), str) and re.search(r"\d+", x["version"])
            else -1
        )
    )
    return out


def _normalize_pcie_version(value):
    """Standardizes PCIe slot generation (Gen3, Gen4, etc.)."""
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


def _normalize_lan_ports(value):
    """Standardizes the number of Ethernet ports."""
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


def _normalize_lan_speed(value):
    """Standardizes LAN maximum speed (e.g., 2.5 Gb)."""
    if not value:
        return None
    s = str(value).strip().upper().replace("GBE", "GB")
    slash_match = re.search(
        r"((?:\d{2,5}\s*/\s*)+\d{2,5})\s*M(?:BIT|B)(?:/S|PS)?", s
    )
    if slash_match:
        nums = [int(x) for x in re.findall(r"\d{2,5}", slash_match.group(1))]
        if nums:
            top = max(nums)
            if top >= 1000:
                speed = top / 1000
                return f"{speed:g} Gb"
    if re.search(r"\bGIGABIT\s+ETHERNET\b", s):
        return "1 Gb"
    m = re.search(r"(10|5|2\.5|1)\s*GB", s)
    if m:
        return f"{m.group(1)} Gb"
    m = re.search(r"(10|5|2\.5|1)\s*G", s)
    if m:
        return f"{m.group(1)} Gb"
    if re.search(r"\b10000\s*M(?:BIT|B)?(?:/S|PS)?\b", s):
        return "10 Gb"
    if re.search(r"\b5000\s*M(?:BIT|B)?(?:/S|PS)?\b", s):
        return "5 Gb"
    if re.search(r"\b2500\s*M(?:BIT|B)?(?:/S|PS)?\b", s):
        return "2.5 Gb"
    if re.search(r"\b1000\s*M(?:BIT|B)?(?:/S|PS)?\b", s):
        return "1 Gb"
    return None


def _normalize_usb_type(value, normalized_version=None):
    """Standardizes USB port types (Type-A, Type-C)."""
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


def _normalize_usb_version(value, gen=None):
    """Standardizes USB versions and generations (e.g., 3.2 Gen2x2)."""
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
    gm = re.search(r"GEN\s*(\d(?:X\d)?)", s)
    if gm and base in ("3.2",):
        return f"{base} Gen{gm.group(1).replace('X', 'x')}"
    return base


def _normalize_usb_ports(entries):
    """Standardizes USB port configuration into a list of count, type, and version objects."""
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
        if not usb_type or not version:
            continue
        key = (usb_type, version)
        merged[key] = merged.get(key, 0) + count
    return [
        {"count": min(count, 20), "type": t, "version": v}
        for (t, v), count in merged.items()
    ]


def _normalize_pcie_slots(entries):
    """Standardizes PCIe slot configuration including lane count and generation."""
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
        if count is None or count <= 0 or count > 16:
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


def _normalize_max_ram_amount(value):
    """Standardizes maximum supported RAM capacity in GB."""
    v = _to_int(value)
    if v is None:
        return None
    if v <= 0 or v == 10 or v > 4096:
        return None
    return v


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


def _normalize_io_json(value):
    """Normalizes the complete I/O specification object into structured JSON."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return None
    if not isinstance(value, dict):
        return None

    out = {key: value.get(key) for key in _IO_JSON_KEYS}
    out["m2_slots"] = _normalize_m2_slots(out.get("m2_slots"))

    sata = _to_int(out.get("sata_slots"))
    if sata is not None and (sata <= 0 or sata > 16):
        sata = None
    out["sata_slots"] = sata

    out["pcie_slots"] = _normalize_pcie_slots(out.get("pcie_slots"))
    out["usb_ports"] = _normalize_usb_ports(out.get("usb_ports"))

    dp = _to_int(out.get("displayport_ports"))
    out["displayport_ports"] = None if dp is None or dp <= 0 or dp > 4 else dp
    hdmi = _to_int(out.get("hdmi_ports"))
    out["hdmi_ports"] = None if hdmi is None or hdmi <= 0 or hdmi > 4 else hdmi

    out["lan_ports"] = _normalize_lan_ports(out.get("lan_ports"))
    out["lan_max_speed"] = _normalize_lan_speed(out.get("lan_max_speed"))
    if out.get("lan_ports") is None:
        out["lan_max_speed"] = None
    return out


def _map_input_to_model(mb_data: dict) -> dict:
    """Maps raw scraper dictionary keys to Motherboard model attributes."""
    for k, v in list(mb_data.items()):
        if isinstance(v, str):
            mb_data[k] = _clean_str(v)

    mapped = {}
    normalized_brand = _normalize_brand(mb_data.get("brand"))
    inferred_brand = _infer_brand(
        mb_data.get("model"),
        mb_data.get("name"),
        mb_data.get("url") or mb_data.get("product_url"),
    )
    if normalized_brand is None:
        normalized_brand = inferred_brand
    else:
        current_upper = str(normalized_brand).upper()
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
            normalized_brand = inferred_brand or None
        elif current_upper == "INTEL" and inferred_brand == "GIGABYTE":
            normalized_brand = inferred_brand
    if normalized_brand is not None:
        mapped["brand"] = normalized_brand
    if mb_data.get("model") is not None:
        mapped["model"] = mb_data.get("model")
    if mb_data.get("form_factor") is not None:
        mapped["form_factor"] = _normalize_form_factor(mb_data.get("form_factor"))
    if mb_data.get("chipset") is not None:
        mapped["chipset"] = _normalize_chipset(mb_data.get("chipset"))
    if mb_data.get("socket") is not None:
        mapped["socket"] = _normalize_socket(mb_data.get("socket"))
    if mb_data.get("memory_type") is not None:
        mapped["memory_type"] = _normalize_memory_type(mb_data.get("memory_type"))
    if mb_data.get("ram_slots") is not None:
        mapped["ram_slots"] = _normalize_ram_slots(
            mb_data.get("ram_slots"),
            explicit=bool(
                mb_data.get("ram_slots_explicit")
                or mb_data.get("ram_slots_source")
                or mb_data.get("ram_slots_evidence")
            ),
        )
    if mb_data.get("max_ram_speed_mhz") is not None:
        mapped["max_ram_speed_mhz"] = _normalize_max_ram_speed(
            mb_data.get("max_ram_speed_mhz")
        )
    if mb_data.get("max_ram_amount_gb") is not None:
        mapped["max_ram_amount_gb"] = _normalize_max_ram_amount(
            mb_data.get("max_ram_amount_gb")
        )
    mapped["onboard_wifi"] = _normalize_wifi(mb_data.get("onboard_wifi"))
    if mb_data.get("io_json") is not None:
        mapped["io_json"] = _normalize_io_json(mb_data.get("io_json"))
    if mb_data.get("price") is not None:
        mapped["price_eur"] = mb_data.get("price")
    if mb_data.get("url") is not None:
        mapped["product_url"] = mb_data.get("url")

    if mapped.get("chipset") is not None:
        mapped["chipset"] = _correct_chipset_alias(
            mapped.get("chipset"),
            mb_data.get("model"),
            mb_data.get("name"),
            mb_data.get("url") or mb_data.get("product_url"),
            mapped.get("socket"),
            mapped.get("memory_type"),
        )

    return mapped


def upsert_motherboard(mb_data: dict):
    """
    Inserts or updates a Motherboard record in the database.
    Includes frequency-based inference logic: if the socket is missing but the 
    chipset is known, it queries the database for the most common socket 
    associated with that chipset to fill the gap.
    """
    db = SessionLocal()
    mapped = _map_input_to_model(mb_data)

    if not mapped.get("model"):
        db.close()
        raise ValueError("Motherboard data must include a model")

    if mapped.get("socket") is None and mapped.get("chipset"):
        rows = (
            db.query(Motherboard.socket, func.count(Motherboard.id))
            .filter(
                Motherboard.chipset == mapped["chipset"],
                Motherboard.socket.isnot(None),
            )
            .group_by(Motherboard.socket)
            .order_by(func.count(Motherboard.id).desc())
            .all()
        )
        if rows:
            mapped["socket"] = rows[0][0]
    if mapped.get("socket") is None:
        db.close()
        raise ValueError("Motherboard data must include a valid socket")

    mb = None
    if mapped.get("product_url"):
        mb = (
            db.query(Motherboard)
            .filter(Motherboard.product_url == mapped["product_url"])
            .first()
        )

    if mb is None:
        filters = [Motherboard.model == mapped["model"]]
        if mapped.get("brand"):
            filters.append(Motherboard.brand == mapped["brand"])
        if mapped.get("socket"):
            filters.append(Motherboard.socket == mapped["socket"])
        if mapped.get("chipset"):
            filters.append(Motherboard.chipset == mapped["chipset"])
        mb = db.query(Motherboard).filter(*filters).first()

    if mb:
        for key, value in mapped.items():
            setattr(mb, key, value)
    else:
        mb = Motherboard(**mapped)
        db.add(mb)

    if mapped.get("chipset") and mapped.get("socket"):
        _chipset_socket_cache[mapped["chipset"]] = mapped["socket"]

    db.commit()
    db.close()


def get_common_socket_for_chipset(chipset: str):
    """
    Predicts the CPU socket for a given motherboard chipset.
    Uses database frequency analysis (e.g., B760 is typically LGA 1700).
    """
    if not chipset:
        return None
    key = _normalize_chipset(chipset)
    if not key:
        return None
    if key in _chipset_socket_cache:
        return _chipset_socket_cache[key]
    db = SessionLocal()
    try:
        rows = (
            db.query(Motherboard.socket, func.count(Motherboard.id))
            .filter(
                Motherboard.chipset == key,
                Motherboard.socket.isnot(None),
            )
            .group_by(Motherboard.socket)
            .order_by(func.count(Motherboard.id).desc())
            .all()
        )
        value = rows[0][0] if rows else None
        if value is not None:
            _chipset_socket_cache[key] = value
        return value
    finally:
        db.close()


def get_dominant_memory_type_for_chipset(chipset: str):
    """
    Predicts the dominant memory type (DDR4 vs DDR5) for a given chipset.
    Returns the most frequent type if it significantly outweighs alternatives.
    """
    if not chipset:
        return None
    key = _normalize_chipset(chipset)
    if not key:
        return None
    db = SessionLocal()
    try:
        rows = (
            db.query(Motherboard.memory_type, func.count(Motherboard.id))
            .filter(
                Motherboard.chipset == key,
                Motherboard.memory_type.isnot(None),
            )
            .group_by(Motherboard.memory_type)
            .order_by(func.count(Motherboard.id).desc(), Motherboard.memory_type.asc())
            .all()
        )
        if not rows:
            return None
        top_value, top_count = rows[0]
        next_count = rows[1][1] if len(rows) > 1 else 0
        if top_value is None or top_count <= 0 or top_count == next_count:
            return None
        return _normalize_memory_type(top_value)
    finally:
        db.close()
