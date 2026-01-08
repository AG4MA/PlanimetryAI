"""
PlanParser
==========
Parses planimetry PDFs/DWG/DXF and extracts a structured Digital Twin.

The output (DigitalTwin) is the single source of truth for downstream projects:
- Plan2HVAC: Uses topology and room types for HVAC layout
- PlanNL: Uses all data for natural language queries

Usage:
    from PlanParser import parse_planimetry
    
    twin = parse_planimetry("path/to/plan.pdf")
    print(twin.summary())
    twin.save_json("output/plan_twin.json")

CLI:
    python -m PlanParser parse --pdf path/to/plan.pdf
"""

__version__ = "0.3.0"

# Domain layer - core models and value objects
from PlanParser.domain import (
    # Config
    PlanParserConfig,
    DEFAULT_CONFIG,
    SourceType,
    
    # Value Objects
    Scale,
    Compass,
    TopologyGraph,
    
    # Primitives
    Point2D,
    LineSegment,
    Polyline,
    Arc,
    Polygon,
    TextEntity,
    RawPlanGeometry,
    
    # Elements
    Wall,
    Door,
    Window,
    
    # Spaces
    RoomType,
    Room,
    
    # Building
    Floor,
    Building,
    
    # Digital Twin (PRIMARY OUTPUT)
    DigitalTwin,
)

# Lazy import for tesseract
def init_tesseract(require: bool = False, silent: bool = False):
    """Initialize Tesseract OCR - only called when needed."""
    from PlanParser.infrastructure.ocr.bootstrap import init_tesseract as _init_tesseract
    return _init_tesseract(require=require, silent=silent)


# Main API (lazy loaded to avoid import issues during refactoring)
def parse_planimetry(source_path: str, **kwargs) -> DigitalTwin:
    """
    Parse a planimetry file and return a DigitalTwin.
    
    Args:
        source_path: Path to PDF, image, or CAD file
        **kwargs: Additional options passed to PlanParser
        
    Returns:
        DigitalTwin with complete structured data
    """
    # TODO: Update to use new pipeline once refactoring is complete
    raise NotImplementedError(
        "parse_planimetry is being refactored to return DigitalTwin. "
        "Use the legacy API via PlanParser.application.use_cases for now."
    )


__all__ = [
    # Version
    "__version__",
    
    # Config
    "PlanParserConfig",
    "DEFAULT_CONFIG",
    "SourceType",
    
    # Value Objects
    "Scale",
    "Compass",
    "TopologyGraph",
    
    # Primitives
    "Point2D",
    "LineSegment",
    "Polyline",
    "Arc",
    "Polygon",
    "TextEntity",
    "RawPlanGeometry",
    
    # Elements
    "Wall",
    "Door", 
    "Window",
    
    # Spaces
    "RoomType",
    "Room",
    
    # Building
    "Floor",
    "Building",
    
    # Digital Twin (PRIMARY OUTPUT)
    "DigitalTwin",
    
    # Functions
    "parse_planimetry",
    "init_tesseract",
]
