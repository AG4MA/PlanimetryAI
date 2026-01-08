"""
Line Extraction Module
======================
Extracts line segments from planimetry images using Hough transform.
Classifies lines as horizontal, vertical, or diagonal.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LineExtractionConfig:
    """Configuration for line extraction."""
    min_line_length: int = 30
    max_line_gap: int = 10
    canny_low: int = 50
    canny_high: int = 150
    angle_tolerance: float = 10.0  # degrees - lines within this of H/V are classified as such


@dataclass
class ExtractedLine:
    """A detected line segment."""
    x1: int
    y1: int
    x2: int
    y2: int
    angle: float = 0.0  # degrees from horizontal
    length: float = 0.0
    
    def __post_init__(self):
        import math
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        self.length = math.sqrt(dx * dx + dy * dy)
        self.angle = math.degrees(math.atan2(dy, dx))
    
    @property
    def is_horizontal(self) -> bool:
        return abs(self.angle) < 10 or abs(self.angle) > 170
    
    @property
    def is_vertical(self) -> bool:
        return 80 < abs(self.angle) < 100
    
    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass
class LineExtractionResult:
    """Result of line extraction."""
    horizontal_lines: list[ExtractedLine] = field(default_factory=list)
    vertical_lines: list[ExtractedLine] = field(default_factory=list)
    diagonal_lines: list[ExtractedLine] = field(default_factory=list)
    all_lines: list[ExtractedLine] = field(default_factory=list)
    
    @property
    def total_count(self) -> int:
        return len(self.all_lines)


class LineExtractor:
    """
    Extracts and classifies line segments from planimetry images.
    
    Uses Canny edge detection followed by Probabilistic Hough Transform.
    """
    
    def __init__(self, config: LineExtractionConfig | None = None):
        self.config = config or LineExtractionConfig()
    
    def extract(self, image: np.ndarray) -> LineExtractionResult:
        """
        Extract lines from an image.
        
        Args:
            image: BGR or grayscale image
            
        Returns:
            LineExtractionResult with classified lines
        """
        result = LineExtractionResult()
        
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Apply Gaussian blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Canny edge detection
        edges = cv2.Canny(
            blurred, 
            self.config.canny_low, 
            self.config.canny_high
        )
        
        # Probabilistic Hough Line Transform
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=50,
            minLineLength=self.config.min_line_length,
            maxLineGap=self.config.max_line_gap
        )
        
        if lines is None:
            logger.warning("No lines detected")
            return result
        
        # Classify lines
        for line in lines:
            x1, y1, x2, y2 = line[0]
            extracted = ExtractedLine(x1=x1, y1=y1, x2=x2, y2=y2)
            result.all_lines.append(extracted)
            
            if extracted.is_horizontal:
                result.horizontal_lines.append(extracted)
            elif extracted.is_vertical:
                result.vertical_lines.append(extracted)
            else:
                result.diagonal_lines.append(extracted)
        
        logger.info(f"Extracted {len(result.all_lines)} lines: "
                   f"H={len(result.horizontal_lines)}, "
                   f"V={len(result.vertical_lines)}, "
                   f"D={len(result.diagonal_lines)}")
        
        return result
    
    def visualize(
        self, 
        image: np.ndarray, 
        result: LineExtractionResult,
        output_path: str | Path | None = None
    ) -> np.ndarray:
        """Create visualization of extracted lines."""
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()
        
        # Draw horizontal lines in green
        for line in result.horizontal_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (0, 255, 0), 2)
        
        # Draw vertical lines in blue
        for line in result.vertical_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (255, 0, 0), 2)
        
        # Draw diagonal lines in red
        for line in result.diagonal_lines:
            cv2.line(vis, (line.x1, line.y1), (line.x2, line.y2), (0, 0, 255), 1)
        
        # Add legend
        cv2.putText(vis, f"H:{len(result.horizontal_lines)}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(vis, f"V:{len(result.vertical_lines)}", (10, 55),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        cv2.putText(vis, f"D:{len(result.diagonal_lines)}", (10, 80),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), vis)
            logger.info(f"Saved line visualization to: {output_path}")
        
        return vis
    
    def save_debug_images(
        self, 
        image: np.ndarray, 
        output_dir: str | Path
    ) -> None:
        """Save intermediate debug images."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        cv2.imwrite(str(output_dir / "01_gray.png"), gray)
        
        # Blurred
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        cv2.imwrite(str(output_dir / "02_blurred.png"), blurred)
        
        # Edges
        edges = cv2.Canny(blurred, self.config.canny_low, self.config.canny_high)
        cv2.imwrite(str(output_dir / "03_edges.png"), edges)
        
        logger.info(f"Saved debug images to: {output_dir}")
