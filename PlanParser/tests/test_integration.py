"""
Integration tests for PlanParser.

These tests require sample files and may take longer to run.
Note: EasyOCR has compatibility issues with Python 3.14 alpha, so these tests
may crash due to PyTorch quantization issues.
"""

import sys
from pathlib import Path

import pytest

from PlanParser import PlanParser, PlanParserConfig, parse_planimetry

# Mark all tests in this module as integration tests
# Skip on Python 3.14+ due to EasyOCR/PyTorch compatibility issues
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.version_info >= (3, 14),
        reason="EasyOCR has compatibility issues with Python 3.14 alpha"
    ),
]


@pytest.fixture
def sample_pdf_path() -> Path:
    """Get path to sample PDF."""
    return Path(__file__).parent.parent / "data" / "scheda_catastale.pdf"


@pytest.fixture
def parser() -> PlanParser:
    """Create a parser instance."""
    config = PlanParserConfig()
    config.output.save_intermediate = False  # Don't save debug images in tests
    return PlanParser(config)


class TestPlanParserIntegration:
    """Integration tests for PlanParser."""

    def test_parse_sample_pdf(self, parser: PlanParser, sample_pdf_path: Path) -> None:
        """Test parsing sample PDF."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")

        result = parser.parse(sample_pdf_path)

        assert result.success is True
        assert len(result.floors) >= 1
        assert result.source_file == str(sample_pdf_path)

    def test_parse_result_structure(self, parser: PlanParser, sample_pdf_path: Path) -> None:
        """Test parse result structure."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")

        result = parser.parse(sample_pdf_path)

        assert hasattr(result, "success")
        assert hasattr(result, "floors")
        assert hasattr(result, "metadata")
        assert hasattr(result, "errors")

    def test_parse_result_to_json(self, parser: PlanParser, sample_pdf_path: Path) -> None:
        """Test JSON serialization."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")

        result = parser.parse(sample_pdf_path)
        json_str = result.to_json()

        assert isinstance(json_str, str)
        assert '"success"' in json_str
        assert '"floors"' in json_str

    def test_parse_nonexistent_file(self, parser: PlanParser) -> None:
        """Test parsing nonexistent file."""
        result = parser.parse(Path("nonexistent.pdf"))

        assert result.success is False
        assert len(result.errors) > 0


class TestConvenienceFunction:
    """Tests for parse_planimetry convenience function."""

    def test_convenience_function(self, sample_pdf_path: Path) -> None:
        """Test the convenience function."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")

        result = parse_planimetry(sample_pdf_path)

        assert result is not None
        assert hasattr(result, "success")
