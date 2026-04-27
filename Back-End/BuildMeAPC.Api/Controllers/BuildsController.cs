using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.DTOs;
using BuildMeAPC.Api.Models;
using BuildMeAPC.Api.Services;
using System.Security.Claims;
using System.Text.Json;

namespace BuildMeAPC.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    [Authorize]
    public class BuildsController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly IBuildService _buildService;

        public BuildsController(AppDbContext context, IBuildService buildService)
        {
            _context = context;
            _buildService = buildService;
        }

        /// <summary>
        /// Public endpoint to generate build recommendations based on user requirements.
        /// </summary>
        [HttpPost("generate")]
        [AllowAnonymous]
        public async Task<ActionResult<IReadOnlyList<BuildDto>>> GenerateBuilds([FromBody] BuildRequest request)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }

            var builds = await _buildService.GenerateBuildsAsync(request);
            if (builds.Count == 0)
            {
                return Ok(new List<BuildDto>());
            }
            return Ok(builds);
        }

        [HttpGet]
        public async Task<ActionResult> GetSavedBuilds()
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId))
            {
                return Unauthorized();
            }

            var savedBuilds = await _context.SavedBuilds
                .Where(b => b.UserId == userId)
                .OrderByDescending(b => b.CreatedAt)
                .Select(b => new
                {
                    Id = b.Id,
                    BuildData = JsonSerializer.Deserialize<JsonElement>(b.BuildData, (JsonSerializerOptions?)null),
                    CreatedAt = b.CreatedAt
                })
                .ToListAsync();

            return Ok(savedBuilds);
        }

        /// <summary>
        /// Saves a build to the user's personal list. 
        /// Uses raw SQL to perform a JSONB property check for deduplication.
        /// </summary>
        [HttpPost]
        public async Task<ActionResult> SaveBuild([FromBody] JsonElement buildData)
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId))
            {
                return Unauthorized();
            }

            var buildId = buildData.GetProperty("id").GetString();
            if (string.IsNullOrEmpty(buildId)) return BadRequest("Invalid build data.");

            // Limit: only one save per unique build per user
            var alreadySaved = await _context.SavedBuilds
                .FromSqlRaw("SELECT * FROM saved_builds WHERE user_id = {0} AND build_data->>'id' = {1}", userId, buildId)
                .AnyAsync();

            if (alreadySaved)
            {
                return BadRequest("You have already saved this build.");
            }

            var savedBuild = new SavedBuild
            {
                UserId = userId,
                BuildData = JsonSerializer.Serialize(buildData),
                CreatedAt = DateTime.UtcNow
            };

            _context.SavedBuilds.Add(savedBuild);
            await _context.SaveChangesAsync();

            return Ok(new { Id = savedBuild.Id });
        }

        [HttpDelete("{id}")]
        public async Task<IActionResult> DeleteBuild(int id)
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int userId))
            {
                return Unauthorized();
            }

            var savedBuild = await _context.SavedBuilds.FindAsync(id);
            if (savedBuild == null)
            {
                return NotFound();
            }

            if (savedBuild.UserId != userId)
            {
                return Forbid("You can only delete your own saved builds.");
            }

            _context.SavedBuilds.Remove(savedBuild);
            await _context.SaveChangesAsync();

            return Ok();
        }
    }
}
