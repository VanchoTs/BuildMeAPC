import asyncio
import pytest
import pipelines.gpu_pipeline as gpu_pipeline
from pipelines.gpu_pipeline import run_gpu_pipeline, _normalize_model, _normalize_brand, _normalize_interface

class _FakePage:
    async def set_extra_http_headers(self, headers): pass
    async def goto(self, *args, **kwargs): pass
    async def content(self): return "<html></html>"
    async def wait_for_function(self, *args, **kwargs): return None
    async def evaluate(self, *args, **kwargs): return None
    @property
    def locator(self):
        def _locator(sel): return self
        return _locator
    async def count(self): return 0
    async def get_attribute(self, attr): return None
    @property
    def mouse(self):
        class _Mouse:
            async def wheel(self, x, y): pass
        return _Mouse()
    async def wait_for_load_state(self, *args, **kwargs): pass

class _FakeBrowser:
    def __init__(self, headless=False): self.page = _FakePage()
    async def __aenter__(self): return self.page
    async def __aexit__(self, exc_type, exc, tb): return False

def test_normalize_model():
    assert _normalize_model("RTX 4070 Ti Super") == "RTX 4070 Ti Super"
    assert _normalize_model("Radeon RX 7800 XT") == "Radeon RX 7800 XT"
    assert _normalize_model("Arc A770") == "Arc A770"
    assert _normalize_model("GTX 1660 Ti") == "GeForce GTX 1660 Ti"
    assert _normalize_model("N4070") == "GeForce RTX 4070"

def test_normalize_brand():
    assert _normalize_brand("NVIDIA") == "NVIDIA"
    assert _normalize_brand("ASUS") == "Asus"
    assert _normalize_brand("MSI") == "Msi"
    assert _normalize_brand("AMD") == "AMD"

def test_normalize_interface():
    assert _normalize_interface("PCIe 4.0 x16") == "PCIe 4.0"
    assert _normalize_interface("PCI Express 3.0") == "PCIe 3.0"
    assert _normalize_interface("PCI-E Gen 4") == "PCIe 4.0"

def _run_fake_gpu_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None):
    captured = []
    async def fake_collect_gpu_urls(page):
        if getattr(fake_collect_gpu_urls, "called", False): return []
        fake_collect_gpu_urls.called = True
        return ["https://example.com/gpu-1"]
    fake_collect_gpu_urls.called = False
    async def fake_accept_cookies(page): pass
    async def fake_get_next_page_button(*a): return None
    def fake_parse_gpu_page(html, url): return parsed_product
    def fake_parse_gpu(source, name, price, url): return ai_data or {}
    def fake_upsert_gpu(final): captured.append(final)
    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gpu_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(gpu_pipeline, "collect_gpu_urls", fake_collect_gpu_urls)
    monkeypatch.setattr(gpu_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(gpu_pipeline, "parse_gpu_page", fake_parse_gpu_page)
    monkeypatch.setattr(gpu_pipeline, "parse_gpu", fake_parse_gpu)
    monkeypatch.setattr(gpu_pipeline, "upsert_gpu", fake_upsert_gpu)
    monkeypatch.setattr(gpu_pipeline, "_retry", fake_retry)
    monkeypatch.setattr(gpu_pipeline, "get_next_page_button", fake_get_next_page_button)

    asyncio.run(run_gpu_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured

def test_gpu_pipeline_integration(monkeypatch, tmp_path):
    product = {
        "name": "ASUS Dual GeForce RTX 4070 SUPER",
        "brand": "ASUS",
        "model": "RTX 4070 SUPER",
        "price": 1200.0,
        "url": "https://example.com/gpu-1",
        "raw_specs": "Memory: 12GB GDDR6X, Interface: PCIe 4.0, TDP: 220W",
        "specs": {"Memory": "12GB GDDR6X", "Interface": "PCIe 4.0", "TDP": "220W"}
    }
    captured = _run_fake_gpu_pipeline(monkeypatch, tmp_path, product)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "NVIDIA"
    assert "RTX 4070 Super" in final["model"]
    assert final["vram_gb"] == 12
    assert final["memory_type"] == "GDDR6X"
    assert final["interface"] == "PCIe 4.0"
