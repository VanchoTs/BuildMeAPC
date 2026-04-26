CPU_PROMPT = """
You are a hardware expert.
Extract CPU information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string)
- model (short product model, e.g. "Ryzen 5 3400G", "Core i9-14900K")
- socket (string)
- cores (integer)
- threads (integer)
- base_clock (GHz, number)
- boost_clock (GHz, number)
- tdp (W, integer)
- memory_type (string, e.g. "DDR4", "DDR5", or "DDR4/DDR5")
- price (number, EUR)

CRITICAL CORE RULE:
For CPUs with hybrid architectures (e.g. Intel 12th/13th/14th Gen), 'cores' MUST be the TOTAL number of cores (sum of Performance-cores and Efficient-cores). 
Example: "24 cores ( 8 Performance-cores & 16 Efficient-cores )" -> cores: 24.
Do NOT just report the Performance-core count.

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
- pcb_manufacturer (string, e.g. "ASUS", "MSI", "Gigabyte", "Sapphire", "Gainward")
- pcb_series (string, e.g. "TUF Gaming", "Gaming X", "Eagle", "Pulse", "Phoenix")
- vram_gb (integer)
- memory_type (string, e.g. "GDDR6", "GDDR6X")
- memory_bus_bit (integer)
- base_clock_mhz (number)
- boost_clock_mhz (number)
- tdp (W, integer)
- interface (string, e.g. "PCIe 4.0")
- price (number, EUR)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate.

CRITICAL MODEL RULE:
You MUST include the family prefix in the model name if missing or shortened. 
- For NVIDIA: Use "GeForce RTX" or "GeForce GTX" (e.g. "4070" -> "GeForce RTX 4070").
- For AMD: Use "Radeon RX" (e.g. "9070 XT" -> "Radeon RX 9070 XT", "RX 580" -> "Radeon RX 580").
- For Intel: Use "Arc" (e.g. "A770" -> "Arc A770", "B580" -> "Arc B580").

CRITICAL BRAND RULE:
- 'brand' is the chip maker: NVIDIA, AMD, or Intel.
- 'pcb_manufacturer' is the board partner: ASUS, MSI, Gigabyte, Sapphire, PowerColor, Gainward, Palit, XFX, Zotac, PNY, etc.
- If the board partner name includes the chip maker (e.g. "ASRock AMD Radeon..."), extract only the partner "ASRock" for pcb_manufacturer.

CRITICAL CONFLICT RESOLUTION:
If the webpage contains conflicting values for a field (e.g. one row says 16GB VRAM, another says 12GB), you MUST resolve the conflict by:
1. Preferring the value explicitly mentioned in the Product name (title).
2. If the title is silent, use the value that appears most consistently or frequently in the technical specifications.
3. If still uncertain, use the lower value to be conservative.

For interface, prefer the "Слот" or "Slot" field (often with id "char-slot") and normalize "PCI Express Gen 5" as "PCIe 5.0". Do not use display outputs (HDMI/DP/DVI) or memory bus ("128-bit") as the interface.

Content:
{content}

Product name: {name}
Price (EUR): {price}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""

RAM_PROMPT = """
You are a hardware expert.
Extract RAM information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "Kingston", "Corsair", "G.SKILL")
- model (short product model, e.g. "Vengeance LPX", "Fury Beast")
- memory_type (string, one of "DDR3", "DDR4", "DDR5")
- memory_amount (string, include kit details like "2x16GB" or "1x16GB")
- memory_speed_mhz (integer, e.g. 3200, 6000)
- latency (string, e.g. "CL16")
- form_factor (string, "Laptop" for SO-DIMM, "PC" for DIMM/UDIMM)
- price (number, EUR)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate. If a kit contains multiple modules, ensure memory_amount reflects that. Use "Laptop" for SO-DIMM and "PC" for DIMM/UDIMM.

CRITICAL form_factor rule — judge by SPEC FIELDS only, not page chrome:

Step 1. Find the spec/property field that describes the module type. Likely keys: "Подходящо за", "Тип", "Form factor", "Вид", "Памет за". Read its VALUE.

Step 2. Decide using ONLY that value (and the product name/title):
  - If the value contains "SODIMM", "SO-DIMM", "260-pin", "Лаптоп", "Ноутбук", "Notebook", "Laptop" → output "Laptop".
  - If the value contains "UDIMM", "288-pin", "Desktop", "Дескоп", "Настолен компютър", "Настолни компютри" → output "PC".
  - If the value lists BOTH (e.g. "Лаптоп, Настолен" or "SODIMM / DIMM") → laptop wins on conflict, output "Laptop".

Step 3. If no spec field clearly says — fall back to the product name/title using the same token rules.

