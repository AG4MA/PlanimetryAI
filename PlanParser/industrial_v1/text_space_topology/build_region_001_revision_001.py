from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "atomic_v2/region_split/artifacts/scheda_catastale/page_0001/revision_002/region_001.png"
)
REGIONS = (
    ROOT
    / "atomic_v2/region_split/artifacts/scheda_catastale/page_0001/revision_002/regions.json"
)
OCR = (
    ROOT
    / "atomic_v2/ocr_ensemble/artifacts/scheda_catastale/region_001/revision_001/ocr_ensemble.json"
)
LINEWORK = (
    ROOT
    / "atomic_v2/linework/artifacts/scheda_catastale/region_001/revision_001/linework.json"
)
WALL_BANDS = (
    ROOT
    / "atomic_v2/wall_bands/artifacts/scheda_catastale/region_001/revision_001/wall_bands.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/text_space_topology/artifacts/scheda_catastale/region_001/revision_001"
)


ROOM_ALIASES = {
    "bagno": "bagno",
    "camera": "camera",
    "dis": "disimpegno",
    "disimpegno": "disimpegno",
    "soggiorno-pranzo": "soggiorno-pranzo",
    "soggiorno pranzo": "soggiorno-pranzo",
    "rip": "ripostiglio",
    "ripostiglio": "ripostiglio",
    "balcone": "balcone",
    "cucina": "cucina",
    "sala": "sala",
    "portico": "portico",
}
OBJECT_TERMS = ("armadio", "arredo fisso")
COLORS = [
    (37, 99, 235),
    (22, 163, 74),
    (234, 88, 12),
    (147, 51, 234),
    (8, 145, 178),
    (190, 24, 93),
    (101, 163, 13),
    (202, 138, 4),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for candidate in [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.;:|_")


def alternatives(alignment: dict) -> list[str]:
    values: list[str] = []
    consensus = alignment.get("decision", {}).get("consensus") or {}
    if consensus.get("text_normalized"):
        values.append(str(consensus["text_normalized"]))
    for engine in ("ppocrv5", "doctr"):
        value = alignment.get("raw_text_alternatives", {}).get(engine, {}).get("joined_text_raw")
        if value and value not in values:
            values.append(str(value))
    return values


def classify_alignment(alignment: dict, image_width: int) -> tuple[str, str | None, list[str]]:
    normalized = {normalize(value) for value in alternatives(alignment)}
    reasons: list[str] = []
    for value in normalized:
        if value in ROOM_ALIASES:
            reasons.append(f"lexical_room_anchor:{value}")
            return "space_name_seed", ROOM_ALIASES[value], reasons
    for value in normalized:
        if any(term in value for term in OBJECT_TERMS):
            reasons.append(f"lexical_contained_object:{value}")
            return "contained_object_label", None, reasons
    bbox = alignment.get("spatial_audit", {}).get("alignment_bbox_xyxy") or [0, 0, 0, 0]
    if float(bbox[2]) >= image_width - 2:
        reasons.append("touches_region_border")
        return "border_context_unresolved", None, reasons
    reasons.append("no_supported_role_mapping")
    return "unresolved_text", None, reasons


def make_text_nodes(ensemble: dict, image_width: int) -> list[dict]:
    nodes: list[dict] = []
    for alignment in ensemble.get("alignments", []):
        bbox = list(map(float, alignment["spatial_audit"]["alignment_bbox_xyxy"]))
        role, canonical_name, reasons = classify_alignment(alignment, image_width)
        nodes.append(
            {
                "id": "",
                "source_alignment_ids": [alignment["id"]],
                "raw_text_alternatives": alternatives(alignment),
                "bbox_crop_px_xyxy": bbox,
                "center_crop_px": [round((bbox[0] + bbox[2]) / 2, 3), round((bbox[1] + bbox[3]) / 2, 3)],
                "role_hypothesis": role,
                "canonical_space_name_hypothesis": canonical_name,
                "role_reasons": reasons,
                "ocr_classification": alignment.get("decision", {}).get("classification"),
                "ocr_abstained": bool(alignment.get("decision", {}).get("abstained")),
                "composite": False,
            }
        )

    vano = next(
        (node for node in nodes if any(normalize(value) == "vano" for value in node["raw_text_alternatives"])),
        None,
    )
    scala = next(
        (
            node
            for node in nodes
            if any(normalize(value) in {"scala", "cala"} for value in node["raw_text_alternatives"])
        ),
        None,
    )
    if vano and scala:
        distance = math.dist(vano["center_crop_px"], scala["center_crop_px"])
        if distance <= 80:
            x1 = min(vano["bbox_crop_px_xyxy"][0], scala["bbox_crop_px_xyxy"][0])
            y1 = min(vano["bbox_crop_px_xyxy"][1], scala["bbox_crop_px_xyxy"][1])
            x2 = max(vano["bbox_crop_px_xyxy"][2], scala["bbox_crop_px_xyxy"][2])
            y2 = max(vano["bbox_crop_px_xyxy"][3], scala["bbox_crop_px_xyxy"][3])
            nodes = [node for node in nodes if node not in (vano, scala)]
            nodes.append(
                {
                    "id": "",
                    "source_alignment_ids": vano["source_alignment_ids"] + scala["source_alignment_ids"],
                    "raw_text_alternatives": ["vano scala"],
                    "bbox_crop_px_xyxy": [x1, y1, x2, y2],
                    "center_crop_px": [round((x1 + x2) / 2, 3), round((y1 + y2) / 2, 3)],
                    "role_hypothesis": "space_name_seed",
                    "canonical_space_name_hypothesis": "vano scala",
                    "role_reasons": ["spatially_clustered_text_nodes", f"center_distance_px:{distance:.3f}"],
                    "ocr_classification": "composite_mixed_evidence",
                    "ocr_abstained": bool(vano["ocr_abstained"] or scala["ocr_abstained"]),
                    "composite": True,
                }
            )

    nodes.sort(key=lambda item: (item["center_crop_px"][1], item["center_crop_px"][0]))
    for index, node in enumerate(nodes, 1):
        node["id"] = f"text_node_{index:03d}"
    return nodes


def line_text_overlap(candidate: dict, text_nodes: list[dict], padding: int = 2) -> float:
    (x1, y1), (x2, y2) = candidate["points_px"]
    length = max(float(candidate.get("length_px", 0)), 1.0)
    best = 0.0
    for node in text_nodes:
        bx1, by1, bx2, by2 = node["bbox_crop_px_xyxy"]
        bx1 -= padding
        by1 -= padding
        bx2 += padding
        by2 += padding
        if candidate["orientation"] == "horizontal" and by1 <= y1 <= by2:
            best = max(best, max(0.0, min(x2, bx2) - max(x1, bx1)) / length)
        elif candidate["orientation"] == "vertical" and bx1 <= x1 <= bx2:
            best = max(best, max(0.0, min(y2, by2) - max(y1, by1)) / length)
    return round(best, 6)


def band_text_overlap(candidate: dict, text_nodes: list[dict]) -> float:
    x, y, width, height = map(float, candidate["bbox_px"])
    area = max(width * height, 1.0)
    best = 0.0
    for node in text_nodes:
        bx1, by1, bx2, by2 = node["bbox_crop_px_xyxy"]
        intersection = max(0.0, min(x + width, bx2) - max(x, bx1)) * max(
            0.0, min(y + height, by2) - max(y, by1)
        )
        best = max(best, intersection / area)
    return round(best, 6)


def build_barrier(
    width: int,
    height: int,
    linework: dict,
    wall_bands: dict,
    text_nodes: list[dict],
) -> tuple[np.ndarray, np.ndarray, list[dict], list[dict]]:
    raw = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(raw, (0, 0), (width - 1, height - 1), 255, 4)
    line_audit: list[dict] = []
    for candidate in linework.get("candidates", []):
        overlap = line_text_overlap(candidate, text_nodes)
        used = not (overlap >= 0.25 and float(candidate["length_px"]) < 180)
        line_audit.append(
            {
                "id": candidate["id"],
                "text_overlap_ratio": overlap,
                "used_as_barrier": used,
                "reason": "retained_structural_candidate" if used else "excluded_probable_text_stroke",
            }
        )
        if used:
            p1, p2 = map(lambda point: tuple(map(int, point)), candidate["points_px"])
            thickness = 3 if candidate.get("status") == "solid" else 2
            cv2.line(raw, p1, p2, 255, thickness, cv2.LINE_8)

    band_audit: list[dict] = []
    for candidate in wall_bands.get("candidates", []):
        overlap = band_text_overlap(candidate, text_nodes)
        used = not (overlap >= 0.35 and float(candidate["length_px"]) < 180)
        band_audit.append(
            {
                "id": candidate["id"],
                "text_overlap_ratio": overlap,
                "used_as_barrier": used,
                "reason": "retained_parallel_edge_hypothesis" if used else "excluded_probable_text_band",
            }
        )
        if used:
            polygon = np.asarray(candidate["polygon_px"], dtype=np.int32)
            cv2.fillPoly(raw, [polygon], 255)

    horizontal = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((1, 31), np.uint8))
    vertical = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((31, 1), np.uint8))
    closed = cv2.bitwise_or(raw, cv2.bitwise_or(horizontal, vertical))
    closed = cv2.dilate(closed, np.ones((3, 3), np.uint8), iterations=1)
    synthetic_closures = cv2.bitwise_and(closed, cv2.bitwise_not(cv2.dilate(raw, np.ones((3, 3), np.uint8))))
    return raw, synthetic_closures, line_audit, band_audit


