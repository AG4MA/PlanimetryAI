"""
Architectural Elements Models
=============================
Walls, doors, windows, and other building elements.
These are the semantic entities detected in the planimetry.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from PlanParser.domain.models.primitives import Point2D, LineSegment, Polygon


class WallType(Enum):
    """Classification of wall types."""
    EXTERIOR = "exterior"       # Building boundary
    INTERIOR = "interior"       # Room partition
    LOAD_BEARING = "load_bearing"
    PARTITION = "partition"     # Non-structural
    UNKNOWN = "unknown"


class DoorType(Enum):
    """Classification of door types."""
    HINGED = "hinged"           # Standard door
    SLIDING = "sliding"
    FOLDING = "folding"
    POCKET = "pocket"           # Slides into wall
    FRENCH = "french"           # Double doors
    UNKNOWN = "unknown"


class WindowType(Enum):
    """Classification of window types."""
    FIXED = "fixed"
    CASEMENT = "casement"       # Side-hinged
    SLIDING = "sliding"
    DOUBLE_HUNG = "double_hung"
    FRENCH = "french"           # Door-style window
    SKYLIGHT = "skylight"
    UNKNOWN = "unknown"


@dataclass
class Wall:
    """
    A wall segment in the planimetry.
    
    Represents a detected wall with its geometry and properties.
    Walls bound rooms and contain openings (doors, windows).
    """
    id: str
    geometry: LineSegment
    wall_type: WallType = WallType.UNKNOWN
    thickness_meters: float | None = None
    
    # Rooms on each side (None if exterior)
    room_a_id: str | None = None
    room_b_id: str | None = None
    
    # Openings in this wall
    opening_ids: list[str] = field(default_factory=list)
    
    # Detection metadata
    confidence: float = 0.0
    source: str = "detected"  # "detected", "inferred", "manual"
    
    @property
    def length_pixels(self) -> float:
        """Wall length in pixels."""
        return self.geometry.start.distance_to(self.geometry.end)
    
    @property
    def is_exterior(self) -> bool:
        """True if this is an exterior wall."""
        return self.wall_type == WallType.EXTERIOR or \
               (self.room_a_id is None or self.room_b_id is None)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "wall",
            "wall_type": self.wall_type.value,
            "geometry": self.geometry.to_dict(),
            "thickness_m": self.thickness_meters,
            "room_a_id": self.room_a_id,
            "room_b_id": self.room_b_id,
            "opening_ids": self.opening_ids,
            "confidence": self.confidence,
        }


@dataclass
class Door:
    """
    A door in the planimetry.
    
    Connects two rooms or a room to exterior.
    """
    id: str
    position: Point2D          # Center position
    width_meters: float | None = None
    door_type: DoorType = DoorType.UNKNOWN
    
    # What it connects
    wall_id: str | None = None
    room_a_id: str | None = None  # None = exterior
    room_b_id: str | None = None  # None = exterior
    
    # Swing direction (for hinged doors)
    swing_angle_degrees: float | None = None  # Opening direction
    
    # Detection metadata
    confidence: float = 0.0
    source: str = "detected"
    
    @property
    def is_exterior_door(self) -> bool:
        """True if this door leads outside."""
        return self.room_a_id is None or self.room_b_id is None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "door",
            "door_type": self.door_type.value,
            "position": self.position.to_dict(),
            "width_m": self.width_meters,
            "wall_id": self.wall_id,
            "room_a_id": self.room_a_id,
            "room_b_id": self.room_b_id,
            "swing_angle_deg": self.swing_angle_degrees,
            "is_exterior": self.is_exterior_door,
            "confidence": self.confidence,
        }


@dataclass
class Window:
    """
    A window in the planimetry.
    """
    id: str
    position: Point2D
    width_meters: float | None = None
    height_meters: float | None = None  # Sill to top
    window_type: WindowType = WindowType.UNKNOWN
    
    # Location
    wall_id: str | None = None
    room_id: str | None = None
    
    # Detection metadata
    confidence: float = 0.0
    source: str = "detected"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "window",
            "window_type": self.window_type.value,
            "position": self.position.to_dict(),
            "width_m": self.width_meters,
            "height_m": self.height_meters,
            "wall_id": self.wall_id,
            "room_id": self.room_id,
            "confidence": self.confidence,
        }


@dataclass  
class Opening:
    """
    Generic opening (passage without door).
    Used for archways, open-plan connections, etc.
    """
    id: str
    position: Point2D
    width_meters: float | None = None
    
    wall_id: str | None = None
    room_a_id: str | None = None
    room_b_id: str | None = None
    
    confidence: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "opening",
            "position": self.position.to_dict(),
            "width_m": self.width_meters,
            "wall_id": self.wall_id,
            "room_a_id": self.room_a_id,
            "room_b_id": self.room_b_id,
            "confidence": self.confidence,
        }
