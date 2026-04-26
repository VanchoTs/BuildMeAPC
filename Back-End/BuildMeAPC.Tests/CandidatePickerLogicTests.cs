using BuildMeAPC.Api.Services;
using NUnit.Framework;
using System.Reflection;

namespace BuildMeAPC.Tests
{
    [TestFixture]
    public class CandidatePickerLogicTests
    {
        [Test]
        [TestCase("{\"m2_slots\": [\"slot1\", \"slot2\"], \"usb_ports\": 6}", 2, 6, false)]
        [TestCase("{\"m2_slots\": 3, \"usb_ports\": {\"type-a\": 4, \"type-c\": 2}}", 3, 6, false)]
        [TestCase("{\"m2_slots\": 4, \"pcie_gen5\": true}", 4, 0, true)]
        [TestCase("{\"m2_slots\": 2, \"pci_slots\": [\"pcie 5.0 x16\"]}", 2, 0, true)]
        [TestCase("invalid json", 0, 0, false)]
        [TestCase("", 0, 0, false)]
        [TestCase(null, 0, 0, false)]
        public void ParseMoboIo_HandlesVariousFormats(string? json, int expectedM2, int expectedUsb, bool expectedGen5)
        {
            var method = typeof(CandidatePicker).GetMethod("ParseMoboIo", 
                BindingFlags.NonPublic | BindingFlags.Static);
            
            var result = method!.Invoke(null, new object[] { json });
            
            // Result is a ValueTuple (int m2Count, int usbCount, bool gen5)
            // In NUnit, we can decompose it or access fields
            var (m2, usb, gen5) = ((int, int, bool))result!;

            Assert.Multiple(() =>
            {
                Assert.That(m2, Is.EqualTo(expectedM2), "M.2 Count mismatch");
                Assert.That(usb, Is.EqualTo(expectedUsb), "USB Count mismatch");
                Assert.That(gen5, Is.EqualTo(expectedGen5), "PCIe Gen5 detection mismatch");
            });
        }
    }
}
