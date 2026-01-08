"""
Room Polygon Detection
======================
Detects room polygons using region growing from OCR label positions.

Approach:
1. Binarize image (walls = black, spaces = white)
2. Find connected white regions (potential rooms)  
3. Match OCR labels to regions (which region contains the label point?)
4. Extract contour of each matched region → room polygon

This is much more robust than trying to construct polygons from line segments.
"""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RoomPolygon:
    """A detected room with its polygon boundary."""
    label: str
    label_position: tuple[int, int]  # Where the OCR text was found
    contour: np.ndarray  # OpenCV contour (Nx1x2 array)
    
    # Computed properties
    area_pixels: float = 0.0
    perimeter_pixels: float = 0.0
    bounding_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    centroid: tuple[int, int] = (0, 0)
    
    # Simplified polygon (fewer vertices)
    simplified_contour: np.ndarray | None = None
    vertices: list[tuple[int, int]] = field(default_factory=list)
    
    def __post_init__(self):
        """Compute derived properties."""
        if self.contour is not None and len(self.contour) > 0:
            self.area_pixels = cv2.contourArea(self.contour)
            self.perimeter_pixels = cv2.arcLength(self.contour, closed=True)
            self.bounding_box = cv2.boundingRect(self.contour)
            
            # Compute centroid using moments
            M = cv2.moments(self.contour)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                self.centroid = (cx, cy)
            else:
                # Fallback to bounding box center
                x, y, w, h = self.bounding_box
                self.centroid = (x + w // 2, y + h // 2)
            
            # Simplify contour (Douglas-Peucker)
            epsilon = 0.01 * self.perimeter_pixels
            self.simplified_contour = cv2.approxPolyDP(self.contour, epsilon, closed=True)
            
            # Extract vertices as list of tuples
            self.vertices = [(int(p[0][0]), int(p[0][1])) for p in self.simplified_contour]
    
    def area_m2(self, pixels_per_meter: float) -> float:
        """Convert area to square meters."""
        if pixels_per_meter <= 0:
            return 0.0
        return self.area_pixels / (pixels_per_meter ** 2)
    
    def perimeter_m(self, pixels_per_meter: float) -> float:
        """Convert perimeter to meters."""
        if pixels_per_meter <= 0:
            return 0.0
        return self.perimeter_pixels / pixels_per_meter
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "label": self.label,
            "label_position": self.label_position,
            "centroid": self.centroid,
            "bounding_box": self.bounding_box,
            "area_pixels": self.area_pixels,
            "perimeter_pixels": self.perimeter_pixels,
            "vertices": self.vertices,
            "vertex_count": len(self.vertices)
        }


@dataclass
class RegionGrowingResult:
    """Result of room polygon detection."""
    rooms: list[RoomPolygon] = field(default_factory=list)
    unmatched_labels: list[tuple[str, tuple[int, int]]] = field(default_factory=list)
    total_regions_found: int = 0
    image_width: int = 0
    image_height: int = 0


@dataclass  
class RegionGrowingConfig:
    """Configuration for region growing algorithm."""
    # Binarization
    binary_threshold: int = 200  # Pixels brighter than this = white (room)
    use_adaptive: bool = True    # Use adaptive thresholding
    adaptive_block_size: int = 51
    adaptive_c: int = 10
    
    # Morphological operations
    wall_thickness_px: int = 3   # Dilate walls by this amount
    close_gaps: bool = True      # Close small gaps in walls
    gap_close_size: int = 5
    
    # Region filtering
    min_room_area: int = 1000    # Minimum room area in pixels
    max_room_area_ratio: float = 0.5  # Max room as ratio of image
    
    # Contour simplification
    simplify_epsilon_ratio: float = 0.01  # Douglas-Peucker epsilon as ratio of perimeter


