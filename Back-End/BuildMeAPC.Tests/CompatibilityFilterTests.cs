using BuildMeAPC.Api.Models.Components;
using BuildMeAPC.Api.Services;
using NUnit.Framework;

namespace BuildMeAPC.Tests
{
    [TestFixture]
    public class CompatibilityFilterTests
    {
        [Test]
        [TestCase("DDR4", "8GB", "PC", "Desktop", false)]
        [TestCase("DDR4", "8GB", "SODIMM", "Desktop", true)]
        [TestCase("DDR4", "8GB", "Other", "Laptop", true)]
        [TestCase("DDR4", "8GB", "260-PIN", "Desktop", true)]
        [TestCase("DDR4", "8GB", "Notebook", "Desktop", true)]
        [TestCase("DDR4", "16GB", "Laptop Memory", "Other", true)]
        [TestCase("DDR4", "8GB", "Памет за лаптоп", "Desktop", true)]
        [TestCase("DDR4", "8GB", "Ноутбук памет", "Desktop", true)]
        public void IsLaptopRam_DetectsCorrectly(string type, string amount, string model, string ff, bool expected)
        {
            var ram = new RamEntity { MemoryType = type, MemoryAmount = amount, Model = model, FormFactor = ff };
            Assert.That(CompatibilityFilter.IsLaptopRam(ram), Is.EqualTo(expected));
        }

        [Test]
        [TestCase("Intel", "Core i5-12400", "LGA 1700", true)]
        [TestCase("Intel", "Core i5-12400F", "LGA 1700", false)]
        [TestCase("AMD", "Ryzen 5 7600", "AM5", true)]
        [TestCase("AMD", "Ryzen 5 5600X", "AM4", false)]
        [TestCase("AMD", "Ryzen 5 5600G", "AM4", true)]
        public void HasIntegratedGraphics_DetectsCorrectly(string brand, string model, string socket, bool expected)
        {
            var cpu = new CpuEntity { Brand = brand, Model = model, Socket = socket };
            Assert.That(CompatibilityFilter.HasIntegratedGraphics(cpu), Is.EqualTo(expected));
        }

        [Test]
        [TestCase("LGA 1700", "LGA1700", true)]
        [TestCase("Socket AM4", "am4", true)]
        [TestCase("AM5", "  Socket   AM5  ", true)]
        [TestCase("LGA1200", "lga 1200", true)]
        [TestCase("AM4", "LGA1700", false)]
        public void CpuFitsMobo_NormalizesSockets(string cpuSocket, string moboSocket, bool expected)
        {
            var cpu = new CpuEntity { Socket = cpuSocket };
            var mobo = new MotherboardEntity { Socket = moboSocket };
            Assert.That(CompatibilityFilter.CpuFitsMobo(cpu, mobo), Is.EqualTo(expected));
        }

        [Test]
        [TestCase("ATX", "ATX", true)]
        [TestCase("mATX", "ATX, Micro ATX", true)]
        [TestCase("Mini-ITX", "ATX, Micro ATX", false)]
        [TestCase("E-ATX", "EATX", true)]
        [TestCase("Micro-ATX", "uATX", true)]
        [TestCase("ITX", "Mini ITX; Micro ATX", true)]
        [TestCase("Extended ATX", "E-ATX", true)]
        public void MoboFitsCase_NormalizesFormFactors(string moboFF, string caseFFs, bool expected)
        {
            var mobo = new MotherboardEntity { FormFactor = moboFF };
            var pcCase = new CaseEntity { MotherboardFormFactors = caseFFs };
            Assert.That(CompatibilityFilter.MoboFitsCase(mobo, pcCase), Is.EqualTo(expected));
        }

        [Test]
        [TestCase("LGA 1700, AM4, AM5", "LGA 1700", true)]
        [TestCase("AM4/AM5", "Socket AM5", true)]
        [TestCase("LGA1200;LGA1151", "lga 1200", true)]
        [TestCase("AM4", "LGA1700", false)]
        public void CoolerFitsCpu_NormalizesSockets(string compatibility, string cpuSocket, bool expected)
        {
            var cooler = new CoolerEntity { SocketCompatibility = compatibility };
            var cpu = new CpuEntity { Socket = cpuSocket };
            Assert.That(CompatibilityFilter.CoolerFitsCpu(cooler, cpu), Is.EqualTo(expected));
        }

        [Test]
        public void PsuHandlesLoad_CalculatesCorrectly()
        {
            var cpu = new CpuEntity { TdpW = 100 };
            var gpu = new GpuEntity { TdpW = 200 };
            var psuSmall = new PsuEntity { PowerW = 350 }; // (100+200)*1.3 = 390
            var psuBig = new PsuEntity { PowerW = 500 };

            Assert.Multiple(() =>
            {
                Assert.That(CompatibilityFilter.PsuHandlesLoad(psuSmall, cpu, gpu), Is.False);
                Assert.That(CompatibilityFilter.PsuHandlesLoad(psuBig, cpu, gpu), Is.True);
            });
        }
    }
}
