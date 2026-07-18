from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from PIL import Image

from industrial_v1.core.contracts import canonical_json_bytes

from ..publication import ArtifactSpec
from ..rendering import compose_batch_review, encode_pdf, encode_png
from .contracts import JobContractError


class ComputationView(Protocol):
    region_id: str
    payload: Mapping[str, Any]


class RenderingView(Protocol):
    contact_sheet: Image.Image
    artifacts: Mapping[str, bytes]


@dataclass(frozen=True)
class ArtifactLayout:
    machine_directory: str = "machine"
    regions_directory: str = "regions"
    review_directory: str = "review"
    input_snapshot_filename: str = "input_snapshot.json"
    topology_filename: str = "text_space_topology.json"
    equivalence_filename: str = "equivalence_report.json"
    document_graph_filename: str = "document_graph.json"
    review_png_filename: str = "consolidation_review.png"
    review_pdf_filename: str = "consolidation_review.pdf"


@dataclass(frozen=True)
class FinalReview:
    image: Image.Image = field(repr=False, compare=False)
    graph_summary: Mapping[str, Any]
    region_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactAssembly:
    artifacts: tuple[ArtifactSpec, ...]
    review: FinalReview
    producer: str


def _graph_review_summary(document_graph: Mapping[str, Any]) -> dict[str, Any]:
    summary = document_graph.get("summary")
    if not isinstance(summary, Mapping):
        raise JobContractError("Document graph has no summary object")
    result = dict(summary)
    result["duplicate_id_count"] = int(result.get("duplicate_node_ids", 0)) + int(
        result.get("duplicate_edge_ids", 0)
    )
    result["dangling_edge_count"] = int(result.get("dangling_edge_endpoints", 0))
    return result


def _validated_region_views(
    computations: Sequence[ComputationView],
    renderings: Mapping[str, RenderingView],
) -> tuple[tuple[ComputationView, RenderingView], ...]:
    if not computations:
        raise JobContractError("Artifact assembly requires at least one region")
    pairs: list[tuple[ComputationView, RenderingView]] = []
    seen: set[str] = set()
    for computation in computations:
        region_id = str(computation.region_id)
        if not region_id or region_id in seen:
            raise JobContractError(f"Missing or duplicate computation region: {region_id!r}")
        if region_id not in renderings:
            raise JobContractError(f"Missing rendering for region: {region_id}")
        if not isinstance(computation.payload, Mapping):
            raise JobContractError(f"Malformed computation payload: {region_id}")
        rendering = renderings[region_id]
        if not isinstance(rendering.contact_sheet, Image.Image):
            raise JobContractError(f"Malformed contact sheet: {region_id}")
        if not isinstance(rendering.artifacts, Mapping):
            raise JobContractError(f"Malformed rendering artifacts: {region_id}")
        seen.add(region_id)
        pairs.append((computation, rendering))
    extras = set(renderings) - seen
    if extras:
        raise JobContractError(f"Renderings have no matching computation: {sorted(extras)}")
    return tuple(pairs)


def build_final_review(
    *,
    document_id: str,
    page_id: str,
    computations: Sequence[ComputationView],
    renderings: Mapping[str, RenderingView],
    equivalence_report: Mapping[str, Any],
    document_graph: Mapping[str, Any],
) -> FinalReview:
    pairs = _validated_region_views(computations, renderings)
    graph_summary = _graph_review_summary(document_graph)
    region_sheets: list[tuple[str, Image.Image, dict[str, Any]]] = []
    for computation, rendering in pairs:
        summary = computation.payload.get("summary")
        if not isinstance(summary, Mapping):
            raise JobContractError(
                f"Region payload has no summary: {computation.region_id}"
            )
        region_sheets.append(
            (computation.region_id, rendering.contact_sheet, dict(summary))
        )
    image = compose_batch_review(
        document_id=document_id,
        page_id=page_id,
        region_sheets=region_sheets,
        equivalence_ok=bool(equivalence_report.get("all_match")),
        graph_summary=graph_summary,
    )
    return FinalReview(
        image=image,
        graph_summary=graph_summary,
        region_ids=tuple(item[0].region_id for item in pairs),
    )


