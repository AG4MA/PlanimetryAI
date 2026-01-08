"""
Tests for services module.
"""

import numpy as np
import pytest
from numpy.typing import NDArray

from PlanParser.services.text_matching import (
    DefaultTextNormalizer,
    SequenceTextMatcher,
    FuzzyTextMatcher,
)
from PlanParser.services.visualization import (
    VisualStyle,
    VisualizationService,
)
from PlanParser.domain.protocols import DetectionResult

# Type alias for test images
ImageArray = NDArray[np.uint8]


# ============================================================================
# Text Normalizer Tests
# ============================================================================

class TestDefaultTextNormalizer:
    """Tests for DefaultTextNormalizer."""

    @pytest.fixture
    def normalizer(self) -> DefaultTextNormalizer:
        return DefaultTextNormalizer()

    def test_lowercase(self, normalizer: DefaultTextNormalizer) -> None:
        assert normalizer.normalize("CAMERA") == "camera"

    def test_strip_whitespace(self, normalizer: DefaultTextNormalizer) -> None:
        assert normalizer.normalize("  camera  ") == "camera"

    def test_remove_punctuation(self, normalizer: DefaultTextNormalizer) -> None:
        assert normalizer.normalize("camera!") == "camera"
        assert normalizer.normalize("camera.") == "camera"

    def test_collapse_whitespace(self, normalizer: DefaultTextNormalizer) -> None:
        assert normalizer.normalize("camera  da   letto") == "camera da letto"


# ============================================================================
# Sequence Text Matcher Tests
# ============================================================================

class TestSequenceTextMatcher:
    """Tests for SequenceTextMatcher."""

    @pytest.fixture
    def matcher(self) -> SequenceTextMatcher:
        return SequenceTextMatcher()

    def test_identical_strings(self, matcher: SequenceTextMatcher) -> None:
        assert matcher.similarity("camera", "camera") == 1.0

    def test_completely_different(self, matcher: SequenceTextMatcher) -> None:
        sim = matcher.similarity("abc", "xyz")
        assert sim < 0.5

    def test_empty_strings(self, matcher: SequenceTextMatcher) -> None:
        assert matcher.similarity("", "") == 0.0
        assert matcher.similarity("test", "") == 0.0
        assert matcher.similarity("", "test") == 0.0

    def test_find_best_match_found(self, matcher: SequenceTextMatcher) -> None:
        targets = {"camera", "bagno", "cucina"}
        result = matcher.find_best_match("camera", targets, threshold=0.75)
        
        assert result is not None
        assert result[0] == "camera"
        assert result[1] == 1.0

    def test_find_best_match_not_found(self, matcher: SequenceTextMatcher) -> None:
        targets = {"camera", "bagno", "cucina"}
        result = matcher.find_best_match("xyz123", targets, threshold=0.75)
        
        assert result is None


# ============================================================================
# Fuzzy Text Matcher Tests
# ============================================================================

class TestFuzzyTextMatcher:
    """Tests for FuzzyTextMatcher."""

    @pytest.fixture
    def matcher(self) -> FuzzyTextMatcher:
        return FuzzyTextMatcher()

    def test_exact_match(self, matcher: FuzzyTextMatcher) -> None:
        assert matcher.similarity("camera", "camera") == 1.0

    def test_prefix_match(self, matcher: FuzzyTextMatcher) -> None:
        """Prefix should give high score."""
        sim = matcher.similarity("cucina", "cucina abitabile")
        assert sim >= 0.9

    def test_find_all_matches(self, matcher: FuzzyTextMatcher) -> None:
        targets = {"camera", "cameretta", "camerino", "bagno"}
        results = matcher.find_all_matches("camera", targets, threshold=0.5)
        
        assert len(results) >= 1
        # First should be exact match
        assert results[0][0] == "camera"
        assert results[0][1] == 1.0

    def test_case_insensitive(self, matcher: FuzzyTextMatcher) -> None:
        sim = matcher.similarity("CAMERA", "camera")
        assert sim == 1.0


# ============================================================================
# Visual Style Tests
# ============================================================================

class TestVisualStyle:
    """Tests for VisualStyle dataclass."""

    def test_default_values(self) -> None:
        style = VisualStyle()
        
        assert style.box_color == (0, 255, 0)
        assert style.line_thickness == 2
        assert style.font_scale == 0.6

    def test_custom_values(self) -> None:
        style = VisualStyle(
            box_color=(255, 0, 0),
            line_thickness=3
        )
        
        assert style.box_color == (255, 0, 0)
        assert style.line_thickness == 3

    def test_immutable(self) -> None:
        style = VisualStyle()
        
        with pytest.raises(AttributeError):
            style.box_color = (0, 0, 255)  # type: ignore


# ============================================================================
# Visualization Service Tests
# ============================================================================

class TestVisualizationService:
    """Tests for VisualizationService."""

    @pytest.fixture
    def service(self) -> VisualizationService:
        return VisualizationService()

    @pytest.fixture
    def test_image(self) -> ImageArray:
        """Create a simple test image."""
        return np.zeros((100, 100, 3), dtype=np.uint8) + 128

    def test_draw_bbox(
        self, service: VisualizationService, test_image: ImageArray
    ) -> None:
        """Test drawing a bounding box."""
        result = service.draw_bbox(test_image, (10, 10, 30, 30))
        
        # Result should be a copy
        assert result is not test_image
        # Check shape preserved
        assert result.shape == test_image.shape

    def test_draw_detection(
        self, service: VisualizationService, test_image: ImageArray
    ) -> None:
        """Test drawing a detection result."""
        detection = DetectionResult(
            label="Camera",
            confidence=0.95,
            bbox=(10, 20, 40, 30)
        )
        
        result = service.draw_detection(test_image, detection)
        
        assert result is not test_image
        assert result.shape == test_image.shape

    def test_draw_detections_multiple(
        self, service: VisualizationService, test_image: ImageArray
    ) -> None:
        """Test drawing multiple detections."""
        detections = [
            DetectionResult("Room1", 0.9, (10, 10, 20, 20)),
            DetectionResult("Room2", 0.8, (40, 40, 25, 25)),
        ]
        
        result = service.draw_detections(test_image, detections)
        
        assert result is not test_image
        assert result.shape == test_image.shape

    def test_custom_style(self, test_image: ImageArray) -> None:
        """Test service with custom style."""
        custom_style = VisualStyle(
            box_color=(255, 0, 0),
            line_thickness=5
        )
        service = VisualizationService(style=custom_style)
        
        _result = service.draw_bbox(test_image, (10, 10, 30, 30))
        
        # Should use custom style
        assert service.style.box_color == (255, 0, 0)
