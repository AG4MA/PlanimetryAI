"""
Geometry metrics for the Point-1 decomposition benchmark.

All functions operate on the geometry objects defined by
``decomposition.schema.json`` (``{"type": ..., "points": [[x,y],...], "bbox":[x,y,w,h]}``).
No third-party dependencies: polygon intersection-over-union is computed by
deterministic rasterization so that arbitrary (non-convex) room polygons are
handled without shapely/numpy.

Pixel coordinates throughout.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

AREA_TYPES = frozenset({"polygon", "bbox"})
LINE_TYPES = frozenset({"polyline"})
POINT_TYPES = frozenset({"point"})


# --------------------------------------------------------------------------- #
# Extraction helpers
# --------------------------------------------------------------------------- #
def _points(geom: Dict) -> List[Point]:
    pts = geom.get("points") or []
    return [(float(p[0]), float(p[1])) for p in pts if len(p) >= 2]


def bbox_to_polygon(bbox: Sequence[float]) -> List[Point]:
    x, y, w, h = (float(v) for v in bbox)
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def geom_polygon(geom: Dict) -> List[Point]:
    """Return a polygon (vertex list) for an area geometry, or [] otherwise."""
    gtype = geom.get("type")
    if gtype == "polygon":
        return _points(geom)
    if gtype == "bbox" and geom.get("bbox"):
        return bbox_to_polygon(geom["bbox"])
    return []


# --------------------------------------------------------------------------- #
# Basic geometry
# --------------------------------------------------------------------------- #
def polygon_area(points: Sequence[Point]) -> float:
    n = len(points)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def polyline_length(points: Sequence[Point]) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def centroid(points: Sequence[Point]) -> Point:
    if not points:
        return (0.0, 0.0)
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def geom_centroid(geom: Dict) -> Point:
    poly = geom_polygon(geom)
    if poly:
        return centroid(poly)
    return centroid(_points(geom))


def bbox_of(points: Sequence[Point]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def point_in_polygon(x: float, y: float, poly: Sequence[Point]) -> bool:
    """Ray-casting point-in-polygon test (edges as half-open to avoid double count)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


# --------------------------------------------------------------------------- #
# IoU
# --------------------------------------------------------------------------- #
def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def polygon_iou(poly_a: Sequence[Point], poly_b: Sequence[Point],
                target_cells: int = 128, max_cells: int = 200) -> float:
    """
    Intersection-over-union of two polygons via deterministic rasterization.
    ``target_cells`` sets the resolution along the longer combined dimension
    (capped at ``max_cells``). Robust to non-convex shapes.
    """
    if len(poly_a) < 3 or len(poly_b) < 3:
        return 0.0
    ax1, ay1, ax2, ay2 = bbox_of(poly_a)
    bx1, by1, bx2, by2 = bbox_of(poly_b)
    x1, y1 = min(ax1, bx1), min(ay1, by1)
    x2, y2 = max(ax2, bx2), max(ay2, by2)
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return 0.0
    longer = max(w, h)
    n = min(max_cells, max(16, int(target_cells)))
    cell = longer / n
    if cell <= 0:
        return 0.0
    cols = max(1, int(math.ceil(w / cell)))
    rows = max(1, int(math.ceil(h / cell)))
    inter = 0
    union = 0
    for r in range(rows):
        cy = y1 + (r + 0.5) * cell
        for c in range(cols):
            cx = x1 + (c + 0.5) * cell
            in_a = point_in_polygon(cx, cy, poly_a)
            in_b = point_in_polygon(cx, cy, poly_b)
            if in_a or in_b:
                union += 1
                if in_a and in_b:
                    inter += 1
    return inter / union if union > 0 else 0.0


def area_iou(geom_a: Dict, geom_b: Dict) -> float:
    """IoU for area geometries (polygon/bbox). Uses fast path for bbox-bbox."""
    if geom_a.get("type") == "bbox" and geom_b.get("type") == "bbox":
        if geom_a.get("bbox") and geom_b.get("bbox"):
            return bbox_iou(geom_a["bbox"], geom_b["bbox"])
    return polygon_iou(geom_polygon(geom_a), geom_polygon(geom_b))


# --------------------------------------------------------------------------- #
# Similarity used for detection matching
# --------------------------------------------------------------------------- #
def geometry_similarity(geom_a: Dict, geom_b: Dict,
                        point_tol_px: float = 15.0,
                        line_tol_px: float = 25.0) -> float:
    """
    A [0,1] similarity used to decide whether a predicted observation matches a
    ground-truth one. Area geoms -> IoU. Point/line geoms -> proximity of
    centroids normalized by a tolerance (and length ratio for lines).
    Mixed/unsupported (e.g. mask) -> 0.
    """
    ta, tb = geom_a.get("type"), geom_b.get("type")
    if ta in AREA_TYPES and tb in AREA_TYPES:
        return area_iou(geom_a, geom_b)
    if ta in POINT_TYPES and tb in POINT_TYPES:
        d = _centroid_distance(geom_a, geom_b)
        return max(0.0, 1.0 - d / point_tol_px) if point_tol_px > 0 else 0.0
    if ta in LINE_TYPES and tb in LINE_TYPES:
        d = _centroid_distance(geom_a, geom_b)
        prox = max(0.0, 1.0 - d / line_tol_px) if line_tol_px > 0 else 0.0
        la = polyline_length(_points(geom_a))
        lb = polyline_length(_points(geom_b))
        length_ratio = min(la, lb) / max(la, lb) if max(la, lb) > 0 else 0.0
        return prox * length_ratio
    return 0.0


def _centroid_distance(geom_a: Dict, geom_b: Dict) -> float:
    ca, cb = geom_centroid(geom_a), geom_centroid(geom_b)
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


# --------------------------------------------------------------------------- #
# Per-match geometric error (for accepted pairs)
# --------------------------------------------------------------------------- #
def geometry_error(geom_pred: Dict, geom_gt: Dict) -> Dict[str, Optional[float]]:
    """Return geometric error metrics for a matched pair, by geometry family."""
    tgt = geom_gt.get("type")
    out: Dict[str, Optional[float]] = {}
    if tgt in AREA_TYPES:
        a_pred = polygon_area(geom_polygon(geom_pred))
        a_gt = polygon_area(geom_polygon(geom_gt))
        out["iou"] = area_iou(geom_pred, geom_gt)
        out["area_error_ratio"] = abs(a_pred - a_gt) / a_gt if a_gt > 0 else None
    elif tgt in LINE_TYPES:
        l_pred = polyline_length(_points(geom_pred))
        l_gt = polyline_length(_points(geom_gt))
        out["length_error_ratio"] = abs(l_pred - l_gt) / l_gt if l_gt > 0 else None
        out["centroid_distance_px"] = _centroid_distance(geom_pred, geom_gt)
    elif tgt in POINT_TYPES:
        out["centroid_distance_px"] = _centroid_distance(geom_pred, geom_gt)
    return out
