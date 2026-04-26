using System.Text.Json;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.DTOs;
using BuildMeAPC.Api.Models.Components;
using Microsoft.EntityFrameworkCore;

namespace BuildMeAPC.Api.Services
{
    // Groups all short-lists per component type for one tier of a build request.
    public class CandidatePool
    {
        public string Usage { get; set; } = string.Empty;
        public List<CpuEntity> Cpus { get; set; } = new();
        public List<GpuEntity> Gpus { get; set; } = new();
        public List<MotherboardEntity> Motherboards { get; set; } = new();
        public List<RamEntity> Rams { get; set; } = new();
        public List<SsdEntity> Ssds { get; set; } = new();
        public List<PsuEntity> Psus { get; set; } = new();
        public List<CaseEntity> Cases { get; set; } = new();
        public List<CoolerEntity> Coolers { get; set; } = new();
    }

    public class CandidatePicker
    {
        private readonly AppDbContext _db;
        private const int Limit = 15;
        private const double BandLow = 0.55;
        private const double BandHigh = 1.60;
        private double _bandMult = 1.0;

        // Upgrade-friendly long-life sockets.
        private static readonly HashSet<string> UpgradeSockets = new(StringComparer.OrdinalIgnoreCase)
        {
            "AM5", "LGA1851"
        };

        // Quality tier brand whitelists (case-insensitive substring match).
        private static readonly string[] MbQualityBrands =
            { "ASUS", "MSI", "GIGABYTE", "ASROCK" };
        private static readonly string[] PsuQualityBrands =
            { "SEASONIC", "CORSAIR", "BE QUIET", "EVGA", "COOLER MASTER" };
        private static readonly string[] CoolerQualityBrands =
            { "NOCTUA", "BE QUIET", "ARCTIC", "COOLER MASTER" };
        private static readonly string[] SsdQualityBrands =
            { "SAMSUNG", "CRUCIAL", "WESTERN DIGITAL", "WD", "KINGSTON", "SEAGATE", "SABRENT", "SK HYNIX" }; // Excludes APACER

        // 80 PLUS tiers that meet ≥90% efficiency.
        private static readonly string[] EfficiencyTiers90 = { "PLATINUM", "TITANIUM" };

        public CandidatePicker(AppDbContext db)
        {
            _db = db;
        }

        public void SetBandMultiplier(double mult) => _bandMult = mult;

        public async Task<CandidatePool> PickAsync(
            BuildRequest req,
            Dictionary<ComponentType, double> allocation,
            BuildTier tier,
            int totalBudget)
        {
            bool skipGpu = req.Usage == "general" && totalBudget < 600;

            var pool = new CandidatePool
            {
                Usage = req.Usage,
                Cpus = await PickCpus(req, allocation[ComponentType.Cpu], tier, skipGpu),
                Gpus = skipGpu
                    ? new List<GpuEntity>()
                    : await PickGpus(req, allocation[ComponentType.Gpu], tier),
                Motherboards = await PickMobos(req, allocation[ComponentType.Motherboard], tier, totalBudget),
                Rams = await PickRams(req, allocation[ComponentType.Ram]),
                Ssds = await PickSsds(req, allocation[ComponentType.Ssd], totalBudget, tier),
                Psus = await PickPsus(req, allocation[ComponentType.Psu], tier),
                Cases = await PickCases(req, allocation[ComponentType.Case]),
                Coolers = await PickCoolers(req, allocation[ComponentType.Cooler], tier)
            };
            return pool;
        }

        private async Task<List<CpuEntity>> PickCpus(
            BuildRequest req, double target, BuildTier tier, bool requireIgpu)
        {
            var (lo, hi) = Band(target);
            var q = _db.Cpus.AsNoTracking()
                .Where(c => c.PriceEur != null && c.PriceEur >= lo && c.PriceEur <= hi);

            if (!string.IsNullOrEmpty(req.CpuBrandPref))
            {
                var brand = req.CpuBrandPref.ToLower();
                q = q.Where(c => c.Brand != null && c.Brand.ToLower() == brand);
            }

            // Pull a wider pool; we re-rank in memory for X3D bonus + iGPU/socket filters.
            // Order by price so cheap iGPU CPUs survive the Take cap on low-budget paths.
            var raw = await q.OrderBy(c => c.PriceEur).Take(Limit * 6).ToListAsync();

            if (tier == BuildTier.Upgradeability)
            {
                // AM5 is preferred over LGA1851 for long-term support
                raw = raw.OrderByDescending(c => c.Socket != null && c.Socket.ToUpper().Contains("AM5"))
                         .ThenBy(c => c.PriceEur)
                         .ToList();

                raw = raw.Where(c =>
                    !string.IsNullOrEmpty(c.Socket) &&
                    UpgradeSockets.Contains(c.Socket.Trim().Replace(" ", ""))).ToList();
            }

            if (requireIgpu || tier == BuildTier.Quality)
            {
                raw = raw.Where(CompatibilityFilter.HasIntegratedGraphics).ToList();
            }

            double Score(CpuEntity c)
            {
                var baseScore = (double)(c.Cores ?? 0) * (c.Threads ?? 0) * (c.BoostClockGhz ?? 0.0)
                                / (c.PriceEur ?? 1.0);
                if (req.Usage == "gaming" &&
                    !string.IsNullOrEmpty(c.Model) &&
                    c.Model.ToUpperInvariant().Contains("X3D"))
                    baseScore *= 1.25;
                return baseScore;
            }

            // Tight-budget iGPU paths need cheap CPUs surfaced; Score prefers core
            // count which pushes €200+ CPUs to the top and starves €500 builds.
            if (requireIgpu)
                return raw.OrderBy(c => c.PriceEur).Take(Limit).ToList();
            return raw.OrderByDescending(Score).Take(Limit).ToList();
        }

