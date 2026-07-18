from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


COMPONENT = "ocr_geometry_guard"
REVISION = "revision_001"
SCHEMA_VERSION = "planparser.atomic_v2.ocr_geometry_guard.v1"

OBJECTNESS_FLOOR = 0.45
GEOMETRY_CONFIDENCE_FLOOR = 0.55
BORDER_MARGIN_PX = 2.0
STRONG_WORD_COVERAGE_FLOOR = 0.45
STRONG_VERTICAL_OVERLAP_FLOOR = 0.50
STRONG_SCORE_FLOOR = 0.52
MODERATE_WORD_COVERAGE_FLOOR = 0.25
MODERATE_VERTICAL_OVERLAP_FLOOR = 0.50
MODERATE_SCORE_FLOOR = 0.40
AMBIGUITY_SCORE_DELTA = 0.08
OCR_BOX_AMBIGUITY_COVERAGE = 0.45


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def candidate_bbox(candidate: dict[str, Any]) -> list[float]:
    raw = candidate["bbox_original_px"]
    x1 = float(raw["x"])
    y1 = float(raw["y"])
    return [x1, y1, x1 + float(raw["width"]), y1 + float(raw["height"])]


def bbox_metrics(word_box: list[float], geometry_box: list[float]) -> dict[str, Any]:
    wx1, wy1, wx2, wy2 = (float(value) for value in word_box)
    gx1, gy1, gx2, gy2 = (float(value) for value in geometry_box)
    word_width = max(0.0, wx2 - wx1)
    word_height = max(0.0, wy2 - wy1)
    geometry_width = max(0.0, gx2 - gx1)
    geometry_height = max(0.0, gy2 - gy1)
    word_area = word_width * word_height
    geometry_area = geometry_width * geometry_height

    ix1 = max(wx1, gx1)
    iy1 = max(wy1, gy1)
    ix2 = min(wx2, gx2)
    iy2 = min(wy2, gy2)
    intersection_width = max(0.0, ix2 - ix1)
    intersection_height = max(0.0, iy2 - iy1)
    intersection_area = intersection_width * intersection_height
    union_area = word_area + geometry_area - intersection_area

    word_coverage = intersection_area / word_area if word_area else 0.0
    geometry_coverage = intersection_area / geometry_area if geometry_area else 0.0
    iou = intersection_area / union_area if union_area else 0.0
    horizontal_overlap = (
        intersection_width / min(word_width, geometry_width)
        if min(word_width, geometry_width) > 0
        else 0.0
    )
    vertical_overlap = (
        intersection_height / min(word_height, geometry_height)
        if min(word_height, geometry_height) > 0
        else 0.0
    )

    word_center = [(wx1 + wx2) / 2.0, (wy1 + wy2) / 2.0]
    geometry_center = [(gx1 + gx2) / 2.0, (gy1 + gy2) / 2.0]
    normalized_dx = abs(word_center[0] - geometry_center[0]) / max(word_width, geometry_width, 1.0)
    normalized_dy = abs(word_center[1] - geometry_center[1]) / max(word_height, geometry_height, 1.0)
    normalized_center_distance = math.hypot(normalized_dx, normalized_dy)
    center_score = max(0.0, 1.0 - normalized_center_distance)
    word_center_inside_geometry = gx1 <= word_center[0] <= gx2 and gy1 <= word_center[1] <= gy2
    geometry_center_inside_word = wx1 <= geometry_center[0] <= wx2 and wy1 <= geometry_center[1] <= wy2

    return {
        "intersection_area_px2": round(intersection_area, 6),
        "iou": round(iou, 6),
        "word_coverage": round(word_coverage, 6),
        "candidate_coverage": round(geometry_coverage, 6),
        "horizontal_overlap_over_smaller": round(horizontal_overlap, 6),
        "vertical_overlap_over_smaller": round(vertical_overlap, 6),
        "normalized_center_distance": round(normalized_center_distance, 6),
        "center_score": round(center_score, 6),
        "word_center_inside_candidate": word_center_inside_geometry,
        "candidate_center_inside_word": geometry_center_inside_word,
        "word_center_px": [round(value, 3) for value in word_center],
        "candidate_center_px": [round(value, 3) for value in geometry_center],
    }


