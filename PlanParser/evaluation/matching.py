"""Deterministic one-to-one observation matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .config import EvaluationConfig
from .geometry import GeometryComparison, compare_geometry


@dataclass(frozen=True)
class ObservationMatch:
    ground_truth_id: str
    prediction_id: str
    ground_truth_index: int
    prediction_index: int
    comparison: GeometryComparison


def match_observations(
    ground_truth: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    config: EvaluationConfig,
    page_diagonal_px: float,
    *,
    require_same_layer: bool = True,
    require_same_class: bool = True,
) -> list[ObservationMatch]:
    """Find a maximum-quality one-to-one matching among passing pairs."""
    if not ground_truth or not predictions:
        return []

    comparisons: dict[tuple[int, int], GeometryComparison] = {}
    cost = np.full((len(ground_truth), len(predictions)), 1_000_000.0, dtype=float)
    for ground_truth_index, expected in enumerate(ground_truth):
        for prediction_index, actual in enumerate(predictions):
            if require_same_layer and expected["layer"] != actual["layer"]:
                continue
            if require_same_class and expected["class_id"] != actual["class_id"]:
                continue
            comparison = compare_geometry(
                actual["geometry"], expected["geometry"], config, page_diagonal_px
            )
            comparisons[(ground_truth_index, prediction_index)] = comparison
            if comparison.passed:
                # Stable epsilon prevents arbitrary choices between identical scores.
                epsilon = (ground_truth_index * len(predictions) + prediction_index) * 1e-12
                cost[ground_truth_index, prediction_index] = 1.0 - comparison.similarity + epsilon

    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("scipy is required for deterministic matching") from exc

    row_indices, column_indices = linear_sum_assignment(cost)
    matches: list[ObservationMatch] = []
    for ground_truth_index, prediction_index in zip(row_indices, column_indices):
        if cost[ground_truth_index, prediction_index] >= 1_000_000.0:
            continue
        comparison = comparisons[(int(ground_truth_index), int(prediction_index))]
        matches.append(ObservationMatch(
            ground_truth_id=str(ground_truth[ground_truth_index]["id"]),
            prediction_id=str(predictions[prediction_index]["id"]),
            ground_truth_index=int(ground_truth_index),
            prediction_index=int(prediction_index),
            comparison=comparison,
        ))
    return sorted(matches, key=lambda match: (match.ground_truth_id, match.prediction_id))
