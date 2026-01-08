"""
Orientation Value Objects
=========================
Cardinal directions and compass orientation.
"""

from dataclasses import dataclass
from enum import Enum
import math


class CardinalDirection(Enum):
    """Cardinal and intercardinal directions."""
    NORTH = "N"
    SOUTH = "S"
    EAST = "E"
    WEST = "W"
    NORTH_EAST = "NE"
    NORTH_WEST = "NW"
    SOUTH_EAST = "SE"
    SOUTH_WEST = "SW"
    UNKNOWN = "?"
    
    @classmethod
    def from_angle(cls, degrees: float) -> "CardinalDirection":
        """
        Get cardinal direction from angle.
        0° = North (up), 90° = East (right), etc.
        """
        # Normalize to 0-360
        degrees = degrees % 360
        
        if 337.5 <= degrees or degrees < 22.5:
            return cls.NORTH
        elif 22.5 <= degrees < 67.5:
            return cls.NORTH_EAST
        elif 67.5 <= degrees < 112.5:
            return cls.EAST
        elif 112.5 <= degrees < 157.5:
            return cls.SOUTH_EAST
        elif 157.5 <= degrees < 202.5:
            return cls.SOUTH
        elif 202.5 <= degrees < 247.5:
            return cls.SOUTH_WEST
        elif 247.5 <= degrees < 292.5:
            return cls.WEST
        else:
            return cls.NORTH_WEST


@dataclass(frozen=True)
class Compass:
    """
    Compass orientation for the planimetry.
    
    north_angle_degrees: Angle of North from image "up" direction.
    0° = North is up (standard)
    90° = North is right
    180° = North is down
    270° = North is left
    """
    north_angle_degrees: float = 0.0
    detected: bool = False  # Was this auto-detected or assumed?
    
    @property
    def is_standard(self) -> bool:
        """True if North is up (standard orientation)."""
        return abs(self.north_angle_degrees) < 1.0
    
    def image_direction_to_cardinal(self, image_angle_degrees: float) -> CardinalDirection:
        """
        Convert an angle in image space to a cardinal direction.
        
        Args:
            image_angle_degrees: Angle in image coordinates (0° = up)
            
        Returns:
            Cardinal direction in real-world coordinates
        """
        real_angle = (image_angle_degrees - self.north_angle_degrees) % 360
        return CardinalDirection.from_angle(real_angle)
    
    def cardinal_to_image_angle(self, direction: CardinalDirection) -> float:
        """
        Convert a cardinal direction to an angle in image space.
        """
        direction_angles = {
            CardinalDirection.NORTH: 0,
            CardinalDirection.NORTH_EAST: 45,
            CardinalDirection.EAST: 90,
            CardinalDirection.SOUTH_EAST: 135,
            CardinalDirection.SOUTH: 180,
            CardinalDirection.SOUTH_WEST: 225,
            CardinalDirection.WEST: 270,
            CardinalDirection.NORTH_WEST: 315,
            CardinalDirection.UNKNOWN: 0,
        }
        real_angle = direction_angles[direction]
        return (real_angle + self.north_angle_degrees) % 360
