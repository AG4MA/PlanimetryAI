from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Mapping, Sequence
from .ids import (
    GRAPH_SCHEMA_VERSION,
    GraphContractError,
    edge_id,
    evidence_type,
    node_id,
    required_id,
)
from .validator import validate_document_graph

def _audit_lookup(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    audit = payload.get("geometry_barrier_audit", {})
    if not isinstance(audit, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key in ("line_candidates", "band_candidates"):
        values = audit.get(key, [])
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for item in values:
            if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                result[item["id"]] = copy.deepcopy(dict(item))
    return result


def _collect_evidence(
    payload: Mapping[str, Any], spaces: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    evidence: dict[str, str] = {}

    def register(local_id: Any, declared_type: Any = None) -> None:
        if not isinstance(local_id, str) or not local_id:
            raise GraphContractError("Boundary evidence IDs must be non-empty strings")
        current_type = evidence_type(
            local_id, declared_type if isinstance(declared_type, str) else None
        )
        previous = evidence.get(local_id)
        if previous is not None and previous != current_type:
            raise GraphContractError(
                f"Conflicting evidence types for {local_id}: {previous} vs {current_type}"
            )
        evidence[local_id] = current_type

    for space in spaces:
        boundary = space.get("boundary_evidence", [])
        if not isinstance(boundary, Sequence) or isinstance(boundary, (str, bytes)):
            raise GraphContractError("space boundary_evidence must be a sequence")
        for item in boundary:
            if not isinstance(item, Mapping):
                raise GraphContractError("Malformed boundary evidence record")
            register(item.get("source_id"), item.get("source_type"))

    topology_edges = payload.get("topology_edges", [])
    if not isinstance(topology_edges, Sequence) or isinstance(
        topology_edges, (str, bytes)
    ):
        raise GraphContractError("topology_edges must be a sequence")
    for topology_edge in topology_edges:
        if not isinstance(topology_edge, Mapping):
            raise GraphContractError("Malformed topology edge")
        for endpoint in (topology_edge.get("from"), topology_edge.get("to")):
            if isinstance(endpoint, str) and endpoint.startswith(("line_", "band_")):
                register(endpoint, topology_edge.get("target_type"))
    return evidence


def _validate_inputs(
    floor_units: Sequence[Mapping[str, Any]],
    regional_payloads: Mapping[str, Mapping[str, Any]],
    region_to_floor: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(floor_units, Sequence) or isinstance(floor_units, (str, bytes)):
        raise GraphContractError("floor_units must be a sequence")
    if not isinstance(regional_payloads, Mapping) or not regional_payloads:
        raise GraphContractError("regional_payloads must be a non-empty mapping")
    if not isinstance(region_to_floor, Mapping):
        raise GraphContractError("region_to_floor must be a mapping")
    floor_records: dict[str, dict[str, Any]] = {}
    for raw_floor in floor_units:
        if not isinstance(raw_floor, Mapping):
            raise GraphContractError("Malformed floor-unit record")
        floor_id = required_id(raw_floor.get("id"), "floor id")
        if floor_id in floor_records:
            raise GraphContractError(f"Duplicate floor id: {floor_id}")
        floor_records[floor_id] = copy.deepcopy(dict(raw_floor))
    if set(region_to_floor) != set(regional_payloads):
        raise GraphContractError(
            "region_to_floor keys must exactly match regional_payloads keys"
        )
    for region_id, floor_id in region_to_floor.items():
        required_id(region_id, "region id")
        if floor_id not in floor_records:
            raise GraphContractError(
                f"Region {region_id} references unknown floor: {floor_id}"
            )
    return floor_records


def aggregate_document_graph(
    *,
    document_id: str,
    page_id: str,
    floor_units: Sequence[Mapping[str, Any]],
    regional_payloads: Mapping[str, Mapping[str, Any]],
    region_to_floor: Mapping[str, str],
    page_attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a closed document graph without mutating supplied payloads."""

    document_id = required_id(document_id, "document_id")
    page_id = required_id(page_id, "page_id")
    floors = _validate_inputs(floor_units, regional_payloads, region_to_floor)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    document_global = node_id("document", document_id)
    page_global = node_id("page", page_id)
    nodes.extend(
        [
            {"id": document_global, "type": "document"},
            {
                "id": page_global,
                "type": "page",
                "attributes": copy.deepcopy(dict(page_attributes or {})),
            },
        ]
    )
    edges.append(
        {
            "id": edge_id("hierarchy", "document", document_id, "page", page_id),
            "relation": "document_contains_page",
            "from": document_global,
            "to": page_global,
            "status": "observed_hierarchy",
        }
    )

    for floor_id in sorted(floors):
        floor_global = node_id("floor", floor_id)
        nodes.append(
            {
                "id": floor_global,
                "type": "floor_region_candidate",
                "floor_id": floor_id,
                "attributes": floors[floor_id],
            }
        )
        edges.append(
            {
                "id": edge_id("hierarchy", "page", page_id, "floor", floor_id),
                "relation": "page_contains_floor_region_candidate",
                "from": page_global,
                "to": floor_global,
                "status": "automatic_candidate",
            }
        )

    for region_id in sorted(regional_payloads):
        payload = regional_payloads[region_id]
        if not isinstance(payload, Mapping):
            raise GraphContractError(f"Malformed regional payload: {region_id}")
        floor_id = region_to_floor[region_id]
        region_global = node_id("region", region_id)
        nodes.append(
            {
                "id": region_global,
                "type": "analysis_region_candidate",
                "floor_id": floor_id,
                "region_id": region_id,
                "attributes": {
                    "status": payload.get("status"),
                    "source": copy.deepcopy(payload.get("source")),
                    "summary": copy.deepcopy(payload.get("summary")),
                },
            }
        )
        edges.append(
            {
                "id": edge_id("hierarchy", "floor", floor_id, "region", region_id),
                "relation": "floor_region_contains_analysis_region",
                "from": node_id("floor", floor_id),
                "to": region_global,
                "status": "coordinate_containment_observed",
            }
        )

        raw_texts = payload.get("text_nodes", [])
        raw_spaces = payload.get("space_candidates", [])
        raw_edges = payload.get("topology_edges", [])
        for label, values in (
            ("text_nodes", raw_texts),
            ("space_candidates", raw_spaces),
            ("topology_edges", raw_edges),
        ):
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise GraphContractError(f"{region_id}.{label} must be a sequence")
        texts = [dict(item) for item in raw_texts if isinstance(item, Mapping)]
        spaces = [dict(item) for item in raw_spaces if isinstance(item, Mapping)]
        if len(texts) != len(raw_texts) or len(spaces) != len(raw_spaces):
            raise GraphContractError(f"Malformed node record in {region_id}")
        text_ids = {required_id(item.get("id"), "text node id") for item in texts}
        space_ids = {
            required_id(item.get("id"), "space candidate id") for item in spaces
        }
        if len(text_ids) != len(texts):
            raise GraphContractError(f"Duplicate text node id in {region_id}")
        if len(space_ids) != len(spaces):
            raise GraphContractError(f"Duplicate space candidate id in {region_id}")

        for item in sorted(texts, key=lambda value: value["id"]):
            local_id = item["id"]
            global_id = node_id("text", region_id, local_id)
            nodes.append(
                {
                    "id": global_id,
                    "type": "text_node",
                    "floor_id": floor_id,
                    "region_id": region_id,
                    "local_id": local_id,
                    "attributes": copy.deepcopy(item),
                }
            )
            edges.append(
                {
                    "id": edge_id("hierarchy", region_id, "text", local_id),
                    "relation": "region_contains_text_node",
                    "from": region_global,
                    "to": global_id,
                    "status": "observed_hierarchy",
                }
            )
        for item in sorted(spaces, key=lambda value: value["id"]):
            local_id = item["id"]
            global_id = node_id("space", region_id, local_id)
            nodes.append(
                {
                    "id": global_id,
                    "type": "space_candidate",
                    "floor_id": floor_id,
                    "region_id": region_id,
                    "local_id": local_id,
                    "attributes": copy.deepcopy(item),
                }
            )
            edges.append(
                {
                    "id": edge_id("hierarchy", region_id, "space", local_id),
                    "relation": "region_contains_space_candidate",
                    "from": region_global,
                    "to": global_id,
                    "status": "automatic_candidate",
                }
            )

        evidence_types = _collect_evidence(payload, spaces)
        audit = _audit_lookup(payload)
        for local_id in sorted(evidence_types):
            nodes.append(
                {
                    "id": node_id("evidence", region_id, local_id),
                    "type": evidence_types[local_id],
                    "floor_id": floor_id,
                    "region_id": region_id,
                    "local_id": local_id,
                    "attributes": copy.deepcopy(audit.get(local_id, {})),
                }
            )

        def resolve(local_id: Any) -> str:
            local_id = required_id(local_id, "topology edge endpoint")
            if local_id in text_ids:
                return node_id("text", region_id, local_id)
            if local_id in space_ids:
                return node_id("space", region_id, local_id)
            if local_id in evidence_types:
                return node_id("evidence", region_id, local_id)
            return node_id("unresolved", region_id, local_id)

        signatures: set[tuple[str, str, str]] = set()
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, Mapping):
                raise GraphContractError(f"Malformed topology edge in {region_id}")
            local_edge_id = required_id(raw_edge.get("id"), "topology edge id")
            relation = required_id(raw_edge.get("relation"), "topology relation")
            source, target = resolve(raw_edge.get("from")), resolve(raw_edge.get("to"))
            current = copy.deepcopy(dict(raw_edge))
            current.update(
                {
                    "id": edge_id(region_id, local_edge_id),
                    "relation": relation,
                    "from": source,
                    "to": target,
                    "source_edge_id": local_edge_id,
                    "floor_id": floor_id,
                    "region_id": region_id,
                }
            )
            edges.append(current)
            signatures.add((relation, source, target))

        for space in spaces:
            space_local_id = space["id"]
            space_global = node_id("space", region_id, space_local_id)
            for index, item in enumerate(space.get("boundary_evidence", []), start=1):
                evidence_local_id = item["source_id"]
                evidence_global = node_id("evidence", region_id, evidence_local_id)
                signature = (
                    "bounded_by_candidate_evidence",
                    space_global,
                    evidence_global,
                )
                if signature in signatures:
                    continue
                edges.append(
                    {
                        "id": edge_id(
                            region_id,
                            "boundary",
                            space_local_id,
                            evidence_local_id,
                            str(index),
                        ),
                        "relation": "bounded_by_candidate_evidence",
                        "from": space_global,
                        "to": evidence_global,
                        "status": "observed_relation_not_building_semantics",
                        "floor_id": floor_id,
                        "region_id": region_id,
                        "evidence": copy.deepcopy(dict(item)),
                    }
                )
                signatures.add(signature)

    graph = {"schema_version": GRAPH_SCHEMA_VERSION, "nodes": nodes, "edges": edges}
    validation = validate_document_graph(graph)
    graph["summary"] = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_types": dict(sorted(Counter(node["type"] for node in nodes).items())),
        "edge_relations": dict(
            sorted(Counter(edge["relation"] for edge in edges).items())
        ),
        **validation,
    }
    return graph
