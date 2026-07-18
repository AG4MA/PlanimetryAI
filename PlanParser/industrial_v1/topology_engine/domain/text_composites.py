from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from .text_normalization import first_config_value, normalize_text


def _find_node(
    nodes: list[dict[str, Any]],
    accepted: set[str],
) -> dict[str, Any] | None:
    for node in nodes:
        alternatives = node["raw_text_alternatives"]
        if any(normalize_text(value) in accepted for value in alternatives):
            return node
    return None


def apply_vano_scala_composite(
    nodes: list[dict[str, Any]],
    adapter_name: str,
    config: Any,
) -> list[dict[str, Any]]:
    enabled = bool(
        first_config_value(
            config,
            ("text.composite_enabled", "composite_enabled"),
            True,
        )
    )
    if not enabled:
        return nodes
    max_distance = float(
        first_config_value(
            config,
            ("text.composite_max_distance_px", "composite_max_distance_px"),
            80.0,
        )
    )
    policy = str(
        first_config_value(
            config,
            ("text.composite_policy", "composite_policy"),
            "legacy_replacement",
        )
    )
    if policy not in {"legacy_replacement", "additive"}:
        raise ValueError(f"Unsupported composite policy: {policy!r}")

    vano = _find_node(nodes, {"vano"})
    scala = _find_node(nodes, {"scala", "cala"})
    if not vano or not scala:
        return nodes
    distance = math.dist(vano["center_crop_px"], scala["center_crop_px"])
    if distance > max_distance:
        return nodes

    vano_bbox = vano["bbox_crop_px_xyxy"]
    scala_bbox = scala["bbox_crop_px_xyxy"]
    x1 = min(vano_bbox[0], scala_bbox[0])
    y1 = min(vano_bbox[1], scala_bbox[1])
    x2 = max(vano_bbox[2], scala_bbox[2])
    y2 = max(vano_bbox[3], scala_bbox[3])
    source_key = (
        "source_alignment_ids"
        if adapter_name == "ocr_ensemble_v1"
        else "source_text_node_ids"
    )
    source_ids = list(vano.get(source_key, [])) + list(scala.get(source_key, []))
    transcription_abstained = bool(
        vano.get("transcription_abstained")
        or scala.get("transcription_abstained")
    )
    role_abstained = bool(
        vano.get("semantic_role_abstained")
        or scala.get("semantic_role_abstained")
    )
    raw_values = (
        ["vano scala"]
        if adapter_name == "ocr_ensemble_v1"
        else ["vano", "cala", "scala"]
    )
    composite_reasons = (
        ["spatially_clustered_text_nodes", f"center_distance_px:{distance:.3f}"]
        if adapter_name == "ocr_ensemble_v1"
        else [
            "spatially_clustered_vano_and_scala_nodes",
            "scala_reading_preserved_as_cala_vs_scala_conflict",
        ]
    )
    composite: dict[str, Any] = {
        "id": (
            ""
            if adapter_name == "ocr_ensemble_v1"
            else "text_node_composite_vano_scala"
        ),
        source_key: source_ids,
        "raw_text_alternatives": raw_values,
        "bbox_crop_px_xyxy": [x1, y1, x2, y2],
        "center_crop_px": [
            round((x1 + x2) / 2.0, 3),
            round((y1 + y2) / 2.0, 3),
        ],
        "role_hypothesis": "space_name_seed",
        "canonical_space_name_hypothesis": "vano scala",
        "role_reasons": composite_reasons,
        "ocr_classification": (
            "composite_mixed_evidence"
            if adapter_name == "ocr_ensemble_v1"
            else "composite_contains_conflict"
        ),
        "ocr_abstained": transcription_abstained,
        "transcription_abstained": transcription_abstained,
        "semantic_role_abstained": role_abstained,
        "composite": True,
        "composite_member_ids": source_ids,
        "composite_policy": policy,
    }
    if adapter_name == "industrial_text_nodes_v1":
        composite["source_candidate_role"] = [
            deepcopy(vano.get("source_candidate_role")),
            deepcopy(scala.get("source_candidate_role")),
        ]

    result = list(nodes)
    if policy == "legacy_replacement":
        result = [node for node in result if node is not vano and node is not scala]
    else:
        for member in (vano, scala):
            memberships = member.setdefault("composite_memberships", [])
            memberships.append(composite["id"] or "vano_scala")
    result.append(composite)
    return result


__all__ = ["apply_vano_scala_composite"]
