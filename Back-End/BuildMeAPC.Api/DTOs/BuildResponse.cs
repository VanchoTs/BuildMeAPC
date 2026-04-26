using System.Text.Json.Serialization;

namespace BuildMeAPC.Api.DTOs
{
    public class BuildDto
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = string.Empty;

        [JsonPropertyName("name")]
        public string Name { get; set; } = string.Empty;

        [JsonPropertyName("description")]
        public string Description { get; set; } = string.Empty;

        [JsonPropertyName("totalPrice")]
        public double TotalPrice { get; set; }

        [JsonPropertyName("components")]
        public List<ComponentDto> Components { get; set; } = new();

        [JsonPropertyName("scores")]
        public BuildScoresDto Scores { get; set; } = new();
    }

    public class ComponentDto
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = string.Empty;

        [JsonPropertyName("type")]
        public string Type { get; set; } = string.Empty;

        [JsonPropertyName("brand")]
        public string Brand { get; set; } = string.Empty;

        [JsonPropertyName("model")]
        public string Model { get; set; } = string.Empty;

        [JsonPropertyName("price")]
        public double Price { get; set; }

        [JsonPropertyName("url")]
        public string? Url { get; set; }

        [JsonPropertyName("specs")]
        public Dictionary<string, object?> Specs { get; set; } = new();
    }

    public class BuildScoresDto
    {
        [JsonPropertyName("gaming")]
        public int Gaming { get; set; }

        [JsonPropertyName("workstation")]
        public int Workstation { get; set; }

        [JsonPropertyName("value")]
        public int Value { get; set; }
    }
}
