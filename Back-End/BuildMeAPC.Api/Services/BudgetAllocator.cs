namespace BuildMeAPC.Api.Services
{
    public enum ComponentType
    {
        Cpu,
        Gpu,
        Motherboard,
        Ram,
        Ssd,
        Psu,
        Case,
        Cooler
    }

    public enum BuildTier
    {
        PricePerf,
        Upgradeability,
        Quality
    }

    public class BudgetAllocator
    {
        private static readonly Dictionary<ComponentType, double> BaseShares = new()
        {
            { ComponentType.Gpu, 0.30 },
            { ComponentType.Cpu, 0.18 },
            { ComponentType.Motherboard, 0.08 },
            { ComponentType.Ram, 0.08 },
            { ComponentType.Ssd, 0.08 },
            { ComponentType.Psu, 0.08 },
            { ComponentType.Case, 0.07 },
            { ComponentType.Cooler, 0.05 }
        };

        private const double PeripheralsBuffer = 0.08;

        public Dictionary<ComponentType, double> Allocate(
            int totalBudget,
            string usage,
            BuildTier tier)
        {
            var shares = new Dictionary<ComponentType, double>(BaseShares);

            ApplyUsageMultipliers(shares, usage, out double peripheralsMult);
            ApplyTierBias(shares, tier);

            // Dynamic shift for high budgets (>= 1500):
            // Move surplus to CPU/GPU.
            if (totalBudget >= 1500)
            {
                double surplusMult = totalBudget >= 2500 ? 0.45 : 0.25;
                
                double cpuSurplus = shares[ComponentType.Cpu] * surplusMult;
                double gpuSurplus = shares[ComponentType.Gpu] * (surplusMult * 1.2); // Even more for GPU

                shares[ComponentType.Cpu] += cpuSurplus;
                shares[ComponentType.Gpu] += gpuSurplus;
                
                // Reduce floor components further
                shares[ComponentType.Case] *= 0.75;
                shares[ComponentType.Cooler] *= 0.75;
                shares[ComponentType.Psu] *= 0.85;
                shares[ComponentType.Ssd] *= 0.90;
            }

            var peripheralsShare = PeripheralsBuffer * peripheralsMult;
            var sum = shares.Values.Sum() + peripheralsShare;
            var factor = 1.0 / sum;

            var result = new Dictionary<ComponentType, double>();
            foreach (var kv in shares)
            {
                result[kv.Key] = kv.Value * factor * totalBudget;
            }
            return result;
        }

        private static void ApplyUsageMultipliers(
            Dictionary<ComponentType, double> shares,
            string usage,
            out double peripheralsMult)
        {
            switch (usage)
            {
                case "gaming":
                    shares[ComponentType.Gpu] *= 1.50; // Heavy GPU bias
                    shares[ComponentType.Cpu] *= 0.80; // Lean CPU to fund GPU
                    shares[ComponentType.Ram] *= 0.85;
                    shares[ComponentType.Ssd] *= 0.85;
                    shares[ComponentType.Cooler] *= 0.85;
                    peripheralsMult = 0.60;
                    break;
                case "workstation":
                    shares[ComponentType.Gpu] *= 1.10; // Boost GPU for rendering/editing
                    shares[ComponentType.Cpu] *= 2.00; // Heavy CPU for multi-threaded tasks
                    shares[ComponentType.Motherboard] *= 1.10;
                    shares[ComponentType.Ram] *= 1.40;
                    shares[ComponentType.Ssd] *= 1.20;
                    shares[ComponentType.Cooler] *= 1.20;
                    peripheralsMult = 0.70;
                    break;
                default:
                    shares[ComponentType.Gpu] *= 0.90;
                    peripheralsMult = 1.00;
                    break;
            }
        }

        // Per-tier allocation bias:
        // PricePerf: neutral baseline.
        // Upgradeability: heavier MB+PSU for future-proofing, lighter case/cooler.
        // Quality: heavier MB+PSU+cooler (premium brands cost more); trim GPU share to fund it.
        private static void ApplyTierBias(
            Dictionary<ComponentType, double> shares,
            BuildTier tier)
        {
            switch (tier)
            {
                case BuildTier.Upgradeability:
                    shares[ComponentType.Motherboard] *= 1.25;
                    shares[ComponentType.Psu] *= 1.30;
                    shares[ComponentType.Case] *= 0.90;
                    shares[ComponentType.Cooler] *= 0.90;
                    break;
                case BuildTier.Quality:
                    shares[ComponentType.Motherboard] *= 1.20;
                    shares[ComponentType.Psu] *= 1.30;
                    shares[ComponentType.Cooler] *= 1.20;
                    shares[ComponentType.Gpu] *= 0.85;
                    break;
                // PricePerf: no change
            }
        }
    }
}
