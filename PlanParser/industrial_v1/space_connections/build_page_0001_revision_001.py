from __future__ import annotations

import itertools
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_SOURCE_DIR = ROOT / "industrial_v1/text_space_topology"
sys.path.insert(0, str(TOPOLOGY_SOURCE_DIR))

import build_region_001_revision_001 as region1_v1  # noqa: E402
import build_region_001_revision_002 as region1_v2  # noqa: E402
import build_region_002_revision_001 as region2_v1  # noqa: E402


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
OUTPUT = (
    ROOT
    / "industrial_v1/space_connections/artifacts/scheda_catastale/page_0001/revision_001"
)


def state_region1() -> dict:
    source_bgr = cv2.imread(str(region1_v1.SOURCE), cv2.IMREAD_COLOR)
    ensemble = region1_v1.load_json(region1_v1.OCR)
    linework = region1_v1.load_json(region1_v1.LINEWORK)
    bands = region1_v1.load_json(region1_v1.WALL_BANDS)
    nodes = region1_v1.make_text_nodes(ensemble, source_bgr.shape[1])
    raw, closures, line_audit, band_audit = region1_v1.build_barrier(
        source_bgr.shape[1], source_bgr.shape[0], linework, bands, nodes
    )
    barrier = cv2.bitwise_or(cv2.dilate(raw, np.ones((3, 3), np.uint8), iterations=1), closures)
    labels, _ = region1_v1.expand_from_text_nodes(barrier, nodes)
    topology = region1_v1.load_json(REGION1_TOPOLOGY)
    return {
        "region_id": "region_001",
        "labels": labels,
        "closures": closures,
        "topology": topology,
        "overlay": Image.open(REGION1_OVERLAY).convert("RGB"),
        "page_offset": tuple(topology["source"]["bbox_page_px_xywh"][:2]),
    }


def state_region2() -> dict:
    source_bgr = cv2.imread(str(region2_v1.SOURCE), cv2.IMREAD_COLOR)
    text_payload = region1_v1.load_json(region2_v1.TEXT_NODES)
    linework = region1_v1.load_json(region2_v1.LINEWORK)
    bands = region1_v1.load_json(region2_v1.WALL_BANDS)
    nodes = region2_v1.adapt_text_nodes(text_payload)
    raw, closures, line_audit, band_audit = region1_v1.build_barrier(
        source_bgr.shape[1], source_bgr.shape[0], linework, bands, nodes
    )
    barrier = cv2.bitwise_or(cv2.dilate(raw, np.ones((3, 3), np.uint8), iterations=1), closures)
    labels, _ = region1_v1.expand_from_text_nodes(barrier, nodes)
    topology = region1_v1.load_json(REGION2_TOPOLOGY)
    return {
        "region_id": "region_002",
        "labels": labels,
        "closures": closures,
        "topology": topology,
        "overlay": Image.open(REGION2_OVERLAY).convert("RGB"),
        "page_offset": tuple(topology["source"]["bbox_page_px_xywh"][:2]),
    }


