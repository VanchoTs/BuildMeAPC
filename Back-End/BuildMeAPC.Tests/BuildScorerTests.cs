using BuildMeAPC.Api.Models.Components;
using BuildMeAPC.Api.Services;
using NUnit.Framework;

namespace BuildMeAPC.Tests
{
    [TestFixture]
    public class BuildScorerTests
    {
        private BuildScorer _scorer;

        [SetUp]
        public void Setup()
        {
            _scorer = new BuildScorer();
        }

        [Test]
        public void Score_X3D_GivesBonus()
        {
            // Use low specs to avoid 100% cap
            var combo1 = CreateLowSpecCombo();
            combo1.Cpu.Model = "Ryzen 7 7700";
            
            var combo2 = CreateLowSpecCombo();
            combo2.Cpu.Model = "Ryzen 7 7800X3D";

            var score1 = _scorer.Score(combo1);
            var score2 = _scorer.Score(combo2);

            Assert.That(score2.Gaming, Is.GreaterThan(score1.Gaming));
        }

        [Test]
        public void Score_Nvidia_GivesWorkstationBonus()
        {
            // Use absolute minimum specs to avoid 100% cap
            var combo1 = CreateLowSpecCombo();
            combo1.Cpu = new CpuEntity { Cores = 1, Threads = 1, BoostClockGhz = 1.0, PriceEur = 50 };
            combo1.Gpu!.Brand = "AMD";
            
            var combo2 = CreateLowSpecCombo();
            combo2.Cpu = new CpuEntity { Cores = 1, Threads = 1, BoostClockGhz = 1.0, PriceEur = 50 };
            combo2.Gpu!.Brand = "NVIDIA";

            var score1 = _scorer.Score(combo1);
            var score2 = _scorer.Score(combo2);

            Assert.That(score2.Workstation, Is.GreaterThan(score1.Workstation));
        }

        private BuildCombination CreateLowSpecCombo()
        {
            return new BuildCombination
            {
                // Significantly lower specs to ensure we stay below 100
                Cpu = new CpuEntity { Cores = 4, Threads = 8, BoostClockGhz = 3.5, TdpW = 65, PriceEur = 150 },
                Gpu = new GpuEntity { VramGb = 4, TdpW = 100, Brand = "AMD", PriceEur = 200 },
                Motherboard = new MotherboardEntity { PriceEur = 100 },
                Ram = new RamEntity { MemorySpeedMhz = 3200, MemoryAmount = "16GB", PriceEur = 60 },
                Ssd = new SsdEntity { WriteSpeedMbps = 1500, PriceEur = 50 },
                Psu = new PsuEntity { PriceEur = 60 },
                Case = new CaseEntity { PriceEur = 50 },
                Cooler = new CoolerEntity { PriceEur = 30 }
            };
        }
    }
}
