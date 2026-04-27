using BuildMeAPC.Api.DTOs;
using BuildMeAPC.Api.Models.Components;

namespace BuildMeAPC.Api.Services
{
    public class BuildService : IBuildService
    {
        private readonly CandidatePicker _picker;
        private readonly BudgetAllocator _allocator;
        private readonly BuildScorer _scorer;

        private static readonly (BuildTier tier, string name, string desc)[] Tiers =
        {
            (BuildTier.PricePerf, "Best Price-to-Performance",
                "Maximum raw performance per euro."),
            (BuildTier.Upgradeability, "Best Upgradeability",
                "Long-life socket, overbuilt motherboard and PSU headroom for future upgrades."),
            (BuildTier.Quality, "Best Price-to-Quality",
                "Top-tier brands: premium motherboard, high-efficiency PSU, quality cooling.")
        };

        public BuildService(
            CandidatePicker picker,
            BudgetAllocator allocator,
            BuildScorer scorer)
        {
            _picker = picker;
            _allocator = allocator;
            _scorer = scorer;
        }

        /// <summary>
        /// Main orchestration logic for generating three distinct PC builds (PricePerf, Upgradeability, Quality).
        /// Implements a 3-pass strategy to balance user requirements with market availability.
        /// </summary>
        public async Task<IReadOnlyList<BuildDto>> GenerateBuildsAsync(BuildRequest request)
        {
            var results = new List<BuildDto>();
            var usedCpuIds = new HashSet<int>();
            var usedGpuIds = new HashSet<int>();
            
            // Tight budgets need a looser overhead cap because fixed-price components 
            // (like SSDs or Coolers) take up a larger percentage of the total.
            var hardBudgetCap = request.Budget * (request.Budget < 800 ? 1.12 : 1.05);
            
            // Optimization: Skip discrete GPU selection for very low-budget 'general' usage builds.
            bool skipGpu = request.Usage == "general" && request.Budget < 600;

            foreach (var (tier, name, desc) in Tiers)
            {
                // Step 1: Allocate portions of the budget to each component category.
                var allocation = _allocator.Allocate(request.Budget, request.Usage, tier);

                BuildCombination? combo = null;

                // PASS A: Strict - Try to honor the exact RAM capacity requested by the user.
                // We try three price band multipliers (1.0, 1.5, 2.5) to find candidates.
                foreach (var mult in new[] { 1.0, 1.5, 2.5 })
                {
                    _picker.SetBandMultiplier(mult);
                    var pool = await _picker.PickAsync(request, allocation, tier, request.Budget);
                    combo = FindCompatibleCombination(
                        pool, usedCpuIds, usedGpuIds, hardBudgetCap,
                        request.RamGb, strictRam: true, skipGpu: skipGpu, tier: tier);
                    if (combo != null) break;
                }

                // PASS B: Adaptive RAM Downgrade - If no build was found, try reducing RAM.
                // This is crucial for builds where the budget can't support high RAM + high GPU.
                bool canDowngradeBelow16 = tier == BuildTier.Upgradeability || (request.Usage != "gaming" && request.Usage != "workstation");

                if (combo == null)
                {
                    foreach (var ramTry in AdaptiveRamSequence(request.RamGb))
                    {
                        // Minimum safety floor: Gaming/Workstation usually requires at least 16GB.
                        if (!canDowngradeBelow16 && ramTry < 16) continue;

                        foreach (var mult in new[] { 1.0, 1.5, 2.5 })
                        {
                            _picker.SetBandMultiplier(mult);
                            var pool = await _picker.PickAsync(request, allocation, tier, request.Budget);
                            combo = FindCompatibleCombination(
                                pool, usedCpuIds, usedGpuIds, hardBudgetCap,
                                ramTry, strictRam: true, skipGpu: skipGpu, tier: tier);
                            if (combo != null) break;
                        }
                        if (combo != null) break;
                    }
                }

                // PASS C: Last Resort - Loosen all RAM constraints to return *something*.
                if (combo == null && canDowngradeBelow16)
                {
                    foreach (var mult in new[] { 1.0, 1.5, 2.5 })
                    {
                        _picker.SetBandMultiplier(mult);
                        var pool = await _picker.PickAsync(request, allocation, tier, request.Budget);
                        combo = FindCompatibleCombination(
                            pool, usedCpuIds, usedGpuIds, hardBudgetCap,
                            request.RamGb, strictRam: false, skipGpu: skipGpu, tier: tier);
                        if (combo != null) break;
                    }
                }

                _picker.SetBandMultiplier(1.0); // Reset for next tier

                if (combo == null) continue;

                // Track used IDs to maximize variety across the three returned recommendations.
                usedCpuIds.Add(combo.Cpu.Id);
                if (combo.Gpu != null) usedGpuIds.Add(combo.Gpu.Id);

                results.Add(ToDto(combo, name, desc));
            }

            return results;
        }

