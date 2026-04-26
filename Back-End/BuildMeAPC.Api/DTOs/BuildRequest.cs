using System.ComponentModel.DataAnnotations;

namespace BuildMeAPC.Api.DTOs
{
    public class BuildRequest
    {
        [Required]
        [Range(500, 100000)]
        public int Budget { get; set; }

        [Required]
        [RegularExpression("^(gaming|workstation|general)$")]
        public string Usage { get; set; } = "general";

        [Range(120, 16000)]
        public int StorageGb { get; set; } = 1000;

        [RegularExpression("^(1080p60|1080p144|1440p144|4k60)?$")]
        public string? Resolution { get; set; }

        [Range(8, 256)]
        public int RamGb { get; set; } = 16;

        [RegularExpression("^(AMD|Intel)?$")]
        public string? CpuBrandPref { get; set; }

        [RegularExpression("^(NVIDIA|AMD|Intel)?$")]
        public string? GpuBrandPref { get; set; }

        public bool WifiRequired { get; set; } = false;
    }
}
