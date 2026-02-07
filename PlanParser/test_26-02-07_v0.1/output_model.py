"""
Knowledge Model output format (skeleton).

Defines the structured data that PlanParser produces.
Downstream consumers (Plan2HVAC, PlanNL) read this format.
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any


@dataclass
class Connection:
    """A connection between two rooms (door, passage, window)."""
    to_room_id: str
    connection_type: str = "door"  # "door", "passage", "window"
    position: Optional[Tuple[float, float]] = None
    width_m: Optional[float] = None

    def to_dict(self) -> dict:
        d = {
            "to_room_id": self.to_room_id,
            "connection_type": self.connection_type,
        }
        if self.position is not None:
            d["position"] = list(self.position)
        if self.width_m is not None:
            d["width_m"] = self.width_m
        return d


@dataclass
class Wall:
    """A wall segment of a room."""
    wall_type: str = "unknown"  # "external", "internal", "unknown"
    start_point: Tuple[float, float] = (0.0, 0.0)
    end_point: Tuple[float, float] = (0.0, 0.0)
    length_px: float = 0.0
    length_m: Optional[float] = None

    def to_dict(self) -> dict:
        d = {
            "wall_type": self.wall_type,
            "start_point": list(self.start_point),
            "end_point": list(self.end_point),
            "length_px": self.length_px,
        }
        if self.length_m is not None:
            d["length_m"] = self.length_m
        return d


@dataclass
class Room:
    """A room with geometric and semantic properties."""
    id: str = ""
    label: Optional[str] = None
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    area_px: float = 0.0
    area_m2: Optional[float] = None
    walls: List[Wall] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "label": self.label,
            "polygon": [list(p) for p in self.polygon],
            "area_px": self.area_px,
        }
        if self.area_m2 is not None:
            d["area_m2"] = self.area_m2
        if self.walls:
            d["walls"] = [w.to_dict() for w in self.walls]
        if self.connections:
            d["connections"] = [c.to_dict() for c in self.connections]
        return d


@dataclass
class Floor:
    """A floor in the building."""
    id: str = ""
    label: str = ""
    rooms: List[Room] = field(default_factory=list)
    topology: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "rooms": [r.to_dict() for r in self.rooms],
            "topology": self.topology,
        }


@dataclass
class KnowledgeModel:
    """The structured output of PlanParser."""
    source_file: str = ""
    scale: Optional[str] = None
    scale_factor: Optional[float] = None
    orientation_north: Optional[float] = None
    floors: List[Floor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "meta": {
                "source_file": self.source_file,
                "scale": self.scale,
                "scale_factor": self.scale_factor,
                "orientation_north": self.orientation_north,
            },
            "floors": [f.to_dict() for f in self.floors],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
