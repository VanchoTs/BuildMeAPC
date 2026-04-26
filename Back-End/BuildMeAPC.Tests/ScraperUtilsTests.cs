using BuildMeAPC.Api.Services;
using NUnit.Framework;

namespace BuildMeAPC.Tests
{
    [TestFixture]
    public class ScraperUtilsTests
    {
        [Test]
        [TestCase("16GB", 16)]
        [TestCase("32 GB", 32)]
        [TestCase("2x8GB", 16)]
        [TestCase("2 x 16 GB", 32)]
        [TestCase("4x32GB", 128)]
        [TestCase("2x 8GB", 16)]
        [TestCase("2 x8GB", 16)]
        [TestCase("16 GB (2x8GB)", 16)]
        [TestCase("32GB Kit (2 x 16GB)", 32)]
        [TestCase("8GB (1x8GB)", 8)]
        [TestCase("unknown", 0)]
        [TestCase("", 0)]
        [TestCase(null, 0)]
        public void ParseRamGb_HandlesFormats(string? input, int expected)
        {
            Assert.That(ScraperUtils.ParseRamGb(input), Is.EqualTo(expected));
        }
    }
}
