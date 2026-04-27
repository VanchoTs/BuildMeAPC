from database.session import SessionLocal
from models.cpu import CPU
from sqlalchemy import func
import re

_socket_memory_cache = {}
_memory_socket_cache = {}
_model_socket_cache = {}


def _clean_str(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    s = s.strip('"').strip("'").strip()
    s = " ".join(s.split())
    return s or None


def _normalize_model_value(model: str | None) -> str | None:
    if not model:
        return None
    s = str(model).strip()

    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)

    s = s.replace("™", "").replace("®", "")

    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"^(INTEL|AMD)\s+", "", s, flags=re.IGNORECASE).strip()
    s = " ".join(s.split())

    m = re.match(
        r"^(?:CORE\s+)?I([3579])[-\s]?(\d{4,5}[A-Z]{0,3})$", s, flags=re.IGNORECASE
    )
    if m:
        return f"Core i{m.group(1)}-{m.group(2).upper()}"

    s = re.sub(r"^RYZEN\b", "Ryzen", s, flags=re.IGNORECASE)
    s = re.sub(r"^CORE\b", "Core", s, flags=re.IGNORECASE)
    return s


def _normalize_socket_value(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    upper = s.upper().strip()
    if upper in ("UNKNOWN", "N/A", "NONE", "NULL", "NOT AVAILABLE"):
        return None

    upper = upper.replace("-", " ").replace("_", " ")
    upper = " ".join(upper.split())

    if re.fullmatch(r"\d{3,5}", upper):
        return f"LGA {upper}"

    m = re.match(r"(FCLGA|LGA)\s*([0-9]{3,5})", upper)
    if m:
        return f"LGA {m.group(2)}"

    if upper in ("AM4", "AM5"):
        return upper
    return upper


def _map_input_to_model(cpu_data: dict) -> dict:

    for k, v in list(cpu_data.items()):
        if isinstance(v, str):
            cpu_data[k] = _clean_str(v)

    m = {}
    if "model" in cpu_data and cpu_data["model"] is not None:
        m["model"] = _normalize_model_value(cpu_data["model"])
    elif "name" in cpu_data and cpu_data["name"] is not None:
        m["model"] = _normalize_model_value(cpu_data["name"])
    if "brand" in cpu_data and cpu_data["brand"] is not None:
        m["brand"] = cpu_data["brand"]
    if "socket" in cpu_data and cpu_data["socket"] is not None:
        m["socket"] = _normalize_socket_value(cpu_data["socket"])
    if "cores" in cpu_data:
        m["cores"] = cpu_data["cores"]
    if "threads" in cpu_data:
        m["threads"] = cpu_data["threads"]
    if "base_clock" in cpu_data and cpu_data["base_clock"] is not None:
        m["base_clock_ghz"] = cpu_data["base_clock"]
    if "boost_clock" in cpu_data and cpu_data["boost_clock"] is not None:
        m["boost_clock_ghz"] = cpu_data["boost_clock"]
    if "tdp" in cpu_data and cpu_data["tdp"] is not None:
        m["tdp_w"] = cpu_data["tdp"]
    if "memory_type" in cpu_data and cpu_data["memory_type"] is not None:
        m["memory_type"] = cpu_data["memory_type"]
    if "price" in cpu_data and cpu_data["price"] is not None:
        m["price_eur"] = cpu_data["price"]
    if "url" in cpu_data and cpu_data["url"] is not None:
        m["product_url"] = cpu_data["url"]

    for k, v in cpu_data.items():
        if k in (
            "model",
            "brand",
            "socket",
            "cores",
            "threads",
            "base_clock_ghz",
            "boost_clock_ghz",
            "tdp_w",
            "memory_type",
            "price_eur",
            "product_url",
        ):
            if v is None:
                continue
            if k == "socket":
                m[k] = _normalize_socket_value(v)
            elif k == "model":
                m[k] = _normalize_model_value(v)
            else:
                m[k] = v

    return m


def upsert_cpu(cpu_data: dict):
    """
    Performs an idempotent update or insert for CPU records.
    Normalizes the model name and attempts to match existing records, 
    including legacy naming conventions (e.g., 'i7-14700' vs 'Core i7-14700').
    """
    db = SessionLocal()
    mapped = _map_input_to_model(cpu_data)

    model_val = mapped.get("model")
    if not model_val:
        db.close()
        raise ValueError("CPU data must include a name/model")

    cpu = db.query(CPU).filter(CPU.model == model_val).first()
    if cpu is None:
        original = cpu_data.get("model") or cpu_data.get("name")
        if original and original != model_val:
            old = db.query(CPU).filter(CPU.model == original).first()
            if old:
                old.model = model_val
                cpu = old
    if cpu is None and model_val and model_val.lower().startswith("core i"):
        legacy = model_val.replace("Core ", "")
        old = db.query(CPU).filter(CPU.model == legacy).first()
        if old:
            old.model = model_val
            cpu = old

    if cpu:
        for key, value in mapped.items():
            setattr(cpu, key, value)
    else:
        cpu = CPU(**mapped)
        db.add(cpu)

    db.commit()
    db.close()


def get_common_memory_type_for_socket(socket: str):
    """
    Statistical helper that looks up the most common memory type (DDR4/DDR5) for a given socket.
    Used for cross-validation when data is missing.
    """
    if not socket:
        return None
    key = str(socket).upper().strip()
    if key in _socket_memory_cache:
        return _socket_memory_cache[key]

    db = SessionLocal()
    try:
        rows = (
            db.query(CPU.memory_type, func.count(CPU.id))
            .filter(CPU.socket == key, CPU.memory_type.isnot(None))
            .group_by(CPU.memory_type)
            .order_by(func.count(CPU.id).desc())
            .all()
        )
        if not rows:
            _socket_memory_cache[key] = None
            return None
        total = sum(r[1] for r in rows)
        top_mem, top_count = rows[0]
        if total and top_count / total >= 0.6:
            _socket_memory_cache[key] = top_mem
            return top_mem
    finally:
        db.close()

    _socket_memory_cache[key] = None
    return None


def get_common_socket_for_memory_type(memory_type: str):
    if not memory_type:
        return None
    key = str(memory_type).upper().strip()
    if key in _memory_socket_cache:
        return _memory_socket_cache[key]

    db = SessionLocal()
    try:
        rows = (
            db.query(CPU.socket, func.count(CPU.id))
            .filter(CPU.memory_type == key, CPU.socket.isnot(None))
            .group_by(CPU.socket)
            .order_by(func.count(CPU.id).desc())
            .all()
        )
        if not rows:
            _memory_socket_cache[key] = None
            return None
        total = sum(r[1] for r in rows)
        top_socket, top_count = rows[0]
        if total and top_count / total >= 0.9:

            _memory_socket_cache[key] = top_socket
            return top_socket
    finally:
        db.close()

    _memory_socket_cache[key] = None
    return None


def _model_base_candidates(model: str) -> list[str]:
    if not model:
        return []
    s = str(model).upper()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\b(INTEL|AMD)\b", "", s)
    s = " ".join(s.split())
    candidates = []

    m = re.match(r"^(CORE\s+ULTRA\s+\d+\s+)(\d{3,5})([A-Z]{1,3})?$", s)
    if m:
        prefix, digits, _suffix = m.groups()
        candidates.append(f"{prefix}{digits}".strip())

    m = re.match(r"^(CORE\s+I[3579])[-\s]?(\d{4,5})([A-Z]{1,3})?$", s)
    if m:
        prefix, digits, _suffix = m.groups()
        candidates.append(f"{prefix}-{digits}".strip())

    m = re.match(r"^(XEON\s+\w+\s+)(\d{4,5})([A-Z]{1,3})?$", s)
    if m:
        prefix, digits, _suffix = m.groups()
        candidates.append(f"{prefix}{digits}".strip())

    m = re.match(r"^(RYZEN\s+\d\s+)(\d{3,5})([A-Z]{1,3})?$", s)
    if m:
        prefix, digits, _suffix = m.groups()
        candidates.append(f"{prefix}{digits}".strip())

    if not candidates:

        m = re.match(r"^(.*?\d{3,5})([A-Z]{1,3})?$", s)
        if m:
            candidates.append(m.group(1).strip())

    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def get_common_socket_for_model(model: str):
    """
    Attempts to predict the socket type based on the model family (e.g., Ryzen 7000 usually = AM5).
    Uses base candidate matching and frequency analysis of the existing database.
    """
    if not model:
        return None
    key = str(model).upper().strip()
    if key in _model_socket_cache:
        return _model_socket_cache[key]

    candidates = _model_base_candidates(model)
    if not candidates:
        _model_socket_cache[key] = None
        return None

    db = SessionLocal()
    try:
        counts = {}
        total = 0
        for base in candidates:
            rows = (
                db.query(CPU.socket, func.count(CPU.id))
                .filter(CPU.model.ilike(f"{base}%"), CPU.socket.isnot(None))
                .group_by(CPU.socket)
                .all()
            )
            for socket_val, count in rows:
                counts[socket_val] = counts.get(socket_val, 0) + count
                total += count
        if not counts or total == 0:
            _model_socket_cache[key] = None
            return None
        top_socket = max(counts, key=counts.get)
        if counts[top_socket] / total >= 0.6:
            _model_socket_cache[key] = top_socket
            return top_socket
    finally:
        db.close()

    _model_socket_cache[key] = None
    return None