def nearest_free(center: list[float], free: np.ndarray, max_radius: int = 60) -> tuple[int, int] | None:
    height, width = free.shape
    cx = int(round(center[0]))
    cy = int(round(center[1]))
    if 0 <= cx < width and 0 <= cy < height and free[cy, cx]:
        return cx, cy
    for radius in range(1, max_radius + 1):
        x1, x2 = max(0, cx - radius), min(width - 1, cx + radius)
        y1, y2 = max(0, cy - radius), min(height - 1, cy + radius)
        for x in range(x1, x2 + 1):
            for y in (y1, y2):
                if free[y, x]:
                    return x, y
        for y in range(y1 + 1, y2):
            for x in (x1, x2):
                if free[y, x]:
                    return x, y
    return None


def expand_from_text_nodes(
    barrier: np.ndarray,
    text_nodes: list[dict],
) -> tuple[np.ndarray, list[dict]]:
    free = barrier == 0
    labels = np.zeros(barrier.shape, dtype=np.int16)
    distance = np.full(barrier.shape, -1, dtype=np.int32)
    queue: deque[tuple[int, int]] = deque()
    seed_nodes = [node for node in text_nodes if node["role_hypothesis"] == "space_name_seed"]
    seed_audit: list[dict] = []
    for label, node in enumerate(seed_nodes, 1):
        seed = nearest_free(node["center_crop_px"], free)
        node["space_label_index"] = label
        node["expansion_seed_crop_px"] = list(seed) if seed else None
        node["seed_displacement_px"] = (
            round(math.dist(node["center_crop_px"], seed), 3) if seed else None
        )
        seed_audit.append(
            {
                "text_node_id": node["id"],
                "space_label_index": label,
                "seed_crop_px": list(seed) if seed else None,
                "seed_displacement_px": node["seed_displacement_px"],
            }
        )
        if seed:
            x, y = seed
            labels[y, x] = label
            distance[y, x] = 0
            queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        label = labels[y, x]
        next_distance = distance[y, x] + 1
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < labels.shape[1] and 0 <= ny < labels.shape[0]):
                continue
            if not free[ny, nx] or labels[ny, nx] != 0:
                continue
            labels[ny, nx] = label
            distance[ny, nx] = next_distance
            queue.append((nx, ny))
    return labels, seed_audit


