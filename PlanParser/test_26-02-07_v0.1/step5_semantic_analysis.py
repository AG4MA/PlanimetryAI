"""
Step 5: Semantic Analysis.

Given extracted lines + text blocks, applies rules and topology
to create meaning:
  - Build DCEL topology from segments
  - Classify faces as rooms (area filtering)
  - Match text blocks to rooms (point-in-polygon)
  - Classify walls (external vs internal)
  - Detect connections (gaps in walls = doors/passages)
"""

import cv2
import math
import numpy as np
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
import logging

from geometry_types import Segment, TextBlock
from dcel import DCEL, Face, HalfEdge
from graph_builder import GraphBuilder


# Room label equivalence dictionary (from work_on_sections_v2.1.py)
ROOM_LABEL_EQUIV = {
    "sala": {"sala", "soggiorno", "soggiorno-pranzo"},
    "soggiorno": {"soggiorno", "sala", "soggiorno-pranzo"},
    "dis": {"dis", "dis.", "disimpegno", "corridoio"},
    "bagno": {"bagno", "wc"},
    "ripostiglio": {"ripostiglio", "rip.", "rip"},
    "balcone": {"balcone", "terrazzo"},
    "cucina": {"cucina", "angolo cottura", "cottura"},
    "camera": {"camera", "letto", "stanza"},
    "portico": {"portico", "veranda"},
}

KNOWN_ROOM_LABELS = set()
for _key, _vals in ROOM_LABEL_EQUIV.items():
    KNOWN_ROOM_LABELS.add(_key)
    KNOWN_ROOM_LABELS.update(_vals)


def _normalize_label(text: str) -> str:
    """Normalize a room label for matching."""
    text = text.lower().strip()
    text = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    text = text.replace("-", " ")
    text = " ".join(text.split())
    return text


