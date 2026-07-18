from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np

from ..models import BarrierResult
from .text_normalization import first_config_value


def config_value(config: Any, names: tuple[str, ...], default: Any) -> Any:
    return first_config_value(config, names, default)


def is_legacy(config: Any) -> bool:
    value = str(
        config_value(
            config,
            ("topology.compatibility_mode", "compatibility_mode", "mode", "profile"),
            "legacy_v1",
        )
    )
    return value == "legacy_v1"


def nearest_free(
    center: Sequence[float],
    free: np.ndarray,
    max_radius: int = 60,
) -> tuple[int, int] | None:
    """Return the legacy deterministic nearest eligible pixel around a center."""

    if free.ndim != 2:
        raise ValueError("free must be a two-dimensional mask")
    height, width = free.shape
    cx = int(round(float(center[0])))
    cy = int(round(float(center[1])))
    if 0 <= cx < width and 0 <= cy < height and bool(free[cy, cx]):
        return cx, cy
    for radius in range(1, int(max_radius) + 1):
        x1, x2 = max(0, cx - radius), min(width - 1, cx + radius)
        y1, y2 = max(0, cy - radius), min(height - 1, cy + radius)
        for x in range(x1, x2 + 1):
            for y in (y1, y2):
                if bool(free[y, x]):
                    return x, y
        for y in range(y1 + 1, y2):
            for x in (x1, x2):
                if bool(free[y, x]):
                    return x, y
    return None


def expand_from_text_nodes(
    barrier: np.ndarray | BarrierResult,
    text_nodes: list[dict[str, Any]],
    config: Any = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Run the legacy four-connected, multi-source geodesic expansion."""

    if isinstance(barrier, BarrierResult):
        barrier = barrier.effective_barrier
    if barrier.ndim != 2:
        raise ValueError("barrier must be a two-dimensional mask")
    max_radius = int(
        config_value(
            config,
            ("topology.nearest_free_max_radius_px", "nearest_free_max_radius_px"),
            60,
        )
    )
    free = barrier == 0
    labels = np.zeros(barrier.shape, dtype=np.int16 if is_legacy(config) else np.int32)
    distance = np.full(barrier.shape, -1, dtype=np.int32)
    queue: deque[tuple[int, int]] = deque()
    seed_nodes = [
        node for node in text_nodes if node.get("role_hypothesis") == "space_name_seed"
    ]
    seed_audit: list[dict[str, Any]] = []
    for label, node in enumerate(seed_nodes, 1):
        seed = nearest_free(node["center_crop_px"], free, max_radius=max_radius)
        node["space_label_index"] = label
        node["expansion_seed_crop_px"] = list(seed) if seed else None
        node["seed_displacement_px"] = (
            round(math.dist(node["center_crop_px"], seed), 3) if seed else None
        )
        seed_audit.append(
            {
                "text_node_id": node["id"],
                "space_label_index": label,
                "seed_crop_px": list(seed) if seed else None,
                "seed_displacement_px": node["seed_displacement_px"],
            }
        )
        if seed:
            x, y = seed
            labels[y, x] = label
            distance[y, x] = 0
            queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        label = labels[y, x]
        next_distance = distance[y, x] + 1
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < labels.shape[1] and 0 <= ny < labels.shape[0]):
                continue
            if not free[ny, nx] or labels[ny, nx] != 0:
                continue
            labels[ny, nx] = label
            distance[ny, nx] = next_distance
            queue.append((nx, ny))
    return labels, seed_audit


def shift_without_wrap(array: np.ndarray, dx: int, dy: int) -> np.ndarray:
    shifted = np.zeros_like(array)
    source_x1 = max(0, -dx)
    source_x2 = array.shape[1] - max(0, dx)
    source_y1 = max(0, -dy)
    source_y2 = array.shape[0] - max(0, dy)
    target_x1 = max(0, dx)
    target_x2 = array.shape[1] - max(0, -dx)
    target_y1 = max(0, dy)
    target_y2 = array.shape[0] - max(0, -dy)
    shifted[target_y1:target_y2, target_x1:target_x2] = array[
        source_y1:source_y2, source_x1:source_x2
    ]
    return shifted


def competition_boundary(
    region: np.ndarray,
    labels: np.ndarray,
    label: int,
    config: Any = None,
) -> np.ndarray:
    eroded = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    perimeter = region.astype(bool) & ~eroded
    competition = np.zeros(region.shape, dtype=bool)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shifted = (
            np.roll(labels, shift=(dy, dx), axis=(0, 1))
            if is_legacy(config)
            else shift_without_wrap(labels, dx, dy)
        )
        competition |= perimeter & (shifted > 0) & (shifted != label)
    return competition


def contour_polygon(mask: np.ndarray, config: Any = None) -> list[list[int]]:
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    ratio = float(
        config_value(
            config,
            ("topology.contour_epsilon_ratio", "contour_epsilon_ratio"),
            0.003,
        )
    )
    minimum = float(
        config_value(
            config,
            ("topology.contour_min_epsilon_px", "contour_min_epsilon_px"),
            1.0,
        )
    )
    epsilon = max(minimum, cv2.arcLength(contour, True) * ratio)
    approximated = cv2.approxPolyDP(contour, epsilon, True)
    return [[int(point[0][0]), int(point[0][1])] for point in approximated]


def ray_observations(
    seed: tuple[int, int],
    barrier: np.ndarray,
    raw_barrier: np.ndarray,
    synthetic_closures: np.ndarray,
    config: Any = None,
) -> list[dict[str, Any]]:
    del config
    directions = [
        ("north", 0, -1),
        ("north_east", 1, -1),
        ("east", 1, 0),
        ("south_east", 1, 1),
        ("south", 0, 1),
        ("south_west", -1, 1),
        ("west", -1, 0),
        ("north_west", -1, -1),
    ]
    observations: list[dict[str, Any]] = []
    for name, dx, dy in directions:
        x, y = seed
        hit: list[int] | None = None
        while True:
            x += dx
            y += dy
            if not (0 <= x < barrier.shape[1] and 0 <= y < barrier.shape[0]):
                break
            if barrier[y, x]:
                hit_kind = (
                    "observed_barrier"
                    if raw_barrier[y, x]
                    else "synthetic_gap_closure"
                    if synthetic_closures[y, x]
                    else "thickened_barrier"
                )
                hit = [x, y]
                observations.append(
                    {
                        "direction": name,
                        "hit_crop_px": hit,
                        "distance_px": round(math.hypot(x - seed[0], y - seed[1]), 3),
                        "hit_kind": hit_kind,
                    }
                )
                break
        if hit is None:
            observations.append(
                {
                    "direction": name,
                    "hit_crop_px": None,
                    "distance_px": None,
                    "hit_kind": "no_hit",
                }
            )
    return observations


__all__ = [
    "competition_boundary",
    "contour_polygon",
    "expand_from_text_nodes",
    "nearest_free",
    "ray_observations",
]