def labels_in_strip(labels: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> set[int]:
    x1 = max(0, min(labels.shape[1], x1))
    x2 = max(0, min(labels.shape[1], x2))
    y1 = max(0, min(labels.shape[0], y1))
    y2 = max(0, min(labels.shape[0], y2))
    if x1 >= x2 or y1 >= y2:
        return set()
    values, counts = np.unique(labels[y1:y2, x1:x2], return_counts=True)
    return {int(value) for value, count in zip(values, counts) if value > 0 and count >= 3}


def detect_connections(state: dict) -> tuple[list[dict], dict]:
    closures = state["closures"] > 0
    labels = state["labels"]
    component_count, component_labels, stats, _ = cv2.connectedComponentsWithStats(
        closures.astype(np.uint8), connectivity=8
    )
    spaces_by_label = {
        int(space["id"].split("_")[-1]): space
        for space in state["topology"]["space_candidates"]
    }
    candidates: list[dict] = []
    unresolved_components = 0
    ring_kernel = np.ones((13, 13), np.uint8)
    for component_index in range(1, component_count):
        x, y, width, height, area = map(int, stats[component_index])
        component = component_labels == component_index
        ring = cv2.dilate(component.astype(np.uint8), ring_kernel) > 0
        ring &= ~component
        values, counts = np.unique(labels[ring], return_counts=True)
        adjacent_labels = {
            int(value)
            for value, count in zip(values, counts)
            if value > 0 and count >= 3 and int(value) in spaces_by_label
        }
        orientation = "horizontal" if width >= height * 1.5 else "vertical" if height >= width * 1.5 else "compact_or_mixed"
        side_a: set[int]
        side_b: set[int]
        margin = 8
        if orientation == "horizontal":
            side_a = labels_in_strip(labels, x, y - margin, x + width, y)
            side_b = labels_in_strip(labels, x, y + height, x + width, y + height + margin)
        elif orientation == "vertical":
            side_a = labels_in_strip(labels, x - margin, y, x, y + height)
            side_b = labels_in_strip(labels, x + width, y, x + width + margin, y + height)
        else:
            side_a = set()
            side_b = set()
        opposite_pairs = {
            tuple(sorted((a, b)))
            for a in side_a
            for b in side_b
            if a != b and a in spaces_by_label and b in spaces_by_label
        }
        ring_pairs = {
            tuple(sorted(pair))
            for pair in itertools.combinations(sorted(adjacent_labels), 2)
        }
        pairs = opposite_pairs or ring_pairs
        if not pairs:
            unresolved_components += 1
            continue
        touches_border = x <= 1 or y <= 1 or x + width >= labels.shape[1] - 1 or y + height >= labels.shape[0] - 1
        for label_a, label_b in sorted(pairs):
            strong = (
                (label_a, label_b) in opposite_pairs
                and not touches_border
                and area <= 1200
                and max(width, height) <= 70
            )
            candidate_id = f"{state['region_id']}_connection_{len(candidates) + 1:03d}"
            candidates.append(
                {
                    "id": candidate_id,
                    "region_id": state["region_id"],
                    "from_space_id": spaces_by_label[label_a]["id"],
                    "from_space_name_hypothesis": spaces_by_label[label_a]["name_hypothesis"],
                    "to_space_id": spaces_by_label[label_b]["id"],
                    "to_space_name_hypothesis": spaces_by_label[label_b]["name_hypothesis"],
                    "source_closure_component": f"closure_component_{component_index:03d}",
                    "bbox_crop_px_xywh": [x, y, width, height],
                    "bbox_page_px_xywh": [x + state["page_offset"][0], y + state["page_offset"][1], width, height],
                    "area_px2": area,
                    "orientation": orientation,
                    "opposite_side_space_labels_supported": bool((label_a, label_b) in opposite_pairs),
                    "touches_region_border": touches_border,
                    "status": "connection_candidate" if strong else "abstained_connection_hypothesis",
                    "abstained": not strong,
                    "reasons": [
                        "temporary_gap_closure_has_two_distinct_space_labels_nearby",
                        "opposite_side_support" if (label_a, label_b) in opposite_pairs else "ring_proximity_only",
                    ],
                    "explicit_non_claim": "this candidate is not asserted to be a door or traversable opening",
                }
            )
    audit = {
        "synthetic_closure_component_count": component_count - 1,
        "closure_components_without_two_space_labels": unresolved_components,
        "connection_hypothesis_count": len(candidates),
        "supported_connection_candidate_count": sum(not item["abstained"] for item in candidates),
        "abstained_connection_hypothesis_count": sum(item["abstained"] for item in candidates),
    }
    return candidates, audit


def draw_connections(state: dict, candidates: list[dict]) -> Image.Image:
    out = state["overlay"].copy()
    draw = ImageDraw.Draw(out, "RGBA")
    for item in candidates:
        x, y, width, height = item["bbox_crop_px_xywh"]
        color = (6, 182, 212, 255) if not item["abstained"] else (245, 158, 11, 255)
        draw.rectangle((x, y, x + width, y + height), outline=color, width=4)
        cx = x + width / 2
        cy = y + height / 2
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
        label = item["id"].split("_")[-1]
        draw.rectangle((x, max(0, y - 15), x + 28, max(0, y - 1)), fill=(255, 255, 255, 230))
        draw.text((x + 1, max(0, y - 15)), label, fill=color, font=region1_v1.font(9, True))
    return out


def panel(image: Image.Image, title: str, subtitle: str) -> Image.Image:
    header = 76
    out = Image.new("RGB", (image.width, image.height + header), "white")
    out.paste(image, (0, header))
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, out.width - 1, out.height - 1), outline="#9ca3af", width=2)
    draw.text((11, 8), title, fill="#111827", font=region1_v1.font(20, True))
    draw.text((11, 40), subtitle, fill="#4b5563", font=region1_v1.font(13))
    return out


