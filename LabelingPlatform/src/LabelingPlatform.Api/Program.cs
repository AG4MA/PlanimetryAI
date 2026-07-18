using System.Text.Json;
using LabelingPlatform.Api.Data;
using LabelingPlatform.Api.Models;
using LabelingPlatform.Api.Services;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.EntityFrameworkCore;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Processing;

var builder = WebApplication.CreateBuilder(args);

const long maxUploadBytes = 512L * 1024 * 1024;

var dataRoot = builder.Configuration["DataRoot"]
    ?? Path.Combine(builder.Environment.ContentRootPath, "..", "..", "data");
dataRoot = Path.GetFullPath(dataRoot);
Directory.CreateDirectory(dataRoot);

builder.Services.AddSingleton(new StorageOptions(dataRoot));
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseSqlite($"Data Source={Path.Combine(dataRoot, "labeling.db")}"));
builder.Services.AddScoped<DocumentIngestionService>();
builder.Services.AddSingleton<TaxonomyService>();
builder.Services.Configure<FormOptions>(o => o.MultipartBodyLengthLimit = maxUploadBytes);
builder.WebHost.ConfigureKestrel(o => o.Limits.MaxRequestBodySize = maxUploadBytes);

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.Database.EnsureCreated();
    db.EnsureAnnotationsTable();
}

app.UseDefaultFiles();
app.UseStaticFiles();

app.MapGet("/healthz", (StorageOptions storage) =>
    Results.Ok(new { status = "ok", dataRoot = storage.DataRoot }));

app.MapPost("/api/documents", async (IFormFile? file, DocumentIngestionService ingestion, CancellationToken ct) =>
{
    if (file is null || file.Length == 0)
        return Results.BadRequest(new { error = "Nessun file ricevuto. Campo form atteso: 'file'." });

    try
    {
        await using var stream = file.OpenReadStream();
        var result = await ingestion.IngestAsync(stream, file.FileName, file.ContentType, ct);
        var dto = DocumentDto.From(result.Document);
        return result.AlreadyExisted
            ? Results.Ok(dto)
            : Results.Created($"/api/documents/{dto.Id}", dto);
    }
    catch (InvalidDataException ex)
    {
        return Results.Problem(statusCode: StatusCodes.Status415UnsupportedMediaType,
            title: "Documento non elaborabile", detail: ex.Message);
    }
}).DisableAntiforgery();

app.MapGet("/api/documents", async (AppDbContext db, CancellationToken ct) =>
{
    var documents = await db.Documents.AsNoTracking()
        .Include(d => d.Pages)
        .OrderByDescending(d => d.UploadedAtUtc)
        .ToListAsync(ct);
    return Results.Ok(documents.Select(DocumentDto.From));
});

app.MapGet("/api/documents/{id:guid}", async (Guid id, AppDbContext db, CancellationToken ct) =>
{
    var document = await db.Documents.AsNoTracking()
        .Include(d => d.Pages)
        .FirstOrDefaultAsync(d => d.Id == id, ct);
    return document is null ? Results.NotFound() : Results.Ok(DocumentDto.From(document));
});

app.MapGet("/api/pages/{id:guid}/image", (Guid id, AppDbContext db, StorageOptions storage) =>
    ServePageFile(id, db, storage, p => p.ImagePath));

app.MapGet("/api/pages/{id:guid}/thumbnail", (Guid id, AppDbContext db, StorageOptions storage) =>
    ServePageFile(id, db, storage, p => p.ThumbnailPath));

app.MapGet("/api/taxonomy", (TaxonomyService taxonomy) => Results.Ok(taxonomy.Taxonomy));

app.MapGet("/api/pages/{id:guid}/annotations", async (Guid id, AppDbContext db, CancellationToken ct) =>
{
    if (!await db.Pages.AnyAsync(p => p.Id == id, ct))
        return Results.NotFound();
    var annotations = await db.Annotations.AsNoTracking()
        .Where(a => a.PageId == id)
        .OrderBy(a => a.CreatedAtUtc)
        .ToListAsync(ct);
    return Results.Ok(annotations.Select(AnnotationDto.From));
});

app.MapPost("/api/pages/{id:guid}/annotations",
    async (Guid id, AnnotationRequest request, AppDbContext db, TaxonomyService taxonomy, CancellationToken ct) =>
{
    if (!await db.Pages.AnyAsync(p => p.Id == id, ct))
        return Results.NotFound();

    var error = ValidateAnnotation(request, taxonomy);
    if (error is not null)
        return Results.BadRequest(new { error });

    var now = DateTime.UtcNow;
    var annotation = new Annotation
    {
        Id = Guid.NewGuid(),
        PageId = id,
        ClassId = request.ClassId,
        GeometryType = request.GeometryType,
        PointsJson = JsonSerializer.Serialize(request.Points, JsonSerializerOptions.Web),
        Note = request.Note ?? "",
        CreatedAtUtc = now,
        UpdatedAtUtc = now
    };
    db.Annotations.Add(annotation);
    await db.SaveChangesAsync(ct);
    return Results.Created($"/api/annotations/{annotation.Id}", AnnotationDto.From(annotation));
});

