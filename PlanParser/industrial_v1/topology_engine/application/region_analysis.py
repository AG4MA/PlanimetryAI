from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .. import ENGINE_VERSION, TOPOLOGY_SCHEMA_VERSION
from ..barriers import build_barriers
from ..config import TopologyEngineConfig
from ..models import BarrierResult, CoordinateFrame
from ..text import adapt_text_payload
from ..topology import build_graph_edges, build_spaces, expand_from_text_nodes
from .contracts import JobContractError


@dataclass
class RegionComputation:
    region_id: str
    floor_id: str
    frame: CoordinateFrame
    config: TopologyEngineConfig
    text_nodes: list[dict[str, Any]]
    barriers: BarrierResult
    labels: np.ndarray
    seed_audit: list[dict[str, Any]]
    spaces: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    payload: dict[str, Any]


def topology_summary(
    nodes: Sequence[Mapping[str, Any]],
    spaces: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "text_node_count": len(nodes),
        "space_name_seed_count": sum(
            node.get("role_hypothesis") == "space_name_seed" for node in nodes
        ),
        "contained_object_label_count": sum(
            node.get("role_hypothesis") == "contained_object_label" for node in nodes
        ),
        "external_context_node_count": sum(
            node.get("role_hypothesis") == "external_context_label" for node in nodes
        ),
        "unresolved_text_node_count": sum(
            "unresolved" in str(node.get("role_hypothesis", "")) for node in nodes
        ),
        "semantic_role_abstained_node_count": sum(
            bool(node.get("semantic_role_abstained")) for node in nodes
        ),
        "space_candidate_count": len(spaces),
        "space_candidate_abstained_count": sum(
            bool(space.get("abstained")) for space in spaces
        ),
        "topology_edge_count": len(edges),
        "bounded_by_evidence_edge_count": sum(
            edge.get("relation") == "bounded_by_candidate_evidence" for edge in edges
        ),
    }


def _geometry_audit(
    barriers: BarrierResult, linework: Mapping[str, Any]
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "line_candidates": [dict(item) for item in barriers.line_audit],
        "band_candidates": [dict(item) for item in barriers.band_audit],
        "observed_barrier_pixels": int((barriers.raw_observed > 0).sum()),
        "observed_geometry_pixels_excluding_crop_boundary": int(
            (barriers.observed_geometry > 0).sum()
        ),
        "crop_boundary_pixels": int((barriers.crop_boundary > 0).sum()),
        "synthetic_gap_closure_pixels": int(
            (barriers.synthetic_closures > 0).sum()
        ),
        "effective_barrier_pixels": int((barriers.effective_barrier > 0).sum()),
    }
    line_summary = linework.get("summary", {})
    if isinstance(line_summary, Mapping):
        if "text_contaminated_candidate_count" in line_summary:
            audit["upstream_text_contaminated_line_count"] = int(
                line_summary["text_contaminated_candidate_count"]
            )
        if "retained_geometric_candidate_count" in line_summary:
            audit["upstream_retained_geometric_line_count"] = int(
                line_summary["retained_geometric_candidate_count"]
            )
    return audit


def _source_contract(
    source_descriptor: Mapping[str, Any],
    frame: CoordinateFrame,
    width: int,
    height: int,
) -> dict[str, Any]:
    source = dict(source_descriptor)
    source.update(
        {
            "width_px": width,
            "height_px": height,
            "bbox_page_px_xywh": list(frame.bbox_page_px_xywh),
            "coordinate_frame": {
                "document_id": frame.document_id,
                "page_id": frame.page_id,
                "region_id": frame.region_id,
                "convention": "integer pixels; XYXY half-open; XYWH extent",
            },
        }
    )
    return source


