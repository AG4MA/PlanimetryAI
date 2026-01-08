"""
Measurement Value Objects
=========================
Immutable value objects for physical measurements with units.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Self


class LengthUnit(Enum):
    """Supported length units."""
    MILLIMETERS = "mm"
    CENTIMETERS = "cm"
    METERS = "m"
    PIXELS = "px"


class AreaUnit(Enum):
    """Supported area units."""
    SQUARE_MILLIMETERS = "mm²"
    SQUARE_CENTIMETERS = "cm²"
    SQUARE_METERS = "m²"
    SQUARE_PIXELS = "px²"


@dataclass(frozen=True)
class Length:
    """Immutable length measurement with unit."""
    value: float
    unit: LengthUnit = LengthUnit.METERS
    
    def to_meters(self) -> float:
        """Convert to meters."""
        conversions = {
            LengthUnit.MILLIMETERS: 0.001,
            LengthUnit.CENTIMETERS: 0.01,
            LengthUnit.METERS: 1.0,
            LengthUnit.PIXELS: None,  # Requires scale
        }
        factor = conversions[self.unit]
        if factor is None:
            raise ValueError("Cannot convert pixels to meters without scale")
        return self.value * factor
    
    def to_unit(self, target: LengthUnit) -> Self:
        """Convert to different unit."""
        if self.unit == LengthUnit.PIXELS or target == LengthUnit.PIXELS:
            raise ValueError("Pixel conversion requires scale context")
        meters = self.to_meters()
        factors = {
            LengthUnit.MILLIMETERS: 1000.0,
            LengthUnit.CENTIMETERS: 100.0,
            LengthUnit.METERS: 1.0,
        }
        return Length(meters * factors[target], target)


@dataclass(frozen=True)
class Area:
    """Immutable area measurement with unit."""
    value: float
    unit: AreaUnit = AreaUnit.SQUARE_METERS
    
    def to_square_meters(self) -> float:
        """Convert to square meters."""
        conversions = {
            AreaUnit.SQUARE_MILLIMETERS: 1e-6,
            AreaUnit.SQUARE_CENTIMETERS: 1e-4,
            AreaUnit.SQUARE_METERS: 1.0,
            AreaUnit.SQUARE_PIXELS: None,
        }
        factor = conversions[self.unit]
        if factor is None:
            raise ValueError("Cannot convert pixels² to m² without scale")
        return self.value * factor


@dataclass(frozen=True)
class Scale:
    """
    Scale representation for planimetry.
    
    Example: Scale(ratio=100) means 1:100 (1cm on paper = 1m real)
    """
    ratio: float  # e.g., 100 for 1:100
    pixels_per_meter: float | None = None  # Set after rendering
    
    @property
    def label(self) -> str:
        return f"1:{int(self.ratio)}"
    
    def pixels_to_meters(self, pixels: float) -> float:
        """Convert pixel distance to real-world meters."""
        if self.pixels_per_meter is None:
            raise ValueError("pixels_per_meter not set")
        return pixels / self.pixels_per_meter
    
    def meters_to_pixels(self, meters: float) -> float:
        """Convert real-world meters to pixels."""
        if self.pixels_per_meter is None:
            raise ValueError("pixels_per_meter not set")
        return meters * self.pixels_per_meter
