import asyncio
import pytest
import pipelines.ram_pipeline as ram_pipeline
from pipelines.ram_pipeline import (
    run_ram_pipeline,
    _normalize_model,
    _normalize_brand,
    _normalize_memory_type,
    _extract_memory_amount,
    _extract_memory_speed,
    _extract_form_factor,
    _normalize_speed,
    _normalize_latency,
)

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
    assert _normalize_model("Corsair Vengeance LPX DDR4 3200MHz 16GB (2x8GB) CL16") == "Corsair Vengeance LPX"
    assert _normalize_model("G.Skill Trident Z5 RGB") == "G.Skill Trident Z5 RGB"

def test_normalize_brand():
    assert _normalize_brand("G.SKILL") == "G.SKILL"
    assert _normalize_brand("CORSAIR") == "Corsair"
    assert _normalize_brand("KINGSTON") == "Kingston"

def test_normalize_memory_type():
    assert _normalize_memory_type("DDR4") == "DDR4"
    assert _normalize_memory_type("DDR5-6000") == "DDR5"

def test_extract_memory_amount():
    assert _extract_memory_amount("16GB (2x8GB)") == "2x8GB"
    assert _extract_memory_amount("32GB") == "1x32GB"
    assert _extract_memory_amount("2x16GB") == "2x16GB"

def test_extract_memory_speed():
    assert _extract_memory_speed("DDR4 3200") == 3200
    assert _extract_memory_speed("3600MHz") == 3600
    assert _extract_memory_speed("6000 MT/s") == 6000

def test_extract_form_factor():
    assert _extract_form_factor("SO-DIMM") == "Laptop"
    assert _extract_form_factor("UDIMM") == "PC"
    assert _extract_form_factor("Desktop") == "PC"
    assert _extract_form_factor("Laptop") == "Laptop"

def _run_fake_ram_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None):
    captured = []
    async def fake_collect_ram_urls(page):
        if getattr(fake_collect_ram_urls, "called", False): return []
        fake_collect_ram_urls.called = True
        return ["https://example.com/ram-1"]
    fake_collect_ram_urls.called = False
    async def fake_accept_cookies(page): pass
    async def fake_get_next_page_button(*a): return None
    def fake_parse_ram_page(html, url): return parsed_product
    def fake_parse_ram(source, name, price, url): return ai_data or {}
    def fake_upsert_ram(final): captured.append(final)
    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ram_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(ram_pipeline, "collect_ram_urls", fake_collect_ram_urls)
    monkeypatch.setattr(ram_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(ram_pipeline, "parse_ram_page", fake_parse_ram_page)
    monkeypatch.setattr(ram_pipeline, "parse_ram", fake_parse_ram)
    monkeypatch.setattr(ram_pipeline, "upsert_ram", fake_upsert_ram)
    monkeypatch.setattr(ram_pipeline, "_retry", fake_retry)
    monkeypatch.setattr(ram_pipeline, "get_next_page_button", fake_get_next_page_button)

    asyncio.run(run_ram_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured

def test_ram_pipeline_integration(monkeypatch, tmp_path):
    product = {
        "name": "Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200MHz CL16",
        "brand": "Corsair",
        "model": "Vengeance LPX",
        "price": 80.0,
        "url": "https://example.com/ram-1",
        "specs": {"Type": "DDR4", "Capacity": "16GB (2x8GB)", "Speed": "3200MHz", "Latency": "CL16", "Form Factor": "DIMM"}
    }
    captured = _run_fake_ram_pipeline(monkeypatch, tmp_path, product)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Corsair"
    assert final["memory_type"] == "DDR4"
    assert final["memory_amount"] == "2x8GB"
    assert final["memory_speed_mhz"] == 3200
    assert final["latency"] == "CL16"
    assert final["form_factor"] == "PC"
