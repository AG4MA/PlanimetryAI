"""Validate a Point 1 dataset release from the command line."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .validator import dataset_manifest_sha256, validate_dataset_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PlanimetryAI P1 dataset manifest")
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--verify-files",
        action="store_true",
        help="Verify referenced annotation hashes and decomposition contracts",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    issues = validate_dataset_manifest(
        manifest,
        base_dir=manifest_path.parent,
        verify_annotation_files=args.verify_files,
    )
    if issues:
        for issue in issues:
            print(f"{issue.severity.upper()} {issue.code} {issue.path}: {issue.message}")
        return 1
    print(f"VALID {dataset_manifest_sha256(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
