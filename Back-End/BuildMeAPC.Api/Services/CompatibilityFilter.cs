using BuildMeAPC.Api.Models.Components;

namespace BuildMeAPC.Api.Services
{
    // Snapshot of one compatible combination that passed all hard constraints.
    public class BuildCombination
    {
        public CpuEntity Cpu { get; set; } = null!;
        // Null when skipGpu path used (general + budget<600, iGPU-only build).
        public GpuEntity? Gpu { get; set; }
        public MotherboardEntity Motherboard { get; set; } = null!;
        public RamEntity Ram { get; set; } = null!;
        public SsdEntity Ssd { get; set; } = null!;
        public PsuEntity Psu { get; set; } = null!;
        public CaseEntity Case { get; set; } = null!;
        public CoolerEntity Cooler { get; set; } = null!;

        public double TotalPrice =>
            (Cpu.PriceEur ?? 0) + (Gpu?.PriceEur ?? 0) + (Motherboard.PriceEur ?? 0) +
            (Ram.PriceEur ?? 0) + (Ssd.PriceEur ?? 0) + (Psu.PriceEur ?? 0) +
            (Case.PriceEur ?? 0) + (Cooler.PriceEur ?? 0);
    }

    public class CompatibilityFilter
    {
        private const double PsuHeadroom = 1.3;
        private const double PsuMaxOverhead = 2.2;
        private const double PsuMinWatt = 500.0;

        public static bool CpuFitsMobo(CpuEntity cpu, MotherboardEntity mobo) =>
            !string.IsNullOrEmpty(cpu.Socket) &&
            !string.IsNullOrEmpty(mobo.Socket) &&
            NormalizeSocket(cpu.Socket) == NormalizeSocket(mobo.Socket);

        // Safety net for scraper mis-tagging: any SODIMM / 260-pin / Laptop /
        // Notebook token anywhere in the RAM row classifies it as laptop RAM
        // regardless of conflicting values like "Other" or "PC".
        public static bool IsLaptopRam(RamEntity ram)
        {
            if (!string.IsNullOrEmpty(ram.FormFactor) &&
                ram.FormFactor.Equals("Laptop", StringComparison.OrdinalIgnoreCase))
                return true;

            var haystack = string.Join(" | ",
                ram.FormFactor ?? "",
                ram.Model ?? "",
                ram.MemoryType ?? "",
                ram.MemoryAmount ?? "").ToUpperInvariant();

            var tokens = new[]
            {
                "SODIMM", "SO-DIMM", "260-PIN", "260 PIN",
                "NOTEBOOK", "LAPTOP",
                "ЛАПТОП", "НОУТБУК",
            };
            return tokens.Any(t => haystack.Contains(t));
        }

        // Price fairness: MB, case and cooler must each cost strictly less
        // than the cheaper of CPU/GPU. Skip when CPU or GPU price unknown.
        public static bool MbPriceFair(
            CpuEntity cpu, GpuEntity? gpu,
            MotherboardEntity mobo, CaseEntity pcCase, CoolerEntity cooler)
        {
            if (!cpu.PriceEur.HasValue) return true;
            double cap;
            if (gpu != null && gpu.PriceEur.HasValue)
                cap = Math.Min(cpu.PriceEur.Value, gpu.PriceEur.Value);
            else
                cap = cpu.PriceEur.Value;
            if ((mobo.PriceEur ?? 0) >= cap) return false;
            if ((pcCase.PriceEur ?? 0) >= cap) return false;
            if ((cooler.PriceEur ?? 0) >= cap) return false;
            return true;
        }

        public static bool RamFitsMobo(RamEntity ram, MotherboardEntity mobo)
        {
            if (string.IsNullOrEmpty(ram.MemoryType) || string.IsNullOrEmpty(mobo.MemoryType))
                return false;
            if (!ram.MemoryType.Equals(mobo.MemoryType, StringComparison.OrdinalIgnoreCase))
                return false;
            if (ram.MemorySpeedMhz.HasValue && mobo.MaxRamSpeedMhz.HasValue &&
                ram.MemorySpeedMhz.Value > mobo.MaxRamSpeedMhz.Value * 1.05)
                return false;
            return true;
        }

