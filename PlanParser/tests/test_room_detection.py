"""
Tests for room detection module.
"""

import numpy as np
import pytest

from PlanParser.config import RoomLabels
from PlanParser.ocr_engine import OCRManager
from PlanParser.room_detection import DetectedRoom, RoomCandidate, RoomDetector


class TestRoomDetector:
    """Tests for RoomDetector class."""

    @pytest.fixture
    def detector(self) -> RoomDetector:
        """Create a room detector for testing."""
        ocr = OCRManager()
        return RoomDetector(ocr)

    def test_build_targets(self, detector: RoomDetector) -> None:
        """Test that targets are built correctly."""
        targets = detector._targets

        assert "camera" in targets
        assert "bagno" in targets
        assert "cucina" in targets
        assert "soggiorno" in targets
        assert "disimpegno" in targets

    def test_similarity_identical(self, detector: RoomDetector) -> None:
        """Test similarity for identical strings."""
        sim = detector._similarity("camera", "camera")
        assert sim == 1.0

    def test_similarity_different(self, detector: RoomDetector) -> None:
        """Test similarity for different strings."""
        sim = detector._similarity("camera", "cucina")
        assert 0.0 < sim < 1.0

    def test_similarity_empty(self, detector: RoomDetector) -> None:
        """Test similarity with empty string."""
        assert detector._similarity("", "test") == 0.0
        assert detector._similarity("test", "") == 0.0

    def test_similarity_typo(self, detector: RoomDetector) -> None:
        """Test similarity detects typos."""
        sim = detector._similarity("cemera", "camera")
        assert sim >= 0.8  # Should be high for 1-char typo

    def test_get_canonical_label_direct(self, detector: RoomDetector) -> None:
        """Test canonical label for direct match."""
        label = detector._get_canonical_label("camera")
        assert label == "camera"

    def test_get_canonical_label_synonym(self, detector: RoomDetector) -> None:
        """Test canonical label for synonym."""
        label = detector._get_canonical_label("wc")
        assert label == "bagno"

    def test_classify_candidate_exact_match(self, detector: RoomDetector) -> None:
        """Test classifying candidate with exact match."""
        candidate = RoomCandidate(
            bbox=(10, 20, 50, 30),
            ocr_results=["bagno"],
            tokens={"bagno"},
        )

        room = detector.classify_candidate(candidate)

        assert room is not None
        assert room.label == "bagno"
        assert room.confidence == 1.0

    def test_classify_candidate_fuzzy_match(self, detector: RoomDetector) -> None:
        """Test classifying candidate with fuzzy match."""
        candidate = RoomCandidate(
            bbox=(10, 20, 50, 30),
            ocr_results=["cemera"],  # Typo
            tokens={"cemera"},
        )

        room = detector.classify_candidate(candidate)

        assert room is not None
        assert room.label == "camera"
        assert room.confidence >= 0.75

    def test_classify_candidate_no_match(self, detector: RoomDetector) -> None:
        """Test classifying candidate with no match."""
        candidate = RoomCandidate(
            bbox=(10, 20, 50, 30),
            ocr_results=["xyz123"],
            tokens={"xyz123"},
        )

        room = detector.classify_candidate(candidate)

        assert room is None


class TestDetectedRoom:
    """Tests for DetectedRoom dataclass."""

    def test_creation(self) -> None:
        """Test detected room creation."""
        room = DetectedRoom(
            label="Camera",
            normalized_label="camera",
            bbox=(100, 200, 150, 80),
            center=(175, 240),
            confidence=0.95,
            raw_ocr_text="Camera",
        )

        assert room.label == "Camera"
        assert room.bbox == (100, 200, 150, 80)
        assert room.center == (175, 240)
        assert room.confidence == 0.95

    def test_area_property(self) -> None:
        """Test area calculation."""
        room = DetectedRoom(
            label="Test",
            normalized_label="test",
            bbox=(0, 0, 100, 50),
            center=(50, 25),
            confidence=1.0,
            raw_ocr_text="Test",
        )

        assert room.area == 5000  # 100 * 50


class TestRoomCandidate:
    """Tests for RoomCandidate dataclass."""

    def test_creation(self) -> None:
        """Test room candidate creation."""
        candidate = RoomCandidate(
            bbox=(10, 20, 30, 40),
            ocr_results=["camera"],
            tokens={"camera"},
        )

        assert candidate.bbox == (10, 20, 30, 40)
        assert "camera" in candidate.tokens

    def test_with_image_crop(self) -> None:
        """Test candidate with image crop."""
        img = np.ones((40, 30, 3), dtype=np.uint8)
        candidate = RoomCandidate(
            bbox=(0, 0, 30, 40),
            ocr_results=[],
            tokens=set(),
            image_crop=img,
        )

        assert candidate.image_crop is not None
        assert candidate.image_crop.shape == (40, 30, 3)


class TestRoomLabels:
    """Tests for RoomLabels config."""

    def test_default_targets(self) -> None:
        """Test default target labels."""
        labels = RoomLabels()

        assert "camera" in labels.targets
        assert "bagno" in labels.targets
        assert "cucina" in labels.targets

    def test_default_blacklist(self) -> None:
        """Test default blacklist."""
        labels = RoomLabels()

        assert "armadio" in labels.blacklist
        assert "scala" in labels.blacklist

    def test_default_synonyms(self) -> None:
        """Test default synonyms."""
        labels = RoomLabels()

        assert "soggiorno" in labels.synonyms
        assert "sala" in labels.synonyms["soggiorno"]
