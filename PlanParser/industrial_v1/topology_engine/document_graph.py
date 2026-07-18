"""Backward-compatible facade for the document graph package."""

from __future__ import annotations

from .graph import (
    GRAPH_SCHEMA_VERSION,
    GraphContractError,
    aggregate_document_graph,
    validate_document_graph,
)


__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "GraphContractError",
    "aggregate_document_graph",
    "validate_document_graph",
]
