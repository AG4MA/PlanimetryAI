"""
Pipe Router Module

Routes pipes from the heat source (boiler) to all heating elements (radiators).

Supports different piping layouts:
- Two-pipe system: separate supply and return
- One-pipe system: series connection
- Radial/manifold system: star topology from manifold

Uses simplified pathfinding to route pipes through the building.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum
import math

from ..models.knowledge_model import KnowledgeModel, Room
from ..models.hvac_elements import (
    Pipe, PipeSegment, PipeType, Radiator, Boiler, HVACSystem
)


class PipingLayout(Enum):
    """Type of piping system layout."""
    TWO_PIPE = "two_pipe"      # Parallel connection, most common
    ONE_PIPE = "one_pipe"      # Series connection, simpler but less efficient
    RADIAL = "radial"          # Star from manifold, best comfort


@dataclass
class PipeRouterConfig:
    """Configuration for pipe routing."""
    layout: PipingLayout = PipingLayout.TWO_PIPE
    main_pipe_diameter_mm: int = 28      # Main pipe diameter
    branch_pipe_diameter_mm: int = 20    # Branch to radiators
    min_wall_distance_mm: int = 50       # Minimum distance from walls
    route_along_walls: bool = True       # Prefer wall-adjacent routes
    avoid_room_centers: bool = True      # Avoid routing through room centers


class PipeRouter:
    """
    Routes pipes from boiler to radiators.
    
    Uses a simplified routing algorithm that:
    1. Creates a main pipe run from boiler along corridors
    2. Branches off to each room
    3. Connects to radiators within rooms
    """
    
    def __init__(self, config: Optional[PipeRouterConfig] = None):
        self.config = config or PipeRouterConfig()
        self._pipe_counter = 0
    
    def _next_pipe_id(self) -> str:
        self._pipe_counter += 1
        return f"PIPE_{self._pipe_counter:03d}"
    
    def _calculate_distance(
        self, 
        p1: Tuple[float, float], 
        p2: Tuple[float, float]
    ) -> float:
        """Calculate Euclidean distance between two points."""
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return math.sqrt(dx * dx + dy * dy)
    
    def _create_orthogonal_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float]
    ) -> List[Tuple[float, float]]:
        """
        Create an orthogonal (Manhattan) path between two points.
        
        Pipes typically run along walls (horizontal/vertical), not diagonally.
        """
        path = [start]
        
        # First go horizontal, then vertical (or vice versa based on primary direction)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        
        if abs(dx) > abs(dy):
            # Horizontal first
            intermediate = (end[0], start[1])
        else:
            # Vertical first
            intermediate = (start[0], end[1])
        
        if intermediate != start and intermediate != end:
            path.append(intermediate)
        
        path.append(end)
        return path
    
    def route_pipe(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        pipe_type: PipeType,
        source_id: str,
        dest_id: str,
        diameter_mm: int
    ) -> Pipe:
        """
        Route a single pipe from start to end.
        """
        path = self._create_orthogonal_path(start, end)
        
        segments = []
        for i in range(len(path) - 1):
            segment = PipeSegment(
                start=path[i],
                end=path[i + 1],
                diameter_mm=diameter_mm,
                pipe_type=pipe_type
            )
            segments.append(segment)
        
        return Pipe(
            id=self._next_pipe_id(),
            pipe_type=pipe_type,
            segments=segments,
            source_id=source_id,
            destination_id=dest_id,
            diameter_mm=diameter_mm
        )
    
    def route_two_pipe_system(
        self,
        boiler: Boiler,
        radiators: List[Radiator],
        rooms: Dict[str, Room]
    ) -> List[Pipe]:
        """
        Route a two-pipe heating system.
        
        Each radiator gets:
        - Supply pipe from main supply line
        - Return pipe to main return line
        """
        pipes = []
        boiler_pos = boiler.position
        
        # Sort radiators by distance from boiler (greedy routing)
        sorted_radiators = sorted(
            radiators,
            key=lambda r: self._calculate_distance(boiler_pos, r.position)
        )
        
        # Track main line position
        current_supply_pos = boiler_pos
        current_return_pos = (boiler_pos[0] + 0.1, boiler_pos[1])  # Offset return
        
        for radiator in sorted_radiators:
            # Supply pipe: boiler -> radiator
            supply_pipe = self.route_pipe(
                start=current_supply_pos,
                end=radiator.position,
                pipe_type=PipeType.HOT_WATER_SUPPLY,
                source_id=boiler.id,
                dest_id=radiator.id,
                diameter_mm=self.config.branch_pipe_diameter_mm
            )
            pipes.append(supply_pipe)
            
            # Return pipe: radiator -> boiler
            return_end = (radiator.position[0] + 0.05, radiator.position[1])
            return_pipe = self.route_pipe(
                start=return_end,
                end=current_return_pos,
                pipe_type=PipeType.HOT_WATER_RETURN,
                source_id=radiator.id,
                dest_id=boiler.id,
                diameter_mm=self.config.branch_pipe_diameter_mm
            )
            pipes.append(return_pipe)
            
            # Update main line position for next radiator (simplified)
            current_supply_pos = radiator.position
        
        return pipes
    
    def route_one_pipe_system(
        self,
        boiler: Boiler,
        radiators: List[Radiator],
        rooms: Dict[str, Room]
    ) -> List[Pipe]:
        """
        Route a one-pipe (series) heating system.
        
        Single loop: boiler -> rad1 -> rad2 -> ... -> boiler
        Simpler piping but radiators at end get cooler water.
        """
        pipes = []
        boiler_pos = boiler.position
        
        # Sort by distance for a logical loop
        sorted_radiators = sorted(
            radiators,
            key=lambda r: self._calculate_distance(boiler_pos, r.position)
        )
        
        # Route loop
        current_pos = boiler_pos
        current_id = boiler.id
        
        for radiator in sorted_radiators:
            pipe = self.route_pipe(
                start=current_pos,
                end=radiator.position,
                pipe_type=PipeType.HOT_WATER_SUPPLY,
                source_id=current_id,
                dest_id=radiator.id,
                diameter_mm=self.config.main_pipe_diameter_mm
            )
            pipes.append(pipe)
            
            current_pos = radiator.position
            current_id = radiator.id
        
        # Close the loop back to boiler
        if sorted_radiators:
            return_pipe = self.route_pipe(
                start=current_pos,
                end=boiler_pos,
                pipe_type=PipeType.HOT_WATER_RETURN,
                source_id=current_id,
                dest_id=boiler.id,
                diameter_mm=self.config.main_pipe_diameter_mm
            )
            pipes.append(return_pipe)
        
        return pipes
    
    def route_system(
        self,
        boiler: Boiler,
        radiators: List[Radiator],
        knowledge_model: KnowledgeModel
    ) -> List[Pipe]:
        """
        Route pipes for the configured layout type.
        """
        # Build rooms dictionary
        rooms = {}
        for floor in knowledge_model.floors:
            for room in floor.rooms:
                rooms[room.id] = room
        
        if self.config.layout == PipingLayout.TWO_PIPE:
            return self.route_two_pipe_system(boiler, radiators, rooms)
        elif self.config.layout == PipingLayout.ONE_PIPE:
            return self.route_one_pipe_system(boiler, radiators, rooms)
        else:
            # Default to two-pipe
            return self.route_two_pipe_system(boiler, radiators, rooms)
    
    def calculate_total_pipe_length(self, pipes: List[Pipe]) -> Dict[str, float]:
        """
        Calculate total pipe lengths by type.
        
        Returns dict with keys 'supply', 'return', 'total' in meters.
        """
        supply_length = sum(
            p.total_length() 
            for p in pipes 
            if p.pipe_type in [PipeType.HOT_WATER_SUPPLY, PipeType.COLD_WATER_SUPPLY]
        )
        return_length = sum(
            p.total_length()
            for p in pipes
            if p.pipe_type in [PipeType.HOT_WATER_RETURN, PipeType.COLD_WATER_RETURN]
        )
        
        return {
            "supply_m": round(supply_length, 2),
            "return_m": round(return_length, 2),
            "total_m": round(supply_length + return_length, 2)
        }
