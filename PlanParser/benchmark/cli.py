"""
CLI for the P1 benchmark.

    python -m PlanParser.benchmark <prediction.json> <ground_truth.json> \
        [--thresholds thresholds.json] [--json] [--match-threshold 0.5]

Exit codes: 0 = GO, 3 = HOLD, 4 = FAIL, 2 = usage/load error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .evaluator import evaluate
from .gate import evaluate_gate, load_config
from .loader import load

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_THRESHOLDS = os.path.join(_HERE, "thresholds.example.json")

_EXIT = {"GO": 0, "HOLD": 3, "FAIL": 4}


def _print_human(report: dict, verdict: dict) -> None:
    c = report["counts"]
    print(f"Documento: {report['document_id']}  (pred {c['pred_observations']} obs / gt {c['gt_observations']} obs)")
    print(f"Dataset status: pred={report['dataset_status']['prediction']} "
          f"gt={report['dataset_status']['ground_truth']}")
    micro = report["detection"]["micro"]
    print(f"Detection micro: P={micro['precision']:.3f} R={micro['recall']:.3f} "
          f"F1={micro['f1']:.3f} (TP={micro['tp']} FP={micro['fp']} FN={micro['fn']}) "
          f"| macro-F1={report['detection']['macro_f1']:.3f}")
    if report["ocr"]["cer"] is not None:
        print(f"OCR: CER={report['ocr']['cer']:.3f} WER={report['ocr']['wer']:.3f} "
              f"({report['ocr']['n_pairs']} label)")
    if report["measurements"]["mean_value_error_ratio"] is not None:
        print(f"Misure: errore medio={report['measurements']['mean_value_error_ratio']:.3f} "
              f"({report['measurements']['n']})")
    rel = report["relationships"]
    print(f"Relazioni: F1={rel['f1']:.3f} orfani={len(rel['orphan_refs_pred'])}")
    cal = report["calibration"]
    print(f"Calibrazione: ECE={cal['ece']:.3f} Brier={cal['brier']:.3f} "
          f"astensione P/R={cal['abstention_precision']:.2f}/{cal['abstention_recall']:.2f}")
    print()
    s = verdict["summary"]
    print(f"GATE {verdict['gate']}: {verdict['verdict']}  "
          f"[PASS {s['PASS']} / FAIL {s['FAIL']} / UNRESOLVED {s['UNRESOLVED']} / NO_DATA {s['NO_DATA']}]")
    for cr in verdict["criteria"]:
        val = cr["value"]
        vs = f"{val:.3f}" if isinstance(val, float) else str(val)
        thr = cr["threshold"] if cr["threshold"] is not None else "DA CONCORDARE"
        print(f"  [{cr['status']:<10}] {cr['id']}: {vs} {cr['op']} {thr}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="PlanParser.benchmark",
        description="Valuta una decomposizione (predizione) vs ground truth e delibera Gate 1 (fail-closed).",
    )
    ap.add_argument("prediction", help="decomposition JSON prodotto dal decompositore")
    ap.add_argument("ground_truth", help="decomposition JSON ground-truth congelato")
    ap.add_argument("--thresholds", default=_DEFAULT_THRESHOLDS,
                    help="config soglie Gate 1 (default: thresholds.example.json, tutte DA CONCORDARE)")
    ap.add_argument("--match-threshold", type=float, default=0.5)
    ap.add_argument("--point-tol-px", type=float, default=15.0)
    ap.add_argument("--line-tol-px", type=float, default=25.0)
    ap.add_argument("--json", dest="as_json", action="store_true", help="stampa report+verdetto in JSON")
    args = ap.parse_args(argv)

    for path in (args.prediction, args.ground_truth, args.thresholds):
        if not os.path.exists(path):
            print(f"[benchmark] file non trovato: {path}", file=sys.stderr)
            return 2

    try:
        pred = load(args.prediction)
        gt = load(args.ground_truth)
        config = load_config(args.thresholds)
    except Exception as exc:
        print(f"[benchmark] errore di caricamento: {exc}", file=sys.stderr)
        return 2

    report = evaluate(pred, gt, args.match_threshold, args.point_tol_px, args.line_tol_px)
    verdict = evaluate_gate(report, config)

    if args.as_json:
        print(json.dumps({"report": report, "verdict": verdict}, ensure_ascii=False, indent=2))
    else:
        _print_human(report, verdict)

    return _EXIT.get(verdict["verdict"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
