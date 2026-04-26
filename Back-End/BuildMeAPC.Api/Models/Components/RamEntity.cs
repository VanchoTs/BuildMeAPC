using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("rams")]
    public class RamEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("memory_type")]
        public string? MemoryType { get; set; }

        [Column("memory_amount")]
        public string? MemoryAmount { get; set; }

        [Column("memory_speed_mhz")]
        public int? MemorySpeedMhz { get; set; }

        [Column("latency")]
        public string? Latency { get; set; }

        [Column("form_factor")]
        public string? FormFactor { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
