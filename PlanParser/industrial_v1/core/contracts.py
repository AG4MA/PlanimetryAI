from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


CORE_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "planparser.run-manifest/1.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ContractViolation(ValueError):
    """Raised when data would leave the industrial contract in an unsafe state."""


class RunState(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABSTAINED = "abstained"


_ALLOWED_TRANSITIONS = {
    RunState.PLANNED: frozenset(
        {RunState.RUNNING, RunState.FAILED, RunState.ABSTAINED}
    ),
    RunState.RUNNING: frozenset(
        {RunState.COMPLETED, RunState.FAILED, RunState.ABSTAINED}
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.ABSTAINED: frozenset(),
}


def assert_transition(current: RunState, target: RunState) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ContractViolation(
            f"Illegal run-state transition: {current.value} -> {target.value}"
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_snapshot() -> dict[str, str]:
    return {
        "planparser_industrial_core": CORE_VERSION,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
    }


def deterministic_run_id(
    input_sha256: str,
    config_snapshot: Mapping[str, Any],
    versions: Mapping[str, Any],
) -> str:
    if not SHA256_PATTERN.fullmatch(input_sha256):
        raise ContractViolation("input_sha256 is not a lowercase SHA-256 digest")
    identity = {
        "input_sha256": input_sha256,
        "config_snapshot": dict(config_snapshot),
        "version_snapshot": dict(versions),
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"run_{digest[:24]}"


@dataclass(frozen=True)
class ErrorRecord:
    code: str
    stage: str
    message: str
    retryable: bool
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AbstentionRecord:
    reason_code: str
    stage: str
    scope_ref: str
    explanation: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    uri: str
    sha256: str
    byte_size: int
    media_type: str
    producer: str
    derived_from: tuple[str, ...] = ()
    role: str = "derived"

    def validate(self) -> None:
        if not self.artifact_id or not self.producer or not self.media_type:
            raise ContractViolation("Artifact identifiers, producer and media type are required")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ContractViolation(f"Artifact {self.artifact_id} has an invalid SHA-256")
        if self.byte_size < 0:
            raise ContractViolation(f"Artifact {self.artifact_id} has a negative byte size")
        if self.role not in {"source", "derived", "evidence"}:
            raise ContractViolation(f"Artifact {self.artifact_id} has an unknown role")


class ArtifactRegistry:
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}

    def register_existing_file(
        self,
        *,
        artifact_id: str,
        path: Path,
        media_type: str,
        producer: str,
        derived_from: Iterable[str] = (),
        role: str = "derived",
    ) -> ArtifactRecord:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ContractViolation(f"Artifact is not a regular file: {resolved}")
        if artifact_id in self._records:
            raise ContractViolation(f"Duplicate artifact_id: {artifact_id}")
        parents = tuple(derived_from)
        missing = [parent for parent in parents if parent not in self._records]
        if missing:
            raise ContractViolation(
                f"Artifact {artifact_id} references unknown ancestors: {missing}"
            )
        record = ArtifactRecord(
            artifact_id=artifact_id,
            uri=resolved.as_uri(),
            sha256=sha256_file(resolved),
            byte_size=resolved.stat().st_size,
            media_type=media_type,
            producer=producer,
            derived_from=parents,
            role=role,
        )
        record.validate()
        self._records[artifact_id] = record
        return record

    def records(self) -> tuple[ArtifactRecord, ...]:
        # Registration order is the provenance topological order: ancestors are
        # required to exist before descendants can be registered.
        return tuple(self._records.values())


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    revision: int
    state: RunState
    input_sha256: str
    created_at_utc: str
    config_snapshot: Mapping[str, Any]
    version_snapshot: Mapping[str, Any]
    artifacts: tuple[ArtifactRecord, ...]
    errors: tuple[ErrorRecord, ...] = ()
    abstentions: tuple[AbstentionRecord, ...] = ()
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ContractViolation("Unsupported run-manifest schema version")
        if not re.fullmatch(r"run_[0-9a-f]{24}", self.run_id):
            raise ContractViolation("Malformed run_id")
        if self.revision < 1:
            raise ContractViolation("Revision must be positive")
        if not SHA256_PATTERN.fullmatch(self.input_sha256):
            raise ContractViolation("Manifest input_sha256 is invalid")
        artifact_ids: set[str] = set()
        source_matches = 0
        for artifact in self.artifacts:
            artifact.validate()
            if artifact.artifact_id in artifact_ids:
                raise ContractViolation(f"Duplicate artifact_id: {artifact.artifact_id}")
            unknown = set(artifact.derived_from) - artifact_ids
            if unknown:
                raise ContractViolation(
                    f"Artifact {artifact.artifact_id} has unordered/unknown ancestry: {sorted(unknown)}"
                )
            artifact_ids.add(artifact.artifact_id)
            if artifact.role == "source" and artifact.sha256 == self.input_sha256:
                source_matches += 1
        if source_matches != 1:
            raise ContractViolation(
                "Manifest must contain exactly one source artifact matching input_sha256"
            )
        if self.state == RunState.FAILED and not self.errors:
            raise ContractViolation("A failed run requires at least one structured error")
        if self.state == RunState.ABSTAINED and not self.abstentions:
            raise ContractViolation("An abstained run requires at least one abstention")
        if self.state == RunState.COMPLETED and self.errors:
            raise ContractViolation("A completed run cannot contain errors")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload
