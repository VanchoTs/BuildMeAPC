import asyncio

import pytest

from pipelines.ssd_pipeline import run_ssd_pipeline
import pipelines.ssd_pipeline as ssd_pipeline
from scrapers.pic_bg.ssd_page import parse_ssd_page


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


def _run_fake_ssd_pipeline(
    monkeypatch,
    tmp_path,
    parsed_product,
    ai_data=None,
    ai_error=None,
):
    captured = []
    urls = ["https://example.com/ssd"]
    collected = False

    async def fake_collect_ssd_urls(page):
        nonlocal collected
        if collected:
            return []
        collected = True
        return urls

    async def fake_get_next_page_button(page, current_page):
        return None

    async def fake_accept_cookies(page):
        return None

    def fake_parse_ssd_page(html, url):
        return parsed_product

    def fake_parse_ssd(source, name, price, url):
        if ai_error is not None:
            raise ai_error
        return ai_data or {}

    def fake_upsert_ssd(final):
        captured.append(dict(final))

    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ssd_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(ssd_pipeline, "collect_ssd_urls", fake_collect_ssd_urls)
    monkeypatch.setattr(ssd_pipeline, "get_next_page_button", fake_get_next_page_button)
    monkeypatch.setattr(ssd_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(ssd_pipeline, "parse_ssd_page", fake_parse_ssd_page)
    monkeypatch.setattr(ssd_pipeline, "parse_ssd", fake_parse_ssd)
    monkeypatch.setattr(ssd_pipeline, "upsert_ssd", fake_upsert_ssd)
    monkeypatch.setattr(ssd_pipeline, "_retry", fake_retry)
    asyncio.run(run_ssd_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured


def _base_sata_product(**overrides):
    product = {
        "name": "SSD 1TB SSD Samsung 870 EVO MZ-77E1T0B/EU",
        "brand": "Samsung",
        "model": "870 EVO",
        "price": 119.99,
        "url": "https://example.com/sata-ssd",
        "raw_specs": (
            "Серия: 870 EVO\n"
            "Размер: 1 000 GB (1TB)\n"
            "Физически размер: 2.5\"\n"
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: до 560MB/s\n"
            "Скорост на запис: до 530MB/s\n"
            "Общо записани терабайти (TBW): 600 TB\n"
            "Тип флаш памет: Samsung V-NAND 4bit MLC\n"
            "Интерфейс: SATA III 6Gb/s"
        ),
        "specs": {
            "Серия": "870 EVO",
            "Размер": "1 000 GB (1TB)",
            "Физически размер": '2.5"',
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "до 560MB/s",
            "Скорост на запис": "до 530MB/s",
            "Общо записани терабайти (TBW)": "600 TB",
            "Тип флаш памет": "Samsung V-NAND 4bit MLC",
            "Интерфейс": "SATA III 6Gb/s",
        },
    }
    product.update(overrides)
    return product


def _base_m2_product(**overrides):
    product = {
        "name": "SSD 1TB Crucial P510 PCIe Gen5 NVMe 2280 M.2 CT1000P510SSD8",
        "brand": "Crucial",
        "model": "P510",
        "price": 189.99,
        "url": "https://example.com/m2-ssd",
        "raw_specs": (
            "Серия: P510\n"
            "Размер: 1TB\n"
            "Физически размер: M.2 22x80mm\n"
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: до 11 000 MB/s\n"
            "Скорост на запис: до 9 500 MB/s\n"
            "Общо записани терабайти (TBW): 600 TB\n"
            "Тип на паметта: 3D NAND\n"
            "Интерфейс: NVMe (PCIe Gen 5 x4)"
        ),
        "specs": {
            "Серия": "P510",
            "Размер": "1TB",
            "Физически размер": "M.2 22x80mm",
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "до 11 000 MB/s",
            "Скорост на запис": "до 9 500 MB/s",
            "Общо записани терабайти (TBW)": "600 TB",
            "Тип на паметта": "3D NAND",
            "Интерфейс": "NVMe (PCIe Gen 5 x4)",
        },
    }
    product.update(overrides)
    return product


def test_breadcrumb_only_brand_recovery_returns_synology():
    html = """
    <html>
      <body>
        <nav>
          <a data-category="Breadcrumb" href="/storage/c/80">Storage</a>
          <a data-category="Breadcrumb" href="/filter/brands/synology">NAS SSD</a>
        </nav>
        <h1>SAT5221 960GB 2.5 SSD</h1>
      </body>
    </html>
    """
    parsed = parse_ssd_page(html, "https://example.com/sat5221")
    assert parsed["brand"] == "Synology"
    assert parsed["brand_source"] == "breadcrumb"
    assert parsed["model"] == "SAT5221"


def test_sata_25_ssd_pipeline_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_ssd_pipeline(
        monkeypatch, tmp_path, _base_sata_product(), ai_data={}
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Samsung"
    assert final["model"] == "870 EVO"
    assert final["type"] == "SATA"
    assert final["storage_size_gb"] == 1000
    assert final["physical_size"] == '2.5"'
    assert final["read_speed_mbps"] == 560
    assert final["write_speed_mbps"] == 530
    assert final["interface"] == "SATA III 6Gb/s"
    assert final["tbw_tb"] == 600
    assert final["nand_type"] == "V-NAND"


def test_m2_2280_gen5_pipeline_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_ssd_pipeline(
        monkeypatch, tmp_path, _base_m2_product(), ai_data={}
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Crucial"
    assert final["model"] == "P510"
    assert final["type"] == "M.2"
    assert final["storage_size_gb"] == 1000
    assert final["physical_size"] == "2280"
    assert final["read_speed_mbps"] == 11000
    assert final["write_speed_mbps"] == 9500
    assert final["interface"] == "PCIe Gen 5 x4"
    assert final["tbw_tb"] == 600
    assert final["nand_type"] == "NAND"


def test_ssd_with_heatsink_is_kept_and_marked(monkeypatch, tmp_path):
    product = _base_m2_product(
        name="SSD 1TB Samsung 990 PRO с Heatsink M.2 2280 PCIe 4.0 SSD MZ-V9P1T0CW",
        brand="Samsung",
        model="990 PRO",
        specs={
            "Размер": "1 TB",
            "Физически размер": "M.2 (2280)",
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "7450 MB/s",
            "Скорост на запис": "6900 MB/s",
            "Интерфейс": "PCIe Gen 4.0 x4, NVMe 2.0",
        },
        raw_specs=(
            "Физически размер: M.2 (2280)\n"
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: 7450 MB/s\n"
            "Скорост на запис: 6900 MB/s\n"
            "Интерфейс: PCIe Gen 4.0 x4, NVMe 2.0\n"
            "Размери (Ш × Д × В): 80 × 24.3 × 8.2 mm (с охладител)"
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["has_heatsink"] is True
    assert captured[0]["type"] == "M.2"


def test_internal_flag_keeps_ssd_even_with_external_name_hint(monkeypatch, tmp_path):
    product = _base_sata_product(
        name="External SSD 1TB Samsung 870 EVO MZ-77E1T0B/EU",
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["model"] == "870 EVO"
    assert captured[0]["type"] == "SATA"


@pytest.mark.parametrize(
    ("size_text", "expected_gb"),
    [
        ("512GB", 512),
        ("1TB", 1000),
        ("2TB", 2000),
    ],
)
def test_storage_size_normalizes_to_integer_gb(monkeypatch, tmp_path, size_text, expected_gb):
    product = _base_sata_product(
        name=f"SSD {size_text} Samsung 870 EVO",
        specs={**_base_sata_product()["specs"], "Размер": size_text},
        raw_specs=_base_sata_product()["raw_specs"].replace("1 000 GB (1TB)", size_text),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured[0]["storage_size_gb"] == expected_gb


@pytest.mark.parametrize(
    ("interface_text", "expected_interface"),
    [
        ("SATA III 6Gb/s", "SATA III 6Gb/s"),
        ("PCIe NVMe 5.0 x4", "PCIe Gen 5 x4"),
        ("NVMe (PCIe Gen 5 x4)", "PCIe Gen 5 x4"),
        ("PCI Express 4.0 x4 (NVMe)", "PCIe Gen 4 x4"),
    ],
)
def test_interface_normalization_variants(monkeypatch, tmp_path, interface_text, expected_interface):
    product = _base_m2_product(
        specs={**_base_m2_product()["specs"], "Интерфейс": interface_text},
        raw_specs=_base_m2_product()["raw_specs"].replace(
            "Интерфейс: NVMe (PCIe Gen 5 x4)",
            f"Интерфейс: {interface_text}",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured[0]["interface"] == expected_interface


def test_missing_interface_and_confident_m2_type_defaults_to_pcie(monkeypatch, tmp_path):
    base = _base_m2_product()
    product = _base_m2_product(
        name="SSD 1TB Crucial P510 2280 M.2 CT1000P510SSD8",
        raw_specs=base["raw_specs"].replace("\nИнтерфейс: NVMe (PCIe Gen 5 x4)", ""),
        specs={k: v for k, v in base["specs"].items() if k != "Интерфейс"},
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["type"] == "M.2"
    assert captured[0]["interface"] == "PCIe"


def test_missing_interface_and_confident_sata_type_defaults_to_sata(monkeypatch, tmp_path):
    base = _base_sata_product()
    product = _base_sata_product(
        raw_specs=base["raw_specs"].replace("\nИнтерфейс: SATA III 6Gb/s", ""),
        specs={k: v for k, v in base["specs"].items() if k != "Интерфейс"},
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["type"] == "SATA"
    assert captured[0]["interface"] == "SATA"


def test_low_signal_ssd_page_with_missing_real_data_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "SSD",
        "brand": None,
        "model": None,
        "price": 19.99,
        "url": "https://example.com/low-signal-ssd",
        "raw_specs": "SSD",
        "specs": {"Breadcrumb": "Storage / SSD"},
    }
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_missing_interface_and_unknown_type_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "SSD 1TB SolidDrive X1",
        "brand": None,
        "model": None,
        "price": 89.99,
        "url": "https://example.com/ambiguous-ssd",
        "raw_specs": "Размер: 1TB\nВътрешен/Външен: Вътрешен",
        "specs": {
            "Размер": "1TB",
            "Вътрешен/Външен": "Вътрешен",
        },
    }
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


@pytest.mark.parametrize(
    ("nand_text", "expected_nand"),
    [
        ("Triple-Level Cell", "TLC"),
        ("Samsung V-NAND 3-bit MLC", "V-NAND"),
        ("3D NAND TLC", "TLC"),
        ("NAND Flash", "NAND"),
    ],
)
def test_nand_type_normalization_variants(monkeypatch, tmp_path, nand_text, expected_nand):
    base = _base_sata_product()
    product = _base_sata_product(
        specs={**base["specs"], "Тип флаш памет": nand_text},
        raw_specs=base["raw_specs"].replace(
            "Тип флаш памет: Samsung V-NAND 4bit MLC",
            f"Тип флаш памет: {nand_text}",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["nand_type"] == expected_nand


@pytest.mark.parametrize(
    "product",
    [
        {
            "name": "HDD 2TB Seagate Barracuda",
            "brand": "Seagate",
            "model": "Barracuda",
            "price": 79.99,
            "url": "https://example.com/hdd",
            "raw_specs": "Вътрешен/Външен: Вътрешен\nТип: HDD",
            "specs": {"Вътрешен/Външен": "Вътрешен", "Тип": "HDD"},
        },
        {
            "name": "External SSD 1TB Samsung T7",
            "brand": "Samsung",
            "model": "T7",
            "price": 129.99,
            "url": "https://example.com/external-ssd",
            "raw_specs": "Вътрешен/Външен: Външен\nИнтерфейс: USB-C",
            "specs": {"Вътрешен/Външен": "Външен", "Интерфейс": "USB-C"},
        },
        {
            "name": "SSD enclosure 2.5 USB 3.0",
            "brand": "Generic",
            "model": "Enclosure",
            "price": 12.99,
            "url": "https://example.com/enclosure",
            "raw_specs": "Тип: enclosure",
            "specs": {"Тип": "enclosure"},
        },
        {
            "name": "M.2 SSD adapter PCIe to USB",
            "brand": "Generic",
            "model": "Adapter",
            "price": 14.99,
            "url": "https://example.com/adapter",
            "raw_specs": "Тип: adapter",
            "specs": {"Тип": "adapter"},
        },
        {
            "name": "2.5 SSD bracket",
            "brand": "Generic",
            "model": "Bracket",
            "price": 6.99,
            "url": "https://example.com/bracket",
            "raw_specs": "Тип: bracket",
            "specs": {"Тип": "bracket"},
        },
        {
            "name": "SSD caddy 9.5mm",
            "brand": "Generic",
            "model": "Caddy",
            "price": 9.99,
            "url": "https://example.com/caddy",
            "raw_specs": "Тип: caddy",
            "specs": {"Тип": "caddy"},
        },
        {
            "name": "M.2 SSD heatsink",
            "brand": "Generic",
            "model": "Heatsink",
            "price": 8.99,
            "url": "https://example.com/heatsink-only",
            "raw_specs": "Тип: accessory\nФизически размер: M.2 2280",
            "specs": {"Тип": "accessory", "Физически размер": "M.2 2280"},
        },
    ],
)
def test_invalid_non_ssd_products_are_skipped(monkeypatch, tmp_path, product):
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_ai_conflict_does_not_override_deterministic_type_and_interface(monkeypatch, tmp_path):
    ai_data = {
        "brand": "Samsung",
        "model": "870 EVO",
        "type": "M.2",
        "storage_size_gb": 1000,
        "physical_size": "2280",
        "read_speed_mbps": 7000,
        "write_speed_mbps": 6500,
        "interface": "PCIe Gen 5 x4",
        "tbw_tb": 600,
        "nand_type": "3D NAND",
        "has_heatsink": False,
        "price": 119.99,
        "url": "https://example.com/sata-ssd",
    }
    captured = _run_fake_ssd_pipeline(
        monkeypatch, tmp_path, _base_sata_product(), ai_data=ai_data
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["type"] == "SATA"
    assert final["physical_size"] == '2.5"'
    assert final["interface"] == "SATA III 6Gb/s"
    assert final["read_speed_mbps"] == 560
    assert final["write_speed_mbps"] == 530


def test_ai_failure_falls_back_to_parser_only(monkeypatch, tmp_path):
    captured = _run_fake_ssd_pipeline(
        monkeypatch,
        tmp_path,
        _base_m2_product(),
        ai_error=RuntimeError("LLM failed"),
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["type"] == "M.2"
    assert final["physical_size"] == "2280"
    assert final["interface"] == "PCIe Gen 5 x4"
    assert final["storage_size_gb"] == 1000


def test_internal_drive_row_value_does_not_trigger_external_skip(monkeypatch, tmp_path):
    product = _base_sata_product(
        name='SSD 1TB Samsung 870 EVO 2.5"',
        raw_specs=(
            'Физически размер: 2.5"\n'
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: 560 MB/s\n"
            "Скорост на запис: 530 MB/s"
        ),
        specs={
            "Физически размер": '2.5"',
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "560 MB/s",
            "Скорост на запис": "530 MB/s",
        },
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["type"] == "SATA"


def test_breadcrumb_only_brand_recovery_returns_synology():
    html = """
    <html>
      <body>
        <nav>
          <a data-category="Breadcrumb" href="/ssdta/c/31">SSD</a>
          <a data-category="Breadcrumb" data-label="Synology" href="/ssdta/c/31/filter/brands/Synology">
            <span>Synology</span>
          </a>
        </nav>
        <h1>SSD 3.84TB SAT5221-3840G</h1>
      </body>
    </html>
    """
    parsed = parse_ssd_page(html, "https://example.com/sat5221")
    assert parsed["brand"] == "Synology"
    assert parsed["brand_source"] == "breadcrumb"


def test_low_signal_breadcrumb_ssd_page_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": (
            'SSD 3840 GB 2.5" SATA SSD 7mm SAT5221-3840G Гаранция 60 Месеца '
            "Код На Продукта SAT5221-3840G Месеци Вноска 12 329 37 € / 644 20 Лв. "
            "Контакт +49 211 9666 9666 Адрес Synology Gmbh Grafenberger Allee 295 "
            "40237 Düsseldorf Deutschland"
        ),
        "brand": "Synology",
        "brand_source": "breadcrumb",
        "model": None,
        "price": 329.37,
        "url": "https://example.com/synology-low-signal",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_missing_interface_for_m2_falls_back_to_pcie(monkeypatch, tmp_path):
    product = _base_m2_product(
        name="SSD 1TB Crucial P510 M.2 2280",
        raw_specs=(
            "Серия: P510\n"
            "Размер: 1TB\n"
            "Физически размер: M.2 22x80mm\n"
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: 11000 MB/s\n"
            "Скорост на запис: 9500 MB/s"
        ),
        specs={
            "Серия": "P510",
            "Размер": "1TB",
            "Физически размер": "M.2 22x80mm",
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "11000 MB/s",
            "Скорост на запис": "9500 MB/s",
        },
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured[0]["type"] == "M.2"
    assert captured[0]["interface"] == "PCIe"


def test_missing_interface_for_sata_falls_back_to_sata(monkeypatch, tmp_path):
    product = _base_sata_product(
        name='SSD 1TB Samsung 870 EVO 2.5"',
        raw_specs=(
            "Серия: 870 EVO\n"
            "Размер: 1TB\n"
            'Физически размер: 2.5"\n'
            "Вътрешен/Външен: Вътрешен\n"
            "Скорост на четене: 560 MB/s\n"
            "Скорост на запис: 530 MB/s"
        ),
        specs={
            "Серия": "870 EVO",
            "Размер": "1TB",
            "Физически размер": '2.5"',
            "Вътрешен/Външен": "Вътрешен",
            "Скорост на четене": "560 MB/s",
            "Скорост на запис": "530 MB/s",
        },
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured[0]["type"] == "SATA"
    assert captured[0]["interface"] == "SATA"


def test_missing_interface_and_unknown_type_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "SSD 1TB Mystery Drive",
        "brand": "Samsung",
        "model": "Mystery Drive",
        "price": 99.99,
        "url": "https://example.com/unknown-ssd",
        "raw_specs": "Размер: 1TB\nВътрешен/Външен: Вътрешен",
        "specs": {
            "Размер": "1TB",
            "Вътрешен/Външен": "Вътрешен",
        },
    }
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


@pytest.mark.parametrize(
    ("nand_value", "expected"),
    [
        ("Triple-Level Cell", "TLC"),
        ("Samsung V-NAND 3-bit MLC", "V-NAND"),
        ("3D NAND TLC", "TLC"),
        ("NAND Flash", "NAND"),
    ],
)
def test_nand_normalization_cases(monkeypatch, tmp_path, nand_value, expected):
    product = _base_m2_product(
        specs={**_base_m2_product()["specs"], "Тип на паметта": nand_value},
        raw_specs=_base_m2_product()["raw_specs"].replace("Тип на паметта: 3D NAND", f"Тип на паметта: {nand_value}"),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured[0]["nand_type"] == expected


@pytest.mark.parametrize(
    ("tbw_value", "expected"),
    [
        ("1 PB", 1000),
        ("2 PB", 2000),
        ("4 PB", 4000),
        ("8 PB", 8000),
    ],
)
def test_tbw_pb_values_normalize_to_decimal_tb(monkeypatch, tmp_path, tbw_value, expected):
    base = _base_m2_product()
    product = _base_m2_product(
        specs={**base["specs"], "Общо записани терабайти (TBW)": tbw_value},
        raw_specs=base["raw_specs"].replace(
            "Общо записани терабайти (TBW): 600 TB",
            f"Общо записани терабайти (TBW): {tbw_value}",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["tbw_tb"] == expected


def test_tbw_labeled_value_wins_over_capacity_text(monkeypatch, tmp_path):
    base = _base_m2_product()
    product = _base_m2_product(
        specs={**base["specs"], "Общо записани терабайти (TBW)": "2TB:1200TBW"},
        raw_specs=base["raw_specs"].replace(
            "Общо записани терабайти (TBW): 600 TB",
            "Общо записани терабайти (TBW): 2TB:1200TBW",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["tbw_tb"] == 1200


def test_tbw_grouped_thousands_separator_is_normalized(monkeypatch, tmp_path):
    base = _base_m2_product()
    product = _base_m2_product(
        specs={**base["specs"], "Общо записани терабайти (TBW)": "1,480TB"},
        raw_specs=base["raw_specs"].replace(
            "Общо записани терабайти (TBW): 600 TB",
            "Общо записани терабайти (TBW): 1,480TB",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["tbw_tb"] == 1480


@pytest.mark.parametrize(
    ("nand_value", "expected"),
    [
        ("QLC NAND", "QLC"),
        ("Quad-level cell (QLC)", "QLC"),
        ("Single-Level Cell", "SLC"),
        ("NAND TLC", "TLC"),
        ("3D multi-level cell (MLC)", "MLC"),
        ("3D NAND flash", "NAND"),
        ("3D NAND Flash", "NAND"),
        ("3D NAND", "NAND"),
    ],
)
def test_nand_cell_type_variants_normalize_to_canonical_form(monkeypatch, tmp_path, nand_value, expected):
    base = _base_m2_product()
    product = _base_m2_product(
        specs={**base["specs"], "Тип на паметта": nand_value},
        raw_specs=base["raw_specs"].replace(
            "Тип на паметта: 3D NAND",
            f"Тип на паметта: {nand_value}",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["nand_type"] == expected


@pytest.mark.parametrize("nand_value", ["NVMe M.2", "NVMe"])
def test_non_nand_placeholder_value_is_cleared(monkeypatch, tmp_path, nand_value):
    base = _base_m2_product()
    product = _base_m2_product(
        specs={**base["specs"], "Тип на паметта": nand_value},
        raw_specs=base["raw_specs"].replace(
            "Тип на паметта: 3D NAND",
            f"Тип на паметта: {nand_value}",
        ),
    )
    captured = _run_fake_ssd_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["nand_type"] is None
