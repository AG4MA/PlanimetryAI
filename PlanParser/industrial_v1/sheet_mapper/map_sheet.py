from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np


MODULE_ROOT = Path(__file__).resolve().parent
PLANPARSER_ROOT = MODULE_ROOT.parents[1]
DEFAULT_SOURCE = (
    PLANPARSER_ROOT
    / "atomic_v2"
    / "ingest"
    / "artifacts"
    / "scheda_catastale"
    / "pages"
    / "page_0001.png"
)
DEFAULT_OUTPUT = (
    MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_001"
)
DEFAULT_DOCTR_RUNTIME = PLANPARSER_ROOT / "atomic_v2" / "ocr_doctr" / "runtime"

SCHEMA_VERSION = "planparser.industrial_v1.sheet_map.v1"
MAPPER_VERSION = "0.1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bbox_xywh(x0: int, y0: int, x1: int, y1: int) -> dict[str, int]:
    return {
        "x": int(x0),
        "y": int(y0),
        "width": int(max(0, x1 - x0)),
        "height": int(max(0, y1 - y0)),
    }


def bbox_xyxy(box: dict[str, int]) -> list[int]:
    return [
        box["x"],
        box["y"],
        box["x"] + box["width"],
        box["y"] + box["height"],
    ]


def bbox_center(box: dict[str, int]) -> tuple[float, float]:
    return (
        box["x"] + box["width"] / 2.0,
        box["y"] + box["height"] / 2.0,
    )


def bbox_union(boxes: Iterable[dict[str, int]]) -> dict[str, int] | None:
    materialized = list(boxes)
    if not materialized:
        return None
    x0 = min(item["x"] for item in materialized)
    y0 = min(item["y"] for item in materialized)
    x1 = max(item["x"] + item["width"] for item in materialized)
    y1 = max(item["y"] + item["height"] for item in materialized)
    return bbox_xywh(x0, y0, x1, y1)


def intersection_area(a: dict[str, int], b: dict[str, int]) -> int:
    ax0, ay0, ax1, ay1 = bbox_xyxy(a)
    bx0, by0, bx1, by1 = bbox_xyxy(b)
    return max(0, min(ax1, bx1) - max(ax0, bx0)) * max(
        0, min(ay1, by1) - max(ay0, by0)
    )


def iou(a: dict[str, int], b: dict[str, int]) -> float:
    shared = intersection_area(a, b)
    union = a["width"] * a["height"] + b["width"] * b["height"] - shared
    return shared / max(union, 1)


def point_in_bbox(point: tuple[float, float], box: dict[str, int]) -> bool:
    x, y = point
    return (
        box["x"] <= x < box["x"] + box["width"]
        and box["y"] <= y < box["y"] + box["height"]
    )


def grouped_runs(indices: np.ndarray) -> list[tuple[int, int, int]]:
    if len(indices) == 0:
        return []
    runs: list[tuple[int, int, int]] = []
    start = previous = int(indices[0])
    for raw in indices[1:]:
        current = int(raw)
        if current != previous + 1:
            runs.append((start, previous, round((start + previous) / 2)))
            start = current
        previous = current
    runs.append((start, previous, round((start + previous) / 2)))
    return runs


def line_support(
    mask: np.ndarray,
    orientation: str,
    coordinate: int,
    start: int,
    end: int,
    radius: int = 3,
) -> float:
    if end <= start:
        return 0.0
    if orientation == "horizontal":
        y0 = max(0, coordinate - radius)
        y1 = min(mask.shape[0], coordinate + radius + 1)
        strip = mask[y0:y1, start:end] > 0
        supported = strip.any(axis=0)
    else:
        x0 = max(0, coordinate - radius)
        x1 = min(mask.shape[1], coordinate + radius + 1)
        strip = mask[start:end, x0:x1] > 0
        supported = strip.any(axis=1)
    return float(supported.mean()) if supported.size else 0.0


