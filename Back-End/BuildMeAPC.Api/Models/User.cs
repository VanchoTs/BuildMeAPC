using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace BuildMeAPC.Api.Models
{
    [Table("users")]
    public class User
    {
        [Key]
        [Column("id")]
        public int Id { get; set; }

        [Required]
        [Column("full_name")]
        [MaxLength(100)]
        public string FullName { get; set; } = string.Empty;

        [Required]
        [Column("email")]
        [MaxLength(100)]
        public string Email { get; set; } = string.Empty;

        [Required]
        [Column("password_hash")]
        public string PasswordHash { get; set; } = string.Empty;

        [Required]
        [Column("role")]
        [MaxLength(20)]
        public string Role { get; set; } = "user";

        [Column("is_verified")]
        public bool IsVerified { get; set; } = false;

        [Column("verification_code")]
        public string? VerificationCode { get; set; }

        [Column("verification_expiry")]
        public DateTime? VerificationExpiry { get; set; }

        [Column("reset_code")]
        public string? ResetCode { get; set; }

        [Column("reset_expiry")]
        public DateTime? ResetExpiry { get; set; }

        [Column("created_at", TypeName = "timestamp with time zone")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
