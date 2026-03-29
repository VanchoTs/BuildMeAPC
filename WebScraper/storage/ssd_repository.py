import re

from database.session import SessionLocal
from models.ssd import SSD


def _clean_str(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.strip('"').strip("'").strip()
    s = " ".join(s.split())
    return s or None


def _normalize_brand(value):
    if value is None:
        return None
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if upper in ("NULL", "NONE", "N/A", "UNKNOWN", "UNSPECIFIED"):
        return None
    if "WESTERN DIGITAL" in upper or re.fullmatch(r"WD", upper):
        return "Western Digital"
    if "SAMSUNG" in upper:
        return "Samsung"
    if "KINGSTON" in upper:
        return "Kingston"
    if "CRUCIAL" in upper:
        return "Crucial"
    if "ADATA" in upper or "XPG" in upper:
        return "ADATA"
    if "TEAM" in upper and "GROUP" in upper:
        return "TeamGroup"
    if upper.startswith("TEAM"):
        return "TeamGroup"
    if "SILICON POWER" in upper:
        return "Silicon Power"
    if "GIGABYTE" in upper:
        return "GIGABYTE"
    if "APACER" in upper:
        return "Apacer"
    if "MICRON" in upper:
        return "Micron"
    if "LEXAR" in upper:
        return "Lexar"
    if "KIOXIA" in upper:
        return "Kioxia"
    if "VERBATIM" in upper:
        return "Verbatim"
    if "PATRIOT" in upper:
        return "Patriot"
    if "SEAGATE" in upper:
        return "Seagate"
    if "INTEL" in upper:
        return "Intel"
    if "CORSAIR" in upper:
        return "Corsair"
    if "GOODRAM" in upper:
        return "Goodram"
    if "SK HYNIX" in upper or "HYNIX" in upper:
        return "SK hynix"
    if re.search(r"\bMSI\b", upper):
        return "MSI"
    if re.search(r"\bHP\b", upper):
        return "HP"
    if "SYNOLOGY" in upper:
        return "Synology"
    return None


def _normalize_model(value):
    s = _clean_str(value)
    if not s:
        return None
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"^[Ss][Ss][Dd]\s+", "", s)
    s = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:TB|GB)\b", "", s, flags=re.IGNORECASE
    )
    s = re.sub(r"\b(?:M\.2|NVME|SSD)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\bPCI(?:E| EXPRESS)?(?:\s+GEN)?\s*[3-7](?:\.0)?(?:\s*x\s*[1248])?\b",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\b(?:SATA(?:\s*III)?|2\.5\"|2230|2242|2260|2280|22110|MSATA)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bHEATSINK\b|\bС\s+HEATSINK\b", "", s, flags=re.IGNORECASE)
    s = " ".join(s.split(" / "))
    s = " ".join(s.split())
    return s or None


def _normalize_type(value):
    if value is None:
        return None
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if "M.2" in upper or "NVME" in upper or re.search(r"\b22(?:30|42|60|80|110)\b", upper):
        return "M.2"
    if "SATA" in upper or "2.5" in upper or "MSATA" in upper:
        return "SATA"
    return None


def _normalize_storage_size_gb(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = int(value)
        return val if 32 <= val <= 16384 else None
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper().replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)TB\b", upper)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d{2,5})GB\b", upper)
    if m:
        return int(m.group(1))
    m = re.search(r"\((\d{2,5})GB\)", upper)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{3,5})\b", upper)
    if m:
        candidate = int(m.group(1))
        if 32 <= candidate <= 16384:
            return candidate
    return None


def _normalize_physical_size(value):
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper().replace(" ", "")
    m = re.search(r"\b(2230|2242|2260|2280|22110)\b", upper)
    if m:
        return m.group(1)
    if "MSATA" in upper:
        return "mSATA"
    if "2.5" in upper:
        return '2.5"'
    m = re.search(r"M\.?2.*?22X(30|42|60|80|110)", upper)
    if m:
        tail = m.group(1)
        return "22110" if tail == "110" else f"22{tail}"
    return s


def _normalize_speed_mbps(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 50 <= candidate <= 200000 else None
    s = _clean_str(value)
    if not s:
        return None
    compact = s.upper().replace(" ", "")
    m = re.search(r"(\d{2,6})\s*MB/S", compact)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{2,6})MBPS", compact)
    if m:
        return int(m.group(1))
    digits = re.findall(r"\d+", compact)
    if digits:
        candidate = int("".join(digits[:2])) if len(digits[0]) <= 2 and len(digits) > 1 else int(digits[0])
        if 50 <= candidate <= 200000:
            return candidate
    return None


