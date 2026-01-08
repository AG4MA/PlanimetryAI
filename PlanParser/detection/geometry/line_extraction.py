"""
Line Extraction Module
======================
Extracts line segments from planimetry images using computer vision.

This is the foundation for wall detection - walls are typically
parallel line pairs with small distance between them.
"""

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class LineOrientation(Enum):
    """Line orientation classification."""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    DIAGONAL = "diagonal"


@dataclass
class ExtractedLine:
    """A detected line segment."""
    x1: int
    y1: int
    x2: int
    y2: int
    
    # Computed properties
    length: float = 0.0
    angle_degrees: float = 0.0
    orientation: LineOrientation = LineOrientation.DIAGONAL
    
    def __post_init__(self):
        """Compute derived properties."""
        self.length = math.hypot(self.x2 - self.x1, self.y2 - self.y1)
        self.angle_degrees = math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1))
        
        # Normalize angle to 0-180 (lines don't have direction)
        if self.angle_degrees < 0:
            self.angle_degrees += 180
        
        # Classify orientation
        if abs(self.angle_degrees) < 10 or abs(self.angle_degrees - 180) < 10:
            self.orientation = LineOrientation.HORIZONTAL
        elif abs(self.angle_degrees - 90) < 10:
            self.orientation = LineOrientation.VERTICAL
        else:
            self.orientation = LineOrientation.DIAGONAL
    
    @property
    def midpoint(self) -> tuple[float, float]:
        """Return midpoint of line."""
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)
    
    @property
    def as_tuple(self) -> tuple[int, int, int, int]:
        """Return as (x1, y1, x2, y2) tuple."""
        return (self.x1, self.y1, self.x2, self.y2)
    
    def distance_to_point(self, px: float, py: float) -> float:
        """Calculate perpendicular distance from point to line."""
        # Line vector
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        
        # Vector from line start to point
        t = max(0, min(1, ((px - self.x1) * dx + (py - self.y1) * dy) / (dx * dx + dy * dy + 1e-9)))
        
        # Closest point on line segment
        closest_x = self.x1 + t * dx
        closest_y = self.y1 + t * dy
        
        return math.hypot(px - closest_x, py - closest_y)


@dataclass
class LineExtractionResult:
    """Result of line extraction."""
    lines: list[ExtractedLine] = field(default_factory=list)
    horizontal_lines: list[ExtractedLine] = field(default_factory=list)
    vertical_lines: list[ExtractedLine] = field(default_factory=list)
    diagonal_lines: list[ExtractedLine] = field(default_factory=list)
    
    # Statistics
    total_count: int = 0
    image_width: int = 0
    image_height: int = 0
    
    def __post_init__(self):
        """Categorize lines by orientation."""
        if self.lines and not self.horizontal_lines:
            for line in self.lines:
                if line.orientation == LineOrientation.HORIZONTAL:
                    self.horizontal_lines.append(line)
                elif line.orientation == LineOrientation.VERTICAL:
                    self.vertical_lines.append(line)
                else:
                    self.diagonal_lines.append(line)
        self.total_count = len(self.lines)


@dataclass
class LineExtractionConfig:
    """Configuration for line extraction."""
    # Canny edge detection
    canny_low: int = 20          # Very low for maximum sensitivity
    canny_high: int = 80         # Lower for more edges
    
    # Hough transform parameters
    hough_threshold: int = 15    # Very low - fewer votes needed
    min_line_length: int = 10    # Very short lines allowed
    max_line_gap: int = 20       # Large gaps bridged
    
    # Filtering
    min_length_ratio: float = 0.005  # Almost no minimum
    merge_distance: int = 5          # Less aggressive merge
    merge_angle: float = 5.0         # Stricter angle matching
    
    # Aggressive mode
    aggressive: bool = True         # Use even more sensitive params
    multi_scale: bool = True        # Use multiple preprocessing scales


