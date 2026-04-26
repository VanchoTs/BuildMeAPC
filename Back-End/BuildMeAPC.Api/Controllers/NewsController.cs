using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using BuildMeAPC.Api.Data;
using BuildMeAPC.Api.Models;
using BuildMeAPC.Api.DTOs;
using System.Security.Claims;

namespace BuildMeAPC.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class NewsController : ControllerBase
    {
        private readonly AppDbContext _context;

        public NewsController(AppDbContext context)
        {
            _context = context;
        }

        // GET: api/news
        // Everyone can read news (even not logged in)
        [HttpGet]
        public async Task<ActionResult<IEnumerable<NewsResponse>>> GetNews([FromQuery] string? search)
        {
            var query = _context.NewsArticles
                .Include(n => n.Author)
                .AsQueryable();

            if (!string.IsNullOrEmpty(search))
            {
                var lowerSearch = search.ToLower();
                query = query.Where(n => n.Title.ToLower().Contains(lowerSearch) || n.CatchPhrase.ToLower().Contains(lowerSearch));
            }

            var news = await query
                .OrderByDescending(n => n.CreatedAt)
                .Select(n => new NewsResponse
                {
                    Id = n.Id,
                    Title = n.Title,
                    Content = n.Content,
                    ImageUrl = n.ImageUrl,
                    CatchPhrase = n.CatchPhrase,
                    AuthorName = n.Author!.FullName,
                    CreatedAt = n.CreatedAt
                })
                .ToListAsync();

            return Ok(news);
        }

        // POST: api/news
        // Only admin and writer can create news
        [HttpPost]
        [Authorize(Roles = "admin,writer")]
        public async Task<ActionResult<NewsResponse>> CreateNews(CreateNewsRequest request)
        {
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (!int.TryParse(userIdString, out int authorId))
            {
                return Unauthorized("Invalid user ID in token.");
            }

            string? catchPhrase = request.CatchPhrase;
            if (string.IsNullOrWhiteSpace(catchPhrase))
            {
                var content = request.Content;
                var dotIndex = content.IndexOf('.');
                if (dotIndex > 0 && dotIndex < 100)
                {
                    catchPhrase = content.Substring(0, dotIndex + 1);
                }
                else
                {
                    catchPhrase = content.Length > 100 ? content.Substring(0, 97) + "..." : content;
                }
            }

            var newsArticle = new NewsArticle
            {
                Title = request.Title,
                Content = request.Content,
                ImageUrl = request.ImageUrl,
                CatchPhrase = catchPhrase,
                AuthorId = authorId,
                CreatedAt = DateTime.UtcNow
            };

            _context.NewsArticles.Add(newsArticle);
            await _context.SaveChangesAsync();

            // Load author name for response
            var author = await _context.Users.FindAsync(authorId);

            var response = new NewsResponse
            {
                Id = newsArticle.Id,
                Title = newsArticle.Title,
                Content = newsArticle.Content,
                ImageUrl = newsArticle.ImageUrl,
                CatchPhrase = newsArticle.CatchPhrase,
                AuthorName = author?.FullName ?? "Unknown",
                CreatedAt = newsArticle.CreatedAt
            };

            return CreatedAtAction(nameof(GetNews), new { id = response.Id }, response);
        }

        // DELETE: api/news/{id}
        [HttpDelete("{id}")]
        [Authorize(Roles = "admin,writer")]
        public async Task<IActionResult> DeleteNews(int id)
        {
            var newsArticle = await _context.NewsArticles.FindAsync(id);
            if (newsArticle == null)
            {
                return NotFound();
            }

            // Optional: Only allow writer to delete their own, but admin can delete any.
            // For now, allowing admin and writer to delete as requested.
            var userRole = User.FindFirst(ClaimTypes.Role)?.Value;
            var userIdString = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            
            if (userRole == "writer" && int.TryParse(userIdString, out int currentUserId))
            {
                if (newsArticle.AuthorId != currentUserId)
                {
                    return Forbid("Writers can only delete their own articles.");
                }
            }

            _context.NewsArticles.Remove(newsArticle);
            await _context.SaveChangesAsync();

            return Ok();
        }
    }
}
