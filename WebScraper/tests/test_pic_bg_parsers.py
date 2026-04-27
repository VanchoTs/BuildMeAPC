import pytest
from scrapers.pic_bg.cpu_page import parse_cpu_page
from scrapers.pic_bg.gpu_page import parse_gpu_page
from scrapers.pic_bg.ram_page import parse_ram_page
from scrapers.pic_bg.motherboard_page import parse_motherboard_page
from scrapers.pic_bg.ssd_page import parse_ssd_page
from scrapers.pic_bg.psu_page import parse_psu_page
from scrapers.pic_bg.cooler_page import parse_cooler_page
from scrapers.pic_bg.case_page import parse_case_page

def test_parse_cpu_page():
    html = """
    <html>
        <h1>AMD Ryzen 7 7800X3D Box</h1>
        <div class="price-current">800.00 лв.</div>
        <div class="description">Socket AM5, 8 Cores, 16 Threads</div>
    </html>
    """
    url = "https://www.pic.bg/procesor-amd-ryzen-7-7800x3d-box"
    parsed = parse_cpu_page(html, url)
    assert parsed["name"] == "AMD Ryzen 7 7800X3D Box"
    assert parsed["brand"] == "AMD"
    assert "7800X3D" in parsed["model"]
    assert parsed["price_bgn"] == 800.0

def test_parse_gpu_page():
    html = """
    <html>
        <h1>ASUS Dual GeForce RTX 4070 SUPER 12GB</h1>
        <div class="price-current">1400.00 лв.</div>
        <table>
            <tr><td>Memory</td><td>12GB GDDR6X</td></tr>
        </table>
    </html>
    """
    url = "https://www.pic.bg/videokarta-asus-dual-rtx-4070-super"
    parsed = parse_gpu_page(html, url)
    assert "ASUS" in parsed["name"]
    assert parsed["price_bgn"] == 1400.0
    assert parsed["specs"]["Memory"] == "12GB GDDR6X"

def test_parse_ram_page():
    html = """
    <html>
        <h1>Corsair Vengeance 32GB (2x16GB) DDR5 6000MHz</h1>
        <div class="price-current">250.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/ram-corsair-vengeance-32gb-ddr5"
    parsed = parse_ram_page(html, url)
    assert "Corsair" in parsed["name"]
    assert parsed["price_bgn"] == 250.0

def test_parse_motherboard_page():
    html = """
    <html>
        <h1>MSI MAG B650 TOMAHAWK WIFI</h1>
        <div class="price-current">450.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/danna-platka-msi-mag-b650-tomahawk"
    parsed = parse_motherboard_page(html, url)
    assert "MSI" in parsed["name"]
    assert parsed["price_bgn"] == 450.0

def test_parse_ssd_page():
    html = """
    <html>
        <h1>Samsung 990 Pro 2TB NVMe</h1>
        <div class="price-current">350.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/ssd-samsung-990-pro-2tb"
    parsed = parse_ssd_page(html, url)
    assert "Samsung" in parsed["name"]
    assert parsed["price_bgn"] == 350.0

def test_parse_psu_page():
    html = """
    <html>
        <h1>Corsair RM850e 850W Gold</h1>
        <div class="price-current">220.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/zahranvane-corsair-rm850e"
    parsed = parse_psu_page(html, url)
    assert "Corsair" in parsed["name"]
    assert parsed["price_bgn"] == 220.0

def test_parse_cooler_page():
    html = """
    <html>
        <h1>DeepCool AK620 Digital</h1>
        <div class="price-current">120.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/ohladitel-deepcool-ak620"
    parsed = parse_cooler_page(html, url)
    assert "DeepCool" in parsed["name"]
    assert parsed["price_bgn"] == 120.0

def test_parse_case_page():
    html = """
    <html>
        <h1>Lian Li LANCOOL 216 Black</h1>
        <div class="price-current">180.00 лв.</div>
    </html>
    """
    url = "https://www.pic.bg/kutia-lian-li-lancool-216"
    parsed = parse_case_page(html, url)
    assert "Lian Li" in parsed["name"]
    assert parsed["price_bgn"] == 180.0
