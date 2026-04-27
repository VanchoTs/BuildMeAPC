from bs4 import BeautifulSoup
from typing import Optional, Tuple
import re

BGN_PER_EUR = 1.95583


def _first_text(soup, selectors) -> Optional[str]:
    """
    Returns the stripped text of the first element matching any of the given CSS selectors.
    
    Args:
        soup: BeautifulSoup object of the page.
        selectors: List of CSS selector strings to try.
        
    Returns:
        Stripped text if found, otherwise None.
    """
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.text and el.text.strip():
            return el.text.strip()
    return None


def _parse_price_el(el) -> Optional[float]:
    """
    Parses a price element from the HTML, handling various currency formats and fraction (sup) tags.
    
    Args:
        el: BeautifulSoup element containing price information.
        
    Returns:
        The parsed price as a float, or None if parsing fails.
    """
    if el is None:
        return None
    # import re

    sup = el.find("sup")
    sup_digits = None
    if sup:
        sup_digits = re.sub(r"[^\d]", "", sup.get_text())
        if not sup_digits:
            sup_digits = None

    text = el.get_text(" ", strip=True)
    cleaned = re.sub(r"[^\d,\.]", "", text)

    if sup_digits:
        if cleaned.endswith(sup_digits):
            main = cleaned[: -len(sup_digits)]
        else:
            main = cleaned
        main = main.replace(",", ".").strip(".")
        main_digits = re.sub(r"[^\d]", "", main)
        if not main_digits:
            return None
        euros = int(main_digits)
        cents = int(sup_digits[:2].ljust(2, "0"))
        return float(f"{euros}.{cents:02d}")

    m = re.search(r"[0-9]+(?:[\.,][0-9]+)?", cleaned)
    if m:
        return float(m.group(0).replace(",", "."))
    return None


def _extract_prices(soup: BeautifulSoup) -> Tuple[Optional[float], Optional[float]]:
    """
    Extracts both EUR and BGN prices from the page using common CSS selectors.
    
    Args:
        soup: BeautifulSoup object of the page.
        
    Returns:
        A tuple of (price_eur, price_bgn).
    """
    price_eur_el = soup.select_one(".price-euro, .price-eur, .product-price-euro")
    price_bgn_el = soup.select_one(
        ".price-current, .price, .product-price, .price-value"
    )

    price_eur = _parse_price_el(price_eur_el)
    price_bgn = _parse_price_el(price_bgn_el)

    if price_eur is None and price_bgn is not None:
        price_eur = price_bgn / BGN_PER_EUR

    return price_eur, price_bgn


def _collect_specs(soup: BeautifulSoup) -> dict:
    """
    Scrapes technical specifications from tables, definition lists, and list items.
    
    Args:
        soup: BeautifulSoup object of the page.
        
    Returns:
        A dictionary containing technical specification keys and values.
    """
    specs: dict[str, str] = {}

    def _add(k: str, v: str):
        if not k or not v:
            return
        k = " ".join(k.split()).strip()
        v = " ".join(v.split()).strip()
        if not k or not v:
            return
        if k not in specs:
            specs[k] = v

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) >= 2:
                _add(cells[0], cells[1])

    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                _add(dt.get_text(" ", strip=True), dd.get_text(" ", strip=True))

    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        if ":" in text:
            k, v = text.split(":", 1)
            _add(k, v)

    return specs


