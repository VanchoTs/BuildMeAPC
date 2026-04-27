using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.Models;
using BuildMeAPC.Api.DTOs;
using BuildMeAPC.Api.Services;
using BCrypt.Net;
using Microsoft.IdentityModel.Tokens;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;

namespace BuildMeAPC.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class AuthController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly IConfiguration _configuration;
        private readonly IEmailService _emailService;

        public AuthController(AppDbContext context, IConfiguration configuration, IEmailService emailService)
        {
            _context = context;
            _configuration = configuration;
            _emailService = emailService;
        }

        /// <summary>
        /// Registers a new user, hashes their password with BCrypt, and sends a 6-digit verification email.
        /// </summary>
        [HttpPost("register")]
        public async Task<ActionResult> Register(RegisterRequest request)
        {
            if (await _context.Users.AnyAsync(u => u.Email == request.Email))
            {
                return BadRequest("Email already registered.");
            }

            var verificationCode = new Random().Next(100000, 999999).ToString();

            var user = new User
            {
                FullName = request.FullName,
                Email = request.Email,
                PasswordHash = BCrypt.Net.BCrypt.HashPassword(request.Password),
                VerificationCode = verificationCode,
                VerificationExpiry = DateTime.UtcNow.AddHours(2)
            };

            _context.Users.Add(user);
            await _context.SaveChangesAsync();

            // Send verification email
            await _emailService.SendSystemEmailAsync(
                user.Email,
                "Verify your BuildMeAPC Account",
                $"<h3>Welcome, {user.FullName}!</h3><p>Your verification code is: <strong>{verificationCode}</strong></p>"
            );

            var token = CreateToken(user);
            SetTokenCookie(token);

            return Ok(new { 
                fullName = user.FullName, 
                email = user.Email, 
                role = user.Role,
                isVerified = user.IsVerified
            });
        }

        [HttpPost("verify")]
        [Authorize]
        public async Task<ActionResult> VerifyEmail([FromBody] string code)
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId)) return Unauthorized();

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return NotFound();

            if (user.IsVerified) return BadRequest("User already verified.");
            if (user.VerificationCode != code || user.VerificationExpiry < DateTime.UtcNow)
            {
                return BadRequest("Invalid or expired verification code.");
            }

            user.IsVerified = true;
            user.VerificationCode = null;
            user.VerificationExpiry = null;
            await _context.SaveChangesAsync();

            return Ok();
        }

        [HttpPost("resend-verification")]
        [Authorize]
        public async Task<ActionResult> ResendVerification()
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId)) return Unauthorized();

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return NotFound();

            if (user.IsVerified) return BadRequest("User already verified.");

            var verificationCode = new Random().Next(100000, 999999).ToString();
            user.VerificationCode = verificationCode;
            user.VerificationExpiry = DateTime.UtcNow.AddHours(2);
            await _context.SaveChangesAsync();

            await _emailService.SendSystemEmailAsync(
                user.Email,
                "Verify your BuildMeAPC Account",
                $"<p>Your new verification code is: <strong>{verificationCode}</strong></p>"
            );

            return Ok();
        }

        [HttpPost("forgot-password")]
        public async Task<ActionResult> ForgotPassword([FromBody] string email)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);
            if (user == null) return Ok(); // Don't reveal user existence

            var resetCode = new Random().Next(100000, 999999).ToString();
            user.ResetCode = resetCode;
            user.ResetExpiry = DateTime.UtcNow.AddHours(1);
            await _context.SaveChangesAsync();

            await _emailService.SendSystemEmailAsync(
                user.Email,
                "Reset your BuildMeAPC Password",
                $"<p>Your password reset code is: <strong>{resetCode}</strong></p>"
            );

            return Ok();
        }

        [HttpPost("reset-password")]
        public async Task<ActionResult> ResetPassword(ResetPasswordRequest request)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == request.Email);
            if (user == null) return BadRequest("Invalid request.");

            if (user.ResetCode != request.Code || user.ResetExpiry < DateTime.UtcNow)
            {
                return BadRequest("Invalid or expired reset code.");
            }

            user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(request.NewPassword);
            user.ResetCode = null;
            user.ResetExpiry = null;
            await _context.SaveChangesAsync();

            return Ok();
        }

        [HttpPost("login")]
        public async Task<ActionResult> Login(LoginRequest request)
        {
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == request.Email);

            if (user == null || !BCrypt.Net.BCrypt.Verify(request.Password, user.PasswordHash))
            {
                return BadRequest("Invalid email or password.");
            }

            var token = CreateToken(user);
            SetTokenCookie(token);

            return Ok(new { 
                fullName = user.FullName, 
                email = user.Email, 
                role = user.Role,
                isVerified = user.IsVerified
            });
        }

        [Authorize]
        [HttpGet("me")]
        public async Task<IActionResult> GetMe()
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId)) return Unauthorized();
            
            var user = await _context.Users.FindAsync(userId);
            if (user == null) return NotFound();

            return Ok(new
            {
                fullName = user.FullName,
                email = user.Email,
                role = user.Role,
                isVerified = user.IsVerified
            });
        }

        [HttpPost("logout")]
        public IActionResult Logout()
        {
            Response.Cookies.Delete("authToken");
            return Ok();
        }

        /// <summary>
        /// Sets the authentication JWT as an HttpOnly, Lax, SameSite cookie to prevent XSS.
        /// </summary>
        private void SetTokenCookie(string token)
        {
            var cookieOptions = new CookieOptions
            {
                HttpOnly = true,
                Expires = DateTime.UtcNow.AddDays(1),
                Secure = false, // Set to true in production with HTTPS
                SameSite = SameSiteMode.Lax,
                Path = "/"
            };
            Response.Cookies.Append("authToken", token, cookieOptions);
        }

        /// <summary>
        /// Generates a JWT token containing User ID, Email, and Role claims.
        /// Uses HMAC-SHA512 for signing.
        /// </summary>
        private string CreateToken(User user)
        {
            var claims = new List<Claim>
            {
                new Claim(ClaimTypes.NameIdentifier, user.Id.ToString()),
                new Claim(ClaimTypes.Email, user.Email),
                new Claim(ClaimTypes.Name, user.FullName),
                new Claim(ClaimTypes.Role, user.Role)
            };

            var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(
                _configuration.GetSection("AppSettings:Token").Value!));

            var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha512Signature);

            var token = new JwtSecurityToken(
                issuer: "BuildMeAPC",
                audience: "BuildMeAPC-App",
                claims: claims,
                expires: DateTime.Now.AddDays(1),
                signingCredentials: creds
            );

            return new JwtSecurityTokenHandler().WriteToken(token);
        }
    }

    public class ResetPasswordRequest
    {
        public string Email { get; set; } = string.Empty;
        public string Code { get; set; } = string.Empty;
        public string NewPassword { get; set; } = string.Empty;
    }
}