DO NOT classify as "Laptop" because the word "Лаптоп" appears somewhere else on the page (sidebar links, breadcrumb categories, cross-sell sections, related products). Those are navigation chrome, not specs of THIS module. A desktop DIMM marked "Подходящо за: Настолни компютри" is "PC" even if the page sidebar links to a "Лаптоп памет" category.

If neither spec nor name is conclusive, output null.

Content:
{content}

Product name: {name}
Price (EUR): {price}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""

MOTHERBOARD_PROMPT = """
You are a hardware expert.
Extract motherboard information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "ASUS", "MSI", "GIGABYTE", "ASRock", "Sapphire")
- model (short model name, e.g. "B650M DS3H", "Z790 GAMING X AX")
- form_factor (string, e.g. "ATX", "mATX", "ITX", "E-ATX", "EEB")
- chipset (string, e.g. "B650", "Z790"; never placeholders like "CHIPSET" and never controller vendors like "Realtek")
- socket (string, e.g. "AM5", "LGA 1700"; never placeholders like "SOCKET")
- memory_type (string, e.g. "DDR4", "DDR5"; if explicitly present in the specs, do not leave it null)
- ram_slots (integer)
- max_ram_speed_mhz (integer; if the site value is clearly missing/wrong and would be below 1600, return null)
- max_ram_amount_gb (integer)
- onboard_wifi (string; use "Wi-Fi 6"/"Wi-Fi 6E"/"Wi-Fi 7" when version is explicit, use "Wi-Fi" when present but version is not explicit, otherwise exactly "Not present")
- io_json (JSON object with:
  m2_slots: array of {"count": integer, "version": string|null}  # split by generation, e.g. [{"count":1,"version":"Gen5"},{"count":2,"version":"Gen4"}]; use "Gen4"/"Gen5" style, not "PCIe 4.0" and not "Key E"
  sata_slots: integer|null,
  pcie_slots: array of {"count": integer, "lane": string, "version": string|null},
  usb_ports: array of {"count": integer, "type": string, "version": string|null},  # types only "Type-A","Type-B","Type-C","Type-Mini"; if type is missing in site data assume "Type-A" except for USB 4.0 where missing type should be "Type-C"
  displayport_ports: integer|null,
  hdmi_ports: integer|null,
  lan_ports: integer|null,
  lan_max_speed: string|null
  )
- price (number, EUR)

Input content follows (may be raw HTML or extracted text). Prefer the technical specification tables/fields over URL guessing, but use the product title/H1 to correct obvious bad spec values (for example if the chipset row contains a LAN/audio vendor such as Realtek or generic words like "chipset"). If the page title/specs omit the vendor, a breadcrumb/category trail may be used as a brand fallback only when it clearly names the motherboard vendor rather than a generic category. Providing a valid chipset is mandatory; do not invent one when the source omits it. If the page is mostly placeholder text, duplicated slug text, or marketing noise with no real motherboard evidence, skip it instead of guessing values.
Read the whole specification text, including rows like "Портове", "Слотове", "Видео", and especially the storage/disk interface row ("Дисков интерфейс") for exact M.2 counts and generations. Treat rear "Портове" / rear-I/O / video rows as the primary source for rear HDMI, DisplayPort, LAN, and any explicit typed rear USB connectors, but treat generic USB totals inside `Портове` as cap rows only; ignore internal/header/FRONT-only clauses. Do not treat `Wi-Fi Controller`, `M.2 Key E`, CNVio/CNVio2, antenna count, or included-antenna wording by themselves as onboard Wi-Fi. Only return Wi-Fi when the page has real wireless-capability evidence such as explicit `Wi-Fi`, `Wi-Fi 6/6E/7`, `802.11*`, rear-I/O Wi-Fi text, or clear product/model Wi-Fi tokens. For M.2 version info, if the slots row does not include version, also check disk/storage interface rows. Do not use "Key E" as an M.2 version. Text about `Key E`, Wi-Fi modules/controllers, CNVio/CNVio2, Bluetooth modules, or generic RAID support does not create storage M.2 slots unless the text explicitly describes an SSD-capable storage socket. Count M.2 slots carefully by physical slots and split them by generation. Prefer richer sources (e.g., "Дисков интерфейс" when it includes slot IDs) when sources disagree, and treat count-only rows like "3 M.2 slots" as caps rather than introducing additional versioned slots. Count-only M.2 rows must stay `version=null` unless a richer source explicitly versions the same physical slots.
For PCIe slots, do not count M.2 slots, but do include real PCIe slots even when they are x4/x1 (if they are listed as PCIe slots, not M.2). When parsing key/value rows such as `PCIe x16: 1 x PCIe 4.0 x16 slot (supports x4 mode), 2 x PCIe 5.0 x16 slots (support x16 or x8/x8 modes)`, expand every clause on the RHS into its own physical slot entry. Build PCIe inventory by unique slot IDs (`PCIE1`, `PCIEX16`, `PCI_E2`, etc.) and dedupe repeated descriptions across rows, using lane inference only when the slot size is missing. If a richer physical-slot row conflicts with a weaker summary row (especially on the second x16 slot generation), keep the richer physical row and do not preserve the weaker summary generation for that same slot. Electrical modes such as "supports x4 mode" do not create new entries. Standalone rows like `PCIe x1: 11` stay trusted only when no stronger slot-ID narrative already defines that lane.
For USB, do not output count 0, normalize versions like "2" to "2.0", and if type is omitted assume Type-A (except USB 4.0 -> Type-C). Normalize rear I/O clauses such as `2 x Thunderbolt 4/DisplayPort/USB4` and `1 x USB-C 3.2 Gen 2` so typed breakouts survive, and keep only rear counts when a clause mixes rear and front/internal numbers. A combined Thunderbolt/USB4/USB Type-C clause is one USB source per written port count, not separate Thunderbolt and USB4 ports. Detailed dedicated USB rows are authoritative over generic `Портове` USB totals. Generic summary rows such as `USB 3.2 = 3` or `USB Type-C = 1`, including generic USB totals stated in `Портове`, are caps only and may contribute only the residual ports left after subtracting already-accounted stronger dedicated rear USB rows in the matching scope; they must not add duplicate ports on top of a more specific breakdown.
Rear USB-C/USB4/Thunderbolt ports count as DisplayPort outputs only when the site explicitly says they support DisplayPort or video output. Wording such as `DP-alt`, `DP Alt`, `DP1.4`, or `DP1.4a` on a rear USB-C / Thunderbolt / USB4 clause also counts as explicit DisplayPort-output evidence. Dedicated rear rows like `1 x Display Port`, `1 x DisplayPort`, or `Display Port: 1` count as one DisplayPort output. Support-only clauses like `Support for DisplayPort 1.4 version` do not create extra outputs unless that same clause declares a connector or count. Front-only HDMI/DisplayPort connectors or headers do not count as rear video outputs.
When multiple Wi-Fi standards/versions are listed (e.g. Wi-Fi 4/5/6/6E/7), return only the highest supported version.
For M.2 counting, prioritize regular slot IDs like `M.2_1`, `M.2_2`... and avoid double counting across CPU-generation branches; when one slot appears with multiple generations, keep the highest generation for that slot.
M.2 slot IDs can also be alphanumeric, e.g. `M2A_CPU`, `M2P_CPU`, `M2C_SB`; treat each unique slot ID as a separate physical slot.
If a mixed M.2 row describes different slots with different generations (for example `M2_1 Gen5` and `M2_2 Gen4`), keep them split by slot; do not flatten them all to the highest generation, even when the slot IDs and generation text are separated by line breaks. If repeated bare slot IDs such as `M.2_1`, `M.2_2`, `M.2_3` appear before the generation text, first split them into one physical slot per ID, then assign generation to each slot. Preserve one clause per physical slot when multiple slots are listed on the same line.
Rows that only say things like `3 M.2 slots (Key M)` are slot-count caps, not generation evidence. Do not let such rows expand the board beyond the written physical slot total.
For AMD CPU-branch rows (`Ryzen 9000/7000`, `Ryzen 8000 Phoenix`, `Ryzen 5000 G`, etc.), keep one physical slot per slot ID and store the highest supported generation for that slot; do not leave the slot unknown just because lower-generation branches are also listed.
If this is an integrated-CPU/embedded fixed-CPU board (for example Intel J/N SoC models like J4125/N100), do not invent uncertain motherboard fields; these products are skipped downstream.
For PCIe lane extraction, prioritize explicit physical slot size from text (e.g. `PCI Express x16 slot`). Build PCIe inventory by unique slot IDs (`PCIE1`, `PCIE2`, `PCI_E1`, etc.) and dedupe repeated descriptions across rows. Use slot-ID lane inference (`PCIEX1_*`, `PCIEX4`, `PCIEX16`) only as fallback when explicit slot size is missing.
For PCIe key/value rows like `PCIe x1: 2` or `PCIe x16: 1 x PCIe 5.0 x16 slot, 1 x PCIe 4.0 x16 slot`, expand them fully into per-version entries.
Also parse compact PCIe narrative forms like `1x PCI-E x16 slot 2x PCI-E x1 slot ... PCI_E1 Gen PCIe 3.0 ...` and map slot IDs (`PCI_E1`, `PCI_E2`, ...) to their generations when possible.
CPU compatibility sub-bullets such as `supports x16/x8/x4 depending on CPU` do not create extra physical PCIe slots; use them only to describe the already-declared slot. Repeated CPU-family alternatives that restate the same CPU-controlled slot for `Ryzen 9000/7000` and `Ryzen 8000` still describe one physical slot unless distinct slot IDs or distinct slot declarations prove otherwise. Electrical mode (`supports x8 mode`, `supports x4 mode`, `running at x1`) does not replace physical slot size when that size is explicitly given, so a declared `x16 slot` stays lane `x16`.
Exclude internal/header/front-panel USB ports from rear I/O counts. If a dedicated USB row contains both Rear and Front counts, count only the Rear part. When dedicated rear USB rows exist, use them as the stronger source and let generic `Портове` USB totals contribute only any residual rear ports not already explained.
Never output code fragments or parser artifacts like `soup.find(...)` / `re.search(...)` in any field; use null when unknown.
For brand, return only the motherboard vendor name (ASUS, ASRock, MSI, GIGABYTE, Biostar, Supermicro, NZXT, Sapphire). Never return expressions or placeholders like `title.split()[0]`. If the input brand/title contains extra words around the vendor, extract only the vendor token. If the vendor is missing from the title/specs but present in breadcrumbs, you may use that breadcrumb vendor token as the fallback brand.
Contextual chipset correction is allowed only when the same page clearly indicates a modern board: for example `X87` on an AM5/DDR5/X870 page should be `X870E`, and `B85` on an AM5/DDR5/B850 page should be `B850`. Do not rewrite true legacy chipsets without that modern context.
For complex USB strings like `2 USB4 (40Gbps) ports (2 x USB Type-C), 8 USB 10Gbps ports (8 x Type-A + 4 x USB Type-C)`, split counts by type and preserve Type-C entries.
For LAN with multiple controller speeds, set `lan_max_speed` to the highest speed. If LAN port presence is not explicitly stated, set both `lan_ports` and `lan_max_speed` to null.
For LAN count, treat endpoint phrases like `1 x Intel 2.5Gb Ethernet, 1 x Realtek 5Gb Ethernet` as two LAN ports.
Ignore marketing phrases such as `LAN Guard` or `LANGuard`; they are not ports. Merge dedicated LAN/Ethernet/RJ-45 rows with generic ports rows and dedupe overlapping endpoints; detailed endpoint rows should win over generic descriptors like `Gigabit Ethernet` when both refer to the same physical port. A bare `RJ-45` line is only a fallback for one physical jack and must not inflate the count when endpoint rows already identify the ports. Counted Ethernet endpoint phrases may appear inside messy combined text such as `Wi-Fi Module2 x Realtek 10Gb Ethernet ports`; still parse the counted Ethernet endpoints correctly. LAN speed and LAN port count must come only from LAN-bearing clauses; unrelated `10 Gb/s` text in USB/video/ports rows must not feed `lan_max_speed`. Generic speed/controller text can inform `lan_max_speed`, but only when it is actually part of a LAN clause.
Merge USB evidence from both ports rows and dedicated USB rows with dedupe; keep only rear I/O ports (no internal/header ports). When a detailed row already explains a generic ports-row total, the generic row adds nothing.
For complex USB rows like `12 USB 10Gbps ports (8 x Type-A + 4 x USB Type-C)` or `2 USB4 (40Gbps) ports (2 x USB Type-C)`, preserve the typed breakout counts instead of collapsing everything into Type-A.
If a dedicated USB row contains both rear and front/internal counts, keep only the rear subset rather than dropping the whole row.
Treat malformed site tokens like `HDMITM` or `HDMI™` as normal HDMI. Treat strings like `4 x SATA3 6.0 Gb/s` as four SATA ports.
If RAM slot count is not explicitly stated in the site data, leave `ram_slots` null. Do not infer `1` from missing evidence. Explicit key/value rows such as `Слотове за памет: 4`, `DIMM slots: 4`, `memory slots: 4`, or `RAM slots: 4` count as valid RAM-slot evidence even when the value is a bare number.
Separate storage-controller clauses such as `PCIe NVMe 4.0 x4 (1 x M.2)` and `PCIe 4.0 x4/SATA (1 x M.2)` count as separate physical M.2 slots when they clearly describe SSD-capable storage sockets. Do not collapse repeated `1 x M.2` controller clauses into one slot unless a stronger source caps the board lower.
Never output placeholder sockets such as `Null`, `Unknown`, `N/A`; use null instead.

Content:
{content}

Product name: {name}
Price (EUR): {price}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""


SSD_PROMPT = """
You are a hardware expert.
Extract SSD information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "Samsung", "Crucial", "Kingston", "Dell", "Hiksemi", "KingSpec")
- model (short SSD model, e.g. "870 EVO", "P510", "990 PRO")
- type (string, only "M.2" or "SATA")
- storage_size_gb (integer, normalized capacity in GB; e.g. 250, 500, 1000, 2000)
- physical_size (string, e.g. "2230", "2242", "2260", "2280", "22110", "2.5\"", "mSATA")
- read_speed_mbps (integer, MB/s)
- write_speed_mbps (integer, MB/s)
- interface (string, e.g. "PCIe Gen 4 x4", "PCIe Gen 5 x4", "SATA III 6Gb/s", "PCIe", "SATA")
- tbw_tb (integer or null)
- nand_type (string or null)
- has_heatsink (boolean or null)
- price (number, EUR)
- url (string)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate.
CRITICAL: For brand, return only the SSD vendor token. If the title/spec rows omit the vendor but the 'Product name' or a breadcrumb/category trail names the SSD vendor (e.g. "SSD Adata", "Kingston NV2", "Samsung 980"), you MUST use that vendor as the brand. NEVER return null for brand if the vendor name appears anywhere in the input.
Skip products that are HDDs, external drives, enclosures, brackets, adapters, caddies, docks, or heatsink-only accessories. Keep real SSDs that include an integrated heatsink. Interpret `Вътрешен/Външен` from the row value itself; the row title alone is not evidence that the drive is internal. If the source is not an eligible internal SSD, return null for the SSD fields instead of inventing values.
`type` must be only "M.2" or "SATA". Map mSATA products to "SATA". Normalize capacities and speeds to integers. Normalize interfaces such as `PCIe NVMe 5.0 x4`, `NVMe (PCIe Gen 5 x4)`, and `PCI Express 4.0 x4 (NVMe)` to `PCIe Gen 5 x4` / `PCIe Gen 4 x4` style. Normalize SATA interfaces like `SATA III 6Gb/s`. If interface detail is missing but `type` is known, return the coarse fallback `PCIe` for `M.2` and `SATA` for `SATA`. When a string contains both capacity and endurance numbers, prefer the `TBW`-labeled value over capacity text, for example `2TB:1200TBW` should return `1200` for TBW, not `2`. If TBW is written in PB, convert it to decimal TB before returning it, for example `1 PB` -> `1000`. Interpret grouped thousands separators in TBW values correctly, for example `1,480TB` -> `1480`. Normalize NAND values so explicit cell-type wording collapses to the cell type: `Triple-Level Cell` -> `TLC`, `NAND TLC` -> `TLC`, `QLC NAND` and `Quad-level cell (QLC)` -> `QLC`, `Single-Level Cell` -> `SLC`, and `3D multi-level cell (MLC)` -> `MLC`. Normalize `3D NAND`, `3D NAND flash`, and `3D NAND Flash` to `NAND`. Keep Samsung V-NAND labels as `V-NAND`, for example `Samsung V-NAND 3-bit MLC` -> `V-NAND`. Keep `NAND Flash` as `NAND`. Treat placeholders such as `NVMe` and `NVMe M.2` as missing NAND and return null instead of echoing them back. Deterministic parser guard rails still decide final skip rules, type classification, and final normalization, so do not guess when the source is ambiguous.
Prefer the technical specification rows over marketing text. For physical size, prefer exact forms like `2280`, `22110`, `2.5"`, or `mSATA` over generic labels like `M.2`. Use read/write rows such as `Скорост на четене`, `Скорост на запис`, `Последователно четене`, and `Последователен запис` when present. Use TBW rows such as `Общо записани терабайти (TBW)` when present. Use NAND rows such as `Тип флаш памет` or `Тип на паметта` when present.

