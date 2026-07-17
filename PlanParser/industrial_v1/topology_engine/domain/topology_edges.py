from __future__ import annotations

from typing import Any

import numpy as np

from .wavefront import config_value, is_legacy, nearest_free, shift_without_wrap


def _space_by_label(spaces: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for index, space in enumerate(spaces, 1):
        explicit = space.get("space_label_index")
        if explicit is None:
            try:
                explicit = int(str(space["id"]).rsplit("_", 1)[-1])
            except (KeyError, TypeError, ValueError):
                explicit = index
        result[int(explicit)] = space
    return result


def _label_contacts(labels: np.ndarray, legacy: bool) -> dict[tuple[int, int], int]:
    contacts: dict[tuple[int, int], int] = {}
    for dx, dy in ((1, 0), (0, 1)):
        shifted = (
            np.roll(labels, shift=(-dy, -dx), axis=(0, 1))
            if legacy
            else shift_without_wrap(labels, -dx, -dy)
        )
        mask = (labels > 0) & (shifted > 0) & (labels != shifted)
        for a, b in zip(labels[mask].tolist(), shifted[mask].tolist()):
            key = tuple(sorted((int(a), int(b))))
            contacts[key] = contacts.get(key, 0) + 1
    return contacts


def build_graph_edges(
    labels: np.ndarray,
    text_nodes: list[dict[str, Any]],
    spaces: list[dict[str, Any]],
    config: Any = None,
) -> list[dict[str, Any]]:
    """Build naming, optional assignment, adjacency and evidence edges."""

    edges: list[dict[str, Any]] = []
    for space in spaces:
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:03d}",
                "relation": "names_space_candidate",
                "from": space["name_text_node_id"],
                "to": space["id"],
                "status": "hypothesis",
            }
        )

    spaces_by_label = _space_by_label(spaces)
    assignment_policy = str(
        config_value(
            config,
            ("topology.text_assignment_policy", "text_assignment_policy"),
            "legacy_region1",
        )
    )
    if assignment_policy not in {"legacy_region1", "non_seed", "none"}:
        raise ValueError(f"Unsupported text assignment policy: {assignment_policy!r}")
    if assignment_policy != "none":
        max_radius = int(
            config_value(
                config,
                ("topology.nearest_free_max_radius_px", "nearest_free_max_radius_px"),
                60,
            )
        )
        for node in text_nodes:
            if node.get("role_hypothesis") == "space_name_seed":
                continue
            seed = nearest_free(node["center_crop_px"], labels > 0, max_radius=max_radius)
            if not seed:
                continue
            label = int(labels[seed[1], seed[0]])
            space = spaces_by_label.get(label)
            node["located_in_space_candidate_id"] = space["id"] if space else None
            if space:
                edges.append(
                    {
                        "id": f"edge_{len(edges) + 1:03d}",
                        "relation": "text_node_located_in_space_candidate",
                        "from": node["id"],
                        "to": space["id"],
                        "status": (
                            "geometric_assignment_role_unresolved"
                            if node.get("role_hypothesis") == "unresolved_text"
                            else "hypothesis"
                        ),
                    }
                )

    for (a, b), count in sorted(_label_contacts(labels, is_legacy(config)).items()):
        if a not in spaces_by_label or b not in spaces_by_label:
            continue
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:03d}",
                "relation": "candidate_topological_adjacency",
                "from": spaces_by_label[a]["id"],
                "to": spaces_by_label[b]["id"],
                "contact_length_px": count,
                "status": "competition_boundary_not_opening_proof",
            }
        )

    include_boundary = bool(
        config_value(
            config,
            ("topology.include_boundary_evidence_edges", "include_boundary_evidence_edges"),
            str(
                config_value(
                    config,
                    ("topology.space_contract", "space_contract"),
                    "legacy_1_1",
                )
            )
            == "legacy_1_1",
        )
    )
    if include_boundary:
        for space in spaces:
            for evidence in space.get("boundary_evidence", []):
                edges.append(
                    {
                        "id": f"edge_{len(edges) + 1:03d}",
                        "relation": "bounded_by_candidate_evidence",
                        "from": space["id"],
                        "to": evidence["source_id"],
                        "target_type": evidence["source_type"],
                        "support_pixels": evidence["support_pixels_near_space_boundary"],
                        "status": "observed_relation_not_building_semantics",
                    }
                )
    return edges


__all__ = ["build_graph_edges"]
