from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..config import TopologyEngineConfig
from .text_composites import apply_vano_scala_composite
from .text_normalization import normalize_text, role_from_values


def _bbox_center(bbox: list[float]) -> list[float]:
    return [
        round((bbox[0] + bbox[2]) / 2.0, 3),
        round((bbox[1] + bbox[3]) / 2.0, 3),
    ]


def _ensemble_alternatives(alignment: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    consensus = alignment.get("decision", {}).get("consensus") or {}
    if consensus.get("text_normalized"):
        values.append(str(consensus["text_normalized"]))
    alternatives = alignment.get("raw_text_alternatives", {})
    for engine in ("ppocrv5", "doctr"):
        value = alternatives.get(engine, {}).get("joined_text_raw")
        if value and value not in values:
            values.append(str(value))
    return values


def _industrial_alternatives(item: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    consensus = item.get("decision", {}).get("consensus_text")
    if consensus:
        values.append(str(consensus))
    for alternative in item.get("raw_alternatives", []):
        value = alternative.get("text_raw")
        if value and value not in values:
            values.append(str(value))
    return values


def _adapt_ocr_ensemble(
    payload: Mapping[str, Any],
    image_width: int,
    config: Any,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for alignment in payload.get("alignments", []):
        raw_bbox = alignment["spatial_audit"]["alignment_bbox_xyxy"]
        bbox = [float(value) for value in raw_bbox]
        values = _ensemble_alternatives(alignment)
        role, canonical_name, reasons, role_abstained = role_from_values(
            values,
            image_width=image_width,
            bbox=bbox,
            adapter_name="ocr_ensemble_v1",
            source_role=None,
            config=config,
        )
        decision = alignment.get("decision", {})
        transcription_abstained = bool(decision.get("abstained"))
        nodes.append(
            {
                "id": "",
                "source_alignment_ids": [alignment["id"]],
                "raw_text_alternatives": values,
                "bbox_crop_px_xyxy": bbox,
                "center_crop_px": _bbox_center(bbox),
                "role_hypothesis": role,
                "canonical_space_name_hypothesis": canonical_name,
                "role_reasons": reasons,
                "ocr_classification": decision.get("classification"),
                "ocr_abstained": transcription_abstained,
                "transcription_abstained": transcription_abstained,
                "semantic_role_abstained": role_abstained,
                "composite": False,
            }
        )
    return nodes


def _adapt_industrial_text_nodes(
    payload: Mapping[str, Any],
    image_width: int,
    config: Any,
) -> list[dict[str, Any]]:
    del image_width
    nodes: list[dict[str, Any]] = []
    for item in payload.get("text_nodes", []):
        bbox = [float(value) for value in item["bbox_pixels"]]
        values = _industrial_alternatives(item)
        source_role = item.get("candidate_role") or {}
        role, canonical_name, reasons, role_abstained = role_from_values(
            values,
            image_width=0,
            bbox=bbox,
            adapter_name="industrial_text_nodes_v1",
            source_role=source_role,
            config=config,
        )
        decision = item.get("decision", {})
        transcription_abstained = bool(decision.get("abstained"))
        nodes.append(
            {
                "id": item["node_id"],
                "source_text_node_ids": [item["node_id"]],
                "raw_text_alternatives": values,
                "bbox_crop_px_xyxy": bbox,
                "center_crop_px": [float(value) for value in item["center_pixels"]],
                "role_hypothesis": role,
                "canonical_space_name_hypothesis": canonical_name,
                "role_reasons": reasons + list(source_role.get("evidence", [])),
                "source_candidate_role": deepcopy(source_role),
                "ocr_classification": decision.get("classification"),
                "ocr_abstained": transcription_abstained,
                "transcription_abstained": transcription_abstained,
                "semantic_role_abstained": role_abstained,
                "composite": False,
            }
        )
    return nodes


def _adapter_name(adapter: Any) -> str:
    if isinstance(adapter, str):
        raw_name = adapter
    else:
        raw_name = str(getattr(adapter, "name", adapter))
    normalized = normalize_text(raw_name).replace("-", "_").replace(" ", "_")
    aliases = {
        "ocr_ensemble": "ocr_ensemble_v1",
        "ocr_ensemble_v1": "ocr_ensemble_v1",
        "region_001": "ocr_ensemble_v1",
        "industrial_text_nodes": "industrial_text_nodes_v1",
        "industrial_text_nodes_v1": "industrial_text_nodes_v1",
        "text_nodes_v1": "industrial_text_nodes_v1",
        "region_002": "industrial_text_nodes_v1",
    }
    if normalized not in aliases:
        raise ValueError(f"Unsupported text adapter: {adapter!r}")
    return aliases[normalized]


def adapt_text_payload(
    payload: Mapping[str, Any],
    adapter: str | Callable[..., list[dict[str, Any]]] | Any,
    image_width: int,
    config: TopologyEngineConfig | Mapping[str, Any] | object | None,
) -> list[dict[str, Any]]:
    """Adapt supported OCR payloads to topology text nodes."""

    if callable(adapter) and not isinstance(adapter, str):
        nodes = deepcopy(adapter(payload, image_width, config))
        adapter_name = str(getattr(adapter, "name", "custom"))
    elif hasattr(adapter, "adapt_text_payload"):
        nodes = deepcopy(adapter.adapt_text_payload(payload, image_width, config))
        adapter_name = str(getattr(adapter, "name", "custom"))
    else:
        adapter_name = _adapter_name(adapter)
        if adapter_name == "ocr_ensemble_v1":
            nodes = _adapt_ocr_ensemble(payload, image_width, config)
        else:
            nodes = _adapt_industrial_text_nodes(payload, image_width, config)

    for node in nodes:
        transcription = bool(
            node.get("transcription_abstained", node.get("ocr_abstained", False))
        )
        semantic = bool(node.get("semantic_role_abstained", False))
        node["transcription_abstained"] = transcription
        node["semantic_role_abstained"] = semantic
        node.setdefault("ocr_abstained", transcription)

    nodes = apply_vano_scala_composite(nodes, adapter_name, config)
    nodes.sort(key=lambda item: (item["center_crop_px"][1], item["center_crop_px"][0]))
    if adapter_name == "ocr_ensemble_v1":
        for index, node in enumerate(nodes, 1):
            node["id"] = f"text_node_{index:03d}"
    return nodes


__all__ = ["adapt_text_payload"]