def _json_payload(value: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(dict(value)) + b"\n"


def assemble_artifact_specs(
    *,
    engine_version: str,
    document_id: str,
    page_id: str,
    input_snapshot: Mapping[str, Any],
    computations: Sequence[ComputationView],
    renderings: Mapping[str, RenderingView],
    equivalence_report: Mapping[str, Any],
    document_graph: Mapping[str, Any],
    layout: ArtifactLayout = ArtifactLayout(),
) -> ArtifactAssembly:
    pairs = _validated_region_views(computations, renderings)
    review = build_final_review(
        document_id=document_id,
        page_id=page_id,
        computations=computations,
        renderings=renderings,
        equivalence_report=equivalence_report,
        document_graph=document_graph,
    )
    producer = f"planparser.topology_engine/{engine_version}"
    snapshot_id = "batch:input_snapshot"
    artifacts: list[ArtifactSpec] = [
        ArtifactSpec(
            artifact_id=snapshot_id,
            relative_path=f"{layout.machine_directory}/{layout.input_snapshot_filename}",
            payload=_json_payload(input_snapshot),
            media_type="application/json",
            producer=producer,
            role="evidence",
        )
    ]
    topology_ids: list[str] = []
    sheet_ids: list[str] = []
    for computation, rendering in pairs:
        region_id = computation.region_id
        prefix = f"{layout.regions_directory}/{region_id}"
        topology_id = f"region:{region_id}:topology"
        topology_ids.append(topology_id)
        artifacts.append(
            ArtifactSpec(
                artifact_id=topology_id,
                relative_path=f"{prefix}/{layout.topology_filename}",
                payload=_json_payload(computation.payload),
                media_type="application/json",
                producer=producer,
                derived_from=(snapshot_id,),
            )
        )
        has_contact_sheet = False
        for filename, payload in sorted(rendering.artifacts.items()):
            if not isinstance(filename, str) or not filename.endswith(".png"):
                raise JobContractError(
                    f"Unsupported rendering artifact for {region_id}: {filename!r}"
                )
            if not isinstance(payload, bytes):
                raise JobContractError(
                    f"Rendering artifact payload must be bytes: {region_id}/{filename}"
                )
            artifact_id = f"region:{region_id}:{filename.removesuffix('.png')}"
            if filename == "text_space_topology_contact_sheet.png":
                sheet_ids.append(artifact_id)
                has_contact_sheet = True
            artifacts.append(
                ArtifactSpec(
                    artifact_id=artifact_id,
                    relative_path=f"{prefix}/{filename}",
                    payload=payload,
                    media_type="image/png",
                    producer=producer,
                    role="evidence",
                    derived_from=(topology_id,),
                )
            )
        if not has_contact_sheet:
            raise JobContractError(
                f"Region rendering lacks contact-sheet artifact: {region_id}"
            )

    equivalence_id = "batch:equivalence_report"
    graph_id = "page:document_graph"
    review_ancestry = tuple(sheet_ids) + (equivalence_id, graph_id)
    artifacts.extend(
        [
            ArtifactSpec(
                artifact_id=equivalence_id,
                relative_path=f"{layout.machine_directory}/{layout.equivalence_filename}",
                payload=_json_payload(equivalence_report),
                media_type="application/json",
                producer=producer,
                role="evidence",
                derived_from=tuple(topology_ids),
            ),
            ArtifactSpec(
                artifact_id=graph_id,
                relative_path=f"{layout.machine_directory}/{layout.document_graph_filename}",
                payload=_json_payload(document_graph),
                media_type="application/json",
                producer=producer,
                derived_from=tuple(topology_ids),
            ),
            ArtifactSpec(
                artifact_id="review:consolidation_png",
                relative_path=f"{layout.review_directory}/{layout.review_png_filename}",
                payload=encode_png(review.image),
                media_type="image/png",
                producer=producer,
                role="evidence",
                derived_from=review_ancestry,
            ),
            ArtifactSpec(
                artifact_id="review:consolidation_pdf",
                relative_path=f"{layout.review_directory}/{layout.review_pdf_filename}",
                payload=encode_pdf([review.image]),
                media_type="application/pdf",
                producer=producer,
                role="evidence",
                derived_from=review_ancestry,
            ),
        ]
    )
    return ArtifactAssembly(
        artifacts=tuple(artifacts), review=review, producer=producer
    )


__all__ = [
    "ArtifactAssembly",
    "ArtifactLayout",
    "ComputationView",
    "FinalReview",
    "RenderingView",
    "assemble_artifact_specs",
    "build_final_review",
]