        private async Task<List<GpuEntity>> PickGpus(
            BuildRequest req, double target, BuildTier tier)
        {
            var (lo, hi) = Band(target);
            var q = _db.Gpus.AsNoTracking()
                .Where(g => g.PriceEur != null && g.PriceEur >= lo && g.PriceEur <= hi);

            // Workstation: Heavily favor NVIDIA for CUDA
            if (req.Usage == "workstation")
            {
                var nvQ = q.Where(g => g.Brand != null && (g.Brand.ToUpper().Contains("NVIDIA") || g.Brand.ToUpper().Contains("GEFORCE")));
                if (await nvQ.AnyAsync()) q = nvQ;
            }

            // Gaming/Workstation: Try to pick GPUs with at least 8/12GB VRAM.
            if (req.Usage == "gaming" || req.Usage == "workstation")
            {
                var vramLimit = req.Usage == "workstation" ? 12 : 8;
                var vramQ = q.Where(g => g.VramGb != null && g.VramGb >= vramLimit);
                if (await vramQ.AnyAsync()) q = vramQ;
            }

            if (!string.IsNullOrEmpty(req.GpuBrandPref))
            {
                var brand = req.GpuBrandPref.ToLower();
                q = q.Where(g =>
                    (g.Brand != null && g.Brand.ToLower() == brand) ||
                    (g.PcbManufacturer != null && g.PcbManufacturer.ToLower() == brand));
            }

            var raw = await q.Take(Limit * 3).ToListAsync();

            double Score(GpuEntity g)
            {
                // Prioritize VRAM for workstations
                double vramWeight = req.Usage == "workstation" ? 3.0 : 1.0;
                
                // For expensive builds, price should NOT be a divisor (we want raw power, not value)
                double priceWeight = g.PriceEur >= 800 ? 0.2 : 1.0;
                
                var baseScore = (double)(g.VramGb ?? 0) * vramWeight * (g.TdpW ?? 0) / (g.PriceEur * priceWeight ?? 1.0);
                
                // Workstation: NVIDIA bias
                if (req.Usage == "workstation")
                {
                    var brand = (g.Brand ?? "").ToUpperInvariant();
                    if (brand.Contains("NVIDIA") || brand.Contains("GEFORCE") || brand.Contains("RTX"))
                        baseScore *= 2.0; 
                }
                return baseScore;
            }

            return raw.OrderByDescending(Score).Take(Limit).ToList();
        }

