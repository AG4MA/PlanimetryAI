"""
PlanNL — tolerant loader for the PlanimetryAI Knowledge Model.

PlanNL is a *consumer* of PlanParser's output, exactly like Plan2HVAC. The
canonical schema is still being frozen (see PlanimetryDigitalConventions), so
this loader is deliberately defensive and accepts every shape observed so far:

  * flat form produced by the parser today:
        {"meta": {"scale", "scale_factor"}, "rooms": [...], "topology": {"adjacency": {...}}}
  * nested form described by the HVAC contract / README:
        {"source": {...}, "floors": [{"rooms": [...]}], "topology": {...}}

Rooms may carry either ``area_m2`` (already metric) or ``area_px`` (pixels, when
no scale is set). We convert px -> m^2 only when a ``scale_factor`` is available
(interpreted as *metres per pixel*, matching Plan2HVAC's model comment
"pixels to meters conversion"), otherwise the metric area is reported as
unavailable rather than invented.

No third-party dependencies: standard library only.
"""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def normalize_text(value: str) -> str:
    """Lowercase, strip accents and collapse whitespace for robust matching."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


# Canonical room categories -> keywords found on Italian plans (and a few EN).
ROOM_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "bagno": ("bagno", "bagni", "wc", "servizio", "servizi", "toilette", "bathroom"),
    "cucina": ("cucina", "cucinotto", "kitchen"),
    "camera": ("camera", "cameretta", "letto", "bedroom"),
    "soggiorno": ("soggiorno", "salotto", "living", "sala"),
    "ingresso": ("ingresso", "disimpegno", "corridoio", "hall", "entrance", "atrio"),
    "ripostiglio": ("ripostiglio", "sgabuzzino", "cantina", "closet", "storage"),
    "balcone": ("balcone", "terrazzo", "terrazza", "balcony", "loggia"),
    "studio": ("studio", "ufficio", "office", "study"),
    "garage": ("garage", "box", "autorimessa"),
    "lavanderia": ("lavanderia", "laundry"),
}


def categorize_label(label: str) -> Optional[str]:
    """Map a raw OCR label to a canonical category, or None if unknown."""
    norm = normalize_text(label)
    for category, keywords in ROOM_CATEGORIES.items():
        for kw in keywords:
            if kw in norm:
                return category
    return None


# --------------------------------------------------------------------------- #
# Geometry helpers (all in pixel space unless converted)
# --------------------------------------------------------------------------- #
def polygon_area_px(polygon: List[Tuple[float, float]]) -> float:
    """Shoelace absolute area of a polygon in pixel units."""
    n = len(polygon)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def polygon_perimeter_px(polygon: List[Tuple[float, float]]) -> float:
    n = len(polygon)
    if n < 2:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        acc += math.hypot(x2 - x1, y2 - y1)
    return acc


def polygon_centroid(polygon: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not polygon:
        return (0.0, 0.0)
    x = sum(p[0] for p in polygon) / len(polygon)
    y = sum(p[1] for p in polygon) / len(polygon)
    return (x, y)


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
@dataclass
class Room:
    id: str
    label: str
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    area_px: Optional[float] = None
    area_m2: Optional[float] = None
    height_m: Optional[float] = None
    floor_id: Optional[str] = None
    neighbors: List[str] = field(default_factory=list)

    @property
    def category(self) -> Optional[str]:
        return categorize_label(self.label)

    @property
    def centroid(self) -> Tuple[float, float]:
        return polygon_centroid(self.polygon)

    @property
    def display_label(self) -> str:
        lbl = (self.label or "").strip()
        return lbl if lbl else f"(senza etichetta)"


@dataclass
class Building:
    source_file: Optional[str] = None
    scale: Optional[str] = None
    scale_factor: Optional[float] = None          # metres per pixel, if known
    orientation_north: Optional[float] = None      # degrees from top, if known
    rooms: List[Room] = field(default_factory=list)
    adjacency: Dict[str, List[str]] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    # -- lookups ---------------------------------------------------------- #
    def room_by_id(self, room_id: str) -> Optional[Room]:
        for r in self.rooms:
            if r.id == str(room_id):
                return r
        return None

    def rooms_of_category(self, category: str) -> List[Room]:
        return [r for r in self.rooms if r.category == category]

    @property
    def total_area_m2(self) -> Optional[float]:
        vals = [r.area_m2 for r in self.rooms if r.area_m2 is not None]
        return round(sum(vals), 2) if vals else None

    @property
    def has_metric_area(self) -> bool:
        return any(r.area_m2 is not None for r in self.rooms)


# --------------------------------------------------------------------------- #
# Loading / normalization
# --------------------------------------------------------------------------- #
def _coerce_polygon(raw_poly: Any) -> List[Tuple[float, float]]:
    poly: List[Tuple[float, float]] = []
    if isinstance(raw_poly, list):
        for pt in raw_poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    poly.append((float(pt[0]), float(pt[1])))
                except (TypeError, ValueError):
                    continue
    return poly


def _iter_raw_rooms(data: Dict[str, Any]) -> List[Tuple[Optional[str], Dict[str, Any]]]:
    """Yield (floor_id, room_dict) for both flat and nested shapes."""
    out: List[Tuple[Optional[str], Dict[str, Any]]] = []
    if isinstance(data.get("rooms"), list):
        for r in data["rooms"]:
            if isinstance(r, dict):
                out.append((None, r))
    for floor in data.get("floors", []) or []:
        if not isinstance(floor, dict):
            continue
        fid = str(floor.get("id", floor.get("label", "")))
        for r in floor.get("rooms", []) or []:
            if isinstance(r, dict):
                out.append((fid, r))
    return out


def _meters_per_pixel(data: Dict[str, Any]) -> Optional[float]:
    meta = data.get("meta", {}) or {}
    source = data.get("source", {}) or {}
    sf = meta.get("scale_factor", source.get("scale_factor"))
    try:
        sf = float(sf)
    except (TypeError, ValueError):
        return None
    return sf if sf > 0 else None


def build_from_dict(data: Dict[str, Any]) -> Building:
    meta = data.get("meta", {}) or {}
    source = data.get("source", {}) or {}

    scale = source.get("scale", meta.get("scale"))
    scale_factor = _meters_per_pixel(data)
    orientation = None
    orient_raw = source.get("orientation", meta.get("orientation"))
    if isinstance(orient_raw, dict):
        orientation = orient_raw.get("north")
    elif isinstance(orient_raw, (int, float)):
        orientation = float(orient_raw)

    rooms: List[Room] = []
    for floor_id, rd in _iter_raw_rooms(data):
        polygon = _coerce_polygon(rd.get("polygon"))
        area_px = rd.get("area_px")
        if area_px is None and polygon:
            area_px = polygon_area_px(polygon)
        try:
            area_px = float(area_px) if area_px is not None else None
        except (TypeError, ValueError):
            area_px = None

        area_m2 = rd.get("area_m2")
        try:
            area_m2 = float(area_m2) if area_m2 is not None else None
        except (TypeError, ValueError):
            area_m2 = None
        if area_m2 is None and area_px is not None and scale_factor:
            area_m2 = round(area_px * (scale_factor ** 2), 2)

        rooms.append(
            Room(
                id=str(rd.get("id", len(rooms))),
                label=rd.get("label", ""),
                polygon=polygon,
                area_px=area_px,
                area_m2=area_m2,
                height_m=(float(rd["height_m"]) if rd.get("height_m") is not None else None),
                floor_id=floor_id,
            )
        )

    adjacency = _normalize_adjacency(data, rooms)
    known = {r.id for r in rooms}
    for r in rooms:
        r.neighbors = [n for n in adjacency.get(r.id, []) if n in known and n != r.id]

    return Building(
        source_file=source.get("file", meta.get("source_file")),
        scale=scale,
        scale_factor=scale_factor,
        orientation_north=orientation,
        rooms=rooms,
        adjacency=adjacency,
        raw=data,
    )


def _normalize_adjacency(data: Dict[str, Any], rooms: List[Room]) -> Dict[str, List[str]]:
    """
    Return adjacency keyed by room id, but ONLY when the topology keys actually
    correspond to room ids. In some parser outputs ``topology.adjacency`` is
    keyed by candidate-polygon indices that do not match room ids; in that case
    we return an empty mapping so adjacency queries honestly answer
    "dato non disponibile" instead of returning garbage neighbours.
    """
    topo = data.get("topology", {}) or {}
    raw_adj = topo.get("adjacency", {}) or {}
    if not isinstance(raw_adj, dict) or not raw_adj:
        return {}
    room_ids = {r.id for r in rooms}
    keys = {str(k) for k in raw_adj.keys()}
    # Require a meaningful overlap between topology keys and real room ids.
    if not room_ids or len(room_ids & keys) < max(1, len(room_ids) // 2):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in raw_adj.items():
        if str(k) in room_ids and isinstance(v, list):
            out[str(k)] = [str(n) for n in v]
    return out


def load(path: str) -> Building:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Knowledge Model root must be a JSON object")
    return build_from_dict(data)
