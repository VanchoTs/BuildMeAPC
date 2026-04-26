using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models
{
    [Table("build_reports")]
    public class BuildReport
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Column("user_id")]
        public int UserId { get; set; }

        [ForeignKey("UserId")]
        public User? User { get; set; }

        [Column("comment")]
        public string Comment { get; set; } = string.Empty;

        [Required]
        [Column("build_data", TypeName = "jsonb")]
        public string BuildData { get; set; } = string.Empty;

        [Column("is_gibberish")]
        public bool IsGibberish { get; set; } = false;

        [Column("created_at", TypeName = "timestamp with time zone")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
