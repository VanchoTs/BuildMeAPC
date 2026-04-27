import os
from typing import Callable

DEFAULT_LLM_CTX = 8192


class LLMConfigurationError(RuntimeError):
    pass


def get_llm_ctx() -> int:
    """
    Retrieves the LLM context window size from environment variables or defaults to 8192.
    """
    raw = os.environ.get("LLM_CTX")
    try:
        return int(raw) if raw else DEFAULT_LLM_CTX
    except Exception:
        return DEFAULT_LLM_CTX


def estimate_prompt_tokens(llm, prompt: str) -> int:
    """
    Estimates the number of tokens in a prompt.
    Uses the LLM's own tokenizer if available, otherwise falls back to a simple heuristic 
    (characters divided by 4).
    """
    try:
        if hasattr(llm, "tokenize"):
            return len(llm.tokenize(prompt.encode("utf-8")))
    except Exception:
        pass
    return max(1, len(prompt) // 4)


def _format_ctx_error(n_ctx: int, prompt_tokens: int, max_tokens: int, margin: int) -> str:
    """
    Formats a detailed error message when the LLM context is exceeded.
    """
    return (
        "LLM context too small: "
        f"n_ctx={n_ctx}, prompt_tokens={prompt_tokens}, max_tokens={max_tokens}, "
        f"min_required_ctx={prompt_tokens + max_tokens + margin}"
    )


def fit_content_to_ctx(
    llm,
    build_prompt: Callable[[str], str],
    content_text: str,
    max_tokens: int,
    *,
    margin: int = 64,
    max_iterations: int = 12,
) -> tuple[str, str, int, int]:
    """
    Iteratively truncates content to ensure the generated prompt fits within the LLM's context window.
    
    The function performs the following:
    1. Estimates the total tokens required (prompt + max_tokens + margin).
    2. If the total exceeds the LLM context (n_ctx), it calculates a reduction ratio.
    3. Truncates the content_text and repeats until it fits or reaches max_iterations.
    
    Args:
        llm: The LLM instance (used for tokenization).
        build_prompt: A function that takes content and returns the full prompt string.
        content_text: The raw data (e.g., product specs) to be included in the prompt.
        max_tokens: The maximum tokens the LLM is expected to generate in response.
        margin: Buffer tokens to prevent boundary errors.
        max_iterations: Maximum number of truncation attempts.

    Returns:
        A tuple of (truncated_content, full_prompt, estimated_prompt_tokens, n_ctx).
    """
    n_ctx = get_llm_ctx()
    if max_tokens <= 0:
        raise LLMConfigurationError(f"Invalid max_tokens={max_tokens}")
    if max_tokens + margin >= n_ctx:
        raise LLMConfigurationError(
            f"LLM context too small: n_ctx={n_ctx}, max_tokens={max_tokens}, margin={margin}"
        )

    working = content_text or ""
    for _ in range(max_iterations):
        prompt = build_prompt(working)
        prompt_tokens = estimate_prompt_tokens(llm, prompt)
        required_ctx = prompt_tokens + max_tokens + margin
        if required_ctx <= n_ctx:
            return working, prompt, prompt_tokens, n_ctx
        if not working:
            raise LLMConfigurationError(
                _format_ctx_error(n_ctx, prompt_tokens, max_tokens, margin)
            )

        allowed_prompt_tokens = max(1, n_ctx - max_tokens - margin)
        ratio = allowed_prompt_tokens / max(prompt_tokens, 1)
        new_len = int(len(working) * max(0.0, min(0.95, ratio * 0.95)))
        if new_len >= len(working):
            new_len = max(0, len(working) - max(200, len(working) // 4))
        working = working[:new_len].rstrip()

    prompt = build_prompt("")
    prompt_tokens = estimate_prompt_tokens(llm, prompt)
    if prompt_tokens + max_tokens + margin > n_ctx:
        raise LLMConfigurationError(
            _format_ctx_error(n_ctx, prompt_tokens, max_tokens, margin)
        )
    return "", prompt, prompt_tokens, n_ctx


def is_context_error(exc: Exception) -> bool:
    """
    Detects if an exception from the LLM library indicates a context length overflow.
    """
    msg = str(exc).lower()
    return any(
        k in msg for k in ("context", "token", "exceed", "too large", "requested tokens")
    )


def extract_completion_text(resp) -> str:
    """
    Extracts the generated text from various LLM response formats (OpenAI-style or raw string).
    """
    if isinstance(resp, dict) and "choices" in resp and resp["choices"]:
        choice = resp["choices"][0]
        return choice.get("text") or choice.get("message", {}).get("content") or ""
    return str(resp)



def run_llm_completion(
    llm,
    build_prompt: Callable[[str], str],
    content_text: str,
    max_tokens: int,
    *,
    retries: int = 3,
    min_max_tokens: int = 128,
    margin: int = 64,
) -> str:
    """
    Main entry point for AI inference with built-in retry and context-reduction logic.
    
    If a context overflow error is detected, it automatically halves the input 
    and reduces the max_tokens parameter for the next attempt. This ensures 
    robust execution even with varying product specification lengths.
    
    Args:
        llm: The LLM instance to call.
        build_prompt: Function to construct the prompt.
        content_text: Raw content to process.
        max_tokens: Maximum response length.
        retries: Number of attempts before giving up.
        min_max_tokens: Lower bound for response length reduction.
        margin: Token buffer.
        
    Returns:
        The text completion from the LLM.
    """
    working_content = content_text or ""
    current_max_tokens = max_tokens
    last_exc = None

    for _ in range(retries):
        try:
            working_content, prompt, _, _ = fit_content_to_ctx(
                llm,
                build_prompt,
                working_content,
                current_max_tokens,
                margin=margin,
            )
            resp = llm(prompt, max_tokens=current_max_tokens)
            return extract_completion_text(resp)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            last_exc = exc
            if is_context_error(exc):
                prompt = build_prompt(working_content)
                prompt_tokens = estimate_prompt_tokens(llm, prompt)
                if (
                    not working_content
                    or prompt_tokens + current_max_tokens + margin > get_llm_ctx()
                ):
                    raise LLMConfigurationError(
                        _format_ctx_error(
                            get_llm_ctx(), prompt_tokens, current_max_tokens, margin
                        )
                    ) from exc
                if working_content:
                    working_content = working_content[
                        : max(0, len(working_content) // 2)
                    ].rstrip()
                current_max_tokens = max(min_max_tokens, int(current_max_tokens * 0.7))
            else:
                current_max_tokens = max(min_max_tokens, int(current_max_tokens * 0.9))

    raise RuntimeError(f"LLM failed to produce a response: {last_exc}") from last_exc

