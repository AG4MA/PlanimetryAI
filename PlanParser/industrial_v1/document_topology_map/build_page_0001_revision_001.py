from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "atomic_v2/ingest/artifacts/scheda_catastale/pages/page_0001.png"
SHEET_MAP = (
    ROOT
    / "industrial_v1/sheet_mapper/artifacts/scheda_catastale/page_0001/revision_001/sheet_map.json"
)
FLOOR_UNITS = (
    ROOT
    / "industrial_v1/floor_units/artifacts/scheda_catastale/page_0001/revision_001/floor_units.json"
)
REGION1_TOPOLOGY = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_001/revision_002/text_space_topology.json"
)
REGION1_OVERLAY = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_001/revision_002/topology_overlay.png"
)
REGION2_TOPOLOGY = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_002/revision_001/text_space_topology.json"
)
REGION2_OVERLAY = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_002/revision_001/topology_overlay.png"
)
COMPASS = (
    ROOT
    / "industrial_v1/compass_observation/artifacts/scheda_catastale/page_0001/revision_002/compass_observation.json"
)
CONNECTIONS = (
    ROOT
    / "industrial_v1/space_connections/artifacts/scheda_catastale/page_0001/revision_001/space_connections.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/document_topology_map/artifacts/scheda_catastale/page_0001/revision_001"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def xywh(value: dict | list) -> tuple[int, int, int, int]:
    if isinstance(value, dict):
        return int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"])
    return tuple(map(int, value))


def prefix(region_id: str, value: str) -> str:
    return f"{region_id}:{value}"


def compass_observation(compass: dict) -> dict:
    observations = compass["observations"]
    if isinstance(observations, list):
        if len(observations) != 1:
            raise ValueError(f"Expected exactly one compass observation, found {len(observations)}")
        return observations[0]
    return observations


def remap_region_graph(region_id: str, topology: dict) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    nodes.append(
        {
            "id": region_id,
            "type": "analysis_region_candidate",
            "bbox_page_px_xywh": topology["source"]["bbox_page_px_xywh"],
            "status": topology["status"],
        }
    )
    for item in topology["text_nodes"]:
        nodes.append(
            {
                "id": prefix(region_id, item["id"]),
                "type": "text_node",
                "raw_text_alternatives": item["raw_text_alternatives"],
                "role_hypothesis": item["role_hypothesis"],
                "canonical_space_name_hypothesis": item.get("canonical_space_name_hypothesis"),
                "center_page_px": item["center_page_px"],
                "ocr_abstained": item["ocr_abstained"],
            }
        )
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:04d}",
                "relation": "region_contains_text_node",
                "from": region_id,
                "to": prefix(region_id, item["id"]),
                "status": "observed_hierarchy",
            }
        )
    for item in topology["space_candidates"]:
        nodes.append(
            {
                "id": prefix(region_id, item["id"]),
                "type": "space_candidate",
                "name_hypothesis": item["name_hypothesis"],
                "bbox_page_px_xywh": item["bbox_page_px_xywh"],
                "abstained": item["abstained"],
                "boundary_composition": item["boundary_composition"],
            }
        )
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:04d}",
                "relation": "region_contains_space_candidate",
                "from": region_id,
                "to": prefix(region_id, item["id"]),
                "status": "automatic_candidate",
            }
        )
    for item in topology["topology_edges"]:
        source = item["from"]
        target = item["to"]
        if source.startswith(("text_node", "space_candidate")):
            source = prefix(region_id, source)
        if target.startswith(("text_node", "space_candidate")):
            target = prefix(region_id, target)
        edges.append(
            {
                "id": f"edge_{len(edges) + 1:04d}",
                "relation": item["relation"],
                "from": source,
                "to": target,
                "status": item.get("status"),
                "source_edge_id": item["id"],
                "region_id": region_id,
            }
        )
    return nodes, edges


