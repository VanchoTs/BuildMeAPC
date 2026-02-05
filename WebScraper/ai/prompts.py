CPU_PROMPT = """
You are a hardware expert.
Extract CPU information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string)
- model (short product model, e.g. "Ryzen 5 3400G")
- socket (string)
- cores (integer)
- threads (integer)
- base_clock (GHz, number)
- boost_clock (GHz, number)
- tdp (W, integer)
- memory_type (string, e.g. "DDR4", "DDR5", or "DDR4/DDR5")
- price (number, EUR)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate.

Content:
{content}

Product name: {name}
Price (EUR): {price}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""

GPU_PROMPT = """
You are a hardware expert.
Extract GPU information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "NVIDIA", "AMD", "Intel")
- model (short GPU model, e.g. "GeForce RTX 4070", "Radeon RX 7800 XT", "Arc A770")
- pcb_manufacturer (string, e.g. "ASUS", "MSI", "Gigabyte", "Sapphire")
- pcb_series (string, e.g. "TUF Gaming", "Gaming X", "Eagle", "Pulse")
- vram_gb (integer)
- memory_type (string, e.g. "GDDR6", "GDDR6X")
- memory_bus_bit (integer)
- base_clock_mhz (number)
- boost_clock_mhz (number)
- tdp (W, integer)
- interface (string, e.g. "PCIe 4.0")
- price (number, EUR)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate. For interface, prefer the "Слот" or "Slot" field (often with id "char-slot") and normalize "PCI Express Gen 5" as "PCIe 5.0". Do not use display outputs (HDMI/DP/DVI) or memory bus ("128-bit") as the interface.

Content:
{content}

Product name: {name}
Price (EUR): {price}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""
