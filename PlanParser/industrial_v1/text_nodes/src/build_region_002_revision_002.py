from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PLANPARSER_ROOT = HERE.parents[2]
SOURCE_SCRIPT = HERE / "build_region_002_revision_001.py"
PREDECESSOR = (
    PLANPARSER_ROOT
    / "industrial_v1"
    / "text_nodes"
    / "artifacts"
    / "scheda_catastale"
    / "region_002"
    / "revision_001"
)
OUTPUT = PREDECESSOR.parent / "revision_002"


def load_support() -> Any:
    spec = importlib.util.spec_from_file_location("text_nodes_region002_r001", SOURCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(SOURCE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relation_rank(metrics: dict[str, float]) -> tuple[float, float, float]:
    return (
        metrics["intersection_over_smaller"],
        metrics["intersection_over_union"],
        -metrics["center_distance_by_height"],
    )


def same_text_line(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_box = a["bbox_pixels"]
    b_box = b["bbox_pixels"]
    a_height = max(1.0, a_box[3] - a_box[1])
    b_height = max(1.0, b_box[3] - b_box[1])
    center_delta_y = abs(a["center_pixels"][1] - b["center_pixels"][1])
    return center_delta_y <= 0.45 * max(a_height, b_height)


def build_nodes_one_to_one(
    support: Any,
    paddle: list[dict[str, Any]],
    doctr: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unmatched_doctr = set(range(len(doctr)))
    nodes: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    paddle_order = sorted(
        range(len(paddle)),
        key=lambda index: (
            paddle[index]["center_pixels"][1],
            paddle[index]["center_pixels"][0],
        ),
    )
    for pp_index in paddle_order:
        pp = paddle[pp_index]
        candidates: list[tuple[int, dict[str, float]]] = []
        for dt_index in sorted(unmatched_doctr):
            metrics = support.bbox_metrics(pp["bbox_pixels"], doctr[dt_index]["bbox_pixels"])
            if metrics["intersection_over_smaller"] >= support.PAIR_INTERSECTION_OVER_SMALLER:
                candidates.append((dt_index, metrics))
        candidates.sort(key=lambda item: relation_rank(item[1]), reverse=True)

        selected_indices: list[int] = []
        if candidates:
            primary_index = candidates[0][0]
            selected_indices.append(primary_index)
            primary = doctr[primary_index]
            for dt_index, _ in candidates[1:]:
                candidate = doctr[dt_index]
                if same_text_line(primary, candidate):
                    selected_indices.append(dt_index)
            selected_indices.sort(key=lambda index: doctr[index]["center_pixels"][0])
            for index in selected_indices:
                unmatched_doctr.remove(index)

        dt_group = [doctr[index] for index in selected_indices]
        pp_text = pp["text_raw"]
        dt_text = " ".join(item["text_raw"] for item in dt_group) if dt_group else None
        norm_pp = support.normalize_text(pp_text)
        norm_dt = support.normalize_text(dt_text or "")
        exact = bool(dt_group) and norm_pp == norm_dt
        all_confident = (
            pp["confidence_raw"] >= support.ENGINE_CONFIDENCE_FLOOR
            and bool(dt_group)
            and all(
                item["confidence_raw"] >= support.ENGINE_CONFIDENCE_FLOOR
                for item in dt_group
            )
        )
        consensus = exact and all_confident and not pp["abstention"]["abstained"] and all(
            not item["abstention"]["abstained"] for item in dt_group
        )
        if consensus:
            classification = "consensus"
            reasons = [
                "exact normalized transcription",
                "one-to-one or same-baseline segmentation alignment",
            ]
        elif dt_group:
            classification = "conflict_or_ambiguous"
            reasons = [
                "spatially paired engines disagree or confidence requirement failed"
            ]
        else:
            classification = "single_engine"
            reasons = ["no unassigned spatially overlapping docTR observation"]

        boxes = [pp["bbox_pixels"]] + [item["bbox_pixels"] for item in dt_group]
        box = support.union_bbox(boxes)
        alternatives: list[dict[str, Any]] = [
            {
                "engine": "paddle",
                "source_refs": [pp["source_ref"]],
                "text_raw": pp_text,
                "confidence_raw": pp["confidence_raw"],
            }
        ]
        if dt_group:
            alternatives.append(
                {
                    "engine": "doctr",
                    "source_refs": [item["source_ref"] for item in dt_group],
                    "text_raw": dt_text,
                    "confidence_raw": [item["confidence_raw"] for item in dt_group],
                }
            )
        node = {
            "node_id": f"text_node_{len(nodes) + 1:04d}",
            "node_type": "text_observation",
            "geometry_separation": {
                "stored_as_geometry_primitive": False,
                "line_or_wall_membership_assigned": False,
                "future_relation_target": "spatial_context_or_space_node",
            },
            "bbox_pixels": box,
            "center_pixels": support.bbox_center(box),
            "raw_alternatives": alternatives,
            "decision": {
                "classification": classification,
                "consensus_text": pp_text if consensus else None,
                "abstained": not consensus,
                "reasons": reasons,
                "normalized_exact": exact,
                "fuzzy_similarity": round(
                    support.SequenceMatcher(None, norm_pp, norm_dt).ratio(), 6
                )
                if dt_group
                else None,
            },
            "candidate_role": support.candidate_role(pp_text, consensus),
            "relations": [],
        }
        nodes.append(node)
        metric_by_index = {index: metrics for index, metrics in candidates}
        audit.append(
            {
                "paddle_ref": pp["source_ref"],
                "doctr_refs": [item["source_ref"] for item in dt_group],
                "selected_pair_metrics": [metric_by_index[index] for index in selected_indices],
                "same_baseline_grouping_used": len(selected_indices) > 1,
                "node_id": node["node_id"],
            }
        )

    for dt_index in sorted(unmatched_doctr):
        item = doctr[dt_index]
        box = item["bbox_pixels"]
        nodes.append(
            {
                "node_id": f"text_node_{len(nodes) + 1:04d}",
                "node_type": "text_observation",
                "geometry_separation": {
                    "stored_as_geometry_primitive": False,
                    "line_or_wall_membership_assigned": False,
                    "future_relation_target": "spatial_context_or_space_node",
                },
                "bbox_pixels": box,
                "center_pixels": support.bbox_center(box),
                "raw_alternatives": [
                    {
                        "engine": "doctr",
                        "source_refs": [item["source_ref"]],
                        "text_raw": item["text_raw"],
                        "confidence_raw": item["confidence_raw"],
                    }
                ],
                "decision": {
                    "classification": "single_engine",
                    "consensus_text": None,
                    "abstained": True,
                    "reasons": ["no unassigned spatially overlapping PaddleOCR observation"],
                    "normalized_exact": False,
                    "fuzzy_similarity": None,
                },
                "candidate_role": support.candidate_role(item["text_raw"], False),
                "relations": [],
            }
        )
    return nodes, audit


def main() -> None:
    support = load_support()
    if OUTPUT.exists():
        raise FileExistsError(f"immutable output revision exists: {OUTPUT}")
    paddle_path = PREDECESSOR / "paddle_raw.json"
    doctr_path = PREDECESSOR / "doctr_raw.json"
    predecessor_nodes = PREDECESSOR / "text_nodes.json"
    for path in (paddle_path, doctr_path, predecessor_nodes, support.SOURCE):
        if not path.is_file():
            raise FileNotFoundError(path)
    paddle_payload = json.loads(paddle_path.read_text(encoding="utf-8"))
    doctr_payload = json.loads(doctr_path.read_text(encoding="utf-8"))
    nodes, audit = build_nodes_one_to_one(
        support, paddle_payload["records"], doctr_payload["records"]
    )
    classifications = [node["decision"]["classification"] for node in nodes]
    counts = {
        "total": len(nodes),
        "consensus": classifications.count("consensus"),
        "conflict_or_ambiguous": classifications.count("conflict_or_ambiguous"),
        "single_engine": classifications.count("single_engine"),
        "role_candidates": sum(not node["candidate_role"]["abstained"] for node in nodes),
        "role_abstained": sum(node["candidate_role"]["abstained"] for node in nodes),
    }
    payload = {
        "schema_version": "planparser.industrial_v1.text_nodes.v1",
        "revision": "revision_002",
        "created_at_utc": support.utc_now(),
        "status": "completed_conservative_two_engine_alignment",
        "scope": {
            "document": "scheda_catastale",
            "region": "region_002",
            "coordinate_space": "region_002_crop_pixels",
            "width_px": 674,
            "height_px": 729,
        },
        "predecessor": {
            "revision": "revision_001",
            "path": predecessor_nodes.as_posix(),
            "sha256": support.sha256_file(predecessor_nodes),
            "preserved_immutable": True,
            "change": "replace many-to-one vertical over-grouping with one-to-one pairing plus same-baseline segmentation grouping",
        },
        "architecture": {
            "node_type": "text_observation",
            "separate_from_geometry_graph": True,
            "line_or_wall_membership_assigned": False,
            "intended_next_relation": "text_node_to_surrounding_space",
        },
        "inputs": {
            "paddle_raw": {"path": paddle_path.as_posix(), "sha256": support.sha256_file(paddle_path)},
            "doctr_raw": {"path": doctr_path.as_posix(), "sha256": support.sha256_file(doctr_path)},
            "source_sha256": support.sha256_file(support.SOURCE),
        },
        "policy": {
            "spatial_alignment_precedes_text_comparison": True,
            "one_to_one_pairing_default": True,
            "multiple_words_grouped_only_on_same_baseline": True,
            "consensus_requires_exact_normalized_text_and_confidence_floor": True,
            "all_non_consensus_nodes_abstain": True,
            "candidate_roles_are_not_final_semantics": True,
        },
        "counts": counts,
        "text_nodes": nodes,
        "alignment_assignment_audit": audit,
        "limits": [
            "consensus is engine agreement, not ground truth",
            "no geometry or room containment relation is asserted",
            "candidate roles are lexical candidates, never final semantics",
            "no human review or correction was used",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    overlay_bytes = support.render_nodes(support.SOURCE, nodes, counts)
    support.write_bytes_exclusive(OUTPUT / "text_nodes.json", json_bytes)
    support.write_bytes_exclusive(OUTPUT / "text_nodes_overlay.png", overlay_bytes)
    manifest = {
        "schema_version": "planparser.industrial_v1.text_nodes.artifact_manifest.v1",
        "revision": "revision_002",
        "created_at_utc": support.utc_now(),
        "generator": {"path": Path(__file__).resolve().as_posix(), "sha256": support.sha256_file(Path(__file__).resolve())},
        "source_raw_artifacts_reused_without_modification": True,
        "outputs": {
            "text_nodes.json": {"bytes": len(json_bytes), "sha256": support.sha256_bytes(json_bytes)},
            "text_nodes_overlay.png": {"bytes": len(overlay_bytes), "sha256": support.sha256_bytes(overlay_bytes)},
        },
        "counts": counts,
        "write_policy": {"exclusive_create": True, "existing_artifacts_modified": False},
    }
    support.write_json_exclusive(OUTPUT / "artifact_manifest.json", manifest)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
