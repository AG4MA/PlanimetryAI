"""Command-line entry point for native PDF text extraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import PdfTextError, extract_native_pdf_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planparser-atomic-pdf-text")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("ingest_manifest", type=Path)
    parser.add_argument("regions_manifest", type=Path)
    parser.add_argument("region_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--page-index", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report_path = extract_native_pdf_text(
            args.pdf,
            args.ingest_manifest,
            args.regions_manifest,
            args.region_id,
            args.output,
            page_index=args.page_index,
        )
    except (PdfTextError, OSError, ValueError) as exc:
        print(f"pdf text extraction failed: {exc}", file=sys.stderr)
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "abstained": report["region"]["abstained"],
                "objects": len(report["objects"]),
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
