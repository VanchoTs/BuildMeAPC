using System.Security.Claims;
using System.Text.Json;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.Models;
using BuildMeAPC.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace BuildMeAPC.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    [Authorize]
    public class ReportsController : ControllerBase
    {
        private readonly AppDbContext _db;
        private readonly IEmailService _emailService;

        public ReportsController(AppDbContext db, IEmailService emailService)
        {
            _db = db;
            _emailService = emailService;
        }

        /// <summary>
        /// Allows users to report issues with generated builds.
        /// Includes spam protection: verified emails only, deduplication, and rate limiting.
        /// </summary>
        [HttpPost]
        public async Task<IActionResult> ReportBuild([FromBody] ReportRequest request)
        {
            if (string.IsNullOrWhiteSpace(request.Comment))
                return BadRequest("Comment is required.");

            if (request.BuildData == null)
                return BadRequest("Build data is required.");

            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId))
                return Unauthorized();

            var user = await _db.Users.FindAsync(userId);
            if (user == null) return Unauthorized();

            // 1. Only verified users can send reports
            if (!user.IsVerified)
            {
                return BadRequest("Please verify your email address before sending reports.");
            }

            var buildObj = (JsonElement)request.BuildData;
            var buildId = buildObj.GetProperty("id").GetString() ?? "";

            // 2. Limit: 1 report per build per user
            var alreadyReported = await _db.BuildReports
                .FromSqlRaw("SELECT * FROM build_reports WHERE user_id = {0} AND build_data->>'id' = {1}", userId, buildId)
                .AnyAsync();

            if (alreadyReported)
            {
                return BadRequest("You have already reported an issue with this build.");
            }

            // 3. Rate Limit: max 5 reports per hour
            var oneHourAgo = DateTime.UtcNow.AddHours(-1);
            var recentCount = await _db.BuildReports
                .CountAsync(r => r.UserId == userId && r.CreatedAt > oneHourAgo);

            if (recentCount >= 5)
            {
                return BadRequest("Rate limit exceeded. Please wait a while before sending more reports.");
            }

            bool isGibberish = DetectGibberish(request.Comment);

            var report = new BuildReport
            {
                UserId = userId,
                Comment = request.Comment,
                BuildData = buildObj.GetRawText(),
                IsGibberish = isGibberish,
                CreatedAt = DateTime.UtcNow
            };

            _db.BuildReports.Add(report);
            await _db.SaveChangesAsync();

            return Ok(new { isGibberish });
        }

        [HttpGet]
        [Authorize(Roles = "admin")]
        public async Task<IActionResult> GetReports(
            [FromQuery] string? search,
            [FromQuery] string? sortBy = "newest")
        {
            var query = _db.BuildReports
                .Include(r => r.User)
                .AsQueryable();

            // Materialize first to avoid JSONB translation issues for the general search
            var reportsList = await query.ToListAsync();

            var mapped = reportsList.Select(r => new {
                r.Id,
                UserEmail = r.User != null ? r.User.Email : "Unknown",
                r.Comment,
                r.IsGibberish,
                r.CreatedAt,
                Build = JsonSerializer.Deserialize<JsonElement>(r.BuildData, (JsonSerializerOptions)null!)
            });

            if (!string.IsNullOrEmpty(search))
            {
                var lowerSearch = search.ToLower();
                mapped = mapped.Where(r => 
                    r.Comment.ToLower().Contains(lowerSearch) || 
                    r.UserEmail.ToLower().Contains(lowerSearch) ||
                    r.Build.GetRawText().ToLower().Contains(lowerSearch));
            }

            if (sortBy == "budget_desc")
                mapped = mapped.OrderByDescending(r => r.Build.GetProperty("totalPrice").GetDouble());
            else if (sortBy == "budget_asc")
                mapped = mapped.OrderBy(r => r.Build.GetProperty("totalPrice").GetDouble());
            else if (sortBy == "oldest")
                mapped = mapped.OrderBy(r => r.CreatedAt);
            else
                mapped = mapped.OrderByDescending(r => r.CreatedAt);

            return Ok(mapped.ToList());
        }

        [HttpPost("{id}/respond")]
        [Authorize(Roles = "admin")]
        public async Task<IActionResult> RespondToReport(int id, [FromBody] ResponseRequest request)
        {
            var report = await _db.BuildReports
                .Include(r => r.User)
                .FirstOrDefaultAsync(r => r.Id == id);

            if (report == null) return NotFound();
            if (report.User == null) return BadRequest("User not found.");

            var build = JsonSerializer.Deserialize<JsonElement>(report.BuildData);
            var buildName = build.GetProperty("name").GetString();
            var totalPrice = build.GetProperty("totalPrice").GetDouble();

            var componentsHtml = new System.Text.StringBuilder();
            if (build.TryGetProperty("components", out var components))
            {
                componentsHtml.Append("<ul>");
                foreach (var c in components.EnumerateArray())
                {
                    var type = c.GetProperty("type").GetString();
                    var brand = c.GetProperty("brand").GetString();
                    var model = c.GetProperty("model").GetString();
                    string url = "#";
                    if (c.TryGetProperty("url", out var urlProp) && urlProp.ValueKind != JsonValueKind.Null) url = urlProp.GetString() ?? "#";
                    
                    componentsHtml.Append($"<li><strong>{type}:</strong> <a href=\"{url}\">{brand} {model}</a></li>");
                }
                componentsHtml.Append("</ul>");
            }

            string subject = $"BuildMeAPC: Admin Response to your report of '{buildName}'";
            string body = $@"
                <h3>Hello,</h3>
                <p>An admin has responded to your build report for <strong>{buildName}</strong>.</p>
                
                <h4>Admin Message:</h4>
                <p style='background: #f4f4f4; padding: 10px; border-left: 4px solid #333;'>{request.Message}</p>

                <hr/>
                <h4>Original Report:</h4>
                <p><em>""{report.Comment}""</em></p>

                <hr/>
                <h4>Build Details:</h4>
                <p><strong>Name:</strong> {buildName}</p>
                <p><strong>Total Price:</strong> €{totalPrice}</p>
                {componentsHtml.ToString()}
                
                <p>Thank you for using BuildMeAPC!</p>
            ";

            try
            {
                await _emailService.SendSystemEmailAsync(report.User.Email, subject, body);
            }
            catch (Exception ex)
            {
                return BadRequest($"Failed to send email: {ex.Message}");
            }

            return Ok();
        }

        [HttpDelete("{id}")]
        [Authorize(Roles = "admin")]
        public async Task<IActionResult> DeleteReport(int id)
        {
            var report = await _db.BuildReports.FindAsync(id);
            if (report == null) return NotFound();

            _db.BuildReports.Remove(report);
            await _db.SaveChangesAsync();
            return Ok();
        }

        /// <summary>
        /// Heuristic-based detector to identify low-quality or bot-generated comments.
        /// Checks for length, character repetition, vowel presence, and word complexity.
        /// </summary>
        private bool DetectGibberish(string text)
        {
            if (text.Length < 10) return true;
            if (System.Text.RegularExpressions.Regex.IsMatch(text, @"(.)\1{4,}")) return true;
            bool hasVowels = System.Text.RegularExpressions.Regex.IsMatch(text, @"[aeiouyAEIOUYаеиоуяАЕИОУЯ]");
            if (!hasVowels) return true;
            var words = text.Split(new[] { ' ', '.', ',', '!' }, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length < 3) return true;
            foreach (var word in words)
            {
                if (word.Length > 8 && !System.Text.RegularExpressions.Regex.IsMatch(word, @"[aeiouyAEIOUYаеиоуяАЕИОУЯ]")) return true;
            }
            return false;
        }

        public class ReportRequest
        {
            public object? BuildData { get; set; }
            public string Comment { get; set; } = string.Empty;
        }

        public class ResponseRequest
        {
            public string Message { get; set; } = string.Empty;
        }
    }
}
