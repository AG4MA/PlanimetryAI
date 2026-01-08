"""
Tests for geometry module.
"""

import math

from PlanParser.geometry import (
    Arc,
    LineSegment,
    Point2D,
    Polygon,
    Polyline,
    RawPlanGeometry,
    TextEntity,
)


class TestPoint2D:
    """Tests for Point2D class."""

    def test_creation(self) -> None:
        """Test point creation."""
        p = Point2D(10.0, 20.0)
        assert p.x == 10.0
        assert p.y == 20.0

    def test_to_dict(self) -> None:
        """Test point serialization."""
        p = Point2D(5.5, 7.5)
        d = p.to_dict()
        assert d == {"x": 5.5, "y": 7.5}

    def test_distance_to_same_point(self) -> None:
        """Test distance to same point is zero."""
        p = Point2D(10.0, 20.0)
        assert p.distance_to(p) == 0.0

    def test_distance_to_other_point(self) -> None:
        """Test distance calculation."""
        p1 = Point2D(0.0, 0.0)
        p2 = Point2D(3.0, 4.0)
        assert p1.distance_to(p2) == 5.0  # 3-4-5 triangle

    def test_distance_to_negative_coords(self) -> None:
        """Test distance with negative coordinates."""
        p1 = Point2D(-1.0, -1.0)
        p2 = Point2D(2.0, 3.0)
        expected = math.hypot(3.0, 4.0)
        assert p1.distance_to(p2) == expected


class TestLineSegment:
    """Tests for LineSegment class."""

    def test_creation(self) -> None:
        """Test line segment creation."""
        start = Point2D(0.0, 0.0)
        end = Point2D(10.0, 10.0)
        line = LineSegment(start, end, layer="walls")

        assert line.start.x == 0.0
        assert line.end.x == 10.0
        assert line.layer == "walls"

    def test_to_dict(self) -> None:
        """Test line segment serialization."""
        start = Point2D(0.0, 0.0)
        end = Point2D(5.0, 5.0)
        line = LineSegment(start, end, layer="test")

        d = line.to_dict()
        assert d["type"] == "LineSegment"
        assert d["start"] == {"x": 0.0, "y": 0.0}
        assert d["end"] == {"x": 5.0, "y": 5.0}
        assert d["layer"] == "test"

    def test_no_layer(self) -> None:
        """Test line segment without layer."""
        line = LineSegment(Point2D(0, 0), Point2D(1, 1))
        assert line.layer is None
        assert line.to_dict()["layer"] is None


class TestPolyline:
    """Tests for Polyline class."""

    def test_creation(self) -> None:
        """Test polyline creation."""
        points = [Point2D(0, 0), Point2D(10, 0), Point2D(10, 10)]
        poly = Polyline(points, closed=False)

        assert len(poly.points) == 3
        assert poly.closed is False

    def test_closed_polyline(self) -> None:
        """Test closed polyline."""
        points = [Point2D(0, 0), Point2D(10, 0), Point2D(10, 10), Point2D(0, 10)]
        poly = Polyline(points, closed=True, layer="outline")

        assert poly.closed is True
        assert poly.layer == "outline"

    def test_to_dict(self) -> None:
        """Test polyline serialization."""
        points = [Point2D(0, 0), Point2D(5, 0)]
        poly = Polyline(points, closed=True)

        d = poly.to_dict()
        assert d["type"] == "Polyline"
        assert len(d["points"]) == 2
        assert d["closed"] is True


class TestArc:
    """Tests for Arc class."""

    def test_creation(self) -> None:
        """Test arc creation."""
        center = Point2D(50.0, 50.0)
        arc = Arc(center, radius=25.0, start_angle=0.0, end_angle=90.0)

        assert arc.center.x == 50.0
        assert arc.radius == 25.0
        assert arc.start_angle == 0.0
        assert arc.end_angle == 90.0

    def test_to_dict(self) -> None:
        """Test arc serialization."""
        arc = Arc(Point2D(0, 0), radius=10.0, start_angle=0.0, end_angle=180.0, layer="curves")

        d = arc.to_dict()
        assert d["type"] == "Arc"
        assert d["radius"] == 10.0
        assert d["layer"] == "curves"


class TestPolygon:
    """Tests for Polygon class."""

    def test_creation(self) -> None:
        """Test polygon creation."""
        vertices = [
            Point2D(0, 0),
            Point2D(100, 0),
            Point2D(100, 100),
            Point2D(0, 100),
        ]
        polygon = Polygon(vertices, layer="rooms")

        assert len(polygon.vertices) == 4
        assert polygon.layer == "rooms"

    def test_to_dict(self) -> None:
        """Test polygon serialization."""
        vertices = [Point2D(0, 0), Point2D(10, 0), Point2D(5, 10)]
        polygon = Polygon(vertices)

        d = polygon.to_dict()
        assert d["type"] == "Polygon"
        assert len(d["vertices"]) == 3


class TestTextEntity:
    """Tests for TextEntity class."""

    def test_creation(self) -> None:
        """Test text entity creation."""
        text = TextEntity(
            text="Camera",
            position=Point2D(50.0, 50.0),
            rotation=0.0,
            layer="labels",
        )

        assert text.text == "Camera"
        assert text.position.x == 50.0
        assert text.rotation == 0.0

    def test_with_rotation(self) -> None:
        """Test text entity with rotation."""
        text = TextEntity(
            text="Bagno",
            position=Point2D(0, 0),
            rotation=45.0,
        )

        assert text.rotation == 45.0

    def test_to_dict(self) -> None:
        """Test text entity serialization."""
        text = TextEntity(text="Test", position=Point2D(10, 20))

        d = text.to_dict()
        assert d["type"] == "Text"
        assert d["text"] == "Test"
        assert d["position"] == {"x": 10, "y": 20}


class TestRawPlanGeometry:
    """Tests for RawPlanGeometry class."""

    def test_empty_geometry(self) -> None:
        """Test empty geometry creation."""
        geom = RawPlanGeometry()

        assert len(geom.line_segments) == 0
        assert len(geom.polylines) == 0
        assert len(geom.arcs) == 0
        assert len(geom.polygons) == 0
        assert len(geom.texts) == 0

    def test_add_elements(self) -> None:
        """Test adding elements to geometry."""
        geom = RawPlanGeometry()

        geom.line_segments.append(LineSegment(Point2D(0, 0), Point2D(10, 10)))
        geom.texts.append(TextEntity("Label", Point2D(5, 5)))
        geom.polygons.append(Polygon([Point2D(0, 0), Point2D(1, 0), Point2D(0, 1)]))

        assert len(geom.line_segments) == 1
        assert len(geom.texts) == 1
        assert len(geom.polygons) == 1

    def test_to_dict(self) -> None:
        """Test geometry serialization."""
        geom = RawPlanGeometry()
        geom.texts.append(TextEntity("Test", Point2D(0, 0)))

        d = geom.to_dict()
        assert "line_segments" in d
        assert "polylines" in d
        assert "arcs" in d
        assert "polygons" in d
        assert "texts" in d
        assert len(d["texts"]) == 1
