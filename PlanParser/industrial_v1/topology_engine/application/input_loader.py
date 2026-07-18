from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from industrial_v1.core.contracts import sha256_file

from ..config import TopologyEngineConfig
from ..models import CoordinateFrame
from .contracts import (
    ArtifactReference,
    ArtifactReferenceError,
    FloorContractError,
    JOB_SCHEMA_VERSION,
    JobContractError,
    LoadedTopologyJob,
    RegionContractError,
    RegionInputReferences,
    RegionJob,
)


def load_json_object(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise JobContractError(f"JSON root must be an object: {path}")
    return value


def resolve_inside(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactReferenceError("Artifact path must be a non-empty string")
    root_resolved = Path(root).resolve(strict=True)
    if not root_resolved.is_dir():
        raise ArtifactReferenceError(f"Job root is not a directory: {root_resolved}")
    try:
        candidate = (root_resolved / value).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArtifactReferenceError(f"Input artifact does not exist: {value}") from exc
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ArtifactReferenceError(f"Path escapes topology job root: {value}") from exc
    if not candidate.is_file():
        raise ArtifactReferenceError(f"Input is not a regular file: {candidate}")
    return candidate


def validate_artifact_reference(
    root: Path, value: Mapping[str, Any], role: str
) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise ArtifactReferenceError(f"{role} must be an artifact reference object")
    path = resolve_inside(root, str(value.get("path", "")))
    actual = sha256_file(path)
    expected = value.get("sha256")
    if expected is not None and expected != actual:
        raise ArtifactReferenceError(
            f"SHA-256 mismatch for {role}: expected {expected}, found {actual}",
            details={"role": role, "expected": expected, "actual": actual},
        )
    root_resolved = Path(root).resolve(strict=True)
    return ArtifactReference(
        role=role,
        path=path,
        relative_path=path.relative_to(root_resolved).as_posix(),
        sha256=actual,
        byte_size=path.stat().st_size,
    )


def find_region_record(
    contract: Mapping[str, Any], region_id: str
) -> Mapping[str, Any]:
    regions = contract.get("regions")
    if not isinstance(regions, list):
        raise RegionContractError("Region contract has no regions array")
    matches = [
        item
        for item in regions
        if isinstance(item, Mapping) and item.get("id") == region_id
    ]
    if len(matches) != 1:
        raise RegionContractError(
            f"Expected exactly one region contract record for {region_id}, found {len(matches)}"
        )
    return matches[0]


def scope_floor_records(
    page_id: str, floor_records: Sequence[Mapping[str, Any]]
) -> tuple[tuple[dict[str, Any], ...], dict[str, str]]:
    scoped: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for item in floor_records:
        if not isinstance(item, Mapping):
            raise FloorContractError("Malformed floor-unit record")
        floor_id = str(item.get("id", "")).strip()
        if not floor_id:
            raise FloorContractError("Floor-unit record has no id")
        if floor_id in mapping:
            raise FloorContractError(f"Duplicate floor-unit id: {floor_id}")
        scoped_id = f"{page_id}:{floor_id}"
        record = dict(item)
        record["source_floor_id"] = floor_id
        record["id"] = scoped_id
        scoped.append(record)
        mapping[floor_id] = scoped_id
    return tuple(scoped), mapping


def _region_references(
    root: Path, region_id: str, value: Mapping[str, Any]
) -> RegionInputReferences:
    def reference(name: str) -> ArtifactReference:
        return validate_artifact_reference(
            root, value.get(name, {}), f"{region_id}:{name}"
        )

    return RegionInputReferences(
        source_image=reference("source_image"),
        region_contract=reference("region_contract"),
        text_input=reference("text_input"),
        linework=reference("linework"),
        wall_bands=reference("wall_bands"),
        baseline=reference("baseline"),
    )


def _region_config(
    base: TopologyEngineConfig, overrides: Mapping[str, Any], region_id: str
) -> TopologyEngineConfig:
    allowed = set(base.to_dict())
    unknown = set(overrides) - allowed
    if unknown:
        raise RegionContractError(
            f"Unknown config override(s) for {region_id}: {sorted(unknown)}"
        )
    merged = base.to_dict()
    merged.update(dict(overrides))
    return TopologyEngineConfig.from_dict(merged)


def load_topology_job(*, job_path: Path, root: Path) -> LoadedTopologyJob:
    root_resolved = Path(root).resolve(strict=True)
    job_resolved = Path(job_path).resolve(strict=True)
    job = load_json_object(job_resolved)
    if job.get("schema_version") != JOB_SCHEMA_VERSION:
        raise JobContractError("Unsupported topology-engine job schema")
    document_id = str(job.get("document_id", "")).strip()
    page_id = str(job.get("page_id", "")).strip()
    if not document_id or not page_id:
        raise JobContractError("document_id and page_id are required")

    config_ref = validate_artifact_reference(
        root_resolved, job.get("engine_config", {}), "engine_config"
    )
    floor_ref = validate_artifact_reference(
        root_resolved, job.get("floor_units", {}), "floor_units"
    )
    page_ref = validate_artifact_reference(
        root_resolved, job.get("page_image", {}), "page_image"
    )
    config = TopologyEngineConfig.from_dict(load_json_object(config_ref.path))
    floor_payload = load_json_object(floor_ref.path)
    floor_units = floor_payload.get("floor_units")
    if not isinstance(floor_units, list):
        raise FloorContractError("floor_units artifact has no floor_units array")
    scoped_floors, floor_scope = scope_floor_records(page_id, floor_units)

    raw_regions = job.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise RegionContractError("Job requires at least one region")
    regions: list[RegionJob] = []
    input_references: list[ArtifactReference] = [config_ref, floor_ref, page_ref]
    seen_region_ids: set[str] = set()
    for raw_region in raw_regions:
        if not isinstance(raw_region, Mapping):
            raise RegionContractError("Malformed region job")
        region_id = str(raw_region.get("region_id", "")).strip()
        floor_id = str(raw_region.get("floor_id", "")).strip()
        if not region_id or region_id in seen_region_ids:
            raise RegionContractError(f"Missing or duplicate region_id: {region_id!r}")
        if floor_id not in floor_scope:
            raise FloorContractError(
                f"Region {region_id} refers to unknown floor_id: {floor_id!r}"
            )
        seen_region_ids.add(region_id)
        text_adapter = str(raw_region.get("text_adapter", "")).strip()
        if not text_adapter:
            raise RegionContractError(f"Region {region_id} requires text_adapter")
        overrides = raw_region.get("config_overrides", {})
        if not isinstance(overrides, Mapping):
            raise RegionContractError(
                f"config_overrides must be an object: {region_id}"
            )
        references = _region_references(root_resolved, region_id, raw_region)
        record = find_region_record(
            load_json_object(references.region_contract.path), region_id
        )
        bbox = record.get("bbox_px")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise RegionContractError(f"Invalid bbox contract for {region_id}")
        frame = CoordinateFrame(
            page_id=page_id,
            region_id=region_id,
            bbox_page_px_xywh=tuple(map(int, bbox)),
            document_id=document_id,
        )
        regions.append(
            RegionJob(
                region_id=region_id,
                floor_id=floor_id,
                scoped_floor_id=floor_scope[floor_id],
                text_adapter=text_adapter,
                config=_region_config(config, overrides, region_id),
                config_overrides=dict(overrides),
                frame=frame,
                region_record=dict(record),
                references=references,
            )
        )
        input_references.extend(references.ordered())

    return LoadedTopologyJob(
        job_path=job_resolved,
        root=root_resolved,
        raw_job=dict(job),
        document_id=document_id,
        page_id=page_id,
        config=config,
        config_reference=config_ref,
        floor_units_reference=floor_ref,
        page_image_reference=page_ref,
        scoped_floor_records=scoped_floors,
        floor_scope=floor_scope,
        regions=tuple(regions),
        input_references=tuple(input_references),
        fail_on_baseline_difference=bool(job.get("fail_on_baseline_difference", True)),
    )


def load_region_payloads(region: RegionJob) -> dict[str, dict[str, Any]]:
    references = region.references
    return {
        "region_contract": load_json_object(references.region_contract.path),
        "text_input": load_json_object(references.text_input.path),
        "linework": load_json_object(references.linework.path),
        "wall_bands": load_json_object(references.wall_bands.path),
        "baseline": load_json_object(references.baseline.path),
    }


__all__ = [
    "find_region_record",
    "load_json_object",
    "load_region_payloads",
    "load_topology_job",
    "resolve_inside",
    "scope_floor_records",
    "validate_artifact_reference",
]
