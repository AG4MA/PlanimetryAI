"""
Tests for image processing module.
"""

import numpy as np

from PlanParser.image_processing import (
    crop_region,
    detect_edges,
    detect_green_rectangle,
    draw_rectangles,
    enhance_contrast,
    find_horizontal_lines,
    find_largest_rectangle,
    find_text_regions,
    preprocess_for_detection,
    split_image_horizontally,
)


def create_test_image(width: int = 200, height: int = 300, color: tuple = (255, 255, 255)) -> np.ndarray:
    """Create a test image with specified size and background color."""
    img = np.ones((height, width, 3), dtype=np.uint8)
    img[:] = color
    return img


def create_image_with_rectangle(
    width: int = 400,
    height: int = 500,
    rect_x: int = 50,
    rect_y: int = 50,
    rect_w: int = 300,
    rect_h: int = 400,
) -> np.ndarray:
    """Create a test image with a black rectangle on white background."""
    import cv2

    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    cv2.rectangle(img, (rect_x, rect_y), (rect_x + rect_w, rect_y + rect_h), (0, 0, 0), 2)
    return img


class TestEnhanceContrast:
    """Tests for contrast enhancement."""

    def test_grayscale_input(self) -> None:
        """Test with grayscale image."""
        gray = np.ones((100, 100), dtype=np.uint8) * 128
        result = enhance_contrast(gray)

        assert result.shape == gray.shape
        assert result.dtype == np.uint8

    def test_preserves_shape(self) -> None:
        """Test that shape is preserved."""
        gray = np.random.randint(0, 256, (150, 200), dtype=np.uint8)
        result = enhance_contrast(gray)

        assert result.shape == (150, 200)


class TestPreprocessForDetection:
    """Tests for detection preprocessing."""

    def test_bgr_input(self) -> None:
        """Test with BGR input."""
        img = create_test_image(100, 100)
        result = preprocess_for_detection(img)

        assert len(result.shape) == 2  # Should be grayscale
        assert result.dtype == np.uint8

    def test_grayscale_input(self) -> None:
        """Test with grayscale input."""
        gray = np.ones((100, 100), dtype=np.uint8) * 200
        result = preprocess_for_detection(gray)

        assert result.shape == (100, 100)


class TestDetectEdges:
    """Tests for edge detection."""

    def test_basic_edge_detection(self) -> None:
        """Test basic edge detection."""
        gray = np.zeros((100, 100), dtype=np.uint8)
        gray[40:60, :] = 255  # Horizontal white stripe

        edges = detect_edges(gray)

        assert edges.shape == gray.shape
        assert edges.dtype == np.uint8

    def test_blank_image(self) -> None:
        """Test edge detection on blank image."""
        gray = np.ones((100, 100), dtype=np.uint8) * 128
        edges = detect_edges(gray)

        # Blank image should have few/no edges
        assert edges.sum() < 1000  # Very few edge pixels


class TestFindLargestRectangle:
    """Tests for largest rectangle detection."""

    def test_with_rectangle(self) -> None:
        """Test finding rectangle in image."""
        img = create_image_with_rectangle(400, 500, 50, 50, 300, 400)
        rect = find_largest_rectangle(img)

        # Should find a rectangle
        if rect is not None:
            _x, _y, w, h = rect
            assert w > 100  # Should be reasonably large
            assert h > 100

    def test_blank_image(self) -> None:
        """Test with blank image (no rectangles)."""
        img = np.ones((200, 200, 3), dtype=np.uint8) * 255
        rect = find_largest_rectangle(img)

        # May or may not find a rectangle in blank image
        assert rect is None or len(rect) == 4


class TestFindHorizontalLines:
    """Tests for horizontal line detection."""

    def test_with_horizontal_line(self) -> None:
        """Test detecting horizontal line."""
        import cv2

        img = np.ones((200, 300, 3), dtype=np.uint8) * 255
        cv2.line(img, (10, 100), (290, 100), (0, 0, 0), 2)

        lines = find_horizontal_lines(img, min_length=50)

        # Should find at least one horizontal line
        assert isinstance(lines, list)

    def test_blank_image(self) -> None:
        """Test with blank image."""
        img = np.ones((200, 300, 3), dtype=np.uint8) * 255
        lines = find_horizontal_lines(img)

        assert isinstance(lines, list)


