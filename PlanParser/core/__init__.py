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

from PlanParser.core.text_utils import normalize_text, clean_ocr_text

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
    # Utilities
    "normalize_text",
    "clean_ocr_text",
]