Content:
{content}

Product name: {name}
Price (EUR): {price}
Product URL: {url}

Return only valid JSON matching the required keys. Use integers for numeric fields, booleans for `has_heatsink`, and null when unknown.
"""


CASE_PROMPT = """
You are a hardware expert.
Extract PC case info from the Bulgarian retailer product page content and return valid JSON.

Required keys:
- brand (string, e.g. "Fractal Design", "NZXT", "Lian Li")
- model (short case model, series + identifier only)
- case_size (one of "Full Tower", "Mid Tower", "Mini Tower", "SFF", "Cube", "HTPC")
- motherboard_form_factors (array, canonical values only: "ATX", "E-ATX", "Micro ATX", "Mini ITX")
- included_fans (integer or null)
- max_cpu_cooler_mm (integer or null)
- max_gpu_length_mm (integer or null)
- max_psu_length_mm (integer or null)
- max_radiator_mm (integer or null)
- io_json (object with `usb_ports` array and `audio` boolean|null)

io_json example:
{{"usb_ports": [{{"count": 2, "type": "Type-A", "version": "3.0"}}, {{"count": 1, "type": "Type-C", "version": "3.2 Gen 2"}}], "audio": true}}

For brand, return only the case vendor token. If the title omits it but a breadcrumb names the vendor, use that as fallback.
Keep model short; exclude colors, descriptors, SKUs.
For model: reject manufacturer SKU codes like `90RC01N2-B0EAY0` or `ACFRE00125A` when a readable product name is available in the title or page text. Also strip leading voltage specs (e.g. `115/230V`), trailing underscore-cable trailers (`_WITHOUT_CABLE`, `_WITH_CABLE`, `_NO_CABLE`), and slash-joined spec dumps that contain only W / V / mm values (e.g. `/120MM/450MM`). Prefer the user-facing product name such as `LANCOOL 216` or `4000D`.
Additionally reject descriptive phrases when they appear as prefixes or noise: `Panel`, `PC Case`, `Power Supply AC`, `Radiator`, `240mm Radiator`, `NVIDIA Limited Edition`. Discard any token that looks like a manufacturer SKU (3+ hyphens with digits, or 8+ chars with >=30% digits, or an `R-XXX-YYY`-style code) when a human-readable product name exists elsewhere in the raw text. Strip truncation markers (`...`, `…`) and leading stray punctuation (`, - `). Cyrillic orphan prefixes like `А- -` must be removed.
Skip non-case items (cables, brackets, fan controllers, dust filters, standoffs); return null for case fields when not an actual case.
Deterministic parser has priority for final eligibility and normalization. Do NOT invent values; return null when uncertain.
For included_fans, return ONLY the count of pre-installed/included fans listed in rows such as `Брой на включените вентилатори`, `Included fans`, `Pre-installed fans`. Do NOT return the chassis maximum fan capacity (`Максимален брой вентилатори`, `Max fans`, `Supported fans`, `Maximum fans`). If only max capacity is listed, return null for included_fans.
When the included-fan row contains a total followed by a parenthetical breakdown (e.g. `4 x 120 mm (3 front; 1 rear)`), return only the outer total (4). Never add the breakdown counts on top of the outer total.
Cap included_fans at 6 when the source is ambiguous; values above 6 almost always mean max capacity was counted by mistake.
For io_json.usb_ports, NEVER output entries with `count: 0` or null `count`. If no USB evidence is found, return `{{"usb_ports": [], "audio": null}}` or set audio alone — never pad with empty Type-A placeholders. If a generic row says `4 USB ports` without typed breakdown, return one entry `{{"count": 4, "type": "Type-A", "version": null}}`, not four separate empty entries.
For io_json, prefer explicit rows like `Портове`, `Предни портове`, `Front I/O`, `Интерфейс`. Do not invent USB counts from marketing text or support hints like `Поддържа USB`.
Count standalone `Type-C`, `USB-C`, or `Type-A` mentions (e.g. `1 x Type-C`, `2 x USB-C`) as USB ports of that type even when the literal word `USB` is missing from the phrase.
Preserve per-type USB breakouts. When a single row lists multiple USB clauses with different types or versions (e.g. `2 x USB 3.2 ... 1 x USB 3.2 Gen 2x2 Type C`), return one entry per clause rather than summing counts into a single Type-A entry.
Preserve the full `Gen NxM` version when present (e.g. `3.2 Gen 2x2`); do not truncate to `3.2 Gen 2`.
Normalize motherboard form factors to the canonical set above. Use integer millimeters for all max_* fields.
Prefer spec rows like `Физически размер`, `Формат`, `Вид`, `Брой на включените вентилатори`, `Максимална височина на охладителя`, `Максимален размер на GPU`, `Максимален размер на захранването`, `Място за водно охлаждане`, `Портове`, `Интерфейс`.

