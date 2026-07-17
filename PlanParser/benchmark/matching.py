"""
Greedy per-class matching between predicted and ground-truth observations.

Matching is restricted to the same ``class_id`` and same ``page_id`` (an element
must be the right kind, in the right place). Candidate pairs are ranked by
geometry similarity (IoU for areas, proximity for points/lines) and matched
greedily above ``match_threshold``. This yields TP / FP / FN sets used for
detection precision/recall/F1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .geometry_metrics import geometry_similarity
from .loader import Observation


@dataclass
class MatchResult:
    matches: List[Tuple[Observation, Observation, float]] = field(default_factory=list)  # (pred, gt, sim)
    false_positives: List[Observation] = field(default_factory=list)  # predicted, unmatched
    false_negatives: List[Observation] = field(default_factory=list)  # gt, unmatched (missed)

    @property
    def tp(self) -> int:
        return len(self.matches)

    @property
    def fp(self) -> int:
        return len(self.false_positives)

    @property
    def fn(self) -> int:
        return len(self.false_negatives)


def match_observations(pred: List[Observation], gt: List[Observation],
                       match_threshold: float = 0.5,
                       point_tol_px: float = 15.0,
                       line_tol_px: float = 25.0) -> MatchResult:
    """Greedy matching within a single (class_id, page_id) group is expected,
    but this function also enforces class/page equality defensively."""
    candidates: List[Tuple[float, int, int]] = []
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gt):
            if p.class_id != g.class_id or p.page_id != g.page_id:
                continue
            sim = geometry_similarity(p.geometry, g.geometry, point_tol_px, line_tol_px)
            if sim >= match_threshold:
                candidates.append((sim, pi, gi))
    candidates.sort(reverse=True)  # highest similarity first

    used_pred, used_gt = set(), set()
    result = MatchResult()
    for sim, pi, gi in candidates:
        if pi in used_pred or gi in used_gt:
            continue
        used_pred.add(pi)
        used_gt.add(gi)
        result.matches.append((pred[pi], gt[gi], sim))

    result.false_positives = [p for i, p in enumerate(pred) if i not in used_pred]
    result.false_negatives = [g for i, g in enumerate(gt) if i not in used_gt]
    return result


def prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else (1.0 if fp == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}
