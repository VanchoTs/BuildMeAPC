using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("psus")]
    public class PsuEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("physical_size")]
        public string? PhysicalSize { get; set; }

        [Column("power_w")]
        public int? PowerW { get; set; }

        [Column("efficiency")]
        public string? Efficiency { get; set; }

        [Column("certificate")]
        public string? Certificate { get; set; }

        [Column("modularity")]
        public string? Modularity { get; set; }

        [Column("fan_size_mm")]
        public int? FanSizeMm { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
