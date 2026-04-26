using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("coolers")]
    public class CoolerEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("cooler_type")]
        public string? CoolerType { get; set; }

        [Column("socket_compatibility")]
        public string? SocketCompatibility { get; set; }

        [Column("cooler_height_mm")]
        public int? CoolerHeightMm { get; set; }

        [Column("tdp_w")]
        public int? TdpW { get; set; }

        [Column("fan_size_mm")]
        public int? FanSizeMm { get; set; }

        [Column("fan_count")]
        public int? FanCount { get; set; }

        [Column("noise_db")]
        public double? NoiseDb { get; set; }

        [Column("rpm_max")]
        public int? RpmMax { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