def _payload(
    *,
    config: TopologyEngineConfig,
    source: Mapping[str, Any],
    input_descriptors: Sequence[Mapping[str, Any]],
    text_nodes: list[dict[str, Any]],
    barriers: BarrierResult,
    seed_audit: list[dict[str, Any]],
    spaces: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    linework: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": TOPOLOGY_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "profile": config.profile,
        "status": "automatic_candidates_with_explicit_boundary_composition_not_human_approved",
        "source": dict(source),
        "inputs": [dict(item) for item in input_descriptors],
        "config_snapshot": config.to_dict(),
        "method": {
            "name": "text_anchored_geodesic_space_expansion_with_boundary_provenance",
            "text_geometry_separation": True,
            "expansion": "multi_source_four_connected_geodesic_wavefront",
            "boundary_composition": [
                "observed_geometry",
                "synthetic_gap_closure",
                "seed_competition",
                "unresolved",
            ],
            "text_assignment_policy": config.text_assignment_policy,
            "semantic_abstention_policy": config.semantic_abstention_policy,
            "composite_policy": config.composite_policy,
            "compatibility_mode": config.compatibility_mode,
            "confidence_calibrated": False,
        },
        "text_nodes": text_nodes,
        "geometry_barrier_audit": _geometry_audit(barriers, linework),
        "expansion_seed_audit": seed_audit,
        "space_candidates": spaces,
        "topology_edges": edges,
        "summary": topology_summary(text_nodes, spaces, edges),
        "machine_layers": {
            "observed_geometry": "observed_geometry_mask.png",
            "crop_boundary": "crop_boundary_mask.png",
            "raw_observed": "raw_observed_mask.png",
            "synthetic_closures": "synthetic_closures_mask.png",
            "effective_barrier": "effective_barrier_mask.png",
            "space_labels": "space_labels_u16.png",
        },
        "explicit_non_claims": [
            "OCR glyphs are not geometric building lines",
            "a normalized text value does not replace preserved raw OCR",
            "a text role hypothesis is not a validated semantic label",
            "a wavefront region is not a validated room",
            "temporary gap closures are not walls and do not prove doors",
            "competition boundaries are not observed physical boundaries",
            "topological contact does not prove a traversable opening",
            "walls, doors, windows, property membership, scale and north are not inferred",
            "no human approval or correction has been applied",
        ],
    }


def compute_region(
    *,
    region_id: str,
    floor_id: str,
    source_bgr: np.ndarray,
    frame: CoordinateFrame,
    text_payload: Mapping[str, Any],
    text_adapter: str,
    linework: Mapping[str, Any],
    wall_bands: Mapping[str, Any],
    config: TopologyEngineConfig,
    source_descriptor: Mapping[str, Any],
    input_descriptors: Sequence[Mapping[str, Any]],
) -> RegionComputation:
    """Analyze one region without filesystem writes or implicit paths."""

    if source_bgr.ndim != 3 or source_bgr.shape[2] != 3:
        raise JobContractError(f"Invalid BGR raster for {region_id}")
    height, width = source_bgr.shape[:2]
    if (width, height) != (frame.width_px, frame.height_px):
        raise JobContractError(
            f"Raster/coordinate-frame size mismatch for {region_id}: "
            f"raster={width}x{height}, frame={frame.width_px}x{frame.height_px}"
        )

    text_nodes = adapt_text_payload(text_payload, text_adapter, width, config)
    barriers = build_barriers(width, height, linework, wall_bands, text_nodes, config)
    labels, seed_audit = expand_from_text_nodes(
        barriers.effective_barrier, text_nodes, config
    )
    spaces = build_spaces(
        labels,
        barriers.effective_barrier,
        barriers.raw_observed,
        barriers.synthetic_closures,
        text_nodes,
        frame.offset_page_px,
        linework,
        wall_bands,
        barriers.used_line_ids,
        barriers.used_band_ids,
        config,
    )
    edges = build_graph_edges(labels, text_nodes, spaces, config)
    for node in text_nodes:
        page_x, page_y = frame.crop_to_page(node["center_crop_px"])
        node["center_page_px"] = [round(page_x, 3), round(page_y, 3)]

    payload = _payload(
        config=config,
        source=_source_contract(source_descriptor, frame, width, height),
        input_descriptors=input_descriptors,
        text_nodes=text_nodes,
        barriers=barriers,
        seed_audit=seed_audit,
        spaces=spaces,
        edges=edges,
        linework=linework,
    )
    return RegionComputation(
        region_id=region_id,
        floor_id=floor_id,
        frame=frame,
        config=config,
        text_nodes=text_nodes,
        barriers=barriers,
        labels=labels,
        seed_audit=seed_audit,
        spaces=spaces,
        edges=edges,
        payload=payload,
    )


__all__ = ["RegionComputation", "compute_region", "topology_summary"]
