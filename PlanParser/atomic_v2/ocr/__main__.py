"""Command-line interface for raw, non-semantic OCR."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import OcrError, run_raw_ocr


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planparser-atomic-ocr")
    parser.add_argument("source", type=Path, help="Input region image")
    parser.add_argument("output", type=Path, help="New revision directory")
    parser.add_argument("--confidence-threshold", type=float, default=0.60)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report_path = run_raw_ocr(
            args.source,
            args.output,
            confidence_threshold=args.confidence_threshold,
        )
    except (OcrError, OSError, ValueError) as exc:
        print(f"ocr failed: {exc}", file=sys.stderr)
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "abstained": report["region"]["abstained"],
                "elements": len(report["elements"]),
                "report": report_path.as_posix(),
                "status": report["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
