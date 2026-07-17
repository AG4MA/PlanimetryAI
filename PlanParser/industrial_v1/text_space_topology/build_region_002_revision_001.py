from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageDraw

import build_region_001_revision_001 as v1
import build_region_001_revision_002 as v2


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "atomic_v2/region_split/artifacts/scheda_catastale/page_0001/revision_002/region_002.png"
)
REGIONS = (
    ROOT
    / "atomic_v2/region_split/artifacts/scheda_catastale/page_0001/revision_002/regions.json"
)
TEXT_NODES = (
    ROOT
    / "industrial_v1/text_nodes/artifacts/scheda_catastale/region_002/revision_002/text_nodes.json"
)
LINEWORK = (
    ROOT
    / "atomic_v2/linework/artifacts/scheda_catastale/region_002/revision_002/linework.json"
)
WALL_BANDS = (
    ROOT
    / "atomic_v2/wall_bands/artifacts/scheda_catastale/region_002/revision_002/wall_bands.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_002/revision_001"
)


def node_texts(item: dict) -> list[str]:
    values: list[str] = []
    consensus = item.get("decision", {}).get("consensus_text")
    if consensus:
        values.append(str(consensus))
    for alternative in item.get("raw_alternatives", []):
        value = alternative.get("text_raw")
        if value and value not in values:
            values.append(str(value))
    return values


def role_for_texts(values: list[str]) -> tuple[str, str | None, list[str]]:
    normalized = {v1.normalize(value) for value in values}
    for value in normalized:
        if value in v1.ROOM_ALIASES:
            return "space_name_seed", v1.ROOM_ALIASES[value], [f"lexical_space_anchor:{value}"]
    if "altra uiu" in normalized or ({"altra", "uiu"} <= normalized):
        return "external_context_label", None, ["lexical_adjacent_unit_context"]
    return "unresolved_text", None, ["no_supported_role_mapping"]


def adapt_text_nodes(payload: dict) -> list[dict]:
    nodes: list[dict] = []
    for item in payload.get("text_nodes", []):
        values = node_texts(item)
        role, name, reasons = role_for_texts(values)
        bbox = list(map(float, item["bbox_pixels"]))
        nodes.append(
            {
                "id": item["node_id"],
                "source_text_node_ids": [item["node_id"]],
                "raw_text_alternatives": values,
                "bbox_crop_px_xyxy": bbox,
                "center_crop_px": list(map(float, item["center_pixels"])),
                "role_hypothesis": role,
                "canonical_space_name_hypothesis": name,
                "role_reasons": reasons + list(item.get("candidate_role", {}).get("evidence", [])),
                "source_candidate_role": item.get("candidate_role"),
                "ocr_classification": item.get("decision", {}).get("classification"),
                "ocr_abstained": bool(item.get("decision", {}).get("abstained")),
                "composite": False,
            }
        )

    vano = next(
        (node for node in nodes if any(v1.normalize(value) == "vano" for value in node["raw_text_alternatives"])),
        None,
    )
    scala = next(
        (
            node
            for node in nodes
            if any(v1.normalize(value) in {"scala", "cala"} for value in node["raw_text_alternatives"])
        ),
        None,
    )
    if vano and scala and math.dist(vano["center_crop_px"], scala["center_crop_px"]) <= 80:
        x1 = min(vano["bbox_crop_px_xyxy"][0], scala["bbox_crop_px_xyxy"][0])
        y1 = min(vano["bbox_crop_px_xyxy"][1], scala["bbox_crop_px_xyxy"][1])
        x2 = max(vano["bbox_crop_px_xyxy"][2], scala["bbox_crop_px_xyxy"][2])
        y2 = max(vano["bbox_crop_px_xyxy"][3], scala["bbox_crop_px_xyxy"][3])
        nodes = [node for node in nodes if node not in (vano, scala)]
        nodes.append(
            {
                "id": "text_node_composite_vano_scala",
                "source_text_node_ids": vano["source_text_node_ids"] + scala["source_text_node_ids"],
                "raw_text_alternatives": ["vano", "cala", "scala"],
                "bbox_crop_px_xyxy": [x1, y1, x2, y2],
                "center_crop_px": [round((x1 + x2) / 2, 3), round((y1 + y2) / 2, 3)],
                "role_hypothesis": "space_name_seed",
                "canonical_space_name_hypothesis": "vano scala",
                "role_reasons": [
                    "spatially_clustered_vano_and_scala_nodes",
                    "scala_reading_preserved_as_cala_vs_scala_conflict",
                ],
                "source_candidate_role": [vano["source_candidate_role"], scala["source_candidate_role"]],
                "ocr_classification": "composite_contains_conflict",
                "ocr_abstained": True,
                "composite": True,
            }
        )
    nodes.sort(key=lambda item: (item["center_crop_px"][1], item["center_crop_px"][0]))
    return nodes