        private async Task<List<MotherboardEntity>> PickMobos(
            BuildRequest req, double target, BuildTier tier, int totalBudget)
        {
            var (lo, hi) = Band(target);
            var q = _db.Motherboards.AsNoTracking()
                .Where(m => m.PriceEur != null && m.PriceEur >= lo && m.PriceEur <= hi);

            // High-end Quality builds: Hard block B/H chipsets.
            if (tier == BuildTier.Quality && totalBudget >= 1800)
            {
                q = q.Where(m => m.Chipset != null && 
                                 (m.Chipset.ToUpper().StartsWith("X") || m.Chipset.ToUpper().StartsWith("Z")));
            }

            if (req.WifiRequired)
            {
                q = q.Where(m => m.OnboardWifi != null && m.OnboardWifi != "" &&
                                 m.OnboardWifi.ToLower() != "no" &&
                                 m.OnboardWifi.ToLower() != "none" &&
                                 m.OnboardWifi.ToLower() != "not present");
            }

            // Quality tier: hard brand filter.
            if (tier == BuildTier.Quality)
            {
                q = q.Where(m => m.Brand != null &&
                    (m.Brand.ToUpper().Contains("ASUS") ||
                     m.Brand.ToUpper().Contains("MSI") ||
                     m.Brand.ToUpper().Contains("GIGABYTE") ||
                     m.Brand.ToUpper().Contains("ASROCK")));
            }

            // Order SQL-side by price so cheap boards always survive the Take cap.
            // Required for low-budget paths (iGPU builds) where MB must price
            // below the CPU and only the cheapest AM4/H610 boards qualify.
            var raw = await q.OrderBy(m => m.PriceEur).Take(Limit * 6).ToListAsync();

            double Score(MotherboardEntity m)
            {
                var (m2Count, usbCount, gen5) = ParseMoboIo(m.IoJson);
                double s = (m.RamSlots ?? 0) * 100 + (m.MaxRamSpeedMhz ?? 0);

                // Chipset quality bonus for expensive builds
                var chipset = (m.Chipset ?? "").ToUpper();
                if (totalBudget >= 1800 || tier == BuildTier.Quality)
                {
                    if (chipset.StartsWith("X") || chipset.StartsWith("Z")) s += 1000;
                }

                if (tier == BuildTier.Upgradeability)
                {
                    s += m2Count * 200;
                    s += (m.MaxRamAmountGb ?? 0) * 2;
                    if (gen5) s += 500;
                    // Bonus for 4 slots if user wants a lot of RAM (>=32GB)
                    if (req.RamGb >= 32 && m.RamSlots >= 4) s += 2000;
                }
                if (req.Usage == "workstation")
                {
                    s += m2Count * 150;
                    s += usbCount * 15;
                }
                // General low-budget: prefer cheaper.
                if (req.Usage == "general" && totalBudget < 600)
                    s -= (m.PriceEur ?? 0) * 2;
                // Tiebreak: cheaper wins.
                s -= (m.PriceEur ?? 0) * 0.1;
                return s;
            }

            return raw.OrderByDescending(Score).ThenBy(m => m.PriceEur).Take(Limit).ToList();
        }

        private async Task<List<RamEntity>> PickRams(BuildRequest req, double target)
        {
            var (lo, hi) = Band(target);
            var q = _db.Rams.AsNoTracking()
                .Where(r => r.PriceEur != null && r.PriceEur >= lo && r.PriceEur <= hi)
                .Where(r => r.FormFactor == null || r.FormFactor.ToLower() != "laptop");

            return await q
                .OrderByDescending(r => r.MemorySpeedMhz ?? 0)
                .Take(Limit * 2)
                .ToListAsync();
        }

        private async Task<List<SsdEntity>> PickSsds(
            BuildRequest req, double target, int totalBudget, BuildTier tier)
        {
            var (lo, hi) = Band(target);
            var q = _db.Ssds.AsNoTracking()
                .Where(s => s.PriceEur != null && s.PriceEur >= lo && s.PriceEur <= hi);

            // Quality tier: hard brand filter. Also NO SATA allowed for Quality tier.
            if (tier == BuildTier.Quality)
            {
                q = q.Where(s => s.Brand != null &&
                    SsdQualityBrands.Any(b => s.Brand.ToUpper().Contains(b)));

                q = q.Where(s =>
                    (s.Interface == null || !s.Interface.ToUpper().Contains("SATA")) &&
                    (s.Type == null || s.Type.ToUpper() != "SATA"));
            }

            // High-end builds: no SATA SSDs.
            if (totalBudget >= 1200)
            {
                q = q.Where(s =>
                    (s.Interface == null || !s.Interface.ToUpper().Contains("SATA")) &&
                    (s.Type == null || s.Type.ToUpper() != "SATA"));
            }

            // Try requested size, then halve progressively (1TB → 512 → 256).
            int[] sizeFallbacks;
            int req_gb = req.StorageGb;
            if (req_gb >= 1000)
                sizeFallbacks = new[] { req_gb, 512, 256 };
            else if (req_gb >= 512)
                sizeFallbacks = new[] { req_gb, 256 };
            else
                sizeFallbacks = new[] { req_gb };

            foreach (var minGb in sizeFallbacks)
            {
                var tolerance = minGb * 0.8;
                var list = await q
                    .Where(s => s.StorageSizeGb != null && s.StorageSizeGb >= tolerance)
                    .OrderByDescending(s =>
                        ((double)((s.ReadSpeedMbps ?? 0) + (s.WriteSpeedMbps ?? 0)))
                        / (s.PriceEur ?? 1.0))
                    .Take(Limit)
                    .ToListAsync();
                if (list.Count > 0) return list;
            }
            return new List<SsdEntity>();
        }

