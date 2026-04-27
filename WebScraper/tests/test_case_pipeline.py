import asyncio

import pytest

from pipelines.case_pipeline import run_case_pipeline
import pipelines.case_pipeline as case_pipeline
from scrapers.pic_bg.case_page import parse_case_page


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


def _run_fake_case_pipeline(monkeypatch, tmp_path, parsed_product, ai_data=None, ai_error=None):
    captured = []
    urls = [parsed_product.get("url") or "https://example.com/case"]
    collected = False

    async def fake_collect_case_urls(page):
        nonlocal collected
        if collected:
            return []
        collected = True
        return urls

    async def fake_get_next_page_button(page, current_page):
        return None

    async def fake_accept_cookies(page):
        return None

    def fake_parse_case_page(html, url):
        return parsed_product

    def fake_parse_case(source, name, price, url):
        if ai_error is not None:
            raise ai_error
        return ai_data or {}

    def fake_upsert_case(final):
        captured.append(dict(final))

    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(case_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(case_pipeline, "collect_case_urls", fake_collect_case_urls)
    monkeypatch.setattr(case_pipeline, "get_next_page_button", fake_get_next_page_button)
    monkeypatch.setattr(case_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(case_pipeline, "parse_case_page", fake_parse_case_page)
    monkeypatch.setattr(case_pipeline, "parse_case", fake_parse_case)
    monkeypatch.setattr(case_pipeline, "upsert_case", fake_upsert_case)
    monkeypatch.setattr(case_pipeline, "_retry", fake_retry)
    asyncio.run(run_case_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured


def _base_case_product(**overrides):
    specs = {
        "Физически размер": "Middle Tower",
        "Формат": "ATX, Micro ATX, Mini ITX, E-ATX",
        "Брой на включените вентилатори": "4",
        "Максимална височина на охладителя": "до 180 mm",
        "Максимален размер на gpu": "до 400 mm",
        "Максимален размер на захранването": "до 220 mm",
        "Място за водно охлаждане": "360 mm - Отгоре, 240 mm - Отпред, 120 mm - Отзад",
        "Портове": "2 x USB 3.0, 1 x USB-C, HD Audio",
    }
    product = {
        "name": "Кутия Lian Li LANCOOL 216 Middle Tower Black",
        "brand": "Lian Li",
        "brand_source": "breadcrumb",
        "model": "LANCOOL 216",
        "price": 159.99,
        "url": "https://example.com/case-lancool216",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    product.update(overrides)
    return product


def test_breadcrumb_only_brand_recovery_returns_lian_li():
    html = """
    <html>
      <body>
        <nav>
          <a data-category="Breadcrumb" href="/kutii/c/62">Кутии</a>
          <a data-category="Breadcrumb" data-label="Lian Li" href="/kutii/c/62/filter/brands/Lian-Li">
            <span>Lian Li</span>
          </a>
        </nav>
        <h1>Кутия Lian Li LANCOOL 216 Middle Tower Black</h1>
      </body>
    </html>
    """
    parsed = parse_case_page(html, "https://example.com/lancool-216")
    assert parsed["brand"] == "Lian Li"
    assert parsed["brand_source"] == "breadcrumb"
    assert parsed["model"] is not None
    assert "LANCOOL 216" in parsed["model"]


def test_standard_atx_mid_tower_extracts_core_fields(monkeypatch, tmp_path):
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, _base_case_product(), ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Lian Li"
    assert final["model"] == "LANCOOL 216"
    assert final["case_size"] == "Mid Tower"
    assert final["motherboard_form_factors"] == "ATX, E-ATX, Micro ATX, Mini ITX"
    assert final["included_fans"] == 4
    assert final["max_cpu_cooler_mm"] == 180
    assert final["max_gpu_length_mm"] == 400
    assert final["max_psu_length_mm"] == 220
    assert final["max_radiator_mm"] == 360
    assert final["io_json"] is not None
    assert final["io_json"]["audio"] is True


def test_motherboard_form_factor_normalizes_eatx_to_e_atx(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {**base["specs"], "Формат": "EATX"}
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["motherboard_form_factors"] == "E-ATX"


@pytest.mark.parametrize(
    ("ports_text", "expected_audio", "expected_type_a_count", "expected_type_c_count"),
    [
        ("2 x USB 3.0, 1 x USB-C, HD Audio", True, 2, 1),
        ("1 USB 3.2 (Gen 2) Type-C, 2 USB 3.0, HD Audio", True, 2, 1),
        ("4 x USB 3.0, 2 x USB 2.0, Audio In/Out", True, 6, 0),
        ("1 x USB-C, 2 x USB 3.0, 1 x 3.5mm jack", True, 2, 1),
        ("2 USB 3.2 Type-A, 1 USB 3.2 Type-C, HD Audio", True, 2, 1),
    ],
)
def test_io_json_parses_front_usb_and_audio(
    monkeypatch, tmp_path, ports_text, expected_audio, expected_type_a_count, expected_type_c_count
):
    base = _base_case_product()
    specs = {**base["specs"], "Портове": ports_text}
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io_json = captured[0]["io_json"]
    assert io_json is not None
    assert io_json["audio"] is expected_audio
    type_a_total = sum(p["count"] for p in io_json["usb_ports"] if p["type"] == "Type-A")
    type_c_total = sum(p["count"] for p in io_json["usb_ports"] if p["type"] == "Type-C")
    assert type_a_total == expected_type_a_count
    assert type_c_total == expected_type_c_count


def test_max_radiator_extracts_largest_size(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {
        **base["specs"],
        "Място за водно охлаждане": "480 mm - Отгоре, 360 mm - Отпред, 240 mm - Отзад",
    }
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["max_radiator_mm"] == 480


def test_low_signal_case_page_is_skipped(monkeypatch, tmp_path):
    long_model = (
        "LANCOOL 216 Контакт +49 211 9666 9666 Адрес Example GmbH "
        "Website https://example.com Warranty 2 years Extra Description Text Here"
    )
    product = {
        "name": long_model,
        "brand": "Lian Li",
        "brand_source": "breadcrumb",
        "model": long_model,
        "price": 0.0,
        "url": "https://example.com/low-signal-case",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


@pytest.mark.parametrize(
    ("name", "raw_specs", "specs"),
    [
        ("Power Cord 1.8m", "Дължина: 1.8 м", {"Дължина": "1.8 м"}),
        ("USB-C Cable Type-C to Type-C", "Type-C cable", {}),
        ("Case Standoff Kit", "Brass standoffs", {}),
        ("Dust Filter Pack", "Magnetic dust filters", {}),
        ("Fan Controller 6-channel", "6 PWM channels", {"Channels": "6"}),
    ],
)
def test_non_case_accessory_is_skipped(monkeypatch, tmp_path, name, raw_specs, specs):
    product = {
        "name": name,
        "brand": None,
        "brand_source": None,
        "model": None,
        "price": 19.99,
        "url": "https://example.com/accessory",
        "raw_specs": raw_specs,
        "specs": specs,
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_ai_conflict_does_not_override_deterministic_case_identity(monkeypatch, tmp_path):
    ai_data = {
        "brand": "Corsair",
        "model": "4000D Airflow",
        "case_size": "Full Tower",
        "motherboard_form_factors": "ATX",
        "included_fans": 2,
        "max_cpu_cooler_mm": 170,
        "max_gpu_length_mm": 360,
        "max_psu_length_mm": 200,
        "max_radiator_mm": 280,
        "io_json": {"usb_ports": [], "audio": False},
        "price": 99.99,
        "url": "https://example.com/case-lancool216",
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, _base_case_product(), ai_data=ai_data)
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Lian Li"
    assert final["model"] == "LANCOOL 216"
    assert final["case_size"] == "Mid Tower"
    assert final["motherboard_form_factors"] == "ATX, E-ATX, Micro ATX, Mini ITX"
    assert final["included_fans"] == 4
    assert final["max_cpu_cooler_mm"] == 180
    assert final["max_gpu_length_mm"] == 400
    assert final["max_psu_length_mm"] == 220
    assert final["max_radiator_mm"] == 360


def test_ai_failure_falls_back_to_parser_only_success(monkeypatch, tmp_path):
    captured = _run_fake_case_pipeline(
        monkeypatch,
        tmp_path,
        _base_case_product(),
        ai_error=RuntimeError("mock llm failure"),
    )
    assert len(captured) == 1
    final = captured[0]
    assert final["brand"] == "Lian Li"
    assert final["model"] == "LANCOOL 216"
    assert final["case_size"] == "Mid Tower"
    assert final["max_gpu_length_mm"] == 400


def test_fan_count_ignores_max_capacity_row(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {
        **base["specs"],
        "Брой на включените вентилатори": "3",
        "Максимален брой вентилатори": "8",
    }
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(
        monkeypatch, tmp_path, product, ai_data={"included_fans": 8}
    )
    assert len(captured) == 1
    assert captured[0]["included_fans"] == 3


def test_fan_count_capped_when_ai_returns_max_capacity(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {
        k: v for k, v in base["specs"].items() if "включените вентилатори" not in k.lower()
    }
    specs["Максимален брой вентилатори"] = "8"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(
        monkeypatch, tmp_path, product, ai_data={"included_fans": 8}
    )
    assert len(captured) == 1
    assert captured[0]["included_fans"] is None


def test_fan_count_parenthetical_breakdown_not_double_counted(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {
        **base["specs"],
        "Брой на включените вентилатори": "4 x 120 мм ARGB ( Отпред: 3 x 120 мм ARGB; Отзад: 1 x 120 мм ARGB)",
    }
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["included_fans"] == 4


def test_io_json_ai_garbage_replaced_with_null(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    ai_data = {
        "io_json": {
            "usb_ports": [
                {"type": "Type-A", "count": 0, "version": None},
                {"type": "Type-A", "count": 0, "version": None},
                {"type": "Type-A", "count": 0, "version": None},
                {"type": "Type-A", "count": 0, "version": None},
            ],
            "audio": None,
        }
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data=ai_data)
    assert len(captured) == 1
    assert captured[0]["io_json"] is None


def test_io_json_deterministic_wins_when_ai_returns_garbage(monkeypatch, tmp_path):
    product = _base_case_product()
    ai_data = {
        "io_json": {
            "usb_ports": [{"type": "Type-A", "count": 0, "version": None}],
            "audio": None,
        }
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data=ai_data)
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    assert io["audio"] is True
    assert any(p["count"] > 0 for p in io["usb_ports"])


def test_lighting_kit_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "ASUS TUF Gaming GT502 Horizon ARGB Lighting Kit White",
        "brand": "ASUS",
        "brand_source": "title",
        "model": "GT502 Horizon ARGB Lighting Kit",
        "price": 49.99,
        "url": "https://example.com/lighting-kit",
        "raw_specs": "ARGB Lighting Kit for GT502",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_led_strip_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Corsair LED Strip RGB Extension",
        "brand": "Corsair",
        "brand_source": "title",
        "model": "LED Strip",
        "price": 19.99,
        "url": "https://example.com/led-strip",
        "raw_specs": "LED strip kit for case interior",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_fan_kit_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Lian Li Uni Fan SL120 V2 Fan Kit 3-Pack",
        "brand": "Lian Li",
        "brand_source": "title",
        "model": "Uni Fan SL120 V2 Fan Kit",
        "price": 89.99,
        "url": "https://example.com/fan-kit",
        "raw_specs": "3x 120mm fans with controller",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_near_empty_case_page_rejected_even_with_title_brand(monkeypatch, tmp_path):
    product = {
        "name": "Corsair 3200D RS ARGB Mid Tower Performance Case Black",
        "brand": "Corsair",
        "brand_source": "title",
        "model": "3200D RS ARGB Mid Tower Performance Case",
        "price": 129.99,
        "url": "https://example.com/corsair-3200d",
        "raw_specs": "",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_near_empty_case_page_passes_when_three_strong_fields_populated(monkeypatch, tmp_path):
    specs = {
        "Физически размер": "Middle Tower",
        "Формат": "ATX",
        "Максимален размер на gpu": "до 400 mm",
    }
    product = {
        "name": "Corsair 3200D RS ARGB Mid Tower Performance Case Black",
        "brand": "Corsair",
        "brand_source": "title",
        "model": "3200D RS ARGB",
        "price": 129.99,
        "url": "https://example.com/corsair-3200d-full",
        "raw_specs": "\n".join(f"{k}: {v}" for k, v in specs.items()),
        "specs": specs,
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    assert captured[0]["brand"] == "Corsair"
    assert captured[0]["case_size"] == "Mid Tower"


def test_io_json_aggregates_multiple_usb_spec_rows(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["USB"] = "1 (USB Type C)"
    specs["USB 2.0"] = "1 (USB 2.0 (type A))"
    specs["USB 3.0"] = "2 (USB 3.0 (Type A))"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a_total = sum(p["count"] for p in io["usb_ports"] if p["type"] == "Type-A")
    type_c_total = sum(p["count"] for p in io["usb_ports"] if p["type"] == "Type-C")
    assert type_a_total == 3
    assert type_c_total == 1


def test_io_json_dedups_identical_entries_across_rows(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "2 x USB 3.0"
    specs["USB 3.0"] = "2 x USB 3.0 Type-A"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a_entries = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    assert len(type_a_entries) == 1
    assert type_a_entries[0]["count"] == 2


def test_io_json_dedup_keeps_max_count_on_conflict(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "4 x USB 3.0"
    specs["USB 3.0"] = "2 x USB 3.0 Type-A"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    type_a_entries = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    assert len(type_a_entries) == 1
    assert type_a_entries[0]["count"] == 4


def test_pcie_riser_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Кутия FD Flex 2 PCIe 4.0 x16 White",
        "brand": "Fractal Design",
        "brand_source": "title",
        "model": "FD Flex 2 PCIe 4.0 x16",
        "price": 79.99,
        "url": "https://example.com/fd-flex-2",
        "raw_specs": "PCIe 4.0 x16 riser cable for vertical GPU mount",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_vertical_gpu_mount_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Lian Li O11 Vertical GPU Mount Kit Black",
        "brand": "Lian Li",
        "brand_source": "title",
        "model": "O11 Vertical GPU Mount Kit",
        "price": 59.99,
        "url": "https://example.com/vertical-mount",
        "raw_specs": "Vertical GPU mount bracket",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_flex2_pcie_riser_hard_blocked_even_with_atx_in_specs(monkeypatch, tmp_path):
    product = {
        "name": "Кутия FD Flex 2 PCIe 4.0 x 16 White FD-A-FLX2-002",
        "brand": "Fractal Design",
        "brand_source": "title",
        "model": "FD Flex 2 PCIe 4.0 x 16",
        "price": 69.99,
        "url": "https://example.com/fd-flex-2-pcie",
        "raw_specs": "Съвместим с ATX Mid Tower кутии; PCIe 4.0 riser cable",
        "specs": {"Съвместимост": "ATX Mid Tower"},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_fd_a_flx_sku_hard_blocked(monkeypatch, tmp_path):
    product = {
        "name": "FD-A-FLX2-002 Riser Bracket",
        "brand": "Fractal Design",
        "brand_source": "title",
        "model": "FD-A-FLX2-002",
        "price": 49.99,
        "url": "https://example.com/fd-a-flx2",
        "raw_specs": "ATX compatible",
        "specs": {"form factor": "ATX"},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_riser_cable_accessory_is_skipped(monkeypatch, tmp_path):
    product = {
        "name": "Cooler Master Riser Cable PCIe 4.0 x16 300mm",
        "brand": "Cooler Master",
        "brand_source": "title",
        "model": "Riser Cable PCIe 4.0 x16",
        "price": 49.99,
        "url": "https://example.com/riser-cable",
        "raw_specs": "PCIe 4.0 x16 riser cable",
        "specs": {},
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert captured == []


def test_io_json_aggregates_preserves_audio_from_portove_row(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {**base["specs"], "USB 3.0": "2 x USB 3.0 Type-A"}
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    assert io["audio"] is True
    type_a_entries = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    assert len(type_a_entries) == 1
    assert type_a_entries[0]["count"] == 2


def test_io_json_drops_null_type_c_across_portove_and_usb_rows(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items()}
    specs["Портове"] = "1 x USB 3.0, 1 x USB 3.1 Type-C, HD Audio x 1"
    specs["Аудио жак"] = "1 (3.5 мм мини жак)"
    specs["USB"] = "1 (USB Type C)"
    specs["USB 3.0"] = "1 (USB 3.0 (Type A))"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_c = [p for p in io["usb_ports"] if p["type"] == "Type-C"]
    assert len(type_c) == 1
    assert type_c[0]["version"] is not None
    assert "3.1" in type_c[0]["version"]


def test_io_json_drops_null_type_a_across_portove_and_usb_rows(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items()}
    specs["Портове"] = "1 x USB 3.2 Gen 2 Type-C, 2 x USB 3.0, HD Audio x 1"
    specs["Аудио жак"] = "1 (3.5 мм мини жак)"
    specs["USB 3.0"] = "2 (USB Type-A)"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    assert len(type_a) == 1
    assert type_a[0]["version"] is not None
    assert "3.0" in type_a[0]["version"]
    assert type_a[0]["count"] == 2


def test_io_json_dash_separator_preserves_count(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "2 - USB 3.0 (Internal 3.0 to 2.0 adapter included), HD Audio"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    assert len(type_a) == 1
    assert type_a[0]["count"] == 2
    assert type_a[0]["version"] == "3.0"


def test_low_signal_page_rejected_when_only_ai_populates(monkeypatch, tmp_path):
    product = {
        "name": "Corsair 3200D RS ARGB Mid Tower Performance Case Black",
        "brand": "Corsair",
        "brand_source": "title",
        "model": "3200D RS ARGB",
        "price": 129.99,
        "url": "https://example.com/corsair-3200d-ai-only",
        "raw_specs": "",
        "specs": {},
    }
    ai_data = {
        "case_size": "Mid Tower",
        "motherboard_form_factors": "ATX, Micro ATX, Mini ITX",
        "max_gpu_length_mm": 400,
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data=ai_data)
    assert captured == []


def test_io_json_concatenated_row_preserves_type_c_breakout(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "2 x USB 3.2 1 x 3.5мм комбо жак 1 x USB 3.2 Gen 2x2 Type C"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    ai_data = {
        "io_json": {
            "usb_ports": [{"type": "Type-A", "count": 3, "version": None}],
            "audio": True,
        }
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data=ai_data)
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    ports = io["usb_ports"]
    type_a = [p for p in ports if p["type"] == "Type-A"]
    type_c = [p for p in ports if p["type"] == "Type-C"]
    assert len(type_a) == 1
    assert type_a[0]["count"] == 2
    assert type_a[0]["version"] == "3.2"
    assert len(type_c) == 1
    assert type_c[0]["count"] == 1
    assert type_c[0]["version"] == "3.2 Gen 2x2"


def test_io_json_standalone_type_c_row_counted(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "1 x Type-C\n1 x USB3.1 Gen 1"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    type_c = [p for p in io["usb_ports"] if p["type"] == "Type-C"]
    assert len(type_a) == 1
    assert type_a[0]["count"] == 1
    assert type_a[0]["version"] == "3.1 Gen 1"
    assert len(type_c) == 1
    assert type_c[0]["count"] == 1
    assert type_c[0]["version"] == "3.2"


def test_io_json_standalone_type_c_inline_row_counted(monkeypatch, tmp_path):
    base = _base_case_product()
    specs = {k: v for k, v in base["specs"].items() if k != "Портове"}
    specs["Портове"] = "1 x Type-C 1 x USB3.1 Gen 1"
    product = _base_case_product(
        specs=specs,
        raw_specs="\n".join(f"{k}: {v}" for k, v in specs.items()),
    )
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_a = [p for p in io["usb_ports"] if p["type"] == "Type-A"]
    type_c = [p for p in io["usb_ports"] if p["type"] == "Type-C"]
    assert len(type_a) == 1
    assert type_a[0]["count"] == 1
    assert type_a[0]["version"] == "3.1 Gen 1"
    assert len(type_c) == 1
    assert type_c[0]["count"] == 1
    assert type_c[0]["version"] == "3.2"


def test_io_json_type_c_version_one_from_ai_replaced(monkeypatch, tmp_path):
    product = _base_case_product()
    ai_data = {
        "io_json": {
            "usb_ports": [
                {"type": "Type-C", "count": 1, "version": "1"},
                {"type": "Type-A", "count": 2, "version": "3.0"},
            ],
            "audio": True,
        }
    }
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data=ai_data)
    assert len(captured) == 1
    io = captured[0]["io_json"]
    assert io is not None
    type_c = [p for p in io["usb_ports"] if p["type"] == "Type-C"]
    assert len(type_c) == 1
    assert type_c[0]["version"] == "3.2"


def test_sku_spec_model_falls_back_to_name(monkeypatch, tmp_path):
    product = _base_case_product(model="90RC01N2-B0EAY0")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "90RC01N2-B0EAY0"
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "90RC01N2-B0EAY0"
    assert "LANCOOL 216" in final["model"]


def test_hyphen_chain_sku_falls_back_to_name(monkeypatch, tmp_path):
    # Round 5: hyphen-chain SKU (low digit ratio) must be rejected.
    product = _base_case_product(model="R-CH170-BKNPI0D-G-1")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "R-CH170-BKNPI0D-G-1"
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "R-CH170-BKNPI0D-G-1"
    assert "LANCOOL 216" in final["model"]


def test_color_code_sku_falls_back_to_name(monkeypatch, tmp_path):
    # Round 5: "PA401-TG-BK" (trailing 2-letter color code) must be rejected.
    product = _base_case_product(model="PA401-TG-BK")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "PA401-TG-BK"
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    final = captured[0]
    assert final["model"] != "PA401-TG-BK"
    assert "LANCOOL 216" in final["model"]


def test_cyrillic_orphan_prefix_stripped(monkeypatch, tmp_path):
    # Round 5: Cyrillic А- - must be stripped too.
    product = _base_case_product(model="А- - ACFRE00125A")
    product["specs"] = dict(product["specs"])
    product["specs"]["Модел"] = "А- - ACFRE00125A"
    captured = _run_fake_case_pipeline(monkeypatch, tmp_path, product, ai_data={})
    assert len(captured) == 1
    model = captured[0]["model"] or ""
    assert "А- -" not in model
    assert "- -" not in model
