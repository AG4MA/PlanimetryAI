from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from typing import Any

import cv2
import numpy as np

from .config import LEGACY_V1, TopologyEngineConfig
from .models import BarrierResult


def _candidate_items(value: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        candidates = value.get("candidates", [])
        if not isinstance(candidates, Sequence):
            raise TypeError("candidates must be a sequence")
        return candidates
    return value


def _active_text_nodes(
    text_nodes: Sequence[Mapping[str, Any]], config: TopologyEngineConfig
) -> list[Mapping[str, Any]]:
    policy = config.abstention_policy
    active: list[Mapping[str, Any]] = []
    for node in text_nodes:
        if (
            not policy.include_ocr_abstained_in_barrier_overlap
            and bool(node.get(policy.ocr_abstained_field, False))
        ):
            continue
        if (
            not policy.include_semantic_role_abstained_in_barrier_overlap
            and bool(node.get(policy.semantic_role_abstained_field, False))
        ):
            continue
        active.append(node)
    return active


def line_text_overlap(
    candidate: Mapping[str, Any],
    text_nodes: Sequence[Mapping[str, Any]],
    config: TopologyEngineConfig = LEGACY_V1,
) -> float:
    """Maximum fraction of an axis-aligned line covered by one text box."""

    (x1, y1), (x2, y2) = candidate["points_px"]
    x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))
    length = max(float(candidate.get("length_px", 0)), 1.0)
    padding = config.line_text_padding_px
    best = 0.0
    for node in _active_text_nodes(text_nodes, config):
        bx1, by1, bx2, by2 = map(float, node["bbox_crop_px_xyxy"])
        bx1 -= padding
        by1 -= padding
        bx2 += padding
        by2 += padding
        if candidate["orientation"] == "horizontal" and by1 <= y1 <= by2:
            best = max(best, max(0.0, min(x2, bx2) - max(x1, bx1)) / length)
        elif candidate["orientation"] == "vertical" and bx1 <= x1 <= bx2:
            best = max(best, max(0.0, min(y2, by2) - max(y1, by1)) / length)
    return round(best, 6)


def band_text_overlap(
    candidate: Mapping[str, Any],
    text_nodes: Sequence[Mapping[str, Any]],
    config: TopologyEngineConfig = LEGACY_V1,
) -> float:
    """Maximum text-box intersection divided by the candidate band area."""

    x, y, width, height = map(float, candidate["bbox_px"])
    area = max(width * height, 1.0)
    best = 0.0
    for node in _active_text_nodes(text_nodes, config):
        bx1, by1, bx2, by2 = map(float, node["bbox_crop_px_xyxy"])
        intersection = max(0.0, min(x + width, bx2) - max(x, bx1)) * max(
            0.0, min(y + height, by2) - max(y, by1)
        )
        best = max(best, intersection / area)
    return round(best, 6)


def build_barriers(
    width: int,
    height: int,
    linework: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    wall_bands: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    text_nodes: Sequence[Mapping[str, Any]],
    config: TopologyEngineConfig = LEGACY_V1,
) -> BarrierResult:
    """Build legacy-equivalent barrier layers without filesystem side effects."""

    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    observed_geometry = np.zeros((height, width), dtype=np.uint8)
    crop_boundary = np.zeros((height, width), dtype=np.uint8)
    if config.include_crop_boundary:
        cv2.rectangle(
            crop_boundary,
            (0, 0),
            (width - 1, height - 1),
            255,
            config.crop_boundary_thickness_px,
        )

    line_audit: list[dict[str, Any]] = []
    for candidate in _candidate_items(linework):
        overlap = line_text_overlap(candidate, text_nodes, config)
        used = not (
            overlap >= config.line_text_overlap_exclusion_ratio
            and float(candidate["length_px"])
            < config.line_text_exclusion_length_ceiling_px
        )
        line_audit.append(
            {
                "id": candidate["id"],
                "text_overlap_ratio": overlap,
                "used_as_barrier": used,
                "reason": (
                    "retained_structural_candidate"
                    if used
                    else "excluded_probable_text_stroke"
                ),
            }
        )
        if used:
            p1, p2 = [tuple(map(int, point)) for point in candidate["points_px"]]
            thickness = (
                config.solid_line_barrier_thickness_px
                if candidate.get("status") == "solid"
                else config.uncertain_line_barrier_thickness_px
            )
            cv2.line(observed_geometry, p1, p2, 255, thickness, cv2.LINE_8)

    band_audit: list[dict[str, Any]] = []
    for candidate in _candidate_items(wall_bands):
        overlap = band_text_overlap(candidate, text_nodes, config)
        used = not (
            overlap >= config.band_text_overlap_exclusion_ratio
            and float(candidate["length_px"])
            < config.band_text_exclusion_length_ceiling_px
        )
        band_audit.append(
            {
                "id": candidate["id"],
                "text_overlap_ratio": overlap,
                "used_as_barrier": used,
                "reason": (
                    "retained_parallel_edge_hypothesis"
                    if used
                    else "excluded_probable_text_band"
                ),
            }
        )
        if used:
            polygon = np.asarray(candidate["polygon_px"], dtype=np.int32)
            cv2.fillPoly(observed_geometry, [polygon], 255)

    raw_observed = cv2.bitwise_or(observed_geometry, crop_boundary)
    horizontal = cv2.morphologyEx(
        raw_observed,
        cv2.MORPH_CLOSE,
        np.ones((1, config.closure_kernel_length_px), np.uint8),
    )
    vertical = cv2.morphologyEx(
        raw_observed,
        cv2.MORPH_CLOSE,
        np.ones((config.closure_kernel_length_px, 1), np.uint8),
    )
    closed = cv2.bitwise_or(raw_observed, cv2.bitwise_or(horizontal, vertical))
    dilation_kernel = np.ones(
        (config.barrier_dilation_kernel_px, config.barrier_dilation_kernel_px),
        np.uint8,
    )
    closed = cv2.dilate(
        closed,
        dilation_kernel,
        iterations=config.barrier_dilation_iterations,
    )
    dilated_raw = cv2.dilate(
        raw_observed,
        dilation_kernel,
        iterations=config.barrier_dilation_iterations,
    )
    synthetic_closures = cv2.bitwise_and(closed, cv2.bitwise_not(dilated_raw))
    effective_barrier = cv2.bitwise_or(dilated_raw, synthetic_closures)
    return BarrierResult(
        observed_geometry=observed_geometry,
        crop_boundary=crop_boundary,
        raw_observed=raw_observed,
        synthetic_closures=synthetic_closures,
        effective_barrier=effective_barrier,
        line_audit=tuple(line_audit),
        band_audit=tuple(band_audit),
    )


