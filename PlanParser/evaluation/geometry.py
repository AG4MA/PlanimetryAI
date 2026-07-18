"""Geometry comparisons in rendered-page pixel coordinates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from .config import EvaluationConfig


@dataclass(frozen=True)
class GeometryComparison:
    comparable: bool
    passed: bool
    similarity: float
    metric: str
    value: float | None
    threshold: float | None
    approximate: bool = False
    secondary_metric: str | None = None
    secondary_value: float | None = None
    secondary_threshold: float | None = None


REGION_TYPES = {"bbox", "polygon"}
LINE_TYPES = {"polyline"}


def _points(geometry: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [(float(point[0]), float(point[1])) for point in geometry.get("points", [])]


def _bbox_points(bbox: Sequence[float]) -> list[tuple[float, float]]:
    x, y, width, height = (float(value) for value in bbox)
    return [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    ]


def geometry_points(geometry: Mapping[str, Any]) -> list[tuple[float, float]]:
    kind = geometry["type"]
    if kind == "bbox":
        return _bbox_points(geometry["bbox"])
    return _points(geometry)


def geometry_bbox(geometry: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    if geometry["type"] == "bbox":
        x, y, width, height = (float(value) for value in geometry["bbox"])
        return x, y, x + width, y + height
    points = geometry_points(geometry)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_iou(first: Sequence[float], second: Sequence[float]) -> float:
    ax, ay, aw, ah = (float(value) for value in first)
    bx, by, bw, bh = (float(value) for value in second)
    intersection_width = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    intersection_height = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = intersection_width * intersection_height
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _polygon_iou(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    max_raster_pixels: int,
) -> tuple[float, bool]:
    first_points = geometry_points(first)
    second_points = geometry_points(second)
    if len(first_points) < 3 or len(second_points) < 3:
        return 0.0, False

    all_points = first_points + second_points
    min_x = math.floor(min(point[0] for point in all_points))
    min_y = math.floor(min(point[1] for point in all_points))
    max_x = math.ceil(max(point[0] for point in all_points))
    max_y = math.ceil(max(point[1] for point in all_points))
    source_width = max(1.0, max_x - min_x + 3.0)
    source_height = max(1.0, max_y - min_y + 3.0)
    source_pixels = source_width * source_height
    scale = min(1.0, math.sqrt(max_raster_pixels / source_pixels))
    approximate = scale < 1.0
    width = max(2, int(math.ceil(source_width * scale)))
    height = max(2, int(math.ceil(source_height * scale)))

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("opencv-python is required for polygon IoU") from exc

    def raster_points(points: Sequence[tuple[float, float]]) -> np.ndarray:
        converted = [
            [
                int(round((x - min_x + 1.0) * scale)),
                int(round((y - min_y + 1.0) * scale)),
            ]
            for x, y in points
        ]
        return np.asarray(converted, dtype=np.int32)

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(first_mask, [raster_points(first_points)], 1)
    cv2.fillPoly(second_mask, [raster_points(second_points)], 1)
    intersection = int(np.count_nonzero(first_mask & second_mask))
    union = int(np.count_nonzero(first_mask | second_mask))
    return (intersection / union if union else 0.0), approximate


def polyline_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.dist(points[index - 1], points[index])
        for index in range(1, len(points))
    )


def _sample_polyline(
    points: Sequence[tuple[float, float]], max_samples: int
) -> np.ndarray:
    if len(points) == 1:
        return np.asarray(points, dtype=float)
    segment_lengths = np.asarray(
        [math.dist(points[index - 1], points[index]) for index in range(1, len(points))],
        dtype=float,
    )
    total = float(segment_lengths.sum())
    if total == 0:
        return np.asarray([points[0]], dtype=float)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    sample_count = min(max_samples, max(2, int(math.ceil(total)) + 1))
    distances = np.linspace(0.0, total, sample_count)
    sampled: list[tuple[float, float]] = []
    segment_index = 0
    for distance in distances:
        while (
            segment_index < len(segment_lengths) - 1
            and distance > cumulative[segment_index + 1]
        ):
            segment_index += 1
        length = segment_lengths[segment_index]
        start = points[segment_index]
        end = points[segment_index + 1]
        ratio = 0.0 if length == 0 else (distance - cumulative[segment_index]) / length
        sampled.append((
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
        ))
    return np.asarray(sampled, dtype=float)


def symmetric_polyline_distance(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    max_samples: int,
) -> float:
    first_samples = _sample_polyline(first, max_samples)
    second_samples = _sample_polyline(second, max_samples)
    if not len(first_samples) or not len(second_samples):
        return math.inf
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("scipy is required for polyline evaluation") from exc
    first_to_second = cKDTree(second_samples).query(first_samples, k=1)[0]
    second_to_first = cKDTree(first_samples).query(second_samples, k=1)[0]
    return float((first_to_second.mean() + second_to_first.mean()) / 2.0)


def symmetric_polyline_coverage(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    max_samples: int,
    distance_threshold: float,
) -> float:
    first_samples = _sample_polyline(first, max_samples)
    second_samples = _sample_polyline(second, max_samples)
    if not len(first_samples) or not len(second_samples):
        return 0.0
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("scipy is required for polyline evaluation") from exc
    first_to_second = cKDTree(second_samples).query(first_samples, k=1)[0]
    second_to_first = cKDTree(first_samples).query(second_samples, k=1)[0]
    first_coverage = float(np.mean(first_to_second <= distance_threshold))
    second_coverage = float(np.mean(second_to_first <= distance_threshold))
    return min(first_coverage, second_coverage)


def compare_geometry(
    prediction: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    config: EvaluationConfig,
    page_diagonal_px: float,
) -> GeometryComparison:
    if page_diagonal_px <= 0:
        raise ValueError("page_diagonal_px must be positive")
    prediction_type = prediction["type"]
    ground_truth_type = ground_truth["type"]

    if prediction_type in REGION_TYPES and ground_truth_type in REGION_TYPES:
        if prediction_type == ground_truth_type == "bbox":
            value = bbox_iou(prediction["bbox"], ground_truth["bbox"])
            threshold = config.bbox_iou_threshold
            metric = "bbox_iou"
            approximate = False
        else:
            value, approximate = _polygon_iou(
                prediction, ground_truth, config.max_polygon_raster_pixels
            )
            threshold = config.polygon_iou_threshold
            metric = "polygon_iou"
        return GeometryComparison(
            True, value >= threshold, value, metric, value, threshold, approximate
        )

    if prediction_type in LINE_TYPES and ground_truth_type in LINE_TYPES:
        prediction_points = geometry_points(prediction)
        ground_truth_points = geometry_points(ground_truth)
        value = symmetric_polyline_distance(
            prediction_points, ground_truth_points, config.max_polyline_samples
        )
        absolute_threshold = config.line_distance_threshold_fraction * page_diagonal_px
        normalized_value = value / page_diagonal_px
        coverage = symmetric_polyline_coverage(
            prediction_points,
            ground_truth_points,
            config.max_polyline_samples,
            absolute_threshold,
        )
        threshold = config.line_distance_threshold_fraction
        similarity = min(
            max(0.0, 1.0 - normalized_value / (2.0 * threshold)), coverage
        )
        return GeometryComparison(
            True,
            normalized_value <= threshold and coverage >= config.line_min_coverage,
            similarity,
            "polyline_distance_fraction",
            normalized_value,
            threshold,
            False,
            "polyline_coverage",
            coverage,
            config.line_min_coverage,
        )

    if prediction_type == ground_truth_type == "point":
        prediction_points = geometry_points(prediction)
        ground_truth_points = geometry_points(ground_truth)
        value = math.dist(prediction_points[0], ground_truth_points[0]) / page_diagonal_px
        threshold = config.point_distance_threshold_fraction
        similarity = max(0.0, 1.0 - value / (2.0 * threshold))
        return GeometryComparison(
            True, value <= threshold, similarity, "point_distance_fraction", value, threshold
        )

    if prediction_type == ground_truth_type == "mask":
        identical = prediction.get("mask_sha256") == ground_truth.get("mask_sha256")
        value = 1.0 if identical else 0.0
        return GeometryComparison(
            True, identical, value, "mask_hash_match", value, 1.0
        )

    return GeometryComparison(False, False, 0.0, "incomparable", None, None)