def _normalize_interface(value):
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    compact = re.sub(r"\s+", "", upper)
    if compact == "SATA":
        return "SATA"
    if compact in ("PCIE", "PCIEXPRESS", "NVME", "PCIENVME"):
        return "PCIe"
    if "SATA" in upper:
        return "SATA III 6Gb/s"
    if "PCIE" not in upper and "PCI EXPRESS" not in upper and "NVME" not in upper:
        return None
    gen_match = re.search(r"(?:GEN\s*|PCIE(?:\s*NVME)?\s*|PCI EXPRESS\s*)([3-7])(?:\.0)?", upper)
    lane_match = re.search(r"\bX\s*([1248])\b", upper)
    if gen_match and lane_match:
        return f"PCIe Gen {gen_match.group(1)} x{lane_match.group(1)}"
    if gen_match:
        return f"PCIe Gen {gen_match.group(1)}"
    return "PCIe"


def _parse_numeric_token(value):
    token = value.strip()
    try:
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
            return float(token.replace(",", "").replace(".", ""))
        if "," in token and re.search(r",\d{3}$", token):
            return float(token.replace(",", ""))
        if "." in token and re.search(r"\.\d{3}$", token):
            return float(token.replace(".", ""))
        return float(token.replace(",", "."))
    except ValueError:
        return None


def _tbw_match_to_tb(number_text, unit_text):
    value = _parse_numeric_token(number_text)
    if value is None:
        return None
    unit = unit_text.upper()
    if unit == "PB":
        return int(round(value * 1000))
    return int(round(value))