def build_graph(sheet: dict, floors: dict, topologies: dict[str, dict], compass: dict, connections: dict) -> dict:
    nodes = [
        {"id": "scheda_catastale", "type": "document"},
        {"id": "page_0001", "type": "page", "width_px": 2481, "height_px": 3508},
    ]
    edges = [
        {
            "id": "edge_document_page",
            "relation": "document_contains_page",
            "from": "scheda_catastale",
            "to": "page_0001",
            "status": "observed_hierarchy",
        }
    ]
    floor_to_region = {"FR-001": "region_001", "FR-002": "region_002"}
    for floor in floors["floor_units"]:
        nodes.append(
            {
                "id": floor["id"],
                "type": "floor_region_candidate",
                "title_text_raw": floor["title_text_raw"],
                "designation_raw": floor["designation_raw"],
                "bbox_page_px": floor["bbox_page_px"],
                "abstained": floor["abstained_from_sheet_mapper"],
            }
        )
        edges.append(
            {
                "id": f"edge_page_{floor['id']}",
                "relation": "page_contains_floor_region_candidate",
                "from": "page_0001",
                "to": floor["id"],
                "status": "automatic_candidate",
            }
        )
        region_id = floor_to_region[floor["id"]]
        edges.append(
            {
                "id": f"edge_{floor['id']}_{region_id}",
                "relation": "floor_region_contains_analysis_region",
                "from": floor["id"],
                "to": region_id,
                "status": "coordinate_containment_observed",
            }
        )

    for region_id, topology in topologies.items():
        region_nodes, region_edges = remap_region_graph(region_id, topology)
        nodes.extend(region_nodes)
        edges.extend(region_edges)

    compass_item = compass_observation(compass)
    nodes.append(
        {
            "id": compass_item["id"],
            "type": "sheet_level_directional_compass_glyph_candidate",
            "bbox_page_px": compass_item["bbox_page_px"],
            "axis_angle_clockwise_from_page_up_deg": compass_item["direction_observation"]["pointed_end_angle_clockwise_from_page_up_deg"],
            "north_direction_asserted": compass_item["semantic_decision"]["north_direction_asserted"],
            "abstained": compass_item["semantic_decision"]["status"] == "abstained",
        }
    )
    edges.append(
        {
            "id": "edge_page_compass",
            "relation": "page_contains_sheet_level_observation",
            "from": "page_0001",
            "to": compass_item["id"],
            "status": "automatic_candidate",
        }
    )

    for connection in connections["connection_candidates"]:
        region_id = connection["region_id"]
        edges.append(
            {
                "id": f"edge_connection_{connection['id']}",
                "relation": "candidate_connection_via_temporarily_closed_gap",
                "from": prefix(region_id, connection["from_space_id"]),
                "to": prefix(region_id, connection["to_space_id"]),
                "status": connection["status"],
                "evidence_id": connection["id"],
                "abstained": connection["abstained"],
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "explicit_absent_edges": [
            {
                "scope": "cross_floor_space_connections",
                "status": "not_inferred",
                "reason": "no cross-floor relation evidence has been modeled",
            },
            {
                "scope": "compass_axis_to_north_semantics",
                "status": "not_asserted",
                "reason": "directional axis observed but north token absent or unreliable",
            },
        ],
    }


def draw_document_map(
    page: Image.Image,
    sheet: dict,
    floors: dict,
    topologies: dict[str, dict],
    compass: dict,
    connections: dict,
) -> Image.Image:
    mapped = page.convert("RGB").copy()
    for region_id, overlay_path in [("region_001", REGION1_OVERLAY), ("region_002", REGION2_OVERLAY)]:
        topology = topologies[region_id]
        x, y, width, height = xywh(topology["source"]["bbox_page_px_xywh"])
        overlay = Image.open(overlay_path).convert("RGB")
        if overlay.size != (width, height):
            raise ValueError(f"Topology overlay size mismatch for {region_id}")
        mapped.paste(overlay, (x, y))

    draw = ImageDraw.Draw(mapped, "RGBA")
    floor_colors = {"FR-001": (14, 165, 233, 255), "FR-002": (2, 132, 199, 255)}
    for floor in floors["floor_units"]:
        x, y, width, height = xywh(floor["bbox_page_px"])
        color = floor_colors[floor["id"]]
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline=color, width=5)
        label = f"{floor['id']} {floor['title_text_raw']}"
        draw.rectangle((x + 5, y + 5, x + 5 + len(label) * 15, y + 39), fill=(255, 255, 255, 235))
        draw.text((x + 9, y + 8), label, fill=color, font=font(24, True))

    header = sheet["observations"]["header_titleblock"]["bbox_page_px"]
    x, y, width, height = xywh(header)
    draw.rectangle((x, y, x + width, y + height), outline=(192, 38, 211, 255), width=4)
    draw.text((x + 8, y + 8), "SHEET-LEVEL: cartiglio/header", fill=(126, 34, 206, 255), font=font(20, True))

    observation = compass_observation(compass)
    x, y, width, height = xywh(observation["bbox_page_px"])
    draw.rectangle((x, y, x + width, y + height), outline=(220, 38, 38, 255), width=6)
    center = observation["direction_observation"]["axis_center_page_px"]
    pointed = observation["direction_observation"]["pointed_end_page_px"]
    draw.line((center["x"], center["y"], pointed["x"], pointed["y"]), fill=(245, 158, 11, 255), width=8)
    draw.text((x - 20, y - 34), "CO-001 asse osservato; NORD non dichiarato", fill=(185, 28, 28, 255), font=font(20, True))

    sidebar_width = 1060
    canvas = Image.new("RGB", (mapped.width + sidebar_width, mapped.height), "#f8fafc")
    canvas.paste(mapped, (0, 0))
    sx = mapped.width
    side = ImageDraw.Draw(canvas)
    side.rectangle((sx, 0, canvas.width - 1, canvas.height - 1), fill="#f8fafc", outline="#94a3b8", width=2)
    side.text((sx + 36, 32), "PLANPARSER", fill="#111827", font=font(38, True))
    side.text((sx + 36, 82), "MAPPA TOPOLOGICA DOCUMENTO r001", fill="#111827", font=font(27, True))
    side.text((sx + 36, 129), "page_0001 / coordinate raster sorgente", fill="#475569", font=font(18))

    r1 = topologies["region_001"]["summary"]
    r2 = topologies["region_002"]["summary"]
    conn = connections["summary"]
    side.text((sx + 36, 184), "STRUTTURA", fill="#111827", font=font(22, True))
    tree_lines = [
        "scheda_catastale",
        "  └─ page_0001",
        "      ├─ FR-001  Piano Primo",
        f"      │   └─ region_001: {r1['text_node_count']} testi, {r1['space_candidate_count']} spazi",
        "      ├─ FR-002  Piano Terra",
        f"      │   └─ region_002: {r2['text_node_count']} testi, {r2['space_candidate_count']} spazi",
        "      ├─ HC-001  cartiglio/header",
        "      └─ CO-001  bussola sheet-level",
    ]
    for index, line in enumerate(tree_lines):
        side.text((sx + 36, 225 + index * 31), line, fill="#334155", font=font(18))

    y0 = 500
    side.text((sx + 36, y0), "PIANO PRIMO — SPAZI CANDIDATI", fill="#0369a1", font=font(21, True))
    y0 += 39
    for space in topologies["region_001"]["space_candidates"]:
        status = "ASTENUTO" if space["abstained"] else "candidato"
        side.text((sx + 52, y0), f"• {space['name_hypothesis']}  [{status}]", fill="#991b1b" if space["abstained"] else "#166534", font=font(17))
        y0 += 29

    y0 += 21
    side.text((sx + 36, y0), "PIANO TERRA — SPAZI CANDIDATI", fill="#0369a1", font=font(21, True))
    y0 += 39
    for space in topologies["region_002"]["space_candidates"]:
        status = "ASTENUTO" if space["abstained"] else "candidato"
        side.text((sx + 52, y0), f"• {space['name_hypothesis']}  [{status}]", fill="#991b1b" if space["abstained"] else "#166534", font=font(17))
        y0 += 29
    side.text((sx + 52, y0 + 4), "• altra uiu  [contesto esterno, nessuno spazio]", fill="#7e22ce", font=font(17))

    y0 += 80
    side.text((sx + 36, y0), "CONTEGGI DEL GRAFO", fill="#111827", font=font(22, True))
    metrics = [
        f"Nodi testuali: {r1['text_node_count'] + r2['text_node_count']}",
        f"Spazi candidati: {r1['space_candidate_count'] + r2['space_candidate_count']}",
        f"Spazi astenuti: {r1['space_candidate_abstained_count'] + r2['space_candidate_abstained_count']}",
        f"Relazioni bounded-by: {r1['bounded_by_evidence_edge_count'] + r2['bounded_by_evidence_edge_count']}",
        f"Connessioni da gap: {conn['connection_hypothesis_count']} (tutte astenute)",
        "Bussole candidate: 1; Nord dichiarato: 0",
    ]
    for index, metric in enumerate(metrics):
        side.text((sx + 52, y0 + 40 + index * 30), metric, fill="#334155", font=font(17))

    y0 += 260
    side.text((sx + 36, y0), "LEGENDA", fill="#111827", font=font(22, True))
    legends = [
        ((14, 165, 233), "fascia-piano"),
        ((22, 163, 74), "spazio candidato"),
        ((245, 158, 11), "evidenza/relazione astenuta"),
        ((147, 51, 234), "contesto esterno"),
        ((220, 38, 38), "bussola; semantica Nord astenuta"),
    ]
    for index, (color, label) in enumerate(legends):
        yy = y0 + 42 + index * 37
        side.rectangle((sx + 52, yy, sx + 76, yy + 24), fill=color)
        side.text((sx + 88, yy), label, fill="#334155", font=font(16))

    y0 += 260
    side.text((sx + 36, y0), "NON DICHIARATO", fill="#991b1b", font=font(22, True))
    nonclaims = [
        "• muri, porte o finestre validati",
        "• attraversabilità dei gap",
        "• appartenenza/proprietà dei contenuti",
        "• collegamenti tra i due piani",
        "• scala metrica formalizzata",
        "• direzione Nord",
        "• approvazione umana",
    ]
    for index, line in enumerate(nonclaims):
        side.text((sx + 52, y0 + 40 + index * 31), line, fill="#991b1b", font=font(17, True))

    side.text((sx + 36, canvas.height - 120), "PROVENIENZA", fill="#111827", font=font(20, True))
    side.text((sx + 36, canvas.height - 84), "sheet_mapper → floor_units → text-space topology", fill="#475569", font=font(15))
    side.text((sx + 36, canvas.height - 58), "→ compass observation → document graph", fill="#475569", font=font(15))
    side.text((sx + 36, canvas.height - 31), "Tutti gli input sono referenziati per SHA-256 nel JSON.", fill="#475569", font=font(14))
    return canvas


