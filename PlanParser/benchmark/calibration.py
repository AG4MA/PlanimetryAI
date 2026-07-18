"""
Confidence calibration & abstention metrics (ACCEPTANCE_CRITERIA P1-10, P1-16).

Given predictions each with a confidence score, whether they were correct, and
whether the producer abstained, compute:
  * ECE  — Expected Calibration Error (binned)
  * Brier — mean squared error of confidence vs correctness
  * coverage / risk — at a set of confidence thresholds
  * abstention precision/recall — did abstention fire on the wrong/OOD cases?

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence


@dataclass
class ConfidenceSample:
    score: float          # confidence in [0,1]
    correct: bool         # was the (non-abstained) prediction correct?
    abstained: bool = False
    should_abstain: bool = False  # ground-truth: this case had no reliable answer


def expected_calibration_error(samples: Sequence[ConfidenceSample], bins: int = 10) -> float:
    """Binned ECE over non-abstained samples. Returns 0.0 if none."""
    considered = [s for s in samples if not s.abstained]
    if not considered:
        return 0.0
    n = len(considered)
    edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        in_bin = [s for s in considered
                  if (s.score > lo or (b == 0 and s.score >= lo)) and s.score <= hi]
        if not in_bin:
            continue
        avg_conf = sum(s.score for s in in_bin) / len(in_bin)
        acc = sum(1 for s in in_bin if s.correct) / len(in_bin)
        ece += (len(in_bin) / n) * abs(avg_conf - acc)
    return ece


def brier_score(samples: Sequence[ConfidenceSample]) -> float:
    considered = [s for s in samples if not s.abstained]
    if not considered:
        return 0.0
    return sum((s.score - (1.0 if s.correct else 0.0)) ** 2 for s in considered) / len(considered)


def coverage_risk(samples: Sequence[ConfidenceSample], thresholds: Sequence[float]) -> List[Dict]:
    """
    For each confidence threshold t, coverage = fraction of non-abstained samples
    with score >= t; risk = error rate among those covered.
    """
    considered = [s for s in samples if not s.abstained]
    out: List[Dict] = []
    total = len(considered)
    for t in thresholds:
        covered = [s for s in considered if s.score >= t]
        cov = len(covered) / total if total else 0.0
        risk = (sum(1 for s in covered if not s.correct) / len(covered)) if covered else 0.0
        out.append({"threshold": t, "coverage": cov, "risk": risk, "n_covered": len(covered)})
    return out


def abstention_metrics(samples: Sequence[ConfidenceSample]) -> Dict[str, float]:
    """
    Treat abstention as a detector of 'no reliable answer' (should_abstain=True).
    precision = correct abstentions / all abstentions;
    recall    = correct abstentions / all should_abstain cases.
    """
    abstained = [s for s in samples if s.abstained]
    should = [s for s in samples if s.should_abstain]
    tp = sum(1 for s in abstained if s.should_abstain)
    precision = tp / len(abstained) if abstained else (1.0 if not should else 0.0)
    recall = tp / len(should) if should else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "abstention_precision": precision,
        "abstention_recall": recall,
        "abstention_f1": f1,
        "n_abstained": len(abstained),
        "n_should_abstain": len(should),
    }


def summarize(samples: Sequence[ConfidenceSample],
              coverage_thresholds: Sequence[float] = (0.5, 0.7, 0.9)) -> Dict:
    return {
        "ece": expected_calibration_error(samples),
        "brier": brier_score(samples),
        "coverage_risk": coverage_risk(samples, coverage_thresholds),
        **abstention_metrics(samples),
        "n_samples": len(samples),
    }
