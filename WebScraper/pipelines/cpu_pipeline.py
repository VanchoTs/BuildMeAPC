import asyncio
import logging
import json
import os
import re
from typing import Optional

from scrapers.pic_bg.urls import CPU_CATEGORY_URL
from scrapers.core.browser import Browser

from scrapers.pic_bg.cpu_page import parse_cpu_page
from ai.cpu_parser import parse_cpu
from storage.cpu_repository import (
    upsert_cpu,
    get_common_memory_type_for_socket,
    get_common_socket_for_memory_type,
    get_common_socket_for_model,
)

logger = logging.getLogger("cpu_pipeline")
if not logger.handlers:
    fh = logging.FileHandler(os.environ.get("SCRAPER_ERROR_LOG", "scraper_errors.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)

OPN_MODEL_MAP = {
    "100-100001899MPK": "Ryzen 5 PRO 7445",
    "100-100001900MPK": "Ryzen 5 7400",
}

PART_MODEL_MAP = {
    "4XG7A37936": "Xeon Silver 4208",
}


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


async def collect_cpu_urls(page) -> list[str]:
    await page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(2)

    for _ in range(4):
        await page.mouse.wheel(0, 3000)
        await asyncio.sleep(1)

    items = page.locator("div.product-item a[href^='/procesor']")
    count = await items.count()

    urls = []
    for i in range(count):
        href = await items.nth(i).get_attribute("href")
        if href:
            urls.append("https://www.pic.bg" + href)

    print(f"  → CPUs on page: {len(urls)}")
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


async def run_cpu_pipeline(
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

        print(f"🔎 Opening {CPU_CATEGORY_URL}")
        await page.goto(CPU_CATEGORY_URL, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)

        all_urls: set[str] = set()
        current_page = 1
        last_first_url = None

        while True:
            print(f"\n📄 Page {current_page}")

            urls = await collect_cpu_urls(page)
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
            print(f"  → New CPUs added: {len(all_urls) - before}")

            next_button = await get_next_page_button(page, current_page)
            if not next_button:
                print("⛔ No enabled next page button, stopping.")
                break

            print(f"➡️ Clicking page {current_page + 1}")
            await next_button.click()

            try:

                await page.wait_for_function(
                    """(prev) => {
                        const el = document.querySelector("div.product-item a[href^='/procesor']");
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

        print(f"\n✅ Total CPUs collected: {len(all_urls)}")
        for u in sorted(all_urls):
            print(" ", u)

        all_urls_list = [{"url": url} for url in sorted(all_urls)]

        with open("cpu_links.json", "w", encoding="utf-8") as f:
            json.dump(all_urls_list, f, ensure_ascii=False, indent=2)

        print(f"\n💾 Saved {len(all_urls_list)} CPU links to cpu_links.json")

        if collect_only:
            print("Collect-only mode enabled; skipping product fetch and DB upsert.")
            return

        print("\n🔁 Processing collected CPU pages and inserting into DB...")
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

                parsed = parse_cpu_page(html, url)

                ai_source = parsed.get("raw_specs") or html
                try:

                    specs = parsed.get("specs") or {}
                    if specs:
                        preferred_keys = (
                            "core",
                            "thread",
                            "socket",
                            "tdp",
                            "power",
                            "frequency",
                            "clock",
                            "boost",
                            "turbo",
                            "cache",
                            "memory",
                            "ram",
                            "памет",
                            "ядр",
                            "ниш",
                            "сокет",
                            "честота",
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
                    ai_data = parse_cpu(
                        ai_source, parsed.get("name", ""), parsed.get("price", 0.0), url
                    )
                except Exception as e:
                    logger.exception("AI parsing failed for %s", url)
                    print(f"    ✗ AI parse error for {url}: {e}")
                    ai_data = {}

                final = {}

                text_source = " ".join(
                    s
                    for s in [parsed.get("name"), parsed.get("raw_specs"), ai_source]
                    if s
                )
                inferred_text_model = None

                final_model = ai_data.get("model") or parsed.get("model")
                final_brand = ai_data.get("brand") or parsed.get("brand") or "Unknown"

                if not final_model:
                    inferred_text_model = _infer_model_from_text(text_source)
                    if inferred_text_model:
                        final_model = inferred_text_model
                    else:
                        opn = _extract_opn(text_source)
                        mapped = OPN_MODEL_MAP.get(opn) if opn else None
                        if mapped:
                            final_model = mapped
                        else:
                            final_model = ai_data.get("name") or parsed.get("name")

                if final_model and _model_has_packaging(final_model):
                    inferred_text_model = _infer_model_from_text(text_source)
                    if inferred_text_model:
                        final_model = inferred_text_model
                    else:
                        opn = _extract_opn(text_source)
                        mapped = OPN_MODEL_MAP.get(opn) if opn else None
                        final_model = mapped

                if final_model:
                    generic = final_model.strip()
                    if re.match(
                        r"^Ryzen\s+[3579]$", generic, flags=re.IGNORECASE
                    ) or re.match(r"^Core\s+i[3579]$", generic, flags=re.IGNORECASE):
                        inferred_text_model = _infer_model_from_text(text_source)
                        if inferred_text_model:
                            final_model = inferred_text_model
                        else:
                            opn = _extract_opn(text_source)
                            mapped = OPN_MODEL_MAP.get(opn) if opn else None
                            if mapped:
                                final_model = mapped

                if final_model and not _is_plausible_model(final_model):
                    inferred_text_model = _infer_model_from_text(text_source)
                    if inferred_text_model:
                        final_model = inferred_text_model
                    else:
                        opn = _extract_opn(text_source)
                        mapped = OPN_MODEL_MAP.get(opn) if opn else None
                        if mapped:
                            final_model = mapped
                        else:
                            name_fallback = (
                                parsed.get("name") or ai_data.get("name") or ""
                            )
                            if name_fallback and _is_plausible_model(name_fallback):
                                final_model = name_fallback

                if not final_model:
                    inferred = _infer_model_from_url(url)
                    if inferred:
                        final_model = inferred
                    else:
                        opn = _extract_opn(url)
                        mapped = OPN_MODEL_MAP.get(opn) if opn else None
                        if mapped:
                            final_model = mapped

                for part, mapped_model in PART_MODEL_MAP.items():
                    if part in text_source:
                        final_model = mapped_model
                        final_brand = "Intel"
                        break

                final_model, final_brand = _normalize_model_brand(
                    final_model, final_brand
                )

                if (
                    final_model
                    and final_brand == "Intel"
                    and final_model.upper().startswith("RYZEN")
                ):
                    inferred_text_model = _infer_model_from_text(text_source)
                    if inferred_text_model and inferred_text_model.upper().startswith(
                        "CORE"
                    ):
                        final_model = inferred_text_model
                        final_brand = "Intel"

                skip_upsert = False
                if not final_model or not _is_plausible_model(final_model):
                    logger.warning(
                        "Skipping ambiguous CPU model for %s: %s", url, final_model
                    )
                    print(f"    ✗ Skipping ambiguous model for {url}: {final_model}")
                    skip_upsert = True

                final["model"] = final_model
                final["name"] = ai_data.get("name") or parsed.get("name") or final_model
                final["brand"] = final_brand

                for k in (
                    "cores",
                    "threads",
                    "base_clock",
                    "boost_clock",
                    "tdp",
                    "socket",
                    "memory_type",
                ):
                    if k in ai_data and ai_data.get(k) is not None:
                        final[k] = ai_data.get(k)

                raw = parsed.get("raw_specs", "") or ""
                specs = parsed.get("specs") or {}
                specs_lc = {str(k).lower(): str(v) for k, v in specs.items() if k and v}
                search_text = " ".join(
                    s for s in [parsed.get("name"), parsed.get("model"), raw, url] if s
                )
                socket_unavailable = False
                if isinstance(final.get("socket"), str):
                    if "not available" in final["socket"].lower():
                        socket_unavailable = True

                if final.get("cores") is None:
                    spec_cores = _spec_value(specs_lc, ["cores", "ядр"])
                    if spec_cores:
                        cores = _try_extract_from(spec_cores, [r"(\d+)"])
                        if cores:
                            try:
                                final["cores"] = int(cores)
                            except Exception:
                                pass
                    if final.get("cores") is None:
                        cores = _try_extract(
                            raw,
                            [
                                r"(\d+)\s*(?:cores|core|ядр|ядра|ядрен)",
                                r"Cores:\s*(\d+)",
                            ]
                        )
                        if cores:
                            try:
                                final["cores"] = int(cores)
                            except Exception:
                                pass

                if final.get("threads") is None:
                    spec_threads = _spec_value(specs_lc, ["threads", "ниш", "thread"])
                    if spec_threads:
                        threads = _try_extract_from(spec_threads, [r"(\d+)"])
                        if threads:
                            try:
                                final["threads"] = int(threads)
                            except Exception:
                                pass
                    if final.get("threads") is None:
                        threads = _try_extract(
                            raw, [r"(\d+)\s*(?:threads|thread|нишки|тред)"]
                        )
                        if threads:
                            try:
                                final["threads"] = int(threads)
                            except Exception:
                                pass

                if final.get("tdp") is None:
                    spec_tdp = _spec_value(specs_lc, ["tdp", "power", "мощност", "топлина"])
                    if spec_tdp:
                        tdp = _try_extract_from(spec_tdp, [r"(\d{2,3})"])
                        if tdp:
                            try:
                                final["tdp"] = int(tdp)
                            except Exception:
                                pass
                    if final.get("tdp") is None:
                        tdp = _try_extract(
                            raw,
                            [
                                r"(\d{2,3})\s*[Ww]",
                                r"TDP[:\s]+(\d{2,3})",
                                r"(\d{2,3})\s*Вт",
                            ]
                        )
                        if tdp:
                            try:
                                final["tdp"] = int(tdp)
                            except Exception:
                                pass

                if final.get("base_clock") is None:
                    spec_base = _spec_value(
                        specs_lc, ["base", "основ", "clock", "frequency", "честота"]
                    )
                    if spec_base:
                        base = _try_extract_from(
                            spec_base, [r"([0-9]+(?:[\.,][0-9]+)?)"]
                        )
                        if base:
                            try:
                                final["base_clock"] = float(str(base).replace(",", "."))
                            except Exception:
                                pass
                    if final.get("base_clock") is None:
                        base = _try_extract(
                            raw,
                            [
                                r"([0-9]+(?:[\.,][0-9]+)?)\s*[Gg][Hh]z",
                                r"Base\s*clock[:\s]+([0-9]+(?:[\.,][0-9]+)?)",
                            ]
                        )
                        if base:
                            try:
                                final["base_clock"] = float(str(base).replace(",", "."))
                            except Exception:
                                pass

                if final.get("boost_clock") is None:
                    spec_boost = _spec_value(specs_lc, ["boost", "turbo", "max"])
                    if spec_boost:
                        boost = _try_extract_from(
                            spec_boost, [r"([0-9]+(?:[\.,][0-9]+)?)"]
                        )
                        if boost:
                            try:
                                final["boost_clock"] = float(
                                    str(boost).replace(",", ".")
                                )
                            except Exception:
                                pass
                if final.get("boost_clock") is None:
                    boost = _try_extract(
                        raw,
                        [
                            r"(?:Boost|Turbo)[:\s]*([0-9]+(?:[\.,][0-9]+)?)\s*[Gg][Hh]z",
                            r"up to\s*([0-9]+(?:[\.,][0-9]+)?)\s*[Gg][Hh]z",
                        ]
                    )
                    if boost:
                        try:
                            final["boost_clock"] = float(str(boost).replace(",", "."))
                        except Exception:
                            pass

                if final.get("socket") is None:
                    spec_socket = _spec_value(specs_lc, ["socket", "сокет"])
                    if spec_socket:
                        lower_socket = str(spec_socket).lower()
                        if any(k in lower_socket for k in ("not available", "n/a", "unknown")):
                            socket_unavailable = True
                    socket_val = _extract_socket(spec_socket) if spec_socket else None
                    if not socket_val:
                        socket_val = _extract_socket(search_text)
                    if socket_val:
                        final["socket"] = socket_val
                if final.get("socket") is None:
                    inferred_socket = _infer_socket_from_model(
                        final.get("model") or final.get("name") or ""
                    )
                    if inferred_socket:
                        final["socket"] = inferred_socket

                if final.get("socket") is not None:
                    final["socket"] = _normalize_socket(final.get("socket"))

                brand_upper = str(final.get("brand") or "").upper()
                socket_val = final.get("socket")
                if socket_val:
                    if brand_upper == "INTEL" and socket_val in (
                        "AM4",
                        "AM5",
                        "TR4",
                        "STRX4",
                        "SWRX8",
                    ):
                        final["socket"] = None
                    if brand_upper == "AMD" and str(socket_val).upper().startswith(
                        "LGA"
                    ):
                        final["socket"] = None

                if final.get("socket") is None and final.get("model"):
                    db_socket = get_common_socket_for_model(final.get("model"))
                    if db_socket:
                        final["socket"] = _normalize_socket(db_socket)

                if final.get("memory_type") is None:
                    spec_mem = _spec_value(specs_lc, ["memory", "ram", "памет"])
                    if spec_mem:
                        mem_matches = re.findall(
                            r"(LPDDR\s*\d|DDR\s*\d)", spec_mem, flags=re.IGNORECASE
                        )
                        if mem_matches:
                            seen = []
                            for m in mem_matches:
                                token = m.upper().replace(" ", "")
                                if token not in seen:
                                    seen.append(token)
                            final["memory_type"] = "/".join(seen)
                    mem_matches = re.findall(
                        r"(LPDDR\s*\d|DDR\s*\d)", raw, flags=re.IGNORECASE
                    )
                    if mem_matches:
                        seen = []
                        for m in mem_matches:
                            token = m.upper().replace(" ", "")
                            if token not in seen:
                                seen.append(token)
                        final["memory_type"] = "/".join(seen)
                if isinstance(final.get("memory_type"), str):
                    mem_clean = final.get("memory_type").strip()
                    if not mem_clean or mem_clean.upper() in (
                        "UNKNOWN",
                        "N/A",
                        "NONE",
                        "NULL",
                    ):
                        final["memory_type"] = None

                socket_memory = {
                    "AM4": "DDR4",
                    "AM5": "DDR5",
                    "LGA 1700": "DDR4/DDR5",
                    "LGA 1851": "DDR5",
                    "LGA 1200": "DDR4",
                    "LGA 1151": "DDR4",
                    "LGA 1150": "DDR3",
                    "LGA 2066": "DDR4",
                    "LGA 3647": "DDR4",
                    "LGA 4677": "DDR5",
                    "TR4": "DDR4",
                    "STRX4": "DDR4",
                    "SWRX8": "DDR4",
                }

                if final.get("socket"):
                    socket = str(final["socket"]).upper().strip()
                    expected = socket_memory.get(socket)
                    if expected:
                        if expected in ("DDR4", "DDR5"):
                            if (
                                final.get("memory_type") is None
                                or final.get("memory_type") != expected
                            ):
                                final["memory_type"] = expected
                        else:
                            if final.get("memory_type") is None or final.get(
                                "memory_type"
                            ) in ("DDR4", "DDR5"):
                                final["memory_type"] = expected

                    if final.get("memory_type") is None:
                        db_mem = get_common_memory_type_for_socket(socket)
                        if db_mem:
                            final["memory_type"] = db_mem

                if final.get("socket") is None and final.get("memory_type"):
                    db_socket = get_common_socket_for_memory_type(final["memory_type"])
                    if db_socket:
                        final["socket"] = _normalize_socket(db_socket)

                if final.get("memory_type") is None:
                    model_text = str(final.get("model") or final.get("name") or "")
                    if (
                        re.search(r"\b(7|8|9)\d{3}\b", model_text)
                        and str(final.get("brand") or "").upper() == "AMD"
                    ):
                        final["memory_type"] = "DDR5"

                if final.get("socket") is not None:
                    final["socket"] = _normalize_socket(final.get("socket"))

                if final.get("socket"):
                    socket_norm = str(final["socket"]).upper().strip()
                    expected = socket_memory.get(socket_norm)
                    if expected:
                        mem_val = final.get("memory_type")
                        if isinstance(mem_val, str):
                            mem_clean = mem_val.strip()
                            if not mem_clean or mem_clean.upper() in (
                                "UNKNOWN",
                                "N/A",
                                "NONE",
                                "NULL",
                            ):
                                mem_val = None
                        if mem_val is None:
                            final["memory_type"] = expected
                        elif expected in ("DDR4", "DDR5"):
                            if mem_val != expected:
                                final["memory_type"] = expected
                        else:
                            if mem_val in ("DDR4", "DDR5"):
                                final["memory_type"] = expected

                if socket_unavailable:
                    logger.warning(
                        "Skipping CPU with unavailable socket for %s: %s",
                        url,
                        final.get("model"),
                    )
                    print(
                        f"    ✗ Skipping CPU with unavailable socket for {url}: {final.get('model')}"
                    )
                    skip_upsert = True

                if final.get("socket") is None:
                    logger.warning(
                        "Skipping CPU with missing socket for %s: %s",
                        url,
                        final.get("model"),
                    )
                    print(
                        f"    ✗ Skipping CPU with missing socket for {url}: {final.get('model')}"
                    )
                    skip_upsert = True

                if final.get("cores") is None or final.get("threads") is None:
                    m = re.search(r"(\d+)\s*[Cc]\s*/\s*(\d+)\s*[Tt]", search_text)
                    if not m:
                        m = re.search(r"(\d+)\s*[Cc]\s*(\d+)\s*[Tt]", search_text)
                    if m:
                        try:
                            if final.get("cores") is None:
                                final["cores"] = int(m.group(1))
                            if final.get("threads") is None:
                                final["threads"] = int(m.group(2))
                        except Exception:
                            pass

                if final.get("threads") is None and final.get("cores") is not None:
                    name_upper = str(
                        final.get("name") or final.get("model") or ""
                    ).upper()
                    brand_upper = str(final.get("brand") or "").upper()
                    if brand_upper == "AMD" and "RYZEN" in name_upper:
                        try:
                            final["threads"] = int(final["cores"]) * 2
                        except Exception:
                            pass

                final["price"] = (
                    parsed.get("price")
                    if parsed.get("price") is not None
                    else ai_data.get("price")
                )
                final["url"] = ai_data.get("url") or parsed.get("url") or url

                if "base_clock" in final:
                    final["base_clock"] = _normalize_clock(final.get("base_clock"))
                if "boost_clock" in final:
                    final["boost_clock"] = _normalize_clock(final.get("boost_clock"))

                try:
                    if not skip_upsert:
                        upsert_cpu(final)
                        print(
                            f"    ✓ Upserted: {final.get('model') or final.get('name')}"
                        )
                except Exception as e:
                    logger.exception("DB upsert failed for %s", url)
                    print(f"    ✗ DB upsert error for {url}: {e}")

            except Exception as e:
                logger.exception("Failed to process %s", url)
                print(f"    ✗ Error processing {url}: {e}")

            processed += 1
            await asyncio.sleep(0.6)


def _infer_model_from_url(u: str):
    if not u:
        return None
    slug = u.rstrip("/").split("/")[-1]
    parts = [p for p in slug.split("-") if p]
    lower_parts = [p.lower() for p in parts]
    skip_tokens = {
        "box",
        "tray",
        "wof",
        "mpk",
        "sbx",
        "kit",
        "fan",
        "nofan",
        "no",
        "with",
        "am4",
        "am5",
        "lga1700",
        "lga1851",
    }
    skip_substrings = (
        "box",
        "tray",
        "wof",
        "mpk",
        "sbx",
        "kit",
        "fan",
    )

    def _is_model_token(token: str) -> bool:
        t = token.lower()
        if t in skip_tokens or any(s in t for s in skip_substrings):
            return False

        if re.match(r"^\d{4,5}[a-z]{0,2}$", t):
            return True
        if re.match(r"^\d{4,5}[a-z]\d[a-z]$", t):
            return True
        if t.endswith("x3d") and re.match(r"^\d{4,5}x3d$", t):
            return True
        return False

    if "ryzen" in lower_parts:
        i = lower_parts.index("ryzen")
        if i + 1 < len(parts):
            series = parts[i + 1]
            if series.isdigit():
                for token in parts[i + 2 :]:
                    t = token.lower()
                    if (
                        t in skip_tokens
                        or "ghz" in t
                        or any(s in t for s in skip_substrings)
                    ):
                        continue
                    if _is_model_token(t):
                        return f"Ryzen {series} {t.upper()}"
    if "core" in lower_parts:
        i = lower_parts.index("core")
        if i + 1 < len(parts):
            series = parts[i + 1]
            if series.lower().startswith("i"):
                for token in parts[i + 2 :]:
                    t = token.lower()
                    if (
                        t in skip_tokens
                        or "ghz" in t
                        or any(s in t for s in skip_substrings)
                    ):
                        continue
                    if _is_model_token(t):
                        return f"Core {series.upper()} {t.upper()}"
    return None


def _infer_model_from_text(text: str):
    if not text:
        return None
    lowered = str(text).lower()
    skip_substrings = (
        "box",
        "tray",
        "wof",
        "mpk",
        "sbx",
        "kit",
        "fan",
    )

    def _normalize_suffix(token: str) -> str:
        upper = token.upper()
        m = re.match(r"^(\d{4,5})([A-Z0-9]+)?$", upper)
        if not m:
            return upper
        digits = m.group(1)
        suffix = m.group(2) or ""
        if not suffix:
            return digits
        if suffix == "X3D":
            return digits + suffix

        if 1 <= len(suffix) <= 2:
            return digits + suffix
        return digits

    m = re.search(
        r"ryzen\s+([3579])\s*-?\s*(\d{4,5}x3d|\d{4,5}[a-z]\d[a-z]|\d{4,5}[a-z]{0,2})",
        lowered,
        flags=re.IGNORECASE,
    )
    if m:
        token = _normalize_suffix(m.group(2))
        if any(s in token for s in skip_substrings):
            return None
        return f"Ryzen {m.group(1)} {token.upper()}"
    m = re.search(
        r"core\s+i([3579])\s*-?\s*(\d{4,5}[a-z]{0,2}|\d{4,5}[a-z]\d[a-z])",
        lowered,
        flags=re.IGNORECASE,
    )
    if m:
        token = _normalize_suffix(m.group(2))
        if any(s in token for s in skip_substrings):
            return None
        return f"Core I{m.group(1)} {token.upper()}"
    m = re.search(
        r"core\s+ultra\s+(\d+)\s*-?\s*(\d{3,5}[a-z]{0,2})",
        lowered,
        flags=re.IGNORECASE,
    )
    if m:
        token = _normalize_suffix(m.group(2))
        if any(s in token for s in skip_substrings):
            return None
        return f"Core Ultra {m.group(1)} {token.upper()}"
    m = re.search(
        r"xeon\s+(silver|gold|bronze|platinum)\s+(\d{4,5}[a-z]{0,2})",
        lowered,
        flags=re.IGNORECASE,
    )
    if m:
        token = _normalize_suffix(m.group(2))
        return f"Xeon {m.group(1).title()} {token.upper()}"
    return None


def _extract_opn(text: str):
    if not text:
        return None
    m = re.search(r"\b100-?\d{9}[A-Za-z]{0,4}\b", str(text))
    if not m:
        return None
    opn = m.group(0).upper().replace(" ", "")
    if opn.startswith("100") and "-" not in opn:
        opn = opn[:3] + "-" + opn[3:]
    return opn


def _model_has_packaging(m: str) -> bool:
    if not m:
        return False
    upper = str(m).upper()
    if any(k in upper for k in ("MPK", "WOF", "BOX", "TRAY", "SBX", "KIT")):
        return True
    if re.search(r"\b\d{4,5}[A-Z]{3,}\b", upper) and "X3D" not in upper:
        return True
    if any(k in upper for k in ("PPGA", "SOCKET", "FCLGA", "LGA ")):
        return True
    return False


def _model_is_placeholder(m: str) -> bool:
    if not m:
        return True
    upper = str(m).upper()
    if any(k in upper for k in ("64-BIT", "64 BIT", "PROCESSOR", "CPU")) and not re.search(
        r"\d{4,5}", upper
    ):
        return True
    if "PPGA" in upper and not re.search(r"\d{4,5}", upper):
        return True
    return False


def _normalize_socket(value: str | None):
    if not value:
        return None
    s = str(value).upper().strip()
    if s in ("UNKNOWN", "N/A", "NONE", "NULL", "NOT AVAILABLE"):
        return None

    s = s.replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    if re.match(r"^[0-9]{3,5}$", s):
        return f"LGA {s}"
    if s.startswith("BX") or s.startswith("SR"):
        return None

    if s in ("AM4", "AM5"):
        return s

    m = re.search(r"(FCLGA|LGA)\s*([0-9]{3,5})", s)
    if m:
        return f"LGA {m.group(2)}"
    if "LGA" in s or s.startswith("FCLGA"):
        return None

    if s in ("TR4", "STRX4", "SWRX8", "STRX4", "SWRX8"):
        return s
    return s


def _normalize_model_brand(model: str | None, brand: str | None):
    if not model:
        return None, brand
    m = str(model).strip()

    m = re.sub(r"[\u2010-\u2015\u2212]", "-", m)

    m = m.replace("™", "").replace("®", "")

    m = re.sub(r"\(.*?\)", "", m).strip()

    m = re.sub(r"^(INTEL|AMD)\s+", "", m, flags=re.IGNORECASE).strip()

    m = " ".join(m.split())

    m = re.sub(r"^RYZEN\b", "Ryzen", m, flags=re.IGNORECASE)
    m = re.sub(r"^CORE\b", "Core", m, flags=re.IGNORECASE)

    if re.match(r"^I[3579][-\s]?\d{4,5}[A-Z]{0,3}$", m, flags=re.IGNORECASE):
        m = "Core " + m

    m = re.sub(
        r"^CORE\s+I([3579])[-\s]?(\d{4,5}[A-Z]{0,3})$",
        lambda mo: f"Core i{mo.group(1)}-{mo.group(2).upper()}",
        m,
        flags=re.IGNORECASE,
    )

    if re.search(r"\bULTRA\b", m, flags=re.IGNORECASE) and not re.match(
        r"^CORE\s+ULTRA", m, flags=re.IGNORECASE
    ):
        m = "Core " + m

    m = re.sub(
        r"^(Core\s+Ultra\s+\d+\s+\d{3,5})F$",
        r"\1",
        m,
        flags=re.IGNORECASE,
    )

    m = re.sub(r"^XEON", "Xeon", m, flags=re.IGNORECASE)

    upper = m.upper()
    if upper.startswith("RYZEN") or "THREADRIPPER" in upper:
        brand = "AMD"
    elif (
        upper.startswith("CORE")
        or upper.startswith("XEON")
        or upper.startswith("PENTIUM")
        or upper.startswith("CELERON")
    ):
        brand = "Intel"

    if brand:
        b = str(brand).strip()
        if b.upper() == "INTEL":
            brand = "Intel"
        elif b.upper() == "AMD":
            brand = "AMD"
        else:
            brand = b.title()

    return m, brand


def _normalize_clock(value):
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return value

    if v >= 100:
        return round(v / 1000.0, 3)
    return v


def _infer_socket_from_model(m: str):
    if not m:
        return None
    upper = str(m).upper()
    if "THREADRIPPER" in upper:
        return None
    if "RYZEN" in upper:
        match = re.search(r"(\d{4})", upper)
        if match:
            try:
                series = int(match.group(1))
            except Exception:
                series = None
            if series:
                if series >= 7000:
                    return "AM5"
                if 1000 <= series <= 5999:
                    return "AM4"
    return None


def _is_plausible_model(m: str) -> bool:
    if not m or _model_has_packaging(m) or _model_is_placeholder(m):
        return False
    return bool(re.search(r"\d{3,}", m or ""))


def _try_extract(raw, patterns):
    for p in patterns:
        m = re.search(p, raw, flags=re.IGNORECASE)
        if m:
            if m.lastindex and m.lastindex >= 1:
                return m.group(m.lastindex)
            return m.group(1)
    return None


def _try_extract_from(text, patterns):
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            if m.lastindex and m.lastindex >= 1:
                return m.group(m.lastindex)
            return m.group(1)
    return None


def _spec_value(specs_lc, keys):
    for k, v in specs_lc.items():
        if any(key in k for key in keys):
            return v
    return None


def _extract_socket(text: str):
    if not text:
        return None
    if re.fullmatch(r"\d{3,5}", str(text).strip()):
        return str(text).strip()
    m = re.search(
        r"(AM4|AM5|FCLGA\s*\d{3,5}|LGA\s*1700|LGA\s*1851|LGA\s*1200|LGA\s*1151|LGA\s*1150|LGA\s*2066|LGA\s*3647|LGA\s*4677|TR4|sTRX4|sWRX8)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1).upper().replace(" ", "")

if __name__ == "__main__":
    asyncio.run(run_cpu_pipeline())
