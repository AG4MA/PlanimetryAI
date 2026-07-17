namespace LabelingPlatform.Api.Models;

/// <summary>
/// Documento sorgente caricato (PDF o immagine). Identità = SHA-256 del contenuto,
/// coerente con la filosofia del dataset manifest di PlanParser.
/// </summary>
public sealed class SourceDocument
{
    public Guid Id { get; set; }
    public string Sha256 { get; set; } = "";
    public string FileName { get; set; } = "";
    public string ContentType { get; set; } = "";
    public long SizeBytes { get; set; }

    /// <summary>"pdf" oppure "image".</summary>
    public string SourceKind { get; set; } = "pdf";

    public int PageCount { get; set; }
    public DateTime UploadedAtUtc { get; set; }

    public List<DocumentPage> Pages { get; set; } = [];
}

/// <summary>
/// Singola pagina renderizzata in PNG. Per le immagini caricate esiste una sola pagina.
/// </summary>
public sealed class DocumentPage
{
    public Guid Id { get; set; }
    public Guid DocumentId { get; set; }
    public SourceDocument? Document { get; set; }

    /// <summary>1-based.</summary>
    public int PageNumber { get; set; }

    public int WidthPx { get; set; }
    public int HeightPx { get; set; }

    /// <summary>DPI di rendering per i PDF; risoluzione dichiarata nei metadati per le immagini (0 se ignota).</summary>
    public int RenderDpi { get; set; }

    /// <summary>Percorsi relativi alla data root.</summary>
    public string ImagePath { get; set; } = "";
    public string ThumbnailPath { get; set; } = "";

    public List<Annotation> Annotations { get; set; } = [];
}

/// <summary>
/// Annotazione umana sopra una pagina: geometria in coordinate pixel della pagina
/// renderizzata, classe dalla tassonomia P1 di PlanParser.
/// </summary>
public sealed class Annotation
{
    public Guid Id { get; set; }
    public Guid PageId { get; set; }
    public DocumentPage? Page { get; set; }

    /// <summary>Id classe della tassonomia (es. "room_region", "door", "room_label").</summary>
    public string ClassId { get; set; } = "";

    /// <summary>"bbox" (2 punti: due angoli opposti) oppure "polygon" (>= 3 vertici).</summary>
    public string GeometryType { get; set; } = "bbox";

    /// <summary>JSON: [{"x":..,"y":..},...] in pixel della pagina renderizzata.</summary>
    public string PointsJson { get; set; } = "[]";

    public string Note { get; set; } = "";
    public DateTime CreatedAtUtc { get; set; }
    public DateTime UpdatedAtUtc { get; set; }
}
