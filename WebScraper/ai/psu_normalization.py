import re
from typing import Optional

from ai.psu_brands import PSU_BRAND_MAP as _PSU_BRAND_MAP

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

def normalize_psu_brand(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    
    # Strategy: Find all matching brands and their positions
    matches = []
    for token, normalized in _PSU_BRAND_MAP.items():
        # Use word boundaries to prevent partial matches like "AS" in "ASUS" or substring issues
        # and to be more accurate.
        pattern = r"\b" + re.escape(token) + r"\b"
        match = re.search(pattern, upper)
        if match:
            matches.append((match.start(), normalized))
    
    if not matches:
        return None
    
    # Sort by position and return the first one found in the string
    # This helps when multiple brands are mentioned (e.g., "1stPlayer ... ASUS compatible")
    matches.sort()
    return matches[0][1]

def normalize_psu_model(value: str | None, brand: str | None = None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None

    # Remove product codes like BN326, CP-9020300, PS-SPR-0500NHSAWE-1, ZPU-500S
    # We want to be careful not to remove things like "GX-750" or "SF750" which are part of the model.
    # be quiet! product codes often start with BN
    s = re.sub(r"\bBN[0-9]{3,}\b", "", s)
    # General product codes often have more digits if they are just a letter prefix
    s = re.sub(r"\b[A-Z]{1,2}[0-9]{4,}\b", "", s)
    # Targeted hyphenated product codes (avoid destroying real models like TR-KG850-W,
    # TUF-GAMING-750G, ROG-STRIX-850G, ADK-A600W, UD-850GPLUS)
    s = re.sub(r"\bCP-\d{5,}\b", "", s)                             # Corsair: CP-9020300
    s = re.sub(r"\bPS-[A-Z]{2,4}-[A-Z0-9]{8,}(?:-\d+)?\b", "", s)  # Thermaltake: PS-SPR-0500NHSAWE-1
    # Specific 1stPlayer product code pattern
    s = re.sub(r"\bZPU-[0-9]{3}[A-Z]\b", "", s) # ZPU-500S

    # Handle comma-separated lists - often a title or long spec string
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        # Prefer parts that don't contain common noise
        noise_tokens = ["WATT", "PCIE", "CYBENETICS", "CERTIFIED", "PSU", "POWER SUPPLY", "ЗАХРАНВАНЕ", "2025", "SERIES"]
        best_part = None
        for p in parts:
            p_upper = p.upper()
            if not any(token in p_upper for token in noise_tokens):
                best_part = p
                break
        if not best_part and parts:
            # Fallback: pick the first non-empty part that isn't just a number/wattage
            for p in parts:
                if not re.match(r"^\d+\s*W?$", p, re.IGNORECASE):
                    best_part = p
                    break
        if best_part:
            s = best_part

    if brand:
        # Avoid literal regex issues with special characters in brand name (e.g. be quiet!)
        s = re.sub(re.escape(brand), "", s, flags=re.IGNORECASE).strip()

    s = re.sub(r"(?i)^(?:PSU|POWER\s+SUPPLY(?:\s+(?:AC|DC))?|ЗАХРАНВАНЕ)\s*", "", s).strip()
    s = re.sub(r"\b\d{3,4}\s*(?:W(?:ATT)?|ВАТТ?)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b80\s*(?:\+|PLUS)\s*(?:STANDARD|WHITE|BRONZE|SILVER|GOLD|PLATINUM|TITANIUM)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:ATX\s*3\.1|ATX\s*3\.0|ATX12V\s*2\.\d+|ATX|SFX-L|SFX|TFX|FLEX\s*ATX|ITX)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:FULLY\s+MODULAR|FULL\s+MODULAR|SEMI[-\s]?MODULAR|NON[-\s]?MODULAR|MODULAR|FIXED\s+CABLES?)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:12VHPWR|12V-2X6)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:CYBENETICS|GOLD|SILVER|BRONZE|PLATINUM|TITANIUM)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:CERTIFIED|SERIES|SHIFTED|2025)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\(.*?\)", "", s).strip()
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

    tokens = s.split()
    if len(tokens) > 5:
        tokens = tokens[:5]
    s = " ".join(tokens)
    if len(s) > 50:
        s = s[:50].rsplit(" ", 1)[0].strip("- ,")

    return s or None


def normalize_psu_physical_size(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper().replace("_", " ")
    if "SFX-L" in upper or "SFXL" in upper:
        return "SFX-L"
    if "FLEX" in upper and "ATX" in upper:
        return "Flex ATX"
    if re.search(r"\bSFX\b", upper):
        return "SFX"
    if re.search(r"\bTFX\b", upper):
        return "TFX"
    if re.search(r"\bITX\b", upper):
        return "ITX"
    if re.search(r"\bATX\b", upper) and not re.search(r"\bATX12V\s*\d(?:\.\d+)?\b", upper):
        return "ATX"
    return None


def normalize_psu_power_w(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 100 <= candidate <= 3000 else None
    s = _clean_str(value)
    if not s:
        return None
    m = re.search(r"\b(\d{3,4})\s*(?:W(?:ATT)?|ВАТТ?)\b", s, flags=re.IGNORECASE)
    if m:
        candidate = int(m.group(1))
        return candidate if 100 <= candidate <= 3000 else None
    # Bare number fallback for short spec values (e.g. "850" from a "Мощност" row)
    if len(s) < 15:
        m = re.match(r"^(\d{3,4})$", s.strip())
        if m:
            candidate = int(m.group(1))
            return candidate if 100 <= candidate <= 3000 else None
    return None


def normalize_psu_efficiency(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    m = re.search(r"(?:UP TO|ДО|MAX|МАКС)\s*(\d{2,3}(?:[\.,]\d+)?)\s*%", upper)
    if m:
        return f"{m.group(1).replace(',', '.')}%"
    m = re.search(r"[<>]=?\s*(\d{2,3}(?:[\.,]\d+)?)\s*%", upper)
    if m:
        return f"{m.group(1).replace(',', '.')}%"
    m = re.search(r"\b(\d{2,3}(?:[\.,]\d+)?)\s*%", upper)
    if m:
        return f"{m.group(1).replace(',', '.')}%"
    return None

def normalize_psu_certificate(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if "CYBENETICS" in upper:
        for tier in ("DIAMOND", "PLATINUM", "GOLD", "SILVER", "BRONZE"):
            if tier in upper:
                return f"Cybenetics {tier.title()}"
        return "Cybenetics"
    if re.search(r"80\s*(?:\+|PLUS)", upper):
        if "TITANIUM" in upper:
            return "80 Plus Titanium"
        if "PLATINUM" in upper:
            return "80 Plus Platinum"
        if "GOLD" in upper:
            return "80 Plus Gold"
        if "SILVER" in upper:
            return "80 Plus Silver"
        if "BRONZE" in upper:
            return "80 Plus Bronze"
        if "WHITE" in upper:
            return "80 Plus White"
        return "80 Plus Standard"
    return None

def normalize_psu_modularity(value: str | None) -> Optional[str]:
    s = _clean_str(value)
    if not s:
        return None
    upper = s.upper()
    if re.search(r"\b(ДА|YES)\b", upper):
        return "Modular"
    if re.search(r"\b(НЕ|NO)\b", upper):
        return "Not modular"
    if "SEMI" in upper and "MODULAR" in upper:
        return "Semi-modular"
    if any(token in upper for token in ("NOT MODULAR", "NON MODULAR", "NON-MODULAR", "FIXED CABLE", "FIXED-CABLE")):
        return "Not modular"
    if "MODULAR CABLE" in upper or "FULLY MODULAR" in upper or "FULL MODULAR" in upper:
        return "Modular"
    if "MODULAR" in upper:
        return "Modular"
    return None

def normalize_psu_fan_size_mm(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        candidate = int(value)
        return candidate if 40 <= candidate <= 200 else None
    s = _clean_str(value)
    if not s:
        return None
    m = re.search(r"\b(\d{2,3})\s*(?:MM|ММ)\b", s, flags=re.IGNORECASE)
    if m:
        candidate = int(m.group(1))
        return candidate if 40 <= candidate <= 200 else None
    return None