def detect_primary_frame(gray: np.ndarray) -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray]:
    height, width = gray.shape
    ink = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(80, round(width * 0.18)), 1)
        ),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(100, round(height * 0.18)))
        ),
    )

    horizontal_projection = (horizontal > 0).sum(axis=1)
    vertical_projection = (vertical > 0).sum(axis=0)
    horizontal_runs = grouped_runs(
        np.where(horizontal_projection >= width * 0.40)[0]
    )
    vertical_runs = grouped_runs(
        np.where(vertical_projection >= height * 0.40)[0]
    )

    candidates: list[dict[str, Any]] = []
    for top_index in range(len(horizontal_runs)):
        for bottom_index in range(top_index + 1, len(horizontal_runs)):
            y0 = horizontal_runs[top_index][2]
            y1 = horizontal_runs[bottom_index][2]
            if y1 - y0 < height * 0.25:
                continue
            for left_index in range(len(vertical_runs)):
                for right_index in range(left_index + 1, len(vertical_runs)):
                    x0 = vertical_runs[left_index][2]
                    x1 = vertical_runs[right_index][2]
                    if x1 - x0 < width * 0.35:
                        continue
                    area_ratio = ((x1 - x0) * (y1 - y0)) / float(width * height)
                    if not 0.22 <= area_ratio <= 0.98:
                        continue
                    supports = {
                        "top": line_support(horizontal, "horizontal", y0, x0, x1),
                        "bottom": line_support(horizontal, "horizontal", y1, x0, x1),
                        "left": line_support(vertical, "vertical", x0, y0, y1),
                        "right": line_support(vertical, "vertical", x1, y0, y1),
                    }
                    minimum_support = min(supports.values())
                    mean_support = sum(supports.values()) / 4.0
                    if minimum_support < 0.48:
                        continue
                    score = (
                        0.72 * minimum_support
                        + 0.18 * mean_support
                        + 0.10 * min(1.0, area_ratio / 0.70)
                    )
                    candidates.append(
                        {
                            "bbox_page_px": bbox_xywh(x0, y0, x1 + 1, y1 + 1),
                            "area_ratio_page": round(area_ratio, 6),
                            "edge_support": {
                                key: round(value, 6) for key, value in supports.items()
                            },
                            "score": round(score, 6),
                        }
                    )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        fallback = bbox_xywh(0, 0, width, height)
        return (
            {
                "id": "SF-001",
                "bbox_page_px": fallback,
                "confidence": 0.0,
                "abstained": True,
                "reasons": ["no_closed_long_line_rectangle_met_minimum_support"],
            },
            [],
            ink,
        )

    best = candidates[0]
    confidence = min(0.995, 0.55 + 0.45 * best["score"])
    frame = {
        "id": "SF-001",
        "observation_type": "primary_planimetric_frame_candidate",
        "bbox_page_px": best["bbox_page_px"],
        "confidence": round(confidence, 6),
        "abstained": confidence < 0.75,
        "reasons": [
            "closed_rectangle_supported_by_independent_long_horizontal_and_vertical_line_evidence",
            "selected_by_perimeter_continuity_before_area",
            "does_not_assume_fixed_page_template",
        ],
        "measurements": {
            "edge_support": best["edge_support"],
            "area_ratio_page": best["area_ratio_page"],
        },
    }
    alternatives = []
    for index, candidate in enumerate(candidates[1:6], 1):
        alternatives.append(
            {
                "id": f"SF-ALT-{index:03d}",
                **candidate,
                "abstained": True,
                "reason": "lower_ranked_frame_hypothesis_retained_for_audit",
            }
        )
    return frame, alternatives, ink


def detect_header_titleblock(
    ink: np.ndarray, frame: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    height, width = ink.shape
    frame_box = frame["bbox_page_px"]
    frame_top = frame_box["y"]
    if frame_top <= 3:
        return [], None

    top_ink = np.zeros_like(ink)
    top_ink[: frame_top + 1, :] = ink[: frame_top + 1, :]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(top_ink, 8)
    retained_labels = [
        component_id
        for component_id in range(1, count)
        if int(stats[component_id, cv2.CC_STAT_AREA]) >= 3
    ]
    if not retained_labels:
        return [], None

    retained = np.zeros_like(top_ink)
    for component_id in retained_labels:
        retained[labels == component_id] = 255
    points = cv2.findNonZero(retained)
    if points is None:
        return [], None
    ux, uy, uw, uh = cv2.boundingRect(points)
    union = bbox_xywh(ux, uy, ux + uw, uy + uh)

    grouped = cv2.dilate(
        retained,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(19, round(width * 0.012)), max(15, round(height * 0.008))),
        ),
        iterations=1,
    )
    group_count, _, group_stats, _ = cv2.connectedComponentsWithStats(grouped, 8)
    macroboxes: list[dict[str, int]] = []
    for component_id in range(1, group_count):
        x, y, w, h, area = map(int, group_stats[component_id])
        if area < width * height * 0.00035:
            continue
        if w < width * 0.035 or h < height * 0.008:
            continue
        macroboxes.append(bbox_xywh(x, y, x + w, min(frame_top + 1, y + h)))
    macroboxes.sort(key=lambda box: (box["y"], box["x"]))

    components = []
    for index, box in enumerate(macroboxes, 1):
        components.append(
            {
                "id": f"HC-COMP-{index:03d}",
                "bbox_page_px": box,
                "classification": "header_or_titleblock_spatial_component",
                "confidence": round(min(0.96, 0.65 + 0.04 * len(macroboxes)), 6),
                "abstained": False,
                "semantic_fields_status": "not_asserted",
            }
        )

    ink_pixels = int((retained > 0).sum())
    candidate = {
        "id": "HC-001",
        "observation_type": "sheet_header_titleblock_candidate",
        "bbox_page_px": union,
        "confidence": round(min(0.98, 0.70 + 0.04 * len(macroboxes)), 6),
        "abstained": False,
        "reasons": [
            "ink_bearing_content_outside_and_above_primary_planimetric_frame",
            "raw_content_preserved_without_forcing_field_semantics",
        ],
        "measurements": {
            "ink_pixels": ink_pixels,
            "macro_component_count": len(macroboxes),
        },
        "component_ids": [item["id"] for item in components],
    }
    return components, candidate


def normalized_geometry_to_bbox(
    geometry: Any, width: int, height: int
) -> dict[str, int]:
    points = np.asarray(geometry, dtype=np.float64).reshape(-1, 2)
    x0 = max(0, min(width - 1, math.floor(float(points[:, 0].min()) * width)))
    y0 = max(0, min(height - 1, math.floor(float(points[:, 1].min()) * height)))
    x1 = max(x0 + 1, min(width, math.ceil(float(points[:, 0].max()) * width)))
    y1 = max(y0 + 1, min(height, math.ceil(float(points[:, 1].max()) * height)))
    return bbox_xywh(x0, y0, x1, y1)


