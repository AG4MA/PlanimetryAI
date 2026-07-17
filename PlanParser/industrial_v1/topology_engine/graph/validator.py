from __future__ import annotations

from typing import Any, Mapping, Sequence

from .ids import GraphContractError, required_id


def validate_document_graph(graph: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(graph, Mapping):
        raise GraphContractError("Graph must be a mapping")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        raise GraphContractError("Graph nodes must be a sequence")
    if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        raise GraphContractError("Graph edges must be a sequence")

    node_ids: set[str] = set()
    node_by_id: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            raise GraphContractError("Malformed graph node")
        current_id = required_id(node.get("id"), "graph node id")
        if current_id in node_ids:
            raise GraphContractError(f"Duplicate graph node id: {current_id}")
        node_ids.add(current_id)
        node_by_id[current_id] = node

    edge_ids: set[str] = set()
    dangling = 0
    cross_floor = 0
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise GraphContractError("Malformed graph edge")
        current_id = required_id(edge.get("id"), "graph edge id")
        if current_id in edge_ids:
            raise GraphContractError(f"Duplicate graph edge id: {current_id}")
        edge_ids.add(current_id)
        source = required_id(edge.get("from"), "graph edge source")
        target = required_id(edge.get("to"), "graph edge target")
        if source not in node_by_id or target not in node_by_id:
            dangling += 1
            continue
        source_floor = node_by_id[source].get("floor_id")
        target_floor = node_by_id[target].get("floor_id")
        if (
            source_floor is not None
            and target_floor is not None
            and source_floor != target_floor
        ):
            cross_floor += 1

    if dangling:
        raise GraphContractError(
            f"Graph contains {dangling} dangling edge endpoint(s)"
        )
    if cross_floor:
        raise GraphContractError(f"Graph contains {cross_floor} cross-floor edge(s)")
    return {
        "duplicate_node_ids": 0,
        "duplicate_edge_ids": 0,
        "dangling_edge_endpoints": 0,
        "cross_floor_edges": 0,
    }
