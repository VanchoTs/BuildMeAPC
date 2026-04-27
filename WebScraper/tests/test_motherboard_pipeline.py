import asyncio

import pytest

from pipelines.motherboard_pipeline import (
    _extract_ram_slots,
    _extract_io_json,
    _normalize_brand,
    _normalize_chipset,
    _normalize_wifi,
    _normalize_ram_slots,
    _resolve_memory_type,
    run_motherboard_pipeline,
)
import pipelines.motherboard_pipeline as motherboard_pipeline
from scrapers.pic_bg.motherboard_page import parse_motherboard_page


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


def _run_fake_motherboard_pipeline(monkeypatch, tmp_path, parsed_board, ai_data=None):
    captured = []
    urls = ["https://example.com/motherboard"]
    collected = False

    async def fake_collect_motherboard_urls(page):
        nonlocal collected
        if collected:
            return []
        collected = True
        return urls

    async def fake_get_next_page_button(page, current_page):
        return None

    async def fake_accept_cookies(page):
        return None

    def fake_parse_motherboard_page(html, url):
        return parsed_board

    def fake_parse_motherboard(source, name, price, url):
        return ai_data or {}

    def fake_upsert_motherboard(final):
        captured.append(dict(final))

    async def fake_retry(coro_fn, *args, **kwargs):
        kwargs.pop("attempts", None)
        kwargs.pop("delay", None)
        return await coro_fn(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(motherboard_pipeline, "Browser", lambda headless=False: _FakeBrowser(headless=headless))
    monkeypatch.setattr(motherboard_pipeline, "collect_motherboard_urls", fake_collect_motherboard_urls)
    monkeypatch.setattr(motherboard_pipeline, "get_next_page_button", fake_get_next_page_button)
    monkeypatch.setattr(motherboard_pipeline, "accept_cookies", fake_accept_cookies)
    monkeypatch.setattr(motherboard_pipeline, "parse_motherboard_page", fake_parse_motherboard_page)
    monkeypatch.setattr(motherboard_pipeline, "parse_motherboard", fake_parse_motherboard)
    monkeypatch.setattr(motherboard_pipeline, "upsert_motherboard", fake_upsert_motherboard)
    monkeypatch.setattr(motherboard_pipeline, "_retry", fake_retry)
    asyncio.run(run_motherboard_pipeline(headless=False, collect_only=False, page_limit=1))
    return captured


def test_rear_io_clause_case():
    specs = {
        "Портове": (
            "2 x Antenna Mounting Points\n"
            "PS/2 Mouse/Keyboard Port\n"
            "HDMI Port\n"
            "DisplayPort 1.4\n"
            "USB 3.2 Gen1 Type-C Port\n"
            "3 x USB 3.2 Gen1 Type-A Ports\n"
            "2 x USB 2.0 Ports\n"
            "RJ-45 LAN Port\n"
            "HD Audio Jacks: Line in / Front Speaker / Microphone"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["hdmi_ports"] == 1
    assert io["displayport_ports"] == 1
    assert {"count": 1, "type": "Type-C", "version": "3.2 Gen1"} in io["usb_ports"]
    assert {"count": 3, "type": "Type-A", "version": "3.2 Gen1"} in io["usb_ports"]
    assert {"count": 2, "type": "Type-A", "version": "2.0"} in io["usb_ports"]


def test_pcie_physical_slot_case():
    specs = {
        "Слотове": (
            "CPU: PCIe 5.0 x16 Slot (PCIE1), supports x 16 mode;"
            "Chipset: PCIe 3.0 x16 Slot (PCIE2), supports x 4 mode"
        )
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 1, "lane": "x16", "version": "Gen5"} in io["pcie_slots"]
    assert {"count": 1, "lane": "x16", "version": "Gen3"} in io["pcie_slots"]
    assert len(io["pcie_slots"]) == 2


def test_mixed_source_usb_case_uses_rear_only_counts():
    specs = {
        "Портове": (
            "1 x HDMI Port\n"
            "1 x DisplayPort 1.4\n"
            "1 x USB 3.2 Gen2x2 Type-C Port (20 Gb/s)\n"
            "3 x USB 3.2 Gen1 Ports\n"
            "2 x USB 2.0 Ports\n"
            "1 x RJ-45 LAN Port"
        ),
        "USB 2.0": "6 x USB 2.0 (2 Rear, 4 Front)",
        "USB 3.2 Gen 1": "5 x USB 3.2 Gen1 Type-A (3 Rear, 2 Front) 1 x USB 3.2 Gen1 Type-C (Front)",
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 2, "type": "Type-A", "version": "2.0"} in io["usb_ports"]
    assert {"count": 3, "type": "Type-A", "version": "3.2 Gen1"} in io["usb_ports"]
    assert {"count": 1, "type": "Type-C", "version": "3.2 Gen2x2"} in io["usb_ports"]
    assert {"count": 1, "type": "Type-C", "version": "3.2 Gen1"} not in io["usb_ports"]


def test_mixed_source_pcie_case_is_deduped():
    specs = {
        "Слотове": (
            "CPU:;- 1 x PCIe 4.0 x16 Slot (PCIE1), supports x16 mode;"
            "Chipset:;- 1 x PCIe 4.0 x1 Slot (PCIE2);"
            "- 1 x PCIe 4.0 x4 Slot (PCIE3), supports x4 mode;"
            "- 1 x M.2 Socket (Key E), supports type 2230 WiFi/BT PCIe WiFi module"
        ),
        "Разширителни слотове": (
            "1 x PCIe 4.0 x16 1 x PCIe 4.0 x1 1 x PCIe 4.0 x4 "
            "1 x M.2 socket (2230 M.2 Key E slot)"
        ),
        "PCI slots": "1x PCI Express 4.0 x16",
        "PCIe x4": "1",
        "PCIe x16": "1 x PCIe 4.0 x16",
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 1, "lane": "x16", "version": "Gen4"} in io["pcie_slots"]
    assert {"count": 1, "lane": "x1", "version": "Gen4"} in io["pcie_slots"]
    assert {"count": 1, "lane": "x4", "version": "Gen4"} in io["pcie_slots"]
    assert len(io["pcie_slots"]) == 3


def test_m2_split_case_keeps_slot_generations_separate():
    specs = {
        "Storage": (
            "CPU:;- 1 x Blazing M.2 Socket (M2_1\n"
            "Key M)\n"
            "supports type 2260/2280 PCIe Gen5x4 (128 Gb/s) mode;"
            "Chipset:;- 1 x Hyper M.2 Socket (M2_2\n"
            "Key M)\n"
            "supports type 2230/2242/2260/2280 PCIe Gen4x4 (64 Gb/s) mode;"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 1, "version": "Gen4"},
    ]


def test_plural_displayports_are_counted():
    specs = {
        "Портове": "2 x DisplayPorts",
        "Видео": (
            "- 2 x DisplayPorts, supporting a maximum resolution of 4096x2304@60 Hz"
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 2


def test_rear_usb_c_with_displayport_support_counts_as_display_output():
    specs = {
        "Видео": (
            "2 x Intel Thunderbolt 4 connectors (USB4 USB Type-C ports), "
            "supporting DisplayPort and Thunderbolt video outputs"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 2


def test_front_hdmi_connector_is_not_counted_as_rear_hdmi():
    specs = {
        "Видео": (
            "- 1 x front HDMI port, supporting a maximum resolution of 1920x1080@30 Hz"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["hdmi_ports"] is None


def test_m2_clause_with_one_gen5_and_two_gen4_slots():
    specs = {
        "Дисков интерфейс": (
            "CPU:;- 1 x M.2 connector (Socket 3, M key, type 25110/22110/2580/2280 "
            "PCIe 5.0 x4/x2 SSD support) (M2A_CPU);"
            "Chipset:;- 2 x M.2 connectors (Socket 3, M key, type 22110/2280 "
            "PCIe 4.0 x4/x2 SSD support) (M2Q_SB, M2P_SB);"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
    ]


def test_duplicate_m2_rows_do_not_overcount_conflicting_slot_names():
    specs = {
        "Дисков интерфейс": (
            "CPU:;- 1 x M.2 connector (Socket 3, M key, type 25110/22110/2580/2280 "
            "PCIe 5.0 x4/x2 SSD support) (M2A_CPU);"
            "Chipset:;- 2 x M.2 connectors (Socket 3, M key, type 22110/2280 "
            "PCIe 4.0 x4/x2 SSD support) (M2Q_SB, M2P_SB);"
        ),
        "M.2 slot": (
            "2 x M.2 connectors (Socket 3, M key, type 22110/2280 PCIe 4.0 x4/x2 SSD "
            "support) (M2C_SB, M2D_SB), 1 x M.2 connector (Socket 3, M key, type "
            "25110/22110/2580/2280 PCIe 5.0 x4/x2 SSD support)"
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
    ]


def test_pcie_slot_ids_define_exact_three_physical_slots():
    specs = {
        "Слотове": (
            "CPU "
            "- 1 x PCI Express x16 slot, supporting PCIe 5.0 and running at x16 (PCIEX16) "
            "Chipset:;- 1 x PCI Express x16 slot, supporting PCIe 4.0 and running at x4 (PCIEX4) "
            "- 1 x PCI Express x16 slot, supporting PCIe 4.0 and running at x1 (PCIEX1)"
        ),
        "PCIe x4": "1",
        "PCIe x16": "1 x PCIe 5.0 x16 slot",
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 1, "lane": "x16", "version": "Gen5"},
        {"count": 2, "lane": "x16", "version": "Gen4"},
    ]


def test_storage_controller_m2_text_does_not_create_fake_pcie_slots():
    specs = {
        "Storage Controller": (
            "PCI Express 5.0 x4 (1 x M.2) "
            "PCI Express 4.0 x4 (1 x M.2) "
            "PCI Express 4.0 x2 (1 x M.2)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == []
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
    ]


def test_rj45_plus_generic_speed_stays_single_lan_port():
    specs = {
        "Портове": "1 x RJ-45",
        "LAN порт": "10/100/1000 Mbps",
    }
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 1
    assert io["lan_max_speed"] == "1 Gb"


def test_memory_type_falls_back_to_same_chipset_dominant_value():
    memory_type = _resolve_memory_type([None, ""], "B650", lambda _: "DDR5")
    assert memory_type == "DDR5"


def test_memory_type_fallback_returns_none_when_chipset_is_ambiguous():
    memory_type = _resolve_memory_type([None, ""], "B650", lambda _: None)
    assert memory_type is None


def test_count_only_m2_row_stays_capped_to_written_slot_total():
    specs = {"M.2 slot": "3 M.2 slots (Key M)"}
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [{"count": 3, "version": None}]


def test_key_e_wifi_cnvio_rows_do_not_create_storage_m2_slots():
    specs = {
        "M.2 slot": (
            "1 x M.2 Socket (Key E), supports type 2230 WiFi/BT PCIe WiFi module "
            "and Intel CNVio/CNVio2 (Integrated WiFi/BT)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == []


@pytest.mark.xfail(
    reason="v4.2 coverage: parser changes are out of scope for this test-only update"
)
def test_generic_raid_text_for_m2_nvme_devices_does_not_create_unknown_m2_slot():
    specs = {"Storage": "RAID 0/1/5/10 for M.2 NVMe storage devices"}
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == []


def test_amd_cpu_branch_m2_rows_keep_highest_generation_per_slot():
    specs = {
        "Дисков интерфейс": (
            "1 x M.2 connector (M2A_CPU), integrated in the CPU, supporting Socket 3, "
            "M key, type 22110/2280 SSDs:;"
            "- AMD Ryzen 5000/3000 Series Processors support SATA and PCIe 4.0 x4/x2 SSDs;"
            "- AMD Ryzen 5000 G/4000 G/3000 G Series Processors support SATA and PCIe 3.0 x4/x2 SSDs;"
            "1 x M.2 connector (M2B_SB), integrated in the Chipset, supporting Socket 3, "
            "M key, type 22110/2280 PCIe 3.0 x4/x2 SSDs;"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen4"},
        {"count": 1, "version": "Gen3"},
    ]


def test_typed_usb_breakout_rows_preserve_type_a_and_type_c_counts():
    specs = {
        "Портове": (
            "2 USB4 (40Gbps) ports (2 x USB Type-C), "
            "12 USB 10Gbps ports (8 x Type-A + 4 x USB Type-C)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 2, "type": "Type-C", "version": "4.0"} in io["usb_ports"]
    assert {"count": 8, "type": "Type-A", "version": "3.2 Gen2"} in io["usb_ports"]
    assert {"count": 4, "type": "Type-C", "version": "3.2 Gen2"} in io["usb_ports"]


@pytest.mark.xfail(
    reason="v4.2 coverage: parser changes are out of scope for this test-only update"
)
def test_thunderbolt_4_usb4_type_c_ports_do_not_double_count():
    specs = {
        "Портове": "2 x Thunderbolt 4/USB4 Type-C Ports (40 Gb/s)"
    }
    io = _extract_io_json("", specs, None)
    assert io["usb_ports"] == [{"count": 2, "type": "Type-C", "version": "4.0"}]


def test_mixed_rear_and_front_usb_rows_keep_only_rear_counts():
    specs = {
        "USB 3.1 Gen1": "6 x USB 3.1 Gen1 Ports (4 on rear I/Os and 2 via internal header)",
        "USB 2.0": "6 x USB 2.0 Ports (2 on rear I/Os and 4 via internal header)",
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 4, "type": "Type-A", "version": "3.1"} in io["usb_ports"]
    assert {"count": 2, "type": "Type-A", "version": "2.0"} in io["usb_ports"]


def test_gbe_lan_chip_text_produces_single_port_and_one_gigabit_speed():
    specs = {"LAN порт": "Realtek GbE LAN chip (1 Gbps/100 Mbps/10 Mbps)"}
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 1
    assert io["lan_max_speed"] == "1 Gb"


def test_cpu_branch_pcie_rows_keep_highest_generation_per_physical_slot():
    specs = {
        "Слотове": (
            "1 x PCI Express x16 slot (PCIEX16), integrated in the CPU:;"
            "- AMD Ryzen 5000/3000 Series Processors support PCIe 4.0 x16 mode;"
            "- AMD Ryzen 5000 G/4000 G/3000 G Series Processors support PCIe 3.0 x16 mode;"
            "Chipset:;- 4 x PCI Express x16 slots, supporting PCIe 3.0 and running at x1 "
            "(PCIEX1_1, PCIEX1_2, PCIEX1_3, PCIEX1_4)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 1, "lane": "x16", "version": "Gen4"},
        {"count": 4, "lane": "x16", "version": "Gen3"},
    ]


def test_standalone_pcie_count_rows_are_trusted_when_they_are_explicit():
    specs = {
        "PCIe x1": "11 x PCIe 3.0",
        "PCIe x16": "1",
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 11, "lane": "x1", "version": "Gen3"} in io["pcie_slots"]
    assert {"count": 1, "lane": "x16", "version": None} in io["pcie_slots"]


def test_missing_chipset_normalizes_to_none_and_force_skip():
    assert _normalize_chipset(None) is None
    assert _normalize_chipset("chipset") is None
    assert _normalize_chipset("Realtek GbE LAN chip") is None


def test_m2_mixed_gen_connectors_produce_separate_counts():
    specs = {
        "Дисков интерфейс": (
            "PCIe 5.0 -connectors: 3 x M.2 - RAID 0 / RAID 1 / RAID 10",
            "PCIe 4.0 -connectors: 3 x M.2 - RAID 0 / RAID 5",
        )
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 3, "version": "Gen5"} in io["m2_slots"]
    assert {"count": 3, "version": "Gen4"} in io["m2_slots"]


def test_m2_storage_controller_splits_gen5_gen4_and_gen3_rows():
    specs = {
        "Контролер на съхран": (
            "Storage Controller: PCI Express 5.0 x4 (1 x M.2 (Key M))",
            "Storage Controller: PCI Express 4.0 x4 (2 x M.2 (Key M))",
            "Storage Controller: PCI Express 3.0 x4 (1 x M.2 (Key M))",
        ),
        "Дисков интерфейс": (
            "CPU: 1 x Blazing M.2 Socket (M2_1, Key M) supports PCIe Gen5x4",
            "CPU: 1 x Hyper M.2 Socket (M2_2, Key M) supports PCIe Gen4x4",
            "Chipset: 1 x Hyper M.2 Socket (M2_3, Key M) supports PCIe Gen4x4",
            "Chipset: 1 x Ultra M.2 Socket (M2_4, Key M) supports PCIe Gen3x4",
        ),
        "M.2 slot": (
            "1 x M.2 connector (M2_1 Key M) supports PCIe Gen5x4",
            "1 x M.2 connector (M2_2 Key M) supports PCIe Gen4x4",
            "1 x M.2 connector (M2_3 Key M) supports PCIe Gen4x4",
            "1 x M.2 connector (M2_4 Key M) supports PCIe Gen3x4",
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
        {"count": 1, "version": "Gen3"},
    ]


def test_duplicate_m2_rows_with_conflicting_text_do_not_overcount():
    specs = {
        "Дисков интерфейс": (
            "CPU: 1 x M.2 connector (M2_1) supports PCIe 5.0 x4",
            "Chipset: 2 x M.2 connectors (M2_2, M2_3) support PCIe 4.0 x4",
        ),
        "M.2 slot": (
            "M.2_1 slot (Key M) supports PCIe 5.0 x4",
            "M.2_2 slot (Key M) supports PCIe 4.0 x4",
            "M.2_3 slot (Key M) supports PCIe 4.0 x4",
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
    ]


def test_typed_usb_breakout_with_thunderbolt_and_usb_c_preserves_counts():
    specs = {
        "Портове": (
            "2 x Thunderbolt 4/DisplayPort/USB4\n"
            "5 x USB 3.2 Gen 2\n"
            "1 x USB-C 3.2 Gen 2\n"
            "2 x USB 3.2 Gen 1"
        )
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 2, "type": "Type-C", "version": "4.0"} in io["usb_ports"]
    assert {"count": 1, "type": "Type-C", "version": "3.2 Gen2"} in io["usb_ports"]
    assert {"count": 5, "type": "Type-A", "version": "3.2 Gen2"} in io["usb_ports"]
    assert {"count": 2, "type": "Type-A", "version": "3.2 Gen1"} in io["usb_ports"]


def test_realtek_10gb_endpoint_rows_produce_two_ports():
    specs = {"Портове": "2 x Realtek 10Gb Ethernet ports"}
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 2
    assert io["lan_max_speed"] == "10 Gb"


def test_pcie_key_value_expands_each_clause():
    specs = {
        "PCIe x1": "1",
        "PCIe x16": (
            "1 x PCIe 4.0 x16 slot (supports x4 mode);"
            "2 x PCIe 5.0 x16 slots (support x16 or x8/x8 modes)"
        ),
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 1, "lane": "x1", "version": None} in io["pcie_slots"]
    assert {"count": 1, "lane": "x16", "version": "Gen4"} in io["pcie_slots"]
    assert {"count": 2, "lane": "x16", "version": "Gen5"} in io["pcie_slots"]


def test_two_dp_capable_usb_c_clauses_count_two_displayports():
    specs = {
        "Портове": (
            "1 x USB-C port, supporting DisplayPort 1.4 video output\n"
            "1 x Thunderbolt 4 connector (USB4) supporting DisplayPort video outputs"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 2


def test_only_storage_m2_and_wifi_controller_rows_produce_no_pcie_slots():
    specs = {
        "Контролер на съхран": "PCI Express 4.0 x4 (1 x M.2 (Key M))",
        "M.2 slot": "1 x M.2 connector (Key M)",
        "Wi-Fi Controller": "1 x M.2 (Key E)"
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == []


def test_wifi_controller_key_e_does_not_count_as_onboard_wifi():
    assert _normalize_wifi("Wi-Fi Controller: 1 x M.2 (Key E)") == "Not present"


def test_wifi_controller_plus_antenna_still_counts_as_not_present():
    assert (
        _normalize_wifi("Wi-Fi Controller: 1 x M.2 (Key E)\nWi-Fi antenna: 2")
        == "Not present"
    )


def test_placeholder_brand_normalization_is_rejected():
    assert _normalize_brand("Mag") is None
    assert _normalize_brand("Дънна Платка B550_Gaming_Wifi B550_Gaming_Wifi") is None


def test_ram_slot_normalization_requires_explicit_evidence():
    assert _normalize_ram_slots(1) == 1
    assert _normalize_ram_slots(None) is None


def test_ram_slot_key_value_rows_with_bare_numbers_are_parsed():
    assert _extract_ram_slots("Слотове за памет: 4") == 4
    assert _extract_ram_slots("DIMM slots: 4") == 4


@pytest.mark.parametrize(
    "parsed_board",
    [
        {
            "name": "Mag",
            "model": "Mag",
            "brand": "Mag",
            "price": None,
            "url": "https://example.com/mag",
            "specs": {},
            "raw_specs": "",
        },
        {
            "name": "Дънна Платка B550_Gaming_Wifi B550_Gaming_Wifi",
            "model": "Дънна Платка B550_Gaming_Wifi B550_Gaming_Wifi",
            "brand": "Дънна Платка B550_Gaming_Wifi B550_Gaming_Wifi",
            "price": None,
            "url": "https://example.com/b550-gaming-wifi",
            "specs": {},
            "raw_specs": "",
        },
    ],
)
def test_low_signal_placeholder_brands_are_skipped(monkeypatch, tmp_path, parsed_board):
    captured = _run_fake_motherboard_pipeline(monkeypatch, tmp_path, parsed_board)
    assert captured == []


def test_one_line_mixed_m2_row_keeps_gen5_and_gen4_slots_split():
    specs = {
        "M.2 slot": (
            "M2_1 slot (Key M), type 2242/2260/2280 (supports PCIe 5.0 x4 mode), "
            "M2_2 slot (Key M), type 2242/2260/2280 (supports PCIe 5.0 x4 mode), "
            "M2_3 slot (Key M), type 2242/2260/2280 (supports PCIe 4.0 x4), "
            "M2_4 slot (Key M), type 2242/2260/2280/22110 (supports PCIe 4.0 x4 mode)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 2, "version": "Gen5"},
        {"count": 2, "version": "Gen4"},
    ]


def test_bare_m2_slot_id_row_inherits_versions_from_storage_details():
    specs = {
        "M.2 slot": "M.2_1, M.2_2, M.2_3, M.2_4",
        "Storage": "M.2_1 supports PCIe 5.0 x4; M.2_2/M.2_3/M.2_4 support PCIe 4.0 x4",
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 3, "version": "Gen4"},
    ]


def test_lan_guard_and_rj45_dedupe_to_two_lan_ports():
    specs = {
        "LAN порт": "ASUS LAN Guard, 1 x Intel® 2.5Gb Ethernet, 1 x Marvell® AQtion 10Gb Ethernet",
        "Портове": (
            "1 x HDMI, 1 x Display Port, 1 x RJ-45, 3 x Audio jacks, "
            "1 x BIOS Flashback Button, 1 x Marvell AQtion 10Gb Ethernet port, "
            "1 x Clear CMOS button, 1 x Wi-Fi Module"
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 2
    assert io["lan_max_speed"] == "10 Gb"


def test_missing_ram_slot_evidence_with_ai_defaulted_one_stays_null(monkeypatch, tmp_path):
    parsed_board = {
        "name": "ASUS ROG STRIX B650-A GAMING WIFI",
        "model": "ASUS ROG STRIX B650-A GAMING WIFI",
        "brand": "ASUS",
        "price": None,
        "url": "https://example.com/b650-a",
        "specs": {
            "Chipset": "B650",
            "Socket": "AM5",
            "Memory": "DDR5",
        },
        "raw_specs": "Chipset B650 Socket AM5 DDR5",
    }
    captured = _run_fake_motherboard_pipeline(
        monkeypatch,
        tmp_path,
        parsed_board,
        ai_data={"ram_slots": 1},
    )
    assert len(captured) == 1
    assert captured[0]["ram_slots"] is None


def test_explicit_one_slot_ram_evidence_keeps_one(monkeypatch, tmp_path):
    parsed_board = {
        "name": "ASUS PRIME B650M-A WIFI",
        "model": "ASUS PRIME B650M-A WIFI",
        "brand": "ASUS",
        "price": None,
        "url": "https://example.com/b650m-a",
        "specs": {
            "Chipset": "B650",
            "Socket": "AM5",
            "Memory": "DDR5",
            "DIMM slots": "1 x DIMM slot",
        },
        "raw_specs": "Chipset B650 Socket AM5 DDR5 1 x DIMM slot",
    }
    captured = _run_fake_motherboard_pipeline(monkeypatch, tmp_path, parsed_board)
    assert len(captured) == 1
    assert captured[0]["ram_slots"] == 1


def test_count_only_m2_row_is_not_overridden_by_weaker_controller_generation_text():
    specs = {
        "M.2 slot": "5 M.2 slots (Key M)",
        "Контролер на съхран": "PCI Express 4.0 x4 (5 x M.2 (Key M))",
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [{"count": 5, "version": None}]


def test_m2_board_with_one_gen5_and_four_gen4_slots_stays_split_exactly():
    specs = {
        "Дисков интерфейс": (
            "CPU "
            "- 1 x M.2 connector (Socket 3, M key, type 25110/22110/2580/2280 PCIe 5.0 x4/x2 SSD support) (M2A_CPU) "
            "- 1 x M.2 connector (Socket 3, M key, type 22110/2280 PCIe 4.0 x4/x2 SSD support) (M2B_CPU) "
            "Chipset:;- 1 x M.2 connector (Socket 3, M key, type 22110/2280 PCIe 4.0 x4/x2 SSD support) (M2Q_SB) "
            "- 1 x M.2 connector (Socket 3, M key, type 2280 PCIe 4.0 x4/x2 SSD support) (M2P_SB) "
            "- 1 x M.2 connector (Socket 3, M key, type 2280 SATA and PCIe 4.0 x4/x2 SSD support) (M2M_SB) "
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [
        {"count": 1, "version": "Gen5"},
        {"count": 4, "version": "Gen4"},
    ]


def test_cpu_family_pcie_alternatives_do_not_create_extra_cpu_slots():
    specs = {
        "PCIe": (
            "AMD Ryzen 9000 & 7000 Series Desktop Processors;"
            "1 x PCIe 4.0 x16 slot;"
            "AMD Ryzen 8000 Series Desktop Processors;"
            "1 x PCIe 4.0 x16 slot (support x8/x4 mode);"
            "AMD B650 Chipset;"
            "1 x PCIe 4.0 x16 slot (supports x4 mode);"
            "2 x PCIe 4.0 x1 slots;"
            "Specification vary by CPU types.;"
            "PCIe 4.0 x16 slot (supports x4 mode) from AMD B650 Chipset shares bandwidth with M.2_3."
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 2, "lane": "x16", "version": "Gen4"},
        {"count": 2, "lane": "x1", "version": "Gen4"},
    ]


def test_cpu_family_x8_x4_modes_do_not_create_fake_pcie_slots():
    specs = {
        "PCIe x16": (
            "1 x PCI Express x16 slot (PCIEX16), integrated in the CPU;"
            "-AMD Ryzen 9000/7000 Series Processors support PCIe 5.0 x16 mode;"
            "The PCIEX16 slot operates at up to x8 mode when a device is installed in the M2B_CPU or M2C_CPU connector.;"
            "AMD Ryzen 8000 Series-Phoenix 1 Processors support PCIe 4.0 x8 mode;"
            "AMD Ryzen 8000 Series-Phoenix 2 Processors support PCIe 4.0 x4 mode;"
            "Chipset;"
            "- 1 x PCI Express x16 slot, supporting PCIe 4.0 and running at x4 (PCIEX4_1);"
            "- 1 x PCI Express x16 slot, supporting PCIe 3.0 and running at x4 (PCIEX4_2)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 1, "lane": "x16", "version": "Gen5"},
        {"count": 1, "lane": "x16", "version": "Gen4"},
        {"count": 1, "lane": "x16", "version": "Gen3"},
    ]


def test_conflicting_pcie_x16_rows_resolve_to_two_physical_slots():
    specs = {
        "PCIe": "1 x PCIe 5.0 x16 slot; 1 x PCIe 4.0 x16 slot (supports x4 mode)",
        "PCIe x16": "2 x PCIe x16 slots",
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 1, "lane": "x16", "version": "Gen5"},
        {"count": 1, "lane": "x16", "version": "Gen4"},
    ]


def test_dp_alt_and_dp14a_usb_c_outputs_count_as_displayports():
    specs = {
        "Портове": (
            "1 x USB 3.2 Gen1 Type-C Port (DP-alt mode supports DP1.4a) "
            "1 x Thunderbolt 4 connector (USB4 Type-C) supporting DP-alt 1.4"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 2


def test_support_only_displayport_version_clause_does_not_add_extra_output():
    specs = {
        "Видео": (
            "Integrated Graphics Processor with AMD Radeon Graphics support+ASMedia USB4 Controller;"
            "- 2 x USB4 USB Type-C ports, supporting USB4 and DisplayPort video outputs and a maximum resolution of 3840x2160@240 Hz;"
            "Support for DisplayPort 1.4 version and HDR.;"
            "Integrated Graphics Processor with AMD Radeon Graphics support;- 1 x HDMI port, supporting a maximum resolution of 4096x2160@60 Hz;"
            "Support for HDMI 2.1 version.;- 1 x Front HDMI port, supporting a maximum resolution of 1920x1080@30 Hz"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 2
    assert io["hdmi_ports"] == 1


def test_messy_counted_ethernet_endpoint_text_still_counts_lan_ports():
    specs = {
        "Портове": "Wi-Fi Module2 x Realtek 10Gb Ethernet ports"
    }
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 2
    assert io["lan_max_speed"] == "10 Gb"


def test_dedicated_display_port_row_counts_as_one_displayport():
    specs = {"Display Port": "1 x Display Port"}
    io = _extract_io_json("", specs, None)
    assert io["displayport_ports"] == 1


def test_usb_gen2_breakout_row_preserves_type_a_and_type_c():
    specs = {
        "USB 3.2 Gen 2": "2 (USB 3.2 (type A)) (2 USB 3.2 (Type-C))"
    }
    io = _extract_io_json("", specs, None)
    assert {"count": 2, "type": "Type-A", "version": "3.2 Gen2"} in io["usb_ports"]
    assert {"count": 2, "type": "Type-C", "version": "3.2 Gen2"} in io["usb_ports"]


def test_generic_usb_cap_rows_do_not_duplicate_detailed_ports():
    specs = {
        "Портове": (
            "1 x USB 3.2 Gen2 Type-A Port (10 Gb/s)\n"
            "1 x USB 3.2 Gen2 Type-C Port (10 Gb/s)\n"
            "2 x USB 3.2 Gen1 Ports\n"
            "4 x USB 2.0 Ports"
        ),
        "USB 2.0": "4",
        "USB 3.2": "3",
        "USB Type-C": "1",
    }
    io = _extract_io_json("", specs, None)
    assert io["usb_ports"] == [
        {"count": 4, "type": "Type-A", "version": "2.0"},
        {"count": 2, "type": "Type-A", "version": "3.2 Gen1"},
        {"count": 1, "type": "Type-A", "version": "3.2 Gen2"},
        {"count": 1, "type": "Type-C", "version": "3.2 Gen2"},
    ]


def test_lan_speed_ignores_unrelated_10gbps_ports_text():
    specs = {
        "LAN порт": "Realtek 2.5 Gigabit LAN",
        "Портове": (
            "1 x USB 3.2 Gen2 Type-A Port (10 Gb/s)\n"
            "1 x USB 3.2 Gen2 Type-C Port (10 Gb/s)\n"
            "1 x RJ-45 port"
        ),
    }
    io = _extract_io_json("", specs, None)
    assert io["lan_ports"] == 1
    assert io["lan_max_speed"] == "2.5 Gb"


def test_storage_controller_m2_clauses_accumulate_two_gen4_slots():
    specs = {
        "Storage Controller": (
            "PCIe NVMe 4.0 x4 (1 x M.2)\n"
            "PCIe 4.0 x4/SATA (1 x M.2)\n"
            "Supports: Ниво 0, Ниво 1, Ниво 10, Ниво 5\n"
            "SATA III-600 (4)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["m2_slots"] == [{"count": 2, "version": "Gen4"}]


def test_breadcrumb_only_brand_recovery_returns_msi():
    html = """
    <html>
      <body>
        <nav>
          <a data-category="Breadcrumb" href="/dynni-platki/c/80">Boards</a>
          <a data-category="Breadcrumb" href="/filter/brands/msi">Gaming Series</a>
        </nav>
        <h1>PRO B650M-P</h1>
      </body>
    </html>
    """
    parsed = parse_motherboard_page(html, "https://example.com/pro-b650m-p")
    assert parsed["brand"] == "MSI"
    assert parsed["model"] == "PRO B650M-P"


def test_cpu_family_pcie_row_keeps_one_gen4_x16_and_one_gen3_x1():
    specs = {
        "PCIe x16": (
            "1 x PCI Express x16 slot (PCIEX16), integrated in the CPU;"
            "- AMD Ryzen 5000/3000 Series Processors support PCIe 4.0 x16 mode;"
            "- AMD Ryzen 5000 G/4000 G/3000 G Series Processors support PCIe 3.0 x16 mode;"
            "Chipset;"
            "- 1 x PCI Express x1 slot, supporting PCIe 3.0 (PCIEX1_1)"
        )
    }
    io = _extract_io_json("", specs, None)
    assert io["pcie_slots"] == [
        {"count": 1, "lane": "x16", "version": "Gen4"},
        {"count": 1, "lane": "x1", "version": "Gen3"},
    ]


def test_generic_usb_32_type_a_totals_do_not_duplicate_gen_rows():
    specs = {
        "Портове": "8 x USB 3.2 Type-A ports",
        "USB 3.2 Gen 1": "6 x USB 3.2 Gen1 Type-A (Rear)",
        "USB 3.2 Gen 2": "2 x USB 3.2 Gen2 Type-A (Rear)",
    }
    io = _extract_io_json("", specs, None)
    assert io["usb_ports"] == [
        {"count": 6, "type": "Type-A", "version": "3.2 Gen1"},
        {"count": 2, "type": "Type-A", "version": "3.2 Gen2"},
    ]
