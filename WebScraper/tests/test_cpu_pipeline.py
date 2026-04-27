import asyncio
import pytest
import pipelines.cpu_pipeline as cpu_pipeline
from pipelines.cpu_pipeline import run_cpu_pipeline, _infer_model_from_text, _normalize_model_brand, _normalize_socket

class _FakePage:
    async def set_extra_http_headers(self, headers):
        self.headers = headers
    async def goto(self, *args, **kwargs):
        pass
    async def content(self):
        return "<html></html>"
    async def wait_for_function(self, *args, **kwargs):
        return None
    async def evaluate(self, *args, **kwargs):
        return None
    @property
    def locator(self):
        def _locator(sel):
            return self
        return _locator
    async def count(self):
        return 0
    async def get_attribute(self, attr):
        return None
    @property
    def mouse(self):
        class _Mouse:
            async def wheel(self, x, y): pass
        return _Mouse()
    async def wait_for_load_state(self, *args, **kwargs):
        pass

class _FakeBrowser:
    def __init__(self, headless=False):
        self.page = _FakePage()
    async def __aenter__(self):
        return self.page
    async def __aexit__(self, exc_type, exc, tb):
        return False

def test_infer_model_from_text():
    assert _infer_model_from_text("AMD Ryzen 5 5600X Box") == "Ryzen 5 5600X"
    assert _infer_model_from_text("Intel Core i7-12700K Processor") == "Core I7 12700K"
    assert _infer_model_from_text("AMD Ryzen 7 7800X3D") == "Ryzen 7 7800X3D"
    assert _infer_model_from_text("Intel Core Ultra 7 155H") == "Core Ultra 7 155H"
    assert _infer_model_from_text("Intel Xeon Silver 4210") == "Xeon Silver 4210"

def test_normalize_model_brand():
    m, b = _normalize_model_brand("RYZEN 5 5600X", "AMD")
    assert m == "Ryzen 5 5600X"
    assert b == "AMD"

    m, b = _normalize_model_brand("core i5 12400f", "intel")
    assert m == "Core i5-12400F"
    assert b == "Intel"

    m, b = _normalize_model_brand("I7 13700K", None)
    assert m == "Core i7-13700K"
    assert b == "Intel"

def test_normalize_socket():
    assert _normalize_socket("AM4") == "AM4"
    assert _normalize_socket("LGA1700") == "LGA 1700"
    assert _normalize_socket("1200") == "LGA 1200"
    assert _normalize_socket("FCLGA1200") == "LGA 1200"
    assert _normalize_socket("Unknown") is None

def _run_fake_cpu_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None):
    captured = []
    
    async def fake_collect_cpu_urls(page):
        if getattr(fake_collect_cpu_urls, "called", False): return []
        fake_collect_cpu_urls.called = True
        return ["https://example.com/cpu-1"]
    fake_collect_cpu_urls.called = False

    async def fake_accept_cookies(page): pass
    async def fake_get_next_page_button(*a): return None
    def fake_parse_cpu_page(html, url): return parsed_product
    def fake_parse_cpu(source, name, price, url): return ai_data or {}
    def fake_upsert_cpu(final): captured.append(final)
    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cpu_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(cpu_pipeline, "collect_cpu_urls", fake_collect_cpu_urls)
    monkeypatch.setattr(cpu_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(cpu_pipeline, "parse_cpu_page", fake_parse_cpu_page)
    monkeypatch.setattr(cpu_pipeline, "parse_cpu", fake_parse_cpu)
    monkeypatch.setattr(cpu_pipeline, "upsert_cpu", fake_upsert_cpu)
    monkeypatch.setattr(cpu_pipeline, "_retry", fake_retry)
    monkeypatch.setattr(cpu_pipeline, "get_next_page_button", fake_get_next_page_button)

    asyncio.run(run_cpu_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured

def test_cpu_pipeline_integration(monkeypatch, tmp_path):
    product = {
        "name": "AMD Ryzen 5 5600X",
        "brand": "AMD",
        "model": "5600X",
        "price": 300.0,
        "url": "https://example.com/cpu-1",
        "specs": {"Socket": "AM4", "Cores": "6", "Threads": "12", "TDP": "65W"}
    }
    captured = _run_fake_cpu_pipeline(monkeypatch, tmp_path, product)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "AMD"
    assert "5600X" in final["model"]
    assert final["socket"] == "AM4"
    assert final["cores"] == 6
    assert final["threads"] == 12
    assert final["tdp"] == 65