def build_contact_sheet(states: list[dict], candidates_by_region: dict[str, list[dict]], audits: dict[str, dict]) -> Image.Image:
    rendered = [
        panel(
            draw_connections(state, candidates_by_region[state["region_id"]]),
            f"{state['region_id']} - CONNESSIONI FRA SPAZI",
            "ciano=supporto su lati opposti; arancio=ipotesi astenuta; nessun rettangolo significa nessun arco prodotto",
        )
        for state in states
    ]
    max_height = max(image.height for image in rendered)
    gap = 20
    header = 132
    footer = 250
    width = sum(image.width for image in rendered) + gap
    canvas = Image.new("RGB", (width, header + max_height + footer), "#f3f4f6")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), "PLANPARSER - CONNESSIONI TOPOLOGICHE CANDIDATE r001", fill="#111827", font=region1_v1.font(27, True))
    draw.text(
        (18, 50),
        "Una chiusura temporanea genera un arco soltanto quando trova due spazi distinti sui lati della stessa interruzione.",
        fill="#991b1b",
        font=region1_v1.font(15, True),
    )
    draw.text(
        (18, 80),
        "L'arco resta connessione/varco candidato: non è ancora porta, apertura attraversabile o muro.",
        fill="#374151",
        font=region1_v1.font(14),
    )
    draw.text((18, 106), "Provenienza: text-space topology -> synthetic gap components -> opposite-side space test", fill="#4b5563", font=region1_v1.font(13))
    x = 0
    for image in rendered:
        canvas.paste(image, (x, header))
        x += image.width + gap
    y = header + max_height
    draw.rectangle((0, y, canvas.width - 1, canvas.height - 1), fill="white", outline="#9ca3af", width=2)
    draw.text((18, y + 12), "RISULTATI", fill="#111827", font=region1_v1.font(18, True))
    row_y = y + 43
    all_candidates = [item for items in candidates_by_region.values() for item in items]
    for item in all_candidates[:8]:
        text = (
            f"{item['id']}: {item['from_space_name_hypothesis']} <-> {item['to_space_name_hypothesis']}  "
            f"bbox={item['bbox_crop_px_xywh']}  {item['status']}"
        )
        draw.text((18, row_y), text, fill="#166534" if not item["abstained"] else "#92400e", font=region1_v1.font(12))
        row_y += 21
    if len(all_candidates) > 8:
        draw.text((18, row_y), f"+ {len(all_candidates) - 8} ulteriori ipotesi nel JSON", fill="#4b5563", font=region1_v1.font(12))
    summary = "  ".join(
        f"{region}: closure={audit['synthetic_closure_component_count']} connessioni={audit['connection_hypothesis_count']} supportate={audit['supported_connection_candidate_count']} astenute={audit['abstained_connection_hypothesis_count']}"
        for region, audit in audits.items()
    )
    draw.text((18, canvas.height - 52), summary, fill="#111827", font=region1_v1.font(12, True))
    draw.text(
        (18, canvas.height - 27),
        "NON DICHIARATO: porta, attraversabilità, direzione di passaggio, accessibilità, muro o proprietà. Nessuna revisione umana.",
        fill="#991b1b",
        font=region1_v1.font(12, True),
    )
    return canvas


def main() -> int:
    required = [REGION1_TOPOLOGY, REGION1_OVERLAY, REGION2_TOPOLOGY, REGION2_OVERLAY]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")
    states = [state_region1(), state_region2()]
    candidates_by_region: dict[str, list[dict]] = {}
    audits: dict[str, dict] = {}
    for state in states:
        candidates, audit = detect_connections(state)
        candidates_by_region[state["region_id"]] = candidates
        audits[state["region_id"]] = audit
    all_candidates = [item for items in candidates_by_region.values() for item in items]
    sheet = build_contact_sheet(states, candidates_by_region, audits)
    payload = {
        "schema_version": "planparser.industrial_v1.space-connections/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_gap_connection_candidates_not_human_approved",
        "scope": {"document": "scheda_catastale", "page": "page_0001", "regions": ["region_001", "region_002"]},
        "inputs": [
            {"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": region1_v1.sha256(path)}
            for role, path in [
                ("region_001_topology", REGION1_TOPOLOGY),
                ("region_001_topology_overlay", REGION1_OVERLAY),
                ("region_002_topology", REGION2_TOPOLOGY),
                ("region_002_topology_overlay", REGION2_OVERLAY),
            ]
        ],
        "method": {
            "name": "synthetic_gap_component_opposite_space_test",
            "ring_radius_px": 6,
            "opposite_side_margin_px": 8,
            "door_inference_performed": False,
            "traversability_inference_performed": False,
        },
        "region_audits": audits,
        "connection_candidates": all_candidates,
        "topology_edges": [
            {
                "id": f"connection_edge_{index:03d}",
                "relation": "candidate_connection_via_temporarily_closed_gap",
                "from": item["from_space_id"],
                "to": item["to_space_id"],
                "evidence_id": item["id"],
                "status": item["status"],
            }
            for index, item in enumerate(all_candidates, 1)
        ],
        "summary": {
            "connection_hypothesis_count": len(all_candidates),
            "supported_connection_candidate_count": sum(not item["abstained"] for item in all_candidates),
            "abstained_connection_hypothesis_count": sum(item["abstained"] for item in all_candidates),
        },
        "explicit_non_claims": [
            "a temporarily closed gap is not a wall",
            "a connection candidate is not a door",
            "a connection candidate does not prove traversability or accessibility",
            "no passage direction is assigned",
            "no human approval or correction has been applied",
        ],
    }
    parent = OUTPUT.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".revision_001.building-{uuid.uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    image_path = temporary / "space_connections_contact_sheet.png"
    json_path = temporary / "space_connections.json"
    sheet.save(image_path)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifacts = [
        {"path": image_path.name, "sha256": region1_v1.sha256(image_path), "media_type": "image/png"},
        {"path": json_path.name, "sha256": region1_v1.sha256(json_path), "media_type": "application/json"},
    ]
    manifest_path = temporary / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "planparser.artifact-manifest/1.0", "artifacts": artifacts}, indent=2) + "\n",
        encoding="utf-8",
    )
    for artifact in artifacts:
        if region1_v1.sha256(temporary / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Hash verification failed: {artifact['path']}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")
    temporary.rename(OUTPUT)
    print(OUTPUT / "space_connections_contact_sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
