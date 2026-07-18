from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
ATOMIC_V2_DIR = SCRIPT_DIR.parent
PREPROCESS_REVISION = (
    ATOMIC_V2_DIR
    / "ocr_preprocess"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)
PREPROCESS_MANIFEST = PREPROCESS_REVISION / "preprocess_manifest.json"
SOURCE_CROP = (
    ATOMIC_V2_DIR
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_001.png"
)
DEFAULT_OUTPUT = (
    SCRIPT_DIR
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)
INPUT_VARIANT_IDS = (
    "otsu_suppress_long_axis_lines_2x",
    "otsu_suppress_extra_long_axis_lines_2x",
)


@dataclass(frozen=True)
class Component:
    label: int
    x: int
    y: int
    width: int
    height: int
    area: int
    fill: float
    component_class: str
    shape_quality: float

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height


@dataclass
class Observation:
    variant_id: str
    bbox_variant: tuple[float, float, float, float]
    bbox_source: tuple[float, float, float, float]
    components: list[Component]
    word_boxes_variant: list[tuple[float, float, float, float]]
    word_boxes_source: list[tuple[float, float, float, float]]
    geometric_quality: float
    quality_factors: dict[str, float]
    border_clipped: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def png_write_new(path: Path, image: np.ndarray) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise RuntimeError(f"Could not write PNG: {path}")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def bbox_from_components(components: list[Component]) -> tuple[float, float, float, float]:
    x1 = min(component.x for component in components)
    y1 = min(component.y for component in components)
    x2 = max(component.x2 for component in components)
    y2 = max(component.y2 for component in components)
    return float(x1), float(y1), float(x2), float(y2)


def bbox_to_record(bbox: tuple[float, float, float, float], rounded: bool = True) -> dict[str, float]:
    x1, y1, x2, y2 = bbox
    values = {
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }
    if rounded:
        return {key: round(float(value), 3) for key, value in values.items()}
    return {key: float(value) for key, value in values.items()}


