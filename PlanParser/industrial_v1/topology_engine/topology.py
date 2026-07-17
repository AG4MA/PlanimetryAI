"""Compatibility facade for the reusable topology domain kernels.

Existing callers keep importing this module while implementation details live
in cohesive, I/O-free domain modules.
"""

from __future__ import annotations

from .domain import (
    build_graph_edges,
    build_spaces,
    competition_boundary,
    contour_polygon,
    expand_from_text_nodes,
    nearest_free,
    ray_observations,
)


__all__ = [
    "nearest_free",
    "expand_from_text_nodes",
    "competition_boundary",
    "contour_polygon",
    "ray_observations",
    "build_spaces",
    "build_graph_edges",
]
