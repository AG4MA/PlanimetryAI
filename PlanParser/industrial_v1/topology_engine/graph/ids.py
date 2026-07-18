from __future__ import annotations

from typing import Any


GRAPH_SCHEMA_VERSION = "planparser.topology-engine.document-graph/1.0"


class GraphContractError(ValueError):
    pass


def required_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphContractError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise GraphContractError(
            f"{label} must not contain leading or trailing whitespace"
        )
    return value


def node_id(kind: str, *parts: str) -> str:
    return ":".join((kind, *parts))


def edge_id(scope: str, *parts: str) -> str:
    return ":".join(("edge", scope, *parts))


def evidence_type(local_id: str, declared_type: str | None) -> str:
    if local_id.startswith("line_"):
        inferred = "raw_linework_candidate"
    elif local_id.startswith("band_"):
        inferred = "parallel_edge_band_hypothesis"
    else:
        raise GraphContractError(
            f"Cannot classify cited boundary evidence: {local_id}"
        )
    if declared_type is not None and declared_type != inferred:
        raise GraphContractError(
            f"Evidence type conflicts with ID {local_id}: {declared_type} vs {inferred}"
        )
    return inferred
