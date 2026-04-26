using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("ssds")]
    public class SsdEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("type")]
        public string? Type { get; set; }

        [Column("storage_size_gb")]
        public int? StorageSizeGb { get; set; }

        [Column("physical_size")]
        public string? PhysicalSize { get; set; }

        [Column("read_speed_mbps")]
        public int? ReadSpeedMbps { get; set; }

        [Column("write_speed_mbps")]
        public int? WriteSpeedMbps { get; set; }

        [Column("interface")]
        public string? Interface { get; set; }

        [Column("tbw_tb")]
        public int? TbwTb { get; set; }

        [Column("nand_type")]
        public string? NandType { get; set; }

        [Column("has_heatsink")]
        public bool? HasHeatsink { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
