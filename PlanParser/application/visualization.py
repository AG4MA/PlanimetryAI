"""
Visualization Service
=====================
Handles all drawing and visualization operations.
Extracted from detection classes to follow SRP.
"""

from dataclasses import dataclass
from typing import Any

import cv2

from PlanParser.domain.protocols import ImageArray, DetectionResult


@dataclass(frozen=True)
class VisualStyle:
    """Immutable visualization style configuration."""
    box_color: tuple[int, int, int] = (0, 255, 0)  # BGR
    text_color: tuple[int, int, int] = (0, 0, 0)
    text_bg_color: tuple[int, int, int] = (255, 255, 255)
    line_thickness: int = 2
    font_scale: float = 0.6
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    padding: int = 5


class VisualizationService:
    """
    Service for visualizing detection results.
    Single responsibility: drawing on images.
    """

    def __init__(self, style: VisualStyle | None = None) -> None:
        self.style = style or VisualStyle()

    def draw_detection(
        self,
        image: ImageArray,
        detection: DetectionResult,
        style: VisualStyle | None = None
    ) -> ImageArray:
        """Draw a single detection on image (creates copy)."""
        s = style or self.style
        result = image.copy()
        
        x, y, w, h = detection.bbox
        
        # Draw bounding box
        cv2.rectangle(
            result,
            (x, y),
            (x + w, y + h),
            s.box_color,
            s.line_thickness
        )
        
        # Draw label with background
        label = f"{detection.label} ({detection.confidence:.0%})"
        self._draw_label(result, label, (x, y - 10), s)
        
        return result

    def draw_detections(
        self,
        image: ImageArray,
        detections: list[DetectionResult],
        style: VisualStyle | None = None
    ) -> ImageArray:
        """Draw multiple detections on image (creates copy)."""
        result = image.copy()
        s = style or self.style
        
        for det in detections:
            x, y, w, h = det.bbox
            cv2.rectangle(
                result,
                (x, y),
                (x + w, y + h),
                s.box_color,
                s.line_thickness
            )
            label = f"{det.label} ({det.confidence:.0%})"
            self._draw_label(result, label, (x, y - 10), s)
        
        return result

    def draw_bbox(
        self,
        image: ImageArray,
        bbox: tuple[int, int, int, int],
        label: str = "",
        style: VisualStyle | None = None
    ) -> ImageArray:
        """Draw a bounding box with optional label."""
        s = style or self.style
        result = image.copy()
        
        x, y, w, h = bbox
        cv2.rectangle(result, (x, y), (x + w, y + h), s.box_color, s.line_thickness)
        
        if label:
            self._draw_label(result, label, (x, y - 10), s)
        
        return result

    def draw_bboxes(
        self,
        image: ImageArray,
        bboxes: list[tuple[int, int, int, int]],
        labels: list[str] | None = None,
        style: VisualStyle | None = None
    ) -> ImageArray:
        """Draw multiple bounding boxes with optional labels."""
        result = image.copy()
        s = style or self.style
        labels = labels or [""] * len(bboxes)
        
        for bbox, label in zip(bboxes, labels):
            x, y, w, h = bbox
            cv2.rectangle(result, (x, y), (x + w, y + h), s.box_color, s.line_thickness)
            if label:
                self._draw_label(result, label, (x, y - 10), s)
        
        return result

    def draw_ocr_boxes(
        self,
        image: ImageArray,
        ocr_results: list[Any],  # OCRBox from protocols
        show_confidence: bool = True,
        style: VisualStyle | None = None
    ) -> ImageArray:
        """Draw OCR detection boxes with text."""
        s = style or self.style
        result = image.copy()
        
        for box in ocr_results:
            x, y, w, h = box.x, box.y, box.width, box.height
            cv2.rectangle(result, (x, y), (x + w, y + h), s.box_color, s.line_thickness)
            
            if show_confidence:
                label = f"{box.text} ({box.confidence:.0%})"
            else:
                label = box.text
            
            self._draw_label(result, label, (x, y - 10), s)
        
        return result

    def _draw_label(
        self,
        image: ImageArray,
        text: str,
        position: tuple[int, int],
        style: VisualStyle
    ) -> None:
        """Draw label with background (modifies image in place)."""
        x, y = position
        
        # Get text size
        (text_w, text_h), baseline = cv2.getTextSize(
            text, style.font, style.font_scale, 1
        )
        
        # Draw background rectangle
        cv2.rectangle(
            image,
            (x, y - text_h - style.padding),
            (x + text_w + style.padding * 2, y + baseline),
            style.text_bg_color,
            -1  # Filled
        )
        
        # Draw text
        cv2.putText(
            image,
            text,
            (x + style.padding, y),
            style.font,
            style.font_scale,
            style.text_color,
            1,
            cv2.LINE_AA
        )

    def save_debug_image(
        self,
        image: ImageArray,
        path: str,
        prefix: str = "debug"
    ) -> str:
        """Save debug image and return path."""
        import os
        from datetime import datetime
        
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.png"
        full_path = os.path.join(os.path.dirname(path) or ".", filename)
        
        cv2.imwrite(full_path, image)
        return full_path
