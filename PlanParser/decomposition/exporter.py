"""Build Point 1 decomposition documents from PlanParser extraction results."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .validator import DECOMPOSITION_VERSION, load_taxonomy


ROOM_WORDS = {
    "bagno", "camera", "cantina", "corridoio", "cucina", "disimpegno",
    "garage", "ingresso", "ripostiglio", "sala", "salotto", "soggiorno",
    "studio", "terrazzo", "veranda", "wc",
}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_type(path: Path) -> str:
    extension = Path(path).suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".webp": "image/webp",
    }
    if extension not in mapping:
        raise ValueError(f"Unsupported Point 1 input extension: {extension or '<none>'}")
    return mapping[extension]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provenance(
    method: str,
    producer: str,
    version: str,
    derived_from: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "method": method,
        "producer": producer,
        "producer_version": version,
        "created_at": _timestamp(),
        "derived_from": list(derived_from),
    }


def _confidence(score: float, reason: str, calibration: str | None = None) -> dict[str, Any]:
    score = max(0.0, min(float(score), 1.0))
    return {
        "score": score,
        "calibration_version": calibration,
        "abstained": score <= 0.0,
        "reasons": [reason] if reason else [],
    }


def _clamped_bbox(
    x: float,
    y: float,
    width: float,
    height: float,
    page_width: int,
    page_height: int,
) -> list[float]:
    left = max(0.0, min(float(x), page_width - 1.0))
    top = max(0.0, min(float(y), page_height - 1.0))
    right = max(left + 1.0, min(float(x + max(width, 1.0)), float(page_width)))
    bottom = max(top + 1.0, min(float(y + max(height, 1.0)), float(page_height)))
    return [left, top, right - left, bottom - top]


def _points_bbox(
    points: Sequence[Sequence[float]], page_width: int, page_height: int, padding: float = 2.0
) -> list[float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return _clamped_bbox(
        min(xs) - padding,
        min(ys) - padding,
        max(xs) - min(xs) + 2 * padding,
        max(ys) - min(ys) + 2 * padding,
        page_width,
        page_height,
    )


def classify_text(text: str) -> str:
    normalized = " ".join(text.lower().replace(".", " ").split())
    if re.search(r"\b\d+(?:[.,]\d+)?\s*:\s*\d+(?:[.,]\d+)?\b", normalized):
        return "scale_text"
    if any(word in normalized.split() for word in ROOM_WORDS):
        return "room_label"
    if re.search(r"\b(?:piano|livello|quota)\b", normalized):
        return "level_text"
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m|mq|m2|m²)\b", normalized):
        return "dimension_text"
    return "unknown_text"


def _observation(
    observation_id: str,
    layer: str,
    class_id: str,
    geometry: Mapping[str, Any],
    page_id: str,
    evidence_bbox: Sequence[float],
    score: float,
    reason: str,
    producer: str,
    producer_version: str,
    attributes: Mapping[str, Any] | None = None,
    derived_from: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "layer": layer,
        "class_id": class_id,
        "geometry": dict(geometry),
        "evidence": {
            "page_id": page_id,
            "crop_bbox_px": list(evidence_bbox),
            "source_object_refs": [],
        },
        "confidence": _confidence(score, reason),
        "provenance": _provenance(
            "derived" if tuple(derived_from) else "model",
            producer,
            producer_version,
            derived_from,
        ),
        "reviews": [],
        "attributes": dict(attributes or {}),
    }


def build_page_record(
    *,
    page_index: int,
    width_px: int,
    height_px: int,
    render_dpi: float | None,
    floor_results: Sequence[Mapping[str, Any]],
    cv_version: str,
) -> tuple[dict[str, Any], list[str]]:
    """Convert current extraction results into source-linked observations."""
    page_id = f"page-{page_index}"
    observations: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    warnings: list[str] = []

    for floor_index, result in enumerate(floor_results):
        floor = result["floor"]
        extraction = result["extraction"]
        rooms = result.get("rooms", [])
        rect = floor.source_rect or (0, 0, floor.image.shape[1], floor.image.shape[0])
        offset_x, offset_y, rect_width, rect_height = rect
        floor_bbox = _clamped_bbox(
            offset_x, offset_y, rect_width, rect_height, width_px, height_px
        )

        region_id = f"p{page_index}-f{floor_index}-drawing"
        floor_id = f"p{page_index}-f{floor_index}-candidate"
        observations.append(_observation(
            region_id,
            "source_region",
            "drawing_area",
            {"type": "bbox", "bbox": floor_bbox},
            page_id,
            floor_bbox,
            floor.confidence,
            "floor-region detector; confidence is uncalibrated",
            "PlanParser.floor_detection",
            "0.1.0",
            {"floor_label_candidate": floor.label},
        ))
        observations.append(_observation(
            floor_id,
            "architectural_candidate",
            "floor_plan",
            {"type": "bbox", "bbox": floor_bbox},
            page_id,
            floor_bbox,
            floor.confidence,
            "floor candidate; confidence is uncalibrated",
            "PlanParser.floor_detection",
            "0.1.0",
            {"label_candidate": floor.label},
            [region_id],
        ))

        line_ids: list[str] = []
        for line_index, segment in enumerate(extraction.segments):
            points = [
                [float(segment.x1 + offset_x), float(segment.y1 + offset_y)],
                [float(segment.x2 + offset_x), float(segment.y2 + offset_y)],
            ]
            line_id = f"p{page_index}-f{floor_index}-line-{line_index}"
            line_ids.append(line_id)
            observations.append(_observation(
                line_id,
                "geometry",
                "line_segment",
                {"type": "polyline", "points": points},
                page_id,
                _points_bbox(points, width_px, height_px),
                0.5,
                "Hough segment; score not calibrated",
                "opencv.HoughLinesP",
                cv_version,
                {
                    "length_px": float(segment.length),
                    "angle_deg": float(segment.angle_deg),
                    "floor_candidate_id": floor_id,
                },
            ))

        for text_index, block in enumerate(extraction.text_blocks):
            bbox = _clamped_bbox(
                block.x + offset_x,
                block.y + offset_y,
                block.w,
                block.h,
                width_px,
                height_px,
            )
            score = float(block.confidence)
            if score > 1:
                score /= 100.0
            observations.append(_observation(
                f"p{page_index}-f{floor_index}-text-{text_index}",
                "text",
                classify_text(block.text),
                {"type": "bbox", "bbox": bbox},
                page_id,
                bbox,
                score,
                "OCR confidence; calibration pending Gate 1 dataset",
                "PlanParser.multi_variant_tesseract",
                "0.1.0",
                {"transcription": block.text, "floor_candidate_id": floor_id},
            ))

        if not extraction.text_blocks:
            warnings.append(f"{page_id}/{floor_id}: no text observations")

        for room_index, room in enumerate(rooms):
            polygon = [
                [float(point[0] + offset_x), float(point[1] + offset_y)]
                for point in room.polygon
            ]
            if len(polygon) < 3:
                continue
            room_id = f"p{page_index}-f{floor_index}-room-{room_index}"
            observations.append(_observation(
                room_id,
                "architectural_candidate",
                "room_region",
                {"type": "polygon", "points": polygon},
                page_id,
                _points_bbox(polygon, width_px, height_px),
                float(room.label_confidence),
                "room candidate combines topology and label confidence; calibration pending",
                "PlanParser.SemanticAnalyzer",
                "0.1.0",
                {
                    "label_candidate": room.label,
                    "area_px2": float(room.area_px),
                    "floor_candidate_id": floor_id,
                },
                line_ids,
            ))
            relationships.append({
                "id": f"rel-{room_id}-floor",
                "type": "candidate_part_of",
                "from_id": room_id,
                "to_id": floor_id,
                "confidence": max(0.0, min(float(room.label_confidence), 1.0)),
                "provenance": _provenance(
                    "derived", "PlanParser.SemanticAnalyzer", "0.1.0", [room_id, floor_id]
                ),
                "reviews": [],
            })

            for wall_index, wall in enumerate(room.walls):
                start = wall.get("start_point", (0, 0))
                end = wall.get("end_point", (0, 0))
                points = [
                    [float(start[0] + offset_x), float(start[1] + offset_y)],
                    [float(end[0] + offset_x), float(end[1] + offset_y)],
                ]
                wall_id = f"{room_id}-wall-{wall_index}"
                observations.append(_observation(
                    wall_id,
                    "architectural_candidate",
                    "wall_axis",
                    {"type": "polyline", "points": points},
                    page_id,
                    _points_bbox(points, width_px, height_px),
                    0.5,
                    "wall classification heuristic; score not calibrated",
                    "PlanParser.SemanticAnalyzer",
                    "0.1.0",
                    {
                        "wall_type_candidate": wall.get("wall_type", "unknown"),
                        "length_px": float(wall.get("length_px", 0.0)),
                    },
                    [room_id],
                ))
                relationships.append({
                    "id": f"rel-{wall_id}-room",
                    "type": "candidate_part_of",
                    "from_id": wall_id,
                    "to_id": room_id,
                    "confidence": 0.5,
                    "provenance": _provenance(
                        "derived", "PlanParser.SemanticAnalyzer", "0.1.0", [wall_id, room_id]
                    ),
                    "reviews": [],
                })

        if not rooms:
            warnings.append(f"{page_id}/{floor_id}: no room candidates")

    page = {
        "id": page_id,
        "page_index": page_index,
        "width_px": width_px,
        "height_px": height_px,
        "render_dpi": render_dpi,
        "rotation_deg": 0,
        "observations": observations,
        "relationships": relationships,
    }
    return page, warnings


def build_document(
    *,
    source_path: Path,
    page_records: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    render_dpi: float,
    pipeline_version: str = "0.1.0",
    model_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_path = Path(source_path)
    source_hash = file_sha256(source_path)
    taxonomy = load_taxonomy()
    config = {"render_dpi": render_dpi, "schema_version": DECOMPOSITION_VERSION}
    return {
        "schema_version": DECOMPOSITION_VERSION,
        "document_id": f"doc-{source_hash[:16]}",
        "source": {
            "filename": source_path.name,
            "media_type": media_type(source_path),
            "sha256": source_hash,
            "page_count": len(page_records),
            "license_id": None,
            "provenance_id": None,
        },
        "taxonomy": {
            "name": taxonomy["name"],
            "version": taxonomy["version"],
            "sha256": canonical_sha256(taxonomy),
        },
        "run": {
            "producer": "PlanParser.decompose",
            "producer_version": pipeline_version,
            "created_at": _timestamp(),
            "config_sha256": canonical_sha256(config),
            "model_versions": dict(model_versions or {}),
        },
        "dataset_status": "draft",
        "pages": [dict(page) for page in page_records],
        "warnings": list(warnings),
    }
