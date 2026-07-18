"""
Fail-closed Gate-1 verdict.

Maps metrics from an evaluator report to Gate-1 acceptance criteria and returns a
verdict. The verdict is FAIL-CLOSED:

  * a criterion whose threshold is still ``null`` (DA CONCORDARE) is UNRESOLVED;
  * a criterion whose metric is missing/None is NO_DATA;
  * only a criterion with a resolved threshold AND available metric can PASS/FAIL.

Overall: FAIL if any criterion FAILs; else HOLD if any is UNRESOLVED/NO_DATA;
GO only when every criterion is resolved and passes. A GO can therefore never be
produced while thresholds remain unset — no accidental green light.
"""

from __future__ import annotations

import json
import operator
from typing import Any, Dict, List, Optional

_OPS = {
    ">=": operator.ge, "<=": operator.le, ">": operator.gt,
    "<": operator.lt, "==": operator.eq, "!=": operator.ne,
}


def resolve_metric(report: Dict, path: str) -> Optional[Any]:
    """Resolve a dotted path in the report. A trailing '.__len__' yields len()."""
    take_len = False
    if path.endswith(".__len__"):
        take_len = True
        path = path[: -len(".__len__")]
    cur: Any = report
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if take_len:
        try:
            return len(cur)
        except TypeError:
            return None
    return cur


def evaluate_gate(report: Dict, config: Dict) -> Dict:
    results: List[Dict] = []
    for crit in config.get("criteria", []):
        cid = crit.get("id", "?")
        metric_path = crit.get("metric", "")
        op = crit.get("op", ">=")
        threshold = crit.get("threshold", None)
        value = resolve_metric(report, metric_path)

        if threshold is None:
            status = "UNRESOLVED"
        elif value is None:
            status = "NO_DATA"
        else:
            fn = _OPS.get(op)
            if fn is None:
                status = "BAD_OP"
            else:
                status = "PASS" if fn(value, threshold) else "FAIL"

        results.append({
            "id": cid, "metric": metric_path, "op": op,
            "threshold": threshold, "value": value, "status": status,
            "note": crit.get("note"),
        })

    statuses = {r["status"] for r in results}
    if "FAIL" in statuses or "BAD_OP" in statuses:
        verdict = "FAIL"
    elif "UNRESOLVED" in statuses or "NO_DATA" in statuses:
        verdict = "HOLD"
    elif not results:
        verdict = "HOLD"  # no criteria => cannot certify
    else:
        verdict = "GO"

    return {
        "gate": config.get("gate", "GATE_1"),
        "verdict": verdict,
        "n_criteria": len(results),
        "summary": {s: sum(1 for r in results if r["status"] == s)
                    for s in ("PASS", "FAIL", "HOLD", "UNRESOLVED", "NO_DATA")},
        "criteria": results,
    }


def load_config(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
