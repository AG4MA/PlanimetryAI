"""
Building Models
===============
Top-level entities: Building and Floor.
"""

from dataclasses import dataclass, field
from typing import Any

from PlanParser.domain.models.primitives import Point2D, Polygon
from PlanParser.domain.models.spaces import Room, Stairwell
from PlanParser.domain.models.elements import Wall, Door, Window, Opening
from PlanParser.domain.value_objects.measurements import Scale
from PlanParser.domain.value_objects.orientation import Compass
from PlanParser.domain.value_objects.topology import TopologyGraph


@dataclass
class Floor:
    """
    A single floor in the building.
    
    Contains all spaces and elements for one level.
    """
    id: str
    label: str                              # "Piano Terra", "Primo Piano", etc.
    floor_number: int = 0                   # 0 = ground, 1 = first, -1 = basement
    
    # Contained entities
    rooms: list[Room] = field(default_factory=list)
    walls: list[Wall] = field(default_factory=list)
    doors: list[Door] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    stairwells: list[Stairwell] = field(default_factory=list)
    
    # Floor boundary (if detected)
    boundary_polygon: Polygon | None = None
    
    # Topology (computed)
    topology: TopologyGraph = field(default_factory=TopologyGraph)
    
    # Metrics
    total_area_sqm: float | None = None
    habitable_area_sqm: float | None = None
    
    # Source image reference
    image_path: str | None = None
    bbox_in_source: tuple[int, int, int, int] | None = None  # Position in original image
    
    # Detection metadata
    confidence: float = 0.0
    
    def get_room_by_id(self, room_id: str) -> Room | None:
        """Find room by ID."""
        for room in self.rooms:
            if room.id == room_id:
                return room
        return None
    
    def get_rooms_by_type(self, room_type) -> list[Room]:
        """Get all rooms of a specific type."""
        return [r for r in self.rooms if r.room_type == room_type]
    
    def get_wall_by_id(self, wall_id: str) -> Wall | None:
        """Find wall by ID."""
        for wall in self.walls:
            if wall.id == wall_id:
                return wall
        return None
    
    def get_adjacent_rooms(self, room_id: str) -> list[Room]:
        """Get rooms adjacent to given room."""
        adjacent_ids = self.topology.get_adjacent_rooms(room_id)
        return [r for r in self.rooms if r.id in adjacent_ids]
    
    def compute_areas(self):
        """Compute floor area totals from rooms."""
        total = 0.0
        habitable = 0.0
        for room in self.rooms:
            if room.area_sqm:
                total += room.area_sqm
                if room.is_habitable:
                    habitable += room.area_sqm
        self.total_area_sqm = total if total > 0 else None
        self.habitable_area_sqm = habitable if habitable > 0 else None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "floor",
            "label": self.label,
            "floor_number": self.floor_number,
            "total_area_sqm": self.total_area_sqm,
            "habitable_area_sqm": self.habitable_area_sqm,
            "rooms": [r.to_dict() for r in self.rooms],
            "walls": [w.to_dict() for w in self.walls],
            "doors": [d.to_dict() for d in self.doors],
            "windows": [w.to_dict() for w in self.windows],
            "openings": [o.to_dict() for o in self.openings],
            "stairwells": [s.to_dict() for s in self.stairwells],
            "boundary": self.boundary_polygon.to_dict() if self.boundary_polygon else None,
            "confidence": self.confidence,
        }


@dataclass
class Building:
    """
    Top-level building entity.
    
    Contains all floors and building-wide metadata.
    """
    id: str
    name: str | None = None
    
    # Floors
    floors: list[Floor] = field(default_factory=list)
    
    # Building-wide properties
    scale: Scale | None = None
    compass: Compass | None = None
    
    # Totals
    total_floors: int = 0
    total_rooms: int = 0
    total_area_sqm: float | None = None
    
    # Address/location (if available)
    address: str | None = None
    
    # Source metadata
    source_file: str | None = None
    source_type: str | None = None  # "pdf", "dwg", "image"
    
    def get_floor_by_number(self, floor_number: int) -> Floor | None:
        """Find floor by number."""
        for floor in self.floors:
            if floor.floor_number == floor_number:
                return floor
        return None
    
    def get_floor_by_id(self, floor_id: str) -> Floor | None:
        """Find floor by ID."""
        for floor in self.floors:
            if floor.id == floor_id:
                return floor
        return None
    
    def get_all_rooms(self) -> list[Room]:
        """Get all rooms across all floors."""
        rooms = []
        for floor in self.floors:
            rooms.extend(floor.rooms)
        return rooms
    
    def compute_totals(self):
        """Compute building-wide totals."""
        self.total_floors = len(self.floors)
        self.total_rooms = sum(len(f.rooms) for f in self.floors)
        
        total_area = 0.0
        for floor in self.floors:
            floor.compute_areas()
            if floor.total_area_sqm:
                total_area += floor.total_area_sqm
        self.total_area_sqm = total_area if total_area > 0 else None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "building",
            "name": self.name,
            "address": self.address,
            "total_floors": self.total_floors,
            "total_rooms": self.total_rooms,
            "total_area_sqm": self.total_area_sqm,
            "scale": self.scale.label if self.scale else None,
            "compass": {
                "north_angle_degrees": self.compass.north_angle_degrees,
                "detected": self.compass.detected
            } if self.compass else None,
            "floors": [f.to_dict() for f in self.floors],
            "source_file": self.source_file,
            "source_type": self.source_type,
        }