def support_score(metrics: dict[str, Any], geometry_confidence: float) -> float:
    score = (
        0.30 * float(metrics["iou"])
        + 0.25 * float(metrics["word_coverage"])
        + 0.15 * float(metrics["candidate_coverage"])
        + 0.15 * float(metrics["vertical_overlap_over_smaller"])
        + 0.10 * float(metrics["center_score"])
        + 0.05 * max(0.0, min(1.0, geometry_confidence))
    )
    return round(score, 6)


def overlap_coverage(first: list[float], second: list[float]) -> dict[str, float]:
    metrics = bbox_metrics(first, second)
    return {
        "iou": float(metrics["iou"]),
        "first_coverage": float(metrics["word_coverage"]),
        "second_coverage": float(metrics["candidate_coverage"]),
    }


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    color: tuple[int, int, int],
    width: int = 1,
    dash: int = 5,
) -> None:
    x1, y1, x2, y2 = box
    for start in range(int(x1), int(x2) + 1, dash * 2):
        draw.line((start, y1, min(start + dash, x2), y1), fill=color, width=width)
        draw.line((start, y2, min(start + dash, x2), y2), fill=color, width=width)
    for start in range(int(y1), int(y2) + 1, dash * 2):
        draw.line((x1, start, x1, min(start + dash, y2)), fill=color, width=width)
        draw.line((x2, start, x2, min(start + dash, y2)), fill=color, width=width)


def short_reason(reasons: list[str]) -> str:
    mapping = {
        "source_border_clipping": "border",
        "low_detector_objectness": "low_obj",
        "missing_detector_objectness": "no_obj",
        "ambiguous_geometric_overlap": "ambiguous",
        "no_eligible_geometric_candidate": "no_geo",
        "insufficient_independent_geometry_support": "weak_geo",
        "best_candidate_already_abstained": "cand_abst",
        "best_candidate_border_clipped": "cand_border",
        "best_candidate_below_geometry_floor": "cand_low",
    }
    return ",".join(mapping.get(reason, reason) for reason in reasons[:2])