def run_full_page_doctr(
    source: Path, runtime_root: Path, width: int, height: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model_cache = runtime_root / "models" / "doctr"
    expected_weights = [
        model_cache / "models" / "db_resnet50-79bd7d70.pt",
        model_cache / "models" / "parseq-56125471.pt",
    ]
    missing = [str(path) for path in expected_weights if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"cached docTR weights missing: {missing}")

    os.environ["DOCTR_CACHE_DIR"] = str(model_cache)
    os.environ["TORCH_HOME"] = str(runtime_root / "models")
    os.environ["XDG_CACHE_HOME"] = str(runtime_root / "xdg_cache")
    os.environ["HF_HOME"] = str(runtime_root / "models" / "huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import doctr
    import torch
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor

    torch.set_grad_enabled(False)
    load_started = time.perf_counter()
    predictor = ocr_predictor(
        det_arch="db_resnet50",
        reco_arch="parseq",
        pretrained=True,
        assume_straight_pages=True,
        preserve_aspect_ratio=True,
        symmetric_pad=True,
        export_as_straight_boxes=True,
        detect_orientation=False,
        straighten_pages=False,
        detect_language=False,
    ).to(torch.device("cpu"))
    model_load_ms = (time.perf_counter() - load_started) * 1000.0

    document = DocumentFile.from_images(str(source))
    inference_started = time.perf_counter()
    with torch.inference_mode():
        export = predictor(document).export()
    inference_ms = (time.perf_counter() - inference_started) * 1000.0

    words: list[dict[str, Any]] = []
    for page_index, page in enumerate(export.get("pages", [])):
        for block_index, block in enumerate(page.get("blocks", [])):
            for line_index, line in enumerate(block.get("lines", [])):
                for word_index, word in enumerate(line.get("words", [])):
                    confidence = float(word.get("confidence", 0.0))
                    box = normalized_geometry_to_bbox(word["geometry"], width, height)
                    words.append(
                        {
                            "id": f"OCR-{len(words) + 1:04d}",
                            "page_index": page_index,
                            "block_index": block_index,
                            "line_index": line_index,
                            "word_index": word_index,
                            "text_raw": str(word.get("value", "")),
                            "confidence_raw": round(confidence, 8),
                            "bbox_page_px": box,
                            "abstained": confidence < 0.50,
                            "abstention_reasons": (
                                ["raw_ocr_confidence_below_0.50"]
                                if confidence < 0.50
                                else []
                            ),
                        }
                    )

    runtime = {
        "engine": "docTR",
        "engine_version": doctr.__version__,
        "backend": "PyTorch CPU",
        "detector": "db_resnet50",
        "recognizer": "parseq",
        "network_used": False,
        "model_source": "existing_local_read_only_cache",
        "model_load_ms": round(model_load_ms, 3),
        "inference_ms": round(inference_ms, 3),
        "word_count": len(words),
        "limits": [
            "raw_confidence_is_not_calibrated_for_cadastral_floorplans",
            "recognition_is_evidence_not_ground_truth",
        ],
    }
    return words, runtime


FLOOR_DESIGNATOR = re.compile(
    r"\b(?:terra|rialzat[oa]|seminterrat[oa]|interrat[oa]|sottotetto|mansarda|"
    r"primo|secondo|terzo|quarto|quinto|sesto|settimo|ottavo|nono|decimo|"
    r"\d{1,2}(?:\s*[°º])?)\b",
    re.IGNORECASE,
)


def detect_floor_titles(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for word in words:
        key = (word["page_index"], word["block_index"], word["line_index"])
        grouped.setdefault(key, []).append(word)

    candidates: list[dict[str, Any]] = []
    for _, line_words in sorted(grouped.items()):
        line_words.sort(key=lambda item: (item["bbox_page_px"]["x"], item["word_index"]))
        text = " ".join(item["text_raw"] for item in line_words).strip()
        if not re.search(r"\bpiano\b", text, re.IGNORECASE):
            continue
        designation = FLOOR_DESIGNATOR.search(text)
        mean_confidence = sum(item["confidence_raw"] for item in line_words) / max(
            len(line_words), 1
        )
        classification_support = 1.0 if designation else 0.55
        confidence = min(0.995, mean_confidence * classification_support)
        abstained = designation is None or confidence < 0.70
        candidates.append(
            {
                "id": f"FT-{len(candidates) + 1:03d}",
                "observation_type": "floor_title_candidate",
                "text_raw": text,
                "designation_raw": designation.group(0) if designation else None,
                "bbox_page_px": bbox_union(
                    item["bbox_page_px"] for item in line_words
                ),
                "ocr_word_ids": [item["id"] for item in line_words],
                "confidence": round(confidence, 6),
                "abstained": abstained,
                "reasons": [
                    "ocr_line_contains_exact_floor_keyword_token",
                    (
                        "floor_designator_token_detected"
                        if designation
                        else "floor_designator_not_detected"
                    ),
                ],
                "semantic_scope": "candidate_title_only",
            }
        )
    candidates.sort(
        key=lambda item: (
            item["bbox_page_px"]["y"],
            item["bbox_page_px"]["x"],
        )
    )
    for index, candidate in enumerate(candidates, 1):
        candidate["id"] = f"FT-{index:03d}"
    return candidates


def detect_structural_candidates(
    ink: np.ndarray, frame: dict[str, Any]
) -> list[dict[str, Any]]:
    page_height, page_width = ink.shape
    frame_box = frame["bbox_page_px"]
    fx0, fy0, fx1, fy1 = bbox_xyxy(frame_box)
    scoped = np.zeros_like(ink)
    scoped[fy0:fy1, fx0:fx1] = ink[fy0:fy1, fx0:fx1]
    border_clearance = max(5, round(min(frame_box["width"], frame_box["height"]) * 0.003))
    cv2.rectangle(scoped, (fx0, fy0), (fx1 - 1, fy1 - 1), 0, border_clearance * 2)

    horizontal = cv2.morphologyEx(
        scoped,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(25, round(page_width * 0.014)), 1)
        ),
    )
    vertical = cv2.morphologyEx(
        scoped,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(25, round(page_height * 0.010)))
        ),
    )
    structural = cv2.bitwise_or(horizontal, vertical)
    joined = cv2.dilate(
        structural,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(15, round(page_width * 0.010)), max(9, round(page_height * 0.004))),
        ),
        iterations=1,
    )
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    raw: list[dict[str, Any]] = []
    for component_id in range(1, component_count):
        x, y, width, height, joined_area = map(int, stats[component_id])
        box = bbox_xywh(x, y, x + width, y + height)
        if intersection_area(box, frame_box) / max(width * height, 1) < 0.80:
            continue
        width_ratio = width / max(frame_box["width"], 1)
        height_ratio = height / max(frame_box["height"], 1)
        if width_ratio < 0.08 or height_ratio < 0.045:
            continue
        if width_ratio > 0.92 and height_ratio > 0.85:
            continue
        component_mask = labels[y : y + height, x : x + width] == component_id
        source_ink = scoped[y : y + height, x : x + width] > 0
        ink_pixels = int((component_mask & source_ink).sum())
        ink_ratio = ink_pixels / max(width * height, 1)
        if ink_ratio < 0.0025:
            continue
        dimension_support = min(1.0, width_ratio / 0.25) * min(
            1.0, height_ratio / 0.16
        )
        density_support = min(1.0, ink_ratio / 0.035)
        confidence = min(0.96, 0.48 + 0.25 * dimension_support + 0.23 * density_support)
        raw.append(
            {
                "bbox_page_px": box,
                "confidence": round(confidence, 6),
                "abstained": True,
                "observation_type": "connected_structural_linework_candidate",
                "semantic_hypothesis": None,
                "measurements": {
                    "joined_component_area_px": joined_area,
                    "source_ink_pixels": ink_pixels,
                    "source_ink_ratio": round(ink_ratio, 6),
                    "width_ratio_frame": round(width_ratio, 6),
                    "height_ratio_frame": round(height_ratio, 6),
                },
                "reasons": [
                    "connected_horizontal_and_vertical_linework",
                    "semantic_identity_not_proven",
                ],
            }
        )

    raw.sort(
        key=lambda item: (
            -item["confidence"],
            -(item["bbox_page_px"]["width"] * item["bbox_page_px"]["height"]),
        )
    )
    retained: list[dict[str, Any]] = []
    for candidate in raw:
        if any(
            iou(candidate["bbox_page_px"], previous["bbox_page_px"]) > 0.82
            for previous in retained
        ):
            continue
        retained.append(candidate)
    retained.sort(
        key=lambda item: (
            item["bbox_page_px"]["y"],
            item["bbox_page_px"]["x"],
        )
    )
    for index, candidate in enumerate(retained, 1):
        candidate["id"] = f"SC-{index:03d}"
    return retained


