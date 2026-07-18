from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

import build_region_001_revision_001 as v1


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_001/revision_002"
)


def competition_boundary(region: np.ndarray, labels: np.ndarray, label: int) -> np.ndarray:
    eroded = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    perimeter = region & ~eroded
    competition = np.zeros(region.shape, dtype=bool)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shifted = np.roll(labels, shift=(dy, dx), axis=(0, 1))
        competition |= perimeter & (shifted > 0) & (shifted != label)
    return competition


def nearby_source_ids(
    point: list[int] | None,
    linework: dict,
    wall_bands: dict,
    used_line_ids: set[str],
    used_band_ids: set[str],
    tolerance: float = 7.0,
) -> list[str]:
    if point is None:
        return []
    x, y = map(float, point)
    sources: list[str] = []
    for item in linework.get("candidates", []):
        if item["id"] not in used_line_ids:
            continue
        (x1, y1), (x2, y2) = item["points_px"]
        if item["orientation"] == "horizontal":
            distance = abs(y - y1) if min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance else math.inf
        else:
            distance = abs(x - x1) if min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance else math.inf
        if distance <= tolerance:
            sources.append(item["id"])
    for item in wall_bands.get("candidates", []):
        if item["id"] not in used_band_ids:
            continue
        polygon = np.asarray(item["polygon_px"], dtype=np.float32)
        if cv2.pointPolygonTest(polygon, (x, y), True) >= -tolerance:
            sources.append(item["id"])
    return sorted(set(sources))


