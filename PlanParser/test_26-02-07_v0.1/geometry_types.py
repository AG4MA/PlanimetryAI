"""
Shared data types for the PlanParser pipeline.

Contains geometric primitives and intermediate result containers
used across all pipeline steps.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import numpy as np
import math


@dataclass
class Segment:
    """A line segment extracted from the image."""
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def length(self) -> float:
        return math.sqrt((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2)

    @property
    def angle(self) -> float:
        """Angle in radians [-pi, pi]."""
        return math.atan2(self.y2 - self.y1, self.x2 - self.x1)

    @property
    def angle_deg(self) -> float:
        """Angle in degrees [0, 180)."""
        a = math.degrees(self.angle)
        if a < 0:
            a += 180.0
        return a

    @property
    def midpoint(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def to_tuple(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return ((self.x1, self.y1), (self.x2, self.y2))

    def is_horizontal(self, tolerance_deg: float = 5.0) -> bool:
        a = self.angle_deg
        return a < tolerance_deg or a > 180.0 - tolerance_deg

    def is_vertical(self, tolerance_deg: float = 5.0) -> bool:
        return abs(self.angle_deg - 90.0) < tolerance_deg

    def perpendicular_distance_to_point(self, px: float, py: float) -> float:
        """Distance from point (px, py) to the infinite line through this segment."""
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        length = self.length
        if length < 1e-12:
            return math.sqrt((px - self.x1) ** 2 + (py - self.y1) ** 2)
        return abs(dy * px - dx * py + self.x2 * self.y1 - self.y2 * self.x1) / length


@dataclass
class TextBlock:
    """A text block extracted by OCR, with bounding box and confidence."""
    text: str
    x: int
    y: int
    w: int
    h: int
    confidence: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class FloorImage:
    """A single floor's image with its detected label."""
    image: np.ndarray
    label: str
    confidence: float = 0.0
    source_rect: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) in original


@dataclass
class ExtractionResult:
    """Output of Step 4 for a single floor image."""
    segments: List[Segment] = field(default_factory=list)
    text_blocks: List[TextBlock] = field(default_factory=list)
    debug_images: dict = field(default_factory=dict)
