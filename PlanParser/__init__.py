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

# Bootstrap: ensure Tesseract is available
from .bootstrap import init_tesseract

_tesseract_path = init_tesseract(require=False)

from .config import PlanParserConfig
from .geometry import Arc, LineSegment, Point2D, Polygon, Polyline, RawPlanGeometry, TextEntity
from .parser import ParseResult, PlanParser, parse_planimetry

__version__ = "0.2.0"
__all__ = [
    "Arc",
    "LineSegment",
    "ParseResult",
    "PlanParser",
    "PlanParserConfig",
    "Point2D",
    "Polygon",
    "Polyline",
    "RawPlanGeometry",
    "TextEntity",
    "parse_planimetry",
    "init_tesseract",
]
