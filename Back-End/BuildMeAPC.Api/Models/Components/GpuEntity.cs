using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("gpus")]
    public class GpuEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("pcb_manufacturer")]
        public string? PcbManufacturer { get; set; }

        [Column("pcb_series")]
        public string? PcbSeries { get; set; }

        [Column("vram_gb")]
        public int? VramGb { get; set; }

        [Column("memory_type")]
        public string? MemoryType { get; set; }

        [Column("memory_bus_bit")]
        public int? MemoryBusBit { get; set; }

        [Column("base_clock_mhz")]
        public double? BaseClockMhz { get; set; }

        [Column("boost_clock_mhz")]
        public double? BoostClockMhz { get; set; }

        [Column("tdp_w")]
        public int? TdpW { get; set; }

        [Column("interface")]
        public string? Interface { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
