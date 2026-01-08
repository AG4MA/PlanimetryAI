"""
Core Protocols (Interfaces)
===========================
Abstract interfaces for dependency inversion.
All implementations depend on these protocols, not concrete classes.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


# Type alias for images
ImageArray = NDArray[np.uint8]


# ============================================================================
# OCR Protocols
# ============================================================================

@dataclass(frozen=True)
class OCRBox:
    """Immutable OCR result with bounding box."""
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@runtime_checkable
class OCRProvider(Protocol):
    """Protocol for OCR engines."""

    def is_available(self) -> bool:
        """Check if this OCR engine can be used."""
        ...

    def recognize(self, image: ImageArray) -> list[OCRBox]:
        """Extract text with bounding boxes from image."""
        ...

    def recognize_text(self, image: ImageArray) -> str:
        """Extract plain text from image."""
        ...


# ============================================================================
# Text Matching Protocols
# ============================================================================

@runtime_checkable
class TextMatcher(Protocol):
    """Protocol for text similarity matching."""

    def similarity(self, a: str, b: str) -> float:
        """Calculate similarity score between two strings (0.0 to 1.0)."""
        ...

    def find_best_match(
        self,
        text: str,
        targets: set[str],
        threshold: float = 0.75
    ) -> tuple[str, float] | None:
        """Find best matching target for text."""
        ...


@runtime_checkable
class TextNormalizer(Protocol):
    """Protocol for text normalization."""

    def normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        ...


# ============================================================================
# Detection Protocols
# ============================================================================

@dataclass(frozen=True)
class DetectionResult:
    """Generic detection result."""
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)


@runtime_checkable
class LabelDetector(Protocol):
    """Protocol for detecting labels in images."""

    def detect(self, image: ImageArray) -> list[DetectionResult]:
        """Detect labels in image."""
        ...


# ============================================================================
# Image Processing Protocols
# ============================================================================

@runtime_checkable
class ImagePreprocessor(Protocol):
    """Protocol for image preprocessing."""

    def preprocess(self, image: ImageArray) -> ImageArray:
        """Preprocess image for detection."""
        ...


@runtime_checkable
class RegionFinder(Protocol):
    """Protocol for finding regions in images."""

    def find_text_regions(
        self,
        image: ImageArray,
        **kwargs: Any
    ) -> list[tuple[int, int, int, int]]:
        """Find potential text regions, returns list of (x, y, w, h)."""
        ...


# ============================================================================
# Document Processing Protocols
# ============================================================================

@runtime_checkable
class DocumentReader(Protocol):
    """Protocol for reading documents."""

    def read_page(self, path: str, page: int = 0) -> ImageArray | None:
        """Read a page from document as image."""
        ...


# ============================================================================
# Output Protocols
# ============================================================================

@runtime_checkable
class ResultSerializer(Protocol):
    """Protocol for serializing results."""

    def to_dict(self, result: object) -> dict[str, Any]:
        """Convert result to dictionary."""
        ...

    def to_json(self, result: object) -> str:
        """Convert result to JSON string."""
        ...
