from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "atomic_v2/ingest/artifacts/scheda_catastale/pages/page_0001.png"
FLOOR_DIR = (
    ROOT
    / "industrial_v1/floor_units/artifacts/scheda_catastale/page_0001/revision_001"
)
FLOOR_JSON = FLOOR_DIR / "floor_units.json"
FLOOR_IMAGE = FLOOR_DIR / "fr_002.png"
SHEET_MAP = (
    ROOT
    / "industrial_v1/sheet_mapper/artifacts/scheda_catastale/page_0001/revision_001/sheet_map.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/compass_observation/artifacts/scheda_catastale/page_0001/revision_001"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def angle_clockwise_from_up(dx: float, dy: float) -> float:
    return (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0


def axial_distance_deg(first: float, second: float) -> float:
    delta = abs((first - second) % 180.0)
    return min(delta, 180.0 - delta)


def rect_gap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    dx = max(bx - (ax + aw), ax - (bx + bw), 0)
    dy = max(by - (ay + ah), ay - (by + bh), 0)
    return math.hypot(dx, dy)


def intersection_ratio(first: dict[str, int], second: dict[str, int]) -> float:
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(first["x"] + first["width"], second["x"] + second["width"])
    bottom = min(first["y"] + first["height"], second["y"] + second["height"])
    intersection = max(0, right - left) * max(0, bottom - top)
    area = max(1, first["width"] * first["height"])
    return intersection / area


def circle_support(edges: np.ndarray, x: float, y: float, radius: float) -> float:
    hits = 0
    samples = 360
    for theta in np.linspace(0.0, 2.0 * math.pi, samples, endpoint=False):
        px = int(round(x + radius * math.cos(theta)))
        py = int(round(y + radius * math.sin(theta)))
        y0 = max(0, py - 2)
        y1 = min(edges.shape[0], py + 3)
        x0 = max(0, px - 2)
        x1 = min(edges.shape[1], px + 3)
        patch = edges[y0:y1, x0:x1]
        hits += int(patch.size > 0 and bool(patch.max()))
    return hits / samples


def best_ring(glyph_gray: np.ndarray) -> dict[str, float] | None:
    minimum = min(glyph_gray.shape)
    if minimum < 32:
        return None
    blurred = cv2.GaussianBlur(glyph_gray, (5, 5), 1.2)
    edges = cv2.Canny(glyph_gray, 60, 180)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=max(12, minimum // 4),
        param1=100,
        param2=14,
        minRadius=max(8, round(minimum * 0.08)),
        maxRadius=max(10, round(minimum * 0.35)),
    )
    if circles is None:
        return None
    ranked: list[dict[str, float]] = []
    for x, y, radius in circles[0]:
        support = circle_support(edges, float(x), float(y), float(radius))
        ranked.append(
            {
                "center_x_local_px": float(x),
                "center_y_local_px": float(y),
                "radius_px": float(radius),
                "circumference_edge_support": float(support),
                "ranking_value": float(radius * support),
            }
        )
    ranked.sort(key=lambda value: value["ranking_value"], reverse=True)
    return ranked[0] if ranked else None


def line_evidence(glyph_gray: np.ndarray) -> dict[str, Any]:
    edges = cv2.Canny(glyph_gray, 50, 150)
    diagonal = math.hypot(glyph_gray.shape[1], glyph_gray.shape[0])
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360.0,
        threshold=20,
        minLineLength=max(20, round(diagonal * 0.12)),
        maxLineGap=10,
    )
    records: list[dict[str, Any]] = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            dx = int(x2) - int(x1)
            dy = int(y2) - int(y1)
            length = math.hypot(dx, dy)
            angle = angle_clockwise_from_up(dx, dy) % 180.0
            records.append(
                {
                    "xyxy_local_px": [int(x1), int(y1), int(x2), int(y2)],
                    "length_px": float(length),
                    "axis_angle_clockwise_from_up_deg": float(angle),
                }
            )
    records.sort(key=lambda value: value["length_px"], reverse=True)
    total_weight = sum(value["length_px"] for value in records)
    oblique_weight = sum(
        value["length_px"]
        for value in records
        if min(
            axial_distance_deg(value["axis_angle_clockwise_from_up_deg"], 0.0),
            axial_distance_deg(value["axis_angle_clockwise_from_up_deg"], 90.0),
        )
        > 12.0
    )
    if total_weight:
        sine = sum(
            value["length_px"]
            * math.sin(math.radians(2.0 * value["axis_angle_clockwise_from_up_deg"]))
            for value in records
        )
        cosine = sum(
            value["length_px"]
            * math.cos(math.radians(2.0 * value["axis_angle_clockwise_from_up_deg"]))
            for value in records
        )
        mean_axis = (0.5 * math.degrees(math.atan2(sine, cosine)) + 180.0) % 180.0
    else:
        mean_axis = None
    return {
        "count": len(records),
        "oblique_length_share": float(oblique_weight / total_weight) if total_weight else 0.0,
        "length_weighted_mean_axis_deg": mean_axis,
        "longest_lines": records[:12],
    }


def normalize_token(value: str) -> str:
    return re.sub(r"[^A-Z]", "", value.upper())


def analyze_component(
    label_id: int,
    labels: np.ndarray,
    stats: np.ndarray,
    centroids: np.ndarray,
    all_components: list[tuple[int, int, int, int, int, int]],
) -> dict[str, Any]:
    x, y, width, height, area = (int(value) for value in stats[label_id])
    component = labels[y : y + height, x : x + width] == label_id
    glyph_gray = np.where(component, 0, 255).astype(np.uint8)
    ys, xs = np.where(component)
    points = np.column_stack((xs, ys)).astype(np.float64)
    center = points.mean(axis=0)
    covariance = np.cov((points - center).T)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major = float(max(eigenvalues))
    minor = float(max(1e-9, min(eigenvalues)))
    anisotropy = (major - minor) / (major + minor)
    pca_vector = eigenvectors[:, int(np.argmax(eigenvalues))]
    pca_angle = angle_clockwise_from_up(float(pca_vector[0]), float(pca_vector[1])) % 180.0

    ring = best_ring(glyph_gray)
    lines = line_evidence(glyph_gray)
    ring_support = ring["circumference_edge_support"] if ring else 0.0
    if ring:
        ring_center = np.array(
            [ring["center_x_local_px"], ring["center_y_local_px"]], dtype=np.float64
        )
    else:
        ring_center = center
    radial_distance = np.linalg.norm(points - ring_center, axis=1)
    threshold = float(np.quantile(radial_distance, 0.99))
    tip_points = points[radial_distance >= threshold]
    tip = tip_points.mean(axis=0)
    tip_vector = tip - ring_center
    tip_angle = angle_clockwise_from_up(float(tip_vector[0]), float(tip_vector[1]))
    tip_unit = tip_vector / max(1e-9, float(np.linalg.norm(tip_vector)))
    projections = (points - ring_center) @ tip_unit
    forward_extent = float(max(projections))
    reverse_extent = float(max(1e-9, -min(projections)))
    pointed_end_ratio = forward_extent / reverse_extent
    tip_asymmetry = clamp((pointed_end_ratio - 1.0) / 1.0)

    own_bbox = (x, y, width, height)
    clearance = min(
        (
            rect_gap(own_bbox, (ox, oy, ow, oh))
            for other_id, ox, oy, ow, oh, other_area in all_components
            if other_id != label_id and other_area >= 20
        ),
        default=0.0,
    )
    density = area / max(1, width * height)
    ring_score = clamp((ring_support - 0.45) / 0.45)
    score = (
        0.30 * ring_score
        + 0.20 * lines["oblique_length_share"]
        + 0.15 * anisotropy
        + 0.15 * clamp(clearance / 60.0)
        + 0.20 * tip_asymmetry
    )
    return {
        "component_label": label_id,
        "bbox_floor_px": {"x": x, "y": y, "width": width, "height": height},
        "ink_area_px": area,
        "bbox_ink_density": float(density),
        "centroid_floor_px": {"x": float(centroids[label_id][0]), "y": float(centroids[label_id][1])},
        "clearance_to_other_ink_components_px": float(clearance),
        "ring_evidence": ring,
        "line_evidence": lines,
        "pca": {
            "major_eigenvalue": major,
            "minor_eigenvalue": minor,
            "anisotropy": float(anisotropy),
            "undirected_axis_clockwise_from_up_deg": float(pca_angle),
        },
        "pointed_end_evidence": {
            "ring_or_component_center_local_px": [float(ring_center[0]), float(ring_center[1])],
            "tip_cluster_centroid_local_px": [float(tip[0]), float(tip[1])],
            "tip_cluster_quantile": 0.99,
            "forward_extent_px": forward_extent,
            "reverse_extent_px": reverse_extent,
            "forward_to_reverse_extent_ratio": float(pointed_end_ratio),
            "directed_angle_clockwise_from_page_up_deg": float(tip_angle),
        },
        "geometric_candidate_score": float(score),
        "passes_compass_glyph_screen": bool(
            score >= 0.65
            and ring_support >= 0.65
            and lines["oblique_length_share"] >= 0.50
            and pointed_end_ratio >= 1.35
        ),
    }


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str,
    width: int,
) -> None:
    draw.line((start, end), fill=color, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max(1e-9, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    side_x, side_y = -uy, ux
    head = max(12, width * 4)
    wing = head * 0.55
    left = (end[0] - ux * head + side_x * wing, end[1] - uy * head + side_y * wing)
    right = (end[0] - ux * head - side_x * wing, end[1] - uy * head - side_y * wing)
    draw.polygon((end, left, right), fill=color)


def make_overlay(page: Image.Image, selected: dict[str, Any]) -> Image.Image:
    page = page.convert("RGB")
    panel_width = 940
    canvas = Image.new("RGB", (page.width + panel_width, page.height), "#f8fafc")
    canvas.paste(page, (0, 0))
    draw = ImageDraw.Draw(canvas)
    bbox = selected["bbox_page_px"]
    left = bbox["x"]
    top = bbox["y"]
    right = left + bbox["width"]
    bottom = top + bbox["height"]
    draw.rectangle((left - 10, top - 10, right + 10, bottom + 10), outline="#e11d48", width=9)

    center = selected["direction_observation"]["axis_center_page_px"]
    tip = selected["direction_observation"]["pointed_end_page_px"]
    draw_arrow(
        draw,
        (center["x"], center["y"]),
        (tip["x"], tip["y"]),
        "#f59e0b",
        8,
    )
    draw.ellipse(
        (center["x"] - 10, center["y"] - 10, center["x"] + 10, center["y"] + 10),
        fill="#06b6d4",
        outline="white",
        width=3,
    )
    draw.rectangle((left - 10, top - 54, left + 495, top - 10), fill="#e11d48")
    draw.text(
        (left, top - 48),
        "CO-001  directional compass glyph candidate",
        fill="white",
        font=font(24, True),
    )

    panel_x = page.width
    draw.rectangle((panel_x, 0, canvas.width - 1, canvas.height - 1), fill="#f8fafc")
    draw.text((panel_x + 42, 44), "PLANPARSER / COMPASS OBSERVATION", fill="#0f172a", font=font(31, True))
    draw.text((panel_x + 42, 88), "revision_001  |  sheet-level observation", fill="#475569", font=font(20))
    draw.line((panel_x + 42, 132, canvas.width - 42, 132), fill="#cbd5e1", width=2)

    margin = 34
    source_crop = page.crop(
        (
            max(0, left - margin),
            max(0, top - margin),
            min(page.width, right + margin),
            min(page.height, bottom + margin),
        )
    )
    zoom_width = panel_width - 84
    zoom_scale = min(4.0, zoom_width / source_crop.width)
    zoom = source_crop.resize(
        (round(source_crop.width * zoom_scale), round(source_crop.height * zoom_scale)),
        Image.Resampling.NEAREST,
    )
    zoom_x = panel_x + (panel_width - zoom.width) // 2
    zoom_y = 178
    canvas.paste(zoom, (zoom_x, zoom_y))
    draw.rectangle((zoom_x - 2, zoom_y - 2, zoom_x + zoom.width + 2, zoom_y + zoom.height + 2), outline="#334155", width=3)

    crop_origin_x = max(0, left - margin)
    crop_origin_y = max(0, top - margin)
    zoom_center = (
        zoom_x + (center["x"] - crop_origin_x) * zoom_scale,
        zoom_y + (center["y"] - crop_origin_y) * zoom_scale,
    )
    zoom_tip = (
        zoom_x + (tip["x"] - crop_origin_x) * zoom_scale,
        zoom_y + (tip["y"] - crop_origin_y) * zoom_scale,
    )
    ring = selected["geometric_evidence"]["ring"]
    ring_radius = ring["radius_px"] * zoom_scale
    draw.ellipse(
        (
            zoom_center[0] - ring_radius,
            zoom_center[1] - ring_radius,
            zoom_center[0] + ring_radius,
            zoom_center[1] + ring_radius,
        ),
        outline="#06b6d4",
        width=5,
    )
    draw_arrow(draw, zoom_center, zoom_tip, "#f59e0b", 7)
    draw.ellipse(
        (zoom_center[0] - 8, zoom_center[1] - 8, zoom_center[0] + 8, zoom_center[1] + 8),
        fill="#06b6d4",
    )
    text_y = zoom_y + zoom.height + 50
    angle = selected["direction_observation"]["pointed_end_angle_clockwise_from_page_up_deg"]
    evidence = selected["geometric_evidence"]
    lines = [
        ("AUTOMATIC OBSERVATION", "#0f766e", True),
        (f"bbox page: x={left} y={top} w={bbox['width']} h={bbox['height']}", "#334155", False),
        (f"connected ink: {evidence['ink_area_px']} px", "#334155", False),
        (f"ring edge support: {evidence['ring']['circumference_edge_support']:.3f}", "#334155", False),
        (f"oblique line share: {evidence['lines']['oblique_length_share']:.3f}", "#334155", False),
        (f"pointed-end ratio: {evidence['pointed_end_ratio']:.3f}", "#334155", False),
        (f"candidate direction: {angle:.2f} deg clockwise from PAGE UP", "#b45309", True),
        ("", "#334155", False),
        ("SEMANTIC ABSTENTION", "#be123c", True),
        ("Compass/orientation glyph candidate: YES", "#334155", False),
        ("North direction asserted: NO", "#be123c", True),
        ("No reliable N/NORD token is attached to the glyph.", "#334155", False),
        ("Page-up is only the zero-angle reference; it is NOT north.", "#334155", False),
        ("", "#334155", False),
        ("PROVENANCE", "#0f172a", True),
        ("page_0001 -> floor_units r001 / FR-002", "#334155", False),
        ("sheet_mapper r001 -> compass_observation r001", "#334155", False),
        ("No human review; prior artifacts unchanged.", "#475569", False),
    ]
    for value, color, bold in lines:
        if value:
            draw.text((panel_x + 42, text_y), value, fill=color, font=font(20, bold))
        text_y += 38
    return canvas


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable artifact revision: {OUTPUT}")
    if not all(path.exists() for path in (PAGE, FLOOR_JSON, FLOOR_IMAGE, SHEET_MAP)):
        missing = [str(path) for path in (PAGE, FLOOR_JSON, FLOOR_IMAGE, SHEET_MAP) if not path.exists()]
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    floor_payload = json.loads(FLOOR_JSON.read_text(encoding="utf-8"))
    sheet_payload = json.loads(SHEET_MAP.read_text(encoding="utf-8"))
    floor_record = next(item for item in floor_payload["floor_units"] if item["id"] == "FR-002")
    floor_origin_x = int(floor_record["bbox_page_px"]["x"])
    floor_origin_y = int(floor_record["bbox_page_px"]["y"])
    gray = cv2.imread(str(FLOOR_IMAGE), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError(f"OpenCV could not read {FLOOR_IMAGE}")
    otsu_threshold, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    label_count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
    all_components = [
        (
            label_id,
            int(stats[label_id][cv2.CC_STAT_LEFT]),
            int(stats[label_id][cv2.CC_STAT_TOP]),
            int(stats[label_id][cv2.CC_STAT_WIDTH]),
            int(stats[label_id][cv2.CC_STAT_HEIGHT]),
            int(stats[label_id][cv2.CC_STAT_AREA]),
        )
        for label_id in range(1, label_count)
    ]

    rejection_counts: Counter[str] = Counter()
    screened: list[dict[str, Any]] = []
    image_area = gray.shape[0] * gray.shape[1]
    minimum_area = max(450, round(image_area * 0.0001))
    maximum_dimension = round(min(gray.shape) * 0.24)
    for label_id, x, y, width, height, area in all_components:
        reasons: list[str] = []
        if x <= 2 or y <= 2 or x + width >= gray.shape[1] - 2 or y + height >= gray.shape[0] - 2:
            reasons.append("touches_floor_crop_boundary")
        if area < minimum_area:
            reasons.append("ink_area_below_symbol_screen")
        if min(width, height) < 36:
            reasons.append("bbox_too_thin_for_compass_glyph_screen")
        if max(width, height) > maximum_dimension:
            reasons.append("bbox_too_large_for_isolated_glyph_screen")
        density = area / max(1, width * height)
        if density < 0.015 or density > 0.55:
            reasons.append("bbox_ink_density_outside_symbol_screen")
        if reasons:
            rejection_counts.update(reasons)
            continue
        screened.append(analyze_component(label_id, labels, stats, centroids, all_components))

    screened.sort(key=lambda value: value["geometric_candidate_score"], reverse=True)
    passed = [value for value in screened if value["passes_compass_glyph_screen"]]
    if not passed:
        raise RuntimeError("No component passed the geometry-only compass glyph screen")
    candidate = passed[0]
    bbox_floor = candidate["bbox_floor_px"]
    bbox_page = {
        "x": floor_origin_x + bbox_floor["x"],
        "y": floor_origin_y + bbox_floor["y"],
        "width": bbox_floor["width"],
        "height": bbox_floor["height"],
    }
    ring = candidate["ring_evidence"]
    pointed = candidate["pointed_end_evidence"]
    center_floor = {
        "x": bbox_floor["x"] + ring["center_x_local_px"],
        "y": bbox_floor["y"] + ring["center_y_local_px"],
    }
    tip_floor = {
        "x": bbox_floor["x"] + pointed["tip_cluster_centroid_local_px"][0],
        "y": bbox_floor["y"] + pointed["tip_cluster_centroid_local_px"][1],
    }
    center_page = {"x": floor_origin_x + center_floor["x"], "y": floor_origin_y + center_floor["y"]}
    tip_page = {"x": floor_origin_x + tip_floor["x"], "y": floor_origin_y + tip_floor["y"]}

    structural = sheet_payload["observations"]["structural_linework_candidates"]
    overlaps = [
        {
            "structural_candidate_id": item["id"],
            "candidate_bbox_intersection_ratio": intersection_ratio(bbox_page, item["bbox_page_px"]),
        }
        for item in structural
    ]
    nearby_ocr = []
    north_tokens = {"N", "NORD", "NORTH", "NORTE"}
    for item in sheet_payload["observations"]["ocr_words"]:
        word_bbox = item["bbox_page_px"]
        expanded = {
            "x": bbox_page["x"] - 50,
            "y": bbox_page["y"] - 50,
            "width": bbox_page["width"] + 100,
            "height": bbox_page["height"] + 100,
        }
        if intersection_ratio(word_bbox, expanded) > 0.0:
            normalized = normalize_token(item["text_raw"])
            nearby_ocr.append(
                {
                    "ocr_id": item["id"],
                    "text_raw": item["text_raw"],
                    "normalized": normalized,
                    "confidence_raw": item["confidence_raw"],
                    "bbox_page_px": word_bbox,
                    "north_lexicon_match": normalized in north_tokens,
                    "usable_as_north_evidence": bool(
                        normalized in north_tokens and item["confidence_raw"] >= 0.80
                    ),
                }
            )
    usable_north_tokens = [item for item in nearby_ocr if item["usable_as_north_evidence"]]

    selected = {
        "id": "CO-001",
        "observation_type": "isolated_directional_compass_glyph_candidate",
        "scope": "sheet_level",
        "floor_unit_context": "FR-002",
        "bbox_floor_px": bbox_floor,
        "bbox_page_px": bbox_page,
        "geometric_candidate_confidence": round(candidate["geometric_candidate_score"], 6),
        "geometric_evidence": {
            "connected_component_label": candidate["component_label"],
            "ink_area_px": candidate["ink_area_px"],
            "bbox_ink_density": round(candidate["bbox_ink_density"], 6),
            "clearance_to_other_ink_components_px": round(
                candidate["clearance_to_other_ink_components_px"], 3
            ),
            "ring": {
                "center_floor_px": center_floor,
                "center_page_px": center_page,
                "radius_px": round(ring["radius_px"], 3),
                "circumference_edge_support": round(ring["circumference_edge_support"], 6),
            },
            "lines": {
                "hough_line_count": candidate["line_evidence"]["count"],
                "oblique_length_share": round(candidate["line_evidence"]["oblique_length_share"], 6),
                "length_weighted_mean_undirected_axis_deg": (
                    round(candidate["line_evidence"]["length_weighted_mean_axis_deg"], 6)
                    if candidate["line_evidence"]["length_weighted_mean_axis_deg"] is not None
                    else None
                ),
                "longest_lines_local_to_bbox": candidate["line_evidence"]["longest_lines"],
            },
            "pca": candidate["pca"],
            "pointed_end_ratio": round(pointed["forward_to_reverse_extent_ratio"], 6),
        },
        "direction_observation": {
            "reference": "source_page_raster",
            "zero_axis": "page_up",
            "positive_rotation": "clockwise",
            "page_up_is_north_assumption": False,
            "axis_center_floor_px": center_floor,
            "axis_center_page_px": center_page,
            "pointed_end_floor_px": tip_floor,
            "pointed_end_page_px": tip_page,
            "pointed_end_angle_clockwise_from_page_up_deg": round(
                pointed["directed_angle_clockwise_from_page_up_deg"], 6
            ),
            "undirected_axis_clockwise_from_page_up_deg": round(
                pointed["directed_angle_clockwise_from_page_up_deg"] % 180.0, 6
            ),
            "status": "observed_directional_axis_candidate",
        },
        "spatial_evidence": {
            "overlap_with_sheet_mapper_structural_candidates": overlaps,
            "outside_all_structural_candidate_bboxes": all(
                item["candidate_bbox_intersection_ratio"] == 0.0 for item in overlaps
            ),
        },
        "ocr_evidence_near_glyph": nearby_ocr,
        "semantic_decision": {
            "compass_or_orientation_glyph": "automatic_candidate",
            "north_direction_asserted": False,
            "status": "abstained",
            "reason": (
                "geometry_supports_an_isolated_ringed_directional_glyph_but_no_reliable_"
                "N_or_NORD_token_proves_which_pointed_end_denotes_north"
            ),
            "usable_north_token_count": len(usable_north_tokens),
        },
    }

    payload = {
        "schema_version": "planparser.industrial_v1.compass_observation.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_sheet_observation_with_semantic_abstention",
        "source": {
            "page_path": PAGE.relative_to(ROOT).as_posix(),
            "page_sha256": sha256(PAGE),
            "width_px": int(sheet_payload["source"]["width_px"]),
            "height_px": int(sheet_payload["source"]["height_px"]),
        },
        "inputs": [
            {"path": FLOOR_JSON.relative_to(ROOT).as_posix(), "sha256": sha256(FLOOR_JSON)},
            {"path": FLOOR_IMAGE.relative_to(ROOT).as_posix(), "sha256": sha256(FLOOR_IMAGE)},
            {"path": SHEET_MAP.relative_to(ROOT).as_posix(), "sha256": sha256(SHEET_MAP)},
        ],
        "method": {
            "name": "connected_ink_island_plus_ring_oblique_axis_and_pointed_end_geometry",
            "detection_scope": "FR-002_full_width_floor_region_then_mapped_to_source_page",
            "binarization": "opencv_otsu_binary_inverse",
            "otsu_threshold": float(otsu_threshold),
            "minimum_component_area_px": minimum_area,
            "maximum_component_dimension_px": maximum_dimension,
            "compass_screen_threshold": 0.65,
            "ring_support_threshold": 0.65,
            "oblique_line_share_threshold": 0.50,
            "pointed_end_ratio_threshold": 1.35,
            "human_review_used": False,
        },
        "component_screening": {
            "connected_components_excluding_background": label_count - 1,
            "geometry_analyzed_components": len(screened),
            "passed_compass_glyph_screen": len(passed),
            "preanalysis_rejection_counts": dict(sorted(rejection_counts.items())),
            "ranked_analyzed_components": [
                {
                    "component_label": value["component_label"],
                    "bbox_floor_px": value["bbox_floor_px"],
                    "score": round(value["geometric_candidate_score"], 6),
                    "passed": value["passes_compass_glyph_screen"],
                }
                for value in screened
            ],
        },
        "observations": [selected],
        "summary": {
            "sheet_level_compass_glyph_candidates": 1,
            "directional_axis_candidates": 1,
            "north_directions_asserted": 0,
            "semantic_abstentions": 1,
            "prior_artifacts_modified": False,
        },
        "explicit_non_claims": [
            "page-up is not assumed to be north",
            "the pointed end is not asserted to denote north without reliable textual or semantic corroboration",
            "the floor-region context does not make the glyph part of a floor model",
            "no wall, room, property-membership or scale semantics are assigned",
            "no human approval or correction has been applied",
        ],
    }

    OUTPUT.mkdir(parents=True, exist_ok=False)
    json_path = OUTPUT / "compass_observation.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    page_image = Image.open(PAGE)
    overlay = make_overlay(page_image, selected)
    overlay_path = OUTPUT / "compass_observation_overlay.png"
    overlay.save(overlay_path, optimize=True)
    manifest = {
        "schema_version": "planparser.industrial_v1.artifact_manifest.v1",
        "revision": "revision_001",
        "immutable": True,
        "created_at_utc": payload["created_at_utc"],
        "artifacts": [
            {
                "path": json_path.name,
                "sha256": sha256(json_path),
                "media_type": "application/json",
            },
            {
                "path": overlay_path.name,
                "sha256": sha256(overlay_path),
                "media_type": "image/png",
            },
        ],
        "inputs": payload["inputs"],
    }
    manifest_path = OUTPUT / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "summary": payload["summary"]}, indent=2))


if __name__ == "__main__":
    main()