def _parse_brand_model(title: str):
    """
    Extracts GPU brand (NVIDIA/AMD/Intel), model (e.g., RTX 4070), 
    PCB manufacturer (e.g., ASUS), and series (e.g., ROG Strix) from the title.
    
    Uses a series of regex patterns to identify common GPU naming conventions.
    
    Args:
        title: The product name string.
        
    Returns:
        A tuple of (chip_brand, model, pcb_manufacturer, pcb_series).
    """
    # import re

    if not title:
        return None, None, None

    s = title
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"[™®]", "", s)
    s = re.sub(r"(?i)видеокарта|video card|gpu|graphics card", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[,\n\r]", " ", s).strip()
    s = " ".join(s.split())

    chip_brand = None
    m = re.search(r"\b(NVIDIA|AMD|INTEL)\b", s, flags=re.IGNORECASE)
    if m:
        chip_brand = m.group(1).upper()

    vendors = [
        "ASUS",
        "MSI",
        "GIGABYTE",
        "ASROCK",
        "PALIT",
        "ZOTAC",
        "PNY",
        "SAPPHIRE",
        "POWERCOLOR",
        "XFX",
        "INNO3D",
        "GAINWARD",
        "EVGA",
        "GALAX",
        "KFA2",
        "COLORFUL",
        "AORUS",
        "ACER",
        "LENOVO",
        "HP",
        "DELL",
    ]
    pcb_manufacturer = None
    upper = s.upper()
    for v in vendors:
        if v in upper:
            pcb_manufacturer = v.title() if v not in ("MSI", "ASUS", "XFX") else v
            break

    model = None
    m = re.search(
        r"(RTX|GTX|GT)\s*\d{3,4}(?:\s*(?:TI|SUPER))?",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        token = m.group(0).upper().replace("  ", " ").strip()
        model = f"GeForce {token}"
    if model is None:
        m = re.search(
            r"(Radeon\s+RX\s+\d{3,4}(?:\s*(?:XT|XTX|GRE|M))?)",
            s,
            flags=re.IGNORECASE,
        )
        if m:
            token = m.group(1)
            token = token.replace("RADEON", "Radeon").replace("RX", "RX")
            model = token
            chip_brand = chip_brand or "AMD"
    if model is None:
        m = re.search(
            r"\bRX\s*\d{3,4}(?:\s*(?:XT|XTX|GRE|M))?\b", s, flags=re.IGNORECASE
        )
        if m:
            token = m.group(0)
            token = re.sub(r"\s+", " ", token.upper())
            model = f"Radeon {token.replace('RX', 'RX')}"
            chip_brand = chip_brand or "AMD"
    if model is None:
        m = re.search(r"\bR\s*\d{3,4}\b", s, flags=re.IGNORECASE)
        if m:
            token = re.sub(r"\s+", "", m.group(0)).upper()
            model = f"Radeon RX {token.lstrip('R')}"
            chip_brand = chip_brand or "AMD"
    if model is None:
        m = re.search(r"(Arc\s+[A-Z]\d{3,4})", s, flags=re.IGNORECASE)
        if m:
            token = m.group(1)
            model = token.replace("ARC", "Arc")
            chip_brand = chip_brand or "Intel"
    if model is None:
        m = re.search(r"\bT\s*400\b", s, flags=re.IGNORECASE)
        if m:
            model = "T400"
            chip_brand = chip_brand or "NVIDIA"
    if model is None:
        m = re.search(r"\bN\s*\d{4}\b", s, flags=re.IGNORECASE)
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            if digits:
                model = f"GeForce RTX {digits}"
                chip_brand = chip_brand or "NVIDIA"

    pcb_series = None
    if model:
        cleaned = s
        if pcb_manufacturer:
            cleaned = re.sub(
                rf"\b{re.escape(pcb_manufacturer)}\b", "", cleaned, flags=re.IGNORECASE
            )
        if model:
            cleaned = re.sub(re.escape(model), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b\d+\s*GB\b|\bGDDR\dX?\b|\bPCI-?E\s*[\d\.]+\s*x\d+\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split())
        if cleaned:
            pcb_series = cleaned.strip()

    if chip_brand == "NVIDIA":
        chip_brand = "NVIDIA"
    elif chip_brand == "AMD":
        chip_brand = "AMD"
    elif chip_brand == "INTEL":
        chip_brand = "Intel"

    return chip_brand, model, pcb_manufacturer, pcb_series


def _normalize_vendor_token(token: str) -> str:
    """
    Normalizes a vendor token to its canonical capitalization.
    """
    upper = token.upper()
    if upper == "ASROCK":
        return "ASRock"
    if upper in ("MSI", "ASUS", "XFX"):
        return upper
    return token.title()


def _normalize_breadcrumb_brand_candidate(value: str | None) -> Optional[str]:
    """
    Validates if a string candidate from breadcrumbs matches a known GPU vendor.
    """
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", str(value)).strip()
    if not candidate:
        return None
    upper = candidate.upper()
    vendors = [
        "ASUS",
        "MSI",
        "GIGABYTE",
        "ASROCK",
        "PALIT",
        "ZOTAC",
        "PNY",
        "SAPPHIRE",
        "POWERCOLOR",
        "XFX",
        "INNO3D",
        "GAINWARD",
        "EVGA",
        "GALAX",
        "KFA2",
        "COLORFUL",
        "AORUS",
        "ACER",
        "LENOVO",
        "HP",
        "DELL",
    ]
    for v in vendors:
        if upper == v or v in upper:
            return _normalize_vendor_token(v)
    return None


def _extract_breadcrumb_brand(soup: BeautifulSoup) -> Optional[str]:
    """
    Attempts to extract the brand/vendor from the breadcrumb navigation.
    
    Args:
        soup: BeautifulSoup object of the page.
        
    Returns:
        The normalized vendor name if found, otherwise None.
    """
    candidates: list[str] = []
    for anchor in soup.select("a[data-category='Breadcrumb']"):
        data_label = anchor.get("data-label")
        if data_label:
            candidates.append(data_label)
        text = anchor.get_text(" ", strip=True)
        if text:
            candidates.append(text)
        href = anchor.get("href") or ""
        import re
        match = re.search(r"/filter/brands/([^/?#]+)", href, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1).replace("-", " "))
    for candidate in candidates:
        normalized = _normalize_breadcrumb_brand_candidate(candidate)
        if normalized:
            return normalized
    return None


def parse_gpu_page(html: str, url: str) -> dict:
    """
    Main entry point for parsing a GPU product page.
    
    Extracts GPU metadata and technical specifications, with specialized logic
    for identifying chip brands (NVIDIA/AMD) and PCB manufacturers.
    
    Args:
        html: HTML content of the GPU page.
        url: URL of the page.
        
    Returns:
        A dictionary containing the extracted GPU data.
    """
    soup = BeautifulSoup(html, "lxml")

    name = _first_text(soup, [".product-name", ".product-title", "h1", ".name"]) or ""

    specs_el = None
    for sel in (".description", "#description", ".product-description", ".desc"):
        specs_el = soup.select_one(sel)
        if specs_el:
            break

    specs_text = specs_el.get_text("\n") if specs_el else ""

    spec_chunks = [specs_text] if specs_text else []
    specs_dict = _collect_specs(soup)
    slot_el = soup.select_one("#char-slot")
    if slot_el:
        slot_text = slot_el.get_text(" ", strip=True)
        if slot_text:
            specs_dict.setdefault("Slot", slot_text)
    for sel in (
        ".specs",
        ".specifications",
        ".tech-specs",
        ".product-specs",
        ".characteristics",
        "#characteristics",
        ".attributes",
        ".params",
        ".product-params",
        ".product-attributes",
        ".tab-specs",
        ".tab-parameters",
    ):
        el = soup.select_one(sel)
        if el:
            text = el.get_text("\n", strip=True)
            if text:
                spec_chunks.append(text)

    for table in soup.select("table"):
        text = table.get_text("\n", strip=True)
        if text:
            spec_chunks.append(text)

    if spec_chunks:
        specs_text = "\n".join(spec_chunks)
        if len(specs_text) > 12000:
            specs_text = specs_text[:12000]

    price_eur, price_bgn = _extract_prices(soup)
    price = price_eur if price_eur is not None else price_bgn

    brand, model, pcb_manufacturer, pcb_series = _parse_brand_model(name)
    breadcrumb_brand = _extract_breadcrumb_brand(soup)
    if breadcrumb_brand:
        pcb_manufacturer = breadcrumb_brand

    return {
        "name": name,
        "brand": brand,
        "model": model,
        "pcb_manufacturer": pcb_manufacturer,
        "pcb_series": pcb_series,
        "price": price,
        "price_bgn": price_bgn,
        "url": url,
        "raw_specs": specs_text,
        "specs": specs_dict,
    }

