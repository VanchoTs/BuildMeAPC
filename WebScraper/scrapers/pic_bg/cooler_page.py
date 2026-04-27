from bs4 import BeautifulSoup
from typing import Optional, Tuple
import re

from ai.cooler_brands import COOLER_BRAND_MAP, COOLER_BRAND_TOKENS
from ai.cooler_normalization import normalize_cooler_brand, normalize_cooler_model

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
    Parses a price element from the HTML, handling fractional parts in <sup> tags.
    
    Args:
        el: BeautifulSoup element containing price information.
        
    Returns:
        The parsed price as a float, or None if parsing fails.
    """
    if el is None:
        return None

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
    Extracts EUR and BGN prices from the page using common CSS selectors.
    
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
    Aggregates technical specifications from tables, definition lists, and list items.
    
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


def _normalize_brand_token(token: str) -> str:
    """
    Normalizes a brand token using a predefined map or title casing as fallback.
    """
    return COOLER_BRAND_MAP.get(token.upper(), token.title())


def _parse_brand_model(title: str, prioritized_brand: str | None = None):
    """
    Heuristically extracts the cooler brand and model from the product title.
    
    Args:
        title: The product name string.
        prioritized_brand: A trusted brand name (e.g., from breadcrumbs) to use first.
        
    Returns:
        A tuple of (brand, model).
    """
    if not title:
        return None, None

    s = str(title).replace("™", "").replace("®", "")
    # DON'T strip parentheses here, they might contain brand info
    # s = re.sub(r"\(.*?\)", "", s) 
    s = re.sub(r"[\n\r]", " ", s)
    s = " ".join(s.split())

    brand = None
    upper = s.upper()

    # If we already have a trusted brand from breadcrumb, use it
    if prioritized_brand:
        brand = prioritized_brand
        # Still try to strip it from the model name
        for token in COOLER_BRAND_TOKENS:
            if token in upper and _normalize_brand_token(token) == prioritized_brand:
                s = re.sub(re.escape(token), "", s, flags=re.IGNORECASE).strip()
                break
    else:
        # Search for brand tokens, prefer longer matches first
        found_matches = []
        for token in COOLER_BRAND_TOKENS:
            if token in upper:
                found_matches.append((len(token), token))
        
        if found_matches:
            found_matches.sort(reverse=True)
            best_token = found_matches[0][1]
            brand = _normalize_brand_token(best_token)
            s = re.sub(re.escape(best_token), "", s, flags=re.IGNORECASE).strip()

    # Strip Bulgarian Cyrillic cooler-prefixes from the start of the model.
    # Order matters: longer phrases first so "Охладител за процесор" wins over "Охладител".
    s = re.sub(r"(?i)^\s*Охладител\s+за\s+процесор\s*", "", s).strip()
    s = re.sub(r"(?i)^\s*Водно\s+охлаждане\s*", "", s).strip()
    s = re.sub(r"(?i)^\s*Охладител\s*", "", s).strip()
    s = re.sub(r"(?i)^(?:CPU\s+COOLER|AIR\s+COOLER|WATER\s+COOLING|LIQUID\s+COOLER|COOLER)\s*", "", s).strip()
    s = " ".join(s.split()).strip("- ,")
    return brand, (s or None)


def _normalize_breadcrumb_brand_candidate(value: str | None) -> Optional[str]:
    """
    Validates if a string candidate from breadcrumbs matches a known cooler brand.
    """
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", str(value)).strip()
    if not candidate:
        return None
    upper = candidate.upper()
    for token in COOLER_BRAND_TOKENS:
        if upper == token or token in upper:
            return _normalize_brand_token(token)
    return None


def _extract_breadcrumb_brand(soup: BeautifulSoup) -> Optional[str]:
    """
    Extracts the brand from breadcrumb navigation links.
    
    Args:
        soup: BeautifulSoup object of the page.
        
    Returns:
        The normalized brand name if found, otherwise None.
    """
    candidates: list[str] = []
    # Only look at explicit breadcrumb links.
    # General brand filter links (a[href*='/filter/brands/']) often appear in the sidebar
    # and can lead to misidentifying the brand as whatever is first in the sidebar list.
    for anchor in soup.select("a[data-category='Breadcrumb']"):
        data_label = anchor.get("data-label")
        if data_label:
            candidates.append(data_label)
        text = anchor.get_text(" ", strip=True)
        if text:
            candidates.append(text)
        href = anchor.get("href") or ""
        match = re.search(r"/filter/brands/([^/?#]+)", href, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1).replace("-", " "))
    for candidate in candidates:
        normalized = _normalize_breadcrumb_brand_candidate(candidate)
        if normalized:
            return normalized
    return None


def parse_cooler_page(html: str, url: str) -> dict:
    """
    Main entry point for parsing a CPU Cooler product page.
    
    Args:
        html: HTML content of the page.
        url: URL of the page.
        
    Returns:
        A dictionary containing extracted cooler data (name, brand, model, price, specs).
    """
    soup = BeautifulSoup(html, "lxml")

    name = _first_text(soup, [".product-name", ".product-title", "h1", ".name"]) or ""

    breadcrumb_brand = _extract_breadcrumb_brand(soup)
    brand, model = _parse_brand_model(name, prioritized_brand=breadcrumb_brand)

    brand_source = "title" if brand and not breadcrumb_brand else None
    if breadcrumb_brand:
        brand = breadcrumb_brand
        brand_source = "breadcrumb"

    specs_el = None
    for sel in (".description", "#description", ".product-description", ".desc"):
        specs_el = soup.select_one(sel)
        if specs_el:
            break

    specs_text = specs_el.get_text("\n") if specs_el else ""

    spec_chunks = [specs_text] if specs_text else []
    specs_dict = _collect_specs(soup)
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
        if len(specs_text) > 16000:
            specs_text = specs_text[:16000]

    price_eur, price_bgn = _extract_prices(soup)
    price = price_eur if price_eur is not None else price_bgn

    if model is None and specs_dict.get("Модел"):
        model = specs_dict.get("Модел")

    # Spec-based brand fallback when neither breadcrumb nor title yielded one.
    if brand is None:
        for spec_key in ("Производител", "Марка", "Brand", "Manufacturer"):
            if specs_dict.get(spec_key):
                candidate = normalize_cooler_brand(specs_dict[spec_key])
                if candidate:
                    brand = candidate
                    brand_source = "spec"
                    break

    # Run the normalizers for final cleanup on brand/model derived from title/spec.
    if brand:
        normalized_brand = normalize_cooler_brand(brand)
        if normalized_brand:
            brand = normalized_brand
    if model:
        normalized_model = normalize_cooler_model(model, brand=brand)
        if normalized_model:
            model = normalized_model

    return {
        "name": name,
        "brand": brand,
        "brand_source": brand_source,
        "model": model,
        "price": price,
        "price_bgn": price_bgn,
        "url": url,
        "raw_specs": specs_text,
        "specs": specs_dict,
    }