app.MapPut("/api/annotations/{id:guid}",
    async (Guid id, AnnotationRequest request, AppDbContext db, TaxonomyService taxonomy, CancellationToken ct) =>
{
    var annotation = await db.Annotations.FirstOrDefaultAsync(a => a.Id == id, ct);
    if (annotation is null)
        return Results.NotFound();

    var error = ValidateAnnotation(request, taxonomy);
    if (error is not null)
        return Results.BadRequest(new { error });

    annotation.ClassId = request.ClassId;
    annotation.GeometryType = request.GeometryType;
    annotation.PointsJson = JsonSerializer.Serialize(request.Points, JsonSerializerOptions.Web);
    annotation.Note = request.Note ?? "";
    annotation.UpdatedAtUtc = DateTime.UtcNow;
    await db.SaveChangesAsync(ct);
    return Results.Ok(AnnotationDto.From(annotation));
});

app.MapDelete("/api/annotations/{id:guid}", async (Guid id, AppDbContext db, CancellationToken ct) =>
{
    var deleted = await db.Annotations.Where(a => a.Id == id).ExecuteDeleteAsync(ct);
    return deleted == 0 ? Results.NotFound() : Results.NoContent();
});

app.MapGet("/api/annotations/{id:guid}/crop", async (Guid id, AppDbContext db, StorageOptions storage, CancellationToken ct) =>
{
    var annotation = await db.Annotations.AsNoTracking()
        .Include(a => a.Page)
        .FirstOrDefaultAsync(a => a.Id == id, ct);
    if (annotation?.Page is null)
        return Results.NotFound();

    var imageAbs = Path.GetFullPath(Path.Combine(storage.DataRoot, annotation.Page.ImagePath));
    if (!imageAbs.StartsWith(storage.DataRoot, StringComparison.OrdinalIgnoreCase) || !File.Exists(imageAbs))
        return Results.NotFound();

    var points = JsonSerializer.Deserialize<List<PointXY>>(annotation.PointsJson, JsonSerializerOptions.Web);
    if (points is null || points.Count < 2)
        return Results.BadRequest(new { error = "Annotazione senza geometria valida." });

    const int padding = 8;
    using var image = await SixLabors.ImageSharp.Image.LoadAsync(imageAbs, ct);
    var minX = (int)Math.Floor(points.Min(p => p.X)) - padding;
    var minY = (int)Math.Floor(points.Min(p => p.Y)) - padding;
    var maxX = (int)Math.Ceiling(points.Max(p => p.X)) + padding;
    var maxY = (int)Math.Ceiling(points.Max(p => p.Y)) + padding;
    minX = Math.Clamp(minX, 0, image.Width - 1);
    minY = Math.Clamp(minY, 0, image.Height - 1);
    maxX = Math.Clamp(maxX, minX + 1, image.Width);
    maxY = Math.Clamp(maxY, minY + 1, image.Height);

    using var crop = image.Clone(x => x.Crop(new SixLabors.ImageSharp.Rectangle(minX, minY, maxX - minX, maxY - minY)));
    var buffer = new MemoryStream();
    await crop.SaveAsPngAsync(buffer, ct);
    return Results.File(buffer.ToArray(), "image/png",
        $"pezzetto_{annotation.ClassId}_{annotation.Id.ToString()[..8]}.png");
});

app.Run();

static string? ValidateAnnotation(AnnotationRequest request, TaxonomyService taxonomy)
{
    if (string.IsNullOrWhiteSpace(request.ClassId))
        return "classId mancante.";
    if (!taxonomy.IsValidClass(request.ClassId))
        return $"classId '{request.ClassId}' non presente nella tassonomia P1.";
    if (request.GeometryType is not ("bbox" or "polygon"))
        return "geometryType deve essere 'bbox' o 'polygon'.";
    if (request.Points is null)
        return "points mancanti.";
    if (request.GeometryType == "bbox" && request.Points.Count != 2)
        return "Una bbox richiede esattamente 2 punti (angoli opposti).";
    if (request.GeometryType == "polygon" && request.Points.Count < 3)
        return "Un poligono richiede almeno 3 vertici.";
    if (request.Points.Any(p => double.IsNaN(p.X) || double.IsNaN(p.Y) || double.IsInfinity(p.X) || double.IsInfinity(p.Y)))
        return "Coordinate non valide.";
    return null;
}

static IResult ServePageFile(Guid pageId, AppDbContext db, StorageOptions storage, Func<DocumentPage, string> pathSelector)
{
    var page = db.Pages.AsNoTracking().FirstOrDefault(p => p.Id == pageId);
    if (page is null)
        return Results.NotFound();

    var absolute = Path.GetFullPath(Path.Combine(storage.DataRoot, pathSelector(page)));
    if (!absolute.StartsWith(storage.DataRoot, StringComparison.OrdinalIgnoreCase) || !File.Exists(absolute))
        return Results.NotFound();

    return Results.File(absolute, "image/png");
}
