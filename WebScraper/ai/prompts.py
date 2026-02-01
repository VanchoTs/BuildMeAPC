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
