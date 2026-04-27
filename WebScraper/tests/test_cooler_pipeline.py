import asyncio

import pytest

from pipelines.cooler_pipeline import run_cooler_pipeline
import pipelines.cooler_pipeline as cooler_pipeline


class _FakePage:
    async def set_extra_http_headers(self, headers):
        self.headers = headers

    async def goto(self, *args, **kwargs):
        self.gotos = getattr(self, "gotos", [])
        self.gotos.append((args, kwargs))

    async def content(self):
        return "<html></html>"

    async def wait_for_function(self, *args, **kwargs):
        return None


class _FakeBrowser:
    def __init__(self, headless=False):
        self.headless = headless
        self.page = _FakePage()

    async def __aenter__(self):
        return self.page

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run_fake_cooler_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None, ai_error=None):
    captured = []
    urls = ["https://example.com/cooler"]
    collected = False

    async def fake_collect_cooler_urls(page):
        nonlocal collected
        if collected:
            return []
        collected = True
        return urls

    async def fake_get_next_page_button(page, current_page):
        return None

    async def fake_accept_cookies(page):
        return None

    def fake_parse_cooler_page(html, url):
        return parsed_product

    def fake_parse_cooler(source, name, price, url):
        if ai_error is not None:
            raise ai_error
        return ai_data or {}

    def fake_upsert_cooler(final):
        captured.append(dict(final))

    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cooler_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(cooler_pipeline, "collect_cooler_urls", fake_collect_cooler_urls)
    monkeypatch.setattr(cooler_pipeline, "get_next_page_button", fake_get_next_page_button)
    monkeypatch.setattr(cooler_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(cooler_pipeline, "parse_cooler_page", fake_parse_cooler_page)
    monkeypatch.setattr(cooler_pipeline, "parse_cooler", fake_parse_cooler)
    monkeypatch.setattr(cooler_pipeline, "upsert_cooler", fake_upsert_cooler)
    monkeypatch.setattr(cooler_pipeline, "_retry", fake_retry)
    asyncio.run(run_cooler_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured


def _base_cooler_product(**overrides):
    specs = {
        "Модел": "H150i Elite",
        "Тип": "AIO",
        "Сокет": "LGA1700, AM5",
        "Височина": "27 mm",
        "TDP": "250 W",
        "Размер на вентилатора": "120 mm",
        "Брой вентилатори": "3",
        "Шум": "36 dBA",
        "Обороти": "2400 RPM",
    }
    product = {
        "name": "Водно охлаждане Corsair H150i Elite AIO 360mm LGA1700 AM5",
        "brand": "Corsair",
        "brand_source": "name",
        "model": "H150i Elite",
        "price": 299.99,
        "url": "https://example.com/cooler-aio-360",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    product.update(overrides)
    return product


def _air_tower_product(**overrides):
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24 dBA",
        "Обороти": "1500 RPM",
    }
    product = {
        "name": "Охладител Noctua NH-D15 Tower Air Cooler LGA1700 AM5",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-air-tower",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    product.update(overrides)
    return product


def test_standard_aio_360_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, _base_cooler_product(), ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Corsair"
    assert final["model"] == "H150i Elite"
    assert final["cooler_type"] == "AIO"
    assert final["socket_compatibility"] == "LGA1700, AM5"
    assert final["tdp_w"] == 250
    assert final["fan_size_mm"] == 120
    assert final["fan_count"] == 3
    assert final["noise_db"] == 36.0
    assert final["rpm_max"] == 2400


def test_air_tower_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, _air_tower_product(), ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Noctua"
    assert final["model"] == "NH-D15"
    assert final["cooler_type"] == "Air"
    assert final["socket_compatibility"] == "LGA1700, AM5, AM4"
    assert final["cooler_height_mm"] == 165
    assert final["tdp_w"] == 220
    assert final["fan_size_mm"] == 140
    assert final["fan_count"] == 2


def test_thermal_paste_accessory_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Thermal paste Arctic MX-6 4g",
        "brand": "Arctic",
        "brand_source": "name",
        "model": "MX-6",
        "price": 9.99,
        "url": "https://example.com/thermal-paste",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_case_fan_without_heatsink_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Corsair LL120 RGB Case Fan",
        "brand": "Corsair",
        "brand_source": "name",
        "model": "LL120",
        "price": 29.99,
        "url": "https://example.com/case-fan",
        "raw_specs": "Type: Case Fan",
        "specs": {"Тип": "Case Fan"},
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_low_signal_cooler_page_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Some Product With Mystery Warranty Info",
        "brand": "Noctua",
        "brand_source": "breadcrumb",
        "model": "Some Product With Mystery",
        "price": 0.0,
        "url": "https://example.com/low-signal-cooler",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_ai_conflict_does_not_override_deterministic_identity(monkeypatch, tmp_path):
    ai_data = {
        "brand": "Noctua",
        "model": "NH-D15",
        "cooler_type": "Air",
        "socket_compatibility": ["LGA1200"],
        "cooler_height_mm": 165,
        "tdp_w": 220,
        "fan_size_mm": 140,
        "fan_count": 2,
        "noise_db": 24.0,
        "rpm_max": 1500,
        "price": 299.99,
        "url": "https://example.com/cooler-aio-360",
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, _base_cooler_product(), ai_data=ai_data)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Corsair"
    assert final["model"] == "H150i Elite"
    assert final["cooler_type"] == "AIO"
    assert final["socket_compatibility"] == "LGA1700, AM5"
    assert final["tdp_w"] == 250
    assert final["fan_size_mm"] == 120
    assert final["fan_count"] == 3


def test_ai_failure_falls_back_to_deterministic(monkeypatch, tmp_path):
    captured = _run_fake_cooler_pipeline(
        monkeypatch,
        tmp_path,
        _base_cooler_product(),
        ai_error=RuntimeError("mock llm failure"),
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Corsair"
    assert final["model"] == "H150i Elite"
    assert final["cooler_type"] == "AIO"
    assert final["tdp_w"] == 250


def test_bulgarian_vodno_classified_as_aio(monkeypatch, tmp_path):
    specs = {
        "Модел": "H150i Elite",
        "Тип": "Водно",
        "Сокет": "LGA1700, AM5",
        "Височина": "27 mm",
        "TDP": "250 W",
        "Размер на вентилатора": "120 mm",
        "Брой вентилатори": "3",
        "Шум": "36 dBA",
        "Обороти": "250 - 1800 об/мин",
    }
    product = {
        "name": "Водно Corsair H150i Elite 360mm LGA1700 AM5",
        "brand": "Corsair",
        "brand_source": "name",
        "model": "H150i Elite",
        "price": 299.99,
        "url": "https://example.com/cooler-vodno",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["cooler_type"] == "AIO"
    assert final["rpm_max"] == 1800


def test_model_strips_za_procesor_phrase(monkeypatch, tmp_path):
    specs = {
        "Тип": "Air",
        "Сокет": "LGA1700",
        "Височина": "160 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
    }
    product = {
        "name": "Охладител за процесор Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "Охладител за процесор NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-za-procesor",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert "за процесор" not in (final.get("model") or "")
    assert final["model"] == "NH-D15"


def test_bulgarian_oborota_row_fills_rpm_max(monkeypatch, tmp_path):
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24,6 dBA MAX",
        "Оборота в минута": "250 - 1500 RPM",
    }
    product = {
        "name": "Охладител Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-oborota",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["rpm_max"] == 1500
    assert final["noise_db"] == 24.6


def test_sku_spec_model_falls_back_to_name(monkeypatch, tmp_path):
    product = _air_tower_product(
        model="90RC01N2-B0EAY0",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "90RC01N2-B0EAY0"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "90RC01N2-B0EAY0"
    assert "NH-D15" in final["model"]


def test_incomplete_record_skipped(monkeypatch, tmp_path):
    # No cooler_type anywhere - neither in specs nor inferrable from name
    product = {
        "name": "Corsair Something 360",
        "brand": "Corsair",
        "brand_source": "name",
        "model": "Something",
        "price": 199.99,
        "url": "https://example.com/no-type",
        "raw_specs": "Сокет: LGA1700\nTDP: 200 W\n",
        "specs": {
            "Сокет": "LGA1700",
            "TDP": "200 W",
        },
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_hyphen_chain_sku_falls_back_to_name(monkeypatch, tmp_path):
    # R-CH170-BKNPI0D-G-1 has low digit ratio but many hyphens → pipeline rejects.
    product = _air_tower_product(model="R-CH170-BKNPI0D-G-1")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "R-CH170-BKNPI0D-G-1"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "R-CH170-BKNPI0D-G-1"
    assert "NH-D15" in final["model"]


def test_rpm_max_comma_thousands_with_tolerance(monkeypatch, tmp_path):
    # "500 - 2,400 ± 250 RPM" must parse as 2400, not 250.
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24 dBA",
        "Обороти": "500 - 2,400 ± 250 RPM",
    }
    product = {
        "name": "Охладител Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-rpm-tolerance",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["rpm_max"] == 2400


def test_cyrillic_orphan_prefix_stripped(monkeypatch, tmp_path):
    # Cyrillic А- - ACFRE... prefix must be stripped (not Latin A).
    product = _air_tower_product(model="А- - ACFRE00125A")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "А- - ACFRE00125A"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    # Either stored as the cleaned SKU (if name lacks a better alt)
    # or falls back to the product name — never the raw Cyrillic prefix.
    assert "А- -" not in (final["model"] or "")
    assert "- -" not in (final["model"] or "")


def test_socket_only_model_falls_back_to_name(monkeypatch, tmp_path):
    product = _air_tower_product(model="AM4/AM5")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "AM4/AM5"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "AM4/AM5"
    assert "NH-D15" in (final["model"] or "")


def test_underscore_model_falls_back_to_name(monkeypatch, tmp_path):
    product = _air_tower_product(model="AG400_DIGITAL_PLUS")
    product["name"] = "Охладител DeepCool AG400 Tower Air Cooler"
    product["model"] = "AG400_DIGITAL_PLUS"
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "AG400_DIGITAL_PLUS"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert "_" not in (final["model"] or "")
    assert "AG400" in (final["model"] or "")


def test_short_sku_falls_back_to_name(monkeypatch, tmp_path):
    # BW020 — short all-caps with digits, no match in product name.
    product = _air_tower_product(model="BW020")
    product["name"] = "Охладител be quiet! Pure Rock 2 Tower Air Cooler LGA1700"
    product["brand"] = "be quiet!"
    product["model"] = "BW020"
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "BW020"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "BW020"


def test_dot_variant_keeps_generation(monkeypatch, tmp_path):
    product = _air_tower_product(model="NH-D15.G2.CH.BK")
    product["name"] = "Охладител Noctua NH-D15 G2 chromax.black Tower Air Cooler"
    product["model"] = "NH-D15.G2.CH.BK"
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "NH-D15.G2.CH.BK"
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    model = final["model"] or ""
    assert ".CH" not in model and ".BK" not in model
    assert "NH-D15" in model


def test_rpm_max_tilde_range(monkeypatch, tmp_path):
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24 dBA",
        "Обороти": "500~2250RPM±10%",
    }
    product = {
        "name": "Охладител Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-rpm-tilde",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["rpm_max"] == 2250


def test_rpm_max_plus_tolerance_after_range(monkeypatch, tmp_path):
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24 dBA",
        "Обороти": "500-1,800 + 300 RPM",
    }
    product = {
        "name": "Охладител Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-rpm-plus-tolerance",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["rpm_max"] == 1800


def test_rpm_max_parens_annotation(monkeypatch, tmp_path):
    specs = {
        "Модел": "NH-D15",
        "Тип": "Air",
        "Сокет": "LGA1700, AM5, AM4",
        "Височина": "165 mm",
        "TDP": "220 W",
        "Размер на вентилатора": "140 mm",
        "Брой вентилатори": "2",
        "Шум": "24 dBA",
        "Обороти": "650 ~ 2000 RPM (PWM) ± 10%",
    }
    product = {
        "name": "Охладител Noctua NH-D15",
        "brand": "Noctua",
        "brand_source": "name",
        "model": "NH-D15",
        "price": 119.99,
        "url": "https://example.com/cooler-rpm-parens",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_cooler_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["rpm_max"] == 2000
