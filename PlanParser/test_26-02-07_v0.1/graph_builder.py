"""
Graph Builder: constructs a DCEL from line segments.

Pipeline:
    Segments -> Intersections -> Split segments -> Vertices + HalfEdges -> DCEL
"""

import math
from typing import List, Tuple, Optional, Dict, Set
from dataclasses import dataclass
from collections import defaultdict
import logging

from geometry_types import Segment
from dcel import DCEL, Vertex, HalfEdge, Face


@dataclass
class Intersection:
    """An intersection point between two segments."""
    x: float
    y: float
    segment1_idx: int
    segment2_idx: int


def line_intersection(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    p4: Tuple[float, float],
) -> Optional[Tuple[float, float]]:
    """
    Find the intersection of segments (p1-p2) and (p3-p4).

    Uses parametric form. Returns (x, y) if segments intersect, None otherwise.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

    if abs(denom) < 1e-10:
        return None  # Parallel

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (x, y)

    return None


def find_all_intersections(segments: List[Segment]) -> List[Intersection]:
    """Find all pairwise intersections. O(n^2) - acceptable for floor plans."""
    intersections = []
    for i, s1 in enumerate(segments):
        for j, s2 in enumerate(segments[i + 1:], start=i + 1):
            p = line_intersection(
                (s1.x1, s1.y1), (s1.x2, s1.y2),
                (s2.x1, s2.y1), (s2.x2, s2.y2),
            )
            if p:
                intersections.append(Intersection(p[0], p[1], i, j))
    return intersections


def split_segments_at_intersections(
    segments: List[Segment],
    intersections: List[Intersection],
    tolerance: float = 1.0,
) -> List[Segment]:
    """
    Split segments at intersection points.

    After this, segments touch only at endpoints, never in the middle.
    """
    splits: Dict[int, List[Tuple[float, float]]] = defaultdict(list)

    for inter in intersections:
        splits[inter.segment1_idx].append((inter.x, inter.y))
        splits[inter.segment2_idx].append((inter.x, inter.y))

    new_segments = []

    for i, seg in enumerate(segments):
        if i not in splits:
            new_segments.append(seg)
            continue

        points = [(seg.x1, seg.y1)] + splits[i] + [(seg.x2, seg.y2)]

        # Sort by distance from start
        def dist_from_start(p):
            return (p[0] - seg.x1) ** 2 + (p[1] - seg.y1) ** 2

        points.sort(key=dist_from_start)

        # Remove duplicates within tolerance
        unique_points = [points[0]]
        for p in points[1:]:
            dx = p[0] - unique_points[-1][0]
            dy = p[1] - unique_points[-1][1]
            if dx * dx + dy * dy > tolerance * tolerance:
                unique_points.append(p)

        # Create sub-segments
        for j in range(len(unique_points) - 1):
            p1, p2 = unique_points[j], unique_points[j + 1]
            new_seg = Segment(p1[0], p1[1], p2[0], p2[1])
            if new_seg.length > tolerance:
                new_segments.append(new_seg)

    return new_segments


class GraphBuilder:
    """Build a DCEL from a list of segments."""

    def __init__(self, vertex_tolerance: float = 3.0):
        self.vertex_tolerance = vertex_tolerance

    def build(
        self,
        segments: List[Segment],
        logger: Optional[logging.Logger] = None,
    ) -> DCEL:
        """
        Build DCEL from segments:
        1. Find all intersections
        2. Split segments at intersections
        3. Create vertices + half-edge pairs
        4. Link next/prev around each vertex
        5. Enumerate faces
        6. Identify external face
        """
        if logger:
            logger.info("    GraphBuilder: %d input segments", len(segments))

        # Step 1: Find intersections
        intersections = find_all_intersections(segments)
        if logger:
            logger.info("    GraphBuilder: %d intersections", len(intersections))

        # Step 2: Split segments
        split_segs = split_segments_at_intersections(segments, intersections)
        if logger:
            logger.info("    GraphBuilder: %d segments after split", len(split_segs))

        # Step 3: Build DCEL with distance-based vertex dedup
        dcel = DCEL()
        existing_vertices: List[Vertex] = []

        def get_or_create_vertex(x: float, y: float) -> Vertex:
            # Distance-based nearest-neighbor lookup (fixes grid-rounding bug)
            for v in existing_vertices:
                dx = v.x - x
                dy = v.y - y
                if dx * dx + dy * dy <= self.vertex_tolerance * self.vertex_tolerance:
                    return v
            v = dcel.create_vertex(x, y)
            existing_vertices.append(v)
            return v

        for seg in split_segs:
            v1 = get_or_create_vertex(seg.x1, seg.y1)
            v2 = get_or_create_vertex(seg.x2, seg.y2)
            if v1 == v2:
                continue
            dcel.create_edge_pair(v1, v2)

        if logger:
            logger.info("    GraphBuilder: %d vertices, %d half-edges",
                        len(dcel.vertices), len(dcel.half_edges))

        # Step 4: Link edges
        self._link_edges(dcel)

        # Step 5: Enumerate faces
        faces = dcel.enumerate_faces()
        if logger:
            logger.info("    GraphBuilder: %d faces", len(faces))

        # Step 6: Identify external face
        self._identify_external_face(dcel, faces)

        # Validate
        valid, msg = dcel.validate()
        if logger:
            logger.info("    GraphBuilder: %s", msg)

        return dcel

    def _link_edges(self, dcel: DCEL):
        """Link half-edges around each vertex by angle (counterclockwise)."""
        edges_from: Dict[int, List[HalfEdge]] = defaultdict(list)

        for edge in dcel.half_edges.values():
            if edge.origin:
                edges_from[edge.origin.id].append(edge)

        for vertex_id in dcel.vertices:
            vertex = dcel.vertices[vertex_id]
            outgoing = edges_from[vertex_id]

            if len(outgoing) < 1:
                continue

            def edge_angle(e: HalfEdge) -> float:
                dest = e.destination()
                if dest is None:
                    return 0.0
                dx = dest.x - vertex.x
                dy = dest.y - vertex.y
                return math.atan2(dy, dx)

            # Sort counterclockwise (ascending angle)
            sorted_outgoing = sorted(outgoing, key=edge_angle)

            # Link: incoming edge's next = next outgoing edge
            for i, e_out in enumerate(sorted_outgoing):
                e_in = e_out.twin
                if e_in is None:
                    continue
                next_idx = (i + 1) % len(sorted_outgoing)
                next_out = sorted_outgoing[next_idx]
                e_in.next = next_out
                next_out.prev = e_in

    def _identify_external_face(self, dcel: DCEL, faces: List[Face]):
        """Identify the external (unbounded) face - the one with largest area."""
        if not faces:
            return

        max_area = -1
        external = None
        for face in faces:
            area = face.compute_area()
            if area > max_area:
                max_area = area
                external = face

        if external:
            external.is_external = True
            external.label = "EXTERNAL"


def segments_to_rooms(
    segments: List[Segment],
    min_room_area: float = 1000.0,
    max_room_area: float = float('inf'),
    logger: Optional[logging.Logger] = None,
) -> Tuple[DCEL, List[Face]]:
    """Convenience: segments -> (dcel, rooms)."""
    builder = GraphBuilder()
    dcel = builder.build(segments, logger=logger)

    rooms = []
    for face in dcel.faces.values():
        if face.is_external:
            continue
        area = face.compute_area()
        if min_room_area <= area <= max_room_area:
            rooms.append(face)

    return dcel, rooms