def boundary_sources(
    perimeter: np.ndarray,
    linework: dict,
    wall_bands: dict,
    used_line_ids: set[str],
    used_band_ids: set[str],
) -> list[dict]:
    near = cv2.dilate(perimeter.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    evidence: list[dict] = []
    height, width = perimeter.shape
    for item in linework.get("candidates", []):
        if item["id"] not in used_line_ids:
            continue
        mask = np.zeros((height, width), dtype=np.uint8)
        p1, p2 = [tuple(map(int, point)) for point in item["points_px"]]
        cv2.line(mask, p1, p2, 255, 3)
        pixels = int(((mask > 0) & near).sum())
        if pixels:
            evidence.append(
                {
                    "source_type": "raw_linework_candidate",
                    "source_id": item["id"],
                    "support_pixels_near_space_boundary": pixels,
                    "source_status": item["status"],
                    "source_abstained": item["abstained"],
                }
            )
    for item in wall_bands.get("candidates", []):
        if item["id"] not in used_band_ids:
            continue
        mask = np.zeros((height, width), dtype=np.uint8)
        polygon = np.asarray(item["polygon_px"], dtype=np.int32)
        cv2.polylines(mask, [polygon], True, 255, 3)
        pixels = int(((mask > 0) & near).sum())
        if pixels:
            evidence.append(
                {
                    "source_type": "parallel_edge_band_hypothesis",
                    "source_id": item["id"],
                    "support_pixels_near_space_boundary": pixels,
                    "source_status": item["status"],
                    "source_abstained": item["abstained"],
                }
            )
    return sorted(evidence, key=lambda item: (-item["support_pixels_near_space_boundary"], item["source_id"]))


def build_spaces_v2(
    labels: np.ndarray,
    barrier: np.ndarray,
    raw_barrier: np.ndarray,
    synthetic_closures: np.ndarray,
    text_nodes: list[dict],
    page_offset: tuple[int, int],
    linework: dict,
    wall_bands: dict,
    used_line_ids: set[str],
    used_band_ids: set[str],
) -> list[dict]:
    spaces: list[dict] = []
    observed_near = cv2.dilate((raw_barrier > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    synthetic_near = cv2.dilate((synthetic_closures > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    for node in [item for item in text_nodes if item["role_hypothesis"] == "space_name_seed"]:
        label = int(node["space_label_index"])
        region = labels == label
        ys, xs = np.where(region)
        if not len(xs):
            node["space_candidate_id"] = None
            continue
        eroded = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        perimeter = region & ~eroded
        perimeter_count = max(int(perimeter.sum()), 1)
        observed = perimeter & observed_near
        synthetic_only = perimeter & synthetic_near & ~observed_near
        competition = competition_boundary(region, labels, label)
        observed_ratio = float(observed.sum()) / perimeter_count
        synthetic_ratio = float(synthetic_only.sum()) / perimeter_count
        competition_ratio = float(competition.sum()) / perimeter_count
        unresolved_ratio = max(0.0, 1.0 - observed_ratio - synthetic_ratio - competition_ratio)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
        conditions = [
            (observed_ratio < 0.50, "observed_boundary_support_below_0.50"),
            (synthetic_ratio > 0.30, "large_boundary_support_from_temporary_gap_closure"),
            (competition_ratio > 0.25, "large_boundary_created_by_seed_competition"),
            (node["ocr_abstained"], "name_node_contains_abstained_ocr_evidence"),
        ]
        abstention_reasons = [reason for condition, reason in conditions if condition]
        abstained = bool(abstention_reasons)
        confidence = min(
            0.93,
            0.24
            + 0.48 * observed_ratio
            + 0.10 * synthetic_ratio
            + (0.08 if not node["ocr_abstained"] else 0.0)
            + (0.07 if len(xs) >= 500 else 0.0),
        )
        space_id = f"space_candidate_{label:03d}"
        node["space_candidate_id"] = space_id
        seed = tuple(map(int, node["expansion_seed_crop_px"]))
        rays = v1.ray_observations(seed, barrier, raw_barrier, synthetic_closures)
        for ray in rays:
            ray["nearby_source_ids"] = nearby_source_ids(
                ray["hit_crop_px"], linework, wall_bands, used_line_ids, used_band_ids
            )
        sources = boundary_sources(perimeter, linework, wall_bands, used_line_ids, used_band_ids)
        spaces.append(
            {
                "id": space_id,
                "name_text_node_id": node["id"],
                "name_hypothesis": node["canonical_space_name_hypothesis"],
                "bbox_crop_px_xywh": bbox,
                "bbox_page_px_xywh": [bbox[0] + page_offset[0], bbox[1] + page_offset[1], bbox[2], bbox[3]],
                "polygon_crop_px": v1.contour_polygon(region),
                "area_px2": int(region.sum()),
                "boundary_composition": {
                    "observed_geometry_ratio": round(observed_ratio, 6),
                    "synthetic_gap_closure_ratio": round(synthetic_ratio, 6),
                    "seed_competition_ratio": round(competition_ratio, 6),
                    "unresolved_ratio": round(unresolved_ratio, 6),
                },
                "boundary_evidence": sources,
                "confidence_uncalibrated": round(confidence, 6),
                "abstained": abstained,
                "abstention_reasons": abstention_reasons,
                "radial_boundary_observations": rays,
            }
        )
    return spaces


def add_boundary_edges(edges: list[dict], spaces: list[dict]) -> None:
    for space in spaces:
        for evidence in space["boundary_evidence"]:
            edges.append(
                {
                    "id": f"edge_{len(edges) + 1:03d}",
                    "relation": "bounded_by_candidate_evidence",
                    "from": space["id"],
                    "to": evidence["source_id"],
                    "target_type": evidence["source_type"],
                    "support_pixels": evidence["support_pixels_near_space_boundary"],
                    "status": "observed_relation_not_building_semantics",
                }
            )


def contact_sheet_v2(
    source: Image.Image,
    text_overlay: Image.Image,
    barrier_overlay: Image.Image,
    topology_overlay: Image.Image,
    nodes: list[dict],
    spaces: list[dict],
    edges: list[dict],
) -> Image.Image:
    panels = [
        v1.panel(source, "1. SORGENTE", "testo e geometria ancora sovrapposti nel raster"),
        v1.panel(text_overlay, "2. NODI TESTUALI", "verde=nome spazio; blu=oggetto; arancio/rosso=ruolo irrisolto"),
        v1.panel(barrier_overlay, "3. BARRIERE GEOMETRICHE", "blu=evidenza osservata; magenta=chiusura temporanea di gap"),
        v1.panel(topology_overlay, "4. ESPANSIONE TOPOLOGICA", "raggi dal nome alle barriere; ogni hit conserva gli ID delle evidenze vicine"),
    ]
    gap = 18
    header = 136
    footer = 330
    cell_w = source.width
    cell_h = source.height + 72
    canvas = Image.new("RGB", (cell_w * 2 + gap, header + cell_h * 2 + gap + footer), "#f3f4f6")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), "PLANPARSER - TESTO -> SPAZIO -> TOPOLOGIA r002", fill="#111827", font=v1.font(28, True))
    draw.text(
        (18, 50),
        "Il testo genera nodi semantici; le forme nascono dall'espansione fino a evidenze geometriche tracciate per ID.",
        fill="#991b1b",
        font=v1.font(16, True),
    )
    draw.text(
        (18, 80),
        f"nodi testo={len(nodes)}  semi spazio={sum(n['role_hypothesis'] == 'space_name_seed' for n in nodes)}  "
        f"spazi={len(spaces)}  archi grafo={len(edges)}",
        fill="#374151",
        font=v1.font(15),
    )
    draw.text((18, 106), "Osservato, chiuso temporaneamente e creato dalla competizione restano tre cause distinte.", fill="#4b5563", font=v1.font(14))
    positions = [(0, header), (cell_w + gap, header), (0, header + cell_h + gap), (cell_w + gap, header + cell_h + gap)]
    for item, position in zip(panels, positions):
        canvas.paste(item, position)
    y = header + cell_h * 2 + gap
    draw.rectangle((0, y, canvas.width - 1, canvas.height - 1), fill="white", outline="#9ca3af", width=2)
    draw.text((18, y + 12), "RETE PRODOTTA", fill="#111827", font=v1.font(19, True))
    draw.text(
        (18, y + 42),
        "Testo --names--> Spazio --bounded_by_candidate--> Linea/Band; Testo-oggetto --located_in--> Spazio; Spazio --adjacency_candidate--> Spazio.",
        fill="#374151",
        font=v1.font(14),
    )
    draw.text(
        (18, y + 69),
        "Le percentuali sotto separano O=osservato, G=gap chiuso temporaneamente, C=frontiera fra semi. Confidence non calibrata e mai usata come verità.",
        fill="#374151",
        font=v1.font(14),
    )
    draw.text((18, y + 100), "SPAZI", fill="#111827", font=v1.font(15, True))
    for index, space in enumerate(spaces):
        column = index // 4
        row = index % 4
        composition = space["boundary_composition"]
        text = (
            f"{space['id'].replace('space_candidate_', 'S')} {space['name_hypothesis']}  "
            f"O={composition['observed_geometry_ratio']:.2f} G={composition['synthetic_gap_closure_ratio']:.2f} "
            f"C={composition['seed_competition_ratio']:.2f}  "
            f"{'ASTENUTO' if space['abstained'] else 'CANDIDATO'}"
        )
        draw.text(
            (18 + column * (canvas.width // 2), y + 129 + row * 24),
            text,
            fill="#991b1b" if space["abstained"] else "#166534",
            font=v1.font(12),
        )
    bounded_edges = sum(edge["relation"] == "bounded_by_candidate_evidence" for edge in edges)
    adjacency_edges = sum(edge["relation"] == "candidate_topological_adjacency" for edge in edges)
    draw.text(
        (18, y + 234),
        f"Archi verso evidenze di confine={bounded_edges}; adiacenze candidate={adjacency_edges}. Dettagli completi e hit radiali nel JSON.",
        fill="#111827",
        font=v1.font(13, True),
    )
    draw.text(
        (18, y + 264),
        "NON DICHIARATO: muro, porta, finestra, stanza validata, proprietà, scala metrica o nord. Nessuna revisione umana.",
        fill="#991b1b",
        font=v1.font(13, True),
    )
    draw.text(
        (18, y + 291),
        "Le abbreviazioni conservano sempre il raw OCR; la forma normalizzata è una seconda proprietà separata.",
        fill="#4b5563",
        font=v1.font(13),
    )
    return canvas


def main() -> int:
    for path in (v1.SOURCE, v1.REGIONS, v1.OCR, v1.LINEWORK, v1.WALL_BANDS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    bgr = cv2.imread(str(v1.SOURCE), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read {v1.SOURCE}")
    source = v1.pil_from_bgr(bgr)
    height, width = bgr.shape[:2]
    regions = v1.load_json(v1.REGIONS)
    region_record = next(item for item in regions["regions"] if item["id"] == "region_001")
    page_offset = (int(region_record["bbox_px"][0]), int(region_record["bbox_px"][1]))
    ensemble = v1.load_json(v1.OCR)
    linework = v1.load_json(v1.LINEWORK)
    wall_bands = v1.load_json(v1.WALL_BANDS)
    text_nodes = v1.make_text_nodes(ensemble, width)
    raw_barrier, synthetic_closures, line_audit, band_audit = v1.build_barrier(
        width, height, linework, wall_bands, text_nodes
    )
    barrier = cv2.bitwise_or(cv2.dilate(raw_barrier, np.ones((3, 3), np.uint8), iterations=1), synthetic_closures)
    labels, seed_audit = v1.expand_from_text_nodes(barrier, text_nodes)
    used_line_ids = {item["id"] for item in line_audit if item["used_as_barrier"]}
    used_band_ids = {item["id"] for item in band_audit if item["used_as_barrier"]}
    spaces = build_spaces_v2(
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
    edges = v1.graph_edges(labels, text_nodes, spaces)
    add_boundary_edges(edges, spaces)
    for node in text_nodes:
        x, y = node["center_crop_px"]
        node["center_page_px"] = [round(x + page_offset[0], 3), round(y + page_offset[1], 3)]

    text_overlay = v1.draw_text_nodes(source, text_nodes)
    barrier_overlay = v1.draw_barrier(source, raw_barrier, synthetic_closures)
    topology_overlay = v1.draw_topology(source, labels, text_nodes, spaces)
    sheet = contact_sheet_v2(source, text_overlay, barrier_overlay, topology_overlay, text_nodes, spaces, edges)

    payload = {
        "schema_version": "planparser.industrial_v1.text-space-topology/1.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_candidates_with_explicit_boundary_composition_not_human_approved",
        "source": {
            "path": v1.SOURCE.relative_to(ROOT).as_posix(),
            "sha256": v1.sha256(v1.SOURCE),
            "width_px": width,
            "height_px": height,
            "bbox_page_px_xywh": region_record["bbox_px"],
        },
        "inputs": [
            {"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": v1.sha256(path)}
            for role, path in [
                ("region_contract", v1.REGIONS),
                ("ocr_text_nodes", v1.OCR),
                ("raw_linework", v1.LINEWORK),
                ("parallel_edge_band_hypotheses", v1.WALL_BANDS),
            ]
        ],
        "method": {
            "name": "text_anchored_geodesic_space_expansion_with_boundary_provenance",
            "text_geometry_separation": True,
            "expansion": "multi_source_four_connected_geodesic_wavefront",
            "boundary_composition": ["observed_geometry", "synthetic_gap_closure", "seed_competition", "unresolved"],
            "radial_hits_linked_to_source_ids": True,
            "space_boundaries_linked_to_source_ids": True,
            "confidence_calibrated": False,
        },
        "text_nodes": text_nodes,
        "geometry_barrier_audit": {
            "line_candidates": line_audit,
            "band_candidates": band_audit,
            "observed_barrier_pixels": int((raw_barrier > 0).sum()),
            "synthetic_gap_closure_pixels": int((synthetic_closures > 0).sum()),
        },
        "expansion_seed_audit": seed_audit,
        "space_candidates": spaces,
        "topology_edges": edges,
        "summary": {
            "text_node_count": len(text_nodes),
            "space_name_seed_count": sum(node["role_hypothesis"] == "space_name_seed" for node in text_nodes),
            "space_candidate_count": len(spaces),
            "space_candidate_abstained_count": sum(space["abstained"] for space in spaces),
            "topology_edge_count": len(edges),
            "bounded_by_evidence_edge_count": sum(edge["relation"] == "bounded_by_candidate_evidence" for edge in edges),
        },
        "explicit_non_claims": [
            "OCR glyphs are not geometric building lines",
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
    temporary = parent / f".revision_002.building-{uuid.uuid4().hex}"
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
