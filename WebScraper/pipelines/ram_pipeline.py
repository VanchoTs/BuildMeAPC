import asyncio
import json
import logging
import os
import re
from typing import Optional

from scrapers.core.browser import Browser
from scrapers.pic_bg.urls import RAM_CATEGORY_URL
from scrapers.pic_bg.ram_page import parse_ram_page
from ai.ram_parser import parse_ram
from storage.ram_repository import upsert_ram

logger = logging.getLogger("ram_pipeline")
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


async def collect_ram_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href^='/ram']")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if href:
            urls.append("https://www.pic.bg" + href)

    print(f"  -> RAM modules on page: {len(urls)}")
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


def _normalize_brand(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    upper = s.upper()
    if upper in ("NULL", "NONE", "N/A"):
        return None
    if "G.SKILL" in upper or "GSKILL" in upper:
        return "G.SKILL"
    if "CORSAIR" in upper:
        return "Corsair"
    if "KINGSTON" in upper:
        return "Kingston"
    if "ADATA" in upper:
        return "ADATA"
    if "XPG" in upper or "AXPG" in upper:
        return "ADATA"
    if "CRUCIAL" in upper:
        return "Crucial"
    if "TEAM" in upper and "GROUP" in upper:
        return "TeamGroup"
    if upper.startswith("TEAM"):
        return "TeamGroup"
    if "PATRIOT" in upper:
        return "Patriot"
    if "SAMSUNG" in upper:
        return "Samsung"
    if "HYNIX" in upper:
        return "SK hynix"
    if "MICRON" in upper:
        return "Micron"
    if "HP" in upper:
        return "HP"
    return s.title()


def _normalize_model(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    s = s.replace("™", "").replace("®", "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\bDDR\d\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{3,5}\s*MHz\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bCL\s*\d+\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*[x×]\s*\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+\s*GB\b", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(SO-?DIMM|UDIMM|DIMM|LAPTOP|DESKTOP|KIT)\b",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = " ".join(s.split())
    return s or None


def _infer_brand_from_text(text: str | None) -> Optional[str]:
    if not text:
        return None
    upper = str(text).upper()
    for token in (
        "G.SKILL",
        "GSKILL",
        "CORSAIR",
        "KINGSTON",
        "ADATA",
        "XPG",
        "AXPG",
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
    ):
        if token in upper:
            return _normalize_brand(token)
    return None


def _normalize_memory_type(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    m = re.search(r"DDR[3-5]", s)
    return m.group(0) if m else None


def _normalize_latency(value: str | None) -> Optional[str]:
    if not value:
        return None
    s = str(value).upper()
    m = re.search(r"CL\s*(\d+)", s)
    if m:
        return f"CL{m.group(1)}"
    return None


def _normalize_speed(value: str | None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    m = re.search(r"(\d{3,5})", s)
    if m:
        speed = int(m.group(1))
        if 100 <= speed <= 10000:
            return speed
    return None


def _extract_memory_amount(*texts: str | None) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        m = re.search(r"\((\d+)\s*[x×*]\s*(\d+)\s*G(?:B)?\)", text, flags=re.IGNORECASE)
        if m:
            return f"{int(m.group(1))}x{int(m.group(2))}GB"
    for text in texts:
        if not text:
            continue
        m = re.search(r"(\d+)\s*[x×*]\s*(\d+)\s*G(?:B)?\b", text, flags=re.IGNORECASE)
        if m:
            return f"{int(m.group(1))}x{int(m.group(2))}GB"
    for text in texts:
        if not text:
            continue
        m = re.search(r"\b(\d{1,3})\s*G(?:B)?\b", text, flags=re.IGNORECASE)
        if m:
            return f"1x{int(m.group(1))}GB"
    return None


def _infer_memory_amount_from_parts(
    raw: str, specs: dict, name: str | None
) -> Optional[str]:
    texts = [raw, name] + list((specs or {}).values())
    joined = " ".join([t for t in texts if t])
    m = re.search(r"\b(\d+)\s*[x×*]\s*(\d+)\s*G(?:B)?\b", joined, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}x{int(m.group(2))}GB"
    m = re.search(r"\b(\d{1,3})\s*G(?:B)?\b", joined, flags=re.IGNORECASE)
    if m:
        return f"1x{int(m.group(1))}GB"
    return None


def _extract_memory_amount_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    slug = str(url).rstrip("/").split("/")[-1].replace("-", " ")
    return _extract_memory_amount(slug)


def _extract_memory_speed(*texts: str | None) -> Optional[int]:
    for text in texts:
        if not text:
            continue
        m = re.search(r"DDR[3-5]\s*[- ]?\s*(\d{3,5})", text, flags=re.IGNORECASE)
        if m:
            speed = int(m.group(1))
            if 100 <= speed <= 10000:
                return speed
    for text in texts:
        if not text:
            continue
        m = re.search(r"(\d{3,5})\s*MHz", text, flags=re.IGNORECASE)
        if m:
            speed = int(m.group(1))
            if 100 <= speed <= 10000:
                return speed
    for text in texts:
        if not text:
            continue
        m = re.search(r"(\d{3,5})\s*MT/s", text, flags=re.IGNORECASE)
        if m:
            speed = int(m.group(1))
            if 100 <= speed <= 10000:
                return speed
    return None


def _extract_latency(*texts: str | None) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        m = re.search(r"CL\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            return f"CL{m.group(1)}"
    return None


def _extract_form_factor(*texts: str | None) -> Optional[str]:
    for text in texts:
        if not text:
            continue
        s = str(text).upper()
        if any(k in s for k in ("SO-DIMM", "SODIMM", "LAPTOP", "NOTEBOOK")):
            return "Laptop"
        if any(k in s for k in ("UDIMM", "DIMM", "DESKTOP", "PC")):
            return "PC"
    return None


def _build_ai_source(specs: dict, raw: str) -> str:
    if specs:
        preferred = (
            "memory",
            "ram",
            "ddr",
            "capacity",
            "size",
            "speed",
            "mhz",
            "latency",
            "cl",
            "timing",
            "kit",
            "module",
            "sodimm",
            "dimm",
            "laptop",
            "памет",
            "честота",
            "тайминг",
        )
        lines = [
            f"{k}: {v}"
            for k, v in specs.items()
            if any(p in str(k).lower() for p in preferred)
        ]
        if not lines:
            lines = [f"{k}: {v}" for k, v in specs.items()]
        ai_source = "\n".join(lines)
        if len(ai_source) > 8000:
            ai_source = ai_source[:8000]
        return ai_source
    return raw


async def run_ram_pipeline(
    headless: bool = False, collect_only: bool = False, page_limit: Optional[int] = None
):
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

        print(f"Opening {RAM_CATEGORY_URL}")
        await page.goto(RAM_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\nPage {current_page}")

            urls = await collect_ram_urls(page)
            if not urls:
                print("No products found, stopping.")
                break

            first_url = urls[0]
            if first_url == last_first_url:
                print("Page content did not change, stopping.")
                break

            last_first_url = first_url
            before = len(all_urls)
            all_urls.update(urls)
            print(f"  -> New RAM products added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("No enabled next page button, stopping.")
                break

            print(f"Clicking page {current_page + 1}")
            await next_button.click()

            try:
                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href^='/ram']");
                        return el && el.href !== prev;
                    }""",
                    arg=first_url,
                    timeout=15000,
                )
            except Exception:
                print("Products did not update after click, stopping.")
                break

            current_page += 1
            await asyncio.sleep(1.5)

        print(f"\nTotal RAM products collected: {len(all_urls)}")
        for u in sorted(all_urls):
            print(" ", u)

        all_urls_list = [{"url": url} for url in sorted(all_urls)]
        with open("ram_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_urls_list)} RAM links to ram_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\nProcessing collected RAM pages and inserting into DB...")
        processed = 0
        for url in sorted(all_urls):
            if page_limit and processed >= page_limit:
                break
            try:
                print(f"  -> Fetching: {url}")
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
                parsed = parse_ram_page(html, url)

                try:
                    ai_source = _build_ai_source(
                        parsed.get("specs") or {}, parsed.get("raw_specs") or ""
                    )
                    ai_data = parse_ram(
                        ai_source, parsed.get("name", ""), parsed.get("price", 0.0), url
                    )
                except Exception as e:
                    logger.exception("AI parsing failed for %s", url)
                    print(f"    AI parse error for {url}: {e}")
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
                if final_brand is None:
                    final_brand = _infer_brand_from_text(parsed.get("name"))
                if final_brand is None:
                    final_brand = _infer_brand_from_text(parsed.get("raw_specs"))

                if not final_model or not re.search(r"[A-Za-z]", final_model):
                    logger.warning(
                        "Skipping ambiguous RAM model for %s: %s", url, final_model
                    )
                    print(f"    Skipping ambiguous model for {url}: {final_model}")
                    continue

                final["model"] = final_model
                final["brand"] = final_brand

                for k in (
                    "memory_type",
                    "memory_amount",
                    "memory_speed_mhz",
                    "latency",
                    "form_factor",
                ):
                    if k in ai_data and ai_data.get(k) is not None:
                        final[k] = ai_data.get(k)

                raw = parsed.get("raw_specs", "") or ""
                specs = parsed.get("specs") or {}
                specs_lc = {str(k).lower(): str(v) for k, v in specs.items() if k and v}

                def _spec_value(keys):
                    for k, v in specs_lc.items():
                        if any(key in k for key in keys):
                            return v
                    return None

                if final.get("memory_type") is None:
                    mem_val = _spec_value(["ddr", "type", "memory", "памет"])
                    final["memory_type"] = _normalize_memory_type(mem_val or raw)

                if final.get("memory_amount") is None:
                    mem_val = _spec_value(
                        [
                            "capacity",
                            "size",
                            "memory",
                            "памет",
                            "kit",
                            "module",
                            "modules",
                            "stick",
                            "комплект",
                            "модул",
                            "модули",
                            "брой",
                        ]
                    )
                    final["memory_amount"] = _extract_memory_amount(
                        mem_val, parsed.get("name"), raw
                    )
                if final.get("memory_amount") is None:
                    final["memory_amount"] = _infer_memory_amount_from_parts(
                        raw, specs, parsed.get("name")
                    )
                if final.get("memory_amount") is None:
                    final["memory_amount"] = _extract_memory_amount_from_url(
                        parsed.get("url") or url
                    )

                if final.get("memory_speed_mhz") is None:
                    speed_val = _spec_value(["speed", "mhz", "frequency", "честота"])
                    final["memory_speed_mhz"] = _extract_memory_speed(speed_val, raw)

                if final.get("latency") is None:
                    lat_val = _spec_value(["latency", "cl", "timing", "тайминг"])
                    final["latency"] = _extract_latency(lat_val, raw)

                if final.get("form_factor") is None:
                    ff_val = _spec_value(["form", "dimm", "module", "тип"])
                    final["form_factor"] = _extract_form_factor(
                        ff_val, parsed.get("name"), raw
                    )

                if final.get("memory_type") is not None:
                    final["memory_type"] = _normalize_memory_type(
                        final.get("memory_type")
                    )
                if final.get("memory_amount") is not None:
                    final["memory_amount"] = _extract_memory_amount(
                        final.get("memory_amount")
                    )
                if final.get("memory_speed_mhz") is not None:
                    final["memory_speed_mhz"] = _normalize_speed(
                        final.get("memory_speed_mhz")
                    )
                if final.get("latency") is not None:
                    final["latency"] = _normalize_latency(final.get("latency"))
                if final.get("form_factor") is not None:
                    final["form_factor"] = _extract_form_factor(
                        final.get("form_factor")
                    )
                if final.get("memory_amount") is None:
                    final["memory_amount"] = _infer_memory_amount_from_parts(
                        raw, specs, parsed.get("name")
                    )
                if final.get("memory_amount") is None:
                    final["memory_amount"] = _extract_memory_amount_from_url(
                        parsed.get("url") or url
                    )

                final["price"] = (
                    parsed.get("price")
                    if parsed.get("price") is not None
                    else ai_data.get("price")
                )
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                try:
                    upsert_ram(final)
                    print(f"    Upserted: {final.get('model')}")
                except Exception as e:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    DB upsert error for {url}: {e}")

                processed += 1

            except Exception as e:
                logger.exception("Failed to process %s", url)
                print(f"    Error processing {url}: {e}")
