from __future__ import annotations

import hashlib
import io
import json
import math
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SCHEMA_VERSION = "planparser.ocr_ensemble.v1"
REVISION = "revision_001"

# The matcher deliberately uses geometry before text. Text is consulted only after
# spatial assignment, so a similar string cannot pull a distant box into agreement.
ENGINE_MIN_INTERSECTION_OVER_SMALLER = 0.65
ENGINE_MAX_CENTER_DISTANCE_BY_HEIGHT = 1.35
GEOMETRY_MIN_INTERSECTION_OVER_SMALLER = 0.50
GEOMETRY_MAX_CENTER_DISTANCE_BY_HEIGHT = 1.35
FUZZY_SIMILARITY_FLOOR = 0.72
ENGINE_CONFIDENCE_FLOOR = 0.80
BORDER_TOLERANCE_PX = 1.0

ATOMIC_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ATOMIC_ROOT
    / "ocr_ensemble"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / REVISION
)

INPUTS = {
    "ppocrv5_raw": ATOMIC_ROOT
    / "ocr_heavy"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_004"
    / "ppocrv5_raw_001_paddle.json",
    "doctr_raw": ATOMIC_ROOT
    / "ocr_doctr"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_002"
    / "ocr_raw.json",
    "geometric_text_candidates": ATOMIC_ROOT
    / "ocr_text_candidates"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
    / "text_candidates.json",
    "original_crop": ATOMIC_ROOT
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_001.png",
}

INPUT_MANIFEST = OUTPUT_DIR / "input_manifest.json"
OUTPUT_JSON = OUTPUT_DIR / "ocr_ensemble.json"
OUTPUT_OVERLAY = OUTPUT_DIR / "ocr_ensemble_overlay.png"
OUTPUT_MANIFEST = OUTPUT_DIR / "artifact_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)


def normalized_text(value: str) -> str:
    # This is intentionally minimal. Punctuation is preserved; there is no
    # dictionary lookup, spelling correction, transliteration or semantic repair.
    nfkc = unicodedata.normalize("NFKC", value)
    return " ".join(nfkc.casefold().split())


def xywh_to_xyxy(value: dict[str, Any]) -> list[float]:
    x = float(value["x"])
    y = float(value["y"])
    return [x, y, x + float(value["width"]), y + float(value["height"])]


