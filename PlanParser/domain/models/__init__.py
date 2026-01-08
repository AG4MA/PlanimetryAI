"""
Domain Models
=============
Core entities of the planimetry digital twin.

Hierarchy:
- DigitalTwin (top-level output)
  └── Building
      └── Floor
          ├── Room (spaces)
          ├── Wall, Door, Window (elements)
          └── TopologyGraph (relationships)

Primitives:
- Point2D, LineSegment, Polygon, etc. (geometric primitives)
"""

# Geometric primitives
from PlanParser.domain.models.primitives import (
    Point2D,
    LineSegment,
    Polyline,
    Arc,
    Polygon,
    TextEntity,
    RawPlanGeometry,
)

# Architectural elements
from PlanParser.domain.models.elements import (
    WallType,
    DoorType,
    WindowType,
    Wall,
    Door,
    Window,
    Opening,
)

# Spaces
from PlanParser.domain.models.spaces import (
    RoomType,
    Room,
    Stairwell,
)

# Building structure
from PlanParser.domain.models.building import (
    Floor,
    Building,
)

# Top-level output
from PlanParser.domain.models.digital_twin import (
    ProcessingMetadata,
    DigitalTwin,
)


__all__ = [
    # Primitives
    "Point2D",
    "LineSegment", 
    "Polyline",
    "Arc",
    "Polygon",
    "TextEntity",
    "RawPlanGeometry",
    
    # Elements
    "WallType",
    "DoorType", 
    "WindowType",
    "Wall",
    "Door",
    "Window",
    "Opening",
    
    # Spaces
    "RoomType",
    "Room",
    "Stairwell",
    
    # Building
    "Floor",
    "Building",
    
    # Digital Twin
    "ProcessingMetadata",
    "DigitalTwin",
]
