using BuildMeAPC.Api.DTOs;

namespace BuildMeAPC.Api.Services
{
    public interface IBuildService
    {
        Task<IReadOnlyList<BuildDto>> GenerateBuildsAsync(BuildRequest request);
    }
}