        public static bool MoboFitsCase(MotherboardEntity mobo, CaseEntity pcCase)
        {
            if (string.IsNullOrEmpty(mobo.FormFactor)) return true;
            if (string.IsNullOrEmpty(pcCase.MotherboardFormFactors)) return true;

            var mob = NormalizeFormFactor(mobo.FormFactor);
            var supported = pcCase.MotherboardFormFactors
                .Split(new[] { ',', '/', ';' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(NormalizeFormFactor)
                .Where(s => !string.IsNullOrEmpty(s))
                .ToHashSet();
            return supported.Contains(mob);
        }

        // Canonicalize form-factor spellings: ATX / E-ATX / MATX / ITX
        private static string NormalizeFormFactor(string s)
        {
            var up = s.Trim().ToUpperInvariant()
                .Replace("-", "").Replace(" ", "").Replace("_", "");
            if (up.StartsWith("EATX") || up == "EXTENDEDATX") return "EATX";
            if (up.StartsWith("MICROATX") || up == "MATX" || up == "UATX" || up == "ΜATX") return "MATX";
            if (up.StartsWith("MINIITX") || up == "ITX" || up == "MITX") return "ITX";
            if (up == "ATX") return "ATX";
            return up;
        }

        public static bool CoolerFitsCpu(CoolerEntity cooler, CpuEntity cpu)
        {
            if (string.IsNullOrEmpty(cooler.SocketCompatibility) || string.IsNullOrEmpty(cpu.Socket))
                return true; // be permissive when data missing
            var cpuSocket = NormalizeSocket(cpu.Socket);
            return cooler.SocketCompatibility
                .Split(new[] { ',', '/', ';' }, StringSplitOptions.RemoveEmptyEntries)
                .Any(s => NormalizeSocket(s.Trim()) == cpuSocket);
        }

        public static bool CoolerFitsCase(CoolerEntity cooler, CaseEntity pcCase)
        {
            if (cooler.CoolerHeightMm.HasValue && pcCase.MaxCpuCoolerMm.HasValue &&
                cooler.CoolerHeightMm.Value > pcCase.MaxCpuCoolerMm.Value)
                return false;

            // AIO radiator size lives in the cooler model string; crude check.
            if (!string.IsNullOrEmpty(cooler.CoolerType) &&
                cooler.CoolerType.Contains("AIO", StringComparison.OrdinalIgnoreCase) &&
                pcCase.MaxRadiatorMm.HasValue)
            {
                var radMm = ExtractRadiatorMm(cooler.Model);
                if (radMm.HasValue && radMm.Value > pcCase.MaxRadiatorMm.Value)
                    return false;
            }
            return true;
        }

        public static bool PsuHandlesLoad(PsuEntity psu, CpuEntity cpu, GpuEntity? gpu)
        {
            if (!psu.PowerW.HasValue) return false;
            var required = ((cpu.TdpW ?? 65) + (gpu?.TdpW ?? 0)) * PsuHeadroom;
            return psu.PowerW.Value >= required;
        }

        // Smallest PSU >= required; reject ones wildly oversized for the load.
        // Pool has a real-world minimum (500W) — cap must never drop below it.
        public static PsuEntity? PickPsuForLoad(IEnumerable<PsuEntity> psus, CpuEntity cpu, GpuEntity? gpu)
        {
            var required = ((cpu.TdpW ?? 65) + (gpu?.TdpW ?? 0)) * PsuHeadroom;
            if (gpu == null) required = (cpu.TdpW ?? 65) * PsuHeadroom;
            var effectiveFloor = Math.Max(required, PsuMinWatt);
            var maxAllowed = Math.Max(required * PsuMaxOverhead, effectiveFloor + 200);
            return psus
                .Where(p => p.PowerW.HasValue &&
                            p.PowerW.Value >= effectiveFloor &&
                            p.PowerW.Value <= maxAllowed)
                .OrderBy(p => p.PowerW!.Value)
                .FirstOrDefault();
        }

        // Upgradeability tier: pick a PSU 150-300W above required to leave headroom
        // for GPU upgrades. Falls back to PickPsuForLoad if nothing in that band.
        public static PsuEntity? PickPsuWithHeadroom(IEnumerable<PsuEntity> psus, CpuEntity cpu, GpuEntity? gpu)
        {
            var baseLoad = (cpu.TdpW ?? 65) + (gpu?.TdpW ?? 0);
            var required = baseLoad * PsuHeadroom;
            var headroomLo = Math.Max(required + 150, PsuMinWatt);
            var headroomHi = required + 300;
            var list = psus.ToList();
            var picked = list
                .Where(p => p.PowerW.HasValue &&
                            p.PowerW.Value >= headroomLo &&
                            p.PowerW.Value <= headroomHi)
                .OrderBy(p => p.PowerW!.Value)
                .FirstOrDefault();
            return picked ?? PickPsuForLoad(list, cpu, gpu);
        }

        // CPU has integrated graphics?
        // Intel: model does NOT end with 'F' (covers F + KF; K/KS have iGPU).
        // AMD AM5 socket: all Ryzen 7000/8000/9000 have iGPU.
        // AMD older: model ends with 'G' (e.g. 5600G, 8600G APUs).
        public static bool HasIntegratedGraphics(CpuEntity cpu)
        {
            var brand = (cpu.Brand ?? "").Trim().ToUpperInvariant();
            var model = (cpu.Model ?? "").Trim().ToUpperInvariant();
            var socket = NormalizeSocket(cpu.Socket ?? "");

            if (brand == "INTEL")
            {
                if (string.IsNullOrEmpty(model)) return false;
                return !model.EndsWith("F");
            }
            if (brand == "AMD")
            {
                if (model.EndsWith("F")) return false;
                if (socket == "AM5") return true;
                if (model.EndsWith("G") || model.EndsWith("GE")) return true;
                return false;
            }
            return false;
        }

        // TODO: GPU length vs case width — skipped per user decision.

        private static string NormalizeSocket(string s) =>
            s.Trim().ToUpperInvariant().Replace(" ", "").Replace("SOCKET", "");

        private static int? ExtractRadiatorMm(string? model)
        {
            if (string.IsNullOrEmpty(model)) return null;
            foreach (var token in new[] { "360", "280", "240", "140", "120" })
            {
                if (model.Contains(token)) return int.Parse(token);
            }
            return null;
        }
    }
}
