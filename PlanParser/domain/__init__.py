"""
Domain Layer
=============
Core business logic, models, protocols and value objects.
This layer has NO dependencies on infrastructure or application layers.

The primary output is the DigitalTwin - the "single source of truth"
that downstream projects (Plan2HVAC, PlanNL) consume.
"""

# Configuration
from PlanParser.domain.config import (
    PlanParserConfig,
    DEFAULT_CONFIG,
    SourceType,
    Orientation,
    ScaleConfig,
    OCRConfig,
    RoomLabels,
    DetectionConfig,
    PACKAGE_DIR,
)

# Protocols (interfaces)
from PlanParser.domain.protocols import (
    ImageArray,
    OCRBox,
    DetectionResult,
    OCRProvider,
    TextMatcher,
    TextNormalizer,
    LabelDetector,
    ImagePreprocessor,
    RegionFinder,
    DocumentReader,
    ResultSerializer,
)

# Utilities
from PlanParser.domain.text_utils import normalize_text, clean_ocr_text

# Value Objects
from PlanParser.domain.value_objects import (
    LengthUnit,
    AreaUnit,
    Length,
    Area,
    Scale,
    CardinalDirection,
    Compass,
    ConnectionType,
    WallPosition,
    Adjacency,
    TopologyGraph,
)

# Models - Primitives
from PlanParser.domain.models import (
    Point2D,
    LineSegment,
    Polyline,
    Arc,
    Polygon,
    TextEntity,
    RawPlanGeometry,
)

# Models - Architectural Elements
from PlanParser.domain.models import (
    WallType,
    DoorType,
    WindowType,
    Wall,
    Door,
    Window,
    Opening,
)

# Models - Spaces
from PlanParser.domain.models import (
    RoomType,
    Room,
    Stairwell,
)

# Models - Building Structure
from PlanParser.domain.models import (
    Floor,
    Building,
)

# Models - Top-level Output
from PlanParser.domain.models import (
    ProcessingMetadata,
    DigitalTwin,
)


__all__ = [
    # Config
    "PlanParserConfig",
    "DEFAULT_CONFIG",
    "SourceType",
    "Orientation",
    "ScaleConfig",
    "OCRConfig",
    "RoomLabels",
    "DetectionConfig",
    "PACKAGE_DIR",
    
    # Protocols
    "ImageArray",
    "OCRBox",
    "DetectionResult",
    "OCRProvider",
    "TextMatcher",
    "TextNormalizer",
    "LabelDetector",
    "ImagePreprocessor",
    "RegionFinder",
    "DocumentReader",
    "ResultSerializer",
    
    # Utils
    "normalize_text",
    "clean_ocr_text",
    
    # Value Objects
    "LengthUnit",
    "AreaUnit",
    "Length",
    "Area",
    "Scale",
    "CardinalDirection",
    "Compass",
    "ConnectionType",
    "WallPosition",
    "Adjacency",
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
    "WallType",
    "DoorType",
    "WindowType",
    "Wall",
    "Door",
    "Window",
    "Opening",
    
    # Spaces
    "RoomType",
    "Room",
    "Stairwell",
    
    # Building
    "Floor",
    "Building",
    
    # Digital Twin (PRIMARY OUTPUT)
    "ProcessingMetadata",
    "DigitalTwin",
]
