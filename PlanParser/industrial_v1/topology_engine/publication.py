from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from ..core.contracts import (
    ContractViolation,
    SHA256_PATTERN,
    canonical_json_bytes,
    sha256_file,
)
from ..core.storage import (
    create_directory_exclusive,
    read_json,
    write_bytes_atomic_exclusive,
    write_json_atomic_exclusive,
)


MANIFEST_SCHEMA_VERSION = "planparser.topology-engine.artifact-manifest/1.0"
DEFAULT_MANIFEST_NAME = "artifact_manifest.json"


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_id: str
    relative_path: str
    payload: bytes
    media_type: str
    producer: str
    role: str = "derived"
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishedArtifact:
    artifact_id: str
    relative_path: str
    sha256: str
    byte_size: int
    media_type: str
    producer: str
    role: str
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class PublicationResult:
    target: Path
    manifest_path: Path
    manifest_sha256: str
    artifacts: tuple[PublishedArtifact, ...]


def _exclusive_target_path(target: Path) -> Path:
    raw = Path(target)
    if not raw.name:
        raise ContractViolation("Publication target must name a revision directory")
    raw.parent.mkdir(parents=True, exist_ok=True)
    return raw.parent.resolve() / raw.name


def _safe_relative_path(value: str, *, reserved_name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractViolation("Artifact path must be a non-empty POSIX relative path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ContractViolation(f"Unsafe artifact path: {value!r}")
    if relative.as_posix() == reserved_name:
        raise ContractViolation(f"Artifact path is reserved for the manifest: {value!r}")
    return relative


def _validate_manifest_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or PurePosixPath(value).name != value
        or value in {".", ".."}
    ):
        raise ContractViolation("Manifest name must be one safe filename")
    return value


def _validate_specs(
    artifacts: Sequence[ArtifactSpec], manifest_name: str
) -> tuple[tuple[ArtifactSpec, PurePosixPath], ...]:
    if not artifacts:
        raise ContractViolation("At least one artifact is required")
    normalized: list[tuple[ArtifactSpec, PurePosixPath]] = []
    artifact_ids: set[str] = set()
    paths: set[str] = set()
    for spec in artifacts:
        if not isinstance(spec, ArtifactSpec):
            raise ContractViolation("Artifacts must be ArtifactSpec instances")
        if not spec.artifact_id or spec.artifact_id in artifact_ids:
            raise ContractViolation(f"Missing or duplicate artifact_id: {spec.artifact_id!r}")
        if not spec.media_type or not spec.producer:
            raise ContractViolation("Artifact media_type and producer are required")
        if spec.role not in {"source", "derived", "evidence"}:
            raise ContractViolation(f"Unsupported artifact role: {spec.role!r}")
        if not isinstance(spec.payload, bytes):
            raise ContractViolation(f"Artifact {spec.artifact_id} payload must be bytes")
        if any(not isinstance(parent, str) or not parent for parent in spec.derived_from):
            raise ContractViolation(f"Artifact {spec.artifact_id} has invalid ancestry")
        relative = _safe_relative_path(spec.relative_path, reserved_name=manifest_name)
        canonical_path = relative.as_posix()
        if canonical_path in paths:
            raise ContractViolation(f"Duplicate artifact path: {canonical_path}")
        artifact_ids.add(spec.artifact_id)
        paths.add(canonical_path)
        normalized.append((spec, relative))
    normalized.sort(key=lambda item: item[1].as_posix())
    return tuple(normalized)


def _remove_private_staging(path: Path | None) -> None:
    if path is not None and path.exists():
        shutil.rmtree(path)


def publish_revision(
    target: Path,
    artifacts: Sequence[ArtifactSpec],
    *,
    metadata: Mapping[str, Any] | None = None,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
) -> PublicationResult:
    """Publish one immutable revision via a verified sibling staging directory.

    All artifact files use the industrial core's exclusive atomic writer. The
    manifest is written only after every artifact hash and size has been
    verified. Publication uses an exclusive rename while holding a sibling
    lock; an existing target is never replaced.
    """

    manifest_name = _validate_manifest_name(manifest_name)
    normalized = _validate_specs(artifacts, manifest_name)
    metadata_payload = dict(metadata or {})
    canonical_json_bytes(metadata_payload)

    target_path = _exclusive_target_path(Path(target))
    if os.path.lexists(target_path):
        raise ContractViolation(f"Refusing to overwrite immutable revision: {target_path}")

    operation_id = uuid.uuid4().hex
    lock_path = target_path.parent / f".{target_path.name}.publish.lock"
    staging = target_path.parent / f".{target_path.name}.staging-{operation_id}"
    lock_acquired = False
    committed = False
    published: list[PublishedArtifact] = []

    try:
        write_bytes_atomic_exclusive(
            lock_path,
            canonical_json_bytes(
                {
                    "operation_id": operation_id,
                    "target_name": target_path.name,
                }
            ),
        )
        lock_acquired = True
        if os.path.lexists(target_path):
            raise ContractViolation(
                f"Publication target appeared after lock acquisition: {target_path}"
            )
        create_directory_exclusive(staging)

        for spec, relative in normalized:
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic_exclusive(destination, spec.payload)
            actual_hash = sha256_file(destination)
            actual_size = destination.stat().st_size
            expected_hash = hashlib.sha256(spec.payload).hexdigest()
            if actual_hash != expected_hash or actual_size != len(spec.payload):
                raise ContractViolation(
                    f"Post-write integrity verification failed: {relative.as_posix()}"
                )
            published.append(
                PublishedArtifact(
                    artifact_id=spec.artifact_id,
                    relative_path=relative.as_posix(),
                    sha256=actual_hash,
                    byte_size=actual_size,
                    media_type=spec.media_type,
                    producer=spec.producer,
                    role=spec.role,
                    derived_from=tuple(spec.derived_from),
                )
            )

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "metadata": metadata_payload,
            "publication": {
                "mode": "sibling_staging_then_exclusive_rename",
                "immutable": True,
                "manifest_written_last": True,
            },
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "path": item.relative_path,
                    "sha256": item.sha256,
                    "byte_size": item.byte_size,
                    "media_type": item.media_type,
                    "producer": item.producer,
                    "role": item.role,
                    "derived_from": list(item.derived_from),
                }
                for item in published
            ],
        }
        manifest_path = staging / manifest_name
        write_json_atomic_exclusive(manifest_path, manifest)
        verified = verify_publication(staging, manifest_name=manifest_name)
        if verified != manifest:
            raise ContractViolation("Manifest changed during staged verification")
        manifest_hash = sha256_file(manifest_path)

        if os.path.lexists(target_path):
            raise ContractViolation(f"Refusing to replace publication target: {target_path}")
        staging.rename(target_path)
        committed = True
        return PublicationResult(
            target=target_path,
            manifest_path=target_path / manifest_name,
            manifest_sha256=manifest_hash,
            artifacts=tuple(published),
        )
    finally:
        if not committed:
            _remove_private_staging(staging)
        if lock_acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def verify_publication(
    target: Path, *, manifest_name: str = DEFAULT_MANIFEST_NAME
) -> dict[str, Any]:
    """Fail closed unless a published or staged directory is internally exact."""

    manifest_name = _validate_manifest_name(manifest_name)
    root = Path(target)
    if not root.is_dir() or root.is_symlink():
        raise ContractViolation(f"Publication directory is missing or unsafe: {root}")
    manifest_path = root / manifest_name
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ContractViolation(f"Publication manifest is missing or unsafe: {manifest_path}")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ContractViolation("Unsupported publication manifest schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractViolation("Publication manifest has no artifacts")

    artifact_ids: set[str] = set()
    declared_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ContractViolation("Malformed artifact record")
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in artifact_ids:
            raise ContractViolation(f"Missing or duplicate artifact_id: {artifact_id!r}")
        relative = _safe_relative_path(str(item.get("path", "")), reserved_name=manifest_name)
        relative_text = relative.as_posix()
        if relative_text in declared_paths:
            raise ContractViolation(f"Duplicate artifact path: {relative_text}")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ContractViolation(f"Declared artifact is missing or unsafe: {relative_text}")
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256_PATTERN.fullmatch(expected_hash):
            raise ContractViolation(f"Invalid artifact hash: {relative_text}")
        if sha256_file(path) != expected_hash:
            raise ContractViolation(f"Artifact hash mismatch: {relative_text}")
        if item.get("byte_size") != path.stat().st_size:
            raise ContractViolation(f"Artifact size mismatch: {relative_text}")
        if not item.get("media_type") or not item.get("producer"):
            raise ContractViolation(f"Incomplete artifact provenance: {relative_text}")
        if item.get("role") not in {"source", "derived", "evidence"}:
            raise ContractViolation(f"Invalid artifact role: {relative_text}")
        derived_from = item.get("derived_from")
        if not isinstance(derived_from, list) or any(
            not isinstance(parent, str) or not parent for parent in derived_from
        ):
            raise ContractViolation(f"Invalid artifact ancestry: {relative_text}")
        artifact_ids.add(artifact_id)
        declared_paths.add(relative_text)

    actual_paths: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ContractViolation(f"Symlinks are forbidden in publications: {path}")
        if path.is_file():
            actual_paths.add(path.relative_to(root).as_posix())
    expected_paths = declared_paths | {manifest_name}
    if actual_paths != expected_paths:
        raise ContractViolation(
            "Publication file set differs from manifest: "
            f"missing={sorted(expected_paths - actual_paths)}, "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    return manifest
