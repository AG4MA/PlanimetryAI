"""
Domain Layer
=============
Core business logic, models, protocols and value objects.
This layer has NO dependencies on infrastructure or application layers.
"""

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
from PlanParser.domain.text_utils import normalize_text, clean_ocr_text
from PlanParser.domain.models import (
    Point2D,
    LineSegment,
    Polyline,
    Arc,
    Polygon,
    TextEntity,
    RawPlanGeometry,
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
    # Models
    "Point2D",
    "LineSegment",
    "Polyline",
    "Arc",
    "Polygon",
    "TextEntity",
    "RawPlanGeometry",
]
