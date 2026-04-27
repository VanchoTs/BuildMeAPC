"""
GPU Repository Module.

This module manages database interactions for GPU records. It includes logic
for normalizing GPU specifications (brand, manufacturer, model) and 
frequency-based inference logic to predict missing fields like memory type 
or interface based on established patterns for specific models in the database.
"""

from database.session import SessionLocal
from models.gpu import GPU
from sqlalchemy import func
import re

_model_memory_cache = {}
_model_interface_cache = {}


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
    """Normalizes the primary GPU chip designer (NVIDIA, AMD, Intel)."""
    if value is None:
        return None
    s = str(value).strip().upper()
    if "NVIDIA" in s:
        return "NVIDIA"
    if "AMD" in s or "RADEON" in s:
        return "AMD"
    if "INTEL" in s or "ARC" in s:
        return "Intel"
    return s.title()


def _normalize_pcb_manufacturer(value):
    """Normalizes the brand of the actual graphics card manufacturer (ASUS, MSI, etc.)."""
    if value is None:
        return None
    s = str(value).strip()
    upper = s.upper()
    if "ASROCK" in upper:
        return "ASRock"
    if "ASUS" in upper:
        return "ASUS"
    if "MSI" in upper:
        return "MSI"
    if "BIOSTAR" in upper:
        return "Biostar"
    if "GIGABYTE" in upper:
        return "GIGABYTE"
    if "PALIT" in upper:
        return "PALIT"
    if "POWERCOLOR" in upper or "POWER COLOR" in upper:
        return "PowerColor"
    if "SAPPHIRE" in upper:
        return "Sapphire"
    if "XFX" in upper:
        return "XFX"
    if "ZOTAC" in upper:
        return "ZOTAC"
    if "PNY" in upper:
        return "PNY"
    return s.title()