def normalized_axis_spread(
    titles: list[dict[str, Any]], frame_box: dict[str, int]
) -> tuple[str, float, float]:
    if len(titles) <= 1:
        return "single_seed", 0.0, 0.0
    centers = [bbox_center(item["bbox_page_px"]) for item in titles]
    x_spread = (max(x for x, _ in centers) - min(x for x, _ in centers)) / max(
        frame_box["width"], 1
    )
    y_spread = (max(y for _, y in centers) - min(y for _, y in centers)) / max(
        frame_box["height"], 1
    )
    if y_spread >= x_spread * 1.35:
        return "vertical", x_spread, y_spread
    if x_spread >= y_spread * 1.35:
        return "horizontal", x_spread, y_spread
    return "two_dimensional_ambiguous", x_spread, y_spread


def associate_structural_candidates(
    titles: list[dict[str, Any]],
    structural: list[dict[str, Any]],
    frame_box: dict[str, int],
    axis: str,
) -> dict[str, list[tuple[str, float]]]:
    associations: dict[str, list[tuple[str, float]]] = {
        title["id"]: [] for title in titles
    }
    if not titles:
        return associations
    page_scale = max(frame_box["width"], frame_box["height"], 1)
    for component in structural:
        cb = component["bbox_page_px"]
        ccx, ccy = bbox_center(cb)
        best_title: dict[str, Any] | None = None
        best_score = -1.0
        for title in titles:
            tb = title["bbox_page_px"]
            tcx, tcy = bbox_center(tb)
            if axis == "vertical":
                forward_gap = cb["y"] - tcy
                ordering_penalty = 0.20 if forward_gap < -frame_box["height"] * 0.02 else 1.0
                primary_distance = abs(forward_gap)
                secondary_distance = abs(ccx - tcx)
            elif axis == "horizontal":
                forward_gap = cb["x"] - tcx
                ordering_penalty = 0.20 if forward_gap < -frame_box["width"] * 0.02 else 1.0
                primary_distance = abs(forward_gap)
                secondary_distance = abs(ccy - tcy)
            else:
                ordering_penalty = 1.0
                primary_distance = math.hypot(ccx - tcx, ccy - tcy)
                secondary_distance = 0.0
            proximity = math.exp(
                -(primary_distance + 0.35 * secondary_distance) / (0.34 * page_scale)
            )
            score = ordering_penalty * proximity
            if score > best_score:
                best_score = score
                best_title = title
        if best_title is not None:
            associations[best_title["id"]].append(
                (component["id"], round(best_score, 6))
            )
    return associations


