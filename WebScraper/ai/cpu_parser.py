import json
import os
from ai.prompts import CPU_PROMPT
from ai.loader import load_llm

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = load_llm()
    return _llm


def _prepare_llm_content(content: str) -> str:
    max_chars_env = int(os.environ.get("LLM_INPUT_MAX_CHARS", "6000"))
    n_ctx = int(os.environ.get("LLM_CTX", "2048"))

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
            "socket",
            "cores",
            "threads",
            "ghz",
            "tdp",
            "turbo",
            "boost",
            "cache",
            "ядр",
            "нишки",
            "сокет",
            "гхц",
            "вт",
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


def parse_cpu(html: str, name: str, price: float, url: str) -> dict:
    content = _prepare_llm_content(html)

    if os.environ.get("USE_MOCK_LLM", "false").lower() in ("1", "true", "yes"):

        data = {
            "brand": "Unknown",
            "socket": "Unknown",
            "cores": None,
            "threads": None,
            "base_clock": None,
            "boost_clock": None,
            "tdp": None,
            "memory_type": None,
        }
        data["name"] = name
        data["price"] = price
        data["url"] = url
        return data

    llm = _get_llm()

    def _estimate_prompt_tokens(prompt: str) -> int:
        try:
            if hasattr(llm, "tokenize"):
                return len(llm.tokenize(prompt.encode("utf-8")))
        except Exception:
            pass

        return max(1, len(prompt) // 4)

    def _fit_content_to_ctx(content_text: str, max_tokens: int) -> tuple[str, str]:
        n_ctx = int(os.environ.get("LLM_CTX", "2048"))

        reserved = max(128, int(max_tokens * 1.5))
        budget = max(256, n_ctx - reserved)
        for _ in range(6):
            prompt = CPU_PROMPT.format(content=content_text, name=name, price=price)
            tokens = _estimate_prompt_tokens(prompt)
            if tokens <= budget or len(content_text) <= 400:
                return content_text, prompt
            ratio = budget / max(tokens, 1)
            if ratio >= 0.95:
                new_len = max(400, len(content_text) - 500)
            else:
                new_len = max(400, int(len(content_text) * ratio))
            if new_len >= len(content_text):
                new_len = max(400, len(content_text) - 500)
            content_text = content_text[:new_len]
        prompt = CPU_PROMPT.format(content=content_text, name=name, price=price)
        return content_text, prompt

    raw_response = None
    last_exc = None
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "300"))
    for attempt in range(3):
        try:
            content, prompt = _fit_content_to_ctx(content, max_tokens)
            resp = llm(prompt, max_tokens=max_tokens)
            if isinstance(resp, dict) and "choices" in resp and resp["choices"]:
                raw_response = resp["choices"][0].get("text") or resp["choices"][0].get(
                    "message", {}
                ).get("content")
            else:
                raw_response = str(resp)
            break
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if any(k in msg for k in ("context", "token", "exceed", "too large")):
                if len(content) > 400:
                    content = content[: max(400, len(content) // 2)]
                max_tokens = max(150, int(max_tokens * 0.7))
    if raw_response is None:
        raise RuntimeError("LLM failed to produce a response") from last_exc

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
        matches = re.findall(r"(LPDDR\s*\d|DDR\s*\d)", s)
        if matches:
            seen = []
            for m in matches:
                token = m.replace(" ", "")
                if token not in seen:
                    seen.append(token)
            return "/".join(seen)

        return s.strip()[:32]

    normalized = {
        "brand": data.get("brand") or data.get("manufacturer"),
        "model": data.get("model") or data.get("name"),
        "socket": data.get("socket"),
        "cores": _to_number(data.get("cores") or data.get("core_count")),
        "threads": _to_number(data.get("threads") or data.get("thread_count")),
        "base_clock": _to_number(
            data.get("base_clock")
            or data.get("base_clock_ghz")
            or data.get("base_clock_g")
        ),
        "boost_clock": _to_number(
            data.get("boost_clock")
            or data.get("boost_clock_ghz")
            or data.get("boost_clock_g")
        ),
        "tdp": _to_number(
            data.get("tdp") or data.get("tdp_w") or data.get("tdp_watts")
        ),
        "memory_type": _normalize_memory_type(
            data.get("memory_type")
            or data.get("memory")
            or data.get("ram_type")
            or data.get("memory_support")
        ),
    }

    normalized["name"] = name
    if price not in (None, 0, 0.0):
        normalized["price"] = price
    else:
        normalized["price"] = _to_number(data.get("price")) or price
    normalized["url"] = url

    return normalized