class LineExtractor:
    """
    Extracts line segments from planimetry images.
    
    Uses Hough Line Transform with preprocessing optimized for
    architectural drawings.
    """
    
    def __init__(self, config: LineExtractionConfig | None = None):
        self.config = config or LineExtractionConfig()
    
    def extract(self, image: np.ndarray) -> LineExtractionResult:
        """
        Extract all line segments from image.
        
        Args:
            image: BGR or grayscale image
            
        Returns:
            LineExtractionResult with detected lines
        """
        result = LineExtractionResult()
        result.image_height, result.image_width = image.shape[:2]
        
        all_lines = []
        
        # Multi-scale approach: extract at different preprocessing levels
        if self.config.multi_scale:
            # 1. Standard preprocessing
            preprocessed = self._preprocess(image)
            edges1 = self._detect_edges(preprocessed)
            lines1 = self._hough_lines(edges1)
            if lines1 is not None:
                all_lines.extend(lines1)
            
            # 2. High contrast (for faint lines)
            high_contrast = self._preprocess_high_contrast(image)
            edges2 = self._detect_edges(high_contrast)
            lines2 = self._hough_lines(edges2)
            if lines2 is not None:
                all_lines.extend(lines2)
            
            # 3. Adaptive threshold (for varying lighting)
            adaptive = self._preprocess_adaptive(image)
            edges3 = self._detect_edges_from_binary(adaptive)
            lines3 = self._hough_lines(edges3)
            if lines3 is not None:
                all_lines.extend(lines3)
            
            # 4. Morphological approach (for thick lines)
            morph = self._preprocess_morphological(image)
            edges4 = self._detect_edges_from_binary(morph)
            lines4 = self._hough_lines(edges4)
            if lines4 is not None:
                all_lines.extend(lines4)
            
            logger.info(f"Multi-scale extraction: {len(all_lines)} total raw lines")
        else:
            preprocessed = self._preprocess(image)
            edges = self._detect_edges(preprocessed)
            raw_lines = self._hough_lines(edges)
            if raw_lines is not None:
                all_lines = list(raw_lines)
        
        if not all_lines:
            logger.warning("No lines detected")
            return result
        
        logger.info(f"Raw Hough lines detected: {len(all_lines)}")
        
        # Convert to ExtractedLine objects
        lines = []
        for line in all_lines:
            x1, y1, x2, y2 = line[0]
            extracted = ExtractedLine(x1, y1, x2, y2)
            lines.append(extracted)
        
        # Filter short lines
        min_length = self.config.min_length_ratio * math.hypot(result.image_width, result.image_height)
        lines = [l for l in lines if l.length >= min_length]
        logger.info(f"After length filter (>{min_length:.1f}px): {len(lines)}")
        
        # Remove duplicates first
        lines = self._remove_duplicates(lines)
        logger.info(f"After removing duplicates: {len(lines)}")
        
        # Merge similar lines
        lines = self._merge_similar_lines(lines)
        logger.info(f"After merging similar: {len(lines)}")
        
        result.lines = lines
        result.__post_init__()  # Recategorize
        
        logger.info(f"Extracted lines: {result.total_count} total "
                   f"(H:{len(result.horizontal_lines)}, V:{len(result.vertical_lines)}, D:{len(result.diagonal_lines)})")
        
        return result
    
    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for line detection."""
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Denoise while preserving edges
        denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
        
        # Enhance contrast with CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)
        
        return enhanced
    
    def _preprocess_high_contrast(self, image: np.ndarray) -> np.ndarray:
        """High contrast preprocessing for faint lines."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # More aggressive CLAHE
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(gray)
        
        # Sharpen
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        
        return sharpened
    
    def _preprocess_adaptive(self, image: np.ndarray) -> np.ndarray:
        """Adaptive thresholding for varying contrast."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Gaussian blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Adaptive threshold - captures lines regardless of local brightness
        binary = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,  # Invert so lines are white
            blockSize=11,
            C=2
        )
        
        return binary
    
    def _preprocess_morphological(self, image: np.ndarray) -> np.ndarray:
        """Morphological preprocessing to extract lines."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Binary threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Horizontal lines
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
        
        # Vertical lines
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
        
        # Combine
        combined = cv2.bitwise_or(horizontal, vertical)
        
        # Add some dilation to connect
        kernel = np.ones((2, 2), np.uint8)
        combined = cv2.dilate(combined, kernel, iterations=1)
        
        return combined
    
    def _detect_edges_from_binary(self, binary: np.ndarray) -> np.ndarray:
        """Get edges from an already binarized image."""
        # For binary images, just find contours/edges
        edges = cv2.Canny(binary, 50, 150)
        return edges
    
    def _remove_duplicates(self, lines: list[ExtractedLine], tolerance: int = 3) -> list[ExtractedLine]:
        """Remove duplicate lines from multi-scale extraction."""
        if not lines:
            return lines
        
        unique = []
        for line in lines:
            is_dup = False
            for existing in unique:
                # Check if endpoints are very close
                d1 = math.hypot(line.x1 - existing.x1, line.y1 - existing.y1)
                d2 = math.hypot(line.x2 - existing.x2, line.y2 - existing.y2)
                d3 = math.hypot(line.x1 - existing.x2, line.y1 - existing.y2)
                d4 = math.hypot(line.x2 - existing.x1, line.y2 - existing.y1)
                
                if (d1 < tolerance and d2 < tolerance) or (d3 < tolerance and d4 < tolerance):
                    is_dup = True
                    break
            
            if not is_dup:
                unique.append(line)
        
        return unique
    
    def _detect_edges(self, gray: np.ndarray) -> np.ndarray:
        """Detect edges using Canny."""
        # Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Canny edge detection
        edges = cv2.Canny(blurred, self.config.canny_low, self.config.canny_high)
        
        # Dilate slightly to connect broken edges
        kernel = np.ones((2, 2), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        return edges
    
    def _hough_lines(self, edges: np.ndarray) -> np.ndarray | None:
        """Apply probabilistic Hough Line Transform."""
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self.config.hough_threshold,
            minLineLength=self.config.min_line_length,
            maxLineGap=self.config.max_line_gap
        )
        return lines
    
    def _merge_similar_lines(self, lines: list[ExtractedLine]) -> list[ExtractedLine]:
        """Merge lines that are very close and parallel."""
        if not lines:
            return lines
        
        merged = []
        used = set()
        
        for i, line1 in enumerate(lines):
            if i in used:
                continue
            
            # Find lines to merge with this one
            to_merge = [line1]
            
            for j, line2 in enumerate(lines[i+1:], start=i+1):
                if j in used:
                    continue
                
                # Check if lines are parallel (similar angle)
                angle_diff = abs(line1.angle_degrees - line2.angle_degrees)
                if angle_diff > 90:
                    angle_diff = 180 - angle_diff
                
                if angle_diff > self.config.merge_angle:
                    continue
                
                # Check if lines are close
                mid1 = line1.midpoint
                mid2 = line2.midpoint
                
                dist = math.hypot(mid1[0] - mid2[0], mid1[1] - mid2[1])
                
                if dist < self.config.merge_distance + (line1.length + line2.length) / 4:
                    to_merge.append(line2)
                    used.add(j)
            
            # Merge by taking extreme points
            if len(to_merge) > 1:
                all_points = []
                for l in to_merge:
                    all_points.extend([(l.x1, l.y1), (l.x2, l.y2)])
                
                # Find the two points that are furthest apart
                max_dist = 0
                best_pair = (all_points[0], all_points[1])
                for p1 in all_points:
                    for p2 in all_points:
                        d = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
                        if d > max_dist:
                            max_dist = d
                            best_pair = (p1, p2)
                
                merged_line = ExtractedLine(
                    int(best_pair[0][0]), int(best_pair[0][1]),
                    int(best_pair[1][0]), int(best_pair[1][1])
                )
                merged.append(merged_line)
            else:
                merged.append(line1)
            
            used.add(i)
        
        return merged
    
    def visualize(
        self,
        image: np.ndarray,
        result: LineExtractionResult,
        output_path: str | Path | None = None
    ) -> np.ndarray:
        """
        Create visualization of extracted lines.
        
        Color coding:
        - Green: Horizontal lines
        - Blue: Vertical lines
        - Red: Diagonal lines
        """
        # Create copy for drawing
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()
        
        # Draw lines with color coding
        for line in result.horizontal_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (0, 255, 0), 2)  # Green
        
        for line in result.vertical_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (255, 0, 0), 2)  # Blue
        
        for line in result.diagonal_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (0, 0, 255), 2)  # Red
        
        # Add legend
        cv2.putText(vis, f"H:{len(result.horizontal_lines)}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(vis, f"V:{len(result.vertical_lines)}", (10, 55), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        cv2.putText(vis, f"D:{len(result.diagonal_lines)}", (10, 80), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(vis, f"Total:{result.total_count}", (10, 105), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        if output_path:
            cv2.imwrite(str(output_path), vis)
            logger.info(f"Saved line visualization to: {output_path}")
        
        return vis
    
    def save_debug_images(self, image: np.ndarray, output_dir: str | Path) -> None:
        """Save all preprocessing stages for debugging."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Standard preprocessing
        preprocessed = self._preprocess(image)
        cv2.imwrite(str(output_dir / "01_preprocessed.png"), preprocessed)
        
        edges1 = self._detect_edges(preprocessed)
        cv2.imwrite(str(output_dir / "02_edges_standard.png"), edges1)
        
        # 2. High contrast
        high_contrast = self._preprocess_high_contrast(image)
        cv2.imwrite(str(output_dir / "03_high_contrast.png"), high_contrast)
        
        edges2 = self._detect_edges(high_contrast)
        cv2.imwrite(str(output_dir / "04_edges_high_contrast.png"), edges2)
        
        # 3. Adaptive threshold
        adaptive = self._preprocess_adaptive(image)
        cv2.imwrite(str(output_dir / "05_adaptive_threshold.png"), adaptive)
        
        edges3 = self._detect_edges_from_binary(adaptive)
        cv2.imwrite(str(output_dir / "06_edges_adaptive.png"), edges3)
        
        # 4. Morphological
        morph = self._preprocess_morphological(image)
        cv2.imwrite(str(output_dir / "07_morphological.png"), morph)
        
        edges4 = self._detect_edges_from_binary(morph)
        cv2.imwrite(str(output_dir / "08_edges_morphological.png"), edges4)
        
        # Combined edges
        combined = cv2.bitwise_or(edges1, edges2)
        combined = cv2.bitwise_or(combined, edges3)
        combined = cv2.bitwise_or(combined, edges4)
        cv2.imwrite(str(output_dir / "09_edges_combined.png"), combined)
        
        logger.info(f"Saved {9} debug images to: {output_dir}")


def extract_lines_from_image(
    image_path: str | Path,
    output_path: str | Path | None = None,
    config: LineExtractionConfig | None = None
) -> LineExtractionResult:
    """
    Convenience function to extract lines from an image file.
    
    Args:
        image_path: Path to image file
        output_path: Optional path to save visualization
        config: Optional extraction configuration
        
    Returns:
        LineExtractionResult
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    extractor = LineExtractor(config)
    result = extractor.extract(image)
    
    if output_path:
        extractor.visualize(image, result, output_path)
    
    return result
