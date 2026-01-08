"""
PlanParser
==========
Parses planimetry PDFs/DWG/DXF and extracts structured floor/room data.

Usage:
    from PlanParser import parse_planimetry
    
    result = parse_planimetry("path/to/plan.pdf")
    print(result.floors)

CLI:
    python -m PlanParser parse --pdf path/to/plan.pdf
"""

from .parser import PlanParser, ParseResult, parse_planimetry
from .config import PlanParserConfig
from .geometry import (
    Point2D, LineSegment, Polyline, Arc, Polygon, 
    TextEntity, RawPlanGeometry
)

__version__ = "0.2.0"
__all__ = [
    "PlanParser",
    "ParseResult", 
    "parse_planimetry",
    "PlanParserConfig",
    "Point2D",
    "LineSegment",
    "Polyline",
    "Arc",
    "Polygon",
    "TextEntity",
    "RawPlanGeometry",
]