def render_overlay(
    crop: Image.Image,
    results: list[dict[str, Any]],
    candidates_by_id: dict[str, dict[str, Any]],
    counts: dict[str, int],
) -> bytes:
    header_height = 104
    canvas = Image.new("RGB", (crop.width, crop.height + header_height), "white")
    canvas.paste(crop.convert("RGB"), (0, header_height))
    draw = ImageDraw.Draw(canvas)
    title_font = load_font(17, bold=True)
    body_font = load_font(12)
    small_font = load_font(10, bold=True)
    green = (18, 153, 55)
    green_dark = (9, 96, 32)
    orange = (237, 120, 18)
    orange_dark = (153, 67, 0)
    header_ink = (25, 32, 39)

    draw.text((12, 8), "OCR geometry guard — revision_001", fill=header_ink, font=title_font)
    summary = (
        f"Parole: {counts['words_total']}  |  confermate solo geometricamente: "
        f"{counts['confirmed']}  |  astensioni: {counts['abstained']}"
    )
    draw.text((12, 32), summary, fill=header_ink, font=body_font)
    draw.rectangle((12, 56, 29, 73), outline=green, width=3)
    draw.text((36, 57), "VERDE = supporto geometrico forte", fill=green_dark, font=body_font)
    draw.rectangle((350, 56, 367, 73), outline=orange, width=3)
    draw.text((374, 57), "ARANCIONE = astensione", fill=orange_dark, font=body_font)
    draw.text(
        (12, 80),
        "Il verde NON valida trascrizione, ortografia o significato del testo raw.",
        fill=(78, 86, 94),
        font=body_font,
    )

    for result in results:
        guard = result["geometry_guard"]
        status = guard["status"]
        color = green if status == "confirmed" else orange
        dark = green_dark if status == "confirmed" else orange_dark
        word_box = [float(value) for value in result["bbox_pixels"]]
        x1, y1, x2, y2 = word_box
        shifted_word_box = (x1, y1 + header_height, x2, y2 + header_height)

        best_id = guard["best_candidate_id"]
        if best_id is not None:
            geometry_box = candidate_bbox(candidates_by_id[best_id])
            draw_dashed_rectangle(
                draw,
                (
                    geometry_box[0],
                    geometry_box[1] + header_height,
                    geometry_box[2],
                    geometry_box[3] + header_height,
                ),
                dark,
                width=1,
            )

        draw.rectangle(shifted_word_box, outline=color, width=3)
        raw_text = str(result["text_raw"]).replace("\n", " ")
        if len(raw_text) > 22:
            raw_text = raw_text[:19] + "..."
        if status == "confirmed":
            suffix = f"OK→{best_id}"
        else:
            suffix = f"STOP:{short_reason(guard['reasons'])}"
        label = f"{result['id']} {raw_text} {suffix}"
        text_box = draw.textbbox((0, 0), label, font=small_font)
        label_width = text_box[2] - text_box[0] + 6
        label_height = text_box[3] - text_box[1] + 4
        label_x = max(0, min(int(x1), canvas.width - label_width))
        preferred_y = int(y1 + header_height - label_height - 2)
        label_y = max(header_height, preferred_y)
        draw.rectangle(
            (label_x, label_y, label_x + label_width, label_y + label_height),
            fill=(255, 255, 255),
            outline=color,
            width=1,
        )
        draw.text((label_x + 3, label_y + 1), label, fill=dark, font=small_font)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def main() -> None:
    script_path = Path(__file__).resolve()
    component_root = script_path.parent
    atomic_root = component_root.parent
    doctr_path = atomic_root / "ocr_doctr/artifacts/scheda_catastale/region_001/revision_002/ocr_raw.json"
    geometry_path = atomic_root / "ocr_text_candidates/artifacts/scheda_catastale/region_001/revision_001/text_candidates.json"
    crop_path = atomic_root / "region_split/artifacts/scheda_catastale/page_0001/revision_002/region_001.png"
    output_dir = component_root / "artifacts/scheda_catastale/region_001" / REVISION

    for required in (doctr_path, geometry_path, crop_path):
        if not required.is_file():
            raise FileNotFoundError(f"Required read-only input is missing: {required}")
    if output_dir.exists():
        raise FileExistsError(f"Immutable output revision already exists: {output_dir}")

    doctr = load_json(doctr_path)
    geometry = load_json(geometry_path)
    crop_hash = sha256_file(crop_path)
    doctr_source = doctr.get("source", {})
    geometry_source = geometry.get("source", {})
    expected_hashes = {str(doctr_source.get("sha256")), str(geometry_source.get("sha256")), crop_hash}
    if len(expected_hashes) != 1:
        raise ValueError(f"Input source hashes disagree: {sorted(expected_hashes)}")

    with Image.open(crop_path) as opened:
        crop = opened.convert("RGB")
    width, height = crop.size
    declared_sizes = {
        (int(doctr_source.get("width_pixels", -1)), int(doctr_source.get("height_pixels", -1))),
        (int(geometry_source.get("width_px", -1)), int(geometry_source.get("height_px", -1))),
        (width, height),
    }
    if len(declared_sizes) != 1:
        raise ValueError(f"Input source dimensions disagree: {sorted(declared_sizes)}")

    candidates = list(geometry.get("candidates", []))
    candidates_by_id = {str(item["id"]): item for item in candidates}
    if len(candidates_by_id) != len(candidates):
        raise ValueError("Duplicate geometry candidate ids")

    words = list(doctr.get("words", []))
    ocr_overlaps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, word in enumerate(words):
        first_box = [float(value) for value in word["bbox_pixels"]]
        for other in words[index + 1 :]:
            second_box = [float(value) for value in other["bbox_pixels"]]
            overlap = overlap_coverage(first_box, second_box)
            if max(overlap["first_coverage"], overlap["second_coverage"]) >= OCR_BOX_AMBIGUITY_COVERAGE:
                first_evidence = {"other_word_id": other["id"], **{key: round(value, 6) for key, value in overlap.items()}}
                second_evidence = {
                    "other_word_id": word["id"],
                    "iou": round(overlap["iou"], 6),
                    "first_coverage": round(overlap["second_coverage"], 6),
                    "second_coverage": round(overlap["first_coverage"], 6),
                }
                ocr_overlaps[str(word["id"])].append(first_evidence)
                ocr_overlaps[str(other["id"])].append(second_evidence)

    prepared: list[dict[str, Any]] = []
    candidate_usage: dict[str, list[str]] = defaultdict(list)
    for word in words:
        word_id = str(word["id"])
        word_box = [float(value) for value in word["bbox_pixels"]]
        x1, y1, x2, y2 = word_box
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"Invalid bbox for {word_id}: {word_box} against {width}x{height}")

        alignments: list[dict[str, Any]] = []
        for candidate in candidates:
            cid = str(candidate["id"])
            metrics = bbox_metrics(word_box, candidate_bbox(candidate))
            geometry_confidence = float(candidate.get("confidence_geometry", 0.0))
            eligible = (
                not bool(candidate.get("abstained", True))
                and not bool(candidate.get("border_clipped", False))
                and geometry_confidence >= GEOMETRY_CONFIDENCE_FLOOR
            )
            score = support_score(metrics, geometry_confidence)
            alignment = {
                "candidate_id": cid,
                "candidate_bbox_original_px": candidate["bbox_original_px"],
                "candidate_confidence_geometry": geometry_confidence,
                "candidate_variant_agreement": candidate.get("variant_agreement"),
                "candidate_supporting_variants": list(candidate.get("supporting_variants", [])),
                "candidate_abstained": bool(candidate.get("abstained", True)),
                "candidate_border_clipped": bool(candidate.get("border_clipped", False)),
                "eligible_independent_geometry": eligible,
                "metrics": metrics,
                "support_score": score,
            }
            alignments.append(alignment)
        alignments.sort(key=lambda item: (-float(item["support_score"]), item["candidate_id"]))
        best = alignments[0] if alignments else None
        overlapping = [item for item in alignments if float(item["metrics"]["intersection_area_px2"]) > 0.0]
        eligible_ranked = [
            item
            for item in alignments
            if item["eligible_independent_geometry"]
            and float(item["metrics"]["intersection_area_px2"]) > 0.0
        ]
        best_eligible = eligible_ranked[0] if eligible_ranked else None

        strong_support = False
        moderate_support = False
        if best_eligible is not None:
            metrics = best_eligible["metrics"]
            strong_support = (
                float(best_eligible["support_score"]) >= STRONG_SCORE_FLOOR
                and float(metrics["word_coverage"]) >= STRONG_WORD_COVERAGE_FLOOR
                and float(metrics["vertical_overlap_over_smaller"]) >= STRONG_VERTICAL_OVERLAP_FLOOR
            )
            moderate_support = (
                float(best_eligible["support_score"]) >= MODERATE_SCORE_FLOOR
                and float(metrics["word_coverage"]) >= MODERATE_WORD_COVERAGE_FLOOR
                and float(metrics["vertical_overlap_over_smaller"]) >= MODERATE_VERTICAL_OVERLAP_FLOOR
            )

        competitors = [
            item
            for item in eligible_ranked
            if float(item["support_score"]) >= MODERATE_SCORE_FLOOR
            and float(item["metrics"]["word_coverage"]) >= MODERATE_WORD_COVERAGE_FLOOR
            and float(item["metrics"]["vertical_overlap_over_smaller"]) >= MODERATE_VERTICAL_OVERLAP_FLOOR
        ]
        candidate_ambiguous = (
            len(competitors) >= 2
            and abs(float(competitors[0]["support_score"]) - float(competitors[1]["support_score"])) <= AMBIGUITY_SCORE_DELTA
        )
        ocr_overlap_evidence = ocr_overlaps.get(word_id, [])
        overlap_ambiguous = candidate_ambiguous or bool(ocr_overlap_evidence)

        border_sides: list[str] = []
        if x1 <= BORDER_MARGIN_PX:
            border_sides.append("left")
        if y1 <= BORDER_MARGIN_PX:
            border_sides.append("top")
        if x2 >= width - BORDER_MARGIN_PX:
            border_sides.append("right")
        if y2 >= height - BORDER_MARGIN_PX:
            border_sides.append("bottom")
        source_border_clipped = bool(border_sides)

        objectness_raw = word.get("objectness_score_raw")
        missing_objectness = objectness_raw is None
        low_objectness = missing_objectness or float(objectness_raw) < OBJECTNESS_FLOOR

        reasons: list[str] = []
        if source_border_clipped:
            reasons.append("source_border_clipping")
        if missing_objectness:
            reasons.append("missing_detector_objectness")
        elif low_objectness:
            reasons.append("low_detector_objectness")
        if overlap_ambiguous:
            reasons.append("ambiguous_geometric_overlap")
        if best_eligible is None:
            reasons.append("no_eligible_geometric_candidate")
        elif not strong_support:
            reasons.append("insufficient_independent_geometry_support")
        if best is not None and best_eligible is None:
            if best["candidate_abstained"]:
                reasons.append("best_candidate_already_abstained")
            if best["candidate_border_clipped"]:
                reasons.append("best_candidate_border_clipped")
            if float(best["candidate_confidence_geometry"]) < GEOMETRY_CONFIDENCE_FLOOR:
                reasons.append("best_candidate_below_geometry_floor")

        confirmed = strong_support and not source_border_clipped and not low_objectness and not overlap_ambiguous
        status = "confirmed" if confirmed else "abstained"
        if confirmed:
            reasons = [
                "strong_independent_geometry_support",
                "detector_objectness_above_floor",
                "not_border_clipped",
                "unambiguous_alignment",
            ]

        best_id = None
        if best_eligible is not None:
            best_id = str(best_eligible["candidate_id"])
        elif best is not None and float(best["metrics"]["intersection_area_px2"]) > 0.0:
            best_id = str(best["candidate_id"])
        if best_id is not None:
            candidate_usage[best_id].append(word_id)

        if strong_support:
            support_strength = "strong"
        elif moderate_support:
            support_strength = "moderate"
        elif overlapping:
            support_strength = "weak"
        else:
            support_strength = "none"

        raw_word = {
            "id": word_id,
            "page_index": word.get("page_index"),
            "block_index": word.get("block_index"),
            "line_index": word.get("line_index"),
            "word_index": word.get("word_index"),
            "text_raw": word.get("text_raw"),
            "confidence_raw": word.get("confidence_raw"),
            "objectness_score_raw": objectness_raw,
            "geometry_raw_normalized": word.get("geometry_raw_normalized"),
            "polygon_normalized": word.get("polygon_normalized"),
            "bbox_normalized": word.get("bbox_normalized"),
            "polygon_pixels": word.get("polygon_pixels"),
            "bbox_pixels": word.get("bbox_pixels"),
            "crop_orientation_raw": word.get("crop_orientation_raw"),
            "upstream_abstention": word.get("abstention"),
            "geometry_guard": {
                "status": status,
                "confirmation_scope": "geometry_presence_only_not_transcription_correctness",
                "reasons": reasons,
                "support_strength": support_strength,
                "best_candidate_id": best_id,
                "best_alignment": best_eligible if best_eligible is not None else best,
                "overlapping_candidate_alignments": overlapping,
                "candidate_count_evaluated": len(alignments),
                "source_border_clipped": source_border_clipped,
                "source_border_sides": border_sides,
                "low_detector_objectness": low_objectness,
                "overlap_ambiguous": overlap_ambiguous,
                "candidate_competition": competitors[:2] if candidate_ambiguous else [],
                "ocr_box_overlap_evidence": ocr_overlap_evidence,
                "raw_recognition_confidence_used_for_decision": False,
            },
        }
        prepared.append(raw_word)

    shared_candidates = {
        cid: ids for cid, ids in sorted(candidate_usage.items()) if len(ids) > 1
    }
    status_counts = Counter(item["geometry_guard"]["status"] for item in prepared)
    reason_counts = Counter(
        reason
        for item in prepared
        if item["geometry_guard"]["status"] == "abstained"
        for reason in item["geometry_guard"]["reasons"]
    )
    counts = {
        "words_total": len(prepared),
        "confirmed": int(status_counts.get("confirmed", 0)),
        "abstained": int(status_counts.get("abstained", 0)),
        "geometry_candidates_total": len(candidates),
        "geometry_candidates_used_as_best": len(candidate_usage),
        "shared_best_candidates": len(shared_candidates),
    }
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "created_at_utc": created_at,
        "component": COMPONENT,
        "revision": REVISION,
        "source": {
            "path": str(crop_path.relative_to(atomic_root)).replace(os.sep, "/"),
            "sha256": crop_hash,
            "width_pixels": width,
            "height_pixels": height,
        },
        "inputs": {
            "doctr_raw": {
                "path": str(doctr_path.relative_to(atomic_root)).replace(os.sep, "/"),
                "sha256": sha256_file(doctr_path),
                "schema_version": doctr.get("schema_version"),
                "word_count": len(words),
            },
            "geometry_candidates": {
                "path": str(geometry_path.relative_to(atomic_root)).replace(os.sep, "/"),
                "sha256": sha256_file(geometry_path),
                "schema_version": geometry.get("schema_version"),
                "candidate_count": len(candidates),
            },
        },
        "decision_policy": {
            "raw_recognition_confidence_used": False,
            "objectness_floor": OBJECTNESS_FLOOR,
            "geometry_confidence_floor": GEOMETRY_CONFIDENCE_FLOOR,
            "border_margin_pixels": BORDER_MARGIN_PX,
            "strong_support": {
                "support_score_floor": STRONG_SCORE_FLOOR,
                "word_coverage_floor": STRONG_WORD_COVERAGE_FLOOR,
                "vertical_overlap_over_smaller_floor": STRONG_VERTICAL_OVERLAP_FLOOR,
            },
            "moderate_support_for_ambiguity": {
                "support_score_floor": MODERATE_SCORE_FLOOR,
                "word_coverage_floor": MODERATE_WORD_COVERAGE_FLOOR,
                "vertical_overlap_over_smaller_floor": MODERATE_VERTICAL_OVERLAP_FLOOR,
            },
            "candidate_competition_score_delta_max": AMBIGUITY_SCORE_DELTA,
            "ocr_box_overlap_coverage_floor": OCR_BOX_AMBIGUITY_COVERAGE,
            "confirmation_requires": [
                "strong_eligible_independent_geometry",
                "detector_objectness_at_or_above_floor",
                "no_source_border_clipping",
                "no_candidate_or_ocr_box_overlap_ambiguity",
            ],
            "support_score_formula": {
                "iou": 0.30,
                "word_coverage": 0.25,
                "candidate_coverage": 0.15,
                "vertical_overlap_over_smaller": 0.15,
                "center_score": 0.10,
                "candidate_geometry_confidence": 0.05,
            },
        },
        "counts": counts,
        "abstention_reason_counts": dict(sorted(reason_counts.items())),
        "shared_best_candidates": shared_candidates,
        "words": prepared,
        "limits": [
            "A confirmed status validates only independent geometric support for a text-shaped region.",
            "Raw transcription, spelling, language, and semantics are not corrected or validated.",
            "Geometry candidates come from two line-suppressed preprocessing variants and can miss glyphs erased with plan linework.",
            "Border clipping is inferred from the OCR box distance to the crop boundary, not from unseen pixels outside the crop.",
            "Thresholds are deterministic engineering guards and are not yet calibrated on a labelled construction-plan dataset.",
        ],
    }

    result_bytes = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    overlay_bytes = render_overlay(crop, prepared, candidates_by_id, counts)
    manifest = {
        "schema_version": "planparser.atomic_v2.ocr_geometry_guard.manifest.v1",
        "status": "completed",
        "created_at_utc": created_at,
        "component": COMPONENT,
        "revision": REVISION,
        "immutability": "new_revision_written_exclusively_no_existing_file_modified",
        "script": {
            "path": script_path.name,
            "sha256": sha256_file(script_path),
        },
        "inputs": {
            "crop": {"path": str(crop_path), "sha256": crop_hash},
            "doctr_raw": {"path": str(doctr_path), "sha256": sha256_file(doctr_path)},
            "geometry_candidates": {"path": str(geometry_path), "sha256": sha256_file(geometry_path)},
        },
        "outputs": {
            "ocr_geometry_guard.json": {
                "bytes": len(result_bytes),
                "sha256": sha256_bytes(result_bytes),
            },
            "ocr_geometry_guard_overlay.png": {
                "bytes": len(overlay_bytes),
                "sha256": sha256_bytes(overlay_bytes),
            },
        },
        "counts": counts,
        "parameters": result["decision_policy"],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=False)
    outputs = {
        output_dir / "ocr_geometry_guard.json": result_bytes,
        output_dir / "ocr_geometry_guard_overlay.png": overlay_bytes,
        output_dir / "manifest.json": manifest_bytes,
    }
    for path, payload in outputs.items():
        with path.open("xb") as handle:
            handle.write(payload)

    print(json.dumps({"output_dir": str(output_dir), "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
