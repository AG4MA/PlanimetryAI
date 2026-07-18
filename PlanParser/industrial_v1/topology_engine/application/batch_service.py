from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .. import BATCH_SCHEMA_VERSION, ENGINE_VERSION
from ..document_graph import aggregate_document_graph, validate_document_graph
from ..publication import PublicationResult, publish_revision
from ..regression import compare_with_baseline
from .artifact_assembly import ArtifactAssembly, assemble_artifact_specs
from .contracts import EQUIVALENCE_SCHEMA_VERSION, JobContractError, LoadedTopologyJob, RegionJob
from .input_loader import load_region_payloads, load_topology_job
from .provenance import JobProvenance, build_job_provenance
from .region_analysis import RegionComputation, compute_region
from .region_rendering import RegionRendering, render_region


@dataclass(frozen=True)
class RegionExecution:
    computation: RegionComputation
    rendering: RegionRendering
    equivalence: Mapping[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _decode_bgr(path: Path, role: str) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise JobContractError(f"Cannot decode {role}: {path}")
    return image


def _source_descriptor(region: RegionJob) -> dict[str, Any]:
    source = region.references.source_image
    return {"path": source.relative_path, "sha256": source.sha256}


def _input_descriptors(region: RegionJob) -> tuple[dict[str, Any], ...]:
    return region.references.computation_descriptors()


def execute_region(job: LoadedTopologyJob, region: RegionJob) -> RegionExecution:
    payloads = load_region_payloads(region)
    source_bgr = _decode_bgr(
        region.references.source_image.path, f"{region.region_id}:source_image"
    )
    computation = compute_region(
        region_id=region.region_id,
        floor_id=region.floor_id,
        source_bgr=source_bgr,
        frame=region.frame,
        text_payload=payloads["text_input"],
        text_adapter=region.text_adapter,
        linework=payloads["linework"],
        wall_bands=payloads["wall_bands"],
        config=region.config,
        source_descriptor=_source_descriptor(region),
        input_descriptors=_input_descriptors(region),
    )
    comparison = compare_with_baseline(payloads["baseline"], computation.payload)
    equivalence = {
        "region_id": region.region_id,
        "baseline_path": region.references.baseline.relative_path,
        "baseline_sha256": region.references.baseline.sha256,
        **comparison,
    }
    if job.fail_on_baseline_difference and not comparison["match"]:
        raise JobContractError(
            f"Golden regression failed for {region.region_id}: "
            f"{comparison['differences'][:1]}"
        )
    return RegionExecution(
        computation=computation,
        rendering=render_region(source_bgr, computation),
        equivalence=equivalence,
    )


def _equivalence_report(
    executions: tuple[RegionExecution, ...]
) -> dict[str, Any]:
    regions = [dict(item.equivalence) for item in executions]
    return {
        "schema_version": EQUIVALENCE_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "all_match": all(item["match"] for item in regions),
        "regions": regions,
    }


def _document_graph(
    job: LoadedTopologyJob,
    page_bgr: np.ndarray,
    executions: tuple[RegionExecution, ...],
) -> dict[str, Any]:
    regional_payloads = {
        f"{job.page_id}:{item.computation.region_id}": item.computation.payload
        for item in executions
    }
    region_to_floor = {
        f"{job.page_id}:{region.region_id}": region.scoped_floor_id
        for region in job.regions
    }
    height, width = page_bgr.shape[:2]
    graph = aggregate_document_graph(
        document_id=job.document_id,
        page_id=job.page_id,
        floor_units=job.scoped_floor_records,
        regional_payloads=regional_payloads,
        region_to_floor=region_to_floor,
        page_attributes={
            "source_path": job.page_image_reference.relative_path,
            "source_sha256": job.page_image_reference.sha256,
            "width_px": width,
            "height_px": height,
        },
    )
    validate_document_graph(graph)
    return graph


def _provenance(job: LoadedTopologyJob) -> JobProvenance:
    return build_job_provenance(
        engine_root=Path(__file__).resolve().parents[1],
        engine_version=ENGINE_VERSION,
        config_snapshot=job.config.to_dict(),
        raw_job=job.raw_job,
        input_references=job.input_references,
    )


def _assembly(
    job: LoadedTopologyJob,
    executions: tuple[RegionExecution, ...],
    equivalence: Mapping[str, Any],
    graph: Mapping[str, Any],
    provenance: JobProvenance,
) -> ArtifactAssembly:
    computations = tuple(item.computation for item in executions)
    renderings = {
        item.computation.region_id: item.rendering for item in executions
    }
    return assemble_artifact_specs(
        engine_version=ENGINE_VERSION,
        document_id=job.document_id,
        page_id=job.page_id,
        input_snapshot=provenance.input_snapshot,
        computations=computations,
        renderings=renderings,
        equivalence_report=equivalence,
        document_graph=graph,
    )


def run_job(
    *,
    job_path: Path,
    output: Path,
    planparser_root: Path | None = None,
) -> PublicationResult:
    root = (
        Path(planparser_root).resolve(strict=True)
        if planparser_root is not None
        else Path(__file__).resolve().parents[3]
    )
    job = load_topology_job(job_path=job_path, root=root)
    page_bgr = _decode_bgr(job.page_image_reference.path, "page_image")
    executions = tuple(execute_region(job, region) for region in job.regions)
    equivalence = _equivalence_report(executions)
    graph = _document_graph(job, page_bgr, executions)
    provenance = _provenance(job)
    assembly = _assembly(job, executions, equivalence, graph, provenance)
    metadata = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "job_id": provenance.job_id,
        "execution_id": "execution_" + uuid.uuid4().hex,
        "created_at_utc": _utc_now(),
        "engine_version": ENGINE_VERSION,
        "engine_source_sha256": provenance.engine_source_sha256,
        "document_id": job.document_id,
        "page_id": job.page_id,
        "region_count": len(executions),
        "baseline_equivalence": bool(equivalence["all_match"]),
        "document_graph_summary": graph["summary"],
    }
    return publish_revision(output, assembly.artifacts, metadata=metadata)


__all__ = ["RegionExecution", "execute_region", "run_job"]
