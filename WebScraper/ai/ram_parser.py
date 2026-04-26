import json
import os
from ai.llm_utils import LLMConfigurationError, get_llm_ctx, run_llm_completion
from ai.prompts import RAM_PROMPT
from ai.loader import load_llm

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
            "ddr",
            "memory",
            "ram",
            "mhz",
            "mt/s",
            "speed",
            "latency",
            "cl",
            "kit",
            "gb",
            "capacity",
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


def parse_ram(html: str, name: str, price: float, url: str) -> dict:
    content = _prepare_llm_content(html)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):
        data = {
            "brand": "Unknown",
            "model": None,
            "memory_type": None,
            "memory_amount": None,
            "memory_speed_mhz": None,
            "latency": None,
            "form_factor": None,
        }
        data["name"] = name
        data["price"] = price
        data["url"] = url
        return data

    llm = _get_llm()
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "320"))
    raw_response = run_llm_completion(
        llm,
        lambda content_text: RAM_PROMPT.format(
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

    def _normalize_memory_type(value):
        if not value:
            return None
        import re

        s = str(value).upper()
        m = re.search(r"DDR[3-5]", s)
        return m.group(0) if m else None

    def _normalize_latency(value):
        if not value:
            return None
        import re

        s = str(value).upper()
        m = re.search(r"CL\s*(\d+)", s)
        if m:
            return f"CL{m.group(1)}"
        return None

    def _normalize_form_factor(value):
        if not value:
            return None
        s = str(value).upper().strip()
        if s == "LAPTOP":
            return "Laptop"
        if s == "PC":
            return "PC"
        if any(k in s for k in ("SO-DIMM", "SODIMM", "LAPTOP", "NOTEBOOK", "260-PIN", "260 PIN", "ЛАПТОП", "НОУТБУК")):
            return "Laptop"
        if any(k in s for k in ("UDIMM", "DIMM", "DESKTOP", "PC", "ДЕСКТОП", "НАСТОЛЕН", "НАСТОЛНИ", "НАСТОЛНА")):
            return "PC"
        return None

    def _normalize_brand(value):
        if not value:
            return None
        s = str(value).strip().upper()
        if s in ("NULL", "NONE", "N/A"):
            return None
        if "G.SKILL" in s or "GSKILL" in s:
            return "G.SKILL"
        if "CORSAIR" in s:
            return "Corsair"
        if "KINGSTON" in s:
            return "Kingston"
        if "ADATA" in s:
            return "ADATA"
        if "XPG" in s or "AXPG" in s:
            return "ADATA"
        if "CRUCIAL" in s:
            return "Crucial"
        if "TEAM" in s and "GROUP" in s:
            return "TeamGroup"
        if s.startswith("TEAM"):
            return "TeamGroup"
        if "PATRIOT" in s:
            return "Patriot"
        if "SAMSUNG" in s:
            return "Samsung"
        if "HYNIX" in s:
            return "SK hynix"
        if "MICRON" in s:
            return "Micron"
        if "HP" in s:
            return "HP"
        if s in ("UNKNOWN", "UNSPECIFIED"):
            return None
        return str(value).title()

    normalized = {
        "brand": _normalize_brand(data.get("brand")),
        "model": data.get("model") or data.get("name"),
        "memory_type": _normalize_memory_type(data.get("memory_type")),
        "memory_amount": data.get("memory_amount") or data.get("capacity"),
        "memory_speed_mhz": _to_number(
            data.get("memory_speed_mhz") or data.get("speed")
        ),
        "latency": _normalize_latency(data.get("latency")),
        "form_factor": _normalize_form_factor(
            data.get("form_factor") or data.get("form") or data.get("device_type")
        ),
    }

    normalized["name"] = name
    if price not in (None, 0, 0.0):
        normalized["price"] = price
    else:
        normalized["price"] = _to_number(data.get("price")) or price
    normalized["url"] = url

    return normalized
