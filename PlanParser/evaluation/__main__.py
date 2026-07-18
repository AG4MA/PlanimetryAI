"""CLI for one PlanParser P1 prediction/ground-truth pair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import EvaluationConfig
from .evaluator import evaluate_decompositions, validate_evaluation_report


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a PlanParser P1 decomposition against frozen ground truth"
    )
    parser.add_argument("prediction", type=Path)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional JSON matching configuration; these are not Gate 1 thresholds",
    )
    args = parser.parse_args()

    config = (
        EvaluationConfig.from_mapping(_load_json(args.config))
        if args.config
        else EvaluationConfig()
    )
    report = evaluate_decompositions(
        _load_json(args.prediction), _load_json(args.ground_truth), config
    )
    schema_errors = validate_evaluation_report(report)
    if schema_errors:
        for error in schema_errors:
            print(f"REPORT_SCHEMA_ERROR {error}")
        return 3

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if report["status"] == "invalid":
        for issue in report["issues"]:
            print(
                f"INVALID {issue['source']} {issue['code']} {issue['path']}: {issue['message']}"
            )
        return 2
    observations = report["summary"]["observations"]
    print(
        "VALID "
        f"report_id={report['report_id']} "
        f"precision={observations['precision']} "
        f"recall={observations['recall']} "
        f"f1={observations['f1']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
