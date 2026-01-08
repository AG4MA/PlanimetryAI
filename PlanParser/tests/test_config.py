"""
Tests for configuration module.
"""

from pathlib import Path

from PlanParser.config import (
    DEFAULT_CONFIG,
    DetectionConfig,
    FloorLabels,
    OCRConfig,
    OutputConfig,
    PlanParserConfig,
    RoomLabels,
)


class TestDetectionConfig:
    """Tests for DetectionConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = DetectionConfig()

        assert config.min_area == 50
        assert config.max_area == 14000
        assert config.min_aspect_ratio == 1.1
        assert config.max_aspect_ratio == 22.0
        assert config.min_height == 6
        assert config.max_height == 64

    def test_custom_values(self) -> None:
        """Test custom values."""
        config = DetectionConfig(min_area=100, max_area=10000)

        assert config.min_area == 100
        assert config.max_area == 10000


class TestOCRConfig:
    """Tests for OCRConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = OCRConfig()

        assert config.languages == "ita+eng"
        assert config.oem == 3
        assert config.psm_modes == [7, 6, 11]
        assert config.tesseract_path is None

    def test_custom_tesseract_path(self) -> None:
        """Test custom Tesseract path."""
        config = OCRConfig(tesseract_path="/usr/bin/tesseract")

        assert config.tesseract_path == "/usr/bin/tesseract"


class TestRoomLabels:
    """Tests for RoomLabels."""

    def test_targets_not_empty(self) -> None:
        """Test that targets are not empty."""
        labels = RoomLabels()

        assert len(labels.targets) > 0

    def test_blacklist_not_empty(self) -> None:
        """Test that blacklist is not empty."""
        labels = RoomLabels()

        assert len(labels.blacklist) > 0

    def test_synonyms_structure(self) -> None:
        """Test synonyms structure."""
        labels = RoomLabels()

        assert isinstance(labels.synonyms, dict)
        for key, values in labels.synonyms.items():
            assert isinstance(key, str)
            assert isinstance(values, set)


class TestFloorLabels:
    """Tests for FloorLabels."""

    def test_ordinals(self) -> None:
        """Test ordinal floor names."""
        labels = FloorLabels()

        assert "terra" in labels.ordinals
        assert "primo" in labels.ordinals
        assert "secondo" in labels.ordinals
        assert len(labels.ordinals) >= 10


class TestOutputConfig:
    """Tests for OutputConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = OutputConfig()

        assert config.debug_dir == Path("./debug_image")
        assert config.output_dir == Path("./planimetry_output")
        assert config.save_intermediate is True
        assert config.log_level == "INFO"

    def test_custom_paths(self) -> None:
        """Test custom paths."""
        config = OutputConfig(
            debug_dir=Path("/tmp/debug"),
            output_dir=Path("/tmp/output"),
        )

        assert config.debug_dir == Path("/tmp/debug")
        assert config.output_dir == Path("/tmp/output")


class TestPlanParserConfig:
    """Tests for PlanParserConfig."""

    def test_defaults(self) -> None:
        """Test default configuration."""
        config = PlanParserConfig()

        assert isinstance(config.detection, DetectionConfig)
        assert isinstance(config.ocr, OCRConfig)
        assert isinstance(config.rooms, RoomLabels)
        assert isinstance(config.floors, FloorLabels)
        assert isinstance(config.output, OutputConfig)
        assert config.pdf_zoom == 2.0

    def test_nested_access(self) -> None:
        """Test accessing nested configuration."""
        config = PlanParserConfig()

        assert config.detection.min_area == 50
        assert config.ocr.languages == "ita+eng"
        assert "camera" in config.rooms.targets


class TestDefaultConfig:
    """Tests for DEFAULT_CONFIG singleton."""

    def test_exists(self) -> None:
        """Test that DEFAULT_CONFIG exists."""
        assert DEFAULT_CONFIG is not None
        assert isinstance(DEFAULT_CONFIG, PlanParserConfig)

    def test_is_valid(self) -> None:
        """Test that DEFAULT_CONFIG is valid."""
        assert DEFAULT_CONFIG.pdf_zoom > 0
        assert DEFAULT_CONFIG.detection.min_area < DEFAULT_CONFIG.detection.max_area