def nearby_source_ids(
    point: Sequence[int] | None,
    linework: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    wall_bands: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    used_line_ids: Set[str],
    used_band_ids: Set[str],
    config: TopologyEngineConfig = LEGACY_V1,
    *,
    tolerance: float | None = None,
) -> list[str]:
    """Return retained source IDs within the legacy radial-hit tolerance."""

    if point is None:
        return []
    x, y = map(float, point)
    effective_tolerance = (
        config.nearby_source_tolerance_px if tolerance is None else float(tolerance)
    )
    sources: list[str] = []
    for item in _candidate_items(linework):
        if item["id"] not in used_line_ids:
            continue
        (x1, y1), (x2, y2) = item["points_px"]
        if item["orientation"] == "horizontal":
            distance = (
                abs(y - y1)
                if min(x1, x2) - effective_tolerance
                <= x
                <= max(x1, x2) + effective_tolerance
                else math.inf
            )
        else:
            distance = (
                abs(x - x1)
                if min(y1, y2) - effective_tolerance
                <= y
                <= max(y1, y2) + effective_tolerance
                else math.inf
            )
        if distance <= effective_tolerance:
            sources.append(str(item["id"]))
    for item in _candidate_items(wall_bands):
        if item["id"] not in used_band_ids:
            continue
        polygon = np.asarray(item["polygon_px"], dtype=np.float32)
        if cv2.pointPolygonTest(polygon, (x, y), True) >= -effective_tolerance:
            sources.append(str(item["id"]))
    return sorted(set(sources))


def boundary_sources(
    perimeter: np.ndarray,
    linework: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    wall_bands: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    used_line_ids: Set[str],
    used_band_ids: Set[str],
    config: TopologyEngineConfig = LEGACY_V1,
) -> list[dict[str, Any]]:
    """Measure retained line/band support near a candidate space perimeter."""

    if perimeter.ndim != 2:
        raise ValueError("perimeter must be a two-dimensional mask")
    near = cv2.dilate(
        perimeter.astype(np.uint8),
        np.ones((config.boundary_near_kernel_px, config.boundary_near_kernel_px), np.uint8),
    ) > 0
    evidence: list[dict[str, Any]] = []
    height, width = perimeter.shape
    for item in _candidate_items(linework):
        if item["id"] not in used_line_ids:
            continue
        mask = np.zeros((height, width), dtype=np.uint8)
        p1, p2 = [tuple(map(int, point)) for point in item["points_px"]]
        cv2.line(mask, p1, p2, 255, config.boundary_source_stroke_px)
        pixels = int(((mask > 0) & near).sum())
        if pixels:
            evidence.append(
                {
                    "source_type": "raw_linework_candidate",
                    "source_id": item["id"],
                    "support_pixels_near_space_boundary": pixels,
                    "source_status": item["status"],
                    "source_abstained": item["abstained"],
                }
            )
    for item in _candidate_items(wall_bands):
        if item["id"] not in used_band_ids:
            continue
        mask = np.zeros((height, width), dtype=np.uint8)
        polygon = np.asarray(item["polygon_px"], dtype=np.int32)
        cv2.polylines(mask, [polygon], True, 255, config.boundary_source_stroke_px)
        pixels = int(((mask > 0) & near).sum())
        if pixels:
            evidence.append(
                {
                    "source_type": "parallel_edge_band_hypothesis",
                    "source_id": item["id"],
                    "support_pixels_near_space_boundary": pixels,
                    "source_status": item["status"],
                    "source_abstained": item["abstained"],
                }
            )
    return sorted(
        evidence,
        key=lambda item: (-item["support_pixels_near_space_boundary"], item["source_id"]),
    )
