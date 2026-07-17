from __future__ import annotations

from copy import deepcopy

import numpy as np

from industrial_v1.topology_engine.text import adapt_text_payload
from industrial_v1.topology_engine.topology import (
    build_graph_edges,
    build_spaces,
    expand_from_text_nodes,
)


def industrial_node(
    node_id: str,
    text: str,
    bbox: list[float],
    *,
    role: str = "unresolved",
    role_abstained: bool = True,
    transcription_abstained: bool = False,
    alternatives: list[str] | None = None,
) -> dict:
    raw_values = alternatives or [text]
    return {
        "node_id": node_id,
        "bbox_pixels": bbox,
        "center_pixels": [
            (bbox[0] + bbox[2]) / 2.0,
            (bbox[1] + bbox[3]) / 2.0,
        ],
        "raw_alternatives": [
            {
                "engine": f"engine_{index}",
                "source_refs": [f"source_{node_id}_{index}"],
                "text_raw": value,
                "confidence_raw": 0.99,
            }
            for index, value in enumerate(raw_values, 1)
        ],
        "decision": {
            "classification": (
                "conflict_or_ambiguous" if transcription_abstained else "consensus"
            ),
            "consensus_text": None if transcription_abstained else text,
            "abstained": transcription_abstained,
        },
        "candidate_role": {
            "classification": role,
            "abstained": role_abstained,
            "evidence": ["synthetic_test_role_evidence"],
        },
    }


def test_industrial_adapter_keeps_transcription_and_role_abstention_separate() -> None:
    payload = {
        "text_nodes": [
            industrial_node(
                "text_node_0001",
                "dis.",
                [10, 10, 40, 24],
                role="distribution_space_label_candidate",
                role_abstained=True,
            ),
            industrial_node(
                "text_node_0002",
                "altra uiu",
                [70, 10, 130, 24],
                role="adjacent_unit_context_candidate",
                role_abstained=False,
            ),
        ]
    }

    nodes = adapt_text_payload(
        payload,
        "industrial_text_nodes_v1",
        image_width=160,
        config={"composite_enabled": False},
    )

    distribution = next(node for node in nodes if "dis." in node["raw_text_alternatives"])
    context = next(node for node in nodes if "altra uiu" in node["raw_text_alternatives"])
    assert distribution["role_hypothesis"] == "space_name_seed"
    assert distribution["canonical_space_name_hypothesis"] == "disimpegno"
    assert distribution["transcription_abstained"] is False
    assert distribution["semantic_role_abstained"] is True
    assert context["role_hypothesis"] == "external_context_label"
    assert context["canonical_space_name_hypothesis"] is None


def test_vano_scala_composite_supports_replacement_and_additive_policies() -> None:
    payload = {
        "text_nodes": [
            industrial_node("text_node_0007", "vano", [10, 20, 50, 36]),
            industrial_node(
                "text_node_0008",
                "cala",
                [10, 34, 55, 52],
                transcription_abstained=True,
                alternatives=["cala", "scala"],
            ),
        ]
    }

    replacement = adapt_text_payload(
        payload,
        "industrial_text_nodes_v1",
        image_width=100,
        config={"composite_policy": "legacy_replacement"},
    )
    additive = adapt_text_payload(
        payload,
        "industrial_text_nodes_v1",
        image_width=100,
        config={"composite_policy": "additive"},
    )

    assert len(replacement) == 1
    composite = replacement[0]
    assert composite["id"] == "text_node_composite_vano_scala"
    assert composite["canonical_space_name_hypothesis"] == "vano scala"
    assert composite["composite_member_ids"] == ["text_node_0007", "text_node_0008"]
    assert composite["transcription_abstained"] is True
    assert composite["semantic_role_abstained"] is True
    assert len(additive) == 3
    assert sum(node["composite"] for node in additive) == 1
    assert {node["id"] for node in additive if not node["composite"]} == {
        "text_node_0007",
        "text_node_0008",
    }


