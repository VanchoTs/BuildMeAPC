from bs4 import BeautifulSoup
from typing import Optional, Tuple


def _first_text(soup, selectors) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.text and el.text.strip():
            return el.text.strip()
    return None


BGN_PER_EUR = 1.95583


def _parse_price_el(el) -> Optional[float]:
    if el is None:
        return None
    import re

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

    m = re.search(r"[0-9]+(?:[\\.,][0-9]+)?", cleaned)
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


def parse_cpu_page(html: str, url: str) -> dict:
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

    def _parse_brand_model(title: str):
        import re

        if not title:
            return None, None

        s = title

        s = re.sub(r"(?i)процесор|processor|cpu", "", s)
        s = re.sub(r"[™®]", "", s)

        s = re.sub(r"\(.*?\)", "", s)

        s = re.sub(r"[,\n\r]", " ", s).strip()

        m = re.search(r"\b(AMD|Intel|Apple|Qualcomm|NVIDIA)\b", s, flags=re.IGNORECASE)
        brand = m.group(1).upper() if m else None
        if brand:

            s = re.sub(re.escape(m.group(0)), "", s, flags=re.IGNORECASE).strip()

        stop_words = {"BOX", "TRAY", "MPK", "WOF", "NO", "FAN", "BOXED"}
        stop_substrings = {"BOX", "TRAY", "MPK", "WOF", "SBX", "KIT", "FAN"}
        tokens = [t for t in s.split() if t]
        model_tokens = []
        for t in tokens:
            t_upper = t.upper()
            if t_upper in stop_words or any(
                stop in t_upper for stop in stop_substrings
            ):
                break

            if re.match(r"^[A-Z0-9\\-]{6,}$", t):
                if re.search(r"[A-Z]", t) and re.search(r"\d", t) and len(t) <= 8:
                    model_tokens.append(t)
                    continue
                break
            model_tokens.append(t)

        model = " ".join(model_tokens[:3]).strip() if model_tokens else None

        if model:
            model = model.strip("- ,")
            if not re.search(r"\d{3,}", model):
                model = None

        return brand, model

    brand, model = _parse_brand_model(name)

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