class RoomPolygonDetector:
    """
    Detects room polygons using region growing from OCR label positions.
    
    This approach is more robust than line-based polygon construction because:
    1. We already have "seeds" (OCR labels with positions)
    2. Walls naturally separate regions
    3. No need to reconstruct complex topologies from line segments
    """
    
    def __init__(self, config: RegionGrowingConfig | None = None):
        self.config = config or RegionGrowingConfig()
    
    def detect(
        self,
        image: np.ndarray,
        labels: list[tuple[str, tuple[int, int]]]  # [(label_text, (x, y)), ...]
    ) -> RegionGrowingResult:
        """
        Detect room polygons by growing from label positions.
        
        Args:
            image: BGR or grayscale image
            labels: List of (label_text, (x, y)) from OCR detection
            
        Returns:
            RegionGrowingResult with detected room polygons
        """
        result = RegionGrowingResult()
        result.image_height, result.image_width = image.shape[:2]
        
        # Step 1: Binarize - walls black, rooms white
        binary = self._binarize(image)
        
        # Step 2: Find all connected white regions
        regions, labeled_image, num_regions = self._find_regions(binary)
        result.total_regions_found = num_regions
        logger.info(f"Found {num_regions} connected regions")
        
        # Step 3: Match labels to regions
        for label_text, (lx, ly) in labels:
            # Which region contains this point?
            if 0 <= ly < labeled_image.shape[0] and 0 <= lx < labeled_image.shape[1]:
                region_id = labeled_image[ly, lx]
                
                if region_id > 0 and region_id in regions:
                    contour = regions[region_id]
                    
                    # Create room polygon
                    room = RoomPolygon(
                        label=label_text,
                        label_position=(lx, ly),
                        contour=contour
                    )
                    
                    # Filter by area
                    if room.area_pixels >= self.config.min_room_area:
                        max_area = self.config.max_room_area_ratio * result.image_width * result.image_height
                        if room.area_pixels <= max_area:
                            result.rooms.append(room)
                            logger.debug(f"Matched '{label_text}' to region {region_id} "
                                       f"(area={room.area_pixels:.0f}px, vertices={len(room.vertices)})")
                        else:
                            logger.debug(f"Region for '{label_text}' too large (area={room.area_pixels:.0f}px)")
                    else:
                        logger.debug(f"Region for '{label_text}' too small (area={room.area_pixels:.0f}px)")
                else:
                    # Label is on a wall or outside
                    result.unmatched_labels.append((label_text, (lx, ly)))
                    logger.debug(f"Label '{label_text}' at ({lx},{ly}) is on wall or outside")
            else:
                result.unmatched_labels.append((label_text, (lx, ly)))
        
        logger.info(f"Matched {len(result.rooms)} rooms, {len(result.unmatched_labels)} unmatched labels")
        
        return result
    
    def _binarize(self, image: np.ndarray) -> np.ndarray:
        """
        Binarize image: walls = 0 (black), rooms = 255 (white).
        """
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # Binarize
        if self.config.use_adaptive:
            # Adaptive thresholding works better for varying lighting
            binary = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                self.config.adaptive_block_size,
                self.config.adaptive_c
            )
        else:
            _, binary = cv2.threshold(gray, self.config.binary_threshold, 255, cv2.THRESH_BINARY)
        
        # Invert if needed (we want walls=black, rooms=white)
        # Planimetry walls are usually dark lines on white background
        # After thresholding, walls should be black (0)
        
        # Close small gaps in walls
        if self.config.close_gaps:
            kernel = np.ones((self.config.gap_close_size, self.config.gap_close_size), np.uint8)
            # Erode white regions (shrink rooms) to close gaps
            binary = cv2.erode(binary, kernel, iterations=1)
            # Dilate back
            binary = cv2.dilate(binary, kernel, iterations=1)
        
        # Thicken walls slightly
        if self.config.wall_thickness_px > 0:
            kernel = np.ones((self.config.wall_thickness_px, self.config.wall_thickness_px), np.uint8)
            # Erode white = thicken black walls
            binary = cv2.erode(binary, kernel, iterations=1)
        
        return binary
    
    def _find_regions(self, binary: np.ndarray) -> tuple[dict[int, np.ndarray], np.ndarray, int]:
        """
        Find connected white regions and their contours.
        
        Returns:
            (regions_dict, labeled_image, num_regions)
            - regions_dict: {region_id: contour}
            - labeled_image: image where each pixel has its region ID
            - num_regions: total number of regions found
        """
        # Find connected components
        num_labels, labeled_image, stats, centroids = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        
        # Find contours for each region
        regions = {}
        
        for region_id in range(1, num_labels):  # Skip 0 (background/walls)
            # Create mask for this region
            mask = (labeled_image == region_id).astype(np.uint8) * 255
            
            # Find contour
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                # Take the largest contour (there should only be one)
                regions[region_id] = max(contours, key=cv2.contourArea)
        
        return regions, labeled_image, num_labels - 1  # -1 to exclude background
    
    def visualize(
        self,
        image: np.ndarray,
        result: RegionGrowingResult,
        output_path: str | Path | None = None,
        show_labels: bool = True,
        show_vertices: bool = True
    ) -> np.ndarray:
        """
        Create visualization of detected room polygons.
        """
        # Create copy for drawing
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()
        
        # Generate colors for each room
        colors = [
            (0, 255, 0),    # Green
            (255, 0, 0),    # Blue
            (0, 255, 255),  # Yellow
            (255, 0, 255),  # Magenta
            (255, 255, 0),  # Cyan
            (0, 165, 255),  # Orange
            (147, 20, 255), # Pink
            (0, 128, 0),    # Dark green
        ]
        
        for i, room in enumerate(result.rooms):
            color = colors[i % len(colors)]
            
            # Draw filled polygon with transparency
            overlay = vis.copy()
            cv2.fillPoly(overlay, [room.simplified_contour], color)
            cv2.addWeighted(overlay, 0.3, vis, 0.7, 0, vis)
            
            # Draw contour outline
            cv2.drawContours(vis, [room.simplified_contour], -1, color, 2)
            
            # Draw vertices
            if show_vertices:
                for vx, vy in room.vertices:
                    cv2.circle(vis, (vx, vy), 4, color, -1)
            
            # Draw label
            if show_labels:
                cx, cy = room.centroid
                label_text = f"{room.label}"
                
                # Background for text
                (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(vis, (cx - tw//2 - 2, cy - th - 2), (cx + tw//2 + 2, cy + 2), (255, 255, 255), -1)
                cv2.putText(vis, label_text, (cx - tw//2, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # Draw unmatched labels in red
        for label_text, (lx, ly) in result.unmatched_labels:
            cv2.circle(vis, (lx, ly), 5, (0, 0, 255), -1)
            cv2.putText(vis, f"?{label_text}", (lx + 5, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        
        # Add legend
        y_offset = 30
        cv2.putText(vis, f"Rooms: {len(result.rooms)}", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(vis, f"Unmatched: {len(result.unmatched_labels)}", (10, y_offset + 25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(vis, f"Regions: {result.total_regions_found}", (10, y_offset + 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        if output_path:
            cv2.imwrite(str(output_path), vis)
            logger.info(f"Saved polygon visualization to: {output_path}")
        
        return vis
    
    def visualize_binary(
        self,
        image: np.ndarray,
        output_path: str | Path | None = None
    ) -> np.ndarray:
        """Visualize the binarized image (for debugging)."""
        binary = self._binarize(image)
        
        if output_path:
            cv2.imwrite(str(output_path), binary)
            logger.info(f"Saved binary visualization to: {output_path}")
        
        return binary