def _point_in_polygon(px: float, py: float, polygon: List[Tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


@dataclass
class AnalyzedRoom:
    """A room with full semantic information from analysis."""
    face_id: int
    polygon: List[Tuple[float, float]]
    label: Optional[str] = None
    label_confidence: float = 0.0
    area_px: float = 0.0
    walls: List[Dict] = field(default_factory=list)
    connections: List[Dict] = field(default_factory=list)


class SemanticAnalyzer:
    """
    Given extracted lines + text, build topology and assign meaning.
    """

    def __init__(
        self,
        min_room_area_px: float = 1000.0,
        max_room_area_px: float = float('inf'),
        door_gap_min_px: float = 15.0,
        door_gap_max_px: float = 80.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.min_room_area_px = min_room_area_px
        self.max_room_area_px = max_room_area_px
        self.door_gap_min_px = door_gap_min_px
        self.door_gap_max_px = door_gap_max_px
        self.logger = logger

    def analyze(
        self,
        segments: List[Segment],
        text_blocks: List[TextBlock],
        image_shape: Tuple[int, int],
        debug_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> Tuple[DCEL, List[AnalyzedRoom]]:
        """
        Full semantic analysis pipeline:

        1. Build DCEL topology from segments (via GraphBuilder)
        2. Enumerate and filter rooms by area
        3. Match text blocks to rooms (point-in-polygon)
        4. Classify walls (external = on boundary)
        5. Detect connections (gaps between adjacent rooms)

        Returns:
            (dcel, analyzed_rooms)
        """
        log = logger or self.logger

        if debug_dir:
            debug_dir = Path(debug_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)

        # 1. Build topology
        if log:
            log.info("    Semantic: building topology...")
        dcel, rooms = self._build_topology(segments, log)
        if log:
            log.info("    Semantic: %d room candidates", len(rooms))

        # 2. Match text to rooms
        if log:
            log.info("    Semantic: matching text to rooms...")
        labels = self._match_text_to_rooms(rooms, text_blocks)
        if log:
            for fid, lbl in labels.items():
                log.info("      Face %d -> '%s'", fid, lbl)

        # 3. Classify walls
        if log:
            log.info("    Semantic: classifying walls...")
        walls_by_room = self._classify_walls(dcel, rooms, image_shape)

        # 4. Detect connections
        if log:
            log.info("    Semantic: detecting connections...")
        connections = self._detect_connections(dcel, rooms, segments)

        # 5. Assemble results
        analyzed = []
        for face in rooms:
            polygon = face.get_polygon()
            area = face.compute_area()
            label_text = labels.get(face.id)

            analyzed.append(AnalyzedRoom(
                face_id=face.id,
                polygon=polygon,
                label=label_text,
                label_confidence=1.0 if label_text else 0.0,
                area_px=area,
                walls=walls_by_room.get(face.id, []),
                connections=[c for c in connections if c.get("from_room_id") == face.id],
            ))

        # Debug visualization
        if debug_dir and rooms:
            self._save_debug_images(dcel, rooms, labels, image_shape, debug_dir)

        return dcel, analyzed

    def _build_topology(
        self,
        segments: List[Segment],
        logger: Optional[logging.Logger],
    ) -> Tuple[DCEL, List[Face]]:
        """Build DCEL and extract room faces."""
        builder = GraphBuilder()
        dcel = builder.build(segments, logger=logger)

        rooms = []
        for face in dcel.faces.values():
            if face.is_external:
                continue
            area = face.compute_area()
            if self.min_room_area_px <= area <= self.max_room_area_px:
                rooms.append(face)

        return dcel, rooms

    def _match_text_to_rooms(
        self,
        rooms: List[Face],
        text_blocks: List[TextBlock],
    ) -> Dict[int, str]:
        """
        For each text block, find which room polygon contains its center.
        Returns {face_id: "label text"}.
        """
        result: Dict[int, str] = {}

        for tb in text_blocks:
            norm = _normalize_label(tb.text)
            if not norm or len(norm) < 2:
                continue

            # Check if this is a known room label
            is_known = any(
                norm == known or norm in ROOM_LABEL_EQUIV.get(known, set())
                for known in KNOWN_ROOM_LABELS
            )

            for face in rooms:
                polygon = face.get_polygon()
                if _point_in_polygon(tb.cx, tb.cy, polygon):
                    # Prefer known room labels over unknown text
                    existing = result.get(face.id)
                    if existing is None:
                        result[face.id] = tb.text
                    elif is_known and _normalize_label(existing) not in KNOWN_ROOM_LABELS:
                        result[face.id] = tb.text
                    break  # Each text block belongs to at most one room

        return result

    def _classify_walls(
        self,
        dcel: DCEL,
        rooms: List[Face],
        image_shape: Tuple[int, int],
    ) -> Dict[int, List[Dict]]:
        """
        For each room, classify each wall edge as external or internal.

        External = the twin face is the external (unbounded) face,
                   OR the edge endpoints are near the image boundary.
        """
        img_h, img_w = image_shape
        boundary_threshold = 15.0  # pixels from edge

        walls_by_room: Dict[int, List[Dict]] = {}

        for face in rooms:
            walls = []
            if face.outer_edge is None:
                walls_by_room[face.id] = walls
                continue

            edge = face.outer_edge
            start = edge
            max_steps = 10000
            steps = 0

            while True:
                origin = edge.origin
                dest = edge.destination()

                if origin and dest:
                    # Determine wall type
                    is_external = False

                    # Check if twin face is the external face
                    if edge.twin and edge.twin.face and edge.twin.face.is_external:
                        is_external = True

                    # Check if near image boundary
                    if not is_external:
                        near_boundary = (
                            (origin.x < boundary_threshold and dest.x < boundary_threshold) or
                            (origin.y < boundary_threshold and dest.y < boundary_threshold) or
                            (origin.x > img_w - boundary_threshold and dest.x > img_w - boundary_threshold) or
                            (origin.y > img_h - boundary_threshold and dest.y > img_h - boundary_threshold)
                        )
                        if near_boundary:
                            is_external = True

                    wall_type = "external" if is_external else "internal"
                    edge.is_external_wall = is_external

                    walls.append({
                        "wall_type": wall_type,
                        "start_point": (origin.x, origin.y),
                        "end_point": (dest.x, dest.y),
                        "length_px": edge.length(),
                    })

                edge = edge.next
                steps += 1
                if edge is None or edge == start or steps > max_steps:
                    break

            walls_by_room[face.id] = walls

        return walls_by_room

    def _detect_connections(
        self,
        dcel: DCEL,
        rooms: List[Face],
        segments: List[Segment],
    ) -> List[Dict]:
        """
        Detect doors/passages as gaps between adjacent rooms.

        For each pair of adjacent rooms, find shared wall edges.
        Look for degree-1 vertices (dead ends) that indicate wall gaps.
        If two dead ends are close, classify as a door/passage.
        """
        connections = []
        dual = dcel.build_dual_graph()
        room_ids = {f.id for f in rooms}

        # Track which pairs we've already processed
        processed: Set[Tuple[int, int]] = set()

        for face in rooms:
            neighbors = dual.get(face.id, [])
            for neighbor_id in neighbors:
                if neighbor_id not in room_ids:
                    continue

                pair = tuple(sorted((face.id, neighbor_id)))
                if pair in processed:
                    continue
                processed.add(pair)

                # Find shared edges between these two rooms
                shared_edges = []
                for edge in dcel.half_edges.values():
                    if (edge.face and edge.twin and edge.twin.face):
                        f1 = edge.face.id
                        f2 = edge.twin.face.id
                        if (f1 == face.id and f2 == neighbor_id) or \
                           (f1 == neighbor_id and f2 == face.id):
                            shared_edges.append(edge)

                if shared_edges:
                    # For now, record a connection at the midpoint of shared wall
                    total_x, total_y = 0.0, 0.0
                    for e in shared_edges:
                        if e.origin and e.destination():
                            total_x += (e.origin.x + e.destination().x) / 2
                            total_y += (e.origin.y + e.destination().y) / 2
                    n = len(shared_edges)
                    mid = (total_x / n, total_y / n)

                    connections.append({
                        "from_room_id": face.id,
                        "to_room_id": neighbor_id,
                        "connection_type": "passage",
                        "position": mid,
                    })

        return connections

    def _save_debug_images(
        self,
        dcel: DCEL,
        rooms: List[Face],
        labels: Dict[int, str],
        image_shape: Tuple[int, int],
        debug_dir: Path,
    ):
        """Save debug visualization images."""
        img_h, img_w = image_shape

        # 1. Topology (all edges)
        topo_img = np.ones((img_h, img_w, 3), dtype=np.uint8) * 255
        for edge in dcel.half_edges.values():
            if edge.origin and edge.destination():
                o = edge.origin
                d = edge.destination()
                cv2.line(topo_img, (int(o.x), int(o.y)), (int(d.x), int(d.y)),
                         (180, 180, 180), 1)
        cv2.imwrite(str(debug_dir / "01_topology.png"), topo_img)

        # 2. Rooms colored
        rooms_img = np.ones((img_h, img_w, 3), dtype=np.uint8) * 255
        colors = [
            (100, 200, 100), (200, 100, 100), (100, 100, 200),
            (200, 200, 100), (200, 100, 200), (100, 200, 200),
            (150, 150, 100), (100, 150, 150), (150, 100, 150),
        ]
        for i, face in enumerate(rooms):
            polygon = face.get_polygon()
            if len(polygon) < 3:
                continue
            pts = np.array(polygon, dtype=np.int32)
            color = colors[i % len(colors)]
            cv2.fillPoly(rooms_img, [pts], color)

            # Draw label
            label = labels.get(face.id, f"room_{face.id}")
            centroid = np.mean(pts, axis=0).astype(int)
            cv2.putText(rooms_img, label, tuple(centroid),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        cv2.imwrite(str(debug_dir / "02_rooms_colored.png"), rooms_img)

        # 3. Walls classified
        walls_img = np.ones((img_h, img_w, 3), dtype=np.uint8) * 255
        for edge in dcel.half_edges.values():
            if edge.origin and edge.destination():
                o = edge.origin
                d = edge.destination()
                if edge.is_external_wall:
                    color = (0, 0, 255)  # Red = external
                    thickness = 2
                else:
                    color = (255, 0, 0)  # Blue = internal
                    thickness = 1
                cv2.line(walls_img, (int(o.x), int(o.y)), (int(d.x), int(d.y)),
                         color, thickness)
        cv2.imwrite(str(debug_dir / "03_walls_classified.png"), walls_img)