def map_bbox(
    bbox: tuple[float, float, float, float], matrix: np.ndarray
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox
    corners = np.array(
        [[x1, y1, 1.0], [x2, y1, 1.0], [x2, y2, 1.0], [x1, y2, 1.0]],
        dtype=np.float64,
    )
    mapped = (matrix @ corners.T).T
    mapped_xy = mapped[:, :2] / mapped[:, 2:3]
    return (
        float(mapped_xy[:, 0].min()),
        float(mapped_xy[:, 1].min()),
        float(mapped_xy[:, 0].max()),
        float(mapped_xy[:, 1].max()),
    )


def component_candidates(binary_black_on_white: np.ndarray) -> tuple[list[Component], list[Component]]:
    ink = (binary_black_on_white < 128).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
    core: list[Component] = []
    satellites: list[Component] = []
    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        fill = float(area / max(1, width * height))
        aspect = float(width / max(1, height))

        horizontal_rule = height <= 5 and width >= max(18, 4 * height)
        vertical_rule = width <= 4 and height >= 18 and fill >= 0.72
        open_corner_shape = aspect >= 1.8 and fill < 0.13 and width >= 28
        oversized = width > 70 or height > 58 or area > 1500
        core_geometry = (
            8 <= height <= 58
            and 2 <= width <= 70
            and 14 <= area <= 1500
            and 0.045 <= fill <= 0.9
            and not horizontal_rule
            and not vertical_rule
            and not open_corner_shape
            and not oversized
        )
        satellite_geometry = (
            2 <= height <= 11
            and 2 <= width <= 20
            and 4 <= area <= 150
            and not horizontal_rule
        )

        if core_geometry:
            fill_score = 1.0 - min(1.0, abs(fill - 0.34) / 0.34)
            height_score = clamp((height - 8) / 14.0, 0.0, 1.0)
            aspect_score = 1.0 if aspect <= 1.5 else clamp(2.4 - aspect, 0.0, 1.0)
            shape_quality = 0.35 * fill_score + 0.4 * height_score + 0.25 * aspect_score
            core.append(
                Component(
                    label,
                    x,
                    y,
                    width,
                    height,
                    area,
                    fill,
                    "core",
                    float(clamp(shape_quality, 0.0, 1.0)),
                )
            )
        elif satellite_geometry:
            satellites.append(
                Component(label, x, y, width, height, area, fill, "satellite", 0.45)
            )
    return core, satellites


def components_share_line(first: Component, second: Component, median_height: float) -> bool:
    if first.x <= second.x:
        left, right = first, second
    else:
        left, right = second, first
    horizontal_gap = max(0.0, float(right.x - left.x2))
    vertical_overlap = max(0.0, float(min(first.y2, second.y2) - max(first.y, second.y)))
    overlap_ratio = vertical_overlap / max(1.0, float(min(first.height, second.height)))
    center_delta_y = abs((first.y + first.height / 2.0) - (second.y + second.height / 2.0))
    baseline_delta = abs(first.y2 - second.y2)
    vertical_compatible = (
        overlap_ratio >= 0.28
        or center_delta_y <= 0.48 * median_height
        or baseline_delta <= 0.38 * median_height
    )
    maximum_gap = max(13.0, 0.82 * median_height)
    return vertical_compatible and horizontal_gap <= maximum_gap


def group_core_components(core: list[Component]) -> list[list[Component]]:
    if not core:
        return []
    median_height = float(np.median([component.height for component in core]))
    parents = list(range(len(core)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        root_first = find(first)
        root_second = find(second)
        if root_first != root_second:
            parents[root_second] = root_first

    order = sorted(range(len(core)), key=lambda index: core[index].x)
    for position, first_index in enumerate(order):
        first = core[first_index]
        maximum_scan_x = first.x2 + max(18.0, 0.9 * median_height)
        for second_index in order[position + 1 :]:
            second = core[second_index]
            if second.x > maximum_scan_x:
                break
            if components_share_line(first, second, median_height):
                union(first_index, second_index)

    groups_by_root: dict[int, list[Component]] = {}
    for index, component in enumerate(core):
        groups_by_root.setdefault(find(index), []).append(component)
    return list(groups_by_root.values())


def attach_satellites(
    groups: list[list[Component]], satellites: list[Component]
) -> list[list[Component]]:
    if not groups:
        return []
    for satellite in satellites:
        best_index: int | None = None
        best_distance = float("inf")
        satellite_center_x = satellite.x + satellite.width / 2.0
        satellite_center_y = satellite.y + satellite.height / 2.0
        for index, group in enumerate(groups):
            x1, y1, x2, y2 = bbox_from_components(group)
            median_height = float(np.median([component.height for component in group]))
            expanded_x1 = x1 - max(8.0, 0.35 * median_height)
            expanded_x2 = x2 + max(8.0, 0.35 * median_height)
            expanded_y1 = y1 - max(10.0, 0.55 * median_height)
            expanded_y2 = y2 + max(8.0, 0.4 * median_height)
            if not (
                expanded_x1 <= satellite_center_x <= expanded_x2
                and expanded_y1 <= satellite_center_y <= expanded_y2
            ):
                continue
            dx = 0.0 if x1 <= satellite_center_x <= x2 else min(abs(satellite_center_x - x1), abs(satellite_center_x - x2))
            dy = 0.0 if y1 <= satellite_center_y <= y2 else min(abs(satellite_center_y - y1), abs(satellite_center_y - y2))
            distance = math.hypot(dx, dy)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None:
            groups[best_index].append(satellite)
    return groups


def split_word_boxes(components: list[Component]) -> list[tuple[float, float, float, float]]:
    ordered = sorted(components, key=lambda component: (component.x, component.y))
    core_heights = [component.height for component in ordered if component.component_class == "core"]
    median_height = float(np.median(core_heights)) if core_heights else 20.0
    positive_gaps: list[float] = []
    for first, second in zip(ordered, ordered[1:]):
        gap = float(second.x - first.x2)
        if gap > 0:
            positive_gaps.append(gap)
    typical_gap = float(np.median(positive_gaps)) if positive_gaps else 3.0
    split_gap = max(10.0, min(0.62 * median_height, 2.6 * typical_gap))

    words: list[list[Component]] = [[ordered[0]]]
    current_right = float(ordered[0].x2)
    for component in ordered[1:]:
        gap = float(component.x - current_right)
        if gap > split_gap:
            words.append([component])
        else:
            words[-1].append(component)
        current_right = max(current_right, float(component.x2))
    return [bbox_from_components(word) for word in words]


def observation_quality(
    components: list[Component], bbox: tuple[float, float, float, float]
) -> tuple[float, dict[str, float]]:
    core = [component for component in components if component.component_class == "core"]
    heights = np.asarray([component.height for component in core], dtype=np.float64)
    baselines = np.asarray([component.y2 for component in core], dtype=np.float64)
    shape_quality = float(np.mean([component.shape_quality for component in core])) if core else 0.0
    count_score = clamp((len(core) - 1) / 5.0, 0.08, 1.0)
    if len(core) >= 2:
        height_cv = float(np.std(heights) / max(1.0, np.mean(heights)))
        height_consistency = math.exp(-3.2 * height_cv)
        baseline_spread = float(np.std(baselines) / max(1.0, np.median(heights)))
        baseline_consistency = math.exp(-3.0 * baseline_spread)
    else:
        height_consistency = 0.35
        baseline_consistency = 0.35
    x1, y1, x2, y2 = bbox
    bbox_area = max(1.0, (x2 - x1) * (y2 - y1))
    density = sum(component.area for component in components) / bbox_area
    density_score = 1.0 - min(1.0, abs(density - 0.23) / 0.23)
    quality = (
        0.24 * count_score
        + 0.22 * height_consistency
        + 0.22 * baseline_consistency
        + 0.18 * shape_quality
        + 0.14 * density_score
    )
    factors = {
        "component_count": round(count_score, 6),
        "height_consistency": round(height_consistency, 6),
        "baseline_consistency": round(baseline_consistency, 6),
        "component_shape": round(shape_quality, 6),
        "ink_density": round(density_score, 6),
    }
    return float(clamp(quality, 0.0, 1.0)), factors


def build_observations(
    variant_id: str,
    image: np.ndarray,
    inverse_matrix: np.ndarray,
    source_size: tuple[int, int],
) -> tuple[list[Observation], dict[str, int]]:
    core, satellites = component_candidates(image)
    groups = attach_satellites(group_core_components(core), satellites)
    observations: list[Observation] = []
    variant_height, variant_width = image.shape
    source_width, source_height = source_size
    rejected_too_large = 0
    for group in groups:
        bbox_variant = bbox_from_components(group)
        x1, y1, x2, y2 = bbox_variant
        box_width = x2 - x1
        box_height = y2 - y1
        core_count = sum(component.component_class == "core" for component in group)
        if box_width > variant_width * 0.42 or box_height > 85 or core_count == 0:
            rejected_too_large += 1
            continue
        bbox_source = map_bbox(bbox_variant, inverse_matrix)
        source_x1, source_y1, source_x2, source_y2 = bbox_source
        bbox_source = (
            clamp(source_x1, 0.0, float(source_width)),
            clamp(source_y1, 0.0, float(source_height)),
            clamp(source_x2, 0.0, float(source_width)),
            clamp(source_y2, 0.0, float(source_height)),
        )
        word_boxes_variant = split_word_boxes(group)
        word_boxes_source = [map_bbox(box, inverse_matrix) for box in word_boxes_variant]
        quality, factors = observation_quality(group, bbox_variant)
        border_margin = 3.0
        border_clipped = (
            x1 <= border_margin
            or y1 <= border_margin
            or x2 >= variant_width - border_margin
            or y2 >= variant_height - border_margin
        )
        observations.append(
            Observation(
                variant_id=variant_id,
                bbox_variant=bbox_variant,
                bbox_source=bbox_source,
                components=sorted(group, key=lambda component: (component.x, component.y)),
                word_boxes_variant=word_boxes_variant,
                word_boxes_source=word_boxes_source,
                geometric_quality=quality,
                quality_factors=factors,
                border_clipped=border_clipped,
            )
        )
    diagnostics = {
        "connected_core_components": len(core),
        "connected_satellite_components": len(satellites),
        "line_groups_retained": len(observations),
        "groups_rejected_as_oversized": rejected_too_large,
    }
    return observations, diagnostics


def bbox_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_first = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_second = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_first + area_second - intersection
    return float(intersection / union) if union > 0 else 0.0


def compatible_observations(first: Observation, second: Observation) -> tuple[bool, float]:
    first_box = first.bbox_source
    second_box = second.bbox_source
    iou = bbox_iou(first_box, second_box)
    vertical_overlap = max(0.0, min(first_box[3], second_box[3]) - max(first_box[1], second_box[1]))
    minimum_height = max(1.0, min(first_box[3] - first_box[1], second_box[3] - second_box[1]))
    vertical_ratio = vertical_overlap / minimum_height
    horizontal_overlap = max(0.0, min(first_box[2], second_box[2]) - max(first_box[0], second_box[0]))
    minimum_width = max(1.0, min(first_box[2] - first_box[0], second_box[2] - second_box[0]))
    horizontal_ratio = horizontal_overlap / minimum_width
    center_y_first = (first_box[1] + first_box[3]) / 2.0
    center_y_second = (second_box[1] + second_box[3]) / 2.0
    center_delta_y = abs(center_y_first - center_y_second)
    compatible = iou >= 0.3 or (
        vertical_ratio >= 0.62
        and horizontal_ratio >= 0.62
        and center_delta_y <= 0.45 * minimum_height
    )
    score = max(iou, 0.7 * vertical_ratio + 0.3 * horizontal_ratio)
    return compatible, float(clamp(score, 0.0, 1.0))


def merge_observations(
    by_variant: dict[str, list[Observation]]
) -> list[tuple[list[Observation], float]]:
    first_id, second_id = INPUT_VARIANT_IDS
    first_observations = by_variant[first_id]
    second_observations = by_variant[second_id]
    possible_matches: list[tuple[float, int, int]] = []
    for first_index, first in enumerate(first_observations):
        for second_index, second in enumerate(second_observations):
            compatible, score = compatible_observations(first, second)
            if compatible:
                possible_matches.append((score, first_index, second_index))
    possible_matches.sort(reverse=True)

    used_first: set[int] = set()
    used_second: set[int] = set()
    clusters: list[tuple[list[Observation], float]] = []
    for score, first_index, second_index in possible_matches:
        if first_index in used_first or second_index in used_second:
            continue
        used_first.add(first_index)
        used_second.add(second_index)
        clusters.append(
            ([first_observations[first_index], second_observations[second_index]], score)
        )
    for index, observation in enumerate(first_observations):
        if index not in used_first:
            clusters.append(([observation], 0.0))
    for index, observation in enumerate(second_observations):
        if index not in used_second:
            clusters.append(([observation], 0.0))
    return clusters


def merged_bbox(observations: list[Observation]) -> tuple[float, float, float, float]:
    boxes = np.asarray([observation.bbox_source for observation in observations], dtype=np.float64)
    return tuple(float(value) for value in np.median(boxes, axis=0))


def candidate_confidence(
    observations: list[Observation], agreement: float, border_clipped: bool
) -> float:
    mean_quality = float(np.mean([observation.geometric_quality for observation in observations]))
    if len(observations) >= 2:
        confidence = 0.7 * mean_quality + 0.17 * agreement + 0.13
    else:
        confidence = min(0.49, 0.48 * mean_quality + 0.08)
    if border_clipped:
        confidence = min(confidence, 0.48)
    return float(clamp(confidence, 0.02, 0.98))


def reasons_for_candidate(
    observations: list[Observation], agreement: float, confidence: float, border_clipped: bool
) -> list[str]:
    reasons: list[str] = []
    if len(observations) >= 2:
        reasons.append("dual_variant_geometric_support")
        reasons.append("strong_bbox_agreement" if agreement >= 0.72 else "partial_bbox_agreement")
    else:
        reasons.extend(["single_variant_support", "retained_uncertain_candidate"])
    maximum_core_count = max(
        sum(component.component_class == "core" for component in observation.components)
        for observation in observations
    )
    if maximum_core_count >= 3:
        reasons.append("multi_component_horizontal_sequence")
    elif maximum_core_count == 2:
        reasons.append("short_component_sequence")
    else:
        reasons.append("single_core_component")
    if border_clipped:
        reasons.append("touches_input_border_possible_truncation")
    if confidence < 0.55:
        reasons.append("geometry_below_acceptance_threshold")
    return reasons


def component_record(component: Component) -> dict[str, Any]:
    return {
        "component_label": component.label,
        "class": component.component_class,
        "bbox_variant_px": {
            "x": component.x,
            "y": component.y,
            "width": component.width,
            "height": component.height,
        },
        "area_px": component.area,
        "fill_ratio": round(component.fill, 6),
        "shape_quality": round(component.shape_quality, 6),
    }


def build_payload(
    source: np.ndarray,
    manifest: dict[str, Any],
    manifest_path: Path,
    variant_paths: dict[str, Path],
    by_variant: dict[str, list[Observation]],
    diagnostics: dict[str, dict[str, int]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clusters = merge_observations(by_variant)
    raw_candidates: list[dict[str, Any]] = []
    for observations, agreement in clusters:
        bbox = merged_bbox(observations)
        border_clipped = any(observation.border_clipped for observation in observations)
        confidence = candidate_confidence(observations, agreement, border_clipped)
        abstained = bool(confidence < 0.55 or len(observations) < 2 or border_clipped)
        supporting_variants = sorted(observation.variant_id for observation in observations)

        word_boxes: list[tuple[float, float, float, float]] = []
        reference_observation = max(observations, key=lambda item: item.geometric_quality)
        word_boxes.extend(reference_observation.word_boxes_source)
        observation_records: list[dict[str, Any]] = []
        for observation in observations:
            observation_records.append(
                {
                    "variant_id": observation.variant_id,
                    "bbox_variant_px": bbox_to_record(observation.bbox_variant),
                    "bbox_original_px": bbox_to_record(observation.bbox_source),
                    "geometric_quality": round(observation.geometric_quality, 6),
                    "quality_factors": observation.quality_factors,
                    "core_component_count": sum(
                        component.component_class == "core"
                        for component in observation.components
                    ),
                    "satellite_component_count": sum(
                        component.component_class == "satellite"
                        for component in observation.components
                    ),
                    "components": [component_record(component) for component in observation.components],
                }
            )
        raw_candidates.append(
            {
                "bbox": bbox,
                "bbox_original_px": bbox_to_record(bbox),
                "confidence_geometry": round(confidence, 6),
                "abstained": abstained,
                "reasons": reasons_for_candidate(
                    observations, agreement, confidence, border_clipped
                ),
                "supporting_variants": supporting_variants,
                "variant_agreement": round(agreement, 6) if len(observations) >= 2 else None,
                "border_clipped": border_clipped,
                "word_segments": [
                    {
                        "segment_index": index + 1,
                        "bbox_original_px": bbox_to_record(word_box),
                    }
                    for index, word_box in enumerate(word_boxes)
                ],
                "observations": observation_records,
            }
        )

    raw_candidates.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates, start=1):
        candidate = {key: value for key, value in raw.items() if key != "bbox"}
        candidate["id"] = f"TC-{index:03d}"
        candidate["polygon_original_px"] = [
            [round(raw["bbox"][0], 3), round(raw["bbox"][1], 3)],
            [round(raw["bbox"][2], 3), round(raw["bbox"][1], 3)],
            [round(raw["bbox"][2], 3), round(raw["bbox"][3], 3)],
            [round(raw["bbox"][0], 3), round(raw["bbox"][3], 3)],
        ]
        candidates.append(candidate)

    manifest_records = {record["id"]: record for record in manifest["variants"]}
    source_height, source_width = source.shape[:2]
    payload = {
        "schema_version": "planparser.ocr_text_candidates.v1",
        "recognition_performed": False,
        "semantic_assignment_performed": False,
        "source": {
            "path": manifest["source"]["path"],
            "sha256": sha256_file(SOURCE_CROP),
            "width_px": source_width,
            "height_px": source_height,
        },
        "preprocess_manifest": {
            "path": manifest_path.relative_to(ATOMIC_V2_DIR).as_posix(),
            "sha256": sha256_file(manifest_path),
            "schema_version": manifest["schema_version"],
        },
        "input_variants": [
            {
                "id": variant_id,
                "path": variant_paths[variant_id].relative_to(ATOMIC_V2_DIR).as_posix(),
                "sha256": sha256_file(variant_paths[variant_id]),
                "manifest_sha256": manifest_records[variant_id]["sha256"],
                "variant_to_original_homogeneous_3x3": manifest_records[variant_id][
                    "coordinates"
                ]["variant_to_source_homogeneous_3x3"],
                "diagnostics": diagnostics[variant_id],
            }
            for variant_id in INPUT_VARIANT_IDS
        ],
        "method": {
            "component_detection": "8_connected_components_on_binary_ink",
            "line_grouping": "horizontal_proximity_with_vertical_and_baseline_compatibility",
            "word_segmentation": "adaptive_horizontal_gap_only",
            "cross_variant_merge": "greedy_one_to_one_geometric_agreement",
            "confidence_scope": "geometric_candidate_quality_only",
            "acceptance_threshold": 0.55,
            "uncertain_candidates_policy": "preserve_and_mark_abstained",
        },
        "summary": {
            "candidate_count": len(candidates),
            "supported_by_both_variants": sum(
                len(candidate["supporting_variants"]) == 2 for candidate in candidates
            ),
            "single_variant_candidates": sum(
                len(candidate["supporting_variants"]) == 1 for candidate in candidates
            ),
            "abstained_count": sum(candidate["abstained"] for candidate in candidates),
            "non_abstained_count": sum(not candidate["abstained"] for candidate in candidates),
        },
        "candidates": candidates,
        "notes": [
            "Candidate identifiers are geometric references and do not encode text or semantics.",
            "No character recognition, transcription, room classification, or meaning assignment was performed.",
            "Abstained candidates are intentionally retained for downstream review or stronger OCR models.",
        ],
    }
    return payload, raw_candidates


def render_overlay(source: np.ndarray, candidates: list[dict[str, Any]]) -> np.ndarray:
    overlay = source.copy()
    tint = source.copy()
    for candidate in candidates:
        box = candidate["bbox_original_px"]
        x1 = int(math.floor(box["x"]))
        y1 = int(math.floor(box["y"]))
        x2 = int(math.ceil(box["x"] + box["width"]))
        y2 = int(math.ceil(box["y"] + box["height"]))
        color = (0, 155, 255) if candidate["abstained"] else (30, 185, 45)
        cv2.rectangle(tint, (x1, y1), (x2, y2), color, -1)
    overlay = cv2.addWeighted(tint, 0.16, overlay, 0.84, 0.0)

    for candidate in candidates:
        box = candidate["bbox_original_px"]
        x1 = int(math.floor(box["x"]))
        y1 = int(math.floor(box["y"]))
        x2 = int(math.ceil(box["x"] + box["width"]))
        y2 = int(math.ceil(box["y"] + box["height"]))
        color = (0, 145, 245) if candidate["abstained"] else (20, 165, 35)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        label = candidate["id"].replace("TC-", "")
        (label_width, label_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1
        )
        label_x = max(0, min(x1, overlay.shape[1] - label_width - 5))
        label_y = y1 - 3
        if label_y - label_height - baseline < 0:
            label_y = min(overlay.shape[0] - 2, y2 + label_height + baseline + 3)
        cv2.rectangle(
            overlay,
            (label_x, label_y - label_height - baseline - 2),
            (label_x + label_width + 4, label_y + 2),
            color,
            -1,
        )
        cv2.putText(
            overlay,
            label,
            (label_x + 2, label_y - 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    cv2.rectangle(overlay, (5, 5), (225, 42), (255, 255, 255), -1)
    cv2.rectangle(overlay, (5, 5), (225, 42), (80, 80, 80), 1)
    cv2.rectangle(overlay, (13, 13), (28, 27), (20, 165, 35), 2)
    cv2.putText(overlay, "dual support", (34, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (40, 40, 40), 1, cv2.LINE_AA)
    cv2.rectangle(overlay, (119, 13), (134, 27), (0, 145, 245), 2)
    cv2.putText(overlay, "abstained", (140, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (40, 40, 40), 1, cv2.LINE_AA)
    cv2.putText(overlay, "geometry only; no recognition", (13, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (60, 60, 60), 1, cv2.LINE_AA)
    return overlay


def load_inputs() -> tuple[np.ndarray, dict[str, Any], dict[str, Path], dict[str, np.ndarray]]:
    if not PREPROCESS_MANIFEST.is_file():
        raise FileNotFoundError(PREPROCESS_MANIFEST)
    if not SOURCE_CROP.is_file():
        raise FileNotFoundError(SOURCE_CROP)
    manifest = json.loads(PREPROCESS_MANIFEST.read_text(encoding="utf-8"))
    records = {record["id"]: record for record in manifest["variants"]}
    variant_paths: dict[str, Path] = {}
    inverse_matrices: dict[str, np.ndarray] = {}
    for variant_id in INPUT_VARIANT_IDS:
        record = records[variant_id]
        path = PREPROCESS_REVISION / record["filename"]
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Input variant hash mismatch: {variant_id}")
        variant_paths[variant_id] = path
        inverse_matrices[variant_id] = np.asarray(
            record["coordinates"]["variant_to_source_homogeneous_3x3"], dtype=np.float64
        )
    source = cv2.imread(str(SOURCE_CROP), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"Could not decode source: {SOURCE_CROP}")
    return source, manifest, variant_paths, inverse_matrices


def run(output_dir: Path, dry_run: bool) -> tuple[dict[str, Any], np.ndarray]:
    source, manifest, variant_paths, inverse_matrices = load_inputs()
    source_height, source_width = source.shape[:2]
    by_variant: dict[str, list[Observation]] = {}
    diagnostics: dict[str, dict[str, int]] = {}
    for variant_id in INPUT_VARIANT_IDS:
        image = cv2.imread(str(variant_paths[variant_id]), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError(f"Could not decode variant: {variant_paths[variant_id]}")
        observations, variant_diagnostics = build_observations(
            variant_id,
            image,
            inverse_matrices[variant_id],
            (source_width, source_height),
        )
        by_variant[variant_id] = observations
        diagnostics[variant_id] = variant_diagnostics

    payload, _raw = build_payload(
        source,
        manifest,
        PREPROCESS_MANIFEST,
        variant_paths,
        by_variant,
        diagnostics,
    )
    overlay = render_overlay(source, payload["candidates"])
    if dry_run:
        print(json.dumps(payload["summary"], sort_keys=True))
        for candidate in payload["candidates"]:
            print(
                candidate["id"],
                candidate["bbox_original_px"],
                "confidence=",
                candidate["confidence_geometry"],
                "abstained=",
                candidate["abstained"],
                "support=",
                len(candidate["supporting_variants"]),
            )
        return payload, overlay

    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output revision is not empty; refusing overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "text_candidates.json"
    overlay_path = output_dir / "text_candidates_overlay.png"
    json_write_new(json_path, payload)
    png_write_new(overlay_path, overlay)
    print(json_path)
    print(overlay_path)
    return payload, overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect geometry-only text candidates without character recognition."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.output.resolve(), arguments.dry_run)