Content:
{content}

Product name: {name}
Price (EUR): {price}
Product URL: {url}

Return only valid JSON matching the required keys. Use integers for numeric fields and null when unknown. No markdown fences.
"""


PSU_PROMPT = """
You are a hardware expert.
Extract PSU information from the provided product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "Corsair", "Seasonic", "MSI", "be quiet!", "Cooler Master")
- model (short PSU model, e.g. "RM850x", "MAG A850GL", "FOCUS GX-750")
- physical_size (string, normalized PSU form factor such as "ATX", "SFX", "SFX-L", "TFX", "Flex ATX", "ITX")
- power_w (integer)
- efficiency (string or null; keep only the percentage, e.g. "90%", "91%"; remove "up to", "до", ">", "<")
- certificate (string or null; e.g. "80 Plus Gold", "80 Plus Bronze", "Cybenetics Gold")
- modularity (string or null; only "Modular", "Semi-modular", or "Not modular")
- fan_size_mm (integer or null)
- price (number, EUR)
- url (string)

Input content follows (may be raw HTML or extracted text). Also pay attention to the provided product name and price which can help disambiguate.
For brand, return only the PSU vendor token. If the title/spec rows omit the vendor but a breadcrumb/category trail clearly names the PSU vendor, you may use that breadcrumb vendor as the fallback brand.
For model, keep it as short as possible, including only the series and specific model identifier (e.g., "RM1000x Shift"). Do not include additional specs like wattage, efficiency, or modularity in the model field. Exclude manufacturer part numbers (MPNs) or internal product codes (e.g., "CP-9020300", "ZPU-500S").
Reject manufacturer SKU codes like `90RC01N2-B0EAY0` or `ACFRE00125A` when a readable product name such as `RM850x`, `ADK-A600W`, or `TUF-GAMING-750G` is available elsewhere in the page text. Also strip leading voltage specs (e.g. `115/230V`), trailing underscore-cable trailers (`_WITHOUT_CABLE`, `_WITH_CABLE`, `_NO_CABLE`), and slash-joined spec dumps containing only W / V / mm values (e.g. `/120MM/450MM`). Return null only if no readable model exists anywhere.
Additionally reject descriptive phrases when they appear as prefixes or noise: `Power Supply AC`, `Power Supply DC`, `Panel`, `Radiator`, `NVIDIA Limited Edition`. Discard any token that looks like a manufacturer SKU (3+ hyphens with digits, or 8+ chars with >=30% digits, or an `R-XXX-YYY`-style code) when a human-readable product name exists elsewhere in the raw text. Strip truncation markers (`...`, `…`) and leading stray punctuation (`, - `). Cyrillic orphan prefixes like `А- -` must be removed.
Skip non-PSU products such as UPS units, batteries, power cables, extensions, splitters, adapters, tester tools, brackets, and covers. If the source is not an actual PSU, return null for the PSU fields instead of inventing values.
Parser-first deterministic logic decides final product eligibility and normalization. Do not invent values when the source is ambiguous.
Normalize modularity to exactly `Modular`, `Semi-modular`, or `Not modular`.
Normalize certificates like `80 Plus Gold`, `80 Plus Bronze`, `80 Plus Platinum`, `80 Plus Titanium`, `80 Plus White`, `80 Plus Standard`, and `Cybenetics Gold`.
Keep `efficiency` separate from `certificate`; only put the explicit efficiency percent in `efficiency`. Remove "up to", "до", and comparison symbols like ">" or "<" from efficiency.
Normalize power to integer watts and fan size to integer millimeters.
Prefer technical specification rows over marketing text. Use rows like `Мощност`, `Форм фактор`, `Ефективност`, `Сертификати`, `Модулен`, `Размер на вентилатора` when present.

