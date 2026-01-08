import math


class Point2D:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    def distance_to(self, other: "Point2D") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


class LineSegment:
    def __init__(self, start: Point2D, end: Point2D, layer: str | None = None):
        self.start = start
        self.end = end
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "type": "LineSegment",
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "layer": self.layer,
        }


class Polyline:
    def __init__(self, points: list[Point2D], closed: bool = False, layer: str | None = None):
        self.points = points
        self.closed = closed
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "type": "Polyline",
            "points": [p.to_dict() for p in self.points],
            "closed": self.closed,
            "layer": self.layer,
        }


class Arc:
    def __init__(self, center: Point2D, radius: float, start_angle: float, end_angle: float, layer: str | None = None):
        self.center = center
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "type": "Arc",
            "center": self.center.to_dict(),
            "radius": self.radius,
            "start_angle": self.start_angle,
            "end_angle": self.end_angle,
            "layer": self.layer,
        }


class Polygon:
    def __init__(self, vertices: list[Point2D], layer: str | None = None):
        self.vertices = vertices
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "type": "Polygon",
            "vertices": [v.to_dict() for v in self.vertices],
            "layer": self.layer,
        }


class TextEntity:
    def __init__(self, text: str, position: Point2D, rotation: float = 0.0, layer: str | None = None):
        self.text = text
        self.position = position
        self.rotation = rotation
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "type": "Text",
            "text": self.text,
            "position": self.position.to_dict(),
            "rotation": self.rotation,
            "layer": self.layer,
        }

class RawPlanGeometry:
    def __init__(self):
        self.line_segments: list[LineSegment] = []
        self.polylines: list[Polyline] = []
        self.arcs: list[Arc] = []
        self.polygons: list[Polygon] = []
        self.texts: list[TextEntity] = []

    def to_dict(self) -> dict:
        return {
            "line_segments": [ls.to_dict() for ls in self.line_segments],
            "polylines": [pl.to_dict() for pl in self.polylines],
            "arcs": [a.to_dict() for a in self.arcs],
            "polygons": [p.to_dict() for p in self.polygons],
            "texts": [t.to_dict() for t in self.texts],
        }
