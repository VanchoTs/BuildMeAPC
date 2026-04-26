using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models.Components
{
    [Table("cases")]
    public class CaseEntity
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("brand")]
        public string? Brand { get; set; }

        [Column("model")]
        public string? Model { get; set; }

        [Column("case_size")]
        public string? CaseSize { get; set; }

        [Column("motherboard_form_factors")]
        public string? MotherboardFormFactors { get; set; }

        [Column("included_fans")]
        public int? IncludedFans { get; set; }

        [Column("max_cpu_cooler_mm")]
        public int? MaxCpuCoolerMm { get; set; }

        [Column("max_gpu_length_mm")]
        public int? MaxGpuLengthMm { get; set; }

        [Column("max_psu_length_mm")]
        public int? MaxPsuLengthMm { get; set; }

        [Column("max_radiator_mm")]
        public int? MaxRadiatorMm { get; set; }

        [Column("io_json", TypeName = "jsonb")]
        public string? IoJson { get; set; }

        [Column("price_eur")]
        public double? PriceEur { get; set; }

        [Column("product_url")]
        public string? ProductUrl { get; set; }
    }
}
