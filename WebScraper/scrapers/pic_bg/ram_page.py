from bs4 import BeautifulSoup
from typing import Optional, Tuple
import re

BGN_PER_EUR = 1.95583


def _first_text(soup, selectors) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.text and el.text.strip():
            return el.text.strip()
    return None


def _parse_price_el(el) -> Optional[float]:
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


def _parse_brand_model(title: str):
    # import re

    if not title:
        return None, None

    s = title
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"(?i)ram|memory|ram памет|памет|kit", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[\n\r]", " ", s)
    s = " ".join(s.split())

    brands = [
        "KINGSTON",
        "CORSAIR",
        "G.SKILL",
        "GSKILL",
        "ADATA",
        "XPG",
        "CRUCIAL",
        "TEAMGROUP",
        "TEAM GROUP",
        "TEAM",
        "PATRIOT",
        "SAMSUNG",
        "HYNIX",
        "MICRON",
        "GOODRAM",
        "LEXAR",
        "SILICON POWER",
        "HYPERX",
        "HP",
    ]
    brand = None
    upper = s.upper()
    for b in brands:
        if b in upper:
            brand = b
            s = re.sub(re.escape(b), "", s, flags=re.IGNORECASE).strip()
            break

    s = re.sub(r"\bDDR\d\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{3,5}\s*MHz\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bCL\s*\d+\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*[x×]\s*\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(SO-?DIMM|UDIMM|DIMM|LAPTOP|DESKTOP|KIT)\b", "", s, flags=re.IGNORECASE
    )
    s = " ".join(s.split())

    model = s or None
    return brand, model


def _normalize_breadcrumb_brand_candidate(value: str | None) -> Optional[str]:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", str(value)).strip()
    if not candidate:
        return None
    upper = candidate.upper()
    brand_tokens = [
        "KINGSTON",
        "CORSAIR",
        "G.SKILL",
        "GSKILL",
        "ADATA",
        "XPG",
        "CRUCIAL",
        "TEAMGROUP",
        "TEAM GROUP",
        "TEAM",
        "PATRIOT",
        "SAMSUNG",
        "HYNIX",
        "MICRON",
        "GOODRAM",
        "LEXAR",
        "SILICON POWER",
        "HYPERX",
        "HP",
    ]
    for token in brand_tokens:
        if upper == token or token in upper:
            return token
    return None


def _extract_breadcrumb_brand(soup: BeautifulSoup) -> Optional[str]:
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


def parse_ram_page(html: str, url: str) -> dict:
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
        if len(specs_text) > 12000:
            specs_text = specs_text[:12000]

    price_eur, price_bgn = _extract_prices(soup)
    price = price_eur if price_eur is not None else price_bgn

    brand, model = _parse_brand_model(name)
    breadcrumb_brand = _extract_breadcrumb_brand(soup)
    if brand is None or str(brand).upper() in ("TEAM", "XPG", "AXPG", "NULL", "NONE"):
        if breadcrumb_brand:
            brand = breadcrumb_brand

    return {
        "name": name,
        "brand": brand,
        "model": model,
        "price": price,
        "price_bgn": price_bgn,
        "url": url,
        "raw_specs": specs_text,
        "specs": specs_dict,
    }
