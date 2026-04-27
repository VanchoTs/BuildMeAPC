import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import GPU_CATEGORY_URL
from scrapers.pic_bg.gpu_page import parse_gpu_page
from ai.gpu_parser import parse_gpu
from storage.gpu_repository import (
    upsert_gpu,
    get_common_memory_type_for_model,
    get_common_interface_for_model,
)

logger = logging.getLogger("gpu_pipeline")
if not logger.handlers:
    fh = logging.FileHandler(os.environ.get("SCRAPER_ERROR_LOG", "scraper_errors.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


async def _retry(coro_fn, *args, attempts: int = 3, delay: float = 1.0, **kwargs):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            logger.warning(
                "Attempt %d failed for %s: %s",
                attempt,
                getattr(coro_fn, "__name__", str(coro_fn)),
                e,
            )
            if attempt < attempts:
                await asyncio.sleep(delay)
    raise last_exc


async def accept_cookies(page):
    try:
        await page.click("button:has-text('Приемам')", timeout=4000)
        await asyncio.sleep(1)
    except Exception:
        pass


async def collect_gpu_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href^='/videokarta']")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if href:
            urls.append("https://www.pic.bg" + href)

    print(f"  → GPUs on page: {len(urls)}")
    return urls


async def get_next_page_button(page, current_page: int):
    next_page = current_page + 1
    selector = f"div.pages button.page_link[data-page='{next_page}']"
    btn = page.locator(selector)

    if await btn.count() == 0:
        return None
    disabled = await btn.first.get_attribute("disabled")
    if disabled is not None:
        return None
    return btn.first


def _infer_model_from_url(u: str) -> Optional[str]:
    if not u:
        return None
    slug = u.rstrip("/").split("/")[-1]
    parts = [p for p in slug.split("-") if p]
    lower = [p.lower() for p in parts]
    if "rtx" in lower:
        i = lower.index("rtx")
        if i + 1 < len(parts) and re.match(r"^\d{3,4}$", parts[i + 1]):
            token = f"RTX {parts[i + 1]}"
            if i + 2 < len(parts) and lower[i + 2] in ("ti", "super"):
                token = f"{token} {lower[i + 2].upper()}"
            return f"GeForce {token}"
    if "gtx" in lower:
        i = lower.index("gtx")
        if i + 1 < len(parts) and re.match(r"^\d{3,4}$", parts[i + 1]):
            token = f"GTX {parts[i + 1]}"
            if i + 2 < len(parts) and lower[i + 2] in ("ti", "super"):
                token = f"{token} {lower[i + 2].upper()}"
            return f"GeForce {token}"
    if "gt" in lower:
        i = lower.index("gt")
        if i + 1 < len(parts) and re.match(r"^\d{3,4}$", parts[i + 1]):
            token = f"GT {parts[i + 1]}"
            return f"GeForce {token}"
    if "n" in lower:
        i = lower.index("n")
        if i + 1 < len(parts) and re.match(r"^\d{4}$", parts[i + 1]):
            return f"GeForce RTX {parts[i + 1]}"
    if "rx" in lower:
        i = lower.index("rx")
        if i + 1 < len(parts) and re.match(r"^\d{3,4}$", parts[i + 1]):
            token = f"RX {parts[i + 1]}"
            if i + 2 < len(parts) and lower[i + 2] in ("xt", "xtx", "gre"):
                token = f"{token} {lower[i + 2].upper()}"
            return f"Radeon {token}"
    if "arc" in lower:
        i = lower.index("arc")
        if i + 1 < len(parts) and re.match(
            r"^[a-z]\d{3,4}$", parts[i + 1], re.IGNORECASE
        ):
            token = parts[i + 1].upper()
            return f"Arc {token}"
    return None


def _normalize_brand(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    if "NVIDIA" in s:
        return "NVIDIA"
    if "AMD" in s or "RADEON" in s:
        return "AMD"
    if "INTEL" in s or "ARC" in s:
        return "Intel"
    return s.title()


def _brand_from_model(model: str | None) -> Optional[str]:
    if not model:
        return None
    s = str(model).upper()
    if "RADEON" in s or " RX " in f" {s} ":
        return "AMD"
    if "GEFORCE" in s or re.search(r"\bRTX\b|\bGTX\b|\bGT\b", s):
        return "NVIDIA"
    if "ARC" in s:
        return "Intel"
    return None


def _normalize_model(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    s = " ".join(s.split())
    if re.search(r"\bT\s*400\b", s, flags=re.IGNORECASE):
        return "T400"
    if re.match(r"^N\s*\d{4}", s, flags=re.IGNORECASE):
        s = re.sub(r"^N\s*(\d{4}).*$", r"GeForce RTX \1", s, flags=re.IGNORECASE)
    if re.match(r"^RX\s*\d{3,4}\s*XTX?$", s, flags=re.IGNORECASE):
        s = re.sub(
            r"^RX\s*(\d{3,4})\s*XT(X)?$", r"Radeon RX \1 XT\2", s, flags=re.IGNORECASE
        )
        s = s.replace("XTXT", "XTX")
    s = re.sub(
        r"\bRadeon\s+R(\d{3,4})[A-Za-z].*",
        r"Radeon RX \1",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\bRadeon\s+R(\d{3,4})\b", r"Radeon RX \1", s, flags=re.IGNORECASE)
    if re.match(r"^RX\s*\d{3,4}(?:\s*(?:XT|XTX|GRE))?$", s, flags=re.IGNORECASE):
        s = re.sub(
            r"^RX\s*(\d{3,4})(?:\s*(XT|XTX|GRE))?$",
            r"Radeon RX \1 \2",
            s,
            flags=re.IGNORECASE,
        ).strip()
        s = " ".join(s.split())
    s = re.sub(
        r"\bRadeon\s+RX\s+9(\d{2})\s*(XT|XTX|GRE)\b",
        r"Radeon RX 90\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    if re.match(r"^GT\s*\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^GT\s*(\d{3,4})$", r"GeForce GT \1", s, flags=re.IGNORECASE)
    if re.match(r"^RTX\s*A\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^RTX\s*", "RTX ", s, flags=re.IGNORECASE)
        return s
    m = re.search(r"ARC\s+LUMA-?A(\d{3,4})", s, flags=re.IGNORECASE)
    if m:
        s = f"Arc A{m.group(1)}"
    s = re.sub(r"\bRTX\s*(\d{3,4})\b", r"RTX \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bGTX\s*(\d{3,4})\b", r"GTX \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bGT\s*(\d{3,4})\b", r"GT \1", s, flags=re.IGNORECASE)
    s = re.sub(
        r"^(RTX|GTX)\s*(\d{3,4})\s*(TI|SUPER)$",
        r"GeForce \1 \2 \3",
        s,
        flags=re.IGNORECASE,
    )
    if re.match(r"^RTX\s*\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^RTX\s*(\d{3,4})$", r"GeForce RTX \1", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX|RTX|GTX)\s*(\d{3,4})\s*(TI|SUPER)\b",
        r"\1 \2 \3",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX|RTX|GTX)\s*(\d{3,4})\s*(TI)\b",
        r"\1 \2 Ti",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX|GeForce\s+GTX|RTX|GTX)\s*(\d{3,4})\s*(SUPER)\b",
        r"\1 \2 Super",
        s,
        flags=re.IGNORECASE,
    )
    if re.match(r"^GeForce\s+N\d{3,4}$", s, flags=re.IGNORECASE):
        s = re.sub(r"^GeForce\s+N(\d{3,4})$", r"GeForce RTX \1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bRadeon\s+RX\s*(\d{3,4})\b", r"Radeon RX \1", s, flags=re.IGNORECASE)
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
    ]
    for pat in base_patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            s = m.group(1)
            s = " ".join(s.split())
            break
    s = re.sub(
        r"\b(Radeon\s+RX\s+\d{3,4})(XT|XTX|GRE|M)\b",
        r"\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\b(GeForce\s+RTX\s+\d{3,4})(Ti|Super)\b",
        r"\1 \2",
        s,
        flags=re.IGNORECASE,
    )
    return s


def _normalize_interface(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).replace("®", "")
    s = (
        s.replace("PCI-Express", "PCI Express")
        .replace("PCI‑Express", "PCI Express")
        .replace("PCI-E", "PCI Express")
        .replace("PCIe", "PCIe")
    )
    m = re.search(
        r"PCI\s*Express\s*(?:Gen|GEN)?\s*([0-9])(?:\.(\d))?",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        minor = m.group(2) or "0"
        return f"PCIe {m.group(1)}.{minor}"
    m = re.search(r"PCI\s*E\s*([0-9])\.?([0-9])?", s, flags=re.IGNORECASE)
    if m:
        minor = m.group(2) or "0"
        return f"PCIe {m.group(1)}.{minor}"
    m = re.search(r"PCIe\s*([0-9])(?:\.(\d))?", s, flags=re.IGNORECASE)
    if m:
        minor = m.group(2) or "0"
        return f"PCIe {m.group(1)}.{minor}"
    if re.search(r"\bdual\s*slots?\b", s, flags=re.IGNORECASE):
        return None
    if re.search(r"(HDMI|DISPLAYPORT|DVI|VGA)", s, flags=re.IGNORECASE):
        return None
    if re.search(r"\b\d+\s*-?\s*bit\b", s, flags=re.IGNORECASE):
        return None
    return s.strip()


def _series_is_valid(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = " ".join(str(value).split())
    if re.search(r"[A-Z0-9]{4,}", s) and re.search(r"\d", s):
        return None
    if len(s) > 32:
        return None
    return s


def _strip_series_from_model(model: str | None, series: str | None) -> Optional[str]:
    if not model or not series:
        return model
    m = model.strip()
    s = series.strip()
    if m.lower().endswith(s.lower()):
        return m[: -len(s)].strip()
    last = s.split()[-1]
    if last and m.lower().endswith(last.lower()):
        return m[: -len(last)].strip()
    return m


async def run_gpu_pipeline(
    headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None
):
    """
    Main GPU scraping pipeline.
    
    Workflow:
    1. URL collection: Crawls the GPU category to gather all individual product URLs.
    2. Page fetching: Navigates to each collected URL.
    3. Page parsing: Extracts raw HTML and specification tables from the product page.
    4. AI normalization: Sends raw specs to the LLM to extract structured fields.
    5. Database Upsert: Maps and stores normalized GPU data into the database.
    """
    async with Browser(headless=headless) as page:
        await page.set_extra_http_headers(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                )
            }
        )

        print(f"🔎 Opening {GPU_CATEGORY_URL}")
        await page.goto(GPU_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\n📄 Page {current_page}")

            urls = await collect_gpu_urls(page)
            if not urls:
                print("⛔ No products found, stopping.")
                break

            first_url = urls[0]
            if first_url == last_first_url:
                print("⛔ Page content did not change, stopping.")
                break

            last_first_url = first_url
            before = len(all_urls)
            all_urls.update(urls)
            print(f"  → New GPUs added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("⛔ No enabled next page button, stopping.")
                break

            print(f"➡️ Clicking page {current_page + 1}")
            await next_button.click()

            try:
                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href^='/videokarta']");
                        return el && el.href !== prev;
                    }""",
                    arg=first_url,
                    timeout=15000,
                )
            except Exception:
                print("⛔ Products did not update after click, stopping.")
                break

            current_page += 1
            await asyncio.sleep(1.5)

        print(f"\n✅ Total GPUs collected: {len(all_urls)}")
        for u in sorted(all_urls):
            print(" ", u)

        all_urls_list = [{"url": url} for url in sorted(all_urls)]
        with open("gpu_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Saved {len(all_urls_list)} GPU links to gpu_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\n🔁 Processing collected GPU pages and inserting into DB...")
        processed = 0
        for url in sorted(all_urls):
            if page_limit and processed >= page_limit:
                break
            try:
                print(f"  → Fetching: {url}")
                await _retry(
                    page.goto,
                    url,
                    wait_until="domcontentloaded",
                    timeout=90000,
                    attempts=3,
                    delay=1.5,
                )
                await asyncio.sleep(0.6)

                async def _scroll_page():
                    await page.evaluate("""
                    async () => {
                      const distance = 800;
                      const delay = 200;
                      let total = 0;
                      while (total < document.body.scrollHeight) {
                        window.scrollBy(0, distance);
                        total += distance;
                        await new Promise(r => setTimeout(r, delay));
                      }
                      window.scrollTo(0, 0);
                      await new Promise(r => setTimeout(r, 150));
                      window.scrollTo(0, document.body.scrollHeight);
                    }
                    """)

                try:
                    await _retry(_scroll_page, attempts=2, delay=0.2)
                except Exception:
                    pass

                html = await _retry(page.content, attempts=2, delay=0.5)
                parsed = parse_gpu_page(html, url)

                try:
                    specs = parsed.get("specs") or {}
                    if specs:
                        preferred_keys = (
                            "memory",
                            "vram",
                            "gddr",
                            "tdp",
                            "power",
                            "clock",
                            "boost",
                            "interface",
                            "bus",
                            "length",
                            "памет",
                            "честота",
                            "шина",
                            "дължина",
                        )
                        lines = [
                            f"{k}: {v}"
                            for k, v in specs.items()
                            if any(p in str(k).lower() for p in preferred_keys)
                        ]
                        if not lines:
                            lines = [f"{k}: {v}" for k, v in specs.items()]
                        ai_source = "\n".join(lines)
                        if len(ai_source) > 8000:
                            ai_source = ai_source[:8000]
                    else:
                        ai_source = parsed.get("raw_specs") or html
                    ai_data = parse_gpu(
                        ai_source, parsed.get("name", ""), parsed.get("price", 0.0), url
                    )
                except Exception as e:
                    logger.exception("AI parsing failed for %s", url)
                    print(f"    ✗ AI parse error for {url}: {e}")
                    ai_data = {}

                final = {}
                final_model = (
                    ai_data.get("model")
                    or parsed.get("model")
                    or ai_data.get("name")
                    or parsed.get("name")
                )
                final_model = _normalize_model(final_model)
                final_brand = _normalize_brand(
                    ai_data.get("brand") or parsed.get("brand")
                )
                final_pcb = ai_data.get("pcb_manufacturer") or parsed.get(
                    "pcb_manufacturer"
                )
                final_series = ai_data.get("pcb_series") or parsed.get("pcb_series")
                final_series = _series_is_valid(final_series)
                final_model = _strip_series_from_model(final_model, final_series)

                inferred = _infer_model_from_url(url)
                if not final_model and inferred:
                    final_model = _normalize_model(inferred)

                if final_model and inferred:
                    model_brand = _brand_from_model(final_model)
                    inferred_brand = _brand_from_model(inferred)
                    if (
                        model_brand
                        and inferred_brand
                        and model_brand != inferred_brand
                        and inferred
                    ):
                        final_model = _normalize_model(inferred)
                        model_brand = _brand_from_model(final_model)
                else:
                    model_brand = _brand_from_model(final_model)

                if (
                    model_brand
                    and final_brand
                    and final_brand.upper() != "MATROX"
                    and model_brand != final_brand
                ):
                    final_brand = model_brand
                elif model_brand and not final_brand:
                    final_brand = model_brand

                skip_upsert = False
                if not final_model or not re.search(r"\d{3,4}", final_model):
                    logger.warning(
                        "Skipping ambiguous GPU model for %s: %s", url, final_model
                    )
                    print(f"    ✗ Skipping ambiguous model for {url}: {final_model}")
                    skip_upsert = True

                if final_model and re.search(
                    r"\bXT/XTX\b", final_model, flags=re.IGNORECASE
                ):
                    if (
                        "sbp" in url
                        or "backpanel" in url
                        or "панел" in (parsed.get("name") or "").lower()
                    ):
                        logger.warning(
                            "Skipping accessory entry for %s: %s", url, final_model
                        )
                        print(
                            f"    ✗ Skipping accessory entry for {url}: {final_model}"
                        )
                        skip_upsert = True

                final["model"] = final_model
                final["name"] = ai_data.get("name") or parsed.get("name") or final_model
                final["brand"] = final_brand
                if final_brand and final_brand.upper() == "MATROX":
                    if final_model and "ARC" in final_model.upper():
                        final_brand = "Intel"
                        final_pcb = "Matrox"
                        final["brand"] = final_brand
                final["pcb_manufacturer"] = final_pcb
                final["pcb_series"] = final_series

                for k in (
                    "vram_gb",
                    "memory_type",
                    "memory_bus_bit",
                    "base_clock_mhz",
                    "boost_clock_mhz",
                    "tdp",
                    "interface",
                    "pcb_series",
                ):
                    if k in ai_data and ai_data.get(k) is not None:
                        final[k] = ai_data.get(k)
                if final.get("interface") is not None:
                    final["interface"] = _normalize_interface(final.get("interface"))
                    m = re.search(r"PCIe\s*([0-9])", str(final["interface"]))
                    if m:
                        try:
                            if int(m.group(1)) > 5:
                                final["interface"] = None
                        except Exception:
                            pass

                raw = parsed.get("raw_specs", "") or ""
                specs = parsed.get("specs") or {}
                specs_lc = {str(k).lower(): str(v) for k, v in specs.items() if k and v}

                def _spec_value(keys):
                    for k, v in specs_lc.items():
                        if any(key in k for key in keys):
                            return v
                    return None

                def _try_extract_from(text, patterns):
                    for p in patterns:
                        m = re.search(p, text, flags=re.IGNORECASE)
                        if m:
                            if m.lastindex and m.lastindex >= 1:
                                return m.group(m.lastindex)
                            return m.group(1)
                    return None

                if final.get("vram_gb") is None:
                    spec_mem = _spec_value(["memory", "vram", "памет"])
                    if spec_mem:
                        v = _try_extract_from(spec_mem, [r"(\d+)\s*gb"])
                        if v:
                            try:
                                final["vram_gb"] = int(v)
                            except Exception:
                                pass
                    if final.get("vram_gb") is None:
                        m = re.search(r"(\d+)\s*GB", raw, flags=re.IGNORECASE)
                        if m:
                            try:
                                final["vram_gb"] = int(m.group(1))
                            except Exception:
                                pass

                if final.get("memory_type") is None:
                    m = re.search(r"(GDDR\s*\dX?|HBM\s*\d?)", raw, flags=re.IGNORECASE)
                    if m:
                        final["memory_type"] = m.group(1).upper().replace(" ", "")

                slot = _spec_value(["slot", "слот", "interface", "интерфейс"])
                if slot:
                    normalized_slot = _normalize_interface(slot)
                    if normalized_slot:
                        final["interface"] = normalized_slot
                if final.get("interface") is None:
                    m = re.search(r"PCI\s*Express\s*Gen\s*\d", raw, flags=re.IGNORECASE)
                    if m:
                        final["interface"] = _normalize_interface(m.group(0))
                if final.get("interface") is not None:
                    m = re.search(r"PCIe\s*([0-9])", str(final["interface"]))
                    if m:
                        try:
                            if int(m.group(1)) > 5:
                                final["interface"] = None
                        except Exception:
                            pass

                if final.get("tdp") is None:
                    m = re.search(r"(\d{2,3})\s*[Ww]", raw)
                    if m:
                        try:
                            final["tdp"] = int(m.group(1))
                        except Exception:
                            pass

                final["price"] = (
                    parsed.get("price")
                    if parsed.get("price") is not None
                    else ai_data.get("price")
                )
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                if final.get("memory_type") is None and final.get("model"):
                    db_mem = get_common_memory_type_for_model(final.get("model"))
                    if db_mem:
                        final["memory_type"] = db_mem

                if final.get("interface") is None and final.get("model"):
                    db_if = get_common_interface_for_model(final.get("model"))
                    if db_if:
                        final["interface"] = db_if

                try:
                    if not skip_upsert:
                        upsert_gpu(final)
                        print(f"    ✓ Upserted: {final.get('model')}")
                except Exception as e:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    ✗ DB upsert error for {url}: {e}")

            except Exception as e:
                logger.exception("Failed to process %s", url)
                print(f"    ✗ Error processing {url}: {e}")

            processed += 1
            await asyncio.sleep(0.6)


if __name__ == "__main__":
    asyncio.run(run_gpu_pipeline())
