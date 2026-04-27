using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.Models;

namespace BuildMeAPC.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    [Authorize(Roles = "admin")]
    public class AdminController : ControllerBase
    {
        private readonly AppDbContext _context;

        public AdminController(AppDbContext context)
        {
            _context = context;
        }

        /// <summary>
        /// Retrieves a list of users with optional filtering and sorting.
        /// Admin-only access.
        /// </summary>
        [HttpGet("users")]
        public async Task<ActionResult<IEnumerable<object>>> GetUsers(
            [FromQuery] string? search, 
            [FromQuery] string? role, 
            [FromQuery] string? sortBy = "newest")
        {
            var query = _context.Users.AsQueryable();

            if (!string.IsNullOrEmpty(search))
            {
                var lowerSearch = search.ToLower();
                query = query.Where(u => u.FullName.ToLower().Contains(lowerSearch) || u.Email.ToLower().Contains(lowerSearch));
            }

            if (!string.IsNullOrEmpty(role) && role != "all")
            {
                query = query.Where(u => u.Role == role);
            }

            if (sortBy == "oldest")
            {
                query = query.OrderBy(u => u.CreatedAt);
            }
            else
            {
                query = query.OrderByDescending(u => u.CreatedAt);
            }

            return await query
                .Select(u => new { u.Id, u.FullName, u.Email, u.Role, u.CreatedAt })
                .ToListAsync();
        }

        /// <summary>
        /// Updates a user's role. Prevents administrators from demoting themselves.
        /// </summary>
        [HttpPatch("users/{id}/role")]
        public async Task<IActionResult> UpdateRole(int id, [FromBody] string newRole)
        {
            // Security: Prevent self-modification to ensure at least one admin remains
            var currentUserId = User.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
            if (currentUserId == id.ToString())
            {
                return BadRequest("You cannot change your own role.");
            }

            var validRoles = new[] { "user", "writer", "admin" };
            if (!validRoles.Contains(newRole))
            {
                return BadRequest("Invalid role.");
            }

            var user = await _context.Users.FindAsync(id);
            if (user == null)
            {
                return NotFound();
            }

            user.Role = newRole;
            await _context.SaveChangesAsync();

            return Ok();
        }

        /// <summary>
        /// Deletes a user account. Prevents administrators from deleting themselves.
        /// </summary>
        [HttpDelete("users/{id}")]
        public async Task<IActionResult> DeleteUser(int id)
        {
            // Security: Prevent self-deletion
            var currentUserId = User.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value;
            if (currentUserId == id.ToString())
            {
                return BadRequest("You cannot delete your own account.");
            }

            var user = await _context.Users.FindAsync(id);
            if (user == null)
            {
                return NotFound();
            }

            _context.Users.Remove(user);
            await _context.SaveChangesAsync();

            return Ok();
        }
    }
}
