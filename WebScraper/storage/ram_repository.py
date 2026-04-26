from database.session import SessionLocal
from models.ram import RAM
import re


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
    s = str(value).strip()
    upper = s.upper()
    if upper in ("NULL", "NONE", "N/A"):
        return None
    if "G.SKILL" in upper or "GSKILL" in upper:
        return "G.SKILL"
    if "CORSAIR" in upper:
        return "Corsair"
    if "KINGSTON" in upper:
        return "Kingston"
    if "ADATA" in upper:
        return "ADATA"
    if "XPG" in upper or "AXPG" in upper:
        return "ADATA"
    if "CRUCIAL" in upper:
        return "Crucial"
    if "TEAM" in upper and "GROUP" in upper:
        return "TeamGroup"
    if upper.startswith("TEAM"):
        return "TeamGroup"
    if "PATRIOT" in upper:
        return "Patriot"
    if "SAMSUNG" in upper:
        return "Samsung"
    if "HYNIX" in upper:
        return "SK hynix"
    if "MICRON" in upper:
        return "Micron"
    if "HP" in upper:
        return "HP"
    if upper in ("UNKNOWN", "UNSPECIFIED"):
        return None
    return s.title()


def _normalize_model(value):
    if value is None:
        return None
    s = str(value).strip()
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\bDDR\d\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{3,5}\s*MHz\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bCL\s*\d+\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*[x×]\s*\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(SO-?DIMM|UDIMM|DIMM|LAPTOP|DESKTOP|KIT)\b", "", s, flags=re.IGNORECASE
    )
    s = " ".join(s.split())
    return s or None


def _normalize_memory_type(value):
    if value is None:
        return None
    s = str(value).upper()
    m = re.search(r"DDR[3-5]", s)
    return m.group(0) if m else None


def _normalize_memory_amount(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"1x{int(value)}GB"
    s = str(value)
    m = re.search(r"(\d+)\s*[x×*]\s*(\d+)\s*G(?:B)?\b", s, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}GB"
    m = re.search(r"\b(\d{1,3})\s*G(?:B)?\b", s, flags=re.IGNORECASE)
    if m:
        return f"1x{int(m.group(1))}GB"
    return None


def _normalize_latency(value):
    if value is None:
        return None
    s = str(value).upper()
    m = re.search(r"CL\s*(\d+)", s)
    if m:
        return f"CL{m.group(1)}"
    return None


def _normalize_form_factor(value):
    if not value:
        return None
    s = str(value).upper()
    # Canonical pass-through.
    if s.strip() == "LAPTOP":
        return "Laptop"
    if s.strip() == "PC":
        return "PC"
    if any(k in s for k in ("SO-DIMM", "SODIMM", "LAPTOP", "NOTEBOOK", "260-PIN", "260 PIN", "ЛАПТОП", "НОУТБУК")):
        return "Laptop"
    if any(k in s for k in ("UDIMM", "DIMM", "DESKTOP", "PC", "ДЕСКТОП", "НАСТОЛЕН", "НАСТОЛНИ", "НАСТОЛНА")):
        return "PC"
    return None


def _normalize_speed(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    m = re.search(r"(\d{3,5})", s)
    if m:
        return int(m.group(1))
    return None


def _map_input_to_model(ram_data: dict) -> dict:
    for k, v in list(ram_data.items()):
        if isinstance(v, str):
            ram_data[k] = _clean_str(v)

    m = {}
    if ram_data.get("brand") is not None:
        m["brand"] = _normalize_brand(ram_data.get("brand"))
    if ram_data.get("model") is not None:
        m["model"] = _normalize_model(ram_data.get("model"))
    if ram_data.get("memory_type") is not None:
        m["memory_type"] = _normalize_memory_type(ram_data.get("memory_type"))
    if ram_data.get("memory_amount") is not None:
        m["memory_amount"] = _normalize_memory_amount(ram_data.get("memory_amount"))
    if ram_data.get("memory_speed_mhz") is not None:
        m["memory_speed_mhz"] = _normalize_speed(ram_data.get("memory_speed_mhz"))
    if ram_data.get("latency") is not None:
        m["latency"] = _normalize_latency(ram_data.get("latency"))
    if ram_data.get("form_factor") is not None:
        m["form_factor"] = _normalize_form_factor(ram_data.get("form_factor"))
    if ram_data.get("price") is not None:
        m["price_eur"] = ram_data.get("price")
    if ram_data.get("url") is not None:
        m["product_url"] = ram_data.get("url")

    return m


def upsert_ram(ram_data: dict):
    db = SessionLocal()
    mapped = _map_input_to_model(ram_data)
    model_val = mapped.get("model")
    if not model_val:
        db.close()
        raise ValueError("RAM data must include a model")

    ram = None
    product_url = mapped.get("product_url")
    if product_url:
        ram = db.query(RAM).filter(RAM.product_url == product_url).first()

    if ram is None:
        filters = [RAM.model == model_val]
        if mapped.get("brand"):
            filters.append(RAM.brand == mapped["brand"])
        if mapped.get("memory_type"):
            filters.append(RAM.memory_type == mapped["memory_type"])
        if mapped.get("memory_amount"):
            filters.append(RAM.memory_amount == mapped["memory_amount"])
        if mapped.get("memory_speed_mhz") is not None:
            filters.append(RAM.memory_speed_mhz == mapped["memory_speed_mhz"])
        if mapped.get("latency"):
            filters.append(RAM.latency == mapped["latency"])
        if mapped.get("form_factor"):
            filters.append(RAM.form_factor == mapped["form_factor"])
        ram = db.query(RAM).filter(*filters).first()

    if ram:
        for key, value in mapped.items():
            setattr(ram, key, value)
    else:
        ram = RAM(**mapped)
        db.add(ram)

    db.commit()
    db.close()
