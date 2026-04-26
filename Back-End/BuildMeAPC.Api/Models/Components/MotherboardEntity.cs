using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("motherboards")]
    public class MotherboardEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("form_factor")]
        public string? FormFactor { get; set; }

        [Column("chipset")]
        public string? Chipset { get; set; }

        [Column("socket")]
        public string? Socket { get; set; }

        [Column("memory_type")]
        public string? MemoryType { get; set; }

        [Column("ram_slots")]
        public int? RamSlots { get; set; }

        [Column("max_ram_speed_mhz")]
        public int? MaxRamSpeedMhz { get; set; }

        [Column("max_ram_amount_gb")]
        public int? MaxRamAmountGb { get; set; }

        [Column("onboard_wifi")]
        public string? OnboardWifi { get; set; }

        [Column("io_json", TypeName = "jsonb")]
        public string? IoJson { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
