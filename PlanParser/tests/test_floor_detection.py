"""
Tests for floor detection module.
"""

import numpy as np
import pytest

from PlanParser.floor_detection import FloorDetector, FloorSection
from PlanParser.ocr_engine import OCRManager


class TestFloorDetector:
    """Tests for FloorDetector class."""

    @pytest.fixture
    def detector(self) -> FloorDetector:
        """Create a floor detector for testing."""
        ocr = OCRManager()
        return FloorDetector(ocr)

    def test_detect_floor_from_text_piano_terra(self, detector: FloorDetector) -> None:
        """Test detecting Piano Terra from text."""
        result = detector.detect_floor_from_text("piano terra")

        assert result is not None
        label, floor_num, conf = result
        assert label == "Piano Terra"
        assert floor_num == 0
        assert conf >= 0.9

    def test_detect_floor_from_text_primo_piano(self, detector: FloorDetector) -> None:
        """Test detecting Primo Piano from text."""
        result = detector.detect_floor_from_text("primo piano")

        assert result is not None
        label, floor_num, _conf = result
        assert label == "Primo Piano"
        assert floor_num == 1

    def test_detect_floor_from_text_secondo_piano(self, detector: FloorDetector) -> None:
        """Test detecting Secondo Piano from text."""
        result = detector.detect_floor_from_text("secondo piano")

        assert result is not None
        label, floor_num, _conf = result
        assert label == "Secondo Piano"
        assert floor_num == 2

    def test_detect_floor_from_text_numeric_format(self, detector: FloorDetector) -> None:
        """Test detecting floor from numeric format."""
        result = detector.detect_floor_from_text("1° piano")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == 1

    def test_detect_floor_from_text_piano_first(self, detector: FloorDetector) -> None:
        """Test detecting floor with 'piano' first."""
        result = detector.detect_floor_from_text("piano primo")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == 1

    def test_detect_floor_from_text_pt_abbreviation(self, detector: FloorDetector) -> None:
        """Test detecting floor from PT abbreviation."""
        result = detector.detect_floor_from_text("pt")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == 0

    def test_detect_floor_from_text_seminterrato(self, detector: FloorDetector) -> None:
        """Test detecting basement floor."""
        result = detector.detect_floor_from_text("seminterrato")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == -1

    def test_detect_floor_from_text_sottotetto(self, detector: FloorDetector) -> None:
        """Test detecting attic floor."""
        result = detector.detect_floor_from_text("sottotetto")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == 99  # Special code for attic

    def test_detect_floor_from_text_no_match(self, detector: FloorDetector) -> None:
        """Test with non-floor text."""
        result = detector.detect_floor_from_text("camera da letto")

        assert result is None

    def test_detect_floor_from_text_case_insensitive(self, detector: FloorDetector) -> None:
        """Test case insensitivity."""
        result = detector.detect_floor_from_text("PIANO TERRA")

        assert result is not None
        _label, floor_num, _conf = result
        assert floor_num == 0

    def test_detect_floor_from_text_with_spaces(self, detector: FloorDetector) -> None:
        """Test with extra spaces."""
        result = detector.detect_floor_from_text("piano   terra")

        assert result is not None


class TestFloorSection:
    """Tests for FloorSection dataclass."""

    def test_creation(self) -> None:
        """Test floor section creation."""
        img = np.ones((100, 200, 3), dtype=np.uint8)
        section = FloorSection(
            floor_label="Primo Piano",
            floor_number=1,
            image=img,
            y_start=0,
            y_end=100,
            confidence=0.95,
        )

        assert section.floor_label == "Primo Piano"
        assert section.floor_number == 1
        assert section.y_start == 0
        assert section.y_end == 100
        assert section.confidence == 0.95
