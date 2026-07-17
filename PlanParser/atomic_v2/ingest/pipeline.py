"""Format-aware, deterministic ingestion without geometry or OCR concerns."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any


class IngestError(RuntimeError):
    """Base error raised by the isolated ingestion pipeline."""


class UnsupportedSourceError(IngestError):
    """Raised when source bytes do not identify a supported document type."""


_FORMAT_BY_EXTENSION = {
    ".jpeg": "jpeg",
    ".jpg": "jpeg",
    ".pdf": "pdf",
    ".png": "png",
}

_MIME_BY_FORMAT = {
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
    "png": "image/png",
}

_EXIF_ORIENTATION = 274

_ORIENTATION_TRANSFORMS: dict[int, tuple[int, str | None]] = {
    1: (0, None),
    2: (0, "horizontal"),
    3: (180, None),
    4: (0, "vertical"),
    5: (90, "horizontal"),
    6: (90, None),
    7: (270, "horizontal"),
    8: (270, None),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_format(path: Path) -> str:
    with path.open("rb") as stream:
        signature = stream.read(16)

    if signature.startswith(b"%PDF-"):
        detected = "pdf"
    elif signature.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "png"
    elif signature.startswith(b"\xff\xd8\xff"):
        detected = "jpeg"
    else:
        raise UnsupportedSourceError(
            f"unsupported source bytes in {path.name!r}; expected PDF, PNG, or JPEG"
        )

    extension_format = _FORMAT_BY_EXTENSION.get(path.suffix.lower())
    if extension_format is None:
        raise UnsupportedSourceError(
            f"unsupported extension {path.suffix!r}; expected .pdf, .png, .jpg, or .jpeg"
        )
    if extension_format != detected:
        raise UnsupportedSourceError(
            f"extension {path.suffix!r} does not match detected {detected.upper()} bytes"
        )
    return detected


def _source_reference(path: Path) -> tuple[str, str]:
    project_root = Path(__file__).resolve().parents[3]
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root).as_posix(), "project_relative"
    except ValueError:
        return resolved.as_posix(), "absolute"


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _dimensions(width: int | float, height: int | float, unit: str) -> dict[str, Any]:
    conversion = int if unit == "pixels" else _rounded
    return {
        "height": conversion(height),
        "unit": unit,
        "width": conversion(width),
    }


def _normalise_dpi(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, (tuple, list)) or len(raw) < 2:
        return None
    try:
        x = float(raw[0])
        y = float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (x > 0 and y > 0):
        return None
    return {"x": _rounded(x), "y": _rounded(y)}


def _render_pdf(source: Path, pages_dir: Path, pdf_dpi: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        raise IngestError("PDF ingestion requires PyMuPDF (fitz)") from exc

    pages: list[dict[str, Any]] = []
    try:
        document = fitz.open(source)
    except Exception as exc:
        raise IngestError(f"cannot open PDF {source.name!r}: {exc}") from exc

    try:
        if document.needs_pass:
            raise IngestError("password-protected PDFs are not accepted")
        if document.page_count < 1:
            raise IngestError("PDF contains no pages")

        scale = pdf_dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        for index in range(document.page_count):
            page = document.load_page(index)
            rendered_name = f"page_{index + 1:04d}.png"
            rendered_path = pages_dir / rendered_name
            try:
                pixmap = page.get_pixmap(
                    matrix=matrix,
                    colorspace=fitz.csRGB,
                    alpha=False,
                    annots=True,
                )
                pixmap.set_dpi(pdf_dpi, pdf_dpi)
                pixmap.save(rendered_path)
            except Exception as exc:
                raise IngestError(f"cannot rasterize PDF page {index + 1}: {exc}") from exc

            pages.append(
                {
                    "page_index": index,
                    "page_number": index + 1,
                    "rendered": {
                        "alpha": False,
                        "byte_size": rendered_path.stat().st_size,
                        "color_space": "RGB",
                        "dimensions": _dimensions(pixmap.width, pixmap.height, "pixels"),
                        "dpi": {"basis": "configured_pdf_render", "x": pdf_dpi, "y": pdf_dpi},
                        "file": f"pages/{rendered_name}",
                        "mime_type": "image/png",
                        "sha256": _sha256(rendered_path),
                    },
                    "source": {
                        "crop_box": _dimensions(page.cropbox.width, page.cropbox.height, "points"),
                        "display_dimensions": _dimensions(page.rect.width, page.rect.height, "points"),
                        "dpi": None,
                        "dpi_status": "not_applicable_to_vector_page",
                        "media_box": _dimensions(page.mediabox.width, page.mediabox.height, "points"),
                        "rotation_degrees_clockwise": int(page.rotation),
                    },
                }
            )
    finally:
        document.close()

    engine = {
        "annotations_rendered": True,
        "library": "PyMuPDF",
        "library_version": str(fitz.VersionBind),
        "pdf_render_dpi": pdf_dpi,
    }
    return pages, engine


def _render_image(source: Path, pages_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        raise IngestError("image ingestion requires Pillow") from exc

    rendered_name = "page_0001.png"
    rendered_path = pages_dir / rendered_name
    try:
        with Image.open(source) as image:
            image.load()
            raw_width, raw_height = image.size
            raw_mode = image.mode
            raw_dpi = _normalise_dpi(image.info.get("dpi"))
            try:
                orientation = int(image.getexif().get(_EXIF_ORIENTATION, 1))
            except (TypeError, ValueError):
                orientation = 1
            rotation, mirror = _ORIENTATION_TRANSFORMS.get(orientation, (0, None))

            normalised = ImageOps.exif_transpose(image)
            if normalised.mode in {"RGBA", "LA"}:
                output = normalised.convert("RGBA")
            elif normalised.mode == "P" and "transparency" in normalised.info:
                output = normalised.convert("RGBA")
            else:
                output = normalised.convert("RGB")

            save_options: dict[str, Any] = {"compress_level": 9, "optimize": False}
            if raw_dpi is not None:
                save_options["dpi"] = (raw_dpi["x"], raw_dpi["y"])
            output.save(rendered_path, format="PNG", **save_options)
            output_width, output_height = output.size
            output_mode = output.mode
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"cannot decode image {source.name!r}: {exc}") from exc

    output_dpi: dict[str, Any] | None
    if raw_dpi is None:
        output_dpi = None
        dpi_status = "not_declared_by_source"
    else:
        output_dpi = {"basis": "preserved_from_source", **raw_dpi}
        dpi_status = "declared_and_preserved"

    page = {
        "page_index": 0,
        "page_number": 1,
        "rendered": {
            "alpha": output_mode == "RGBA",
            "byte_size": rendered_path.stat().st_size,
            "color_space": output_mode,
            "dimensions": _dimensions(output_width, output_height, "pixels"),
            "dpi": output_dpi,
            "file": f"pages/{rendered_name}",
            "mime_type": "image/png",
            "sha256": _sha256(rendered_path),
        },
        "source": {
            "dimensions": _dimensions(raw_width, raw_height, "pixels"),
            "dpi": raw_dpi,
            "dpi_status": dpi_status,
            "exif_orientation": orientation,
            "mirror_applied": mirror,
            "mode": raw_mode,
            "rotation_applied_degrees_clockwise": rotation,
        },
    }
    engine = {
        "exif_orientation_normalized": True,
        "library": "Pillow",
        "library_version": str(Image.__version__),
        "pixel_resampling": False,
    }
    return [page], engine


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    path.write_bytes(encoded)


def ingest_source(source: Path | str, output_dir: Path | str, *, pdf_dpi: int = 300) -> Path:
    """Ingest one supported source into a new immutable-style artifact directory.

    The output directory must not exist. This prevents accidental overwrite of any
    previous run and keeps every generated artifact traceable to its manifest.
    """

    source_path = Path(source).resolve()
    destination = Path(output_dir).resolve()

    if not source_path.is_file():
        raise IngestError(f"source is not a readable file: {source_path}")
    if destination.exists():
        raise IngestError(f"output directory already exists; refusing to overwrite: {destination}")
    if not isinstance(pdf_dpi, int) or isinstance(pdf_dpi, bool) or not 72 <= pdf_dpi <= 1200:
        raise ValueError("pdf_dpi must be an integer between 72 and 1200")

    source_format = _detect_format(source_path)
    destination.mkdir(parents=True, exist_ok=False)
    pages_dir = destination / "pages"
    pages_dir.mkdir()

    if source_format == "pdf":
        pages, engine = _render_pdf(source_path, pages_dir, pdf_dpi)
    else:
        pages, engine = _render_image(source_path, pages_dir)

    reference, reference_kind = _source_reference(source_path)
    manifest = {
        "document": {
            "page_count": len(pages),
            "pages": pages,
        },
        "ingestion": {
            "engine": engine,
            "operation": "source_to_canonical_png_pages",
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
        "schema": "planparser.atomic_v2.ingest_manifest",
        "schema_version": "1.0.0",
        "source": {
            "byte_size": source_path.stat().st_size,
            "detected_format": source_format,
            "extension": source_path.suffix.lower(),
            "filename": source_path.name,
            "mime_type": _MIME_BY_FORMAT[source_format],
            "reference": reference,
            "reference_kind": reference_kind,
            "sha256": _sha256(source_path),
        },
    }
    manifest_path = destination / "manifest.json"
    _write_manifest(manifest_path, manifest)
    return manifest_path
