"""
Tests for OCR engine module.

Note: Some tests use EasyOCR which has compatibility issues with Python 3.14 alpha.
"""

import sys

import numpy as np
import pytest

from PlanParser.ocr_engine import (
    OCRManager,
    OCRResult,
    TesseractEngine,
    normalize_text,
)

# Skip tests that use EasyOCR on Python 3.14+ due to PyTorch compatibility issues
requires_stable_python = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="EasyOCR/PyTorch has compatibility issues with Python 3.14 alpha"
)


class TestNormalizeText:
    """Tests for text normalization function."""

    def test_lowercase(self) -> None:
        """Test lowercase conversion."""
        assert normalize_text("CAMERA") == "camera"
        assert normalize_text("BaGnO") == "bagno"

    def test_remove_accents(self) -> None:
        """Test accent removal."""
        assert normalize_text("città") == "citta"
        assert normalize_text("perché") == "perche"

    def test_replace_hyphens(self) -> None:
        """Test hyphen to space conversion."""
        assert normalize_text("soggiorno-pranzo") == "soggiorno pranzo"

    def test_normalize_whitespace(self) -> None:
        """Test whitespace normalization."""
        assert normalize_text("  camera   doppia  ") == "camera doppia"
        assert normalize_text("dis\t.") == "dis"  # trailing period removed for short text

    def test_remove_trailing_period_short(self) -> None:
        """Test trailing period removal for abbreviations."""
        assert normalize_text("dis.") == "dis"
        assert normalize_text("rip.") == "rip"

    def test_keep_trailing_period_long(self) -> None:
        """Test trailing period kept for longer words."""
        assert normalize_text("camera.") == "camera."

    def test_empty_string(self) -> None:
        """Test empty string handling."""
        assert normalize_text("") == ""
        assert normalize_text(None) == ""

    def test_keep_allowed_chars(self) -> None:
        """Test allowed characters are kept."""
        assert normalize_text("piano_1") == "piano_1"
        assert normalize_text("path/to") == "path/to"


class TestOCRResult:
    """Tests for OCRResult dataclass."""

    def test_creation(self) -> None:
        """Test OCR result creation."""
        result = OCRResult(text="Camera", confidence=0.95, bbox=(10, 20, 50, 30))

        assert result.text == "Camera"
        assert result.confidence == 0.95
        assert result.bbox == (10, 20, 50, 30)

    def test_normalized_text(self) -> None:
        """Test normalized text property."""
        result = OCRResult(text="BAGNO", confidence=0.9)
        assert result.normalized_text == "bagno"

    def test_no_bbox(self) -> None:
        """Test result without bounding box."""
        result = OCRResult(text="Test", confidence=0.5)
        assert result.bbox is None


class TestTesseractEngine:
    """Tests for Tesseract OCR engine."""

    def test_availability_check(self) -> None:
        """Test Tesseract availability detection."""
        engine = TesseractEngine()
        # Just check it doesn't crash
        _ = engine.is_available()

    def test_recognize_empty_image(self) -> None:
        """Test recognition on empty image."""
        engine = TesseractEngine()
        if not engine.is_available():
            pytest.skip("Tesseract not available")

        # Create blank white image
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        results = engine.recognize(img)

        # Should return empty or minimal results for blank image
        assert isinstance(results, list)


class TestOCRManager:
    """Tests for OCR manager."""

    def test_creation(self) -> None:
        """Test OCR manager creation."""
        manager = OCRManager()
        assert len(manager.engines) >= 1

    def test_get_available_engine(self) -> None:
        """Test getting available engine."""
        manager = OCRManager()
        engine = manager.get_available_engine()

        # Either an engine is available or None
        if engine is not None:
            assert engine.is_available()

    @requires_stable_python
    def test_recognize_blank_image(self) -> None:
        """Test recognition on blank image."""
        manager = OCRManager()

        # Create blank image
        img = np.ones((50, 200, 3), dtype=np.uint8) * 255
        results = manager.recognize(img)

        assert isinstance(results, list)

    @requires_stable_python
    def test_recognize_text_blank_image(self) -> None:
        """Test text recognition on blank image."""
        manager = OCRManager()

        img = np.ones((50, 200, 3), dtype=np.uint8) * 255
        text = manager.recognize_text(img)

        assert isinstance(text, str)
