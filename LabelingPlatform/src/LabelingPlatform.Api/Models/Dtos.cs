namespace LabelingPlatform.Api.Models;

public sealed record PageDto(Guid Id, int PageNumber, int WidthPx, int HeightPx, int RenderDpi)
{
    public static PageDto From(DocumentPage p) => new(p.Id, p.PageNumber, p.WidthPx, p.HeightPx, p.RenderDpi);
}

public sealed record PointXY(double X, double Y);

public sealed record AnnotationDto(
    Guid Id,
    Guid PageId,
    string ClassId,
    string GeometryType,
    IReadOnlyList<PointXY> Points,
    string Note,
    DateTime CreatedAtUtc,
    DateTime UpdatedAtUtc)
{
    public static AnnotationDto From(Annotation a) => new(
        a.Id, a.PageId, a.ClassId, a.GeometryType,
        System.Text.Json.JsonSerializer.Deserialize<List<PointXY>>(
            a.PointsJson, System.Text.Json.JsonSerializerOptions.Web) ?? [],
        a.Note, a.CreatedAtUtc, a.UpdatedAtUtc);
}

public sealed record AnnotationRequest(
    string ClassId,
    string GeometryType,
    List<PointXY> Points,
    string? Note);

public sealed record DocumentDto(
    Guid Id,
    string Sha256,
    string FileName,
    string SourceKind,
    long SizeBytes,
    int PageCount,
    DateTime UploadedAtUtc,
    IReadOnlyList<PageDto> Pages)
{
    public static DocumentDto From(SourceDocument d) => new(
        d.Id, d.Sha256, d.FileName, d.SourceKind, d.SizeBytes, d.PageCount, d.UploadedAtUtc,
        d.Pages.OrderBy(p => p.PageNumber).Select(PageDto.From).ToList());
}
