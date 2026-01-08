"""
Topology Value Objects
======================
Spatial relationships between spaces and elements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PlanParser.domain.models.spaces import Room


class ConnectionType(Enum):
    """Type of connection between spaces."""
    DOOR = "door"           # Connected via door
    OPENING = "opening"     # Open passage (no door)
    WINDOW = "window"       # Visual connection only
    WALL = "wall"           # Adjacent but separated by wall
    NONE = "none"           # Not adjacent


class WallPosition(Enum):
    """Position of wall relative to room."""
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    INTERIOR = "interior"   # Internal partition
    EXTERIOR = "exterior"   # Building boundary


@dataclass(frozen=True)
class Adjacency:
    """
    Represents adjacency relationship between two spaces.
    
    Immutable value object describing how two rooms relate spatially.
    """
    room_a_id: str
    room_b_id: str
    connection_type: ConnectionType
    shared_wall_length_meters: float | None = None
    opening_id: str | None = None  # ID of door/window if applicable
    
    @property
    def is_connected(self) -> bool:
        """True if spaces are physically connected (can walk between)."""
        return self.connection_type in (ConnectionType.DOOR, ConnectionType.OPENING)
    
    @property
    def is_adjacent(self) -> bool:
        """True if spaces share a wall."""
        return self.connection_type != ConnectionType.NONE
    
    def involves(self, room_id: str) -> bool:
        """Check if this adjacency involves a specific room."""
        return room_id in (self.room_a_id, self.room_b_id)
    
    def other_room(self, room_id: str) -> str:
        """Get the other room in this adjacency."""
        if room_id == self.room_a_id:
            return self.room_b_id
        elif room_id == self.room_b_id:
            return self.room_a_id
        raise ValueError(f"Room {room_id} not in this adjacency")


@dataclass
class TopologyGraph:
    """
    Graph representation of spatial topology.
    
    Nodes are rooms, edges are adjacencies.
    Enables queries like "rooms reachable from X" or "path between rooms".
    """
    adjacencies: list[Adjacency] = field(default_factory=list)
    
    def get_adjacent_rooms(self, room_id: str) -> list[str]:
        """Get all rooms adjacent to given room."""
        result = []
        for adj in self.adjacencies:
            if adj.involves(room_id):
                result.append(adj.other_room(room_id))
        return result
    
    def get_connected_rooms(self, room_id: str) -> list[str]:
        """Get rooms directly reachable (via door/opening) from given room."""
        result = []
        for adj in self.adjacencies:
            if adj.involves(room_id) and adj.is_connected:
                result.append(adj.other_room(room_id))
        return result
    
    def get_adjacency(self, room_a_id: str, room_b_id: str) -> Adjacency | None:
        """Get adjacency between two specific rooms."""
        for adj in self.adjacencies:
            if adj.involves(room_a_id) and adj.involves(room_b_id):
                return adj
        return None
    
    def find_path(self, from_room: str, to_room: str) -> list[str] | None:
        """
        Find path of rooms between two rooms (BFS).
        Returns list of room IDs or None if not reachable.
        """
        if from_room == to_room:
            return [from_room]
        
        visited = {from_room}
        queue = [[from_room]]
        
        while queue:
            path = queue.pop(0)
            current = path[-1]
            
            for next_room in self.get_connected_rooms(current):
                if next_room == to_room:
                    return path + [next_room]
                if next_room not in visited:
                    visited.add(next_room)
                    queue.append(path + [next_room])
        
        return None  # No path found
