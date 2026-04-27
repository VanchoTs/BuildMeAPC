using BuildMeAPC.Api.DTOs;

namespace BuildMeAPC.Api.Services
{
    public class BuildScorer
    {
        // Calibrated so a mid-range €1500 gaming build scores ~75.
        private const double GamingReference = 4500.0;
        private const double WorkstationReference = 1800.0;

        /// <summary>
        /// Calculates normalized 0-100 scores for Gaming, Workstation, and Value.
        /// Gaming is GPU-centric, Workstation is CPU/RAM-centric, and Value is a function of performance per euro.
        /// </summary>
        public BuildScoresDto Score(BuildCombination combo)
        {
            var gpuPower = (combo.Gpu?.VramGb ?? 0) * (combo.Gpu?.TdpW ?? 0);
            var cpuPower = (combo.Cpu.Cores ?? 0) * (combo.Cpu.Threads ?? 0) *
                           (combo.Cpu.BoostClockGhz ?? 0);
            var ramPower = (combo.Ram.MemorySpeedMhz ?? 0) * ScraperUtils.ParseRamGb(combo.Ram.MemoryAmount);
            var ssdWrite = combo.Ssd.WriteSpeedMbps ?? 0;

            var gamingRaw = gpuPower + 0.25 * cpuPower * 100 + 0.10 * ramPower / 100;
            // X3D gaming bonus: AMD's 3D V-Cache gives a sizable gaming uplift.
            if (!string.IsNullOrEmpty(combo.Cpu.Model) &&
                combo.Cpu.Model.ToUpperInvariant().Contains("X3D"))
                gamingRaw *= 1.25;

            var workstationRaw = cpuPower * 130 + ScraperUtils.ParseRamGb(combo.Ram.MemoryAmount) * 20 +
                                 ssdWrite / 10.0;
            // NVIDIA workstation bonus: CUDA ecosystem dominates pro workloads.
            if (combo.Gpu != null)
            {
                var gpuBrand = (combo.Gpu.Brand ?? "").ToUpperInvariant();
                if (gpuBrand.Contains("NVIDIA") || gpuBrand.Contains("GEFORCE"))
                    workstationRaw *= 1.15;
            }

            var gaming = Clamp(100.0 * gamingRaw / GamingReference);
            var workstation = Clamp(100.0 * workstationRaw / WorkstationReference);

            var price = Math.Max(combo.TotalPrice, 1.0);
            var valueRaw = (gaming + workstation) / (2.0 * price / 1000.0);
            var value = Clamp(valueRaw);

            return new BuildScoresDto
            {
                Gaming = (int)Math.Round(gaming),
                Workstation = (int)Math.Round(workstation),
                Value = (int)Math.Round(value)
            };
        }

        private static double Clamp(double v) => Math.Max(0, Math.Min(100, v));
    }
}
