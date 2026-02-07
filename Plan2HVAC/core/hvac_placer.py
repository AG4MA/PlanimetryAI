"""
HVAC Element Placer Module

Determines optimal placement of HVAC elements (radiators, AC units) within rooms.

Placement rules:
- Radiators: preferably under windows, on external walls
- AC units: high on internal walls, avoiding windows and doors
- Minimum clearance requirements
- Avoiding obstructions
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math

from ..models.knowledge_model import Room, KnowledgeModel, WallType, Wall
from ..models.hvac_elements import Radiator, ACUnit, CoolingType
from .thermal_calculator import ThermalRequirements, RoomUsage


# Standard radiator dimensions (height x depth in mm)
RADIATOR_PROFILES = {
    "low": {"height": 300, "depth": 100},      # Under large windows
    "standard": {"height": 600, "depth": 100}, # Most common
    "tall": {"height": 900, "depth": 100},     # Limited wall space
}

# Watts per element for standard radiators (ΔT = 50°C)
WATTS_PER_ELEMENT = {
    "low": 80,
    "standard": 120,
    "tall": 160,
}

# Element width in mm
ELEMENT_WIDTH_MM = 80


@dataclass
class PlacementConstraints:
    """Constraints for placing HVAC elements."""
    min_floor_clearance_mm: int = 100  # Distance from floor
    min_wall_clearance_mm: int = 50    # Distance from side walls
    radiator_under_window_offset_mm: int = 100  # Below window sill
    radiator_max_width_mm: int = 2000  # Maximum radiator width
    ac_min_height_mm: int = 2000       # Minimum AC height from floor
    ac_min_ceiling_clearance_mm: int = 150  # Distance from ceiling


class HVACPlacer:
    """
    Determines optimal placement of radiators and AC units in rooms.
    """
    
    def __init__(self, constraints: Optional[PlacementConstraints] = None):
        self.constraints = constraints or PlacementConstraints()
        self._radiator_counter = 0
        self._ac_counter = 0
    
    def _next_radiator_id(self) -> str:
        self._radiator_counter += 1
        return f"RAD_{self._radiator_counter:03d}"
    
    def _next_ac_id(self) -> str:
        self._ac_counter += 1
        return f"AC_{self._ac_counter:03d}"
    
    def select_radiator_profile(
        self, 
        requirements: ThermalRequirements,
        available_wall_length_m: float
    ) -> Tuple[str, int]:
        """
        Select appropriate radiator profile and calculate number of elements.
        
        Returns: (profile_name, n_elements)
        """
        watts_needed = requirements.recommended_radiator_watts
        
        # Try profiles from most preferred to least
        for profile in ["standard", "low", "tall"]:
            watts_per_elem = WATTS_PER_ELEMENT[profile]
            n_elements = math.ceil(watts_needed / watts_per_elem)
            
            # Check if it fits
            width_mm = n_elements * ELEMENT_WIDTH_MM
            max_width = min(
                self.constraints.radiator_max_width_mm,
                (available_wall_length_m * 1000) - (2 * self.constraints.min_wall_clearance_mm)
            )
            
            if width_mm <= max_width:
                return profile, n_elements
        
        # Fallback: split into multiple radiators (handled by caller)
        profile = "standard"
        n_elements = math.ceil(watts_needed / WATTS_PER_ELEMENT[profile])
        return profile, n_elements
    
    def find_best_wall_for_radiator(
        self, 
        room: Room
    ) -> Optional[Wall]:
        """
        Find the best wall for placing a radiator.
        
        Priority:
        1. External walls (especially those with windows)
        2. Longest available wall
        """
        external_walls = [w for w in room.walls if w.wall_type == WallType.EXTERNAL]
        
        if external_walls:
            # Return longest external wall
            return max(external_walls, key=lambda w: w.length_m)
        
        # Fallback to any wall
        if room.walls:
            return max(room.walls, key=lambda w: w.length_m)
        
        return None
    
    def calculate_radiator_position(
        self,
        room: Room,
        wall: Wall,
        radiator_width_mm: int
    ) -> Tuple[float, float]:
        """
        Calculate the position for a radiator on a given wall.
        
        Returns position in room coordinates (center point).
        """
        # For simplicity, center on wall
        if wall.start_point and wall.end_point:
            cx = (wall.start_point[0] + wall.end_point[0]) / 2
            cy = (wall.start_point[1] + wall.end_point[1]) / 2
            return (cx, cy)
        
        # Fallback: use room centroid with offset
        centroid = room.get_centroid()
        return centroid
    
    def place_radiator(
        self,
        room: Room,
        requirements: ThermalRequirements
    ) -> List[Radiator]:
        """
        Place radiator(s) in a room to meet heating requirements.
        
        May return multiple radiators if one isn't sufficient.
        """
        radiators = []
        
        # Find best wall
        wall = self.find_best_wall_for_radiator(room)
        available_length = wall.length_m if wall else 3.0  # Default
        
        # Select profile and size
        profile, n_elements = self.select_radiator_profile(
            requirements, available_length
        )
        
        profile_dims = RADIATOR_PROFILES[profile]
        watts_per_elem = WATTS_PER_ELEMENT[profile]
        
        # Check if we need to split into multiple radiators
        max_elements_per_radiator = int(
            (self.constraints.radiator_max_width_mm) / ELEMENT_WIDTH_MM
        )
        
        remaining_elements = n_elements
        radiator_index = 0
        
        while remaining_elements > 0:
            n_elem = min(remaining_elements, max_elements_per_radiator)
            width_mm = n_elem * ELEMENT_WIDTH_MM
            power = n_elem * watts_per_elem
            
            # Calculate position (offset for multiple radiators)
            position = self.calculate_radiator_position(room, wall, width_mm)
            if radiator_index > 0:
                # Offset by previous radiator width
                position = (position[0] + radiator_index * 0.5, position[1])
            
            radiator = Radiator(
                id=self._next_radiator_id(),
                room_id=room.id,
                position=position,
                width_mm=width_mm,
                height_mm=profile_dims["height"],
                depth_mm=profile_dims["depth"],
                power_watts=power,
                n_elements=n_elem,
                wall_side=wall.side if wall else "unknown"
            )
            radiators.append(radiator)
            
            remaining_elements -= n_elem
            radiator_index += 1
        
        return radiators
    
    def place_ac_unit(
        self,
        room: Room,
        requirements: ThermalRequirements
    ) -> Optional[ACUnit]:
        """
        Place an AC unit in a room.
        
        Prefers placement on internal walls, high up.
        """
        # Skip rooms that typically don't need AC
        if requirements.room_usage in [RoomUsage.STORAGE, RoomUsage.GARAGE, RoomUsage.HALLWAY]:
            return None
        
        # Find internal wall (opposite of external)
        internal_walls = [w for w in room.walls if w.wall_type == WallType.INTERNAL]
        
        wall = None
        if internal_walls:
            wall = max(internal_walls, key=lambda w: w.length_m)
        elif room.walls:
            wall = max(room.walls, key=lambda w: w.length_m)
        
        # Calculate position (high on wall, centered)
        centroid = room.get_centroid()
        position = (centroid[0], centroid[1])
        
        if wall and wall.start_point and wall.end_point:
            cx = (wall.start_point[0] + wall.end_point[0]) / 2
            cy = (wall.start_point[1] + wall.end_point[1]) / 2
            position = (cx, cy)
        
        # Standard residential split unit dimensions
        return ACUnit(
            id=self._next_ac_id(),
            room_id=room.id,
            position=position,
            cooling_type=CoolingType.SPLIT_AC,
            cooling_capacity_watts=requirements.recommended_ac_watts,
            heating_capacity_watts=requirements.recommended_ac_watts * 1.1,  # Heat pump bonus
            width_mm=800,
            height_mm=290,
            depth_mm=200,
            wall_side=wall.side if wall else "unknown"
        )
    
    def place_all_hvac(
        self,
        knowledge_model: KnowledgeModel,
        requirements: Dict[str, ThermalRequirements],
        include_heating: bool = True,
        include_cooling: bool = True
    ) -> Tuple[List[Radiator], List[ACUnit]]:
        """
        Place all HVAC elements for a building.
        
        Returns (radiators, ac_units) tuples.
        """
        all_radiators = []
        all_ac_units = []
        
        for floor in knowledge_model.floors:
            for room in floor.rooms:
                req = requirements.get(room.id)
                if not req:
                    continue
                
                if include_heating:
                    radiators = self.place_radiator(room, req)
                    all_radiators.extend(radiators)
                
                if include_cooling:
                    ac_unit = self.place_ac_unit(room, req)
                    if ac_unit:
                        all_ac_units.append(ac_unit)
        
        return all_radiators, all_ac_units
