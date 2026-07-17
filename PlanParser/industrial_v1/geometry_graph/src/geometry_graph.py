from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EPSILON = 1e-9


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def as_list(self, digits: int = 3) -> list[float]:
        return [round(self.x, digits), round(self.y, digits)]


@dataclass(frozen=True)
class Segment:
    id: str
    start: Point
    end: Point
    confidence: float
    raw: dict[str, Any]

    @property
    def dx(self) -> float:
        return self.end.x - self.start.x

    @property
    def dy(self) -> float:
        return self.end.y - self.start.y

    @property
    def length(self) -> float:
        return math.hypot(self.dx, self.dy)

    def point_at(self, t: float) -> Point:
        return Point(self.start.x + t * self.dx, self.start.y + t * self.dy)


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def _dot(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * bx + ay * by


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parameter_location(t: float, length: float, endpoint_tolerance_px: float) -> str:
    threshold = min(0.25, endpoint_tolerance_px / max(length, EPSILON))
    if t <= threshold:
        return "endpoint_start"
    if t >= 1.0 - threshold:
        return "endpoint_end"
    return "interior"


def _continuity(t: float, length: float, endpoint_tolerance_px: float) -> dict[str, Any]:
    threshold = min(0.25, endpoint_tolerance_px / max(length, EPSILON))
    before = t > threshold
    after = t < 1.0 - threshold
    return {
        "parameter_t": round(t, 6),
        "location": _parameter_location(t, length, endpoint_tolerance_px),
        "observed_extent_before_node": before,
        "observed_extent_after_node": after,
        "continuous_through_node": before and after,
    }


def acute_angle_degrees(a: Segment, b: Segment) -> float:
    denominator = a.length * b.length
    if denominator <= EPSILON:
        return 0.0
    cosine = abs(_dot(a.dx, a.dy, b.dx, b.dy) / denominator)
    cosine = _clamp(cosine, -1.0, 1.0)
    return math.degrees(math.acos(cosine))


def _project_point_to_segment(point: Point, segment: Segment) -> tuple[Point, float, float]:
    length_sq = segment.dx * segment.dx + segment.dy * segment.dy
    if length_sq <= EPSILON:
        return segment.start, 0.0, _distance(point, segment.start)
    t = _dot(point.x - segment.start.x, point.y - segment.start.y, segment.dx, segment.dy) / length_sq
    t_clamped = _clamp(t, 0.0, 1.0)
    projected = segment.point_at(t_clamped)
    return projected, t_clamped, _distance(point, projected)


def _point_to_infinite_line_distance(point: Point, segment: Segment) -> float:
    if segment.length <= EPSILON:
        return _distance(point, segment.start)
    return abs(
        _cross(
            point.x - segment.start.x,
            point.y - segment.start.y,
            segment.dx,
            segment.dy,
        )
    ) / segment.length


def closest_points(a: Segment, b: Segment) -> tuple[Point, Point, float, float, float]:
    candidates: list[tuple[Point, Point, float, float, float]] = []
    for ta, pa in ((0.0, a.start), (1.0, a.end)):
        pb, tb, distance = _project_point_to_segment(pa, b)
        candidates.append((pa, pb, ta, tb, distance))
    for tb, pb in ((0.0, b.start), (1.0, b.end)):
        pa, ta, distance = _project_point_to_segment(pb, a)
        candidates.append((pa, pb, ta, tb, distance))
    return min(candidates, key=lambda item: (item[4], item[2], item[3]))


def _intersection(a: Segment, b: Segment) -> dict[str, Any] | None:
    r_x, r_y = a.dx, a.dy
    s_x, s_y = b.dx, b.dy
    qmp_x = b.start.x - a.start.x
    qmp_y = b.start.y - a.start.y
    denominator = _cross(r_x, r_y, s_x, s_y)
    scale = max(a.length * b.length, 1.0)

    if abs(denominator) > EPSILON * scale:
        ta = _cross(qmp_x, qmp_y, s_x, s_y) / denominator
        tb = _cross(qmp_x, qmp_y, r_x, r_y) / denominator
        if -EPSILON <= ta <= 1.0 + EPSILON and -EPSILON <= tb <= 1.0 + EPSILON:
            ta = _clamp(ta, 0.0, 1.0)
            tb = _clamp(tb, 0.0, 1.0)
            return {
                "kind": "point",
                "point": a.point_at(ta),
                "ta": ta,
                "tb": tb,
            }
        return None

    if abs(_cross(qmp_x, qmp_y, r_x, r_y)) > EPSILON * max(a.length, 1.0):
        return None

    axis_x = abs(r_x) >= abs(r_y)
    a0 = a.start.x if axis_x else a.start.y
    a1 = a.end.x if axis_x else a.end.y
    b0 = b.start.x if axis_x else b.start.y
    b1 = b.end.x if axis_x else b.end.y
    denominator_axis = a1 - a0
    if abs(denominator_axis) <= EPSILON:
        return None
    tb0_on_a = (b0 - a0) / denominator_axis
    tb1_on_a = (b1 - a0) / denominator_axis
    overlap_start = max(0.0, min(tb0_on_a, tb1_on_a))
    overlap_end = min(1.0, max(tb0_on_a, tb1_on_a))
    if overlap_end < overlap_start - EPSILON:
        return None
    if abs(overlap_end - overlap_start) <= EPSILON:
        point = a.point_at(_clamp(overlap_start, 0.0, 1.0))
        _, tb, _ = _project_point_to_segment(point, b)
        return {
            "kind": "point",
            "point": point,
            "ta": _clamp(overlap_start, 0.0, 1.0),
            "tb": tb,
        }
    start = a.point_at(overlap_start)
    end = a.point_at(overlap_end)
    return {
        "kind": "overlap",
        "start": start,
        "end": end,
        "overlap_length_px": _distance(start, end),
    }


def _junction_class(location_a: str, location_b: str) -> str:
    interior_a = location_a == "interior"
    interior_b = location_b == "interior"
    if interior_a and interior_b:
        return "crossing"
    if interior_a != interior_b:
        return "endpoint_to_interior"
    return "endpoint_to_endpoint"


def _geometry_confidence(a: Segment, b: Segment, base: float) -> float:
    observed = math.sqrt(max(0.0, a.confidence) * max(0.0, b.confidence))
    return round(_clamp(base * (0.65 + 0.35 * observed), 0.0, 1.0), 3)


def analyze_segments(
    segments: list[Segment],
    *,
    near_tolerance_px: float = 8.0,
    endpoint_tolerance_px: float = 2.0,
    parallel_angle_tolerance_deg: float = 2.0,
) -> dict[str, Any]:
    junctions: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    parallels: list[dict[str, Any]] = []

    for left_index, a in enumerate(segments):
        if a.length <= EPSILON:
            continue
        for b in segments[left_index + 1 :]:
            if b.length <= EPSILON:
                continue
            pair = [a.id, b.id]
            angle = acute_angle_degrees(a, b)
            exact = _intersection(a, b)

            if exact and exact["kind"] == "point":
                point: Point = exact["point"]
                continuity_a = _continuity(exact["ta"], a.length, endpoint_tolerance_px)
                continuity_b = _continuity(exact["tb"], b.length, endpoint_tolerance_px)
                node_class = _junction_class(continuity_a["location"], continuity_b["location"])
                junctions.append(
                    {
                        "relation_id": "",
                        "kind": "exact_intersection",
                        "geometric_class": node_class,
                        "segment_ids": pair,
                        "coordinate_crop_px": point.as_list(),
                        "angle_degrees": round(angle, 3),
                        "separation_px": 0.0,
                        "continuity": {a.id: continuity_a, b.id: continuity_b},
                        "confidence": _geometry_confidence(a, b, 0.99),
                        "abstained": False,
                        "abstention_reason": None,
                    }
                )
            elif exact and exact["kind"] == "overlap":
                overlaps.append(
                    {
                        "relation_id": "",
                        "kind": "collinear_overlap",
                        "segment_ids": pair,
                        "overlap_crop_px": [exact["start"].as_list(), exact["end"].as_list()],
                        "overlap_length_px": round(exact["overlap_length_px"], 3),
                        "angle_degrees": round(angle, 3),
                        "confidence": _geometry_confidence(a, b, 0.99),
                        "abstained": False,
                        "abstention_reason": None,
                    }
                )
            else:
                point_a, point_b, ta, tb, separation = closest_points(a, b)
                continuity_a = _continuity(ta, a.length, endpoint_tolerance_px)
                continuity_b = _continuity(tb, b.length, endpoint_tolerance_px)
                at_least_one_endpoint = (
                    continuity_a["location"] != "interior" or continuity_b["location"] != "interior"
                )
                parallel_offset_is_not_gap = False
                if angle <= parallel_angle_tolerance_deg:
                    lateral_distance = min(
                        _point_to_infinite_line_distance(point_a, b),
                        _point_to_infinite_line_distance(point_b, a),
                    )
                    parallel_offset_is_not_gap = lateral_distance > endpoint_tolerance_px
                if (
                    separation <= near_tolerance_px
                    and at_least_one_endpoint
                    and not parallel_offset_is_not_gap
                ):
                    midpoint = Point((point_a.x + point_b.x) / 2.0, (point_a.y + point_b.y) / 2.0)
                    decay = max(0.15, 1.0 - separation / max(near_tolerance_px, EPSILON))
                    junctions.append(
                        {
                            "relation_id": "",
                            "kind": "near_junction",
                            "geometric_class": _junction_class(
                                continuity_a["location"], continuity_b["location"]
                            ),
                            "segment_ids": pair,
                            "coordinate_crop_px": midpoint.as_list(),
                            "closest_points_crop_px": [point_a.as_list(), point_b.as_list()],
                            "angle_degrees": round(angle, 3),
                            "separation_px": round(separation, 3),
                            "continuity": {a.id: continuity_a, b.id: continuity_b},
                            "confidence": _geometry_confidence(a, b, 0.85 * decay),
                            "abstained": True,
                            "abstention_reason": "segments_do_not_physically_touch_within_observed_linework",
                        }
                    )

            if angle <= parallel_angle_tolerance_deg:
                point_a, point_b, ta, tb, separation = closest_points(a, b)
                parallels.append(
                    {
                        "relation_id": "",
                        "kind": "parallel_pair",
                        "segment_ids": pair,
                        "angle_degrees": round(angle, 3),
                        "minimum_distance_px": round(separation, 3),
                        "closest_points_crop_px": [point_a.as_list(), point_b.as_list()],
                        "closest_parameters": {a.id: round(ta, 6), b.id: round(tb, 6)},
                        "confidence": _geometry_confidence(
                            a, b, 1.0 - 0.2 * angle / max(parallel_angle_tolerance_deg, EPSILON)
                        ),
                        "abstained": False,
                        "abstention_reason": None,
                    }
                )

    junctions.sort(
        key=lambda item: (
            item["coordinate_crop_px"][1],
            item["coordinate_crop_px"][0],
            item["kind"],
            item["segment_ids"],
        )
    )
    overlaps.sort(key=lambda item: (item["segment_ids"], item["overlap_crop_px"]))
    parallels.sort(key=lambda item: (item["segment_ids"], item["minimum_distance_px"]))
    for index, relation in enumerate(junctions, 1):
        relation["relation_id"] = f"junction_{index:04d}"
    for index, relation in enumerate(overlaps, 1):
        relation["relation_id"] = f"overlap_{index:04d}"
    for index, relation in enumerate(parallels, 1):
        relation["relation_id"] = f"parallel_{index:04d}"

    nodes = cluster_junctions(junctions, radius_px=3.0)
    return {
        "junction_relations": junctions,
        "overlap_relations": overlaps,
        "parallel_relations": parallels,
        "nodes": nodes,
    }


def cluster_junctions(junctions: list[dict[str, Any]], radius_px: float) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []
    for relation in junctions:
        point = Point(*relation["coordinate_crop_px"])
        selected: list[dict[str, Any]] | None = None
        for cluster in clusters:
            cx = sum(item["coordinate_crop_px"][0] for item in cluster) / len(cluster)
            cy = sum(item["coordinate_crop_px"][1] for item in cluster) / len(cluster)
            if _distance(point, Point(cx, cy)) <= radius_px:
                selected = cluster
                break
        if selected is None:
            clusters.append([relation])
        else:
            selected.append(relation)

    nodes: list[dict[str, Any]] = []
    for cluster in clusters:
        x = sum(item["coordinate_crop_px"][0] for item in cluster) / len(cluster)
        y = sum(item["coordinate_crop_px"][1] for item in cluster) / len(cluster)
        classes = sorted({item["geometric_class"] for item in cluster})
        kinds = sorted({item["kind"] for item in cluster})
        segment_ids = sorted({sid for item in cluster for sid in item["segment_ids"]})
        if len(classes) == 1:
            geometric_class = classes[0]
        else:
            geometric_class = "mixed"
        node = {
            "node_id": "",
            "coordinate_crop_px": [round(x, 3), round(y, 3)],
            "geometric_class": geometric_class,
            "observed_relation_kinds": kinds,
            "segment_ids": segment_ids,
            "relation_ids": [item["relation_id"] for item in cluster],
            "confidence": round(min(item["confidence"] for item in cluster), 3),
            "abstained": any(item["abstained"] for item in cluster) or len(classes) > 1,
            "abstention_reason": (
                "cluster_contains_near_or_mixed_geometric_evidence"
                if any(item["abstained"] for item in cluster) or len(classes) > 1
                else None
            ),
        }
        nodes.append(node)
    nodes.sort(key=lambda node: (node["coordinate_crop_px"][1], node["coordinate_crop_px"][0]))
    for index, node in enumerate(nodes, 1):
        node["node_id"] = f"node_{index:04d}"
    return nodes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_segments(linework_path: Path) -> tuple[dict[str, Any], list[Segment]]:
    payload = json.loads(linework_path.read_text(encoding="utf-8"))
    raw_candidates = payload.get("candidates", [])
    segments: list[Segment] = []
    for raw in raw_candidates:
        points = raw.get("points_px")
        if not isinstance(points, list) or len(points) != 2:
            continue
        segments.append(
            Segment(
                id=str(raw["id"]),
                start=Point(float(points[0][0]), float(points[0][1])),
                end=Point(float(points[1][0]), float(points[1][1])),
                confidence=float(raw.get("confidence", 0.0)),
                raw=raw,
            )
        )
    return payload, segments


def _source_coordinates(point: list[float], offset: tuple[float, float]) -> list[float]:
    return [round(point[0] + offset[0], 3), round(point[1] + offset[1], 3)]


def _add_source_coordinates(result: dict[str, Any], offset: tuple[float, float]) -> None:
    for node in result["nodes"]:
        node["coordinate_source_page_px"] = _source_coordinates(node["coordinate_crop_px"], offset)
    for junction in result["junction_relations"]:
        junction["coordinate_source_page_px"] = _source_coordinates(
            junction["coordinate_crop_px"], offset
        )
        if "closest_points_crop_px" in junction:
            junction["closest_points_source_page_px"] = [
                _source_coordinates(point, offset) for point in junction["closest_points_crop_px"]
            ]
    for overlap in result["overlap_relations"]:
        overlap["overlap_source_page_px"] = [
            _source_coordinates(point, offset) for point in overlap["overlap_crop_px"]
        ]
    for parallel in result["parallel_relations"]:
        parallel["closest_points_source_page_px"] = [
            _source_coordinates(point, offset) for point in parallel["closest_points_crop_px"]
        ]


def _exclusive_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def render_overlay(
    crop_path: Path,
    output_path: Path,
    segments: list[Segment],
    result: dict[str, Any],
) -> None:
    import cv2
    import numpy as np

    gray = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError(f"Cannot read crop image: {crop_path}")
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    canvas = cv2.addWeighted(base, 0.68, np.full_like(base, 255), 0.32, 0)

    for segment in segments:
        start = (round(segment.start.x), round(segment.start.y))
        end = (round(segment.end.x), round(segment.end.y))
        cv2.line(canvas, start, end, (165, 165, 165), 1, cv2.LINE_AA)

    color_by_class = {
        "crossing": (30, 190, 30),
        "endpoint_to_interior": (0, 155, 255),
        "endpoint_to_endpoint": (235, 80, 50),
        "mixed": (180, 45, 210),
    }
    for node in result["nodes"]:
        x, y = (round(value) for value in node["coordinate_crop_px"])
        color = color_by_class.get(node["geometric_class"], (180, 45, 210))
        if node["abstained"]:
            cv2.circle(canvas, (x, y), 6, color, 1, cv2.LINE_AA)
            cv2.circle(canvas, (x, y), 2, color, -1, cv2.LINE_AA)
        else:
            cv2.circle(canvas, (x, y), 4, color, -1, cv2.LINE_AA)

    margin = 30
    legend_height = 116
    enlarged = cv2.copyMakeBorder(
        canvas, legend_height, margin, margin, margin, cv2.BORDER_CONSTANT, value=(250, 250, 250)
    )
    cv2.putText(
        enlarged,
        "GEOMETRY GRAPH r001 - osservazioni geometriche, nessuna semantica edilizia",
        (margin, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (30, 30, 30),
        1,
        cv2.LINE_AA,
    )
    entries = [
        ("crossing", (30, 190, 30), False),
        ("endpoint-interior", (0, 155, 255), False),
        ("endpoint-endpoint", (235, 80, 50), False),
        ("astensione/mixed/near", (180, 45, 210), True),
    ]
    x_cursor = margin
    for label, color, hollow in entries:
        center = (x_cursor + 6, 55)
        cv2.circle(enlarged, center, 5, color, 1 if hollow else -1, cv2.LINE_AA)
        cv2.putText(
            enlarged,
            label,
            (x_cursor + 17, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (45, 45, 45),
            1,
            cv2.LINE_AA,
        )
        x_cursor += 170
    summary = (
        f"segmenti raw={len(segments)}  nodi={len(result['nodes'])}  "
        f"intersezioni/near={len(result['junction_relations'])}  "
        f"overlap={len(result['overlap_relations'])}  paralleli={len(result['parallel_relations'])}"
    )
    cv2.putText(
        enlarged,
        summary,
        (margin, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (35, 35, 35),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        enlarged,
        "Cerchio vuoto = evidenza non fisicamente connessa o cluster ambiguo; verificare sul tratto originale.",
        (margin, 108),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.39,
        (60, 60, 60),
        1,
        cv2.LINE_AA,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite: {output_path}")
    success, encoded = cv2.imencode(".png", enlarged)
    if not success:
        raise RuntimeError("PNG encoding failed")
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded.tobytes())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def build_payload(
    linework_path: Path,
    crop_path: Path,
    regions_path: Path,
    *,
    near_tolerance_px: float,
    endpoint_tolerance_px: float,
    parallel_angle_tolerance_deg: float,
) -> tuple[dict[str, Any], list[Segment]]:
    linework_payload, segments = _load_segments(linework_path)
    regions_payload = json.loads(regions_path.read_text(encoding="utf-8"))
    selected_region = next(item for item in regions_payload["regions"] if item["id"] == "region_001")
    offset = (float(selected_region["bbox_px"][0]), float(selected_region["bbox_px"][1]))
    result = analyze_segments(
        segments,
        near_tolerance_px=near_tolerance_px,
        endpoint_tolerance_px=endpoint_tolerance_px,
        parallel_angle_tolerance_deg=parallel_angle_tolerance_deg,
    )
    _add_source_coordinates(result, offset)
    counts = {
        "raw_segment_count": len(segments),
        "node_count": len(result["nodes"]),
        "exact_intersection_count": sum(
            item["kind"] == "exact_intersection" for item in result["junction_relations"]
        ),
        "near_junction_count": sum(
            item["kind"] == "near_junction" for item in result["junction_relations"]
        ),
        "collinear_overlap_count": len(result["overlap_relations"]),
        "parallel_pair_count": len(result["parallel_relations"]),
        "abstained_node_count": sum(item["abstained"] for item in result["nodes"]),
    }
    payload = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "coordinate_systems": {
            "crop_px": {"origin": "region_001_top_left", "x_axis": "right", "y_axis": "down"},
            "source_page_px": {"origin": "page_0001_top_left", "x_axis": "right", "y_axis": "down"},
            "crop_offset_in_source_page_px": [offset[0], offset[1]],
        },
        "provenance": {
            "source_crop": str(crop_path).replace("\\", "/"),
            "source_crop_sha256": _sha256(crop_path),
            "source_linework": str(linework_path).replace("\\", "/"),
            "source_linework_sha256": _sha256(linework_path),
            "source_regions": str(regions_path).replace("\\", "/"),
            "source_regions_sha256": _sha256(regions_path),
            "upstream_detector": linework_payload.get("provenance", {}),
            "engine": "nonsemantic-segment-relation-graph",
            "engine_version": "1.0.0",
        },
        "parameters": {
            "near_junction_tolerance_px": near_tolerance_px,
            "endpoint_classification_tolerance_px": endpoint_tolerance_px,
            "parallel_angle_tolerance_degrees": parallel_angle_tolerance_deg,
            "node_cluster_radius_px": 3.0,
        },
        "scope": {
            "observed_only": True,
            "semantic_labels_emitted": False,
            "explicitly_not_inferred": [
                "wall",
                "door",
                "window",
                "room",
                "property_boundary",
                "building_membership",
            ],
        },
        "summary": counts,
        "raw_segments_preserved": [segment.raw for segment in segments],
        **result,
    }
    return payload, segments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a non-semantic geometric relation graph.")
    parser.add_argument("--linework", type=Path, required=True)
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-overlay", type=Path, required=True)
    parser.add_argument("--near-tolerance", type=float, default=8.0)
    parser.add_argument("--endpoint-tolerance", type=float, default=2.0)
    parser.add_argument("--parallel-angle-tolerance", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_json.exists() or args.output_overlay.exists():
        raise FileExistsError("Revision outputs already exist; refusing any overwrite")
    payload, segments = build_payload(
        args.linework,
        args.crop,
        args.regions,
        near_tolerance_px=args.near_tolerance,
        endpoint_tolerance_px=args.endpoint_tolerance,
        parallel_angle_tolerance_deg=args.parallel_angle_tolerance,
    )
    _exclusive_write_json(args.output_json, payload)
    render_overlay(args.crop, args.output_overlay, segments, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
