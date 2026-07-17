from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

import cv2
import numpy as np

from ..barriers import boundary_sources, nearby_source_ids
from ..config import LEGACY_V1, TopologyEngineConfig
from ..models import BarrierResult, CoordinateFrame
from .wavefront import (
    competition_boundary,
    config_value,
    contour_polygon,
    is_legacy,
    ray_observations,
)


def _abstention_flags(node: Mapping[str, Any], config: Any) -> tuple[bool, bool, bool]:
    transcription = bool(
        node.get("transcription_abstained", node.get("ocr_abstained", False))
    )
    semantic = bool(node.get("semantic_role_abstained", False))
    policy = str(
        config_value(
            config,
            ("topology.semantic_abstention_policy", "semantic_abstention_policy"),
            "transcription_only" if is_legacy(config) else "transcription_or_role",
        )
    )
    policies = {
        "transcription_only": transcription,
        "transcription_or_role": transcription or semantic,
        "role_only": semantic,
    }
    if policy not in policies:
        raise ValueError(f"Unsupported semantic abstention policy: {policy!r}")
    return transcription, semantic, policies[policy]


def _evidence_config(config: Any, kernel_size: int, tolerance: float) -> TopologyEngineConfig:
    base = config if isinstance(config, TopologyEngineConfig) else LEGACY_V1
    if (
        base.boundary_near_kernel_px == kernel_size
        and base.nearby_source_tolerance_px == tolerance
    ):
        return base
    return replace(
        base,
        boundary_near_kernel_px=kernel_size,
        nearby_source_tolerance_px=tolerance,
    )


def _common_space_fields(
    node: Mapping[str, Any],
    label: int,
    xs: np.ndarray,
    ys: np.ndarray,
    region: np.ndarray,
    page_offset: tuple[int, int],
    config: Any,
) -> dict[str, Any]:
    bbox = [
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    ]
    return {
        "id": f"space_candidate_{label:03d}",
        "name_text_node_id": node["id"],
        "name_hypothesis": node.get("canonical_space_name_hypothesis"),
        "bbox_crop_px_xywh": bbox,
        "bbox_page_px_xywh": [
            bbox[0] + int(page_offset[0]),
            bbox[1] + int(page_offset[1]),
            bbox[2],
            bbox[3],
        ],
        "polygon_crop_px": contour_polygon(region, config),
        "area_px2": int(region.sum()),
    }