        // Helper to generate a sequence of RAM capacities (e.g., 64 -> 32 -> 16 -> 8).
        private static IEnumerable<int> AdaptiveRamSequence(int requested)
        {
            var seen = new HashSet<int>();
            int cur = requested;
            while (cur >= 16)
            {
                cur /= 2;
                if (cur < 8) break;
                if (seen.Add(cur)) yield return cur;
            }
            if (seen.Add(8)) yield return 8;
        }

        /// <summary>
        /// A greedy nested loop search that validates hardware compatibility at every level.
        /// The order is strategic: CPU -> Mobo -> Cooler -> RAM -> Case -> GPU -> PSU -> SSD.
        /// This allows early-exit on socket or physical dimension mismatches.
        /// </summary>
        private static BuildCombination? FindCompatibleCombination(
            CandidatePool pool,
            HashSet<int> usedCpuIds,
            HashSet<int> usedGpuIds,
            double hardBudgetCap,
            int requestedRamGb,
            bool strictRam,
            bool skipGpu,
            BuildTier tier)
        {
            if (pool.Cpus.Count == 0 || pool.Motherboards.Count == 0 ||
                pool.Rams.Count == 0 || pool.Ssds.Count == 0 || pool.Psus.Count == 0 ||
                pool.Cases.Count == 0 || pool.Coolers.Count == 0)
            {
                return null;
            }
            if (!skipGpu && pool.Gpus.Count == 0) return null;

            var ramPool = pool.Rams
                .Where(r => !CompatibilityFilter.IsLaptopRam(r));
            
            if (tier == BuildTier.Upgradeability)
            {
                // Prefer 1x configurations for easier future upgrades
                ramPool = ramPool.OrderByDescending(r => r.MemoryAmount != null && r.MemoryAmount.ToLower().Contains("1x"))
                                 .ThenBy(r => r.PriceEur);
            }
            
            var desktopRams = ramPool.ToList();
            if (desktopRams.Count == 0) return null;

            // Pick cheapest SSD that honors requested size. Pool is pre-filtered
            // on size fallback + SATA cutoff, so order by price asc here keeps
            // tight budgets feasible.
            var ssdFixed = pool.Ssds.OrderBy(s => s.PriceEur ?? double.MaxValue).First();
            var ssdPrice = ssdFixed.PriceEur ?? 0;


            // GPU list for iteration: real pool or a single null-slot for skip path.
            var gpuIter = skipGpu ? new GpuEntity?[] { null } : pool.Gpus.Cast<GpuEntity?>().ToArray();

            for (int pass = 0; pass < 2; pass++)
            {
                foreach (var cpu in pool.Cpus)
                {
                    if (pass == 0 && usedCpuIds.Contains(cpu.Id)) continue;
                    var cpuPrice = cpu.PriceEur ?? 0;
                    if (cpuPrice + ssdPrice > hardBudgetCap) continue;

                    foreach (var mobo in pool.Motherboards)
                    {
                        if (!CompatibilityFilter.CpuFitsMobo(cpu, mobo)) continue;

                        // Upgradeability constraint: 4+ slots for high-end RAM builds
                        if (tier == BuildTier.Upgradeability && requestedRamGb >= 32)
                        {
                            if (mobo.RamSlots < 4) continue;
                        }

                        var runTotal2 = cpuPrice + (mobo.PriceEur ?? 0) + ssdPrice;
                        if (runTotal2 > hardBudgetCap) continue;

                        foreach (var cooler in pool.Coolers)
                        {
                            if (!CompatibilityFilter.CoolerFitsCpu(cooler, cpu)) continue;

                            // High-end CPU cooling rule (i7/i9, Ryzen 7/9)
                            var model = (cpu.Model ?? "").ToUpper();
                            bool isHighEnd = model.Contains("I7") || model.Contains("I9") || model.Contains("RYZEN 7") || model.Contains("RYZEN 9");
                            if (isHighEnd)
                            {
                                if (cooler.TdpW == null || cooler.TdpW < cpu.TdpW) continue;
                            }

                            var runTotal3 = runTotal2 + (cooler.PriceEur ?? 0);
                            if (runTotal3 > hardBudgetCap) continue;

                            foreach (var ram in desktopRams)
                            {
                                if (!CompatibilityFilter.RamFitsMobo(ram, mobo)) continue;
                                if (strictRam)
                                {
                                    var ramGb = ScraperUtils.ParseRamGb(ram.MemoryAmount);
                                    if (ramGb < requestedRamGb) continue;
                                }
                                var runTotal4 = runTotal3 + (ram.PriceEur ?? 0);
                                if (runTotal4 > hardBudgetCap) continue;

                                foreach (var pcCase in pool.Cases)
                                {
                                    if (!CompatibilityFilter.MoboFitsCase(mobo, pcCase)) continue;
                                    if (!CompatibilityFilter.CoolerFitsCase(cooler, pcCase)) continue;
                                    var runTotal5 = runTotal4 + (pcCase.PriceEur ?? 0);
                                    if (runTotal5 > hardBudgetCap) continue;

                                    foreach (var gpu in gpuIter)
                                    {
                                        if (!skipGpu && pass == 0 && gpu != null && usedGpuIds.Contains(gpu.Id)) continue;
                                        
                                        // Gaming constraint: CPU must not be more expensive than GPU.
                                        if (!skipGpu && pool.Usage == "gaming" && gpu != null && (cpu.PriceEur ?? 0) > (gpu.PriceEur ?? 0)) continue;

                                        var runTotal6 = runTotal5 + (gpu?.PriceEur ?? 0);
                                        if (runTotal6 > hardBudgetCap) continue;

                                        var psu = tier == BuildTier.Upgradeability
                                            ? CompatibilityFilter.PickPsuWithHeadroom(pool.Psus, cpu, gpu)
                                            : CompatibilityFilter.PickPsuForLoad(pool.Psus, cpu, gpu);
                                        if (psu == null) continue;
                                        if (runTotal6 + (psu.PriceEur ?? 0) > hardBudgetCap) continue;

                                        if (!skipGpu &&
                                            !CompatibilityFilter.MbPriceFair(cpu, gpu, mobo, pcCase, cooler))
                                            continue;

                                        return new BuildCombination
                                        {
                                            Cpu = cpu,
                                            Gpu = gpu,
                                            Motherboard = mobo,
                                            Ram = ram,
                                            Ssd = ssdFixed,
                                            Psu = psu,
                                            Case = pcCase,
                                            Cooler = cooler
                                        };
                                    }
                                }
                            }
                        }
                    }
                }
            }
            return null;
        }