def union_bbox(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise ValueError("Cannot union an empty box list")
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def bbox_metrics(a: list[float], b: list[float]) -> dict[str, float]:
    ax1, ay1, ax2, ay2 = (float(v) for v in a)
    bx1, by1, bx2, by2 = (float(v) for v in b)
    intersection_width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    smaller = min(area_a, area_b)
    center_distance = math.hypot(
        (ax1 + ax2 - bx1 - bx2) / 2.0,
        (ay1 + ay2 - by1 - by2) / 2.0,
    )
    height_scale = max(1.0, ay2 - ay1, by2 - by1)
    return {
        "intersection_area_px2": round(intersection, 6),
        "intersection_over_union": round(intersection / union, 6)
        if union > 0
        else 0.0,
        "intersection_over_smaller": round(intersection / smaller, 6)
        if smaller > 0
        else 0.0,
        "center_distance_px": round(center_distance, 6),
        "center_distance_by_max_height": round(center_distance / height_scale, 6),
    }


def is_strong_engine_relation(metrics: dict[str, float]) -> bool:
    return (
        metrics["intersection_over_smaller"]
        >= ENGINE_MIN_INTERSECTION_OVER_SMALLER
        and metrics["center_distance_by_max_height"]
        <= ENGINE_MAX_CENTER_DISTANCE_BY_HEIGHT
    )


def is_strong_geometry_relation(metrics: dict[str, float]) -> bool:
    return (
        metrics["intersection_over_smaller"]
        >= GEOMETRY_MIN_INTERSECTION_OVER_SMALLER
        and metrics["center_distance_by_max_height"]
        <= GEOMETRY_MAX_CENTER_DISTANCE_BY_HEIGHT
    )


def relation_rank(metrics: dict[str, float]) -> tuple[float, float, float]:
    return (
        metrics["intersection_over_smaller"],
        metrics["intersection_over_union"],
        -metrics["center_distance_by_max_height"],
    )


def touches_border(box: list[float], width: int, height: int) -> bool:
    return (
        box[0] <= BORDER_TOLERANCE_PX
        or box[1] <= BORDER_TOLERANCE_PX
        or box[2] >= width - BORDER_TOLERANCE_PX
        or box[3] >= height - BORDER_TOLERANCE_PX
    )


def relative(path: Path) -> str:
    return path.relative_to(ATOMIC_ROOT).as_posix()


def verify_preflight() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not OUTPUT_DIR.is_dir():
        raise FileNotFoundError(f"Missing pre-created output directory: {OUTPUT_DIR}")
    if not INPUT_MANIFEST.is_file():
        raise FileNotFoundError(f"Missing immutable input manifest: {INPUT_MANIFEST}")
    for output in (OUTPUT_JSON, OUTPUT_OVERLAY, OUTPUT_MANIFEST):
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    manifest = read_json(INPUT_MANIFEST)
    manifest_by_role = {item["role"]: item for item in manifest["inputs"]}
    verified: dict[str, dict[str, Any]] = {}
    for role, path in INPUTS.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing input {role}: {path}")
        actual = {
            "role": role,
            "path": relative(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        expected = manifest_by_role.get(role)
        if expected is None:
            raise ValueError(f"Input role absent from manifest: {role}")
        if actual["bytes"] != expected["bytes"] or actual["sha256"] != expected["sha256"]:
            raise ValueError(
                f"Input changed after preflight manifest: {role}; "
                f"expected {expected['sha256']}, got {actual['sha256']}"
            )
        verified[role] = actual
    return manifest, verified


def assign_doctr_to_pp(
    pp_items: list[dict[str, Any]], doctr_words: list[dict[str, Any]]
) -> tuple[dict[int, list[int]], list[dict[str, Any]]]:
    assignments: dict[int, list[int]] = {index: [] for index in range(len(pp_items))}
    relation_audit: list[dict[str, Any]] = []

    # Each docTR word goes to at most one PP box, using geometry only.
    for doctr_index, word in enumerate(doctr_words):
        doctr_box = [float(v) for v in word["bbox_pixels"]]
        viable: list[tuple[tuple[float, float, float], int, dict[str, float]]] = []
        for pp_index, item in enumerate(pp_items):
            pp_box = [float(v) for v in item["bbox_xyxy"]]
            metrics = bbox_metrics(pp_box, doctr_box)
            if is_strong_engine_relation(metrics):
                viable.append((relation_rank(metrics), pp_index, metrics))
        viable.sort(reverse=True)
        if viable:
            _, pp_index, metrics = viable[0]
            assignments[pp_index].append(doctr_index)
            relation_audit.append(
                {
                    "ppocrv5_ref": f"ppocrv5:item:{pp_items[pp_index]['index']:04d}",
                    "doctr_ref": f"doctr:{word['id']}",
                    "selected": True,
                    "metrics": metrics,
                    "alternative_viable_pp_count": len(viable) - 1,
                }
            )

    for pp_index in assignments:
        assignments[pp_index].sort(
            key=lambda idx: (
                float(doctr_words[idx]["bbox_pixels"][0]),
                float(doctr_words[idx]["bbox_pixels"][1]),
                doctr_words[idx]["id"],
            )
        )
    return assignments, relation_audit


def create_base_units(
    pp_items: list[dict[str, Any]],
    doctr_words: list[dict[str, Any]],
    assignments: dict[int, list[int]],
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    assigned_doctr: set[int] = set()
    for pp_index, pp_item in enumerate(pp_items):
        doctr_indices = assignments[pp_index]
        assigned_doctr.update(doctr_indices)
        pp_box = [float(v) for v in pp_item["bbox_xyxy"]]
        doctr_boxes = [
            [float(v) for v in doctr_words[index]["bbox_pixels"]]
            for index in doctr_indices
        ]
        units.append(
            {
                "pp_indices": [pp_index],
                "doctr_indices": doctr_indices,
                "base_bbox": union_bbox([pp_box, *doctr_boxes]),
            }
        )

    # docTR-only units are retained explicitly and must abstain.
    for doctr_index, word in enumerate(doctr_words):
        if doctr_index not in assigned_doctr:
            units.append(
                {
                    "pp_indices": [],
                    "doctr_indices": [doctr_index],
                    "base_bbox": [float(v) for v in word["bbox_pixels"]],
                }
            )

    units.sort(key=lambda unit: (unit["base_bbox"][1], unit["base_bbox"][0]))
    return units


def assign_geometry_candidates(
    units: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> tuple[dict[int, list[tuple[int, dict[str, float]]]], list[int]]:
    assignments: dict[int, list[tuple[int, dict[str, float]]]] = {
        index: [] for index in range(len(units))
    }
    unassigned: list[int] = []
    for candidate_index, candidate in enumerate(candidates):
        candidate_box = xywh_to_xyxy(candidate["bbox_original_px"])
        viable: list[tuple[tuple[float, float, float], int, dict[str, float]]] = []
        for unit_index, unit in enumerate(units):
            metrics = bbox_metrics(unit["base_bbox"], candidate_box)
            if is_strong_geometry_relation(metrics):
                viable.append((relation_rank(metrics), unit_index, metrics))
        viable.sort(reverse=True)
        if viable:
            _, unit_index, metrics = viable[0]
            assignments[unit_index].append((candidate_index, metrics))
        else:
            unassigned.append(candidate_index)
    return assignments, unassigned


def build_alignment_records(
    units: list[dict[str, Any]],
    geometry_assignments: dict[int, list[tuple[int, dict[str, float]]]],
    pp_items: list[dict[str, Any]],
    doctr_words: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    alignments: list[dict[str, Any]] = []
    for unit_index, unit in enumerate(units, start=1):
        pp_group = [pp_items[index] for index in unit["pp_indices"]]
        doctr_group = [doctr_words[index] for index in unit["doctr_indices"]]
        geometry_group = geometry_assignments[unit_index - 1]

        pp_texts = [str(item["text"]) for item in pp_group]
        doctr_texts = [str(word["text_raw"]) for word in doctr_group]
        pp_joined = " ".join(pp_texts)
        doctr_joined = " ".join(doctr_texts)
        pp_normalized = normalized_text(pp_joined) if pp_group else None
        doctr_normalized = normalized_text(doctr_joined) if doctr_group else None
        exact_normalized = (
            pp_normalized is not None
            and doctr_normalized is not None
            and pp_normalized == doctr_normalized
        )
        fuzzy_similarity = (
            round(SequenceMatcher(None, pp_normalized, doctr_normalized).ratio(), 6)
            if pp_normalized is not None and doctr_normalized is not None
            else None
        )
        segmentation_differs = len(pp_group) != len(doctr_group)

        engine_pair_metrics: list[dict[str, Any]] = []
        for item in pp_group:
            for word in doctr_group:
                metrics = bbox_metrics(
                    [float(v) for v in item["bbox_xyxy"]],
                    [float(v) for v in word["bbox_pixels"]],
                )
                engine_pair_metrics.append(
                    {
                        "ppocrv5_ref": f"ppocrv5:item:{item['index']:04d}",
                        "doctr_ref": f"doctr:{word['id']}",
                        "metrics": metrics,
                        "strong_spatial_relation": is_strong_engine_relation(metrics),
                    }
                )

        geometry_matches: list[dict[str, Any]] = []
        for candidate_index, metrics in geometry_group:
            candidate = candidates[candidate_index]
            geometry_matches.append(
                {
                    "geometry_ref": f"geometry:{candidate['id']}",
                    "bbox_original_px_xyxy": xywh_to_xyxy(candidate["bbox_original_px"]),
                    "confidence_geometry_raw": candidate["confidence_geometry"],
                    "abstained_raw": candidate["abstained"],
                    "border_clipped_raw": candidate["border_clipped"],
                    "metrics_to_alignment_bbox": metrics,
                    "strong_spatial_relation": is_strong_geometry_relation(metrics),
                }
            )

        pp_border = any(
            touches_border([float(v) for v in item["bbox_xyxy"]], width, height)
            for item in pp_group
        )
        doctr_border = any(
            touches_border([float(v) for v in word["bbox_pixels"]], width, height)
            for word in doctr_group
        )
        valid_geometry = [
            match
            for match in geometry_matches
            if match["strong_spatial_relation"]
            and not match["abstained_raw"]
            and not match["border_clipped_raw"]
        ]
        all_confident = (
            bool(pp_group)
            and bool(doctr_group)
            and all(float(item["confidence"]) >= ENGINE_CONFIDENCE_FLOOR for item in pp_group)
            and all(
                float(word["confidence_raw"]) >= ENGINE_CONFIDENCE_FLOOR
                for word in doctr_group
            )
        )
        one_to_one = len(pp_group) == 1 and len(doctr_group) == 1
        strong_engine_geometry = bool(engine_pair_metrics) and all(
            entry["strong_spatial_relation"] for entry in engine_pair_metrics
        )

        reasons: list[str] = []
        if not pp_group or not doctr_group:
            classification = "single_engine"
            render_class = "single"
            reasons.append("single_engine_only")
        elif (
            exact_normalized
            and one_to_one
            and strong_engine_geometry
            and len(valid_geometry) == 1
            and all_confident
            and not pp_border
            and not doctr_border
        ):
            classification = "consensus"
            render_class = "consensus"
            reasons.extend(
                [
                    "normalized_text_exact",
                    "one_to_one_segmentation",
                    "strong_engine_box_overlap",
                    "one_independent_non_abstained_geometry_match",
                    "engine_confidences_above_floor",
                    "not_border_clipped",
                ]
            )
        elif (
            fuzzy_similarity is not None
            and fuzzy_similarity < FUZZY_SIMILARITY_FLOOR
            and strong_engine_geometry
        ):
            classification = "conflict"
            render_class = "conflict"
            reasons.append("spatially_aligned_normalized_text_conflict")
        else:
            classification = "fuzzy_or_ambiguous_abstained"
            render_class = "fuzzy_abstained"
            if segmentation_differs:
                reasons.append("segmentation_differs_between_engines")
            if not exact_normalized:
                reasons.append("normalized_text_not_exact")
                if fuzzy_similarity is not None and fuzzy_similarity >= FUZZY_SIMILARITY_FLOOR:
                    reasons.append("text_similarity_is_fuzzy_only")
            if not one_to_one:
                reasons.append("not_one_to_one")
            if not strong_engine_geometry:
                reasons.append("engine_box_overlap_not_strong")
            if len(valid_geometry) == 0:
                reasons.append("no_non_abstained_independent_geometry_match")
            elif len(valid_geometry) > 1:
                reasons.append("multiple_independent_geometry_matches_ambiguous")
            if not all_confident:
                reasons.append("one_or_more_engine_confidences_below_floor")
            if pp_border or doctr_border:
                reasons.append("engine_box_touches_input_border")

        alignment_id = f"ALIGN-{unit_index:03d}"
        consensus_payload: dict[str, Any] | None = None
        if classification == "consensus":
            consensus_payload = {
                "text_normalized": pp_normalized,
                "raw_forms": [pp_joined, doctr_joined],
                "raw_forms_identical": pp_joined == doctr_joined,
                "confidence_aggregation_performed": False,
                "note": "Per-engine raw confidences are retained; no synthetic confidence is invented.",
            }

        alignments.append(
            {
                "id": alignment_id,
                "reading_order_geometric_only": unit_index,
                "source_refs": {
                    "ppocrv5": [
                        f"ppocrv5:item:{item['index']:04d}" for item in pp_group
                    ],
                    "doctr": [f"doctr:{word['id']}" for word in doctr_group],
                    "geometry": [
                        f"geometry:{candidates[index]['id']}"
                        for index, _ in geometry_group
                    ],
                },
                "raw_text_alternatives": {
                    "ppocrv5": {
                        "segments": [
                            {
                                "source_ref": f"ppocrv5:item:{item['index']:04d}",
                                "text_raw": item["text"],
                                "confidence_raw": item["confidence"],
                            }
                            for item in pp_group
                        ],
                        "joined_text_raw": pp_joined if pp_group else None,
                    },
                    "doctr": {
                        "segments": [
                            {
                                "source_ref": f"doctr:{word['id']}",
                                "text_raw": word["text_raw"],
                                "confidence_raw": word["confidence_raw"],
                                "objectness_score_raw": word.get(
                                    "objectness_score_raw"
                                ),
                            }
                            for word in doctr_group
                        ],
                        "joined_text_raw": doctr_joined if doctr_group else None,
                    },
                },
                "normalization_audit": {
                    "ppocrv5_normalized": pp_normalized,
                    "doctr_normalized": doctr_normalized,
                    "normalized_exact": exact_normalized,
                    "fuzzy_similarity_sequence_matcher": fuzzy_similarity,
                    "punctuation_preserved": True,
                    "dictionary_or_semantic_correction_performed": False,
                },
                "line_and_segmentation_mapping": {
                    "ppocrv5_line_metadata_available": False,
                    "ppocrv5_item_count": len(pp_group),
                    "doctr_line_refs": [
                        {
                            "page_index": word["page_index"],
                            "block_index": word["block_index"],
                            "line_index": word["line_index"],
                            "word_index": word["word_index"],
                        }
                        for word in doctr_group
                    ],
                    "doctr_word_count": len(doctr_group),
                    "segmentation_differs": segmentation_differs,
                    "geometry_word_segment_counts": [
                        {
                            "geometry_ref": f"geometry:{candidates[index]['id']}",
                            "word_segment_count_raw": len(
                                candidates[index].get("word_segments", [])
                            ),
                        }
                        for index, _ in geometry_group
                    ],
                },
                "spatial_audit": {
                    "alignment_bbox_xyxy": [round(v, 6) for v in unit["base_bbox"]],
                    "ppocrv5_bboxes_xyxy": [
                        item["bbox_xyxy"] for item in pp_group
                    ],
                    "doctr_bboxes_xyxy": [
                        word["bbox_pixels"] for word in doctr_group
                    ],
                    "engine_pair_metrics": engine_pair_metrics,
                    "geometry_matches": geometry_matches,
                    "ppocrv5_border_clipped_computed": pp_border,
                    "doctr_border_clipped_computed": doctr_border,
                },
                "decision": {
                    "classification": classification,
                    "render_class": render_class,
                    "abstained": classification != "consensus",
                    "reasons": reasons,
                    "consensus": consensus_payload,
                },
            }
        )
    return alignments


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        candidates = [
            Path("C:/Windows/Fonts") / name,
            Path("/usr/share/fonts/truetype/dejavu") / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_dashed_rectangle(
    draw: ImageDraw.ImageDraw,
    box: list[float],
    color: tuple[int, int, int],
    width: int = 1,
    dash: int = 6,
    gap: int = 4,
) -> None:
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    for start in range(x1, x2 + 1, dash + gap):
        draw.line((start, y1, min(start + dash, x2), y1), fill=color, width=width)
        draw.line((start, y2, min(start + dash, x2), y2), fill=color, width=width)
    for start in range(y1, y2 + 1, dash + gap):
        draw.line((x1, start, x1, min(start + dash, y2)), fill=color, width=width)
        draw.line((x2, start, x2, min(start + dash, y2)), fill=color, width=width)


def clipped_text(value: str | None, limit: int = 32) -> str:
    if value is None:
        return "∅"
    return value if len(value) <= limit else value[: limit - 1] + "…"


def render_overlay(
    crop: Image.Image,
    alignments: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    unassigned_geometry: list[int],
    counts: dict[str, int],
) -> bytes:
    source = crop.convert("RGB")
    panel_width = 530
    canvas_height = max(source.height, 744)
    canvas = Image.new("RGB", (source.width + panel_width, canvas_height), "white")
    canvas.paste(source, (0, 0))
    draw = ImageDraw.Draw(canvas)
    font_small = load_font(13)
    font_medium = load_font(16)
    font_bold = load_font(18, bold=True)
    font_title = load_font(24, bold=True)

    colors = {
        "consensus": (0, 166, 81),
        "fuzzy_abstained": (235, 165, 0),
        "conflict": (215, 38, 61),
        "single": (105, 105, 105),
        "geometry": (0, 126, 167),
    }

    # Geometry-only detections remain visible but faint and never become text.
    for candidate_index in unassigned_geometry:
        candidate_box = xywh_to_xyxy(candidates[candidate_index]["bbox_original_px"])
        draw_dashed_rectangle(draw, candidate_box, (165, 165, 165), width=1, dash=2, gap=3)

    for alignment in alignments:
        render_class = alignment["decision"]["render_class"]
        color = colors[render_class]
        base_box = alignment["spatial_audit"]["alignment_bbox_xyxy"]
        draw.rectangle(tuple(base_box), outline=color, width=3)

        for pp_box in alignment["spatial_audit"]["ppocrv5_bboxes_xyxy"]:
            draw.rectangle(tuple(pp_box), outline=color, width=1)
        for doctr_box in alignment["spatial_audit"]["doctr_bboxes_xyxy"]:
            draw_dashed_rectangle(draw, doctr_box, color, width=1, dash=5, gap=3)
        for match in alignment["spatial_audit"]["geometry_matches"]:
            draw_dashed_rectangle(
                draw,
                match["bbox_original_px_xyxy"],
                colors["geometry"],
                width=1,
                dash=2,
                gap=2,
            )

        pp_text = alignment["raw_text_alternatives"]["ppocrv5"]["joined_text_raw"]
        doctr_text = alignment["raw_text_alternatives"]["doctr"]["joined_text_raw"]
        if alignment["decision"]["classification"] == "consensus":
            text = f"{alignment['id']} OK {clipped_text(pp_text)}"
        elif pp_text is not None and doctr_text is not None:
            text = (
                f"{alignment['id']} ABST {clipped_text(pp_text, 18)}"
                f" <> {clipped_text(doctr_text, 18)}"
            )
        else:
            text = f"{alignment['id']} SINGLE {clipped_text(pp_text or doctr_text)}"
        text_bbox = draw.textbbox((0, 0), text, font=font_small)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        x = max(1, min(int(base_box[0]), source.width - text_width - 5))
        y = int(base_box[1]) - text_height - 5
        if y < 1:
            y = min(source.height - text_height - 3, int(base_box[3]) + 2)
        draw.rounded_rectangle(
            (x, y, x + text_width + 4, y + text_height + 4),
            radius=2,
            fill=(255, 255, 255),
            outline=color,
            width=1,
        )
        draw.text((x + 2, y + 1), text, fill=color, font=font_small)

    panel_x = source.width
    draw.rectangle((panel_x, 0, canvas.width - 1, canvas.height - 1), fill=(250, 250, 250))
    draw.line((panel_x, 0, panel_x, canvas.height), fill=(40, 40, 40), width=2)
    x = panel_x + 22
    y = 20
    draw.text((x, y), "OCR ensemble — audit", fill=(20, 20, 20), font=font_title)
    y += 38
    draw.text((x, y), "revision_001 · no dictionary · no correction", fill=(60, 60, 60), font=font_medium)
    y += 36
    legend = [
        ("consensus", "CONSENSUS: exact normalized + strong geometry"),
        ("fuzzy_abstained", "FUZZY / AMBIGUOUS: abstained"),
        ("conflict", "CONFLICT: abstained"),
        ("single", "SINGLE ENGINE / GEOMETRY-ONLY: abstained"),
    ]
    for key, label in legend:
        draw.rectangle((x, y + 2, x + 20, y + 18), fill=colors[key])
        draw.text((x + 30, y), label, fill=(30, 30, 30), font=font_small)
        y += 26

    y += 12
    draw.text((x, y), "Counts", fill=(25, 25, 25), font=font_bold)
    y += 28
    for label, key in [
        ("Consensus", "consensus"),
        ("Fuzzy / ambiguous abstained", "fuzzy_or_ambiguous_abstained"),
        ("Conflicts", "conflict"),
        ("Single-engine", "single_engine"),
        ("Geometry-only", "geometry_only"),
    ]:
        draw.text((x, y), f"{label}: {counts.get(key, 0)}", fill=(40, 40, 40), font=font_medium)
        y += 24

    y += 10
    draw.text((x, y), "Alignment decisions", fill=(25, 25, 25), font=font_bold)
    y += 27
    for alignment in alignments:
        render_class = alignment["decision"]["render_class"]
        pp_text = alignment["raw_text_alternatives"]["ppocrv5"]["joined_text_raw"]
        doctr_text = alignment["raw_text_alternatives"]["doctr"]["joined_text_raw"]
        if alignment["decision"]["classification"] == "consensus":
            line = f"{alignment['id']}  {clipped_text(pp_text, 36)}"
        else:
            line = (
                f"{alignment['id']}  {clipped_text(pp_text, 17)}"
                f" <> {clipped_text(doctr_text, 17)}"
            )
        draw.text((x, y), line, fill=colors[render_class], font=font_small)
        y += 20

    footer_y = canvas.height - 54
    draw.text(
        (x, footer_y),
        "Boxes: thick=alignment · solid=PP · dashed=docTR",
        fill=(75, 75, 75),
        font=font_small,
    )
    draw.text(
        (x, footer_y + 20),
        "cyan dotted=independent geometric candidate",
        fill=colors["geometry"],
        font=font_small,
    )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> None:
    input_manifest, verified_inputs = verify_preflight()
    pp_raw = read_json(INPUTS["ppocrv5_raw"])
    doctr_raw = read_json(INPUTS["doctr_raw"])
    geometry_raw = read_json(INPUTS["geometric_text_candidates"])
    with Image.open(INPUTS["original_crop"]) as opened:
        crop = opened.convert("RGB")

    width, height = crop.size
    manifest_canvas = input_manifest["source_canvas"]
    if width != manifest_canvas["width_px"] or height != manifest_canvas["height_px"]:
        raise ValueError("Original crop dimensions differ from immutable input manifest")
    if doctr_raw["source"]["sha256"] != verified_inputs["original_crop"]["sha256"]:
        raise ValueError("docTR source hash does not match the original crop")
    if geometry_raw["source"]["sha256"] != verified_inputs["original_crop"]["sha256"]:
        raise ValueError("Geometry-candidate source hash does not match the original crop")

    pp_items = list(pp_raw["items"])
    doctr_words = list(doctr_raw["words"])
    candidates = list(geometry_raw["candidates"])

    doctr_assignments, engine_assignment_audit = assign_doctr_to_pp(
        pp_items, doctr_words
    )
    units = create_base_units(pp_items, doctr_words, doctr_assignments)
    geometry_assignments, unassigned_geometry = assign_geometry_candidates(
        units, candidates
    )
    alignments = build_alignment_records(
        units,
        geometry_assignments,
        pp_items,
        doctr_words,
        candidates,
        width,
        height,
    )

    class_counts: dict[str, int] = {
        "consensus": 0,
        "fuzzy_or_ambiguous_abstained": 0,
        "conflict": 0,
        "single_engine": 0,
        "geometry_only": len(unassigned_geometry),
    }
    for alignment in alignments:
        class_counts[alignment["decision"]["classification"]] += 1

    created_at = utc_now()
    ensemble = {
        "schema_version": SCHEMA_VERSION,
        "revision": REVISION,
        "created_at_utc": created_at,
        "status": "complete_conservative_alignment",
        "scope": {
            "document": "scheda_catastale",
            "region": "region_001",
            "canvas_width_px": width,
            "canvas_height_px": height,
            "coordinate_space": "original_region_crop_pixels",
        },
        "input_integrity": {
            "manifest_path": relative(INPUT_MANIFEST),
            "manifest_sha256": sha256_file(INPUT_MANIFEST),
            "verified_inputs": verified_inputs,
            "all_hashes_verified_before_alignment": True,
        },
        "policy": {
            "spatial_assignment_uses_text": False,
            "text_normalization": "Unicode NFKC + casefold + whitespace collapse; punctuation preserved",
            "dictionary_lookup_performed": False,
            "spelling_correction_performed": False,
            "semantic_assignment_performed": False,
            "confidence_aggregation_performed": False,
            "consensus_requires": [
                "normalized text exact",
                "one-to-one engine segmentation",
                "strong PP/docTR spatial overlap",
                "exactly one strong non-abstained independent geometry candidate",
                "every engine confidence at or above configured floor",
                "no engine box touching the input border",
            ],
            "all_non_consensus_records_abstain": True,
            "thresholds": {
                "engine_min_intersection_over_smaller": ENGINE_MIN_INTERSECTION_OVER_SMALLER,
                "engine_max_center_distance_by_height": ENGINE_MAX_CENTER_DISTANCE_BY_HEIGHT,
                "geometry_min_intersection_over_smaller": GEOMETRY_MIN_INTERSECTION_OVER_SMALLER,
                "geometry_max_center_distance_by_height": GEOMETRY_MAX_CENTER_DISTANCE_BY_HEIGHT,
                "fuzzy_similarity_floor": FUZZY_SIMILARITY_FLOOR,
                "engine_confidence_floor": ENGINE_CONFIDENCE_FLOOR,
                "border_tolerance_px": BORDER_TOLERANCE_PX,
            },
        },
        "summary": {
            "ppocrv5_raw_item_count": len(pp_items),
            "doctr_raw_word_count": len(doctr_words),
            "geometric_candidate_raw_count": len(candidates),
            "alignment_count": len(alignments),
            "counts_by_classification": class_counts,
            "abstained_alignment_count": sum(
                1 for item in alignments if item["decision"]["abstained"]
            ),
            "consensus_alignment_count": class_counts["consensus"],
            "unassigned_geometry_candidate_count": len(unassigned_geometry),
        },
        "alignment_assignment_audit": {
            "method": "geometry-only best strong relation per docTR word",
            "selected_engine_relations": engine_assignment_audit,
        },
        "alignments": alignments,
        "unassigned_geometry": [
            {
                "geometry_ref": f"geometry:{candidates[index]['id']}",
                "reason": "no_strong_spatial_relation_to_any_ocr_alignment",
                "abstained": True,
            }
            for index in unassigned_geometry
        ],
        "source_record_catalog": {
            "preservation_note": (
                "Every OCR text and confidence value is copied verbatim as a raw "
                "source record. Alignment decisions only reference these records."
            ),
            "ppocrv5_items": [
                {
                    "source_ref": f"ppocrv5:item:{item['index']:04d}",
                    "raw": item,
                }
                for item in pp_items
            ],
            "doctr_words": [
                {"source_ref": f"doctr:{word['id']}", "raw": word}
                for word in doctr_words
            ],
            "geometric_candidates": [
                {"source_ref": f"geometry:{candidate['id']}", "raw": candidate}
                for candidate in candidates
            ],
        },
        "limits": [
            "Consensus is agreement, not ground truth.",
            "No OCR alternative was corrected or selected when engines disagreed.",
            "Geometric candidates contain no transcription and only provide independent spatial support.",
            "This revision processes region_001 only.",
        ],
    }

    json_bytes = (
        json.dumps(ensemble, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    overlay_bytes = render_overlay(
        crop,
        alignments,
        candidates,
        unassigned_geometry,
        class_counts,
    )
    output_hashes = {
        "ocr_ensemble.json": {
            "bytes": len(json_bytes),
            "sha256": sha256_bytes(json_bytes),
        },
        "ocr_ensemble_overlay.png": {
            "bytes": len(overlay_bytes),
            "sha256": sha256_bytes(overlay_bytes),
        },
    }
    generator_hash = sha256_file(Path(__file__))
    artifact_manifest = {
        "schema_version": "planparser.ocr_ensemble.artifact_manifest.v1",
        "revision": REVISION,
        "created_at_utc": created_at,
        "generator": {
            "path": relative(Path(__file__)),
            "sha256": generator_hash,
        },
        "input_manifest": {
            "path": relative(INPUT_MANIFEST),
            "sha256": sha256_file(INPUT_MANIFEST),
        },
        "outputs": output_hashes,
        "summary": ensemble["summary"],
        "write_policy": {
            "exclusive_create": True,
            "existing_outputs_overwritten": False,
        },
    }
    artifact_manifest_bytes = (
        json.dumps(artifact_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    # All payloads are complete in memory before the first write. Exclusive-create
    # mode prevents accidental replacement of any artifact.
    write_exclusive(OUTPUT_JSON, json_bytes)
    write_exclusive(OUTPUT_OVERLAY, overlay_bytes)
    write_exclusive(OUTPUT_MANIFEST, artifact_manifest_bytes)

    print(json.dumps(ensemble["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