def build_spaces(
    labels: np.ndarray,
    barrier: np.ndarray | BarrierResult,
    raw_barrier: np.ndarray | None = None,
    synthetic_closures: np.ndarray | None = None,
    text_nodes: list[dict[str, Any]] | None = None,
    page_offset: tuple[int, int] | CoordinateFrame = (0, 0),
    linework: Mapping[str, Any] | None = None,
    wall_bands: Mapping[str, Any] | None = None,
    used_line_ids: Iterable[str] | None = None,
    used_band_ids: Iterable[str] | None = None,
    config: Any = None,
) -> list[dict[str, Any]]:
    """Build legacy 1.0 or 1.1 candidates from a wavefront label raster."""

    barrier_result = barrier if isinstance(barrier, BarrierResult) else None
    if barrier_result is not None:
        barrier = barrier_result.effective_barrier
        raw_barrier = barrier_result.raw_observed
        synthetic_closures = barrier_result.synthetic_closures
        used_line_ids = barrier_result.used_line_ids if used_line_ids is None else used_line_ids
        used_band_ids = barrier_result.used_band_ids if used_band_ids is None else used_band_ids
    if raw_barrier is None or synthetic_closures is None or text_nodes is None:
        raise TypeError(
            "raw_barrier, synthetic_closures and text_nodes are required unless a BarrierResult supplies the barrier layers"
        )
    if isinstance(page_offset, CoordinateFrame):
        page_offset = page_offset.offset_page_px
    linework = linework or {"candidates": []}
    wall_bands = wall_bands or {"candidates": []}
    line_ids = (
        set(used_line_ids)
        if used_line_ids is not None
        else {item["id"] for item in linework.get("candidates", [])}
    )
    band_ids = (
        set(used_band_ids)
        if used_band_ids is not None
        else {item["id"] for item in wall_bands.get("candidates", [])}
    )
    contract = str(
        config_value(config, ("topology.space_contract", "space_contract"), "legacy_1_1")
    )
    near_size = int(
        config_value(
            config,
            (
                "topology.space_boundary_near_kernel_px",
                "space_boundary_near_kernel_px",
                "topology.boundary_near_kernel_px",
            ),
            5,
        )
    )
    source_near_size = int(
        config_value(
            config,
            (
                "topology.evidence_near_kernel_px",
                "evidence_near_kernel_px",
                "boundary_near_kernel_px",
            ),
            7,
        )
    )
    tolerance = float(
        config_value(
            config,
            (
                "topology.radial_source_tolerance_px",
                "radial_source_tolerance_px",
                "nearby_source_tolerance_px",
            ),
            7.0,
        )
    )
    evidence_config = _evidence_config(config, source_near_size, tolerance)
    observed_near = cv2.dilate(
        (raw_barrier > 0).astype(np.uint8), np.ones((near_size, near_size), np.uint8)
    ) > 0
    synthetic_near = cv2.dilate(
        (synthetic_closures > 0).astype(np.uint8),
        np.ones((near_size, near_size), np.uint8),
    ) > 0
    all_barrier_near = cv2.dilate(
        (barrier > 0).astype(np.uint8), np.ones((near_size, near_size), np.uint8)
    ) > 0
    spaces: list[dict[str, Any]] = []

    for node in [
        item for item in text_nodes if item.get("role_hypothesis") == "space_name_seed"
    ]:
        label = int(node["space_label_index"])
        region = labels == label
        ys, xs = np.where(region)
        if not len(xs):
            node["space_candidate_id"] = None
            continue
        eroded = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        perimeter = region & ~eroded
        perimeter_count = max(int(perimeter.sum()), 1)
        competition = competition_boundary(region, labels, label, config)
        common = _common_space_fields(node, label, xs, ys, region, page_offset, config)
        node["space_candidate_id"] = common["id"]
        seed_value = node.get("expansion_seed_crop_px")
        if seed_value is None:
            continue
        seed = tuple(map(int, seed_value))
        rays = ray_observations(seed, barrier, raw_barrier, synthetic_closures, config)
        for ray in rays:
            ray["nearby_source_ids"] = nearby_source_ids(
                ray["hit_crop_px"],
                linework,
                wall_bands,
                line_ids,
                band_ids,
                evidence_config,
                tolerance=tolerance,
            )
        transcription_abstained, _, effective_text_abstained = _abstention_flags(
            node, config
        )

        if contract == "legacy_1_0":
            support_ratio = float((perimeter & all_barrier_near).sum()) / perimeter_count
            competition_ratio = float(competition.sum()) / perimeter_count
            support_threshold = float(config_value(config, ("legacy_support_abstention_below",), 0.35))
            competition_threshold = float(config_value(config, ("legacy_competition_abstention_above",), 0.35))
            area_threshold = int(config_value(config, ("confidence_large_area_min_px2",), 500))
            confidence = min(
                float(config_value(config, ("confidence_cap",), 0.93)),
                float(config_value(config, ("legacy_confidence_base",), 0.30))
                + float(
                    config_value(config, ("legacy_confidence_observed_weight",), 0.45)
                )
                * support_ratio
                + (
                    float(
                        config_value(
                            config, ("legacy_confidence_non_abstained_bonus",), 0.10
                        )
                    )
                    if not transcription_abstained
                    else 0.0
                )
                + (
                    float(
                        config_value(
                            config, ("legacy_confidence_large_area_bonus",), 0.08
                        )
                    )
                    if len(xs) >= area_threshold
                    else 0.0
                ),
            )
            reasons = [
                reason
                for condition, reason in [
                    (support_ratio < support_threshold, "insufficient_observed_boundary_support"),
                    (competition_ratio > competition_threshold, "large_boundary_created_by_seed_competition"),
                    (effective_text_abstained, "name_node_contains_abstained_ocr_evidence"),
                ]
                if condition
            ]
            spaces.append(
                {
                    **common,
                    "boundary_support_ratio": round(support_ratio, 6),
                    "competition_boundary_ratio": round(competition_ratio, 6),
                    "confidence_uncalibrated": round(confidence, 6),
                    "abstained": support_ratio < support_threshold
                    or competition_ratio > competition_threshold,
                    "abstention_reasons": reasons,
                    "radial_boundary_observations": rays,
                }
            )
            continue

        if contract != "legacy_1_1":
            raise ValueError(f"Unsupported space contract: {contract!r}")
        observed = perimeter & observed_near
        synthetic_only = perimeter & synthetic_near & ~observed_near
        observed_ratio = float(observed.sum()) / perimeter_count
        synthetic_ratio = float(synthetic_only.sum()) / perimeter_count
        competition_ratio = float(competition.sum()) / perimeter_count
        unresolved_ratio = max(
            0.0, 1.0 - observed_ratio - synthetic_ratio - competition_ratio
        )
        observed_threshold = float(config_value(config, ("observed_boundary_abstention_below",), 0.50))
        synthetic_threshold = float(config_value(config, ("synthetic_boundary_abstention_above",), 0.30))
        competition_threshold = float(config_value(config, ("competition_boundary_abstention_above",), 0.25))
        reasons = [
            reason
            for condition, reason in [
                (
                    observed_ratio < observed_threshold,
                    f"observed_boundary_support_below_{observed_threshold:.2f}",
                ),
                (synthetic_ratio > synthetic_threshold, "large_boundary_support_from_temporary_gap_closure"),
                (competition_ratio > competition_threshold, "large_boundary_created_by_seed_competition"),
                (effective_text_abstained, "name_node_contains_abstained_ocr_evidence"),
            ]
            if condition
        ]
        area_threshold = int(config_value(config, ("confidence_large_area_min_px2",), 500))
        confidence = min(
            float(config_value(config, ("confidence_cap",), 0.93)),
            float(config_value(config, ("confidence_base",), 0.24))
            + float(config_value(config, ("confidence_observed_weight",), 0.48))
            * observed_ratio
            + float(config_value(config, ("confidence_synthetic_weight",), 0.10))
            * synthetic_ratio
            + (
                float(config_value(config, ("confidence_non_abstained_bonus",), 0.08))
                if not transcription_abstained
                else 0.0
            )
            + (
                float(config_value(config, ("confidence_large_area_bonus",), 0.07))
                if len(xs) >= area_threshold
                else 0.0
            ),
        )
        spaces.append(
            {
                **common,
                "boundary_composition": {
                    "observed_geometry_ratio": round(observed_ratio, 6),
                    "synthetic_gap_closure_ratio": round(synthetic_ratio, 6),
                    "seed_competition_ratio": round(competition_ratio, 6),
                    "unresolved_ratio": round(unresolved_ratio, 6),
                },
                "boundary_evidence": boundary_sources(
                    perimeter,
                    linework,
                    wall_bands,
                    line_ids,
                    band_ids,
                    evidence_config,
                ),
                "confidence_uncalibrated": round(confidence, 6),
                "abstained": bool(reasons),
                "abstention_reasons": reasons,
                "radial_boundary_observations": rays,
            }
        )
    return spaces


__all__ = ["build_spaces"]
