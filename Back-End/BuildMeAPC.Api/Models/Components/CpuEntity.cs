using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("cpus")]
    public class CpuEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("cores")]
        public int? Cores { get; set; }

        [Column("threads")]
        public int? Threads { get; set; }

        [Column("base_clock_ghz")]
        public double? BaseClockGhz { get; set; }

        [Column("boost_clock_ghz")]
        public double? BoostClockGhz { get; set; }

        [Column("tdp_w")]
        public int? TdpW { get; set; }

        [Column("socket")]
        public string? Socket { get; set; }

        [Column("memory_type")]
        public string? MemoryType { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
