"""
DCEL - Doubly Connected Edge List.

Represents planar subdivisions (floor plan rooms) using the half-edge
data structure from de Berg et al. "Computational Geometry".

This is a pure data structure. Construction from segments is done
by GraphBuilder.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Set
import math


@dataclass
class Vertex:
    """A vertex (wall intersection point)."""
    id: int
    x: float
    y: float
    incident_edge: Optional['HalfEdge'] = None

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if not isinstance(other, Vertex):
            return False
        return self.id == other.id

    def distance_to(self, other: 'Vertex') -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def coords(self) -> Tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Face:
    """A face (room or external unbounded region)."""
    id: int
    outer_edge: Optional['HalfEdge'] = None
    inner_edges: List['HalfEdge'] = field(default_factory=list)
    label: Optional[str] = None
    is_external: bool = False

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if not isinstance(other, Face):
            return False
        return self.id == other.id

    def get_vertices(self) -> List[Vertex]:
        """Return all boundary vertices in order."""
        if self.outer_edge is None:
            return []
        vertices = []
        edge = self.outer_edge
        start = edge
        max_steps = 10000  # Infinite loop guard
        steps = 0
        while True:
            vertices.append(edge.origin)
            edge = edge.next
            steps += 1
            if edge is None or edge == start or steps > max_steps:
                break
        return vertices

    def get_polygon(self) -> List[Tuple[float, float]]:
        """Return polygon coordinates."""
        return [v.coords() for v in self.get_vertices()]

    def compute_area(self) -> float:
        """Compute area using the Shoelace formula."""
        coords = self.get_polygon()
        if len(coords) < 3:
            return 0.0
        n = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += coords[i][0] * coords[j][1]
            area -= coords[j][0] * coords[i][1]
        return abs(area) / 2.0

    def compute_signed_area(self) -> float:
        """Compute signed area (positive = CCW, negative = CW)."""
        coords = self.get_polygon()
        if len(coords) < 3:
            return 0.0
        n = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += coords[i][0] * coords[j][1]
            area -= coords[j][0] * coords[i][1]
        return area / 2.0


@dataclass
class HalfEdge:
    """
    A half-edge.

    Each wall segment is represented by TWO half-edges:
    - One for each direction
    - Each half-edge "belongs" to the face on its left
    """
    id: int
    origin: Optional[Vertex] = None
    twin: Optional['HalfEdge'] = None
    face: Optional[Face] = None
    next: Optional['HalfEdge'] = None
    prev: Optional['HalfEdge'] = None

    # Metadata flags (set during semantic analysis)
    is_door: bool = False
    is_window: bool = False
    is_external_wall: bool = False

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        if not isinstance(other, HalfEdge):
            return False
        return self.id == other.id

    def destination(self) -> Optional[Vertex]:
        """The destination vertex (= origin of twin)."""
        if self.twin:
            return self.twin.origin
        return None

    def length(self) -> float:
        """Length of this edge."""
        if self.origin and self.twin and self.twin.origin:
            return self.origin.distance_to(self.twin.origin)
        return 0.0


class DCEL:
    """
    Doubly Connected Edge List.

    Provides O(1) access to vertices, edges, faces and
    O(1) navigation between adjacent elements.
    """

    def __init__(self):
        self.vertices: Dict[int, Vertex] = {}
        self.half_edges: Dict[int, HalfEdge] = {}
        self.faces: Dict[int, Face] = {}

        self._next_vertex_id = 0
        self._next_edge_id = 0
        self._next_face_id = 0

    def create_vertex(self, x: float, y: float) -> Vertex:
        v = Vertex(id=self._next_vertex_id, x=x, y=y)
        self.vertices[v.id] = v
        self._next_vertex_id += 1
        return v

    def create_half_edge(self) -> HalfEdge:
        e = HalfEdge(id=self._next_edge_id)
        self.half_edges[e.id] = e
        self._next_edge_id += 1
        return e

    def create_face(self, label: Optional[str] = None) -> Face:
        f = Face(id=self._next_face_id, label=label)
        self.faces[f.id] = f
        self._next_face_id += 1
        return f

    def create_edge_pair(self, v1: Vertex, v2: Vertex) -> Tuple[HalfEdge, HalfEdge]:
        """Create a pair of twin half-edges between two vertices."""
        e1 = self.create_half_edge()
        e2 = self.create_half_edge()

        e1.origin = v1
        e2.origin = v2

        e1.twin = e2
        e2.twin = e1

        if v1.incident_edge is None:
            v1.incident_edge = e1
        if v2.incident_edge is None:
            v2.incident_edge = e2

        return e1, e2

    def enumerate_faces(self) -> List[Face]:
        """
        Enumerate all faces by traversing half-edge cycles.

        Uses a per-cycle visited set to avoid the infinite loop bug
        from testV1. Also guards with max_steps.
        """
        global_visited: Set[int] = set()
        faces: List[Face] = []
        max_steps = len(self.half_edges) + 1

        for edge_id, edge in self.half_edges.items():
            if edge_id in global_visited:
                continue

            # Walk this cycle
            cycle: List[HalfEdge] = []
            current = edge
            cycle_visited: Set[int] = set()
            steps = 0

            while current is not None and current.id not in cycle_visited and steps < max_steps:
                cycle.append(current)
                cycle_visited.add(current.id)
                steps += 1
                current = current.next
                if current is not None and current.id == edge.id:
                    break  # Completed the cycle

            # Mark all edges in this cycle as globally visited
            global_visited.update(cycle_visited)

            # If we have a closed cycle (>=3 edges), create/identify the face
            is_closed = (current is not None and current.id == edge.id and len(cycle) >= 3)
            if is_closed:
                face = cycle[0].face
                if face is None:
                    face = self.create_face()
                    face.outer_edge = edge
                    for e in cycle:
                        e.face = face
                if face not in faces:
                    faces.append(face)

        return faces

    def get_rooms(self, min_area: float = 0.0, max_area: float = float('inf')) -> List[Face]:
        """Return faces that are rooms (not external, area within range)."""
        rooms = []
        for face in self.enumerate_faces():
            if face.is_external:
                continue
            area = face.compute_area()
            if min_area <= area <= max_area:
                rooms.append(face)
        return rooms

    def build_dual_graph(self) -> Dict[int, List[int]]:
        """Build the dual graph: nodes = faces, edges = shared walls."""
        adjacency: Dict[int, Set[int]] = {f.id: set() for f in self.faces.values()}

        for edge in self.half_edges.values():
            if edge.face and edge.twin and edge.twin.face:
                f1_id = edge.face.id
                f2_id = edge.twin.face.id
                if f1_id != f2_id:
                    adjacency[f1_id].add(f2_id)
                    adjacency[f2_id].add(f1_id)

        return {k: list(v) for k, v in adjacency.items()}

    def validate(self) -> Tuple[bool, str]:
        """Validate using Euler's formula: V - E + F = 2."""
        V = len(self.vertices)
        E = len(self.half_edges) // 2
        F = len(self.enumerate_faces())
        euler = V - E + F

        if euler == 2:
            return True, f"Euler OK: V({V}) - E({E}) + F({F}) = 2"
        else:
            return False, f"Euler FAIL: V({V}) - E({E}) + F({F}) = {euler} (expected 2)"