def draw_text_nodes(source, nodes: list[dict]):
    out = source.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")
    role_color = {
        "space_name_seed": (22, 163, 74, 255),
        "external_context_label": (147, 51, 234, 255),
        "unresolved_text": (245, 158, 11, 255),
    }
    for node in nodes:
        x1, y1, x2, y2 = node["bbox_crop_px_xyxy"]
        color = role_color[node["role_hypothesis"]]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        cx, cy = node["center_crop_px"]
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
        label = node["id"].replace("text_node_", "T")
        label = label[:18]
        draw.rectangle((x1, max(0, y1 - 14), x1 + max(35, len(label) * 6), max(0, y1 - 1)), fill=(255, 255, 255, 225))
        draw.text((x1 + 1, max(0, y1 - 14)), label, fill=color, font=v1.font(9, True))
    return out


def topology_edges(labels: np.ndarray, text_nodes: list[dict], spaces: list[dict]) -> list[dict]:
    edges: list[dict] = []
    for space in spaces:
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:03d}",
                "relation": "names_space_candidate",
                "from": space["name_text_node_id"],
                "to": space["id"],
                "status": "hypothesis",
            }
        )
    space_by_label = {
        int(space["id"].split("_")[-1]): space
        for space in spaces
    }
    contacts: dict[tuple[int, int], int] = {}
    for dx, dy in ((1, 0), (0, 1)):
        shifted = np.roll(labels, shift=(-dy, -dx), axis=(0, 1))
        mask = (labels > 0) & (shifted > 0) & (labels != shifted)
        for a, b in zip(labels[mask].tolist(), shifted[mask].tolist()):
            key = tuple(sorted((int(a), int(b))))
            contacts[key] = contacts.get(key, 0) + 1
    for (a, b), count in sorted(contacts.items()):
        if a not in space_by_label or b not in space_by_label:
            continue
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:03d}",
                "relation": "candidate_topological_adjacency",
                "from": space_by_label[a]["id"],
                "to": space_by_label[b]["id"],
                "contact_length_px": count,
                "status": "competition_boundary_not_opening_proof",
            }
        )
    return edges