def main() -> int:
    required = [
        PAGE,
        SHEET_MAP,
        FLOOR_UNITS,
        REGION1_TOPOLOGY,
        REGION1_OVERLAY,
        REGION2_TOPOLOGY,
        REGION2_OVERLAY,
        COMPASS,
        CONNECTIONS,
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    page = Image.open(PAGE).convert("RGB")
    sheet = load_json(SHEET_MAP)
    floors = load_json(FLOOR_UNITS)
    topologies = {"region_001": load_json(REGION1_TOPOLOGY), "region_002": load_json(REGION2_TOPOLOGY)}
    compass = load_json(COMPASS)
    connections = load_json(CONNECTIONS)
    graph = build_graph(sheet, floors, topologies, compass, connections)
    overlay = draw_document_map(page, sheet, floors, topologies, compass, connections)

    payload = {
        "schema_version": "planparser.industrial_v1.document-topology-map/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_hierarchical_graph_not_human_approved",
        "source": {
            "path": PAGE.relative_to(ROOT).as_posix(),
            "sha256": sha256(PAGE),
            "width_px": page.width,
            "height_px": page.height,
        },
        "inputs": [
            {"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
            for role, path in [
                ("sheet_map", SHEET_MAP),
                ("floor_units", FLOOR_UNITS),
                ("region_001_topology", REGION1_TOPOLOGY),
                ("region_001_topology_overlay", REGION1_OVERLAY),
                ("region_002_topology", REGION2_TOPOLOGY),
                ("region_002_topology_overlay", REGION2_OVERLAY),
                ("compass_observation", COMPASS),
                ("space_connections", CONNECTIONS),
            ]
        ],
        "graph": graph,
        "summary": {
            "floor_region_candidates": len(floors["floor_units"]),
            "analysis_regions": len(topologies),
            "text_nodes": sum(item["summary"]["text_node_count"] for item in topologies.values()),
            "space_candidates": sum(item["summary"]["space_candidate_count"] for item in topologies.values()),
            "space_candidates_abstained": sum(item["summary"]["space_candidate_abstained_count"] for item in topologies.values()),
            "bounded_by_evidence_relations": sum(item["summary"]["bounded_by_evidence_edge_count"] for item in topologies.values()),
            "gap_connection_hypotheses": connections["summary"]["connection_hypothesis_count"],
            "gap_connection_candidates_supported": connections["summary"]["supported_connection_candidate_count"],
            "sheet_level_compass_candidates": compass["summary"]["sheet_level_compass_glyph_candidates"],
            "north_directions_asserted": compass["summary"]["north_directions_asserted"],
            "graph_node_count": len(graph["nodes"]),
            "graph_edge_count": len(graph["edges"]),
        },
        "explicit_non_claims": [
            "no cross-floor space connection is inferred",
            "space candidates are not validated rooms",
            "bounded-by evidence does not assert walls",
            "gap connections do not assert doors or traversability",
            "external context is not assigned to the target property",
            "the observed compass axis is not asserted as north",
            "metric scale is not formalized",
            "no human approval or correction has been applied",
        ],
    }

    parent = OUTPUT.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".revision_001.building-{uuid.uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    image_path = temporary / "document_topology_map.png"
    json_path = temporary / "document_topology_map.json"
    overlay.save(image_path)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifacts = [
        {"path": image_path.name, "sha256": sha256(image_path), "media_type": "image/png"},
        {"path": json_path.name, "sha256": sha256(json_path), "media_type": "application/json"},
    ]
    manifest_path = temporary / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "planparser.artifact-manifest/1.0", "artifacts": artifacts}, indent=2) + "\n",
        encoding="utf-8",
    )
    for artifact in artifacts:
        if sha256(temporary / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Hash verification failed: {artifact['path']}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")
    temporary.rename(OUTPUT)
    print(OUTPUT / "document_topology_map.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