        private async Task<List<PsuEntity>> PickPsus(
            BuildRequest req, double target, BuildTier tier)
        {
            var q = _db.Psus.AsNoTracking()
                .Where(p => p.PowerW != null && p.PowerW >= 500 && p.PriceEur != null)
                .Where(p => !string.IsNullOrEmpty(p.PhysicalSize)); // Avoid server/unknown PSUs

            if (tier == BuildTier.Quality)
            {
                q = q.Where(p => p.Brand != null &&
                    (p.Brand.ToUpper().Contains("SEASONIC") ||
                     p.Brand.ToUpper().Contains("CORSAIR") ||
                     p.Brand.ToUpper().Contains("BE QUIET") ||
                     p.Brand.ToUpper().Contains("EVGA") ||
                     p.Brand.ToUpper().Contains("COOLER MASTER")));
                // Efficiency ≥90%: Platinum or Titanium.
                q = q.Where(p =>
                    (p.Efficiency != null &&
                        (p.Efficiency.ToUpper().Contains("PLATINUM") ||
                         p.Efficiency.ToUpper().Contains("TITANIUM"))) ||
                    (p.Certificate != null &&
                        (p.Certificate.ToUpper().Contains("PLATINUM") ||
                         p.Certificate.ToUpper().Contains("TITANIUM"))));
            }

            return await q
                .OrderBy(p => p.PowerW)
                .ThenBy(p => p.PriceEur)
                .ToListAsync();
        }

        private async Task<List<CaseEntity>> PickCases(BuildRequest req, double target)
        {
            var (lo, hi) = Band(target);
            return await _db.Cases.AsNoTracking()
                .Where(c => c.PriceEur != null && c.PriceEur >= lo && c.PriceEur <= hi)
                .OrderBy(c => c.PriceEur)
                .Take(Limit * 2)
                .ToListAsync();
        }

        private async Task<List<CoolerEntity>> PickCoolers(
            BuildRequest req, double target, BuildTier tier)
        {
            var (lo, hi) = Band(target);
            var q = _db.Coolers.AsNoTracking()
                .Where(c => c.PriceEur != null && c.PriceEur >= lo && c.PriceEur <= hi);

            // For expensive builds, only use coolers with a known TDP rating
            if (target >= 40)
            {
                q = q.Where(c => c.TdpW != null && c.TdpW > 0);
            }

            if (tier == BuildTier.Quality)
            {
                q = q.Where(c => c.Brand != null &&
                    (c.Brand.ToUpper().Contains("NOCTUA") ||
                     c.Brand.ToUpper().Contains("BE QUIET") ||
                     c.Brand.ToUpper().Contains("ARCTIC") ||
                     c.Brand.ToUpper().Contains("COOLER MASTER")));
            }

            double Score(CoolerEntity c)
            {
                var s = (double)(c.TdpW ?? 0);
                if (tier == BuildTier.Upgradeability) s *= 2.0; // Prioritize cooling headroom
                s -= (c.PriceEur ?? 0) * 0.1;
                return s;
            }

            var list = await q.ToListAsync();
            return list
                .OrderByDescending(Score)
                .Take(Limit * 3)
                .ToList();
        }

        private (double lo, double hi) Band(double target) =>
            (target * BandLow / _bandMult, target * BandHigh * _bandMult);

        // Parse motherboard io_json jsonb: count m.2 slots, usb ports, detect PCIe Gen5.
        private static (int m2Count, int usbCount, bool gen5) ParseMoboIo(string? json)
        {
            if (string.IsNullOrWhiteSpace(json)) return (0, 0, false);
            int m2 = 0, usb = 0;
            bool gen5 = json.ToUpperInvariant().Replace(" ", "")
                .Contains("GEN5") || json.Contains("5.0");
            try
            {
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;
                if (root.TryGetProperty("m2_slots", out var m2El))
                    m2 = CountOrNumber(m2El);
                if (root.TryGetProperty("usb_ports", out var usbEl))
                    usb = CountOrNumber(usbEl);
            }
            catch { }
            return (m2, usb, gen5);
        }

        private static int CountOrNumber(JsonElement el)
        {
            switch (el.ValueKind)
            {
                case JsonValueKind.Array:
                    return el.GetArrayLength();
                case JsonValueKind.Number:
                    return el.TryGetInt32(out var n) ? n : 0;
                case JsonValueKind.Object:
                    int total = 0;
                    foreach (var p in el.EnumerateObject())
                    {
                        if (p.Value.ValueKind == JsonValueKind.Number &&
                            p.Value.TryGetInt32(out var v)) total += v;
                        else if (p.Value.ValueKind == JsonValueKind.Array) total += p.Value.GetArrayLength();
                    }
                    return total;
                default:
                    return 0;
            }
        }
    }
}