Content:
{content}

Product name: {name}
Price (EUR): {price}
Product URL: {url}

Return only valid JSON matching the required keys. Use integers for numeric fields and null when unknown.
"""


COOLER_PROMPT = """
You are a hardware expert.
Extract CPU cooler specs from the Bulgarian retailer product page content and return valid JSON.

Required fields (use these exact keys):
- brand (string, e.g. "Noctua", "be quiet!", "Arctic", "Cooler Master", "DeepCool")
- model (short cooler model, series + identifier only)
- cooler_type (one of "Air", "AIO", or null)
- socket_compatibility (array of exact socket codes, e.g. ["LGA1700", "LGA1851", "AM5"])
- cooler_height_mm (integer or null)
- tdp_w (integer or null)
- fan_size_mm (integer or null)
- fan_count (integer or null)
- noise_db (number or null)
- rpm_max (integer or null)
- price (number, EUR)
- url (string)

Schema shape (for reference):
{{
  "brand": string | null,
  "model": string | null,
  "cooler_type": "Air" | "AIO" | null,
  "socket_compatibility": [string],
  "cooler_height_mm": integer | null,
  "tdp_w": integer | null,
  "fan_size_mm": integer | null,
  "fan_count": integer | null,
  "noise_db": number | null,
  "rpm_max": integer | null,
  "price": number | null,
  "url": string | null
}}