def contour_polygon(mask: np.ndarray) -> list[list[int]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    epsilon = max(1.0, cv2.arcLength(contour, True) * 0.003)
    approximated = cv2.approxPolyDP(contour, epsilon, True)
    return [[int(point[0][0]), int(point[0][1])] for point in approximated]


def ray_observations(
    seed: tuple[int, int],
    barrier: np.ndarray,
    raw_barrier: np.ndarray,
    synthetic_closures: np.ndarray,
) -> list[dict]:
    directions = [
        ("north", 0, -1),
        ("north_east", 1, -1),
        ("east", 1, 0),
        ("south_east", 1, 1),
        ("south", 0, 1),
        ("south_west", -1, 1),
        ("west", -1, 0),
        ("north_west", -1, -1),
    ]
    observations: list[dict] = []
    for name, dx, dy in directions:
        x, y = seed
        distance = 0
        hit = None
        while True:
            x += dx
            y += dy
            distance += 1
            if not (0 <= x < barrier.shape[1] and 0 <= y < barrier.shape[0]):
                break
            if barrier[y, x]:
                hit_kind = "observed_barrier" if raw_barrier[y, x] else "synthetic_gap_closure" if synthetic_closures[y, x] else "thickened_barrier"
                hit = [x, y]
                observations.append(
                    {
                        "direction": name,
                        "hit_crop_px": hit,
                        "distance_px": round(math.hypot(x - seed[0], y - seed[1]), 3),
                        "hit_kind": hit_kind,
                    }
                )
                break
        if hit is None:
            observations.append(
                {"direction": name, "hit_crop_px": None, "distance_px": None, "hit_kind": "no_hit"}
            )
    return observations


def build_spaces(
    labels: np.ndarray,
    barrier: np.ndarray,
    raw_barrier: np.ndarray,
    synthetic_closures: np.ndarray,
    text_nodes: list[dict],
    page_offset: tuple[int, int],
) -> list[dict]:
    spaces: list[dict] = []
    barrier_near = cv2.dilate((barrier > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
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
        supported = perimeter & barrier_near
        competition = np.zeros(region.shape, dtype=bool)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted = np.roll(labels, shift=(dy, dx), axis=(0, 1))
            competition |= perimeter & (shifted > 0) & (shifted != label)
        support_ratio = float(supported.sum()) / perimeter_count
        competition_ratio = float(competition.sum()) / perimeter_count
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
        confidence = min(
            0.93,
            0.30
            + 0.45 * support_ratio
            + (0.10 if not node["ocr_abstained"] else 0.0)
            + (0.08 if len(xs) >= 500 else 0.0),
        )
        abstained = support_ratio < 0.35 or competition_ratio > 0.35
        space_id = f"space_candidate_{label:03d}"
        node["space_candidate_id"] = space_id
        seed = tuple(map(int, node["expansion_seed_crop_px"]))
        rays = ray_observations(seed, barrier, raw_barrier, synthetic_closures)
        spaces.append(
            {
                "id": space_id,
                "name_text_node_id": node["id"],
                "name_hypothesis": node["canonical_space_name_hypothesis"],
                "bbox_crop_px_xywh": bbox,
                "bbox_page_px_xywh": [bbox[0] + page_offset[0], bbox[1] + page_offset[1], bbox[2], bbox[3]],
                "polygon_crop_px": contour_polygon(region),
                "area_px2": int(region.sum()),
                "boundary_support_ratio": round(support_ratio, 6),
                "competition_boundary_ratio": round(competition_ratio, 6),
                "confidence_uncalibrated": round(confidence, 6),
                "abstained": abstained,
                "abstention_reasons": [
                    reason
                    for condition, reason in [
                        (support_ratio < 0.35, "insufficient_observed_boundary_support"),
                        (competition_ratio > 0.35, "large_boundary_created_by_seed_competition"),
                        (node["ocr_abstained"], "name_node_contains_abstained_ocr_evidence"),
                    ]
                    if condition
                ],
                "radial_boundary_observations": rays,
            }
        )
    return spaces


def graph_edges(labels: np.ndarray, text_nodes: list[dict], spaces: list[dict]) -> list[dict]:
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

    space_by_label = {index + 1: item for index, item in enumerate(spaces)}
    for node in text_nodes:
        if node["role_hypothesis"] == "space_name_seed":
            continue
        seed = nearest_free(node["center_crop_px"], labels > 0)
        if not seed:
            continue
        label = int(labels[seed[1], seed[0]])
        space = space_by_label.get(label)
        node["located_in_space_candidate_id"] = space["id"] if space else None
        if space:
            edges.append(
                {
                    "id": f"edge_{len(edges) + 1:03d}",
                    "relation": "text_node_located_in_space_candidate",
                    "from": node["id"],
                    "to": space["id"],
                    "status": "geometric_assignment_role_unresolved" if node["role_hypothesis"] == "unresolved_text" else "hypothesis",
                }
            )

    contacts: dict[tuple[int, int], int] = {}
    for dx, dy in ((1, 0), (0, 1)):
        shifted = np.roll(labels, shift=(-dy, -dx), axis=(0, 1))
        mask = (labels > 0) & (shifted > 0) & (labels != shifted)
        left = labels[mask]
        right = shifted[mask]
        for a, b in zip(left.tolist(), right.tolist()):
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


def pil_from_bgr(image: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def draw_text_nodes(source: Image.Image, nodes: list[dict]) -> Image.Image:
    out = source.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")
    role_color = {
        "space_name_seed": (22, 163, 74, 255),
        "contained_object_label": (37, 99, 235, 255),
        "border_context_unresolved": (220, 38, 38, 255),
        "unresolved_text": (245, 158, 11, 255),
    }
    for node in nodes:
        x1, y1, x2, y2 = node["bbox_crop_px_xyxy"]
        color = role_color[node["role_hypothesis"]]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        cx, cy = node["center_crop_px"]
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
        label = node["id"].replace("text_node_", "T")
        draw.rectangle((x1, max(0, y1 - 14), x1 + 30, max(0, y1 - 2)), fill=(255, 255, 255, 220))
        draw.text((x1 + 1, max(0, y1 - 14)), label, fill=color, font=font(9, True))
    return out


def draw_barrier(source: Image.Image, raw: np.ndarray, closures: np.ndarray) -> Image.Image:
    base = np.array(source.convert("RGB"))
    overlay = base.copy()
    overlay[raw > 0] = np.array([37, 99, 235], dtype=np.uint8)
    overlay[closures > 0] = np.array([217, 70, 239], dtype=np.uint8)
    blended = cv2.addWeighted(base, 0.56, overlay, 0.44, 0)
    return Image.fromarray(blended)


def draw_topology(
    source: Image.Image,
    labels: np.ndarray,
    nodes: list[dict],
    spaces: list[dict],
) -> Image.Image:
    base = np.array(source.convert("RGB"))
    overlay = base.copy()
    for index, space in enumerate(spaces, 1):
        color = np.array(COLORS[(index - 1) % len(COLORS)], dtype=np.uint8)
        overlay[labels == index] = color
    blended = cv2.addWeighted(base, 0.62, overlay, 0.38, 0)
    out = Image.fromarray(blended)
    draw = ImageDraw.Draw(out, "RGBA")
    for index, space in enumerate(spaces, 1):
        node = next(node for node in nodes if node["id"] == space["name_text_node_id"])
        seed = node.get("expansion_seed_crop_px")
        if not seed:
            continue
        color = (*COLORS[(index - 1) % len(COLORS)], 255)
        for ray in space["radial_boundary_observations"]:
            if ray["hit_crop_px"]:
                draw.line((tuple(seed), tuple(ray["hit_crop_px"])), fill=(*color[:3], 150), width=1)
                hx, hy = ray["hit_crop_px"]
                draw.ellipse((hx - 3, hy - 3, hx + 3, hy + 3), fill=color)
        sx, sy = seed
        draw.ellipse((sx - 7, sy - 7, sx + 7, sy + 7), fill=color, outline=(255, 255, 255, 255), width=2)
        label = f"{space['id'].replace('space_candidate_', 'S')} {space['name_hypothesis']}"
        draw.rectangle((sx + 8, sy - 8, sx + 8 + len(label) * 6, sy + 7), fill=(255, 255, 255, 220))
        draw.text((sx + 10, sy - 7), label, fill=color, font=font(9, True))
    return out


def panel(image: Image.Image, title: str, subtitle: str) -> Image.Image:
    header = 72
    out = Image.new("RGB", (image.width, image.height + header), "white")
    out.paste(image, (0, header))
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, out.width - 1, out.height - 1), outline="#9ca3af", width=2)
    draw.text((11, 8), title, fill="#111827", font=font(20, True))
    draw.text((11, 39), subtitle, fill="#4b5563", font=font(13))
    return out


def contact_sheet(
    source: Image.Image,
    text_overlay: Image.Image,
    barrier_overlay: Image.Image,
    topology_overlay: Image.Image,
    nodes: list[dict],
    spaces: list[dict],
) -> Image.Image:
    panels = [
        panel(source, "1. SORGENTE", "testo e geometria ancora sovrapposti nel raster"),
        panel(text_overlay, "2. NODI TESTUALI", "verde=nome spazio; blu=oggetto; arancio/rosso=ruolo irrisolto"),
        panel(barrier_overlay, "3. BARRIERE GEOMETRICHE", "blu=evidenza trattenuta; magenta=chiusura temporanea di gap"),
        panel(topology_overlay, "4. ESPANSIONE TOPOLOGICA", "ogni nome-spazio si espande fino a barriere o confini di competizione"),
    ]
    gap = 18
    header = 132
    footer = 230
    cell_w = source.width
    cell_h = source.height + 72
    canvas = Image.new("RGB", (cell_w * 2 + gap, header + cell_h * 2 + gap + footer), "#f3f4f6")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), "PLANPARSER - TESTO -> SPAZIO -> TOPOLOGIA r001", fill="#111827", font=font(28, True))
    draw.text(
        (18, 50),
        "Le parole restano nodi semantici; i loro glifi non vengono promossi a muri o linee edilizie.",
        fill="#991b1b",
        font=font(16, True),
    )
    draw.text(
        (18, 80),
        f"nodi testo={len(nodes)}  semi spazio={sum(n['role_hypothesis'] == 'space_name_seed' for n in nodes)}  spazi candidati={len(spaces)}",
        fill="#374151",
        font=font(15),
    )
    draw.text((18, 105), "Evidenza automatica non revisionata; le forme sono candidate, non verità catastale.", fill="#4b5563", font=font(14))
    positions = [(0, header), (cell_w + gap, header), (0, header + cell_h + gap), (cell_w + gap, header + cell_h + gap)]
    for item, position in zip(panels, positions):
        canvas.paste(item, position)

    y = header + cell_h * 2 + gap
    draw.rectangle((0, y, canvas.width - 1, canvas.height - 1), fill="white", outline="#9ca3af", width=2)
    draw.text((18, y + 12), "RETE PRODOTTA", fill="#111827", font=font(19, True))
    draw.text(
        (18, y + 43),
        "Nodo testo --names_space_candidate--> Spazio --candidate_topological_adjacency--> Spazio; gli oggetti sono assegnati geometricamente allo spazio che li contiene.",
        fill="#374151",
        font=font(14),
    )
    draw.text(
        (18, y + 71),
        "Il confine può essere: linea/band osservata, chiusura temporanea di un gap, oppure frontiera creata dalla competizione tra due semi. Queste cause restano distinte.",
        fill="#374151",
        font=font(14),
    )
    draw.text((18, y + 105), "SPAZI", fill="#111827", font=font(15, True))
    for index, space in enumerate(spaces):
        column = index // 4
        row = index % 4
        text = (
            f"{space['id'].replace('space_candidate_', 'S')} {space['name_hypothesis']}  "
            f"area={space['area_px2']}  supporto={space['boundary_support_ratio']:.2f}  "
            f"{'ASTENUTO' if space['abstained'] else 'CANDIDATO'}"
        )
        draw.text((18 + column * (canvas.width // 2), y + 133 + row * 22), text, fill="#991b1b" if space["abstained"] else "#166534", font=font(12))
    draw.text(
        (18, canvas.height - 27),
        "NON DICHIARATO: muro, porta, finestra, stanza validata, appartenenza all'immobile, scala metrica o nord.",
        fill="#991b1b",
        font=font(13, True),
    )
    return canvas


def main() -> int:
    for path in (SOURCE, REGIONS, OCR, LINEWORK, WALL_BANDS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    bgr = cv2.imread(str(SOURCE), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Cannot read {SOURCE}")
    source = pil_from_bgr(bgr)
    height, width = bgr.shape[:2]
    regions = load_json(REGIONS)
    region_record = next(item for item in regions["regions"] if item["id"] == "region_001")
    page_offset = (int(region_record["bbox_px"][0]), int(region_record["bbox_px"][1]))
    ensemble = load_json(OCR)
    linework = load_json(LINEWORK)
    wall_bands = load_json(WALL_BANDS)
    text_nodes = make_text_nodes(ensemble, width)

    raw_barrier, synthetic_closures, line_audit, band_audit = build_barrier(
        width, height, linework, wall_bands, text_nodes
    )
    barrier = cv2.bitwise_or(
        cv2.dilate(raw_barrier, np.ones((3, 3), np.uint8), iterations=1),
        synthetic_closures,
    )
    labels, seed_audit = expand_from_text_nodes(barrier, text_nodes)
    spaces = build_spaces(
        labels,
        barrier,
        raw_barrier,
        synthetic_closures,
        text_nodes,
        page_offset,
    )
    edges = graph_edges(labels, text_nodes, spaces)
    for node in text_nodes:
        x, y = node["center_crop_px"]
        node["center_page_px"] = [round(x + page_offset[0], 3), round(y + page_offset[1], 3)]

    text_overlay = draw_text_nodes(source, text_nodes)
    barrier_overlay = draw_barrier(source, raw_barrier, synthetic_closures)
    topology_overlay = draw_topology(source, labels, text_nodes, spaces)
    sheet = contact_sheet(source, text_overlay, barrier_overlay, topology_overlay, text_nodes, spaces)

    payload = {
        "schema_version": "planparser.industrial_v1.text-space-topology/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_candidates_not_human_approved",
        "source": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": sha256(SOURCE),
            "width_px": width,
            "height_px": height,
            "bbox_page_px_xywh": region_record["bbox_px"],
        },
        "inputs": [
            {"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
            for role, path in [
                ("region_contract", REGIONS),
                ("ocr_text_nodes", OCR),
                ("raw_linework", LINEWORK),
                ("parallel_edge_band_hypotheses", WALL_BANDS),
            ]
        ],
        "method": {
            "name": "text_anchored_geodesic_space_expansion",
            "text_geometry_separation": True,
            "text_stroke_exclusion": {
                "line_overlap_threshold": 0.25,
                "band_overlap_threshold": 0.35,
                "long_candidate_retention_threshold_px": 180,
            },
            "temporary_gap_closure": {
                "horizontal_kernel_px": [31, 1],
                "vertical_kernel_px": [1, 31],
                "semantic_opening_inference": False,
            },
            "expansion": "multi_source_four_connected_geodesic_wavefront",
            "competition_boundaries_retained_separately": True,
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
            "contained_object_label_count": sum(node["role_hypothesis"] == "contained_object_label" for node in text_nodes),
            "unresolved_text_node_count": sum("unresolved" in node["role_hypothesis"] for node in text_nodes),
            "space_candidate_count": len(spaces),
            "space_candidate_abstained_count": sum(space["abstained"] for space in spaces),
            "topology_edge_count": len(edges),
        },
        "explicit_non_claims": [
            "OCR glyphs are not geometric building lines",
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
        artifacts.append({"path": filename, "sha256": sha256(path), "media_type": "image/png"})
    json_path = temporary / "text_space_topology.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifacts.append({"path": json_path.name, "sha256": sha256(json_path), "media_type": "application/json"})
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
    print(OUTPUT / "text_space_topology_contact_sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
