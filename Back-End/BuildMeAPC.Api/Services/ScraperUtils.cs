using System.Text.RegularExpressions;

namespace BuildMeAPC.Api.Services
{
    public static class ScraperUtils
    {
        /// <summary>
        /// Parses a RAM capacity string (e.g. "16GB", "2x8GB", "2 x 16 GB") into total GB.
        /// Returns 0 if parsing fails.
        /// </summary>
        public static int ParseRamGb(string? memoryAmount)
        {
            if (string.IsNullOrWhiteSpace(memoryAmount)) return 0;

            // Handle "2x8GB" or "2 x 16 GB"
            var m = Regex.Match(
                memoryAmount, @"(\d+)\s*[xX×]\s*(\d+)\s*GB",
                RegexOptions.IgnoreCase);
            if (m.Success)
            {
                if (int.TryParse(m.Groups[1].Value, out var count) &&
                    int.TryParse(m.Groups[2].Value, out var size))
                {
                    return count * size;
                }
            }

            // Handle "16GB" or "16 GB"
            var single = Regex.Match(
                memoryAmount, @"(\d+)\s*GB",
                RegexOptions.IgnoreCase);
            if (single.Success)
            {
                if (int.TryParse(single.Groups[1].Value, out var val))
                {
                    return val;
                }
            }

            return 0;
        }
    }
}
