import json
import os

from ai.llm_utils import LLMConfigurationError, get_llm_ctx, run_llm_completion
from ai.prompts import SSD_PROMPT

_llm = None


def _get_llm():
    """
    Retrieves and caches the LLM instance using the local loader.
    """
    global _llm
    if _llm is None:
        try:
            from ai.loader import load_llm

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
            "ssd",
            "nvme",
            "m.2",
            "sata",
            "tbw",
            "nand",
            "read",
            "write",
            "четене",
            "запис",
            "терабайти",
            "интерф",
            "форм",
            "размер",
            "вътрешен",
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


def parse_ssd(html: str, name: str, price: float, url: str) -> dict:
    """
    Parses SSD specifications from HTML content using an LLM.
    
    This function:
    1. Prepares the content by extracting relevant spec text.
    2. Sends the text to the LLM with an SSD extraction prompt.
    3. Handles and repairs JSON output from the AI.
    4. Normalizes capacities, speeds, and TBW values.
    """
    content = _prepare_llm_content(html)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):
        return {
            "brand": None,
            "model": None,
            "type": None,
            "storage_size_gb": None,
            "physical_size": None,
            "read_speed_mbps": None,
            "write_speed_mbps": None,
            "interface": None,
            "tbw_tb": None,
            "nand_type": None,
            "has_heatsink": None,
            "price": price,
            "url": url,
        }

    llm = _get_llm()
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "384"))
    raw_response = run_llm_completion(
        llm,
        lambda content_text: SSD_PROMPT.format(
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

    def _to_bool(value):
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in {"true", "1", "yes", "y"}:
            return True
        if s in {"false", "0", "no", "n"}:
            return False
        return None

    normalized = {
        "brand": data.get("brand"),
        "model": data.get("model"),
        "type": data.get("type"),
        "storage_size_gb": _to_int(data.get("storage_size_gb")),
        "physical_size": data.get("physical_size"),
        "read_speed_mbps": _to_int(data.get("read_speed_mbps")),
        "write_speed_mbps": _to_int(data.get("write_speed_mbps")),
        "interface": data.get("interface"),
        "tbw_tb": _to_int(data.get("tbw_tb")),
        "nand_type": data.get("nand_type"),
        "has_heatsink": _to_bool(data.get("has_heatsink")),
        "price": price,
        "url": url,
    }
    return normalized
