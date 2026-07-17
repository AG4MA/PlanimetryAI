using System.Security.Cryptography;
using LabelingPlatform.Api.Data;
using LabelingPlatform.Api.Models;
using Microsoft.EntityFrameworkCore;
using PDFtoImage;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Processing;
using SkiaSharp;

namespace LabelingPlatform.Api.Services;

public sealed record StorageOptions(string DataRoot);

public sealed record IngestionResult(SourceDocument Document, bool AlreadyExisted);

/// <summary>
/// Ingestione documenti: spool su file temporaneo, hash SHA-256, dedup,
/// archiviazione dell'originale immutato e rendering pagine PNG + thumbnail.
/// </summary>
public sealed class DocumentIngestionService(
    AppDbContext db,
    StorageOptions storage,
    ILogger<DocumentIngestionService> logger)
{
    private const int PdfRenderDpi = 200;
    private const int ThumbnailMaxSide = 480;

    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"
    };

    public async Task<IngestionResult> IngestAsync(Stream content, string fileName, string? contentType, CancellationToken ct)
    {
        var tempDir = Path.Combine(storage.DataRoot, "tmp");
        Directory.CreateDirectory(tempDir);
        var tempPath = Path.Combine(tempDir, Guid.NewGuid().ToString("N"));

        try
        {
            string sha256;
            long sizeBytes;
            await using (var tempFile = File.Create(tempPath))
            using (var sha = SHA256.Create())
            {
                await using (var hashing = new CryptoStream(tempFile, sha, CryptoStreamMode.Write, leaveOpen: true))
                {
                    await content.CopyToAsync(hashing, ct);
                }
                sha256 = Convert.ToHexString(sha.Hash!).ToLowerInvariant();
                sizeBytes = tempFile.Length;
            }

            if (sizeBytes == 0)
                throw new InvalidDataException("Il file ricevuto è vuoto.");

            var existing = await db.Documents
                .Include(d => d.Pages)
                .FirstOrDefaultAsync(d => d.Sha256 == sha256, ct);
            if (existing is not null)
            {
                logger.LogInformation("Documento già presente ({Sha256}), dedup su '{FileName}'.", sha256, fileName);
                return new IngestionResult(existing, true);
            }

            var kind = DetectKind(tempPath, fileName, contentType)
                ?? throw new InvalidDataException(
                    $"Formato non supportato per '{fileName}'. Ammessi: PDF e immagini ({string.Join(", ", ImageExtensions)}).");

            var extension = kind == "pdf"
                ? ".pdf"
                : NormalizeImageExtension(Path.GetExtension(fileName));

            var originalRel = Path.Combine("originals", sha256 + extension);
            var originalAbs = Path.Combine(storage.DataRoot, originalRel);
            Directory.CreateDirectory(Path.GetDirectoryName(originalAbs)!);
            File.Move(tempPath, originalAbs, overwrite: true);

            var document = new SourceDocument
            {
                Id = Guid.NewGuid(),
                Sha256 = sha256,
                FileName = Path.GetFileName(fileName),
                ContentType = contentType ?? "",
                SizeBytes = sizeBytes,
                SourceKind = kind,
                UploadedAtUtc = DateTime.UtcNow
            };

            var pagesDirRel = Path.Combine("pages", sha256);
            var thumbsDirRel = Path.Combine("thumbnails", sha256);
            Directory.CreateDirectory(Path.Combine(storage.DataRoot, pagesDirRel));
            Directory.CreateDirectory(Path.Combine(storage.DataRoot, thumbsDirRel));

            try
            {
                if (kind == "pdf")
                    await Task.Run(() => RenderPdfPages(document, originalAbs, pagesDirRel, thumbsDirRel, ct), ct);
                else
                    await NormalizeUploadedImageAsync(document, originalAbs, pagesDirRel, thumbsDirRel, ct);
            }
            catch (Exception ex) when (ex is not OperationCanceledException and not InvalidDataException)
            {
                CleanupDerived(originalAbs, pagesDirRel, thumbsDirRel);
                throw new InvalidDataException($"Impossibile elaborare '{fileName}': {ex.Message}", ex);
            }
            catch (InvalidDataException)
            {
                CleanupDerived(originalAbs, pagesDirRel, thumbsDirRel);
                throw;
            }

            document.PageCount = document.Pages.Count;
            db.Documents.Add(document);
            await db.SaveChangesAsync(ct);

            logger.LogInformation(
                "Ingerito '{FileName}' ({Kind}, {Pages} pagine, {Sha256}).",
                document.FileName, document.SourceKind, document.PageCount, sha256);

            return new IngestionResult(document, false);
        }
        finally
        {
            if (File.Exists(tempPath))
                File.Delete(tempPath);
        }
    }

    private void RenderPdfPages(SourceDocument document, string pdfAbsPath, string pagesDirRel, string thumbsDirRel, CancellationToken ct)
    {
        if (!OperatingSystem.IsWindows() && !OperatingSystem.IsLinux() && !OperatingSystem.IsMacOS())
            throw new PlatformNotSupportedException("Il rendering PDF richiede Windows, Linux o macOS.");

        using var pdfStream = File.OpenRead(pdfAbsPath);
        var pageNumber = 0;

#pragma warning disable CA1416 // guard runtime sopra: server Windows/Linux/macOS
        foreach (var rendered in Conversion.ToImages(pdfStream, options: new RenderOptions(Dpi: PdfRenderDpi)))
#pragma warning restore CA1416
        {
            ct.ThrowIfCancellationRequested();
            pageNumber++;
            using var bitmap = rendered;

            var pageRel = Path.Combine(pagesDirRel, $"p{pageNumber:D3}.png");
            using (var data = bitmap.Encode(SKEncodedImageFormat.Png, 100))
            using (var fs = File.Create(Path.Combine(storage.DataRoot, pageRel)))
            {
                data.SaveTo(fs);
            }

            var thumbRel = Path.Combine(thumbsDirRel, $"p{pageNumber:D3}.png");
            WriteThumbnail(bitmap, Path.Combine(storage.DataRoot, thumbRel));

            document.Pages.Add(new DocumentPage
            {
                Id = Guid.NewGuid(),
                DocumentId = document.Id,
                PageNumber = pageNumber,
                WidthPx = bitmap.Width,
                HeightPx = bitmap.Height,
                RenderDpi = PdfRenderDpi,
                ImagePath = pageRel,
                ThumbnailPath = thumbRel
            });
        }

        if (pageNumber == 0)
            throw new InvalidDataException("Il PDF non contiene pagine renderizzabili.");
    }

    private async Task NormalizeUploadedImageAsync(SourceDocument document, string imageAbsPath, string pagesDirRel, string thumbsDirRel, CancellationToken ct)
    {
        using var image = await Image.LoadAsync(imageAbsPath, ct);

        var pageRel = Path.Combine(pagesDirRel, "p001.png");
        await image.SaveAsPngAsync(Path.Combine(storage.DataRoot, pageRel), ct);

        var thumbRel = Path.Combine(thumbsDirRel, "p001.png");
        if (Math.Max(image.Width, image.Height) <= ThumbnailMaxSide)
        {
            await image.SaveAsPngAsync(Path.Combine(storage.DataRoot, thumbRel), ct);
        }
        else
        {
            using var thumb = image.Clone(x => x.Resize(new ResizeOptions
            {
                Mode = ResizeMode.Max,
                Size = new Size(ThumbnailMaxSide, ThumbnailMaxSide)
            }));
            await thumb.SaveAsPngAsync(Path.Combine(storage.DataRoot, thumbRel), ct);
        }

        document.Pages.Add(new DocumentPage
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            PageNumber = 1,
            WidthPx = image.Width,
            HeightPx = image.Height,
            RenderDpi = (int)Math.Round(image.Metadata.HorizontalResolution),
            ImagePath = pageRel,
            ThumbnailPath = thumbRel
        });
    }

    private void WriteThumbnail(SKBitmap source, string absPath)
    {
        var scale = Math.Min(1.0, (double)ThumbnailMaxSide / Math.Max(source.Width, source.Height));
        var width = Math.Max(1, (int)Math.Round(source.Width * scale));
        var height = Math.Max(1, (int)Math.Round(source.Height * scale));

        using var resized = source.Resize(
            new SKImageInfo(width, height),
            new SKSamplingOptions(SKFilterMode.Linear, SKMipmapMode.Linear))
            ?? throw new InvalidOperationException("Generazione thumbnail fallita.");

        using var data = resized.Encode(SKEncodedImageFormat.Png, 90);
        using var fs = File.Create(absPath);
        data.SaveTo(fs);
    }

    private void CleanupDerived(string originalAbs, string pagesDirRel, string thumbsDirRel)
    {
        try
        {
            if (File.Exists(originalAbs)) File.Delete(originalAbs);
            var pagesAbs = Path.Combine(storage.DataRoot, pagesDirRel);
            var thumbsAbs = Path.Combine(storage.DataRoot, thumbsDirRel);
            if (Directory.Exists(pagesAbs)) Directory.Delete(pagesAbs, recursive: true);
            if (Directory.Exists(thumbsAbs)) Directory.Delete(thumbsAbs, recursive: true);
        }
        catch (IOException ex)
        {
            logger.LogWarning(ex, "Pulizia parziale dopo ingestione fallita.");
        }
    }

    private static string? DetectKind(string filePath, string fileName, string? contentType)
    {
        Span<byte> header = stackalloc byte[5];
        using (var fs = File.OpenRead(filePath))
        {
            var read = fs.Read(header);
            if (read >= 5 && header[0] == (byte)'%' && header[1] == (byte)'P' &&
                header[2] == (byte)'D' && header[3] == (byte)'F' && header[4] == (byte)'-')
                return "pdf";
        }

        var extension = Path.GetExtension(fileName);
        if (!string.IsNullOrEmpty(extension) && ImageExtensions.Contains(extension))
            return "image";

        if (string.Equals(contentType, "application/pdf", StringComparison.OrdinalIgnoreCase))
            return "pdf";
        if (contentType?.StartsWith("image/", StringComparison.OrdinalIgnoreCase) == true)
            return "image";

        return null;
    }

    private static string NormalizeImageExtension(string extension) =>
        string.IsNullOrEmpty(extension) || !ImageExtensions.Contains(extension)
            ? ".img"
            : extension.ToLowerInvariant();
}
