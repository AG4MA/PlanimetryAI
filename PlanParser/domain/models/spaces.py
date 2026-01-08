"""
Space Models
============
Rooms, corridors, and other spaces in the planimetry.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from PlanParser.domain.models.primitives import Point2D, Polygon
from PlanParser.domain.value_objects.measurements import Area


class RoomType(Enum):
    """Standard room type classifications."""
    # Living spaces
    LIVING_ROOM = "living_room"
    DINING_ROOM = "dining_room"
    BEDROOM = "bedroom"
    MASTER_BEDROOM = "master_bedroom"
    GUEST_ROOM = "guest_room"
    STUDY = "study"
    OFFICE = "office"
    
    # Utility spaces
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    TOILET = "toilet"          # WC only
    LAUNDRY = "laundry"
    STORAGE = "storage"
    CLOSET = "closet"
    PANTRY = "pantry"
    
    # Circulation
    HALLWAY = "hallway"
    CORRIDOR = "corridor"
    ENTRANCE = "entrance"
    FOYER = "foyer"
    STAIRWELL = "stairwell"
    
    # Outdoor/Semi-outdoor
    BALCONY = "balcony"
    TERRACE = "terrace"
    LOGGIA = "loggia"
    GARAGE = "garage"
    
    # Generic
    ROOM = "room"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_label(cls, label: str) -> "RoomType":
        """
        Map OCR-detected label to room type.
        Handles common Italian/English variations.
        """
        label = label.lower().strip()
        
        mappings = {
            # Italian
            "soggiorno": cls.LIVING_ROOM,
            "salotto": cls.LIVING_ROOM,
            "pranzo": cls.DINING_ROOM,
            "sala pranzo": cls.DINING_ROOM,
            "camera": cls.BEDROOM,
            "camera da letto": cls.BEDROOM,
            "camera matrimoniale": cls.MASTER_BEDROOM,
            "cameretta": cls.BEDROOM,
            "cucina": cls.KITCHEN,
            "bagno": cls.BATHROOM,
            "wc": cls.TOILET,
            "ripostiglio": cls.STORAGE,
            "sgabuzzino": cls.STORAGE,
            "ingresso": cls.ENTRANCE,
            "corridoio": cls.CORRIDOR,
            "disimpegno": cls.HALLWAY,
            "balcone": cls.BALCONY,
            "terrazzo": cls.TERRACE,
            "loggia": cls.LOGGIA,
            "studio": cls.STUDY,
            "ufficio": cls.OFFICE,
            "lavanderia": cls.LAUNDRY,
            "garage": cls.GARAGE,
            "box": cls.GARAGE,
            
            # English
            "living room": cls.LIVING_ROOM,
            "living": cls.LIVING_ROOM,
            "lounge": cls.LIVING_ROOM,
            "dining room": cls.DINING_ROOM,
            "dining": cls.DINING_ROOM,
            "bedroom": cls.BEDROOM,
            "bed": cls.BEDROOM,
            "master bedroom": cls.MASTER_BEDROOM,
            "master": cls.MASTER_BEDROOM,
            "kitchen": cls.KITCHEN,
            "bathroom": cls.BATHROOM,
            "bath": cls.BATHROOM,
            "toilet": cls.TOILET,
            "storage": cls.STORAGE,
            "closet": cls.CLOSET,
            "hall": cls.HALLWAY,
            "hallway": cls.HALLWAY,
            "entrance": cls.ENTRANCE,
            "foyer": cls.FOYER,
            "corridor": cls.CORRIDOR,
            "balcony": cls.BALCONY,
            "terrace": cls.TERRACE,
            "study": cls.STUDY,
            "office": cls.OFFICE,
            "laundry": cls.LAUNDRY,
            "garage": cls.GARAGE,
        }
        
        # Exact match
        if label in mappings:
            return mappings[label]
        
        # Partial match
        for key, room_type in mappings.items():
            if key in label or label in key:
                return room_type
        
        return cls.UNKNOWN


@dataclass
class Room:
    """
    A room in the planimetry.
    
    This is the core semantic unit of the digital twin.
    Contains geometry (polygon), classification, and relationships.
    """
    id: str
    label: str                              # Original detected label
    room_type: RoomType = RoomType.UNKNOWN
    
    # Geometry
    polygon: Polygon | None = None          # Room boundary
    centroid: Point2D | None = None         # Center point
    area_sqm: float | None = None           # Area in square meters
    
    # Bounding box (always available, even without polygon)
    bbox: tuple[int, int, int, int] | None = None  # (x, y, width, height) in pixels
    
    # Relationships (populated by topology analysis)
    wall_ids: list[str] = field(default_factory=list)
    door_ids: list[str] = field(default_factory=list)
    window_ids: list[str] = field(default_factory=list)
    adjacent_room_ids: list[str] = field(default_factory=list)
    
    # Floor reference
    floor_id: str | None = None
    
    # Detection metadata
    confidence: float = 0.0
    label_confidence: float = 0.0           # OCR confidence for label
    polygon_confidence: float = 0.0         # Geometry detection confidence
    source: str = "detected"
    
    def __post_init__(self):
        # Auto-classify if not set
        if self.room_type == RoomType.UNKNOWN and self.label:
            self.room_type = RoomType.from_label(self.label)
    
    @property
    def is_habitable(self) -> bool:
        """True if this is a habitable space (not circulation/storage)."""
        habitable = {
            RoomType.LIVING_ROOM, RoomType.DINING_ROOM, 
            RoomType.BEDROOM, RoomType.MASTER_BEDROOM, RoomType.GUEST_ROOM,
            RoomType.STUDY, RoomType.OFFICE, RoomType.KITCHEN,
        }
        return self.room_type in habitable
    
    @property
    def is_wet_room(self) -> bool:
        """True if this room has water fixtures."""
        return self.room_type in {
            RoomType.BATHROOM, RoomType.TOILET, 
            RoomType.KITCHEN, RoomType.LAUNDRY
        }
    
    @property
    def is_circulation(self) -> bool:
        """True if this is a circulation space."""
        return self.room_type in {
            RoomType.HALLWAY, RoomType.CORRIDOR, 
            RoomType.ENTRANCE, RoomType.FOYER, RoomType.STAIRWELL
        }
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "room",
            "label": self.label,
            "room_type": self.room_type.value,
            "area_sqm": self.area_sqm,
            "centroid": self.centroid.to_dict() if self.centroid else None,
            "polygon": self.polygon.to_dict() if self.polygon else None,
            "bbox": self.bbox,
            "wall_ids": self.wall_ids,
            "door_ids": self.door_ids,
            "window_ids": self.window_ids,
            "adjacent_room_ids": self.adjacent_room_ids,
            "floor_id": self.floor_id,
            "is_habitable": self.is_habitable,
            "is_wet_room": self.is_wet_room,
            "confidence": self.confidence,
        }


@dataclass
class Stairwell:
    """
    A stairwell connecting floors.
    """
    id: str
    position: Point2D
    
    # Which floors it connects
    connects_floor_ids: list[str] = field(default_factory=list)
    
    # Direction
    goes_up: bool = True
    goes_down: bool = True
    
    # Geometry
    polygon: Polygon | None = None
    
    confidence: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "stairwell",
            "position": self.position.to_dict(),
            "connects_floors": self.connects_floor_ids,
            "goes_up": self.goes_up,
            "goes_down": self.goes_down,
            "polygon": self.polygon.to_dict() if self.polygon else None,
            "confidence": self.confidence,
        }
