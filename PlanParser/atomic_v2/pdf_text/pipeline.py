"""Extract unmodified native PDF text spans and map them into one plan region."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class PdfTextError(RuntimeError):
    """Raised for invalid native-PDF-text extraction inputs."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_reference(path: Path) -> tuple[str, str]:
    project_root = Path(__file__).resolve().parents[3]
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root).as_posix(), "project_relative"
    except ValueError:
        return resolved.as_posix(), "absolute"


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PdfTextError(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PdfTextError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PdfTextError(f"{label} root must be a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    path.write_bytes(encoded)


def _round(value: float) -> float:
    return round(float(value), 6)


def _xyxy(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        raise PdfTextError(f"invalid bbox: {values!r}")
    return [_round(float(value)) for value in values]


def _intersection(a: list[float], b: list[float]) -> list[float] | None:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return [_round(x0), _round(y0), _round(x1), _round(y1)]


def _translate(bbox: list[float], x: float, y: float) -> list[float]:
    return [
        _round(bbox[0] - x),
        _round(bbox[1] - y),
        _round(bbox[2] - x),
        _round(bbox[3] - y),
    ]


def _render_overlay(
    crop_path: Path,
    output_path: Path,
    objects: list[dict[str, Any]],
    *,
    abstained: bool,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise PdfTextError("Pillow is required for the native text overlay") from exc

    try:
        with Image.open(crop_path) as opened:
            overlay = opened.convert("RGB")
    except Exception as exc:
        raise PdfTextError(f"cannot decode region crop: {exc}") from exc

    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()
    for item in objects:
        x0, y0, x1, y1 = item["bbox_region_local_clipped_px_xyxy"]
        draw.rectangle((x0, y0, x1, y1), outline=(118, 42, 176), width=2)
        label = f"{item['id']} conf=null"
        label_bbox = draw.textbbox((x0, y0), label, font=font)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        label_y = max(0, int(y0) - label_height - 4)
        draw.rectangle(
            (int(x0), label_y, int(x0) + label_width + 4, label_y + label_height + 3),
            fill=(255, 255, 255),
        )
        draw.text((int(x0) + 2, label_y + 1), label, fill=(118, 42, 176), font=font)

    if abstained:
        label = "ABSTAINED: 0 native PDF text objects"
        label_bbox = draw.textbbox((0, 0), label, font=font)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        draw.rectangle((0, 0, label_width + 12, label_height + 10), fill=(255, 255, 255))
        draw.rectangle((0, 0, label_width + 12, label_height + 10), outline=(210, 35, 35), width=2)
        draw.text((6, 5), label, fill=(210, 35, 35), font=font)

    overlay.save(output_path, format="PNG", compress_level=9, optimize=False)


def extract_native_pdf_text(
    pdf_path: Path | str,
    ingest_manifest_path: Path | str,
    regions_manifest_path: Path | str,
    region_id: str,
    output_dir: Path | str,
    *,
    page_index: int = 0,
) -> Path:
    """Extract native PDF spans intersecting one region, without merging or correction."""

    pdf = Path(pdf_path).resolve()
    ingest_path = Path(ingest_manifest_path).resolve()
    regions_path = Path(regions_manifest_path).resolve()
    destination = Path(output_dir).resolve()
    if not pdf.is_file():
        raise PdfTextError(f"PDF source does not exist: {pdf}")
    if destination.exists():
        raise PdfTextError(f"output directory already exists; refusing to overwrite: {destination}")
    if page_index < 0:
        raise ValueError("page_index cannot be negative")

    ingest = _load_json(ingest_path, "ingest manifest")
    regions = _load_json(regions_path, "regions manifest")
    if ingest.get("source", {}).get("sha256") != _sha256(pdf):
        raise PdfTextError("PDF SHA-256 does not match the ingest manifest")

    ingest_pages = ingest.get("document", {}).get("pages", [])
    if page_index >= len(ingest_pages):
        raise PdfTextError("page_index is outside the ingest manifest")
    rendered = ingest_pages[page_index].get("rendered", {})
    rendered_dimensions = rendered.get("dimensions", {})
    page_width_px = int(rendered_dimensions.get("width", 0))
    page_height_px = int(rendered_dimensions.get("height", 0))
    if page_width_px <= 0 or page_height_px <= 0:
        raise PdfTextError("ingest manifest has invalid rendered page dimensions")

    region = next(
        (item for item in regions.get("regions", []) if item.get("id") == region_id),
        None,
    )
    if region is None:
        raise PdfTextError(f"region {region_id!r} is absent from regions manifest")
    region_bbox_xywh = region.get("bbox_px")
    if not isinstance(region_bbox_xywh, list) or len(region_bbox_xywh) != 4:
        raise PdfTextError("region bbox_px must be [x, y, width, height]")
    rx, ry, rw, rh = [int(value) for value in region_bbox_xywh]
    region_bbox_xyxy = [float(rx), float(ry), float(rx + rw), float(ry + rh)]

    crop_path = regions_path.parent / f"{region_id}.png"
    if not crop_path.is_file():
        raise PdfTextError(f"region crop does not exist: {crop_path}")

    try:
        import fitz
    except ImportError as exc:
        raise PdfTextError("PyMuPDF is required for native PDF text extraction") from exc

    try:
        document = fitz.open(pdf)
    except Exception as exc:
        raise PdfTextError(f"cannot open PDF: {exc}") from exc

    try:
        if page_index >= document.page_count:
            raise PdfTextError("page_index is outside the PDF")
        page = document.load_page(page_index)
        if page.rotation != 0:
            raise PdfTextError(
                "this coordinate mapper requires page rotation 0; refusing an ambiguous transform"
            )
        page_width_points = float(page.rect.width)
        page_height_points = float(page.rect.height)
        scale_x = page_width_px / page_width_points
        scale_y = page_height_px / page_height_points
        text_dictionary = page.get_text("dict", sort=False)

        total_blocks = len(text_dictionary.get("blocks", []))
        total_text_blocks = 0
        total_lines = 0
        total_spans = 0
        objects: list[dict[str, Any]] = []
        for block_index, block in enumerate(text_dictionary.get("blocks", [])):
            lines = block.get("lines")
            if not isinstance(lines, list):
                continue
            total_text_blocks += 1
            for line_index, line in enumerate(lines):
                total_lines += 1
                for span_index, span in enumerate(line.get("spans", [])):
                    total_spans += 1
                    raw_bbox = _xyxy(span.get("bbox"))
                    page_png_bbox = [
                        _round(raw_bbox[0] * scale_x),
                        _round(raw_bbox[1] * scale_y),
                        _round(raw_bbox[2] * scale_x),
                        _round(raw_bbox[3] * scale_y),
                    ]
                    clipped = _intersection(page_png_bbox, region_bbox_xyxy)
                    if clipped is None:
                        continue

                    objects.append(
                        {
                            "abstained": False,
                            "bbox_pdf_points_raw_xyxy": raw_bbox,
                            "bbox_page_png_px_xyxy": page_png_bbox,
                            "bbox_region_local_clipped_px_xyxy": _translate(clipped, rx, ry),
                            "bbox_region_local_px_xyxy": _translate(page_png_bbox, rx, ry),
                            "confidence": None,
                            "font_raw": span.get("font"),
                            "font_size_points_raw": (
                                _round(span["size"]) if span.get("size") is not None else None
                            ),
                            "id": f"pdf_text_{len(objects) + 1:04d}",
                            "pdf_structure_index": {
                                "block": block_index,
                                "line": line_index,
                                "span": span_index,
                            },
                            "reasons": [
                                "native_pdf_text_span_intersects_region",
                                "confidence_unavailable: PyMuPDF native text extraction exposes no OCR confidence",
                            ],
                            "transcription_raw": span.get("text", ""),
                        }
                    )
    finally:
        document.close()

    abstained = len(objects) == 0
    destination.mkdir(parents=True, exist_ok=False)
    overlay_path = destination / "pdf_text_overlay.png"
    _render_overlay(crop_path, overlay_path, objects, abstained=abstained)

    pdf_reference, pdf_reference_kind = _project_reference(pdf)
    ingest_reference, _ = _project_reference(ingest_path)
    regions_reference, _ = _project_reference(regions_path)
    crop_reference, _ = _project_reference(crop_path)
    report = {
        "inventory": {
            "intersecting_native_text_spans": len(objects),
            "page_blocks": total_blocks,
            "page_lines": total_lines,
            "page_native_text_spans": total_spans,
            "page_text_blocks": total_text_blocks,
        },
        "mapping": {
            "formula": "page_png_x=pdf_x*scale_x; page_png_y=pdf_y*scale_y; local=page_png-region_origin",
            "page_dimensions_pdf_points": [_round(page_width_points), _round(page_height_points)],
            "page_dimensions_png_px": [page_width_px, page_height_px],
            "page_rotation_degrees_clockwise": 0,
            "scale_x_px_per_point": _round(scale_x),
            "scale_y_px_per_point": _round(scale_y),
        },
        "objects": objects,
        "output": {
            "overlay_file": "pdf_text_overlay.png",
            "overlay_sha256": _sha256(overlay_path),
        },
        "provenance": {
            "crop": {
                "path": crop_reference,
                "sha256": _sha256(crop_path),
            },
            "engine": "PyMuPDF.native_pdf_text",
            "engine_version": str(fitz.VersionBind),
            "ingest_manifest": {
                "path": ingest_reference,
                "sha256": _sha256(ingest_path),
            },
            "regions_manifest": {
                "path": regions_reference,
                "sha256": _sha256(regions_path),
            },
            "semantic_assignment": False,
            "span_merging": False,
            "text_correction": False,
        },
        "region": {
            "abstained": abstained,
            "bbox_page_png_px_xywh": [rx, ry, rw, rh],
            "bbox_region_local_px_xywh": [0, 0, rw, rh],
            "confidence": None,
            "id": region_id,
            "reasons": (
                ["no_native_pdf_text_objects_intersect_region"]
                if abstained
                else [
                    "native_pdf_text_objects_intersect_region",
                    "confidence_unavailable: PyMuPDF native text extraction exposes no OCR confidence",
                ]
            ),
            "transcription_raw": None,
            "transcription_status": "not_merged_by_design" if not abstained else "unavailable",
        },
        "schema": "planparser.atomic_v2.native_pdf_text",
        "schema_version": "1.0.0",
        "source": {
            "byte_size": pdf.stat().st_size,
            "page_index": page_index,
            "page_number": page_index + 1,
            "path": pdf_reference,
            "reference_kind": pdf_reference_kind,
            "sha256": _sha256(pdf),
        },
        "status": "abstained" if abstained else "completed",
    }
    report_path = destination / "pdf_text.json"
    _write_json(report_path, report)
    return report_path
