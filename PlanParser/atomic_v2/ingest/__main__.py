"""Command-line entry point for atomic v2 ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import IngestError, ingest_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="planparser-atomic-ingest",
        description="Ingest a PDF, PNG, or JPEG into deterministic page PNGs and a JSON manifest.",
    )
    parser.add_argument("source", type=Path, help="PDF, PNG, JPEG, or JPG source file")
    parser.add_argument("output", type=Path, help="New output directory; it must not already exist")
    parser.add_argument(
        "--pdf-dpi",
        type=int,
        default=300,
        help="Rasterization DPI for PDF pages (default: 300)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest_path = ingest_source(args.source, args.output, pdf_dpi=args.pdf_dpi)
    except (IngestError, OSError, ValueError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 2

    result = {
        "manifest": manifest_path.as_posix(),
        "output": args.output.resolve().as_posix(),
        "status": "ok",
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
