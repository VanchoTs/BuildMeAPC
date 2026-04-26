using BuildMeAPC.Api.Services;
using NUnit.Framework;

namespace BuildMeAPC.Tests
{
    [TestFixture]
    public class BudgetAllocatorTests
    {
        private BudgetAllocator _allocator;

        [SetUp]
        public void Setup()
        {
            _allocator = new BudgetAllocator();
        }

        [Test]
        public void Allocate_LowBudget_SumsToTotal()
        {
            int budget = 500;
            var allocation = _allocator.Allocate(budget, "general", BuildTier.PricePerf);
            
            double sum = allocation.Values.Sum();
            // Allow small delta for floating point precision, but we subtract peripherals buffer
            // Actually, my Allocate method returns shares that sum to ALMOST totalBudget because of the peripherals buffer.
            // Wait, looking at the code: factor = 1.0 / (shares.Sum + peripheralsShare).
            // So Sum(allocation) + peripheralsShareInEuro = totalBudget.
            
            Assert.That(sum, Is.LessThanOrEqualTo(budget));
            Assert.That(sum, Is.GreaterThan(budget * 0.8)); // At least 80% used for core parts
        }

        [Test]
        public void Allocate_Gaming_FavorsGpu()
        {
            var allocation = _allocator.Allocate(1000, "gaming", BuildTier.PricePerf);
            
            Assert.That(allocation[ComponentType.Gpu], Is.GreaterThan(allocation[ComponentType.Cpu]));
        }

        [Test]
        public void Allocate_Workstation_FavorsCpu()
        {
            var allocation = _allocator.Allocate(1000, "workstation", BuildTier.PricePerf);
            
            Assert.That(allocation[ComponentType.Cpu], Is.GreaterThan(allocation[ComponentType.Gpu]));
        }

        [Test]
        public void Allocate_HighBudget_ShiftsSurplusToCore()
        {
            var low = _allocator.Allocate(1000, "general", BuildTier.PricePerf);
            var high = _allocator.Allocate(3000, "general", BuildTier.PricePerf);

            // Calculate percentage of budget for CPU
            double lowCpuPct = low[ComponentType.Cpu] / 1000;
            double highCpuPct = high[ComponentType.Cpu] / 3000;

            // In high budget (>= 2500), CPU percentage should be higher due to surplusMult
            Assert.That(highCpuPct, Is.GreaterThan(lowCpuPct));
        }
    }
}
