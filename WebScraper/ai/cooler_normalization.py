import re
from typing import Optional

from ai.cooler_brands import COOLER_BRAND_MAP as _COOLER_BRAND_MAP


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


def normalize_cooler_brand(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()

    matches = []
    for token, normalized in _COOLER_BRAND_MAP.items():
        pattern = r"\b" + re.escape(token) + r"\b"
        match = re.search(pattern, upper)
        if match:
            matches.append((match.start(), normalized))

    if not matches:
        # Fallback to substring match if word boundaries failed
        for token, normalized in _COOLER_BRAND_MAP.items():
            if token in upper:
                matches.append((upper.find(token), normalized))

    if not matches:
        return None

    matches.sort()
    return matches[0][1]


def normalize_cooler_model(value: str | None, brand: str | None = None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None

    # Strip Cyrillic "Охладител за процесор" / "за процесор" anywhere,
    # then "Водно охлаждане" / "Охладител" prefix.
    s = re.sub(r"(?i)\bохладител\s+за\s+процесор\b", " ", s)
    s = re.sub(r"(?i)\bза\s+процесор\b", " ", s)
    s = re.sub(r"(?i)^\s*водно\s+охлаждане\s*", "", s)
    s = re.sub(r"(?i)^\s*охладител\s*", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    # Strip parenthesized text
    s = re.sub(r"\(.*?\)", "", s)

    if brand:
        s = re.sub(re.escape(brand), "", s, flags=re.IGNORECASE).strip()

    # Strip descriptors that pollute model names
    descriptors = [
        r"WATER\s+COOLING",
        r"AIR\s+COOLER",
        r"CPU\s+COOLER",
        r"ARGB",
        r"RGB",
        r"AIO",
        r"TOWER",
        r"LIQUID",
        r"FAN",
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

    # Strip leading stray punctuation: ", - " / "- " / ", "
    s = re.sub(r"^[\s,\-]+", "", s)

    # Strip truncation ellipsis ("PC Case... CGR-5GC9W", "NVIDIA Limite… R-…")
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

    # Strip underscore-cable trailer
    s = re.sub(r"_(?:WITHOUT|WITH|NO)[_\s]+CABLE[_A-Z0-9]*", "", s, flags=re.IGNORECASE)

    # Drop pure-spec segments from a slash-joined string
    if "/" in s:
        parts = [p.strip() for p in s.split("/")]
        kept = [p for p in parts if not re.fullmatch(r"\s*\d+\s*(?:V|W|MM|MW)\s*", p, re.IGNORECASE)]
        if kept and len(kept) < len(parts):
            s = " ".join(kept).strip()

    # Per-token SKU-shaped junk drop (only when >=3 tokens and >=2 non-SKU siblings remain)
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

    # --- Round 6: cooler-specific junk patterns ---

    # Reject any value containing underscores (Bulgarian retailer mangling)
    if "_" in s:
        return None

    # Strip trailing packaging suffix: /Bulk, /Retail, /OEM, /Tray, /Box
    s = re.sub(r"\s*/\s*(?:Bulk|Retail|OEM|Tray|Box)\b.*$", "", s, flags=re.IGNORECASE)

    # Strip socket-list segments (LGA\d+ / AM\d+ combinations, Intel/AMD platform tags)
    _SOCKET_ATOM = r"(?:LGA\s*\d{3,4}(?:-\d)?|AM[0-9](?:\+)?|FM[12](?:\+)?|TR[45]|sTRX?\d|SP[356]|Intel|AMD)"
    s = re.sub(rf"^\s*{_SOCKET_ATOM}(?:\s*/\s*{_SOCKET_ATOM})*\s*[-,]?\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(rf"\s*{_SOCKET_ATOM}(?:\s*/\s*{_SOCKET_ATOM})+\s*$", "", s, flags=re.IGNORECASE).strip()

    # Strip trailing .XX.YY color/variant codes (e.g. NH-D15.G2.CH.BK -> NH-D15.G2)
    _COLOR_DOT_CODES = r"(?:CH|BK|WH|BL|RD|GR|SL|BG|CHROMAX)"
    while True:
        new_s = re.sub(rf"\.{_COLOR_DOT_CODES}\s*$", "", s, flags=re.IGNORECASE)
        if new_s == s:
            break
        s = new_s.strip(" .-,")

    # Convert surviving dots between word chars to spaces — NH-D15.G2 -> NH-D15 G2
    s = re.sub(r"(?<=\w)\.(?=\w)", " ", s)

    s = " ".join(s.split()).strip("- ,/")

    # If empty after socket/packaging strips, reject → name-fallback wins
    if not s:
        return None
    # Single-token hyphen-chain SKU (e.g. remainder after socket strip) → reject
    tokens_final = s.split()
    if len(tokens_final) == 1:
        tok = tokens_final[0]
        if tok.count("-") >= 2 and any(c.isdigit() for c in tok):
            return None

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


_CANONICAL_COOLER_TYPES = {"Air", "AIO"}


def normalize_cooler_type(value) -> Optional[str]:
    if value is None:
        return None
    s = _clean_str(value)
    if not s:
        return None

    # Accept already-canonical input
    for canonical in _CANONICAL_COOLER_TYPES:
        if s.strip().lower() == canonical.lower():
            return canonical
    # Legacy "Custom loop" input folds into AIO per new taxonomy
    if s.strip().lower() == "custom loop":
        return "AIO"

    upper = s.upper()

    # AIO tokens — any water/liquid cooler (sealed AIO, open-loop blocks, waterblocks, CPU blocks)
    aio_tokens = (
        "AIO", "ALL-IN-ONE", "ALL IN ONE",
        "LIQUID", "WATER COOLING", "WATERBLOCK", "WATER BLOCK",
        "OPEN LOOP", "CUSTOM LOOP", "CPU BLOCK",
        "ВОДНО ОХЛАЖДАНЕ", "ВОДНО", "ВОДЕН",
    )
    for tok in aio_tokens:
        if tok in upper:
            return "AIO"

    # Radiator size co-located with РАДИАТОР/RADIATOR (within 15 chars)
    for rad_match in re.finditer(r"(?:РАДИАТОР|RADIATOR)", upper):
        start = max(0, rad_match.start() - 15)
        end = min(len(upper), rad_match.end() + 15)
        window = upper[start:end]
        if re.search(r"\b(240|280|360|420)\b", window):
            return "AIO"

    # Air fallback tokens
    air_tokens = ("HEATPIPE", "TOWER", "HEATSINK", "AIR COOLER", "ВЪЗДУШНО", "ВЪЗДУШЕН")
    for tok in air_tokens:
        if tok in upper:
            return "Air"

    return None


_VALID_SOCKETS = [
    "LGA1700", "LGA1851", "LGA1200", "LGA1150", "LGA1151", "LGA1155", "LGA1156",
    "LGA2011-3", "LGA2011", "LGA2066", "LGA1366", "LGA775", "LGA3647", "LGA4189", "LGA4677",
    "AM5", "AM4", "AM3+", "AM3", "AM2",
    "FM2+", "FM2", "FM1",
    "TR4", "sTRX4", "sTR5",
    "SP3", "SP5", "SP6",
]


def _canonicalize_socket_token(token: str) -> Optional[str]:
    t = token.strip()
    if not t:
        return None
    # Normalize whitespace around hyphens
    t_compact = re.sub(r"\s*-\s*", "-", t)
    t_upper = t_compact.upper()
    for canonical in _VALID_SOCKETS:
        if t_upper == canonical.upper():
            return canonical
    return None


def normalize_cooler_sockets(value) -> Optional[str]:
    if value is None:
        return None
    
    seen: list[str] = []
    
    # Unified approach: convert everything to string and extract all valid tokens
    text_to_scan = ""
    if isinstance(value, list):
        text_to_scan = " ".join(str(t) for t in value)
    else:
        text_to_scan = str(value)
    
    if not text_to_scan.strip():
        return None
        
    upper = text_to_scan.upper()
    # Build regex across all sockets, longest first to avoid partial matches (e.g. LGA2011 vs LGA2011-3)
    for canonical in sorted(_VALID_SOCKETS, key=lambda k: -len(k)):
        pat = re.escape(canonical.upper()).replace(r"\-", r"\s*-\s*")
        # Match standalone token
        if re.search(r"(?<![A-Z0-9])" + pat + r"(?![A-Z0-9])", upper):
            if canonical not in seen:
                seen.append(canonical)

    if not seen:
        return None
    
    # Return in fixed order for consistency
    ordered = [s for s in _VALID_SOCKETS if s in seen]
    return ", ".join(ordered) if ordered else ", ".join(seen)


def normalize_cooler_height_mm(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 30 <= candidate <= 300 else None
    s = _clean_str(value)
    if not s:
        return None
    s = s.replace(",", ".")
    candidates: list[int] = []
    for m in re.finditer(r"(?:до\s*)?(\d{2,4})(?:\.\d+)?\s*(?:mm|мм|millimeter)", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    if not candidates:
        m = re.match(r"^\s*(\d{2,4})(?:\.\d+)?\s*$", s)
        if m:
            candidates.append(int(m.group(1)))
    if not candidates:
        return None
    largest = max(candidates)
    return largest if 30 <= largest <= 300 else None


def normalize_cooler_tdp_w(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 30 <= candidate <= 500 else None
    s = _clean_str(value)
    if not s:
        return None
    s = s.replace(",", ".")
    candidates: list[int] = []
    # "до NNN W"
    for m in re.finditer(r"до\s*(\d{2,4})(?:\.\d+)?\s*W\b", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    # "NNN W"
    for m in re.finditer(r"(\d{2,4})(?:\.\d+)?\s*W\b", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    # "TDP NNN"
    for m in re.finditer(r"TDP[^\d]{0,6}(\d{2,4})", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    # "капацитет NNN"
    for m in re.finditer(r"капацитет[^\d]{0,6}(\d{2,4})", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    # "мощност NNN"
    for m in re.finditer(r"мощност[^\d]{0,6}(\d{2,4})", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))

    if not candidates:
        m = re.match(r"^\s*(\d{2,4})(?:\.\d+)?\s*$", s)
        if m:
            candidates.append(int(m.group(1)))
    if not candidates:
        return None
    # Filter to valid range, then take largest
    in_range = [c for c in candidates if 30 <= c <= 500]
    if not in_range:
        return None
    return max(in_range)


_VALID_FAN_SIZES = {40, 60, 70, 80, 92, 120, 140, 200}


def normalize_cooler_fan_size_mm(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if candidate in _VALID_FAN_SIZES else None
    s = _clean_str(value)
    if not s:
        return None
    s = s.replace(",", ".")
    candidates: list[int] = []
    for m in re.finditer(r"(\d{2,3})\s*(?:mm|мм)", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    for m in re.finditer(r"(\d{2,3})\s*x\b", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    if not candidates:
        m = re.match(r"^\s*(\d{2,3})\s*$", s)
        if m:
            candidates.append(int(m.group(1)))
    valid = [c for c in candidates if c in _VALID_FAN_SIZES]
    if not valid:
        return None
    return max(valid)


def normalize_cooler_fan_count(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 1 <= candidate <= 6 else None
    s = _clean_str(value)
    if not s:
        return None
    s = s.replace(",", ".")
    # Strip parenthetical breakdowns
    outer = re.sub(r"\(.*?\)", "", s).strip()
    # Bare integer
    m = re.match(r"^\s*(\d{1,2})\s*$", outer)
    if m:
        candidate = int(m.group(1))
        return candidate if 1 <= candidate <= 6 else None
    # "N бр"
    m = re.search(r"\b(\d{1,2})\s*бр\b", outer, flags=re.IGNORECASE)
    if m:
        candidate = int(m.group(1))
        return candidate if 1 <= candidate <= 6 else None
    # "N fans"
    m = re.search(r"\b(\d{1,2})\s*fans?\b", outer, flags=re.IGNORECASE)
    if m:
        candidate = int(m.group(1))
        return candidate if 1 <= candidate <= 6 else None
    # `\bN\s*x\s*\d` patterns (sum)
    matches = re.findall(r"\b(\d+)\s*[xXхХ]\s*\d", outer)
    if matches:
        total = sum(int(m) for m in matches)
        return total if 1 <= total <= 6 else None
    # Bare "Nx" like "2x"
    matches2 = re.findall(r"\b(\d+)\s*[xXхХ]\b", outer)
    if matches2:
        total = sum(int(m) for m in matches2)
        return total if 1 <= total <= 6 else None
    return None


def normalize_cooler_noise_db(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if 0 <= candidate <= 70:
            return round(candidate, 1)
        return None
    s = _clean_str(value)
    if not s:
        return None
    # Strip leading "<" / "до" and trailing "MAX" / "макс"
    cleaned = re.sub(r"^\s*(?:<|до)\s*", "", s, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*(?:MAX|макс)\.?\s*$", "", cleaned, flags=re.IGNORECASE)
    candidates: list[float] = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*d[Bb][Aa]?", cleaned):
        candidates.append(float(m.group(1).replace(",", ".")))
    if not candidates:
        m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*$", cleaned)
        if m:
            candidates.append(float(m.group(1).replace(",", ".")))
    if not candidates:
        return None
    valid = [c for c in candidates if 0 <= c <= 70]
    if not valid:
        return None
    return round(max(valid), 1)


def normalize_cooler_rpm_max(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 200 <= candidate <= 5000 else None
    s = _clean_str(value)
    if not s:
        return None
    # Strip parenthesized annotations ("(PWM)", "(MAX)", etc.) before any parsing
    s = re.sub(r"\([^)]*\)", " ", s)
    # Preserve comma-thousands: "2,400" -> "2400" (only when exactly 3 digits follow)
    s = re.sub(r"(\d),(\d{3})(?!\d)", r"\1\2", s)
    # Normalize tilde variants to hyphen — `~`/`∼`/`～` are RANGE separators, not tolerance
    s = re.sub(r"[~\u223C\uFF5E]", "-", s)
    # Strip tolerance markers: "± N(%)" and "+ N(%)" (range now always uses "-")
    s = re.sub(r"±\s*\d+(?:[.,]\d+)?\s*%?", " ", s)
    s = re.sub(r"\+\s*\d+(?:[.,]\d+)?\s*%?", " ", s)
    # Remaining commas are decimal separators
    s = s.replace(",", ".")
    # Strip trailing "MAX" / "макс" so single-value ranges like "1500 RPM MAX" parse
    s = re.sub(r"\s*(?:MAX|макс)\.?\s*$", "", s, flags=re.IGNORECASE)
    candidates: list[int] = []
    _RPM_UNIT = r"(?:RPM|об\s*/?\s*мин)"
    # Ranges: "AAA-BBBB RPM" / "AAA-BBBB об/мин" (take max); allow up to 20 non-digit chars between range end and unit
    for m in re.finditer(rf"(\d{{2,4}})\s*[-–]\s*(\d{{2,5}})(?:\D{{0,20}}?){_RPM_UNIT}", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(2)))
    # "до NNNN RPM" / "до NNNN об/мин"
    for m in re.finditer(rf"до\s*(\d{{2,5}})\s*{_RPM_UNIT}", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    # Standalone "NNNN RPM" / "NNNN об/мин"
    for m in re.finditer(rf"(\d{{2,5}})\s*{_RPM_UNIT}", s, flags=re.IGNORECASE):
        candidates.append(int(m.group(1)))
    if not candidates:
        m = re.match(r"^\s*(\d{2,5})\s*$", s)
        if m:
            candidates.append(int(m.group(1)))
    if not candidates:
        return None
    valid = [c for c in candidates if 200 <= c <= 5000]
    if not valid:
        return None
    return max(valid)
