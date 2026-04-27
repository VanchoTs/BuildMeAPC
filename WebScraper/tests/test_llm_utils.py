import pytest

from ai.llm_utils import LLMConfigurationError, fit_content_to_ctx, run_llm_completion
from ai.motherboard_parser import parse_motherboard


class FakeLLM:
    def tokenize(self, data: bytes):
        return data.decode("utf-8").split()

    def __call__(self, prompt, max_tokens=0):
        return {"choices": [{"text": '{"ok": true}'}]}


def test_fit_content_to_ctx_raises_for_prompt_only_overflow(monkeypatch):
    monkeypatch.setenv("LLM_CTX", "120")
    llm = FakeLLM()

    def build_prompt(content):
        return ("token " * 90) + content

    with pytest.raises(LLMConfigurationError, match="n_ctx=120"):
        fit_content_to_ctx(llm, build_prompt, "extra content", 24)


def test_fit_content_to_ctx_trims_content_until_prompt_fits(monkeypatch):
    monkeypatch.setenv("LLM_CTX", "180")
    llm = FakeLLM()
    content = " ".join(["data"] * 200)

    def build_prompt(content_text):
        return ("token " * 60) + content_text

    fitted_content, _, prompt_tokens, n_ctx = fit_content_to_ctx(
        llm, build_prompt, content, 40
    )

    assert len(fitted_content) < len(content)
    assert prompt_tokens + 40 + 64 <= n_ctx


def test_run_llm_completion_returns_completion_text(monkeypatch):
    monkeypatch.setenv("LLM_CTX", "256")
    llm = FakeLLM()

    text = run_llm_completion(
        llm,
        lambda content: f"prompt {content}",
        "short content",
        32,
    )

    assert text == '{"ok": true}'


def test_parse_motherboard_raises_configuration_error_when_prompt_cannot_fit(
    monkeypatch,
):
    monkeypatch.setenv("LLM_CTX", "256")
    monkeypatch.setattr("ai.motherboard_parser._get_llm", lambda: FakeLLM())

    with pytest.raises(LLMConfigurationError, match="n_ctx=256"):
        parse_motherboard("short content", "Board", 100.0, "https://example.com")
