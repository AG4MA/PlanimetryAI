from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import TopologyEngineConfig
from ..models import CoordinateFrame


JOB_SCHEMA_VERSION = "planparser.topology-engine.job/1.0"
INPUT_SNAPSHOT_SCHEMA_VERSION = "planparser.topology-engine.input-snapshot/1.0"
EQUIVALENCE_SCHEMA_VERSION = "planparser.topology-engine.equivalence/1.0"


class JobContractError(ValueError):
    """Structured rejection of an invalid topology-engine job."""

    default_code = "TOPOLOGY_JOB_CONTRACT_INVALID"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.details = dict(details or {})


class ArtifactReferenceError(JobContractError):
    default_code = "TOPOLOGY_ARTIFACT_REFERENCE_INVALID"


class FloorContractError(JobContractError):
    default_code = "TOPOLOGY_FLOOR_CONTRACT_INVALID"


class RegionContractError(JobContractError):
    default_code = "TOPOLOGY_REGION_CONTRACT_INVALID"


@dataclass(frozen=True)
class ArtifactReference:
    role: str
    path: Path
    relative_path: str
    sha256: str
    byte_size: int

    def descriptor(self, *, include_size: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
        }
        if include_size:
            result["byte_size"] = self.byte_size
        return result


@dataclass(frozen=True)
class RegionInputReferences:
    source_image: ArtifactReference
    region_contract: ArtifactReference
    text_input: ArtifactReference
    linework: ArtifactReference
    wall_bands: ArtifactReference
    baseline: ArtifactReference

    def named(self) -> tuple[tuple[str, ArtifactReference], ...]:
        return (
            ("source_image", self.source_image),
            ("region_contract", self.region_contract),
            ("text_input", self.text_input),
            ("linework", self.linework),
            ("wall_bands", self.wall_bands),
            ("baseline", self.baseline),
        )

    def ordered(self) -> tuple[ArtifactReference, ...]:
        return tuple(reference for _, reference in self.named())

    def computation_descriptors(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "role": role,
                "path": reference.relative_path,
                "sha256": reference.sha256,
            }
            for role, reference in self.named()
            if role != "baseline"
        )


@dataclass(frozen=True)
class RegionJob:
    region_id: str
    floor_id: str
    scoped_floor_id: str
    text_adapter: str
    config: TopologyEngineConfig
    config_overrides: Mapping[str, Any]
    frame: CoordinateFrame
    region_record: Mapping[str, Any]
    references: RegionInputReferences


@dataclass(frozen=True)
class LoadedTopologyJob:
    job_path: Path
    root: Path
    raw_job: Mapping[str, Any]
    document_id: str
    page_id: str
    config: TopologyEngineConfig
    config_reference: ArtifactReference
    floor_units_reference: ArtifactReference
    page_image_reference: ArtifactReference
    scoped_floor_records: tuple[Mapping[str, Any], ...]
    floor_scope: Mapping[str, str]
    regions: tuple[RegionJob, ...]
    input_references: tuple[ArtifactReference, ...]
    fail_on_baseline_difference: bool

    def region(self, region_id: str) -> RegionJob:
        matches = [item for item in self.regions if item.region_id == region_id]
        if len(matches) != 1:
            raise RegionContractError(
                f"Expected exactly one loaded region {region_id}, found {len(matches)}"
            )
        return matches[0]


__all__ = [
    "ArtifactReference",
    "ArtifactReferenceError",
    "EQUIVALENCE_SCHEMA_VERSION",
    "FloorContractError",
    "INPUT_SNAPSHOT_SCHEMA_VERSION",
    "JOB_SCHEMA_VERSION",
    "JobContractError",
    "LoadedTopologyJob",
    "RegionContractError",
    "RegionInputReferences",
    "RegionJob",
]