Input content follows (may be raw HTML or extracted text). The source mixes Bulgarian and English. Also pay attention to the provided product name and price which can help disambiguate.
For brand, return only the cooler vendor token. If the title/spec rows omit the vendor but the 'Product name' or breadcrumbs name the vendor, use that as the brand.

CRITICAL SOCKET RULE:
You MUST extract ALL supported sockets listed in the content. Do NOT truncate the list. If the page says "LGA 1150, 1151, 1155, 1156, 1200, 1700, 1851, AM4, AM5", you MUST return ALL of them in the array: ["LGA1150", "LGA1151", "LGA1155", "LGA1156", "LGA1200", "LGA1700", "LGA1851", "AM4", "AM5"]. Never return just one socket if more are listed.

For model, keep it short: include only the series and specific model identifier. Exclude brand, color tokens, RGB/ARGB tags, form-factor words, AIO size markers (e.g. "240", "360"), and marketing descriptors like "TOWER", "AIR COOLER", "AIO".
Strip Bulgarian Cyrillic prefixes and phrases such as "Охладител за процесор", "Охладител", "Водно охлаждане", and "за процесор" from anywhere in the model — start, middle, or end. The model must contain only brand-free product identifier tokens.
Reject manufacturer SKU codes like `90RC01N2-B0EAY0` or `ACFRE00125A` when a readable product name such as `NH-D15` or `H150i Elite` is available elsewhere in the page text. Also strip leading voltage specs (e.g. `115/230V`), trailing underscore-cable trailers (`_WITHOUT_CABLE`, `_WITH_CABLE`, `_NO_CABLE`), and slash-joined spec dumps containing only W / V / mm values (e.g. `/120MM/450MM`). Return null only if no readable model exists anywhere.
Additionally reject descriptive phrases when they appear as prefixes or noise: `Panel`, `Radiator`, `240mm Radiator`, `NVIDIA Limited Edition`. Discard any token that looks like a manufacturer SKU (3+ hyphens with digits, or 8+ chars with >=30% digits, or an `R-XXX-YYY`-style code) when a human-readable product name exists elsewhere in the raw text. Strip truncation markers (`...`, `…`) and leading stray punctuation (`, - `). Cyrillic orphan prefixes like `А- -` must be removed.
Also reject: (a) any string containing underscores — retailer-mangled forms such as `AG400_DIGITAL_PLUS`, `MAG_CORELIQUID_A15_360`, `LQ360_ULTRA_WH_ARGB` — return null and the product name will be used instead; (b) strings that are only a socket/platform list such as `AM4/AM5`, `LGA1700`, `Intel/AMD`; (c) packaging suffixes like `/Bulk`, `/Retail`, `/OEM`, `/Tray`, `/Box` — strip them; (d) short all-caps alphanumeric tokens like `BW020`, `EY3B001` when a descriptive product name is present elsewhere. For Noctua `.CH.BK`-style variant codes, strip trailing `.CH`, `.BK`, `.WH`, `.CHROMAX` etc. so `NH-D15.G2.CH.BK` becomes `NH-D15 G2`.
Rules:
- cooler_type: "AIO" for any liquid/water cooler — including Bulgarian "Водно" or "Водно охлаждане", sealed AIO units, open-loop blocks, waterblocks, and CPU blocks. "Air" for heatsink/tower/heatpipe-based coolers. Return null only if no cooling type can be inferred.
- socket_compatibility: exact codes only (LGA1700, LGA1851, LGA1200, LGA1151, LGA2066, AM5, AM4, sTRX4, SP5, etc.). Do not invent ranges or generic labels like "Intel" / "AMD". Return [] when no sockets are listed.
- cooler_height_mm: cooler tower height in mm (30-300). Accept "до NNN mm" / "NNN mm" / bare integer.
- tdp_w: cooler heat-dissipation capacity in watts (30-500). Accept "NNN W", "до NNN W", "TDP NNN", "капацитет NNN". Not fan wattage or CPU TDP label.
- fan_size_mm: single fan dimension only (120, 140, 200, etc.). Never the radiator length (240/280/360/420 mm).
- fan_count: count of bundled fans only. Sum parenthetical breakdowns like "4 x 120 mm (3 front; 1 rear)" -> 4. AIO 240 with dual fans -> 2.
- noise_db: in dBA. Strip "<" / "до" prefixes and trailing "MAX" / "макс" suffixes. Accept both dot and comma decimal separators ("24.6 dBA" and "24,6 dBA" both mean 24.6). Range 0-70 dBA.
- rpm_max: maximum RPM as integer. Accept both Latin "RPM" and Bulgarian "об/мин" units, and spec-row labels such as "Обороти", "Оборота в минута", "Оборот в минута", "Обороти на вентилатора". For ranges like "600-2000 RPM", "250 - 1500 RPM", or "250 - 1800 об/мин", take the upper bound (so 1800, not 250). Accept trailing "MAX" / "макс" suffixes ("1500 RPM MAX" -> 1500). Range 200-5000.
Skip non-cooler accessories such as thermal paste/grease, standalone fans without a heatsink, cable kits, fan hubs, and brackets. If the source is not a CPU cooler, return null for the cooler fields instead of inventing values.
Parser-first deterministic logic decides final product eligibility and normalization. Do not invent values when the source is ambiguous.
Prefer technical specification rows over marketing text. Use rows like "Съвместимост", "Тип", "Височина", "Мощност на охлаждане", "Размер на вентилатора" / "Размер на вентилаторите", "Брой вентилатори", "Ниво на шум", "Обороти", "Оборота в минута", "Оборот в минута" when present.
Bulgarian specs often use comma as the decimal separator (e.g. "24,6 dBA"). Treat "24,6" and "24.6" as equivalent.
Return null for unknown fields; never fabricate. Return only valid JSON — no commentary, no markdown fences.

Content:
{content}

Product name: {name}
Price (EUR): {price}
Product URL: {url}

Return only valid JSON matching the required keys. Use numbers for numeric fields and null when unknown.
"""
