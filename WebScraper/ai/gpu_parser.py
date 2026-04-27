import json
import os
from ai.llm_utils import LLMConfigurationError, get_llm_ctx, run_llm_completion
from ai.prompts import GPU_PROMPT
from ai.loader import load_llm

_llm = None


def _get_llm():
    """
    Retrieves and caches the LLM instance using the local loader.
    Raises LLMConfigurationError if the loader fails.
    """
    global _llm
    if _llm is None:
        try:
            _llm = load_llm()
        except Exception as exc:
            raise LLMConfigurationError(f"Failed to load LLM: {exc}") from exc
    return _llm


def _prepare_llm_content(content: str) -> str:
    """
    Prepares HTML content for LLM processing by stripping unnecessary tags
    and selecting relevant specification sections to stay within context limits.
    """
    max_chars_env = int(os.environ.get("LLM_INPUT_MAX_CHARS", "6000"))
    n_ctx = get_llm_ctx()
    max_chars = min(max_chars_env, max(1000, n_ctx * 3))
    if not content:
        return ""
    if len(content) <= max_chars and "<" not in content:
        return content
    if "<" not in content:
        return content[:max_chars]
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()
        chunks = []
        title = soup.select_one(".product-name, .product-title, h1, .name")
        if title:
            chunks.append(title.get_text(" ", strip=True))
        spec_selectors = [
            ".specs",
            ".specifications",
            ".tech-specs",
            ".product-specs",
            "#specs",
            "#specifications",
            "#tech-specs",
            ".characteristics",
            "#characteristics",
            ".attributes",
            "#attributes",
            ".params",
            "#params",
            ".product-params",
            ".product-attributes",
            ".tab-specs",
            ".tab-parameters",
            ".description",
            "#description",
            ".product-description",
            ".desc",
        ]
        for sel in spec_selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    chunks.append(text)
        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True)
            if text:
                chunks.append(text)
        if not chunks:
            chunks.append(soup.get_text(" ", strip=True))
        keywords = (
            "memory",
            "gddr",
            "vram",
            "tdp",
            "power",
            "pcie",
            "interface",
            "mhz",
            "boost",
            "clock",
            "length",
            "mm",
            "bus",
            "бит",
            "памет",
            "честота",
        )
        filtered = []
        for chunk in chunks:
            lowered = chunk.lower()
            if any(k in lowered for k in keywords) or len(chunk) < 800:
                filtered.append(chunk)
        text = "\n".join(filtered or chunks)
    except Exception:
        text = content
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def parse_gpu(html: str, name: str, price: float, url: str) -> dict:
    """
    Parses GPU specifications from HTML content using an LLM.
    
    This function:
    1. Prepares the content by extracting relevant spec text.
    2. Sends the text to the LLM with a specific GPU extraction prompt.
    3. Handles raw LLM response, attempting to extract and repair JSON.
    4. Normalizes the extracted data (clocks, memory types, brands) into a consistent format.
    """
    content = _prepare_llm_content(html)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):
        data = {
            "brand": "Unknown",
            "model": None,
            "pcb_manufacturer": None,
            "pcb_series": None,
            "vram_gb": None,
            "memory_type": None,
            "memory_bus_bit": None,
            "base_clock_mhz": None,
            "boost_clock_mhz": None,
            "tdp": None,
            "interface": None,
        }
        data["name"] = name
        data["price"] = price
        data["url"] = url
        return data

    llm = _get_llm()
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "320"))
    raw_response = run_llm_completion(
        llm,
        lambda content_text: GPU_PROMPT.format(
            content=content_text, name=name, price=price
        ),
        content,
        max_tokens,
        retries=3,
        min_max_tokens=160,
    )

    start = raw_response.find("{")
    end = raw_response.rfind("}")
    json_text = (
        raw_response[start : end + 1] if start != -1 and end != -1 else raw_response
    )

    def _repair_json(s: str) -> str:
        import re

        s = s.replace('""', '"')
        s = re.sub(r"'(\w+)':", r'"\1":', s)
        s = s.replace("'", '"')
        s = re.sub(r",\s*([}\]])", r"\1", s)
        s = re.sub(r"(?<!\\)\b([a-zA-Z_][a-zA-Z0-9_]*)\b\s*:", r'"\1":', s)
        return s

    parsed = None
    try:
        parsed = json.loads(json_text)
    except Exception:
        try:
            repaired = _repair_json(json_text)
            parsed = json.loads(repaired)
        except Exception as e:
            try:
                import re

                pairs = re.findall(r'"?(\w+)"?\s*[:=]\s*"?([^,}\]]+)"?', json_text)
                parsed = {k: v.strip() for k, v in pairs}
            except Exception:
                raise RuntimeError("Failed to parse AI output as JSON") from e

    data = parsed if isinstance(parsed, dict) else {}

    def _to_number(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return x
        s = str(x).strip().replace(",", ".")
        try:
            return int(s)
        except Exception:
            try:
                return float(s)
            except Exception:
                import re

                m = re.search(r"-?\d+(?:\.\d+)?", s)
                if not m:
                    return None
                num = m.group(0)
                try:
                    if "." in num:
                        return float(num)
                    return int(num)
                except Exception:
                    return None

    def _to_clock_mhz(x):
        v = _to_number(x)
        if v is None:
            return None
        if v < 50:
            return float(v) * 1000.0
        return float(v)

    def _normalize_memory_type(value):
        if not value:
            return None
        import re

        s = str(value).upper()
        matches = re.findall(r"(GDDR\s*\dX?|HBM\s*\d?)", s)
        if matches:
            seen = []
            for m in matches:
                token = m.replace(" ", "")
                if token not in seen:
                    seen.append(token)
            return "/".join(seen)
        return s.strip()[:32]

    def _normalize_brand(value):
        if not value:
            return None
        s = str(value).strip().upper()
        if "NVIDIA" in s:
            return "NVIDIA"
        if "AMD" in s or "RADEON" in s:
            return "AMD"
        if "INTEL" in s or "ARC" in s:
            return "Intel"
        return s.title()

    normalized = {
        "brand": _normalize_brand(data.get("brand") or data.get("chip_brand")),
        "model": data.get("model") or data.get("name"),
        "pcb_manufacturer": data.get("pcb_manufacturer")
        or data.get("manufacturer")
        or data.get("aib_partner"),
        "pcb_series": data.get("pcb_series")
        or data.get("series")
        or data.get("aib_series"),
        "vram_gb": _to_number(
            data.get("vram_gb") or data.get("vram") or data.get("memory_size")
        ),
        "memory_type": _normalize_memory_type(
            data.get("memory_type") or data.get("memory")
        ),
        "memory_bus_bit": _to_number(
            data.get("memory_bus_bit") or data.get("memory_bus")
        ),
        "base_clock_mhz": _to_clock_mhz(
            data.get("base_clock_mhz") or data.get("base_clock")
        ),
        "boost_clock_mhz": _to_clock_mhz(
            data.get("boost_clock_mhz") or data.get("boost_clock")
        ),
        "tdp": _to_number(data.get("tdp") or data.get("tdp_w")),
        "interface": data.get("interface"),
    }

    normalized["name"] = name
    if price not in (None, 0, 0.0):
        normalized["price"] = price
    else:
        normalized["price"] = _to_number(data.get("price")) or price
    normalized["url"] = url

    return normalized