def _normalize_model(value):
    """
    Normalizes GPU model names into a canonical form (e.g., 'GeForce RTX 3060').
    Removes trademark symbols and standardizes prefixes for NVIDIA, AMD, and Intel.
    """
    if value is None:
        return None
    s = str(value).strip()
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = " ".join(s.split())
    s = re.sub(r"^GEFORCE", "GeForce", s, flags=re.IGNORECASE)
    s = re.sub(r"^RADEON", "Radeon", s, flags=re.IGNORECASE)
    s = re.sub(r"^ARC", "Arc", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\bRadeon\s+R(\d{3,4})[A-Za-z].*",
        r"Radeon RX \1",
        s,
        flags=re.IGNORECASE,
    )
    if re.match(r"^N\s*\d{4}", s, flags=re.IGNORECASE):
        s = re.sub(r"^N\s*(\d{4}).*$", r"GeForce RTX \1", s, flags=re.IGNORECASE)
    if re.match(r"^GT\s*\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^GT\s*(\d{3,4})$", r"GeForce GT \1", s, flags=re.IGNORECASE)
    if re.match(r"^RTX\s*A\d{3,4}$", s, flags=re.IGNORECASE):
        return re.sub(r"^RTX\s*", "RTX ", s, flags=re.IGNORECASE)
    if re.match(r"^RTX\s*\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^RTX\s*(\d{3,4})$", r"GeForce RTX \1", s, flags=re.IGNORECASE)
    if re.match(r"^RX\s*\d{3,4}", s, flags=re.IGNORECASE):
        s = re.sub(r"^RX\s*(\d{3,4})", r"Radeon RX \1", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\bRadeon\s+RX\s+9(\d{2})\s*(XT|XTX|GRE)\b",
        r"Radeon RX 90\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX|GeForce\s+GT)\s*(\d{3,4})\s*(TI|SUPER)\b",
        r"\1 \2 \3",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX)\s*(\d{3,4})\s*(TI)\b",
        r"\1 \2 Ti",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX)\s*(\d{3,4})\s*(SUPER)\b",
        r"\1 \2 Super",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\bRadeon\s+RX\s*(\d{3,4})\s*(XT|XTX|GRE)\b",
        r"Radeon RX \1 \2",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^GeForce\s+RTX\s+(1000|2000|4000)\b",
        r"RTX \1",
        s,
        flags=re.IGNORECASE,
    )
    base_patterns = [
        r"(GeForce\s+RTX\s+\d{3,4}\s*(?:Ti|Super)?)",
        r"(GeForce\s+GTX\s+\d{3,4}\s*(?:Ti|Super)?)",
        r"(GeForce\s+GT\s+\d{3,4})",
        r"(Radeon\s+RX\s+\d{3,4}\s*(?:XT|XTX|GRE|M)?)",
        r"(Arc\s+[A-Z]\d{3,4})",
        r"(RTX\s+\d{4})",
    ]
    for pat in base_patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            s = " ".join(m.group(1).split())
            break
    s = re.sub(
        r"\b(Radeon\s+RX\s+\d{3,4})(XT|XTX|GRE|M)\b",
        r"\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    return s or None


def _map_input_to_model(gpu_data: dict) -> dict:
    """Maps raw scraper dictionary keys to the GPU model attributes."""
    for k, v in list(gpu_data.items()):
        if isinstance(v, str):
            gpu_data[k] = _clean_str(v)

    m = {}
    if "model" in gpu_data and gpu_data["model"] is not None:
        m["model"] = _normalize_model(gpu_data["model"])
    elif "name" in gpu_data and gpu_data["name"] is not None:
        m["model"] = _normalize_model(gpu_data["name"])
    if "brand" in gpu_data and gpu_data["brand"] is not None:
        m["brand"] = _normalize_brand(gpu_data["brand"])
    if "pcb_manufacturer" in gpu_data and gpu_data["pcb_manufacturer"] is not None:
        m["pcb_manufacturer"] = _normalize_pcb_manufacturer(
            gpu_data["pcb_manufacturer"]
        )
    if "pcb_series" in gpu_data and gpu_data["pcb_series"] is not None:
        m["pcb_series"] = gpu_data["pcb_series"]
    if "vram_gb" in gpu_data:
        m["vram_gb"] = gpu_data["vram_gb"]
    if "memory_type" in gpu_data and gpu_data["memory_type"] is not None:
        m["memory_type"] = gpu_data["memory_type"]
    if "memory_bus_bit" in gpu_data:
        m["memory_bus_bit"] = gpu_data["memory_bus_bit"]
    if "base_clock_mhz" in gpu_data and gpu_data["base_clock_mhz"] is not None:
        m["base_clock_mhz"] = gpu_data["base_clock_mhz"]
    if "boost_clock_mhz" in gpu_data and gpu_data["boost_clock_mhz"] is not None:
        m["boost_clock_mhz"] = gpu_data["boost_clock_mhz"]
    if "tdp" in gpu_data and gpu_data["tdp"] is not None:
        m["tdp_w"] = gpu_data["tdp"]
    if "interface" in gpu_data and gpu_data["interface"] is not None:
        m["interface"] = gpu_data["interface"]
    if "price" in gpu_data and gpu_data["price"] is not None:
        m["price_eur"] = gpu_data["price"]
    if "url" in gpu_data and gpu_data["url"] is not None:
        m["product_url"] = gpu_data["url"]

    for k, v in gpu_data.items():
        if k in (
            "model",
            "brand",
            "pcb_manufacturer",
            "pcb_series",
            "vram_gb",
            "memory_type",
            "memory_bus_bit",
            "base_clock_mhz",
            "boost_clock_mhz",
            "tdp_w",
            "interface",
            "price_eur",
            "product_url",
        ):
            if v is not None:
                if k == "model":
                    m[k] = _normalize_model(v)
                elif k == "brand":
                    m[k] = _normalize_brand(v)
                elif k == "pcb_manufacturer":
                    m[k] = _normalize_pcb_manufacturer(v)
                else:
                    m[k] = v

    return m


def upsert_gpu(gpu_data: dict):
    """
    Inserts or updates a GPU record in the database.
    Deduplicates based on product URL or a combination of model,
    manufacturer, series, and VRAM capacity.
    """
    db = SessionLocal()
    mapped = _map_input_to_model(gpu_data)
    model_val = mapped.get("model")
    if not model_val:
        db.close()
        raise ValueError("GPU data must include a model")

    gpu = None
    product_url = mapped.get("product_url")
    if product_url:
        gpu = db.query(GPU).filter(GPU.product_url == product_url).first()

    if gpu is None:
        filters = [GPU.model == model_val]
        if mapped.get("pcb_manufacturer"):
            filters.append(GPU.pcb_manufacturer == mapped["pcb_manufacturer"])
        if mapped.get("pcb_series"):
            filters.append(GPU.pcb_series == mapped["pcb_series"])
        if mapped.get("vram_gb") is not None:
            filters.append(GPU.vram_gb == mapped["vram_gb"])
        gpu = db.query(GPU).filter(*filters).first()

    if gpu:
        for key, value in mapped.items():
            setattr(gpu, key, value)
    else:
        gpu = GPU(**mapped)
        db.add(gpu)

    db.commit()
    db.close()


def _model_candidates(model: str) -> list[str]:
    """Generates a list of potential model name variations for pattern matching."""
    if not model:
        return []
    s = str(model)
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = " ".join(s.split())
    candidates = []
    m = re.search(r"(GeForce\s+RTX\s+\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        base = m.group(1)
        candidates.append(base)
        num = re.search(r"\d{3,4}", base)
        if num:
            digits = num.group(0)
            if len(digits) >= 3:
                prefix = digits[:2]
                candidates.append(f"GeForce RTX {prefix}")
    m = re.search(r"(GeForce\s+GTX\s+\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        base = m.group(1)
        candidates.append(base)
        num = re.search(r"\d{3,4}", base)
        if num:
            digits = num.group(0)
            prefix = digits[:2] if len(digits) >= 3 else digits[:1]
            candidates.append(f"GeForce GTX {prefix}")
    m = re.search(r"(GeForce\s+GT\s+\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        base = m.group(1)
        candidates.append(base)
        num = re.search(r"\d{3,4}", base)
        if num:
            digits = num.group(0)
            prefix = digits[:1]
            candidates.append(f"GeForce GT {prefix}")
    m = re.search(r"(Radeon\s+RX\s+\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        base = m.group(1)
        candidates.append(base)
        num = re.search(r"\d{3,4}", base)
        if num:
            digits = num.group(0)
            prefix = digits[:1]
            candidates.append(f"Radeon RX {prefix}")
            if len(digits) >= 2:
                candidates.append(f"Radeon RX {digits[:2]}")
    m = re.search(r"(Arc\s+[A-Z]\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        candidates.append(m.group(1))
    m = re.search(r"(RTX\s+\d{4})", s, flags=re.IGNORECASE)
    if m:
        candidates.append(m.group(1))
    out = []
    seen = set()
    for c in candidates:
        c = _normalize_model(c)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _most_common_value(db, field, patterns):
    """
    Finds the most frequent value for a field among records matching certain model patterns.
    Requires at least 60% frequency to return a value, ensuring high confidence in the inference.
    """
    counts = {}
    total = 0
    for p in patterns:
        rows = (
            db.query(field, func.count(GPU.id))
            .filter(GPU.model.ilike(f"{p}%"), field.isnot(None))
            .group_by(field)
            .all()
        )
        for val, cnt in rows:
            counts[val] = counts.get(val, 0) + cnt
            total += cnt
    if not counts or total == 0:
        return None
    top = max(counts, key=counts.get)
    if counts[top] / total >= 0.6:
        return top
    return None


def get_common_memory_type_for_model(model: str):
    """
    Infers the common memory type (e.g., GDDR6) for a GPU model.
    Uses database frequency analysis to predict the likely memory type.
    """
    if not model:
        return None
    key = str(model).upper().strip()
    if key in _model_memory_cache:
        return _model_memory_cache[key]
    candidates = _model_candidates(model)
    if not candidates:
        _model_memory_cache[key] = None
        return None
    db = SessionLocal()
    try:
        value = _most_common_value(db, GPU.memory_type, candidates)
        _model_memory_cache[key] = value
        return value
    finally:
        db.close()


def get_common_interface_for_model(model: str):
    """
    Infers the common interface (e.g., PCIe 4.0 x16) for a GPU model.
    Uses database frequency analysis to predict the likely interface.
    """
    if not model:
        return None
    key = str(model).upper().strip()
    if key in _model_interface_cache:
        return _model_interface_cache[key]
    candidates = _model_candidates(model)
    if not candidates:
        _model_interface_cache[key] = None
        return None
    db = SessionLocal()
    try:
        value = _most_common_value(db, GPU.interface, candidates)
        _model_interface_cache[key] = value
        return value
    finally:
        db.close()
