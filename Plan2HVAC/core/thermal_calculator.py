"""
Thermal Calculator Module

Calculates heating and cooling requirements for each room based on:
- Room volume (area × height)
- External wall exposure
- Window area
- Room usage type
- Climate zone
- Orientation (sun exposure)

Standard calculation based on Italian/European norms.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import math

from ..models.knowledge_model import Room, KnowledgeModel, WallType


class ClimateZone(Enum):
    """Italian climate zones (A-F, from warmest to coldest)."""
    A = "A"  # <600 degree days
    B = "B"  # 600-900 degree days
    C = "C"  # 900-1400 degree days
    D = "D"  # 1400-2100 degree days
    E = "E"  # 2100-3000 degree days
    F = "F"  # >3000 degree days


class RoomUsage(Enum):
    """Room usage type affects thermal calculations."""
    LIVING = "living"       # Soggiorno, sala
    BEDROOM = "bedroom"     # Camera, stanza
    BATHROOM = "bathroom"   # Bagno
    KITCHEN = "kitchen"     # Cucina
    HALLWAY = "hallway"     # Corridoio, ingresso
    STORAGE = "storage"     # Ripostiglio
    GARAGE = "garage"       # Garage, box
    OFFICE = "office"       # Studio, ufficio
    UNKNOWN = "unknown"


# Room label mappings (Italian)
ROOM_LABEL_TO_USAGE = {
    "soggiorno": RoomUsage.LIVING,
    "sala": RoomUsage.LIVING,
    "salotto": RoomUsage.LIVING,
    "living": RoomUsage.LIVING,
    "camera": RoomUsage.BEDROOM,
    "stanza": RoomUsage.BEDROOM,
    "letto": RoomUsage.BEDROOM,
    "bagno": RoomUsage.BATHROOM,
    "wc": RoomUsage.BATHROOM,
    "cucina": RoomUsage.KITCHEN,
    "angolo cottura": RoomUsage.KITCHEN,
    "corridoio": RoomUsage.HALLWAY,
    "ingresso": RoomUsage.HALLWAY,
    "disimpegno": RoomUsage.HALLWAY,
    "ripostiglio": RoomUsage.STORAGE,
    "cantina": RoomUsage.STORAGE,
    "garage": RoomUsage.GARAGE,
    "box": RoomUsage.GARAGE,
    "studio": RoomUsage.OFFICE,
    "ufficio": RoomUsage.OFFICE,
}

# Target temperatures by room type (°C)
TARGET_TEMPERATURES = {
    RoomUsage.LIVING: 20,
    RoomUsage.BEDROOM: 18,
    RoomUsage.BATHROOM: 22,
    RoomUsage.KITCHEN: 18,
    RoomUsage.HALLWAY: 18,
    RoomUsage.STORAGE: 14,
    RoomUsage.GARAGE: 10,
    RoomUsage.OFFICE: 20,
    RoomUsage.UNKNOWN: 20,
}

# Minimum external temperature by climate zone (°C)
MIN_EXTERNAL_TEMP = {
    ClimateZone.A: 5,
    ClimateZone.B: 0,
    ClimateZone.C: -5,
    ClimateZone.D: -10,
    ClimateZone.E: -15,
    ClimateZone.F: -20,
}

# W/m³ base factor for heating calculation
W_PER_M3_BASE = {
    ClimateZone.A: 25,
    ClimateZone.B: 30,
    ClimateZone.C: 35,
    ClimateZone.D: 40,
    ClimateZone.E: 50,
    ClimateZone.F: 60,
}


@dataclass
class ThermalRequirements:
    """Thermal requirements for a room."""
    room_id: str
    room_label: str
    
    # Basic properties
    area_m2: float
    volume_m3: float
    external_wall_length_m: float
    
    # Calculated requirements
    heating_watts: float
    cooling_watts: float
    target_temp_c: float
    
    # Sizing recommendations
    recommended_radiator_watts: float
    recommended_ac_watts: float
    
    # Room type
    room_usage: RoomUsage = RoomUsage.UNKNOWN


@dataclass
class ThermalCalculator:
    """
    Calculates heating and cooling requirements for rooms.
    
    Uses simplified UNI EN 12831 methodology for heating
    and basic load calculation for cooling.
    """
    climate_zone: ClimateZone = ClimateZone.E  # Default: Northern Italy
    
    # Building characteristics
    insulation_quality: float = 1.0  # 0.7 (excellent) to 1.5 (poor)
    window_ratio: float = 0.15  # Window area as ratio of external wall area
    ceiling_height_m: float = 2.7
    
    # Oversizing factors
    heating_safety_factor: float = 1.2  # 20% oversizing
    cooling_safety_factor: float = 1.15  # 15% oversizing
    
    def get_room_usage(self, label: str) -> RoomUsage:
        """Determine room usage from its label."""
        label_lower = label.lower()
        for keyword, usage in ROOM_LABEL_TO_USAGE.items():
            if keyword in label_lower:
                return usage
        return RoomUsage.UNKNOWN
    
    def calculate_heating_load(self, room: Room) -> float:
        """
        Calculate heating load in Watts for a room.
        
        Formula: Q = V × W/m³ × factors
        
        Where:
        - V = volume in m³
        - W/m³ = base watts per cubic meter for climate zone
        - factors = adjustments for insulation, exposure, etc.
        """
        # Get volume
        volume = room.volume_m3
        if volume <= 0:
            volume = room.area_m2 * self.ceiling_height_m
        
        # Base calculation
        base_w_per_m3 = W_PER_M3_BASE.get(self.climate_zone, 40)
        base_load = volume * base_w_per_m3
        
        # Adjustments
        # 1. Insulation quality
        base_load *= self.insulation_quality
        
        # 2. External wall exposure bonus
        ext_wall_length = room.get_external_wall_length()
        if ext_wall_length > 0:
            # Add 10W per linear meter of external wall
            base_load += ext_wall_length * 10
        
        # 3. Room type adjustment
        usage = self.get_room_usage(room.label)
        target_temp = TARGET_TEMPERATURES.get(usage, 20)
        min_ext_temp = MIN_EXTERNAL_TEMP.get(self.climate_zone, -10)
        
        # Temperature delta factor
        temp_factor = (target_temp - min_ext_temp) / 30  # Normalized to base 30°C delta
        base_load *= temp_factor
        
        # 4. Safety factor
        final_load = base_load * self.heating_safety_factor
        
        return round(final_load, 0)
    
    def calculate_cooling_load(self, room: Room) -> float:
        """
        Calculate cooling load in Watts for a room.
        
        Simplified calculation based on:
        - Room volume
        - External exposure (sun load)
        - Internal gains (people, equipment)
        """
        volume = room.volume_m3
        if volume <= 0:
            volume = room.area_m2 * self.ceiling_height_m
        
        # Base cooling: ~25-35 W/m³ for Italian summer
        base_load = volume * 30
        
        # Sun exposure bonus
        ext_wall_length = room.get_external_wall_length()
        if ext_wall_length > 0:
            # Assuming some windows on external walls
            window_area = ext_wall_length * self.ceiling_height_m * self.window_ratio
            # ~200-400 W/m² of window during peak sun
            sun_load = window_area * 250
            base_load += sun_load
        
        # Internal gains (people, equipment) - simplified
        # Assume 100W per person, 1 person per 10m²
        people = max(1, room.area_m2 / 10)
        internal_gains = people * 100
        base_load += internal_gains
        
        # Room type adjustment - bathrooms and kitchens need less cooling
        usage = self.get_room_usage(room.label)
        if usage == RoomUsage.BATHROOM:
            base_load *= 0.8
        elif usage == RoomUsage.STORAGE or usage == RoomUsage.GARAGE:
            base_load *= 0.5
        
        # Safety factor
        final_load = base_load * self.cooling_safety_factor
        
        return round(final_load, 0)
    
    def calculate_room_requirements(self, room: Room) -> ThermalRequirements:
        """Calculate complete thermal requirements for a room."""
        usage = self.get_room_usage(room.label)
        target_temp = TARGET_TEMPERATURES.get(usage, 20)
        
        heating_watts = self.calculate_heating_load(room)
        cooling_watts = self.calculate_cooling_load(room)
        
        # Volume calculation
        volume = room.volume_m3
        if volume <= 0:
            volume = room.area_m2 * self.ceiling_height_m
        
        return ThermalRequirements(
            room_id=room.id,
            room_label=room.label,
            area_m2=room.area_m2,
            volume_m3=volume,
            external_wall_length_m=room.get_external_wall_length(),
            heating_watts=heating_watts,
            cooling_watts=cooling_watts,
            target_temp_c=target_temp,
            recommended_radiator_watts=heating_watts,
            recommended_ac_watts=cooling_watts,
            room_usage=usage
        )
    
    def calculate_building_requirements(
        self, 
        knowledge_model: KnowledgeModel
    ) -> Dict[str, ThermalRequirements]:
        """
        Calculate thermal requirements for all rooms in the building.
        
        Returns a dictionary mapping room_id -> ThermalRequirements.
        """
        requirements = {}
        
        for floor in knowledge_model.floors:
            for room in floor.rooms:
                req = self.calculate_room_requirements(room)
                requirements[room.id] = req
        
        return requirements
    
    def get_total_heating_load(
        self, 
        requirements: Dict[str, ThermalRequirements]
    ) -> float:
        """Get total building heating load in kW."""
        total = sum(r.heating_watts for r in requirements.values())
        return round(total / 1000, 2)
    
    def get_total_cooling_load(
        self, 
        requirements: Dict[str, ThermalRequirements]
    ) -> float:
        """Get total building cooling load in kW."""
        total = sum(r.cooling_watts for r in requirements.values())
        return round(total / 1000, 2)
    
    def recommend_boiler_size(
        self, 
        requirements: Dict[str, ThermalRequirements]
    ) -> float:
        """Recommend boiler size in kW with headroom."""
        total_heating = self.get_total_heating_load(requirements)
        
        # Add domestic hot water allowance (~10-20%)
        dhw_allowance = total_heating * 0.15
        
        # Round up to standard sizes
        needed_kw = total_heating + dhw_allowance
        
        # Standard boiler sizes
        standard_sizes = [12, 18, 24, 28, 32, 35, 40, 50, 60, 80, 100]
        for size in standard_sizes:
            if size >= needed_kw:
                return size
        
        return math.ceil(needed_kw / 10) * 10  # Round to nearest 10
