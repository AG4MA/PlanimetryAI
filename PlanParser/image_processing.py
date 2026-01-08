"""
Image Processing Utilities
==========================
Computer vision operations for planimetry analysis.
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """Apply CLAHE and unsharp masking for better contrast."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Unsharp mask
    blur = cv2.GaussianBlur(enhanced, (0, 0), 1.2)
    sharpened = cv2.addWeighted(enhanced, 1.5, blur, -0.5, 0)
    
    return sharpened


def preprocess_for_detection(image: np.ndarray) -> np.ndarray:
    """Preprocess image for contour/line detection."""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Bilateral filter to reduce noise while keeping edges
    filtered = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
    
    # Enhance contrast
    enhanced = enhance_contrast(filtered)
    
    return enhanced


def detect_edges(gray: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    """Apply Canny edge detection."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, low, high)
    return edges


def find_largest_rectangle(
    image: np.ndarray,
    min_area_ratio: float = 0.1,
    max_area_ratio: float = 0.95
) -> Optional[Tuple[int, int, int, int]]:
    """
    Find the largest rectangular contour in an image.
    
    Args:
        image: Input image (BGR or grayscale)
        min_area_ratio: Minimum area as fraction of image area
        max_area_ratio: Maximum area as fraction of image area
        
    Returns:
        Bounding box (x, y, w, h) or None if not found
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    img_area = gray.shape[0] * gray.shape[1]
    min_area = int(img_area * min_area_ratio)
    max_area = int(img_area * max_area_ratio)
    
    # Preprocess
    processed = preprocess_for_detection(gray)
    edges = detect_edges(processed)
    
    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_rect = None
    max_found_area = 0
    
    for cnt in contours:
        # Approximate contour to polygon
        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        
        # Check if it's a quadrilateral
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            
            if min_area <= area <= max_area and area > max_found_area:
                # Check aspect ratio is reasonable
                aspect_ratio = max(w, h) / min(w, h) if min(w, h) > 0 else float('inf')
                if aspect_ratio < 5:  # Not too elongated
                    max_found_area = area
                    best_rect = (x, y, w, h)
    
    if best_rect:
        logger.info(f"Found largest rectangle: {best_rect}, area={max_found_area}")
    else:
        logger.warning("No suitable rectangle found")
    
    return best_rect


def find_horizontal_lines(
    image: np.ndarray,
    min_length: int = 100,
    max_gap: int = 10
) -> List[Tuple[int, int, int, int]]:
    """
    Detect horizontal lines in an image using Hough transform.
    
    Returns:
        List of lines as (x1, y1, x2, y2)
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    edges = detect_edges(gray)
    
    # Probabilistic Hough Line Transform
    lines = cv2.HoughLinesP(
        edges, 
        rho=1, 
        theta=np.pi/180, 
        threshold=50,
        minLineLength=min_length, 
        maxLineGap=max_gap
    )
    
    horizontal_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Check if mostly horizontal (angle < 10 degrees)
            angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            if angle < 10 or angle > 170:
                horizontal_lines.append((x1, y1, x2, y2))
    
    # Sort by y-coordinate
    horizontal_lines.sort(key=lambda l: (l[1] + l[3]) / 2)
    
    return horizontal_lines


def find_text_regions(
    image: np.ndarray,
    min_area: int = 50,
    max_area: int = 14000,
    min_aspect_ratio: float = 1.1,
    max_aspect_ratio: float = 22.0,
    min_height: int = 6,
    max_height: int = 64
) -> List[Tuple[int, int, int, int]]:
    """
    Detect potential text regions using morphological operations.
    
    Returns:
        List of bounding boxes (x, y, w, h)
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Enhance contrast
    enhanced = enhance_contrast(gray)
    
    # Top-hat transform to isolate small bright regions (text)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    tophat = cv2.morphologyEx(enhanced, cv2.MORPH_TOPHAT, kernel)
    
    # Threshold
    _, binary = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Dilate to connect text characters
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(binary, dilate_kernel, iterations=1)
    
    # Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h
        aspect_ratio = w / float(h) if h > 0 else float('inf')
        
        # Apply filters
        if (min_area <= area <= max_area and
            min_aspect_ratio <= aspect_ratio <= max_aspect_ratio and
            min_height <= h <= max_height):
            boxes.append((x, y, w, h))
    
    # Sort by position (top-to-bottom, left-to-right)
    boxes.sort(key=lambda b: (b[1], b[0]))
    
    logger.debug(f"Found {len(boxes)} text regions from {len(contours)} contours")
    return boxes


def crop_region(
    image: np.ndarray,
    bbox: Tuple[int, int, int, int],
    padding: int = 0
) -> np.ndarray:
    """Crop a region from an image with optional padding."""
    x, y, w, h = bbox
    height, width = image.shape[:2]
    
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(width, x + w + padding)
    y2 = min(height, y + h + padding)
    
    return image[y1:y2, x1:x2].copy()


def draw_rectangles(
    image: np.ndarray,
    boxes: List[Tuple[int, int, int, int]],
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2
) -> np.ndarray:
    """Draw rectangles on an image."""
    result = image.copy()
    for x, y, w, h in boxes:
        cv2.rectangle(result, (x, y), (x + w, y + h), color, thickness)
    return result


def split_image_horizontally(
    image: np.ndarray,
    y_positions: List[int]
) -> List[np.ndarray]:
    """
    Split an image into horizontal sections at given y-coordinates.
    
    Args:
        image: Input image
        y_positions: List of y-coordinates where to split
        
    Returns:
        List of image sections
    """
    height = image.shape[0]
    
    # Sort and add boundaries
    splits = sorted(set([0] + y_positions + [height]))
    
    sections = []
    for i in range(len(splits) - 1):
        y1, y2 = splits[i], splits[i + 1]
        if y2 > y1:
            section = image[y1:y2, :].copy()
            sections.append(section)
    
    return sections


def detect_green_rectangle(image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect a green-outlined rectangle (drawn by previous processing steps).
    Used to find already-marked regions.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    
    # Green color range
    lower_green = np.array([40, 100, 80], dtype=np.uint8)
    upper_green = np.array([85, 255, 255], dtype=np.uint8)
    
    mask = cv2.inRange(hsv, lower_green, upper_green)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    
    # Find bounding box of green pixels
    ys, xs = np.where(mask > 0)
    
    if xs.size == 0 or ys.size == 0:
        return None
    
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    
    return (x1, y1, x2 - x1, y2 - y1)