def test_geodesic_expansion_stops_at_observed_barrier() -> None:
    barrier = np.zeros((9, 13), dtype=np.uint8)
    barrier[[0, -1], :] = 255
    barrier[:, [0, -1]] = 255
    barrier[:, 6] = 255
    nodes = [
        {
            "id": "text_node_left",
            "center_crop_px": [3.0, 4.0],
            "role_hypothesis": "space_name_seed",
        },
        {
            "id": "text_node_right",
            "center_crop_px": [9.0, 4.0],
            "role_hypothesis": "space_name_seed",
        },
    ]

    labels, audit = expand_from_text_nodes(barrier, nodes, {"compatibility_mode": "legacy_v1"})

    assert labels[4, 3] == 1
    assert labels[4, 9] == 2
    assert np.all(labels[:, 6] == 0)
    assert set(np.unique(labels[:, 1:6])) <= {0, 1}
    assert set(np.unique(labels[:, 7:12])) <= {0, 2}
    assert [item["space_label_index"] for item in audit] == [1, 2]


def test_graph_reports_seed_competition_adjacency_without_wraparound() -> None:
    labels = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [1, 1, 2, 2],
        ],
        dtype=np.int32,
    )
    nodes = [
        {"id": "text_a", "role_hypothesis": "space_name_seed", "center_crop_px": [0, 1]},
        {"id": "text_b", "role_hypothesis": "space_name_seed", "center_crop_px": [3, 1]},
    ]
    spaces = [
        {"id": "space_candidate_001", "name_text_node_id": "text_a"},
        {"id": "space_candidate_002", "name_text_node_id": "text_b"},
    ]

    edges = build_graph_edges(
        labels,
        nodes,
        spaces,
        {
            "compatibility_mode": "modern",
            "text_assignment_policy": "none",
            "include_boundary_evidence_edges": False,
        },
    )

    adjacency = [edge for edge in edges if edge["relation"] == "candidate_topological_adjacency"]
    assert len(adjacency) == 1
    assert adjacency[0]["from"] == "space_candidate_001"
    assert adjacency[0]["to"] == "space_candidate_002"
    assert adjacency[0]["contact_length_px"] == 3


def test_text_assignment_policy_can_disable_context_to_space_edges() -> None:
    labels = np.ones((5, 5), dtype=np.int16)
    spaces = [{"id": "space_candidate_001", "name_text_node_id": "name"}]
    nodes = [
        {"id": "name", "role_hypothesis": "space_name_seed", "center_crop_px": [2, 2]},
        {"id": "context", "role_hypothesis": "external_context_label", "center_crop_px": [4, 4]},
    ]

    assigned = build_graph_edges(
        labels,
        deepcopy(nodes),
        spaces,
        {
            "compatibility_mode": "legacy_v1",
            "text_assignment_policy": "legacy_region1",
            "include_boundary_evidence_edges": False,
        },
    )
    unassigned = build_graph_edges(
        labels,
        deepcopy(nodes),
        spaces,
        {
            "compatibility_mode": "legacy_v1",
            "text_assignment_policy": "none",
            "include_boundary_evidence_edges": False,
        },
    )

    assert any(edge["relation"] == "text_node_located_in_space_candidate" for edge in assigned)
    assert not any(edge["relation"] == "text_node_located_in_space_candidate" for edge in unassigned)


def test_space_abstention_policy_preserves_legacy_and_future_behavior() -> None:
    raw = np.zeros((9, 9), dtype=np.uint8)
    raw[[0, -1], :] = 255
    raw[:, [0, -1]] = 255
    barrier = raw.copy()
    closures = np.zeros_like(raw)
    base_node = {
        "id": "text_node_001",
        "center_crop_px": [4.0, 4.0],
        "role_hypothesis": "space_name_seed",
        "canonical_space_name_hypothesis": "disimpegno",
        "transcription_abstained": False,
        "semantic_role_abstained": True,
        "ocr_abstained": False,
    }

    legacy_nodes = [deepcopy(base_node)]
    legacy_labels, _ = expand_from_text_nodes(barrier, legacy_nodes)
    legacy_spaces = build_spaces(
        legacy_labels,
        barrier,
        raw,
        closures,
        legacy_nodes,
        config={
            "compatibility_mode": "legacy_v1",
            "semantic_abstention_policy": "transcription_only",
        },
    )

    future_nodes = [deepcopy(base_node)]
    future_labels, _ = expand_from_text_nodes(
        barrier, future_nodes, {"compatibility_mode": "modern"}
    )
    future_spaces = build_spaces(
        future_labels,
        barrier,
        raw,
        closures,
        future_nodes,
        config={
            "compatibility_mode": "modern",
            "semantic_abstention_policy": "transcription_or_role",
        },
    )

    assert legacy_spaces[0]["abstained"] is False
    assert future_spaces[0]["abstained"] is True
    assert "name_node_contains_abstained_ocr_evidence" in future_spaces[0]["abstention_reasons"]
