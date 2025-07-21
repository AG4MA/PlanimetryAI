from typing import List, Dict, Tuple, Optional
import math


class Point2D:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def to_dict(self) -> Dict:
        return {"x": self.x, "y": self.y}

    def distance_to(self, other: "Point2D") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


class LineSegment:
    def __init__(self, start: Point2D, end: Point2D, layer: Optional[str] = None):
        self.start = start
        self.end = end
        self.layer = layer

    def to_dict(self) -> Dict:
        return {
            "type": "LineSegment",
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "layer": self.layer,
        }


class Polyline:
    def __init__(self, points: List[Point2D], closed: bool = False, layer: Optional[str] = None):
        self.points = points
        self.closed = closed
        self.layer = layer

    def to_dict(self) -> Dict:
        return {
            "type": "Polyline",
            "points": [p.to_dict() for p in self.points],
            "closed": self.closed,
            "layer": self.layer,
        }


class Arc:
    def __init__(self, center: Point2D, radius: float, start_angle: float, end_angle: float, layer: Optional[str] = None):
        self.center = center
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.layer = layer

    def to_dict(self) -> Dict:
        return {
            "type": "Arc",
            "center": self.center.to_dict(),
            "radius": self.radius,
            "start_angle": self.start_angle,
            "end_angle": self.end_angle,
            "layer": self.layer,
        }


class Polygon:
    def __init__(self, vertices: List[Point2D], layer: Optional[str] = None):
        self.vertices = vertices
        self.layer = layer

    def to_dict(self) -> Dict:
        return {
            "type": "Polygon",
            "vertices": [v.to_dict() for v in self.vertices],
            "layer": self.layer,
        }


class TextEntity:
    def __init__(self, text: str, position: Point2D, rotation: float = 0.0, layer: Optional[str] = None):
        self.text = text
        self.position = position
        self.rotation = rotation
        self.layer = layer

    def to_dict(self) -> Dict:
        return {
            "type": "Text",
            "text": self.text,
            "position": self.position.to_dict(),
            "rotation": self.rotation,
            "layer": self.layer,
        }

class RawPlanGeometry:
    def __init__(self):
        self.line_segments: List[LineSegment] = []
        self.polylines: List[Polyline] = []
        self.arcs: List[Arc] = []
        self.polygons: List[Polygon] = []
        self.texts: List[TextEntity] = []

    def to_dict(self) -> Dict:
        return {
            "line_segments": [ls.to_dict() for ls in self.line_segments],
            "polylines": [pl.to_dict() for pl in self.polylines],
            "arcs": [a.to_dict() for a in self.arcs],
            "polygons": [p.to_dict() for p in self.polygons],
            "texts": [t.to_dict() for t in self.texts],
        }
