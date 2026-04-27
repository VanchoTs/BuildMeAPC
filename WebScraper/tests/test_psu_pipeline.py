import asyncio

import pytest

from pipelines.psu_pipeline import run_psu_pipeline
import pipelines.psu_pipeline as psu_pipeline
from scrapers.pic_bg.psu_page import parse_psu_page


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


def _run_fake_psu_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None, ai_error=None):
    captured = []
    urls = ["https://example.com/psu"]
    collected = False

    async def fake_collect_psu_urls(page):
        nonlocal collected
        if collected:
            return []
        collected = True
        return urls

    async def fake_get_next_page_button(page, current_page):
        return None

    async def fake_accept_cookies(page):
        return None

    def fake_parse_psu_page(html, url):
        return parsed_product

    def fake_parse_psu(source, name, price, url):
        if ai_error is not None:
            raise ai_error
        return ai_data or {}

    def fake_upsert_psu(final):
        captured.append(dict(final))

    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(psu_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(psu_pipeline, "collect_psu_urls", fake_collect_psu_urls)
    monkeypatch.setattr(psu_pipeline, "get_next_page_button", fake_get_next_page_button)
    monkeypatch.setattr(psu_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(psu_pipeline, "parse_psu_page", fake_parse_psu_page)
    monkeypatch.setattr(psu_pipeline, "parse_psu", fake_parse_psu)
    monkeypatch.setattr(psu_pipeline, "upsert_psu", fake_upsert_psu)
    monkeypatch.setattr(psu_pipeline, "_retry", fake_retry)
    asyncio.run(run_psu_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured


def _base_psu_product(**overrides):
    product = {
        "name": "Захранване MSI MAG A650BN 650W 80 Plus Bronze",
        "brand": "MSI",
        "model": "MAG A650BN",
        "price": 79.99,
        "url": "https://example.com/psu-atx",
        "raw_specs": (
            "Физически размер: ATX\n"
            "Мощност: 650 W\n"
            "Сертификати: 80 Plus Bronze\n"
            "Модулен: Non-Modular\n"
            "Ефективност: 85%\n"
            "Вентилатор: 120 mm\n"
            "Гаранция: 5 years"
        ),
        "specs": {
            "Физически размер": "ATX",
            "Мощност": "650 W",
            "Сертификати": "80 Plus Bronze",
            "Модулен": "Non-Modular",
            "Ефективност": "85%",
            "Вентилатор": "120 mm",
            "Гаранция": "5 years",
        },
    }
    product.update(overrides)
    return product


def _base_modular_psu_product(**overrides):
    product = {
        "name": "Захранване MSI MAG A850GL PCIE5 850W 80 Plus Gold",
        "brand": "MSI",
        "model": "MAG A850GL PCIE5",
        "price": 139.99,
        "url": "https://example.com/psu-modular",
        "raw_specs": (
            "Физически размер: ATX\n"
            "Мощност: 850 W\n"
            "Сертификати: 80 Plus Gold\n"
            "Модулен: Fully Modular\n"
            "Ефективност: 90%\n"
            "ATX стандарт: ATX 3.1\n"
            "PCIe 5.1 Ready: Yes\n"
            "12VHPWR / 12V-2x6: Included\n"
            "Вентилатор: 120 mm\n"
            "Гаранция: 10 years"
        ),
        "specs": {
            "Физически размер": "ATX",
            "Мощност": "850 W",
            "Сертификати": "80 Plus Gold",
            "Модулен": "Fully Modular",
            "Ефективност": "90%",
            "ATX стандарт": "ATX 3.1",
            "PCIe 5.1 Ready": "Yes",
            "12VHPWR / 12V-2x6": "Included",
            "Вентилатор": "120 mm",
            "Гаранция": "10 years",
        },
    }
    product.update(overrides)
    return product


def test_breadcrumb_only_brand_recovery_returns_corsair():
    html = """
    <html>
      <body>
        <nav>
          <a data-category="Breadcrumb" href="/components/c/46">Components</a>
          <a data-category="Breadcrumb" data-label="Corsair" href="/zahranvaniya/c/46/filter/brands/Corsair">
            <span>Corsair</span>
          </a>
        </nav>
        <h1>RM850x SHIFT 850W 80 Plus Gold</h1>
      </body>
    </html>
    """
    parsed = parse_psu_page(html, "https://example.com/rm850x-shift")
    assert parsed["brand"] == "Corsair"
    assert parsed["brand_source"] == "breadcrumb"
    assert parsed["model"] == "RM850x SHIFT"


def test_standard_atx_psu_pipeline_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, _base_psu_product(), ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "MSI"
    assert final["model"] == "MAG A650BN"
    assert final["physical_size"] == "ATX"
    assert final["power_w"] == 650
    assert final["certificate"] == "80 Plus Bronze"
    assert final["modularity"] == "Not modular"
    assert final["efficiency"] == "85%"
    assert final["fan_size_mm"] == 120



@pytest.mark.parametrize(
    ("size_text", "expected"),
    [
        ("SFX", "SFX"),
        ("SFX-L", "SFX-L"),
    ],
)
def test_psu_form_factor_normalizes_sfx_variants(monkeypatch, tmp_path, size_text, expected):
    product = _base_psu_product(
        name=f"Захранване Corsair SF750 750W 80 Plus Platinum {size_text}",
        brand="Corsair",
        model="SF750",
        specs={**_base_psu_product()["specs"], "Физически размер": size_text, "Мощност": "750 W", "Сертификати": "80 Plus Platinum"},
        raw_specs=_base_psu_product()["raw_specs"].replace("Физически размер: ATX", f"Физически размер: {size_text}").replace("Мощност: 650 W", "Мощност: 750 W").replace("Сертификати: 80 Plus Bronze", "Сертификати: 80 Plus Platinum"),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["physical_size"] == expected


@pytest.mark.parametrize(
    ("modularity_value", "expected"),
    [
        ("Fully Modular", "Modular"),
        ("Semi-Modular", "Semi-modular"),
        ("Fixed Cables", "Not modular"),
    ],
)
def test_modularity_wording_normalizes(monkeypatch, tmp_path, modularity_value, expected):
    product = _base_psu_product(
        specs={**_base_psu_product()["specs"], "Модулен": modularity_value},
        raw_specs=_base_psu_product()["raw_specs"].replace("Модулен: Non-Modular", f"Модулен: {modularity_value}"),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["modularity"] == expected


def test_low_signal_psu_page_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "RMx Shift Контакт +49 211 9666 9666 Адрес Example GmbH Website https://example.com Warranty 10 years",
        "brand": "Corsair",
        "brand_source": "breadcrumb",
        "model": "RMx Shift Контакт +49 211 9666 9666 Адрес Example GmbH Website https://example.com Warranty 10 years",
        "price": 0.0,
        "url": "https://example.com/low-signal-psu",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_efficiency_is_kept_separate_from_certificate(monkeypatch, tmp_path):
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, _base_modular_psu_product(), ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["efficiency"] == "90%"
    assert final["certificate"] == "80 Plus Gold"


def test_certificate_without_efficiency_keeps_efficiency_null(monkeypatch, tmp_path):
    product = _base_modular_psu_product(
        specs={k: v for k, v in _base_modular_psu_product()["specs"].items() if k != "Ефективност"},
        raw_specs=_base_modular_psu_product()["raw_specs"].replace("Ефективност: 90%\n", ""),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["efficiency"] is None
    assert captured[0]["certificate"] == "80 Plus Gold"


@pytest.mark.parametrize(
    ("fan_value", "expected_mm"),
    [
        ("120 mm", 120),
        ("140 mm", 140),
    ],
)
def test_fan_size_is_extracted_in_mm(monkeypatch, tmp_path, fan_value, expected_mm):
    product = _base_psu_product(
        specs={**_base_psu_product()["specs"], "Вентилатор": fan_value},
        raw_specs=_base_psu_product()["raw_specs"].replace("Вентилатор: 120 mm", f"Вентилатор: {fan_value}"),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["fan_size_mm"] == expected_mm



@pytest.mark.parametrize(
    ("name", "raw_specs", "specs"),
    [
        ("UPS CyberPower 1000VA", "Тип: UPS", {"Тип": "UPS"}),
        ("Battery Pack for UPS", "Тип: Battery", {"Тип": "Battery"}),
        ("12VHPWR Cable Extension Kit", "Тип: Cable extension", {"Тип": "Cable extension"}),
        ("24-pin ATX Adapter", "Тип: Adapter", {"Тип": "Adapter"}),
        ("PSU Tester Tool", "Тип: Tester", {"Тип": "Tester"}),
    ],
)
def test_non_psu_products_are_skipped(monkeypatch, tmp_path, name, raw_specs, specs):
    product = {
        "name": name,
        "brand": None,
        "model": None,
        "price": 19.99,
        "url": "https://example.com/non-psu",
        "raw_specs": raw_specs,
        "specs": specs,
    }
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_ai_conflict_does_not_override_deterministic_psu_identity(monkeypatch, tmp_path):
    ai_data = {
        "brand": "Corsair",
        "model": "SF750",
        "physical_size": "SFX",
        "power_w": 750,
        "efficiency": None,
        "certificate": "80 Plus Platinum",
        "modularity": "Semi-modular",
        "atx_standard": "ATX 3.0",
        "pcie5_ready": False,
        "has_12vhpwr": False,
        "fan_size_mm": 92,
        "warranty_months": 84,
        "price": 139.99,
        "url": "https://example.com/psu-modular",
    }
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, _base_modular_psu_product(), ai_data=ai_data)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "MSI"
    assert final["model"] == "MAG A850GL PCIE5"
    assert final["physical_size"] == "ATX"
    assert final["power_w"] == 850
    assert final["certificate"] == "80 Plus Gold"
    assert final["modularity"] == "Modular"


@pytest.mark.parametrize(
    ("brand", "model", "expected_brand"),
    [
        ("Segotep", "GP600G", "Segotep"),
        ("GameMax", "VP-500", "GameMax"),
        ("Endorfy", "Vero L5", "Endorfy"),
        ("Xigmatek", "Minotaur", "Xigmatek"),
        ("darkFlash", "G750", "darkFlash"),
        ("Thermalright", "TG-750S", "Thermalright"),
        ("Inter-Tech", "Argus", "Inter-Tech"),
    ],
)
def test_new_brand_passes_through_pipeline(monkeypatch, tmp_path, brand, model, expected_brand):
    product = _base_psu_product(
        name=f"Захранване {brand} {model} 650W 80 Plus Bronze",
        brand=brand,
        model=model,
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["brand"] == expected_brand


def test_fan_size_key_before_physical_size_does_not_corrupt_fields(monkeypatch, tmp_path):
    """Fan size spec appearing before physical size in dict must not leak into physical_size."""
    # Intentionally put "Размер на вентилатора" before "Физически размер"
    specs = {
        "Размер на вентилатора": "140 мм",
        "Физически размер": "ATX 3.1",
        "Мощност": "850 W",
        "Сертификация 80 Plus": "80 Plus Gold",
        "Модулен": "Да",
        "Ефективност": "90%",
    }
    product = _base_psu_product(
        name="Захранване Thermalright ATX 3.1 850W Gold KG850",
        brand="Thermalright",
        model="KG850",
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["power_w"] == 850
    assert captured[0]["physical_size"] == "ATX"
    assert captured[0]["fan_size_mm"] == 140


def test_watt_unit_in_power_spec_parses_correctly(monkeypatch, tmp_path):
    """Power value with 'Watt' unit (not just 'W') must be parsed correctly."""
    specs = {
        "Физически размер": "ATX",
        "Мощност": "750 Watt",
        "Сертификация 80 Plus": "80 Plus Gold",
        "Модулен": "Да",
        "Ефективност": "89%",
        "Размер на вентилатора": "140 мм",
    }
    product = _base_psu_product(
        name="Захранване Corsair RM750x Shift 750 Watt ATX 3.1",
        brand="Corsair",
        model="RM750x Shift",
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["power_w"] == 750
    assert captured[0]["fan_size_mm"] == 140


def test_fan_size_extracted_from_cooling_key(monkeypatch, tmp_path):
    """'Охлаждане' key (Cooling) with fan value must be recognized as the fan size source."""
    specs = {
        "Физически размер": "ATX",
        "Мощност": "850 W",
        "Сертификация 80 Plus": "80 Plus Gold",
        "Модулен": "Да",
        "Ефективност": "90%",
        "Охлаждане": "120 mm вентилатор",
    }
    product = _base_psu_product(
        name="Захранване ASUS TUF Gaming 850G 850W",
        brand="ASUS",
        model="TUF Gaming 850G",
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["fan_size_mm"] == 120


def test_certificate_lookup_prefers_80_plus_over_generic_sertifikati(monkeypatch, tmp_path):
    """When 'Сертификати' (generic, e.g. PCIe 5.1) appears before 'Сертификация 80 Plus',
    the 80 Plus value must still win — lookup priority is by needle order, not dict order."""
    specs = {
        "Физически размер": "ATX",
        "Мощност": "850 W",
        "Сертификати": "PCIe 5.1",  # noise appears first
        "Сертификация 80 Plus": "80 Plus Gold",  # real cert appears second
        "Модулен": "Да",
        "Ефективност": "90%",
        "Вентилатор": "120 mm",
    }
    product = _base_psu_product(
        name="Захранване Corsair RM850x 850W 80 Plus Gold",
        brand="Corsair",
        model="RM850x",
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["certificate"] == "80 Plus Gold"


def test_ai_failure_falls_back_to_parser_only_success(monkeypatch, tmp_path):
    captured = _run_fake_psu_pipeline(
        monkeypatch,
        tmp_path,
        _base_psu_product(),
        ai_error=RuntimeError("mock llm failure"),
    )
    assert len(captured) == 1
    assert captured[0]["brand"] == "MSI"
    assert captured[0]["power_w"] == 650
    assert captured[0]["certificate"] == "80 Plus Bronze"


def test_sku_spec_model_falls_back_to_name(monkeypatch, tmp_path):
    product = _base_psu_product(
        name="Захранване Corsair RM850x 850W 80 Plus Gold",
        model="90RC01N2-B0EAY0",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "90RC01N2-B0EAY0"
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["model"] != "90RC01N2-B0EAY0"
    assert "RM850x" in captured[0]["model"]


def test_voltage_spec_dump_cleaned(monkeypatch, tmp_path):
    product = _base_psu_product(
        name="Захранване Trendsonic ADK-A600W 600W",
        model="115/230V ADK-A600W/120MM/450MM_WITHOUT_CABLE",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "115/230V ADK-A600W/120MM/450MM_WITHOUT_CABLE"
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["model"] == "ADK-A600W"


def test_power_supply_ac_prefix_cleaned(monkeypatch, tmp_path):
    # Round 5: "Power Supply AC 115/230V …" must clean down to "ADK-A600W".
    product = _base_psu_product(
        name="Захранване Trendsonic ADK-A600W 600W",
        model="Power Supply AC 115/230V ADK-A600W/120MM/450MM_WITHOUT_CABLE",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "Power Supply AC 115/230V ADK-A600W/120MM/450MM_WITHOUT_CABLE"
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["model"] == "ADK-A600W"


def test_hyphen_chain_sku_falls_back_to_name(monkeypatch, tmp_path):
    # Round 5: R-PN750D-FC0B-EU has low digit ratio but 3 hyphens → rejected.
    product = _base_psu_product(
        name="Захранване Corsair RM750e 750W",
        model="R-PN750D-FC0B-EU",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "R-PN750D-FC0B-EU"
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    model = captured[0]["model"] or ""
    assert model != "R-PN750D-FC0B-EU"
    assert "RM750e" in model


def test_cyrillic_orphan_prefix_stripped(monkeypatch, tmp_path):
    # Round 5: Cyrillic А- - must be stripped too.
    product = _base_psu_product(
        name="А- - ACFRE00125A",
        model="А- - ACFRE00125A",
    )
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "А- - ACFRE00125A"
    captured = _run_fake_psu_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    model = captured[0]["model"] or ""
    assert "А- -" not in model
    assert "- -" not in model