        private BuildDto ToDto(BuildCombination combo, string name, string desc)
        {
            var scores = _scorer.Score(combo);
            var components = new List<ComponentDto> { CpuToDto(combo.Cpu) };
            if (combo.Gpu != null) components.Add(GpuToDto(combo.Gpu));
            components.Add(MoboToDto(combo.Motherboard));
            components.Add(RamToDto(combo.Ram));
            components.Add(SsdToDto(combo.Ssd));
            components.Add(PsuToDto(combo.Psu));
            components.Add(CaseToDto(combo.Case));
            components.Add(CoolerToDto(combo.Cooler));

            return new BuildDto
            {
                Id = Guid.NewGuid().ToString("N").Substring(0, 9),
                Name = name,
                Description = desc,
                TotalPrice = Math.Round(combo.TotalPrice, 2),
                Components = components,
                Scores = scores
            };
        }

        private static ComponentDto CpuToDto(CpuEntity c) => new()
        {
            Id = $"cpu-{c.Id}",
            Type = "CPU",
            Brand = c.Brand ?? "",
            Model = c.Model ?? "",
            Price = c.PriceEur ?? 0,
            Url = c.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "cores", c.Cores },
                { "threads", c.Threads },
                { "baseClockGhz", c.BaseClockGhz },
                { "boostClockGhz", c.BoostClockGhz },
                { "tdpW", c.TdpW },
                { "socket", c.Socket },
                { "memoryType", c.MemoryType }
            }
        };

        private static ComponentDto GpuToDto(GpuEntity g) => new()
        {
            Id = $"gpu-{g.Id}",
            Type = "GPU",
            Brand = string.IsNullOrEmpty(g.PcbManufacturer) ? (g.Brand ?? "") : g.PcbManufacturer,
            Model = $"{(string.IsNullOrEmpty(g.PcbManufacturer) ? "" : g.Brand + " ")}{g.Model}".Trim(),
            Price = g.PriceEur ?? 0,
            Url = g.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "vramGb", g.VramGb },
                { "memoryType", g.MemoryType },
                { "memoryBusBit", g.MemoryBusBit },
                { "boostClockMhz", g.BoostClockMhz },
                { "tdpW", g.TdpW },
                { "interface", g.Interface }
            }
        };

        private static ComponentDto MoboToDto(MotherboardEntity m) => new()
        {
            Id = $"mobo-{m.Id}",
            Type = "Motherboard",
            Brand = m.Brand ?? "",
            Model = m.Model ?? "",
            Price = m.PriceEur ?? 0,
            Url = m.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "formFactor", m.FormFactor },
                { "chipset", m.Chipset },
                { "socket", m.Socket },
                { "memoryType", m.MemoryType },
                { "ramSlots", m.RamSlots },
                { "maxRamSpeedMhz", m.MaxRamSpeedMhz },
                { "maxRamAmountGb", m.MaxRamAmountGb },
                { "onboardWifi", m.OnboardWifi }
            }
        };

        private static ComponentDto RamToDto(RamEntity r) => new()
        {
            Id = $"ram-{r.Id}",
            Type = "RAM",
            Brand = r.Brand ?? "",
            Model = r.Model ?? "",
            Price = r.PriceEur ?? 0,
            Url = r.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "memoryType", r.MemoryType },
                { "memoryAmount", r.MemoryAmount },
                { "memorySpeedMhz", r.MemorySpeedMhz },
                { "latency", r.Latency },
                { "formFactor", r.FormFactor }
            }
        };

        private static ComponentDto SsdToDto(SsdEntity s) => new()
        {
            Id = $"ssd-{s.Id}",
            Type = "SSD",
            Brand = s.Brand ?? "",
            Model = s.Model ?? "",
            Price = s.PriceEur ?? 0,
            Url = s.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "type", s.Type },
                { "storageSizeGb", s.StorageSizeGb },
                { "readSpeedMbps", s.ReadSpeedMbps },
                { "writeSpeedMbps", s.WriteSpeedMbps },
                { "interface", s.Interface },
                { "tbwTb", s.TbwTb }
            }
        };

        private static ComponentDto PsuToDto(PsuEntity p) => new()
        {
            Id = $"psu-{p.Id}",
            Type = "PSU",
            Brand = p.Brand ?? "",
            Model = p.Model ?? "",
            Price = p.PriceEur ?? 0,
            Url = p.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "powerW", p.PowerW },
                { "efficiency", p.Efficiency },
                { "certificate", p.Certificate },
                { "modularity", p.Modularity }
            }
        };

        private static ComponentDto CaseToDto(CaseEntity c) => new()
        {
            Id = $"case-{c.Id}",
            Type = "Case",
            Brand = c.Brand ?? "",
            Model = c.Model ?? "",
            Price = c.PriceEur ?? 0,
            Url = c.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "caseSize", c.CaseSize },
                { "motherboardFormFactors", c.MotherboardFormFactors },
                { "includedFans", c.IncludedFans },
                { "maxCpuCoolerMm", c.MaxCpuCoolerMm },
                { "maxGpuLengthMm", c.MaxGpuLengthMm },
                { "maxRadiatorMm", c.MaxRadiatorMm }
            }
        };

        private static ComponentDto CoolerToDto(CoolerEntity c) => new()
        {
            Id = $"cooler-{c.Id}",
            Type = "Cooler",
            Brand = c.Brand ?? "",
            Model = c.Model ?? "",
            Price = c.PriceEur ?? 0,
            Url = c.ProductUrl,
            Specs = new Dictionary<string, object?>
            {
                { "coolerType", c.CoolerType },
                { "socketCompatibility", c.SocketCompatibility },
                { "coolerHeightMm", c.CoolerHeightMm },
                { "tdpW", c.TdpW },
                { "fanSizeMm", c.FanSizeMm },
                { "fanCount", c.FanCount },
                { "noiseDb", c.NoiseDb },
                { "rpmMax", c.RpmMax }
            }
        };
    }
}
