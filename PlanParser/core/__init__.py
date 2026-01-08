"""
Core Domain Module
==================
Contains protocols (interfaces) and domain models.
"""

from PlanParser.core.protocols import (
    # Type aliases
    ImageArray,
    # Data classes
    OCRBox,
    DetectionResult,
    # Protocols
    OCRProvider,
    TextMatcher,
    TextNormalizer,
    LabelDetector,
    ImagePreprocessor,
    RegionFinder,
    DocumentReader,
    ResultSerializer,
)

__all__ = [
    # Types
    "ImageArray",
    # DTOs
    "OCRBox",
    "DetectionResult",
    # Protocols
    "OCRProvider",
    "TextMatcher",
    "TextNormalizer",
    "LabelDetector",
    "ImagePreprocessor",
    "RegionFinder",
    "DocumentReader",
    "ResultSerializer",
]
