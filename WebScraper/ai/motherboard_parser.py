import json
import os
import re
from ai.loader import load_llm
from ai.llm_utils import LLMConfigurationError, get_llm_ctx, run_llm_completion
from ai.prompts import MOTHERBOARD_PROMPT

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        try:
            _llm = load_llm()
        except Exception as exc:
            raise LLMConfigurationError(f"Failed to load LLM: {exc}") from exc
    return _llm


def _prepare_llm_content(content: str) -> str:
    max_chars_env = int(os.environ.get("LLM_INPUT_MAX_CHARS", "7000"))
    n_ctx = get_llm_ctx()
    max_chars = min(max_chars_env, max(1200, n_ctx * 3))
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
        selectors = [
            ".specs",
            ".specifications",
            ".tech-specs",
            ".product-specs",
            "#specs",
            "#specifications",
            ".characteristics",
            "#characteristics",
            ".attributes",
            ".params",
            ".product-params",
            ".product-attributes",
            ".description",
            "#description",
            ".product-description",
            ".desc",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    chunks.append(text)
        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True)
            if text:
                chunks.append(text)
        text = "\n".join(chunks or [soup.get_text(" ", strip=True)])
    except Exception:
        text = content
    return text[:max_chars]


def _repair_json(s: str) -> str:
    s = s.replace('""', '"')
    s = re.sub(r"'(\w+)':", r'"\1":', s)
    s = s.replace("'", '"')
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r"(?<!\\)\b([a-zA-Z_][a-zA-Z0-9_]*)\b\s*:", r'"\1":', s)
    return s


def parse_motherboard(html: str, name: str, price: float, url: str) -> dict:
    content = _prepare_llm_content(html)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):
        return {
            "brand": None,
            "model": None,
            "form_factor": None,
            "chipset": None,
            "socket": None,
            "memory_type": None,
            "ram_slots": None,
            "max_ram_speed_mhz": None,
            "max_ram_amount_gb": None,
            "onboard_wifi": None,
            "io_json": None,
            "name": name,
            "price": price,
            "url": url,
        }

    llm = _get_llm()
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "640"))

    def _build_prompt(content_text: str) -> str:
        prompt = MOTHERBOARD_PROMPT
        prompt = prompt.replace("{content}", content_text)
        prompt = prompt.replace("{name}", str(name))
        prompt = prompt.replace("{price}", str(price))
        return prompt

    raw_response = run_llm_completion(
        llm,
        _build_prompt,
        content,
        max_tokens,
        retries=3,
        min_max_tokens=256,
    )

    start = raw_response.find("{")
    end = raw_response.rfind("}")
    json_text = (
        raw_response[start : end + 1] if start != -1 and end != -1 else raw_response
    )

    parsed = None
    try:
        parsed = json.loads(json_text)
    except Exception:
        try:
            parsed = json.loads(_repair_json(json_text))
        except Exception:
            pairs = re.findall(r'"?(\w+)"?\s*[:=]\s*"?([^,}\]]+)"?', json_text)
            parsed = {k: v.strip() for k, v in pairs}

    data = parsed if isinstance(parsed, dict) else {}

    def _to_int(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return int(x)
        m = re.search(r"\d+", str(x))
        return int(m.group(0)) if m else None

    def _normalize_memory_type(x):
        if not x:
            return None
        s = str(x).upper()
        vals = []
        for t in re.findall(r"DDR[3-5]", s):
            if t not in vals:
                vals.append(t)
        if not vals:
            return None
        return "/".join(vals)

    def _normalize_wifi(x):
        if not x:
            return None
        s = str(x).strip()
        upper = s.upper()
        if any(k in upper for k in ("NOT", "NONE", "NO WIFI", "N/A", "НЕ")):
            return "Not present"
        m = re.search(r"WI[ -]?FI\s*(\d(?:E)?)", upper)
        if m:
            ver = m.group(1)
            return f"Wi-Fi {ver}"
        if "WIFI" in upper or "WI-FI" in upper:
            return "Wi-Fi"
        return s

    def _normalize_form_factor(x):
        if not x:
            return None
        s = str(x).upper()
        if "E-ATX" in s:
            return "E-ATX"
        if "XL-ATX" in s:
            return "XL-ATX"
        if "MICRO" in s and "ATX" in s:
            return "mATX"
        if "M-ATX" in s or "MATX" in s:
            return "mATX"
        if "MINI" in s and "ITX" in s:
            return "ITX"
        if "ITX" in s:
            return "ITX"
        if "ATX" in s:
            return "ATX"
        return str(x).strip()

    io_json = data.get("io_json")
    if isinstance(io_json, str):
        try:
            io_json = json.loads(io_json)
        except Exception:
            io_json = None
    if not isinstance(io_json, dict):
        io_json = None

    out = {
        "brand": data.get("brand"),
        "model": data.get("model") or data.get("name"),
        "form_factor": _normalize_form_factor(data.get("form_factor")),
        "chipset": data.get("chipset"),
        "socket": data.get("socket"),
        "memory_type": _normalize_memory_type(data.get("memory_type")),
        "ram_slots": _to_int(data.get("ram_slots")),
        "max_ram_speed_mhz": _to_int(data.get("max_ram_speed_mhz")),
        "max_ram_amount_gb": _to_int(data.get("max_ram_amount_gb")),
        "onboard_wifi": _normalize_wifi(data.get("onboard_wifi")),
        "io_json": io_json,
        "name": name,
        "price": price,
        "url": url,
    }

    return out