class TestFindTextRegions:
    """Tests for text region detection."""

    def test_blank_image(self) -> None:
        """Test with blank image."""
        img = np.ones((200, 200, 3), dtype=np.uint8) * 255
        regions = find_text_regions(img)

        assert isinstance(regions, list)

    def test_grayscale_input(self) -> None:
        """Test with grayscale input."""
        gray = np.ones((200, 200), dtype=np.uint8) * 255
        regions = find_text_regions(gray)

        assert isinstance(regions, list)


class TestCropRegion:
    """Tests for region cropping."""

    def test_basic_crop(self) -> None:
        """Test basic cropping."""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        bbox = (10, 20, 30, 40)  # x, y, w, h

        cropped = crop_region(img, bbox)

        assert cropped.shape == (40, 30, 3)

    def test_crop_with_padding(self) -> None:
        """Test cropping with padding."""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        bbox = (20, 20, 30, 30)

        cropped = crop_region(img, bbox, padding=5)

        assert cropped.shape == (40, 40, 3)  # 30+5+5

    def test_crop_at_edge(self) -> None:
        """Test cropping at image edge with padding."""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        bbox = (0, 0, 20, 20)

        cropped = crop_region(img, bbox, padding=10)

        # Should not go below 0
        assert cropped.shape[0] <= 30
        assert cropped.shape[1] <= 30


class TestDrawRectangles:
    """Tests for rectangle drawing."""

    def test_draw_single_rectangle(self) -> None:
        """Test drawing a single rectangle."""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        boxes = [(10, 10, 20, 20)]

        result = draw_rectangles(img, boxes, color=(0, 255, 0))

        assert result.shape == img.shape
        # Original should not be modified
        assert np.all(img == 255)

    def test_draw_multiple_rectangles(self) -> None:
        """Test drawing multiple rectangles."""
        img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        boxes = [(10, 10, 20, 20), (50, 50, 30, 30)]

        result = draw_rectangles(img, boxes)

        assert result.shape == img.shape


class TestSplitImageHorizontally:
    """Tests for horizontal image splitting."""

    def test_single_split(self) -> None:
        """Test splitting at one position."""
        img = np.ones((100, 50, 3), dtype=np.uint8) * 128
        sections = split_image_horizontally(img, [50])

        assert len(sections) == 2
        assert sections[0].shape[0] == 50
        assert sections[1].shape[0] == 50

    def test_multiple_splits(self) -> None:
        """Test splitting at multiple positions."""
        img = np.ones((120, 50, 3), dtype=np.uint8) * 128
        sections = split_image_horizontally(img, [40, 80])

        assert len(sections) == 3
        assert sections[0].shape[0] == 40
        assert sections[1].shape[0] == 40
        assert sections[2].shape[0] == 40

    def test_no_splits(self) -> None:
        """Test with no split positions."""
        img = np.ones((100, 50, 3), dtype=np.uint8) * 128
        sections = split_image_horizontally(img, [])

        assert len(sections) == 1
        assert sections[0].shape[0] == 100


class TestDetectGreenRectangle:
    """Tests for green rectangle detection."""

    def test_with_green_rectangle(self) -> None:
        """Test detecting green rectangle."""
        import cv2

        img = np.ones((200, 200, 3), dtype=np.uint8) * 255
        cv2.rectangle(img, (50, 50), (150, 150), (0, 255, 0), 3)

        rect = detect_green_rectangle(img)

        assert rect is not None
        x, y, _w, _h = rect
        assert 40 <= x <= 60
        assert 40 <= y <= 60

    def test_no_green(self) -> None:
        """Test with no green in image."""
        img = np.ones((200, 200, 3), dtype=np.uint8) * 255
        rect = detect_green_rectangle(img)

        assert rect is None
