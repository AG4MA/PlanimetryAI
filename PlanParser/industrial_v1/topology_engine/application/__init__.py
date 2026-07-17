"""Application-layer contracts for topology job orchestration."""

from .artifact_assembly import (
    ArtifactAssembly,
    ArtifactLayout,
    FinalReview,
    assemble_artifact_specs,
    build_final_review,
)
from .batch_service import RegionExecution, execute_region, run_job
from .contracts import (
    ArtifactReference,
    ArtifactReferenceError,
    EQUIVALENCE_SCHEMA_VERSION,
    FloorContractError,
    INPUT_SNAPSHOT_SCHEMA_VERSION,
    JOB_SCHEMA_VERSION,
    JobContractError,
    LoadedTopologyJob,
    RegionContractError,
    RegionInputReferences,
    RegionJob,
)
from .input_loader import (
    find_region_record,
    load_json_object,
    load_region_payloads,
    load_topology_job,
    resolve_inside,
    scope_floor_records,
    validate_artifact_reference,
)
from .provenance import (
    JobProvenance,
    build_input_identity,
    build_input_snapshot,
    build_job_provenance,
    engine_source_digest,
    stable_job_id,
)
from .region_analysis import RegionComputation, compute_region, topology_summary
from .region_rendering import RegionRendering, render_region


__all__ = [
    "ArtifactAssembly",
    "ArtifactLayout",
    "ArtifactReference",
    "ArtifactReferenceError",
    "EQUIVALENCE_SCHEMA_VERSION",
    "FinalReview",
    "FloorContractError",
    "INPUT_SNAPSHOT_SCHEMA_VERSION",
    "JOB_SCHEMA_VERSION",
    "JobContractError",
    "JobProvenance",
    "LoadedTopologyJob",
    "RegionContractError",
    "RegionComputation",
    "RegionExecution",
    "RegionInputReferences",
    "RegionJob",
    "RegionRendering",
    "assemble_artifact_specs",
    "build_final_review",
    "build_input_identity",
    "build_input_snapshot",
    "build_job_provenance",
    "compute_region",
    "engine_source_digest",
    "execute_region",
    "find_region_record",
    "load_json_object",
    "load_region_payloads",
    "load_topology_job",
    "resolve_inside",
    "render_region",
    "run_job",
    "scope_floor_records",
    "stable_job_id",
    "topology_summary",
    "validate_artifact_reference",
]
