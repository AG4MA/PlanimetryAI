using System.Text.Json;

namespace LabelingPlatform.Api.Services;

public sealed record TaxonomyClass(string Id, string Layer);

public sealed record TaxonomyView(string Version, string Source, IReadOnlyList<TaxonomyClass> Classes);

/// <summary>
/// Carica la tassonomia atomica P1 dal contratto pubblicato di PlanParser
/// (PlanParser/decomposition/taxonomy.v1.json). Sola lettura: il file resta
/// di proprietà di PlanParser. Fallback minimo se il file non è raggiungibile.
/// </summary>
public sealed class TaxonomyService
{
    public TaxonomyView Taxonomy { get; }

    public TaxonomyService(IConfiguration configuration, IHostEnvironment environment, ILogger<TaxonomyService> logger)
    {
        var path = configuration["TaxonomyPath"] ?? Path.Combine(
            environment.ContentRootPath, "..", "..", "..", "PlanParser", "decomposition", "taxonomy.v1.json");
        path = Path.GetFullPath(path);

        if (File.Exists(path))
        {
            try
            {
                using var stream = File.OpenRead(path);
                using var json = JsonDocument.Parse(stream);
                var root = json.RootElement;

                var version = root.TryGetProperty("version", out var v) ? v.GetString() ?? "?" : "?";
                var classes = new List<TaxonomyClass>();
                if (root.TryGetProperty("layers", out var layers))
                {
                    foreach (var layer in layers.EnumerateObject())
                        foreach (var cls in layer.Value.EnumerateArray())
                            if (cls.GetString() is { Length: > 0 } id)
                                classes.Add(new TaxonomyClass(id, layer.Name));
                }

                if (classes.Count > 0)
                {
                    Taxonomy = new TaxonomyView(version, path, classes);
                    logger.LogInformation("Tassonomia P1 caricata: v{Version}, {Count} classi da {Path}.",
                        version, classes.Count, path);
                    return;
                }
            }
            catch (Exception ex) when (ex is JsonException or IOException)
            {
                logger.LogWarning(ex, "Tassonomia non leggibile da {Path}; uso il fallback.", path);
            }
        }
        else
        {
            logger.LogWarning("Tassonomia non trovata in {Path}; uso il fallback.", path);
        }

        Taxonomy = new TaxonomyView("fallback", "embedded",
        [
            new("drawing_area", "source_region"),
            new("title_block", "source_region"),
            new("legend", "source_region"),
            new("unknown_region", "source_region"),
            new("room_region", "architectural_candidate"),
            new("wall_region", "architectural_candidate"),
            new("door", "architectural_candidate"),
            new("window", "architectural_candidate"),
            new("stair", "architectural_candidate"),
            new("room_label", "text"),
            new("dimension_text", "text"),
            new("scale_text", "text"),
            new("unknown_text", "text"),
        ]);
    }

    public bool IsValidClass(string classId) =>
        Taxonomy.Classes.Any(c => string.Equals(c.Id, classId, StringComparison.Ordinal));
}