def build_floor_regions(
    titles: list[dict[str, Any]],
    structural: list[dict[str, Any]],
    frame: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame_box = frame["bbox_page_px"]
    axis, x_spread, y_spread = normalized_axis_spread(titles, frame_box)
    associations = associate_structural_candidates(
        titles, structural, frame_box, axis
    )
    structural_by_id = {item["id"]: item for item in structural}
    layout = {
        "axis": axis,
        "normalized_title_spread_x": round(x_spread, 6),
        "normalized_title_spread_y": round(y_spread, 6),
        "abstained": axis == "two_dimensional_ambiguous",
        "reason": (
            "dominant_title_arrangement_axis"
            if axis in {"vertical", "horizontal"}
            else "single_title_seed_or_ambiguous_two_dimensional_arrangement"
        ),
    }
    if not titles:
        return [], {**layout, "abstained": True, "reason": "no_floor_title_candidates"}

    if axis == "vertical":
        ordered = sorted(titles, key=lambda item: bbox_center(item["bbox_page_px"])[1])
    elif axis == "horizontal":
        ordered = sorted(titles, key=lambda item: bbox_center(item["bbox_page_px"])[0])
    else:
        ordered = sorted(
            titles,
            key=lambda item: (
                item["bbox_page_px"]["y"],
                item["bbox_page_px"]["x"],
            ),
        )

    boundaries: list[int] = []
    overlap_flags: list[bool] = []
    if axis in {"vertical", "horizontal"}:
        for current, following in zip(ordered, ordered[1:]):
            current_components = [
                structural_by_id[component_id]["bbox_page_px"]
                for component_id, _ in associations[current["id"]]
            ]
            if axis == "vertical":
                current_extent = max(
                    [current["bbox_page_px"]["y"] + current["bbox_page_px"]["height"]]
                    + [box["y"] + box["height"] for box in current_components]
                )
                next_start = following["bbox_page_px"]["y"]
                fallback = round(
                    (
                        bbox_center(current["bbox_page_px"])[1]
                        + bbox_center(following["bbox_page_px"])[1]
                    )
                    / 2
                )
            else:
                current_extent = max(
                    [current["bbox_page_px"]["x"] + current["bbox_page_px"]["width"]]
                    + [box["x"] + box["width"] for box in current_components]
                )
                next_start = following["bbox_page_px"]["x"]
                fallback = round(
                    (
                        bbox_center(current["bbox_page_px"])[0]
                        + bbox_center(following["bbox_page_px"])[0]
                    )
                    / 2
                )
            if current_extent < next_start:
                boundaries.append(round((current_extent + next_start) / 2))
                overlap_flags.append(False)
            else:
                boundaries.append(fallback)
                overlap_flags.append(True)

    fx0, fy0, fx1, fy1 = bbox_xyxy(frame_box)
    regions: list[dict[str, Any]] = []
    for index, title in enumerate(ordered):
        associated = associations[title["id"]]
        associated_ids = [component_id for component_id, _ in associated]
        association_scores = [score for _, score in associated]
        if axis == "vertical":
            y0 = fy0 if index == 0 else boundaries[index - 1]
            y1 = fy1 if index == len(ordered) - 1 else boundaries[index]
            box = bbox_xywh(fx0, y0, fx1, y1)
            overlap_ambiguous = (
                (index > 0 and overlap_flags[index - 1])
                or (index < len(overlap_flags) and overlap_flags[index])
            )
        elif axis == "horizontal":
            x0 = fx0 if index == 0 else boundaries[index - 1]
            x1 = fx1 if index == len(ordered) - 1 else boundaries[index]
            box = bbox_xywh(x0, fy0, x1, fy1)
            overlap_ambiguous = (
                (index > 0 and overlap_flags[index - 1])
                or (index < len(overlap_flags) and overlap_flags[index])
            )
        else:
            component_boxes = [
                structural_by_id[component_id]["bbox_page_px"]
                for component_id in associated_ids
            ]
            raw_union = bbox_union([title["bbox_page_px"], *component_boxes])
            assert raw_union is not None
            pad = max(10, round(min(frame_box["width"], frame_box["height"]) * 0.015))
            rx0, ry0, rx1, ry1 = bbox_xyxy(raw_union)
            box = bbox_xywh(
                max(fx0, rx0 - pad),
                max(fy0, ry0 - pad),
                min(fx1, rx1 + pad),
                min(fy1, ry1 + pad),
            )
            overlap_ambiguous = True

        association_quality = max(association_scores, default=0.0)
        confidence = min(
            0.98,
            0.52 + 0.28 * title["confidence"] + 0.18 * association_quality,
        )
        abstained = (
            title["abstained"]
            or not associated_ids
            or axis == "two_dimensional_ambiguous"
            or overlap_ambiguous
        )
        regions.append(
            {
                "id": f"FR-{index + 1:03d}",
                "observation_type": "floor_region_candidate",
                "bbox_page_px": box,
                "title_candidate_id": title["id"],
                "structural_candidate_ids": associated_ids,
                "association_scores": {
                    component_id: score for component_id, score in associated
                },
                "confidence": round(confidence, 6),
                "abstained": abstained,
                "reasons": [
                    "region_seeded_by_detected_floor_title",
                    f"layout_axis={axis}",
                    (
                        "one_or_more_structural_components_associated"
                        if associated_ids
                        else "no_structural_component_associated"
                    ),
                    (
                        "adjacent_regions_separated_without_observed_content_overlap"
                        if not overlap_ambiguous
                        else "region_boundary_or_layout_requires_human_validation"
                    ),
                ],
                "internal_content_semantics": "unclassified_preserved",
            }
        )
    return regions, layout


def detect_external_unclassified_ink(
    ink: np.ndarray,
    frame_box: dict[str, int],
    header_box: dict[str, int] | None,
) -> tuple[int, list[dict[str, Any]]]:
    known_spatial = np.zeros_like(ink)
    fx0, fy0, fx1, fy1 = bbox_xyxy(frame_box)
    known_spatial[fy0:fy1, fx0:fx1] = 255
    if header_box is not None:
        hx0, hy0, hx1, hy1 = bbox_xyxy(header_box)
        known_spatial[hy0:hy1, hx0:hx1] = 255
    unexplained = cv2.bitwise_and(ink, cv2.bitwise_not(known_spatial))
    count, _, stats, _ = cv2.connectedComponentsWithStats(unexplained, 8)
    components: list[dict[str, Any]] = []
    total = 0
    for component_id in range(1, count):
        x, y, width, height, area = map(int, stats[component_id])
        if area < 3:
            continue
        total += area
        components.append(
            {
                "id": f"UC-EXT-{len(components) + 1:03d}",
                "bbox_page_px": bbox_xywh(x, y, x + width, y + height),
                "ink_pixels": area,
                "classification": "unclassified_external_ink_preserved",
                "abstained": True,
            }
        )
    return total, components


def draw_label(
    image: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
    scale: float = 0.72,
    thickness: int = 2,
) -> None:
    x, y = origin
    (text_width, text_height), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
    )
    x = max(0, min(image.shape[1] - text_width - 8, x))
    y = max(text_height + baseline + 5, min(image.shape[0] - 3, y))
    cv2.rectangle(
        image,
        (x, y - text_height - baseline - 5),
        (x + text_width + 8, y + 3),
        (255, 255, 255),
        -1,
    )
    cv2.rectangle(
        image,
        (x, y - text_height - baseline - 5),
        (x + text_width + 8, y + 3),
        color,
        2,
    )
    cv2.putText(
        image,
        text,
        (x + 4, y - baseline),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def draw_box(
    image: np.ndarray,
    box: dict[str, int],
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    x0, y0, x1, y1 = bbox_xyxy(box)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, thickness)


def render_overlay(
    source_image: np.ndarray,
    frame: dict[str, Any],
    header: dict[str, Any] | None,
    titles: list[dict[str, Any]],
    structural: list[dict[str, Any]],
    floor_regions: list[dict[str, Any]],
    layout: dict[str, Any],
    ocr_runtime: dict[str, Any],
    external_unclassified_count: int,
) -> np.ndarray:
    overlay = source_image.copy()
    fill = source_image.copy()
    colors = {
        "frame": (30, 160, 30),
        "header": (185, 35, 185),
        "title": (0, 125, 255),
        "floor": (220, 145, 20),
        "structural": (0, 190, 220),
        "abstention": (40, 40, 210),
    }

    for region in floor_regions:
        box = region["bbox_page_px"]
        x0, y0, x1, y1 = bbox_xyxy(box)
        color = colors["abstention"] if region["abstained"] else colors["floor"]
        cv2.rectangle(fill, (x0, y0), (x1 - 1, y1 - 1), color, -1)
    overlay = cv2.addWeighted(fill, 0.08, overlay, 0.92, 0)

    draw_box(overlay, frame["bbox_page_px"], colors["frame"], 8)
    draw_label(
        overlay,
        f"{frame['id']} frame  conf={frame['confidence']:.3f}",
        (frame["bbox_page_px"]["x"] + 12, frame["bbox_page_px"]["y"] + 40),
        colors["frame"],
        0.82,
        2,
    )
    if header is not None:
        draw_box(overlay, header["bbox_page_px"], colors["header"], 6)
        draw_label(
            overlay,
            f"{header['id']} header/cartiglio  conf={header['confidence']:.3f}",
            (header["bbox_page_px"]["x"] + 12, header["bbox_page_px"]["y"] + 38),
            colors["header"],
            0.78,
            2,
        )

    for component in structural:
        draw_box(overlay, component["bbox_page_px"], colors["structural"], 3)
        box = component["bbox_page_px"]
        draw_label(
            overlay,
            f"{component['id']} linework ?  conf={component['confidence']:.3f}",
            (box["x"] + 6, box["y"] + 30),
            colors["structural"],
            0.58,
            1,
        )

    for region in floor_regions:
        color = colors["abstention"] if region["abstained"] else colors["floor"]
        draw_box(overlay, region["bbox_page_px"], color, 6)
        box = region["bbox_page_px"]
        status = "ABSTAIN" if region["abstained"] else "candidate"
        draw_label(
            overlay,
            f"{region['id']} floor region {status} conf={region['confidence']:.3f}",
            (box["x"] + 280, box["y"] + 42),
            color,
            0.72,
            2,
        )

    for title in titles:
        color = colors["abstention"] if title["abstained"] else colors["title"]
        draw_box(overlay, title["bbox_page_px"], color, 5)
        box = title["bbox_page_px"]
        draw_label(
            overlay,
            f"{title['id']} title conf={title['confidence']:.3f}: {title['text_raw']}",
            (box["x"], max(30, box["y"] - 8)),
            color,
            0.66,
            2,
        )

    panel_width = 860
    canvas = np.full(
        (overlay.shape[0], overlay.shape[1] + panel_width, 3), 255, dtype=np.uint8
    )
    canvas[:, : overlay.shape[1]] = overlay
    panel_x = overlay.shape[1] + 28
    cv2.putText(
        canvas,
        "PLANPARSER / SHEET MAPPER / REVISION 001",
        (panel_x, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Coordinate: source page pixels, origin top-left",
        (panel_x, 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.64,
        (60, 60, 60),
        1,
        cv2.LINE_AA,
    )

    legend = [
        (colors["frame"], "SF  primary planimetric frame candidate"),
        (colors["header"], "HC  header/cartiglio spatial candidate"),
        (colors["title"], "FT  floor-title candidate from OCR"),
        (colors["floor"], "FR  floor-region candidate"),
        (colors["structural"], "SC  structural linework; semantics unknown"),
        (colors["abstention"], "RED  abstention / human validation needed"),
    ]
    cursor_y = 180
    for color, label in legend:
        cv2.rectangle(canvas, (panel_x, cursor_y - 18), (panel_x + 34, cursor_y + 12), color, -1)
        cv2.putText(
            canvas,
            label,
            (panel_x + 52, cursor_y + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.59,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
        cursor_y += 52

    cursor_y += 35
    facts = [
        f"Layout axis: {layout['axis']}",
        f"OCR words retained: {ocr_runtime['word_count']}",
        f"Floor titles: {len(titles)}",
        f"Floor regions: {len(floor_regions)}",
        f"Structural candidates: {len(structural)}",
        f"External unclassified ink px: {external_unclassified_count}",
    ]
    for fact in facts:
        cv2.putText(
            canvas,
            fact,
            (panel_x, cursor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.64,
            (35, 35, 35),
            1,
            cv2.LINE_AA,
        )
        cursor_y += 43

    cursor_y += 30
    cv2.putText(
        canvas,
        "NON ASSERTED:",
        (panel_x, cursor_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        colors["abstention"],
        2,
        cv2.LINE_AA,
    )
    cursor_y += 44
    warnings = [
        "No wall / room / ownership semantics in this stage.",
        "SC boxes are observations, not claimed buildings.",
        "All raster content remains in the source reference.",
        "Human validation is required where marked ABSTAIN.",
    ]
    for warning in warnings:
        cv2.putText(
            canvas,
            warning,
            (panel_x, cursor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (55, 55, 55),
            1,
            cv2.LINE_AA,
        )
        cursor_y += 38

    cursor_y += 35
    for region in floor_regions:
        title = next(
            item for item in titles if item["id"] == region["title_candidate_id"]
        )
        status = "ABSTAIN" if region["abstained"] else "CANDIDATE"
        cv2.putText(
            canvas,
            f"{region['id']} <- {title['id']}  {status}",
            (panel_x, cursor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            colors["abstention"] if region["abstained"] else colors["floor"],
            2,
            cv2.LINE_AA,
        )
        cursor_y += 38
        cv2.putText(
            canvas,
            title["text_raw"][:70],
            (panel_x + 24, cursor_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (45, 45, 45),
            1,
            cv2.LINE_AA,
        )
        cursor_y += 54
    return canvas


def build_payload(
    source: Path,
    image: np.ndarray,
    frame: dict[str, Any],
    frame_alternatives: list[dict[str, Any]],
    header_components: list[dict[str, Any]],
    header: dict[str, Any] | None,
    words: list[dict[str, Any]],
    ocr_runtime: dict[str, Any],
    titles: list[dict[str, Any]],
    structural: list[dict[str, Any]],
    floor_regions: list[dict[str, Any]],
    layout: dict[str, Any],
    external_unclassified_pixels: int,
    external_unclassified: list[dict[str, Any]],
) -> dict[str, Any]:
    used_title_word_ids = {
        word_id for title in titles for word_id in title["ocr_word_ids"]
    }
    unresolved_words_by_scope: dict[str, list[str]] = {
        "header_or_titleblock": [],
        "floor_regions": [],
        "outside_mapped_spatial_regions": [],
    }
    for word in words:
        if word["id"] in used_title_word_ids:
            continue
        center = bbox_center(word["bbox_page_px"])
        if header is not None and point_in_bbox(center, header["bbox_page_px"]):
            unresolved_words_by_scope["header_or_titleblock"].append(word["id"])
        elif any(point_in_bbox(center, region["bbox_page_px"]) for region in floor_regions):
            unresolved_words_by_scope["floor_regions"].append(word["id"])
        else:
            unresolved_words_by_scope["outside_mapped_spatial_regions"].append(
                word["id"]
            )

    abstentions = [
        {
            "id": "ABS-001",
            "scope": "structural_linework_semantics",
            "status": "abstained",
            "reason": "geometry_alone_does_not_prove_building_wall_room_or_property_membership",
            "affected_ids": [item["id"] for item in structural],
        },
        {
            "id": "ABS-002",
            "scope": "floor_region_internal_semantics",
            "status": "abstained",
            "reason": "sheet_mapper_assigns_spatial_regions_only",
            "affected_ids": [item["id"] for item in floor_regions],
        },
        {
            "id": "ABS-003",
            "scope": "orientation_and_compass",
            "status": "not_attempted",
            "reason": "outside_this_first_sheet_mapping_component",
            "affected_ids": [],
        },
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mapper_version": MAPPER_VERSION,
        "status": "completed_with_explicit_abstentions",
        "created_at_utc": utc_now(),
        "source": {
            "path": source.relative_to(PLANPARSER_ROOT).as_posix(),
            "sha256": sha256_file(source),
            "width_px": int(image.shape[1]),
            "height_px": int(image.shape[0]),
            "coordinate_system": {
                "origin": "top_left",
                "x_positive": "right",
                "y_positive": "down",
                "bbox_encoding": "x_y_width_height_half_open",
                "unit": "source_page_pixel",
            },
            "preservation": {
                "authoritative_raster_unchanged": True,
                "raw_source_reference_retained": True,
                "pixel_data_copied_or_rewritten": False,
            },
        },
        "method": {
            "name": "evidence_first_sheet_mapper",
            "automatic": True,
            "fixed_floor_count_assumption": False,
            "stages": [
                "long_line_closed_frame_detection",
                "outside_frame_header_titleblock_mapping",
                "offline_full_page_ocr_observation",
                "floor_title_candidate_detection",
                "connected_structural_linework_observation",
                "title_to_linework_association",
                "dominant_axis_floor_region_partition_or_abstention",
                "unclassified_content_preservation_audit",
            ],
            "legacy_evidence": {
                "consulted_read_only": [
                    "from_pdf_to_floors.v2.py",
                    "define_floor_v2.py",
                    "atomic_v2/region_split/split_regions.py",
                ],
                "changes_in_this_mapper": [
                    "no_largest_area_only_frame_selection",
                    "no_exactly_two_regions_assumption",
                    "no_one_floor_per_page_assumption",
                    "uncertainty_is_retained_instead_of_discarded",
                ],
            },
        },
        "runtime": {"ocr": ocr_runtime},
        "observations": {
            "primary_planimetric_frame": frame,
            "alternative_frame_hypotheses": frame_alternatives,
            "header_titleblock": header,
            "header_titleblock_components": header_components,
            "ocr_words": words,
            "floor_title_candidates": titles,
            "structural_linework_candidates": structural,
            "floor_regions": floor_regions,
            "floor_layout": layout,
        },
        "unclassified_content": {
            "policy": "preserve_first_classify_later",
            "raw_source_is_authoritative": True,
            "floor_region_raster_scopes": [
                {
                    "region_id": region["id"],
                    "bbox_page_px": region["bbox_page_px"],
                    "classification": "raw_content_preserved_semantics_unresolved",
                    "abstained": True,
                }
                for region in floor_regions
            ],
            "unresolved_ocr_word_ids_by_scope": unresolved_words_by_scope,
            "external_unclassified_ink_pixels": external_unclassified_pixels,
            "external_unclassified_ink_components": external_unclassified,
        },
        "abstentions": abstentions,
        "summary": {
            "frame_detected": not frame["abstained"],
            "header_titleblock_candidates": 1 if header else 0,
            "header_macro_components": len(header_components),
            "ocr_words": len(words),
            "floor_title_candidates": len(titles),
            "floor_region_candidates": len(floor_regions),
            "floor_regions_abstained": sum(
                1 for region in floor_regions if region["abstained"]
            ),
            "structural_linework_candidates": len(structural),
            "semantic_wall_or_room_assignments": 0,
        },
    }
    return payload


def map_sheet(
    source: Path,
    output_dir: Path,
    doctr_runtime: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"source image not found: {source}")
    if not doctr_runtime.is_dir():
        raise FileNotFoundError(f"docTR runtime not found: {doctr_runtime}")
    if output_dir.exists():
        raise FileExistsError(
            f"immutable revision already exists; refusing overwrite: {output_dir}"
        )

    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"OpenCV cannot decode source image: {source}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    frame, frame_alternatives, ink = detect_primary_frame(gray)
    header_components, header = detect_header_titleblock(ink, frame)
    words, ocr_runtime = run_full_page_doctr(
        source, doctr_runtime, image.shape[1], image.shape[0]
    )
    titles = detect_floor_titles(words)
    structural = detect_structural_candidates(ink, frame)
    floor_regions, layout = build_floor_regions(titles, structural, frame)
    external_count, external_components = detect_external_unclassified_ink(
        ink, frame["bbox_page_px"], header["bbox_page_px"] if header else None
    )
    payload = build_payload(
        source,
        image,
        frame,
        frame_alternatives,
        header_components,
        header,
        words,
        ocr_runtime,
        titles,
        structural,
        floor_regions,
        layout,
        external_count,
        external_components,
    )

    if dry_run:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "frame": frame,
                    "header": header,
                    "titles": titles,
                    "structural": structural,
                    "regions": floor_regions,
                    "layout": layout,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return payload

    overlay = render_overlay(
        image,
        frame,
        header,
        titles,
        structural,
        floor_regions,
        layout,
        ocr_runtime,
        external_count,
    )
    success, encoded_overlay = cv2.imencode(".png", overlay)
    if not success:
        raise RuntimeError("OpenCV failed to encode overlay PNG")
    json_bytes = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "sheet_map.json"
    overlay_path = output_dir / "sheet_map_overlay.png"
    if json_path.exists() or overlay_path.exists():
        raise FileExistsError("immutable revision artifact unexpectedly exists")
    json_path.write_bytes(json_bytes)
    overlay_path.write_bytes(encoded_overlay.tobytes())
    print(json_path)
    print(overlay_path)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map page, frame, titleblock, floor-title candidates and floor regions."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--doctr-runtime", type=Path, default=DEFAULT_DOCTR_RUNTIME)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        map_sheet(
            source=args.source.resolve(),
            output_dir=args.output_dir.resolve(),
            doctr_runtime=args.doctr_runtime.resolve(),
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"SHEET_MAPPER_ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
