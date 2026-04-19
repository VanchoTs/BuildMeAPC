import json
import os

from ai.llm_utils import LLMConfigurationError, get_llm_ctx, run_llm_completion
from ai.prompts import COOLER_PROMPT

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        try:
            from ai.loader import load_llm

            _llm = load_llm()
        except Exception as exc:
            raise LLMConfigurationError(f"Failed to load LLM: {exc}") from exc
    return _llm


def _prepare_llm_content(content: str) -> str:
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
            "cooler",
            "cpu cooler",
            "air cooler",
            "aio",
            "liquid",
            "water cooling",
            "radiator",
            "heatpipe",
            "heatsink",
            "tower",
            "fan",
            "rpm",
            "db",
            "dba",
            "tdp",
            "socket",
            "lga",
            "am4",
            "am5",
            "охладител",
            "водно охлаждане",
            "въздушно",
            "радиатор",
            "вентилатор",
            "оборот",
            "шум",
            "сокет",
            "съвместим",
            "мощност",
            "височина",
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


def parse_cooler(source: str, name: str, price: float, url: str) -> dict:
    content = _prepare_llm_content(source)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):
        return {
            "brand": None,
            "model": None,
            "cooler_type": None,
            "socket_compatibility": [],
            "cooler_height_mm": None,
            "tdp_w": None,
            "fan_size_mm": None,
            "fan_count": None,
            "noise_db": None,
            "rpm_max": None,
            "price": price,
            "url": url,
        }

    llm = _get_llm()
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "384"))
    raw_response = run_llm_completion(
        llm,
        lambda content_text: COOLER_PROMPT.format(
            content=content_text,
            name=name,
            price=price,
            url=url,
        ),
        content,
        max_tokens,
        retries=3,
        min_max_tokens=192,
    )

    start = raw_response.find("{")
    end = raw_response.rfind("}")
    json_text = raw_response[start : end + 1] if start != -1 and end != -1 else raw_response

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
            parsed = json.loads(_repair_json(json_text))
        except Exception as exc:
            try:
                import re

                pairs = re.findall(r'"?(\w+)"?\s*[:=]\s*"?([^,}\]]+)"?', json_text)
                parsed = {k: v.strip() for k, v in pairs}
            except Exception:
                raise RuntimeError("Failed to parse AI output as JSON") from exc

    data = parsed if isinstance(parsed, dict) else {}

    def _to_int(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        import re

        s = str(value).strip().replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        try:
            return int(float(m.group(0)))
        except Exception:
            return None

    def _to_float(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        import re

        s = str(value).strip().replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    sockets = data.get("socket_compatibility")
    if sockets is None:
        sockets = []
    elif not isinstance(sockets, list):
        sockets = [sockets]

    return {
        "brand": data.get("brand"),
        "model": data.get("model"),
        "cooler_type": data.get("cooler_type"),
        "socket_compatibility": sockets,
        "cooler_height_mm": _to_int(data.get("cooler_height_mm")),
        "tdp_w": _to_int(data.get("tdp_w")),
        "fan_size_mm": _to_int(data.get("fan_size_mm")),
        "fan_count": _to_int(data.get("fan_count")),
        "noise_db": _to_float(data.get("noise_db")),
        "rpm_max": _to_int(data.get("rpm_max")),
        "price": price,
        "url": url,
    }
