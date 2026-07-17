from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.contracts import (  # type: ignore[import-not-found]
        ArtifactRegistry,
        ContractViolation,
        RunManifest,
        RunState,
        assert_transition,
        deterministic_run_id,
        sha256_file,
        utc_now,
        version_snapshot,
    )
    from core.storage import (  # type: ignore[import-not-found]
        create_directory_exclusive,
        write_json_atomic_exclusive,
    )
else:
    from .contracts import (
        ArtifactRegistry,
        ContractViolation,
        RunManifest,
        RunState,
        assert_transition,
        deterministic_run_id,
        sha256_file,
        utc_now,
        version_snapshot,
    )
    from .storage import create_directory_exclusive, write_json_atomic_exclusive


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


def default_config() -> dict[str, Any]:
    return {
        "pipeline": "planparser-industrial-bootstrap",
        "pipeline_contract": "1.0",
        "fail_closed": True,
        "preserve_source_bytes": True,
        "copy_source_into_run": False,
        "allowed_input_media_types": sorted(set(_MEDIA_TYPES.values())),
        "artifact_hash": "sha256",
        "publication": "atomic-exclusive",
    }


def bootstrap_run(
    input_path: Path,
    runs_root: Path,
    *,
    revision: int = 1,
    config: dict[str, Any] | None = None,
) -> Path:
    source = input_path.resolve(strict=True)
    if not source.is_file():
        raise ContractViolation(f"Input is not a regular file: {source}")
    media_type = _MEDIA_TYPES.get(source.suffix.lower())
    if media_type is None:
        raise ContractViolation(f"Unsupported input extension: {source.suffix}")
    if revision < 1:
        raise ContractViolation("Revision must be positive")

    config_snapshot = dict(default_config() if config is None else config)
    versions = version_snapshot()
    input_sha256 = sha256_file(source)
    run_id = deterministic_run_id(input_sha256, config_snapshot, versions)
    revision_dir = runs_root.resolve() / run_id / f"revision_{revision:03d}"

    create_directory_exclusive(revision_dir)
    registry = ArtifactRegistry()
    registry.register_existing_file(
        artifact_id="input:primary",
        path=source,
        media_type=media_type,
        producer="external",
        role="source",
    )

    state = RunState.PLANNED
    assert_transition(state, RunState.RUNNING)
    state = RunState.RUNNING
    assert_transition(state, RunState.COMPLETED)
    state = RunState.COMPLETED

    manifest = RunManifest(
        run_id=run_id,
        revision=revision,
        state=state,
        input_sha256=input_sha256,
        created_at_utc=utc_now(),
        config_snapshot=config_snapshot,
        version_snapshot=versions,
        artifacts=registry.records(),
    )
    manifest_path = revision_dir / "run_manifest.json"
    write_json_atomic_exclusive(manifest_path, manifest.to_dict())
    return manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a fail-closed PlanParser industrial bootstrap run."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--revision", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest_path = bootstrap_run(
            args.input, args.runs_root, revision=args.revision
        )
    except (ContractViolation, FileNotFoundError, PermissionError, OSError) as exc:
        error = {
            "status": "failed",
            "error": {
                "code": "BOOTSTRAP_REJECTED",
                "stage": "industrial_bootstrap",
                "message": str(exc),
                "retryable": False,
                "details": {"exception_type": type(exc).__name__},
            },
        }
        print(json.dumps(error, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(str(manifest_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