def main() -> int:
    for path in (SOURCE, REGIONS, TEXT_NODES, LINEWORK, WALL_BANDS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    bgr = cv2.imread(str(SOURCE), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read {SOURCE}")
    source = v1.pil_from_bgr(bgr)
    height, width = bgr.shape[:2]
    regions = v1.load_json(REGIONS)
    region_record = next(item for item in regions["regions"] if item["id"] == "region_002")
    page_offset = (int(region_record["bbox_px"][0]), int(region_record["bbox_px"][1]))
    text_payload = v1.load_json(TEXT_NODES)
    linework = v1.load_json(LINEWORK)
    wall_bands = v1.load_json(WALL_BANDS)
    text_nodes = adapt_text_nodes(text_payload)

    raw_barrier, synthetic_closures, line_audit, band_audit = v1.build_barrier(
        width, height, linework, wall_bands, text_nodes
    )
    barrier = cv2.bitwise_or(cv2.dilate(raw_barrier, np.ones((3, 3), np.uint8), iterations=1), synthetic_closures)
    labels, seed_audit = v1.expand_from_text_nodes(barrier, text_nodes)
    used_line_ids = {item["id"] for item in line_audit if item["used_as_barrier"]}
    used_band_ids = {item["id"] for item in band_audit if item["used_as_barrier"]}
    spaces = v2.build_spaces_v2(
        labels,
        barrier,
        raw_barrier,
        synthetic_closures,
        text_nodes,
        page_offset,
        linework,
        wall_bands,
        used_line_ids,
        used_band_ids,
    )
    edges = topology_edges(labels, text_nodes, spaces)
    v2.add_boundary_edges(edges, spaces)
    for node in text_nodes:
        x, y = node["center_crop_px"]
        node["center_page_px"] = [round(x + page_offset[0], 3), round(y + page_offset[1], 3)]

    text_overlay = draw_text_nodes(source, text_nodes)
    barrier_overlay = v1.draw_barrier(source, raw_barrier, synthetic_closures)
    topology_overlay = v1.draw_topology(source, labels, text_nodes, spaces)
    sheet = v2.contact_sheet_v2(source, text_overlay, barrier_overlay, topology_overlay, text_nodes, spaces, edges)

    payload = {
        "schema_version": "planparser.industrial_v1.text-space-topology/1.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_candidates_with_explicit_boundary_composition_not_human_approved",
        "source": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": v1.sha256(SOURCE),
            "width_px": width,
            "height_px": height,
            "bbox_page_px_xywh": region_record["bbox_px"],
        },
        "inputs": [
            {"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": v1.sha256(path)}
            for role, path in [
                ("region_contract", REGIONS),
                ("independent_text_nodes", TEXT_NODES),
                ("text_masked_linework", LINEWORK),
                ("text_masked_parallel_edge_bands", WALL_BANDS),
            ]
        ],
        "method": {
            "name": "text_anchored_geodesic_space_expansion_with_boundary_provenance",
            "text_geometry_separation": True,
            "linework_text_masked_upstream": True,
            "expansion": "multi_source_four_connected_geodesic_wavefront",
            "boundary_composition": ["observed_geometry", "synthetic_gap_closure", "seed_competition", "unresolved"],
            "external_context_nodes_do_not_seed_rooms": True,
            "radial_hits_linked_to_source_ids": True,
            "space_boundaries_linked_to_source_ids": True,
            "confidence_calibrated": False,
        },
        "text_nodes": text_nodes,
        "geometry_barrier_audit": {
            "line_candidates": line_audit,
            "band_candidates": band_audit,
            "upstream_text_contaminated_line_count": linework["summary"]["text_contaminated_candidate_count"],
            "upstream_retained_geometric_line_count": linework["summary"]["retained_geometric_candidate_count"],
            "observed_barrier_pixels": int((raw_barrier > 0).sum()),
            "synthetic_gap_closure_pixels": int((synthetic_closures > 0).sum()),
        },
        "expansion_seed_audit": seed_audit,
        "space_candidates": spaces,
        "topology_edges": edges,
        "summary": {
            "text_node_count": len(text_nodes),
            "space_name_seed_count": sum(node["role_hypothesis"] == "space_name_seed" for node in text_nodes),
            "external_context_node_count": sum(node["role_hypothesis"] == "external_context_label" for node in text_nodes),
            "unresolved_text_node_count": sum(node["role_hypothesis"] == "unresolved_text" for node in text_nodes),
            "space_candidate_count": len(spaces),
            "space_candidate_abstained_count": sum(space["abstained"] for space in spaces),
            "topology_edge_count": len(edges),
            "bounded_by_evidence_edge_count": sum(edge["relation"] == "bounded_by_candidate_evidence" for edge in edges),
        },
        "explicit_non_claims": [
            "OCR glyphs are not geometric building lines",
            "altra uiu is context and does not seed a room",
            "a normalized text value does not replace the preserved raw OCR value",
            "a text role hypothesis is not a validated semantic label",
            "a wavefront region is not a validated room",
            "temporary gap closures are not walls and do not prove doors",
            "competition boundaries are not observed physical boundaries",
            "topological contact does not prove a traversable opening",
            "walls, doors, windows, property membership, scale and north are not inferred",
            "no human approval or correction has been applied",
        ],
    }

    parent = OUTPUT.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".revision_001.building-{uuid.uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    artifacts: list[dict] = []
    for filename, image in [
        ("text_nodes_overlay.png", text_overlay),
        ("barrier_overlay.png", barrier_overlay),
        ("topology_overlay.png", topology_overlay),
        ("text_space_topology_contact_sheet.png", sheet),
    ]:
        path = temporary / filename
        image.save(path)
        artifacts.append({"path": filename, "sha256": v1.sha256(path), "media_type": "image/png"})
    json_path = temporary / "text_space_topology.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifacts.append({"path": json_path.name, "sha256": v1.sha256(json_path), "media_type": "application/json"})
    manifest_path = temporary / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "planparser.artifact-manifest/1.0", "artifacts": artifacts}, indent=2) + "\n",
        encoding="utf-8",
    )
    for artifact in artifacts:
        if v1.sha256(temporary / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Hash verification failed: {artifact['path']}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")
    temporary.rename(OUTPUT)
    print(OUTPUT / "text_space_topology_contact_sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
