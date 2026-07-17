"""Canonical PlanParser output model shared with Plan2HVAC."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
PARSER_VERSION = "0.1.0"


@dataclass
class Connection:
    """A detected connection between two rooms."""

    to_room_id: str = ""
    connection_type: str = "passage"
    position: Optional[Tuple[float, float]] = None
    width_m: Optional[float] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "to_room_id": self.to_room_id,
            "connection_type": self.connection_type,
            "position_px": list(self.position) if self.position is not None else None,
            "width_m": self.width_m,
            "confidence": self.confidence,
        }


@dataclass
class Wall:
    """A wall segment expressed in the declared pixel coordinate system."""

    id: str = ""
    wall_type: str = "unknown"
    start_point: Tuple[float, float] = (0.0, 0.0)
    end_point: Tuple[float, float] = (0.0, 0.0)
    length_px: float = 0.0
    length_m: Optional[float] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "wall_type": self.wall_type,
            "start_px": list(self.start_point),
            "end_px": list(self.end_point),
            "length_px": self.length_px,
            "length_m": self.length_m,
            "confidence": self.confidence,
        }


@dataclass
class Opening:
    """A door, window or passage assigned to a wall when known."""

    id: str = ""
    opening_type: str = "unknown"
    start_point: Tuple[float, float] = (0.0, 0.0)
    end_point: Tuple[float, float] = (0.0, 0.0)
    width_m: Optional[float] = None
    wall_id: Optional[str] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "opening_type": self.opening_type,
            "start_px": list(self.start_point),
            "end_px": list(self.end_point),
            "width_m": self.width_m,
            "wall_id": self.wall_id,
            "confidence": self.confidence,
        }


@dataclass
class Room:
    """A room with explicit geometry, semantics and confidence."""

    id: str = ""
    label: Optional[str] = None
    confidence: float = 0.0
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    area_px: float = 0.0
    area_m2: Optional[float] = None
    height_m: Optional[float] = None
    walls: List[Wall] = field(default_factory=list)
    openings: List[Opening] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "confidence": self.confidence,
            "polygon_px": [list(point) for point in self.polygon],
            "area_px2": self.area_px,
            "area_m2": self.area_m2,
            "height_m": self.height_m,
            "walls": [wall.to_dict() for wall in self.walls],
            "openings": [opening.to_dict() for opening in self.openings],
            "connections": [connection.to_dict() for connection in self.connections],
        }


@dataclass
class Floor:
    """A floor and its rooms in source-image coordinates."""

    id: str = ""
    label: str = ""
    confidence: float = 0.0
    source_rect: Optional[Tuple[int, int, int, int]] = None
    rooms: List[Room] = field(default_factory=list)
    topology: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "confidence": self.confidence,
            "source_rect_px": list(self.source_rect) if self.source_rect else None,
            "rooms": [room.to_dict() for room in self.rooms],
            "topology": self.topology,
        }


@dataclass
class KnowledgeModel:
    """Versioned machine-readable result produced by PlanParser."""

    source_file: str = ""
    scale: Optional[str] = None
    scale_factor: Optional[float] = None
    orientation_north: Optional[float] = None
    floors: List[Floor] = field(default_factory=list)
    document_status: str = "draft"
    parser_version: str = PARSER_VERSION
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    warnings: List[str] = field(default_factory=list)

    @property
    def source_type(self) -> str:
        return "pdf" if Path(self.source_file).suffix.lower() == ".pdf" else "image"

    @property
    def overall_confidence(self) -> float:
        if not self.floors:
            return 0.0
        return sum(floor.confidence for floor in self.floors) / len(self.floors)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "document_status": self.document_status,
            "meta": {
                "source_file": self.source_file,
                "source_type": self.source_type,
                "parser_version": self.parser_version,
                "created_at": self.created_at,
                "coordinate_system": {
                    "unit": "pixel",
                    "origin": "top_left",
                    "x_axis": "right",
                    "y_axis": "down",
                },
                "scale": self.scale,
                "scale_factor_m_per_px": self.scale_factor,
                "orientation_north_deg": self.orientation_north,
                "overall_confidence": self.overall_confidence,
                "warnings": list(self.warnings),
            },
            "floors": [floor.to_dict() for floor in self.floors],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
