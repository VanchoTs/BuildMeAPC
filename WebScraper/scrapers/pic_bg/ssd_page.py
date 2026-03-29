from bs4 import BeautifulSoup
from typing import Optional, Tuple
import re

BGN_PER_EUR = 1.95583

_KNOWN_SSD_BRANDS = [
    "SAMSUNG",
    "CRUCIAL",
    "KINGSTON",
    "WD",
    "WESTERN DIGITAL",
    "ADATA",
    "XPG",
    "APACER",
    "MICRON",
    "TEAMGROUP",
    "TEAM GROUP",
    "TEAM",
    "SILICON POWER",
    "LEXAR",
    "GIGABYTE",
    "VERBATIM",
    "KIOXIA",
    "SEAGATE",
    "INTEL",
    "CORSAIR",
    "PATRIOT",
    "GOODRAM",
    "SK HYNIX",
    "HYNIX",
    "MSI",
    "HP",
    "SYNOLOGY",
]


def _first_text(soup, selectors) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.text and el.text.strip():
            return el.text.strip()
    return None


def _parse_price_el(el) -> Optional[float]:
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
    upper = token.upper()
    if upper in ("WD", "WESTERN DIGITAL"):
        return "WD"
    if upper in ("TEAMGROUP", "TEAM GROUP", "TEAM"):
        return "TeamGroup"
    if upper in ("SK HYNIX", "HYNIX"):
        return "SK hynix"
    if upper == "GIGABYTE":
        return "GIGABYTE"
    if upper == "ADATA":
        return "ADATA"
    if upper == "MSI":
        return "MSI"
    if upper == "HP":
        return "HP"
    if upper == "SYNOLOGY":
        return "Synology"
    return token.title()


def _parse_brand_model(title: str):
    if not title:
        return None, None

    s = str(title).replace("™", "").replace("®", "")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[\n\r]", " ", s)
    s = " ".join(s.split())

    brand = None
    upper = s.upper()
    for token in _KNOWN_SSD_BRANDS:
        if token in upper:
            brand = _normalize_brand_token(token)
            s = re.sub(re.escape(token), "", s, flags=re.IGNORECASE).strip()
            break

    s = re.sub(r"(?i)^SSD\s*", "", s).strip()
    s = re.sub(r"\b\d+(?:[\.,]\d+)?\s*TB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+(?:[\.,]\d+)?\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:M\.2|NVME|PCIE|PCIE|GEN\s*[345]|SATA(?:\s*III)?|SSD|HEATSINK)\b.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(2230|2242|2260|2280|22110|2\.5\"|2\.5INCH|2\.5)\b", "", s, flags=re.IGNORECASE)
    s = " ".join(s.split()).strip("- ,")
    return brand, (s or None)


def _normalize_breadcrumb_brand_candidate(value: str | None) -> Optional[str]:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", str(value)).strip()
    if not candidate:
        return None
    upper = candidate.upper()
    for token in _KNOWN_SSD_BRANDS:
        if upper == token or token in upper:
            return _normalize_brand_token(token)
    return None


def _extract_breadcrumb_brand(soup: BeautifulSoup) -> Optional[str]:
    candidates: list[str] = []
    for anchor in soup.select("a[data-category='Breadcrumb'], a[href*='/filter/brands/']"):
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


def parse_ssd_page(html: str, url: str) -> dict:
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

    brand, model = _parse_brand_model(name)
    brand_source = "title" if brand else None
    if brand is None:
        brand = _extract_breadcrumb_brand(soup)
        if brand:
            brand_source = "breadcrumb"

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
