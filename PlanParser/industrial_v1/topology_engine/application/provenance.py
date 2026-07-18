from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from industrial_v1.core.contracts import canonical_json_bytes

from .contracts import (
    ArtifactReference,
    INPUT_SNAPSHOT_SCHEMA_VERSION,
    JobContractError,
)


@dataclass(frozen=True)
class JobProvenance:
    job_id: str
    engine_source_sha256: str
    identity: Mapping[str, Any]
    input_snapshot: Mapping[str, Any]


def engine_source_digest(
    engine_root: Path,
    *,
    recursive: bool = True,
    excluded_directories: Sequence[str] = ("__pycache__", "tests", "artifacts"),
) -> str:
    """Hash engine Python sources by relative name and exact bytes.

    Recursive discovery includes application modules in the digest while the
    explicit exclusion list prevents test/runtime artifacts from changing a
    production job identity.
    """

    root = Path(engine_root).resolve(strict=True)
    if not root.is_dir():
        raise JobContractError(f"Engine source root is not a directory: {root}")
    iterator = root.rglob("*.py") if recursive else root.glob("*.py")
    excluded = set(excluded_directories)
    sources = [
        path
        for path in iterator
        if path.is_file()
        and not path.is_symlink()
        and not any(part in excluded for part in path.relative_to(root).parts[:-1])
    ]
    sources.sort(key=lambda path: path.relative_to(root).as_posix())
    if not sources:
        raise JobContractError(f"Engine source root contains no Python modules: {root}")
    digest = hashlib.sha256()
    for path in sources:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def stable_job_id(identity: Mapping[str, Any]) -> str:
    if not isinstance(identity, Mapping):
        raise TypeError("Job identity must be a mapping")
    return "job_" + hashlib.sha256(canonical_json_bytes(dict(identity))).hexdigest()[:24]


def _reference_snapshot(
    reference: ArtifactReference | Mapping[str, Any]
) -> dict[str, Any]:
    if isinstance(reference, ArtifactReference):
        return reference.descriptor(include_size=True)
    if not isinstance(reference, Mapping):
        raise TypeError("Input references must be ArtifactReference objects or mappings")
    snapshot = {
        key: reference[key]
        for key in ("role", "relative_path", "sha256", "byte_size")
        if key in reference
    }
    missing = {"role", "relative_path", "sha256", "byte_size"} - set(snapshot)
    if missing:
        raise JobContractError(
            f"Input reference snapshot is incomplete: {sorted(missing)}"
        )
    return snapshot


def build_input_identity(
    *,
    engine_version: str,
    engine_source_sha256: str,
    config_snapshot: Mapping[str, Any],
    raw_job: Mapping[str, Any],
    input_references: Sequence[ArtifactReference | Mapping[str, Any]],
) -> dict[str, Any]:
    if not engine_version or len(engine_source_sha256) != 64:
        raise JobContractError("Engine version and SHA-256 source digest are required")
    identity = {
        "engine_version": engine_version,
        "engine_source_sha256": engine_source_sha256,
        "config": dict(config_snapshot),
        "job": dict(raw_job),
        "inputs": [_reference_snapshot(item) for item in input_references],
    }
    canonical_json_bytes(identity)
    return identity


def build_input_snapshot(
    identity: Mapping[str, Any],
    *,
    schema_version: str = INPUT_SNAPSHOT_SCHEMA_VERSION,
) -> dict[str, Any]:
    identity_copy = dict(identity)
    return {
        "schema_version": schema_version,
        "job_id": stable_job_id(identity_copy),
        **identity_copy,
    }


def build_job_provenance(
    *,
    engine_root: Path,
    engine_version: str,
    config_snapshot: Mapping[str, Any],
    raw_job: Mapping[str, Any],
    input_references: Sequence[ArtifactReference | Mapping[str, Any]],
) -> JobProvenance:
    source_digest = engine_source_digest(engine_root)
    identity = build_input_identity(
        engine_version=engine_version,
        engine_source_sha256=source_digest,
        config_snapshot=config_snapshot,
        raw_job=raw_job,
        input_references=input_references,
    )
    snapshot = build_input_snapshot(identity)
    return JobProvenance(
        job_id=str(snapshot["job_id"]),
        engine_source_sha256=source_digest,
        identity=identity,
        input_snapshot=snapshot,
    )


__all__ = [
    "JobProvenance",
    "build_input_identity",
    "build_input_snapshot",
    "build_job_provenance",
    "engine_source_digest",
    "stable_job_id",
]
