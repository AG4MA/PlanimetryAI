"""
Point-1 decomposition evaluator.

Compares a *prediction* decomposition against a *ground-truth* decomposition
(both conforming to decomposition.schema.json) and produces a structured metrics
report covering the measurable ACCEPTANCE_CRITERIA P1 items:

  * detection precision/recall/F1 per class        (P1-03, P1-05, P1-06)
  * geometric error: IoU, area/length/position err (P1-04, P1-05, P1-08)
  * OCR CER/WER on matched text                      (P1-07)
  * measurement value error + abstention             (P1-08, P1-10)
  * relationship precision/recall + orphan refs      (P1-09)
  * confidence calibration ECE/Brier/coverage-risk   (P1-10, P1-16)

The report is data only; pass/fail against Gate-1 thresholds is done in gate.py
(fail-closed). Standard library only.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import calibration, text_metrics
from .geometry_metrics import AREA_TYPES, LINE_TYPES, POINT_TYPES, geometry_error
from .loader import Decomposition, Observation, orphan_relationship_refs
from .matching import MatchResult, match_observations, prf


def _group_key(o: Observation) -> Tuple[str, str]:
    return (o.class_id, o.page_id)


def _numeric_value(o: Observation) -> Optional[float]:
    """Best-effort numeric extraction for measurement observations."""
    attrs = o.attributes
    for k in ("value", "magnitude", "length_mm", "length_m", "angle_deg"):
        if isinstance(attrs.get(k), (int, float)):
            return float(attrs[k])
    # scale like "1:100" -> 100.0 ; plain number in text -> float
    txt = o.text
    if txt:
        t = txt.strip().replace(",", ".")
        if ":" in t:
            parts = t.split(":")
            try:
                return float(parts[1])
            except (ValueError, IndexError):
                pass
        try:
            return float("".join(c for c in t if (c.isdigit() or c in ".-")) or "x")
        except ValueError:
            return None
    return None


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def evaluate(pred: Decomposition, gt: Decomposition,
             match_threshold: float = 0.5,
             point_tol_px: float = 15.0,
             line_tol_px: float = 25.0) -> Dict:
    # Detection matching excludes abstained predictions: an abstention is not a
    # committed detection, so it must not be penalized as a false positive. It is
    # still scored in the calibration/abstention block below.
    pred_groups: Dict[Tuple[str, str], List[Observation]] = {}
    gt_groups: Dict[Tuple[str, str], List[Observation]] = {}
    for o in pred.observations:
        if o.abstained:
            continue
        pred_groups.setdefault(_group_key(o), []).append(o)
    for o in gt.observations:
        gt_groups.setdefault(_group_key(o), []).append(o)

    all_keys = set(pred_groups) | set(gt_groups)
    per_class_counts: Dict[str, Dict[str, int]] = {}
    per_class_geom: Dict[str, Dict[str, List[float]]] = {}
    matched_pairs: List[Tuple[Observation, Observation]] = []
    tp_pred_ids: set = set()
    total_tp = total_fp = total_fn = 0

    for key in all_keys:
        cls = key[0]
        p = pred_groups.get(key, [])
        g = gt_groups.get(key, [])
        res: MatchResult = match_observations(p, g, match_threshold, point_tol_px, line_tol_px)
        c = per_class_counts.setdefault(cls, {"tp": 0, "fp": 0, "fn": 0})
        c["tp"] += res.tp
        c["fp"] += res.fp
        c["fn"] += res.fn
        total_tp += res.tp
        total_fp += res.fp
        total_fn += res.fn
        gm = per_class_geom.setdefault(cls, {"iou": [], "area_error_ratio": [],
                                             "length_error_ratio": [], "centroid_distance_px": []})
        for pobs, gobs, _sim in res.matches:
            matched_pairs.append((pobs, gobs))
            tp_pred_ids.add(pobs.id)
            err = geometry_error(pobs.geometry, gobs.geometry)
            for k, v in err.items():
                if v is not None:
                    gm.setdefault(k, []).append(v)

    detection = {
        "per_class": {cls: prf(c["tp"], c["fp"], c["fn"]) for cls, c in per_class_counts.items()},
        "micro": prf(total_tp, total_fp, total_fn),
    }
    f1s = [v["f1"] for v in detection["per_class"].values()]
    detection["macro_f1"] = sum(f1s) / len(f1s) if f1s else 0.0

    geometry = {}
    for cls, gm in per_class_geom.items():
        summary = {k: _mean(v) for k, v in gm.items() if v}
        if summary:
            geometry[cls] = summary

    # OCR on matched text observations
    ocr_pairs = [(g.text or "", p.text or "")
                 for p, g in matched_pairs if g.layer == "text" and (g.text is not None)]
    ocr = {
        "n_pairs": len(ocr_pairs),
        "cer": text_metrics.corpus_cer(ocr_pairs) if ocr_pairs else None,
        "wer": text_metrics.corpus_wer(ocr_pairs) if ocr_pairs else None,
    }

    # Measurement value error on matched measurement observations
    meas_errs: List[float] = []
    for p, g in matched_pairs:
        if g.layer != "measurement":
            continue
        pv, gv = _numeric_value(p), _numeric_value(g)
        if pv is not None and gv is not None and gv != 0:
            meas_errs.append(abs(pv - gv) / abs(gv))
    measurements = {
        "n": len(meas_errs),
        "mean_value_error_ratio": _mean(meas_errs),
    }

    # Relationships: translate predicted endpoints via the pred->gt id map
    id_map = {p.id: g.id for p, g in matched_pairs}
    gt_rel_set = {(r.type, r.from_id, r.to_id) for r in gt.relationships}
    rel_tp = rel_fp = 0
    for r in pred.relationships:
        mapped = (r.type, id_map.get(r.from_id), id_map.get(r.to_id))
        if mapped[1] is not None and mapped[2] is not None and mapped in gt_rel_set:
            rel_tp += 1
        else:
            rel_fp += 1
    rel_fn = len(gt_rel_set) - rel_tp
    relationships = {
        **prf(rel_tp, rel_fp, max(0, rel_fn)),
        "orphan_refs_pred": orphan_relationship_refs(pred),
    }

    # Calibration: correct = matched (TP); should_abstain = not TP (no right answer to give)
    samples = [
        calibration.ConfidenceSample(
            score=o.confidence_score,
            correct=(o.id in tp_pred_ids),
            abstained=o.abstained,
            should_abstain=(o.id not in tp_pred_ids),
        )
        for o in pred.observations
    ]
    calib = calibration.summarize(samples)

    error_registry = {
        "false_negatives": [
            {"class_id": g.class_id, "page_id": g.page_id, "gt_id": g.id}
            for key in all_keys
            for g in _unmatched_gt(pred_groups.get(key, []), gt_groups.get(key, []),
                                   match_threshold, point_tol_px, line_tol_px)
        ],
    }

    return {
        "document_id": gt.document_id or pred.document_id,
        "dataset_status": {"prediction": pred.dataset_status, "ground_truth": gt.dataset_status},
        "counts": {"tp": total_tp, "fp": total_fp, "fn": total_fn,
                   "pred_observations": len(pred.observations),
                   "gt_observations": len(gt.observations)},
        "detection": detection,
        "geometry": geometry,
        "ocr": ocr,
        "measurements": measurements,
        "relationships": relationships,
        "calibration": calib,
        "error_registry": error_registry,
        "params": {"match_threshold": match_threshold,
                   "point_tol_px": point_tol_px, "line_tol_px": line_tol_px},
    }


def _unmatched_gt(p, g, mt, pt, lt):
    return match_observations(p, g, mt, pt, lt).false_negatives