def _normalize_tbw_tb(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 1 <= candidate <= 100000 else None
    s = _clean_str(value)
    if not s:
        return None

    labeled_patterns = (
        r"\bTBW\s*[:=-]?\s*(\d[\d.,]*)\s*(PB|TB)\b",
        r"(\d[\d.,]*)\s*(PB|TB)\s*W\b",
    )
    for pattern in labeled_patterns:
        m = re.search(pattern, s, flags=re.IGNORECASE)
        if m:
            candidate = _tbw_match_to_tb(m.group(1), m.group(2))
            return candidate if candidate is not None and 1 <= candidate <= 100000 else None

    m = re.search(r"(\d[\d.,]*)\s*(PB|TB)\b", s, flags=re.IGNORECASE)
    if m:
        candidate = _tbw_match_to_tb(m.group(1), m.group(2))
        return candidate if candidate is not None and 1 <= candidate <= 100000 else None
    return None


def _normalize_nand_type(value):
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if upper in ("NULL", "NONE", "N/A", "UNKNOWN", "UNSPECIFIED"):
        return None
    canonical = re.sub(r"[\s_-]+", " ", upper).strip()
    if ("SAMSUNG" in canonical and "V NAND" in canonical) or canonical == "V NAND":
        return "V-NAND"
    if canonical in {
        "NVME",
        "NVME M.2",
        "NVME M2",
        "M.2",
        "M2",
        "PCIE",
        "PCI EXPRESS",
        "PCIE NVME",
        "SATA",
    }:
        return None
    if re.search(r"\bQLC\b", canonical) or "QUAD LEVEL CELL" in canonical:
        return "QLC"
    if re.search(r"\bSLC\b", canonical) or "SINGLE LEVEL CELL" in canonical:
        return "SLC"
    if re.search(r"\bTLC\b", canonical) or "TRIPLE LEVEL CELL" in canonical:
        return "TLC"
    if re.search(r"\bMLC\b", canonical) or "MULTI LEVEL CELL" in canonical:
        return "MLC"
    if canonical in {"NAND FLASH", "3D NAND", "3D NAND FLASH"}:
        return "NAND"
    if "NVME" in canonical and ("M.2" in upper or re.search(r"\bM2\b", canonical)):
        return None
    return s


def _normalize_has_heatsink(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if any(token in upper for token in ("HEATSINK", "HEAT SINK", "ОХЛАД", "РАДИАТОР")):
        return True
    if upper in ("TRUE", "YES", "1"):
        return True
    if upper in ("FALSE", "NO", "0"):
        return False
    return None


def _map_input_to_model(ssd_data: dict) -> dict:
    for k, v in list(ssd_data.items()):
        if isinstance(v, str):
            ssd_data[k] = _clean_str(v)

    mapped = {}

    brand_val = _normalize_brand(ssd_data.get("brand"))
    if brand_val is not None:
        mapped["brand"] = brand_val

    model_val = _normalize_model(ssd_data.get("model") or ssd_data.get("name"))
    if model_val is not None:
        mapped["model"] = model_val

    type_source = ssd_data.get("type")
    if type_source is None:
        type_source = " ".join(
            str(x)
            for x in (
                ssd_data.get("physical_size"),
                ssd_data.get("interface"),
                ssd_data.get("model"),
                ssd_data.get("name"),
            )
            if x
        )
    type_val = _normalize_type(type_source)
    if type_val is not None:
        mapped["type"] = type_val

    size_val = _normalize_storage_size_gb(ssd_data.get("storage_size_gb") or ssd_data.get("storage_size"))
    if size_val is not None:
        mapped["storage_size_gb"] = size_val

    physical_val = _normalize_physical_size(ssd_data.get("physical_size"))
    if physical_val is not None:
        mapped["physical_size"] = physical_val

    read_val = _normalize_speed_mbps(ssd_data.get("read_speed_mbps") or ssd_data.get("read_speed"))
    if read_val is not None:
        mapped["read_speed_mbps"] = read_val

    write_val = _normalize_speed_mbps(ssd_data.get("write_speed_mbps") or ssd_data.get("write_speed"))
    if write_val is not None:
        mapped["write_speed_mbps"] = write_val

    interface_source = ssd_data.get("interface")
    if interface_source is None:
        interface_source = " ".join(
            str(x)
            for x in (ssd_data.get("type"), ssd_data.get("physical_size"), ssd_data.get("name"))
            if x
        )
    interface_val = _normalize_interface(interface_source)
    if interface_val is not None:
        mapped["interface"] = interface_val

    tbw_val = _normalize_tbw_tb(ssd_data.get("tbw_tb") or ssd_data.get("tbw"))
    if tbw_val is not None:
        mapped["tbw_tb"] = tbw_val

    nand_val = _normalize_nand_type(ssd_data.get("nand_type"))
    if nand_val is not None:
        mapped["nand_type"] = nand_val

    heatsink_source = ssd_data.get("has_heatsink")
    if heatsink_source is None:
        heatsink_source = " ".join(
            str(x)
            for x in (ssd_data.get("model"), ssd_data.get("name"), ssd_data.get("physical_size"))
            if x
        )
    heatsink_val = _normalize_has_heatsink(heatsink_source)
    if heatsink_val is not None:
        mapped["has_heatsink"] = heatsink_val

    if ssd_data.get("price") is not None:
        mapped["price_eur"] = ssd_data.get("price")
    elif ssd_data.get("price_eur") is not None:
        mapped["price_eur"] = ssd_data.get("price_eur")

    if ssd_data.get("url") is not None:
        mapped["product_url"] = ssd_data.get("url")
    elif ssd_data.get("product_url") is not None:
        mapped["product_url"] = ssd_data.get("product_url")

    return mapped


def upsert_ssd(ssd_data: dict):
    db = SessionLocal()
    mapped = _map_input_to_model(ssd_data)
    model_val = mapped.get("model")
    if not model_val:
        db.close()
        raise ValueError("SSD data must include a model")

    ssd = None
    product_url = mapped.get("product_url")
    if product_url:
        ssd = db.query(SSD).filter(SSD.product_url == product_url).first()

    if ssd is None:
        filters = [SSD.model == model_val]
        if mapped.get("brand"):
            filters.append(SSD.brand == mapped["brand"])
        if mapped.get("storage_size_gb") is not None:
            filters.append(SSD.storage_size_gb == mapped["storage_size_gb"])
        if mapped.get("type"):
            filters.append(SSD.type == mapped["type"])
        if mapped.get("interface"):
            filters.append(SSD.interface == mapped["interface"])
        if mapped.get("physical_size"):
            filters.append(SSD.physical_size == mapped["physical_size"])
        if mapped.get("has_heatsink") is not None:
            filters.append(SSD.has_heatsink == mapped["has_heatsink"])
        ssd = db.query(SSD).filter(*filters).first()

    if ssd:
        for key, value in mapped.items():
            setattr(ssd, key, value)
    else:
        ssd = SSD(**mapped)
        db.add(ssd)

    db.commit()
    db.close()
