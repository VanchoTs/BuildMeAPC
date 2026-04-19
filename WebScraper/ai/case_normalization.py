import re
from typing import Optional

from ai.case_brands import CASE_BRAND_MAP as _CASE_BRAND_MAP


def _clean_str(value: str | None) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("™", "").replace("®", "")
    s = s.strip('"').strip("'").strip()
    s = " ".join(s.split())
    if not s or s.upper() in ("NULL", "NONE", "N/A", "UNKNOWN", "UNSPECIFIED"):
        return None
    return s


def normalize_case_brand(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()

    matches = []
    for token, normalized in _CASE_BRAND_MAP.items():
        pattern = r"\b" + re.escape(token) + r"\b"
        match = re.search(pattern, upper)
        if match:
            matches.append((match.start(), normalized))

    if not matches:
        return None

    matches.sort()
    return matches[0][1]


def normalize_case_model(value: str | None, brand: str | None = None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None

    # Strip Cyrillic "Кутия" prefix
    s = re.sub(r"(?i)^\s*кутия\s*", "", s)

    # Strip parenthesized text
    s = re.sub(r"\(.*?\)", "", s)

    if brand:
        s = re.sub(re.escape(brand), "", s, flags=re.IGNORECASE).strip()

    # Strip descriptors that pollute model names
    descriptors = [
        r"MIDDLE\s+TOWER",
        r"MID\s+TOWER",
        r"FULL\s+TOWER",
        r"MINI\s+TOWER",
        r"TEMPERED\s+GLASS",
        r"ARGB",
        r"RGB",
        r"E-ATX",
        r"EATX",
        r"MICRO[-\s]+ATX",
        r"M-ATX",
        r"MATX",
        r"MINI[-\s]+ITX",
        r"M-ITX",
        r"MITX",
        r"ATX",
    ]
    for d in descriptors:
        s = re.sub(r"\b" + d + r"\b", "", s, flags=re.IGNORECASE)

    # Strip trailing color tokens
    color_tokens = [
        "BLACK", "WHITE", "GREY", "GRAY", "SILVER", "RED", "BLUE", "GREEN",
        "PINK", "PURPLE", "YELLOW", "ORANGE",
        "ЧЕРЕН", "ЧЕРНА", "ЧЕРНО",
        "БЯЛ", "БЯЛА", "БЯЛО",
        "СИВ", "СИВА", "СИВО",
        "ЧЕРВЕН", "ЧЕРВЕНА",
        "СИН", "СИНЯ",
        "ЗЕЛЕН", "ЗЕЛЕНА",
    ]
    color_pattern = r"(?i)\b(?:" + "|".join(color_tokens) + r")\b"
    # Strip trailing colors repeatedly
    prev = None
    while prev != s:
        prev = s
        s = re.sub(color_pattern + r"\s*$", "", s).strip(" -,")
    # Also strip any remaining color tokens anywhere
    s = re.sub(color_pattern, "", s)

    s = " ".join(s.split()).strip("- ,")

    # Orphan leading single-letter prefix incl. Cyrillic: "А- - ACFRE..." -> "ACFRE..."
    s = re.sub(r"^\s*[A-Za-zА-Яа-я]\s*-\s*-\s*", "", s).strip()

    # Strip leading stray punctuation
    s = re.sub(r"^[\s,\-]+", "", s)

    # Strip truncation ellipsis
    s = re.sub(r"(?:\.{3,}|…)", " ", s)

    # Strip descriptive prefixes/phrases that pollute model names
    descriptive_phrases = [
        r"Panel",
        r"PC\s+Case",
        r"Power\s+Supply(?:\s+(?:AC|DC))?",
        r"\d{2,4}\s*mm\s+Radiator",
        r"Radiator",
        r"NVIDIA\s+Limit\w*(?:\s+Edition)?",
        r"Limited\s+Edition",
    ]
    for d in descriptive_phrases:
        s = re.sub(r"\b" + d + r"\b", " ", s, flags=re.IGNORECASE)

    # Strip voltage spec (leading AND mid-string)
    s = re.sub(r"\b\d{2,4}(?:\s*/\s*\d{2,4})?\s*V\b[\s_/]*", " ", s, flags=re.IGNORECASE)

    # Strip trailing underscore-cable trailer
    s = re.sub(r"_(?:WITHOUT|WITH|NO)[_\s]+CABLE[_A-Z0-9]*", "", s, flags=re.IGNORECASE)

    # Drop pure-spec segments from slash-joined string
    if "/" in s:
        parts = [p.strip() for p in s.split("/")]
        kept = [p for p in parts if not re.fullmatch(r"\s*\d+\s*(?:V|W|MM|MW)\s*", p, re.IGNORECASE)]
        if kept and len(kept) < len(parts):
            s = " ".join(kept).strip()

    # Per-token SKU-shaped junk drop
    def _token_looks_like_sku(tok: str) -> bool:
        tok = tok.strip(",.- ")
        if len(tok) < 6:
            return False
        if not any(c.isdigit() for c in tok):
            return False
        hyphens = tok.count("-")
        digit_ratio = sum(c.isdigit() for c in tok) / len(tok)
        if hyphens >= 2:
            return True
        if digit_ratio >= 0.4 and len(tok) >= 8:
            return True
        return False

    tokens = s.split()
    if len(tokens) >= 3:
        non_sku = [t for t in tokens if not _token_looks_like_sku(t)]
        if non_sku and len(non_sku) >= 2 and len(non_sku) < len(tokens):
            s = " ".join(non_sku)

    s = " ".join(s.split()).strip("- ,")

    junk_tails = (
        r"\bКонтакт\b.*$",
        r"\bАдрес\b.*$",
        r"\bWebsite\b.*$",
        r"\bWarranty\b.*$",
        r"\bContact\b.*$",
        r"\bAddress\b.*$",
        r"\bExtra\s+Description.*$",
        r"\bDescription\s+Text.*$",
    )
    for pat in junk_tails:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)

    for cut in (
        r"\s*\+\d[\d\s\-()]{5,}",
        r"\s*\S+@\S+",
        r"\s*https?://\S+",
        r"\s*www\.\S+",
    ):
        s = re.sub(cut, "", s, flags=re.IGNORECASE)

    s = " ".join(s.split()).strip("- ,")

    tokens = s.split()
    if len(tokens) > 5:
        tokens = tokens[:5]
    s = " ".join(tokens)
    if len(s) > 50:
        s = s[:50].rsplit(" ", 1)[0].strip("- ,")

    return s or None


def normalize_case_size(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if "FULL TOWER" in upper or "BIG TOWER" in upper:
        return "Full Tower"
    if "MINI TOWER" in upper:
        return "Mini Tower"
    if "MID TOWER" in upper or "MIDDLE TOWER" in upper or "MID-TOWER" in upper or "MIDI TOWER" in upper:
        return "Mid Tower"
    if "SMALL FORM FACTOR" in upper or re.search(r"\bSFF\b", upper):
        return "SFF"
    if "CUBE" in upper:
        return "Cube"
    if "HTPC" in upper or "DESKTOP" in upper:
        return "HTPC"
    return None


def normalize_motherboard_form_factors(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        tokens = [str(t) for t in value]
    else:
        s = _clean_str(value)
        if not s:
            return None
        tokens = re.split(r"[,/;]", s)

    canonical: set[str] = set()
    for raw in tokens:
        t = raw.strip().upper()
        if not t:
            continue
        # Normalize whitespace and dashes
        compact = re.sub(r"[\s\-]+", " ", t).strip()
        if compact in ("E ATX", "EATX", "EXTENDED ATX") or t in ("E-ATX", "EATX", "EXTENDED-ATX", "EXTENDED ATX"):
            canonical.add("E-ATX")
        elif compact in ("M ATX", "MATX", "MICRO ATX") or t in ("M-ATX", "MATX", "MICRO-ATX", "MICRO ATX", "ΜATX", "µATX") or "Μ" in t or "µ" in raw.lower():
            canonical.add("Micro ATX")
        elif compact in ("MINI ITX", "MITX", "M ITX") or t in ("MINI-ITX", "MITX", "M-ITX", "MINI ITX"):
            canonical.add("Mini ITX")
        elif compact == "ATX" or t == "ATX":
            canonical.add("ATX")

    if not canonical:
        return None
    return ", ".join(sorted(canonical))


def normalize_included_fans(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 0 <= candidate <= 20 else None
    s = _clean_str(value)
    if not s:
        return None
    # Strip parenthetical breakdowns so outer total wins over sum of inner parts
    outer = re.sub(r"\(.*?\)", "", s).strip()
    # Bare integer
    m = re.match(r"^\s*(\d{1,2})\s*$", outer)
    if m:
        candidate = int(m.group(1))
        return candidate if 0 <= candidate <= 20 else None
    # Free-form: sum every leading integer in `\bN\s*x\s*\d` patterns
    matches = re.findall(r"\b(\d+)\s*[xXхХ]\s*\d", outer)
    if matches:
        total = sum(int(m) for m in matches)
        return total if 0 <= total <= 20 else None
    return None


def normalize_max_mm(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 50 <= candidate <= 600 else None
    s = _clean_str(value)
    if not s:
        return None
    candidates: list[int] = []
    for m in re.finditer(r"(?:до\s*)?(\d{2,4})\s*(?:mm|мм|millimeter)", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    if not candidates:
        # Fallback: bare integer
        m = re.match(r"^\s*(\d{2,4})\s*$", s)
        if m:
            candidates.append(int(m.group(1)))
    if not candidates:
        return None
    largest = max(candidates)
    return largest if 50 <= largest <= 600 else None


def normalize_max_radiator_mm(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 120 <= candidate <= 480 else None
    s = _clean_str(value)
    if not s:
        return None
    matches = re.findall(r"\b(120|140|240|280|360|420|480)\b", s)
    if not matches:
        return None
    largest = max(int(m) for m in matches)
    return largest if 120 <= largest <= 480 else None


_USB_VERSION_PATTERN = re.compile(
    r"^\s*(\d+)(?:\.(\d+))?(\s*\(?\s*Gen\s*\d+(?:x\d+)?\s*\)?)?\s*$",
    flags=re.IGNORECASE,
)


def _valid_usb_version(value) -> Optional[str]:
    if value is None:
        return None
    s = " ".join(str(value).split())
    if not s:
        return None
    m = _USB_VERSION_PATTERN.match(s)
    if not m:
        return None
    major = int(m.group(1))
    if major < 2:
        return None
    return s


def _apply_type_c_version_default(port: dict) -> dict:
    if port.get("type") == "Type-C" and port.get("version") is None:
        return {**port, "version": "3.2"}
    return port


def _dedup_usb_ports(ports: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, Optional[str]], dict] = {}
    for port in ports:
        ptype = port.get("type") or "Type-A"
        version_raw = port.get("version")
        version_key = " ".join(str(version_raw).split()).lower() if version_raw else None
        key = (ptype, version_key)
        existing = deduped.get(key)
        if existing is None or int(port.get("count") or 0) > int(existing.get("count") or 0):
            deduped[key] = port

    collapsed = list(deduped.values())
    types_with_concrete_version = {
        (p.get("type") or "Type-A")
        for p in collapsed
        if p.get("version") is not None
    }
    return [
        p for p in collapsed
        if p.get("version") is not None
        or (p.get("type") or "Type-A") not in types_with_concrete_version
    ]


def _normalize_io_dict(d: dict, apply_type_c_default: bool = True) -> Optional[dict]:
    usb_ports_raw = d.get("usb_ports") or []
    audio = d.get("audio")
    cleaned_ports = []
    if isinstance(usb_ports_raw, list):
        for port in usb_ports_raw:
            if not isinstance(port, dict):
                continue
            count_raw = port.get("count")
            try:
                count = int(count_raw) if count_raw is not None else 0
            except (TypeError, ValueError):
                count = 0
            if count <= 0:
                continue
            ptype = port.get("type")
            if ptype:
                pt_upper = str(ptype).upper().replace(" ", "").replace("-", "")
                if "C" in pt_upper and "TYPEC" in pt_upper or pt_upper == "TYPEC" or pt_upper == "C":
                    ptype = "Type-C"
                elif "TYPEA" in pt_upper or pt_upper == "A":
                    ptype = "Type-A"
                else:
                    ptype = "Type-A"
            else:
                ptype = "Type-A"
            version = port.get("version")
            if version is not None:
                version = re.sub(r"[()]", "", str(version))
                version = " ".join(version.split()) or None
            version = _valid_usb_version(version)
            cleaned_ports.append({"count": count, "type": ptype, "version": version})

    cleaned_ports = _dedup_usb_ports(cleaned_ports)
    if apply_type_c_default:
        cleaned_ports = [_apply_type_c_version_default(p) for p in cleaned_ports]

    if audio is not None and not isinstance(audio, bool):
        audio = bool(audio)

    if not cleaned_ports and audio is None:
        return None
    return {"usb_ports": cleaned_ports, "audio": audio}


_STANDALONE_TYPE_PATTERN = re.compile(
    r"(?P<count>\d+)\s*x?\s*(?:USB[-\s]?)?Type[-\s]?(?P<type>[CA])\b",
    flags=re.IGNORECASE,
)


_USB_PATTERN = re.compile(
    r"(?P<count>\d+)?\s*x?\s*USB"
    r"(?:[-\s]?(?P<type1>Type[-\s]?[CA]|[CA]\b))?"
    r"\s*(?P<version>[\d.]+(?:\s*\(?\s*Gen\s*\d+(?:x\d+)?\s*\)?)?)?"
    r"(?:\s*[-]?\s*(?P<type2>Type[-\s]?[CA]|[CA]\b))?",
    flags=re.IGNORECASE,
)


def normalize_io_json(value, apply_type_c_default: bool = True) -> Optional[dict]:
    if value is None:
        return None
    if isinstance(value, dict):
        return _normalize_io_dict(value, apply_type_c_default=apply_type_c_default)
    s = _clean_str(value)
    if not s:
        return None

    upper = s.upper()
    audio = None
    if re.search(r"HD\s*AUDIO", upper) or "АУДИО" in upper or re.search(r"\bAUDIO\b", upper) or re.search(r"3\.5\s*MM", upper) or "JACK" in upper:
        audio = True

    usb_ports: list[dict] = []
    raw_for_tokens = str(value)
    tokens = re.split(r"[,;\n]", raw_for_tokens)
    for token in tokens:
        t = " ".join(token.split()).strip()
        if not t:
            continue
        usb_spans: list[tuple[int, int]] = []
        if "USB" in t.upper():
            for m in _USB_PATTERN.finditer(t):
                if m.start() == m.end():
                    continue
                matched_text = m.group(0)
                if "USB" not in matched_text.upper():
                    continue
                count_raw = m.group("count")
                type_raw = m.group("type1") or m.group("type2")
                version_raw = m.group("version")
                try:
                    count = int(count_raw) if count_raw else 1
                except ValueError:
                    count = 1
                if type_raw:
                    tr = type_raw.upper().replace(" ", "").replace("-", "")
                    if tr in ("TYPEC", "C"):
                        ptype = "Type-C"
                    else:
                        ptype = "Type-A"
                else:
                    ms_up = matched_text.upper()
                    if re.search(r"TYPE[-\s]?C\b", ms_up) or re.search(r"USB[-\s]?C\b", ms_up):
                        ptype = "Type-C"
                    else:
                        ptype = "Type-A"
                version = None
                if version_raw:
                    version = re.sub(r"[()]", "", version_raw)
                    version = " ".join(version.split()) or None
                version = _valid_usb_version(version)
                usb_ports.append({"count": count, "type": ptype, "version": version})
                usb_spans.append((m.start(), m.end()))
        for m in _STANDALONE_TYPE_PATTERN.finditer(t):
            if any(start <= m.start() < end for start, end in usb_spans):
                continue
            count_raw = m.group("count")
            try:
                count = int(count_raw) if count_raw else 1
            except ValueError:
                count = 1
            tr = m.group("type").upper()
            ptype = "Type-C" if tr == "C" else "Type-A"
            usb_ports.append({"count": count, "type": ptype, "version": None})

    usb_ports = _dedup_usb_ports(usb_ports)
    if apply_type_c_default:
        usb_ports = [_apply_type_c_version_default(p) for p in usb_ports]

    if not usb_ports and audio is None:
        return None
    return {"usb_ports": usb_ports, "audio": audio}
