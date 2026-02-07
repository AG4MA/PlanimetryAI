"""
Data models for consuming PlanParser's Knowledge Model output.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum


class WallType(Enum):
    """Type of wall for thermal calculations."""
    EXTERNAL = "external"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ConnectionType(Enum):
    """Type of connection between rooms."""
    DOOR = "door"
    PASSAGE = "passage"
    WINDOW = "window"


@dataclass
class Wall:
    """Represents a wall segment of a room."""
    side: str  # "north", "south", "east", "west" or angle
    wall_type: WallType
    length_m: float
    start_point: Tuple[float, float] = (0, 0)
    end_point: Tuple[float, float] = (0, 0)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Wall":
        return cls(
            side=data.get("side", "unknown"),
            wall_type=WallType(data.get("type", "unknown")),
            length_m=data.get("length_m", 0.0),
            start_point=tuple(data.get("start_point", (0, 0))),
            end_point=tuple(data.get("end_point", (0, 0)))
        )


@dataclass
class Connection:
    """Represents a connection between rooms (door, passage, etc.)."""
    to_room_id: str
    connection_type: ConnectionType
    position: Optional[Tuple[float, float]] = None
    width_m: float = 0.8  # Default door width
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Connection":
        return cls(
            to_room_id=data.get("to", ""),
            connection_type=ConnectionType(data.get("type", "door")),
            position=tuple(data["position"]) if data.get("position") else None,
            width_m=data.get("width_m", 0.8)
        )


@dataclass
class Room:
    """Represents a room with its geometric and semantic properties."""
    id: str
    label: str
    polygon: List[Tuple[float, float]]  # List of (x, y) vertices
    area_m2: float = 0.0
    height_m: float = 2.7  # Default ceiling height
    connections: List[Connection] = field(default_factory=list)
    walls: List[Wall] = field(default_factory=list)
    
    # Computed properties
    volume_m3: float = 0.0
    perimeter_m: float = 0.0
    
    def __post_init__(self):
        if self.area_m2 > 0 and self.height_m > 0:
            self.volume_m3 = self.area_m2 * self.height_m
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Room":
        room = cls(
            id=str(data.get("id", "")),
            label=data.get("label", "Unknown"),
            polygon=[(p[0], p[1]) for p in data.get("polygon", [])],
            area_m2=data.get("area_m2", 0.0),
            height_m=data.get("height_m", 2.7),
            connections=[Connection.from_dict(c) for c in data.get("connections", [])],
            walls=[Wall.from_dict(w) for w in data.get("walls", [])]
        )
        return room
    
    def get_external_wall_length(self) -> float:
        """Get total length of external walls."""
        return sum(w.length_m for w in self.walls if w.wall_type == WallType.EXTERNAL)
    
    def get_centroid(self) -> Tuple[float, float]:
        """Calculate the centroid of the room polygon."""
        if not self.polygon:
            return (0, 0)
        x = sum(p[0] for p in self.polygon) / len(self.polygon)
        y = sum(p[1] for p in self.polygon) / len(self.polygon)
        return (x, y)


@dataclass
class Floor:
    """Represents a floor in the building."""
    id: str
    label: str
    bounds: Dict[str, float]  # x, y, width, height
    rooms: List[Room] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Floor":
        return cls(
            id=data.get("id", ""),
            label=data.get("label", "Unknown Floor"),
            bounds=data.get("bounds", {"x": 0, "y": 0, "width": 0, "height": 0}),
            rooms=[Room.from_dict(r) for r in data.get("rooms", [])]
        )
    
    def get_total_area(self) -> float:
        """Get total floor area from all rooms."""
        return sum(room.area_m2 for room in self.rooms)


@dataclass
class KnowledgeModel:
    """
    The structured output from PlanParser that Plan2HVAC consumes.
    Contains all information about the building layout needed for HVAC planning.
    """
    source_file: str
    scale: str  # e.g., "1:100"
    scale_factor: Optional[float]  # pixels to meters conversion
    orientation_north: float  # degrees from top
    floors: List[Floor] = field(default_factory=list)
    topology: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeModel":
        source = data.get("source", {})
        meta = data.get("meta", {})
        
        return cls(
            source_file=source.get("file", meta.get("source_file", "")),
            scale=source.get("scale", meta.get("scale", "1:100")),
            scale_factor=meta.get("scale_factor"),
            orientation_north=source.get("orientation", {}).get("north", 0),
            floors=[Floor.from_dict(f) for f in data.get("floors", [])],
            topology=data.get("topology", {})
        )
    
    @classmethod
    def from_json_file(cls, filepath: str) -> "KnowledgeModel":
        """Load knowledge model from a JSON file."""
        import json
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def get_all_rooms(self) -> List[Room]:
        """Get all rooms across all floors."""
        rooms = []
        for floor in self.floors:
            rooms.extend(floor.rooms)
        return rooms
