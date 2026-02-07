"""
Data models for HVAC elements (radiators, AC units, pipes, ducts).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum


class HeatingType(Enum):
    """Type of heating element."""
    RADIATOR = "radiator"
    FLOOR_HEATING = "floor_heating"
    FAN_COIL = "fan_coil"
    CONVECTOR = "convector"


class CoolingType(Enum):
    """Type of cooling element."""
    SPLIT_AC = "split_ac"
    FAN_COIL = "fan_coil"
    CASSETTE = "cassette"
    DUCT_AC = "duct_ac"


class PipeType(Enum):
    """Type of pipe."""
    HOT_WATER_SUPPLY = "hot_water_supply"
    HOT_WATER_RETURN = "hot_water_return"
    COLD_WATER_SUPPLY = "cold_water_supply"
    COLD_WATER_RETURN = "cold_water_return"
    REFRIGERANT = "refrigerant"
    CONDENSATE = "condensate"


@dataclass
class Radiator:
    """Represents a radiator heating element."""
    id: str
    room_id: str
    position: Tuple[float, float]  # (x, y) in room coordinates
    width_mm: int  # Radiator width in mm
    height_mm: int  # Radiator height in mm
    depth_mm: int  # Radiator depth in mm
    power_watts: float  # Thermal output in Watts
    n_elements: int = 0  # Number of elements (for sectional radiators)
    wall_side: str = ""  # Which wall it's mounted on
    
    def get_dimensions_m(self) -> Tuple[float, float, float]:
        """Return dimensions in meters."""
        return (self.width_mm / 1000, self.height_mm / 1000, self.depth_mm / 1000)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "radiator",
            "room_id": self.room_id,
            "position": self.position,
            "dimensions_mm": {
                "width": self.width_mm,
                "height": self.height_mm,
                "depth": self.depth_mm
            },
            "power_watts": self.power_watts,
            "n_elements": self.n_elements,
            "wall_side": self.wall_side
        }


@dataclass
class ACUnit:
    """Represents an air conditioning unit."""
    id: str
    room_id: str
    position: Tuple[float, float]
    cooling_type: CoolingType
    cooling_capacity_watts: float
    heating_capacity_watts: float = 0  # For heat pumps
    width_mm: int = 800
    height_mm: int = 290
    depth_mm: int = 200
    wall_side: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.cooling_type.value,
            "room_id": self.room_id,
            "position": self.position,
            "dimensions_mm": {
                "width": self.width_mm,
                "height": self.height_mm,
                "depth": self.depth_mm
            },
            "cooling_capacity_watts": self.cooling_capacity_watts,
            "heating_capacity_watts": self.heating_capacity_watts,
            "wall_side": self.wall_side
        }


@dataclass
class PipeSegment:
    """A segment of pipe from one point to another."""
    start: Tuple[float, float]
    end: Tuple[float, float]
    diameter_mm: int
    pipe_type: PipeType
    
    def length(self) -> float:
        """Calculate segment length in meters."""
        import math
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class Pipe:
    """Represents a pipe route from source to destination."""
    id: str
    pipe_type: PipeType
    segments: List[PipeSegment] = field(default_factory=list)
    source_id: str = ""  # e.g., "boiler_1"
    destination_id: str = ""  # e.g., "radiator_1"
    diameter_mm: int = 20
    
    def total_length(self) -> float:
        """Calculate total pipe length in meters."""
        return sum(seg.length() for seg in self.segments)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pipe_type": self.pipe_type.value,
            "source_id": self.source_id,
            "destination_id": self.destination_id,
            "diameter_mm": self.diameter_mm,
            "total_length_m": self.total_length(),
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "diameter_mm": seg.diameter_mm
                }
                for seg in self.segments
            ]
        }


@dataclass
class Duct:
    """Represents an air duct for ducted HVAC systems."""
    id: str
    width_mm: int
    height_mm: int
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    source_id: str = ""
    destination_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dimensions_mm": {
                "width": self.width_mm,
                "height": self.height_mm
            },
            "source_id": self.source_id,
            "destination_id": self.destination_id,
            "segments": self.segments
        }


@dataclass
class Boiler:
    """Represents a boiler/heat source."""
    id: str
    position: Tuple[float, float]
    room_id: str
    power_kw: float
    fuel_type: str = "gas"  # gas, electric, oil, pellet
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "boiler",
            "position": self.position,
            "room_id": self.room_id,
            "power_kw": self.power_kw,
            "fuel_type": self.fuel_type
        }


@dataclass
class HVACSystem:
    """Complete HVAC system for a building."""
    radiators: List[Radiator] = field(default_factory=list)
    ac_units: List[ACUnit] = field(default_factory=list)
    pipes: List[Pipe] = field(default_factory=list)
    ducts: List[Duct] = field(default_factory=list)
    boilers: List[Boiler] = field(default_factory=list)
    
    # System totals
    total_heating_power_kw: float = 0.0
    total_cooling_power_kw: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "radiators": [r.to_dict() for r in self.radiators],
            "ac_units": [ac.to_dict() for ac in self.ac_units],
            "pipes": [p.to_dict() for p in self.pipes],
            "ducts": [d.to_dict() for d in self.ducts],
            "boilers": [b.to_dict() for b in self.boilers],
            "totals": {
                "heating_power_kw": self.total_heating_power_kw,
                "cooling_power_kw": self.total_cooling_power_kw,
                "n_radiators": len(self.radiators),
                "n_ac_units": len(self.ac_units),
                "total_pipe_length_m": sum(p.total_length() for p in self.pipes)
            }
        }
