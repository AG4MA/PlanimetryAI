"""
Floor Detection Module
======================
Detects floor labels and splits planimetry into floor sections.
"""

import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

from PlanParser.domain.text_utils import normalize_text
from PlanParser.infrastructure.ocr.engine import OCRManager

logger = logging.getLogger(__name__)


@dataclass
class FloorSection:
    """Represents a detected floor section."""
    floor_label: str
    floor_number: int  # 0 = ground floor, 1 = first floor, etc.
    image: np.ndarray
    y_start: int
    y_end: int
    confidence: float


class FloorDetector:
    """
    Detects floor labels in planimetry and splits into sections.
    """

    # Italian floor patterns
    FLOOR_PATTERNS = [
        # Ground floor
        (r"\bpiano[\s._-]*terra\b", "Piano Terra", 0, 1.0),
        (r"\bp[\s._-]*\.?[\s._-]*terra\b", "Piano Terra", 0, 0.95),
        (r"\bpt\b", "Piano Terra", 0, 0.8),

        # Ordinal floors
        (r"\bprimo[\s._-]*piano\b", "Primo Piano", 1, 1.0),
        (r"\bsecondo[\s._-]*piano\b", "Secondo Piano", 2, 1.0),
        (r"\bterzo[\s._-]*piano\b", "Terzo Piano", 3, 1.0),
        (r"\bquarto[\s._-]*piano\b", "Quarto Piano", 4, 1.0),
        (r"\bquinto[\s._-]*piano\b", "Quinto Piano", 5, 1.0),
        (r"\bsesto[\s._-]*piano\b", "Sesto Piano", 6, 1.0),
        (r"\bsettimo[\s._-]*piano\b", "Settimo Piano", 7, 1.0),
        (r"\bottavo[\s._-]*piano\b", "Ottavo Piano", 8, 1.0),
        (r"\bnono[\s._-]*piano\b", "Nono Piano", 9, 1.0),
        (r"\bdecimo[\s._-]*piano\b", "Decimo Piano", 10, 1.0),

        # "Piano + ordinal" format
        (r"\bpiano[\s._-]*primo\b", "Primo Piano", 1, 0.95),
        (r"\bpiano[\s._-]*secondo\b", "Secondo Piano", 2, 0.95),
        (r"\bpiano[\s._-]*terzo\b", "Terzo Piano", 3, 0.95),
        (r"\bpiano[\s._-]*quarto\b", "Quarto Piano", 4, 0.95),
        (r"\bpiano[\s._-]*quinto\b", "Quinto Piano", 5, 0.95),

        # Numeric formats
        (r"\b1[°º]?[\s._-]*piano\b", "Primo Piano", 1, 0.9),
        (r"\b2[°º]?[\s._-]*piano\b", "Secondo Piano", 2, 0.9),
        (r"\b3[°º]?[\s._-]*piano\b", "Terzo Piano", 3, 0.9),
        (r"\b4[°º]?[\s._-]*piano\b", "Quarto Piano", 4, 0.9),
        (r"\b5[°º]?[\s._-]*piano\b", "Quinto Piano", 5, 0.9),

        # "Piano + number" format
        (r"\bpiano[\s._-]*1[°º]?\b", "Primo Piano", 1, 0.85),
        (r"\bpiano[\s._-]*2[°º]?\b", "Secondo Piano", 2, 0.85),
        (r"\bpiano[\s._-]*3[°º]?\b", "Terzo Piano", 3, 0.85),
        (r"\bpiano[\s._-]*4[°º]?\b", "Quarto Piano", 4, 0.85),
        (r"\bpiano[\s._-]*5[°º]?\b", "Quinto Piano", 5, 0.85),

        # Basement
        (r"\bseminterrato\b", "Seminterrato", -1, 1.0),
        (r"\binterrato\b", "Interrato", -1, 0.95),
        (r"\bcantina\b", "Cantina", -1, 0.9),

        # Attic
        (r"\bsottotetto\b", "Sottotetto", 99, 1.0),
        (r"\bmansarda\b", "Mansarda", 99, 0.95),
    ]

    def __init__(self, ocr_manager: OCRManager):
        self.ocr = ocr_manager
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), label, num, conf)
            for pattern, label, num, conf in self.FLOOR_PATTERNS
        ]

    def detect_floor_labels(
        self,
        image: np.ndarray
    ) -> list[tuple[str, int, int, float, tuple[int, int, int, int]]]:
        """
        Detect floor labels in an image.

        Returns:
            List of (label, floor_number, y_position, confidence, bbox)
        """
        # Get OCR results with bounding boxes
        results = self.ocr.recognize(image)

        # Group nearby words (same line = y within threshold)
        # This handles Tesseract returning "Piano" and "Terra" as separate words
        grouped_results = self._group_nearby_words(results, y_threshold=20, x_threshold=80)
        
        found_floors = []

        for group in grouped_results:
            # Combine text from all words in group
            combined_text = " ".join(r.text for r in group)
            normalized = normalize_text(combined_text)
            
            # Calculate group bbox (union of all word bboxes)
            min_x = min(r.bbox[0] for r in group if r.bbox)
            min_y = min(r.bbox[1] for r in group if r.bbox)
            max_x = max(r.bbox[0] + r.bbox[2] for r in group if r.bbox)
            max_y = max(r.bbox[1] + r.bbox[3] for r in group if r.bbox)
            group_bbox = (min_x, min_y, max_x - min_x, max_y - min_y)
            avg_conf = sum(r.confidence for r in group) / len(group)

            for pattern, label, floor_num, conf in self._compiled_patterns:
                if pattern.search(normalized):
                    y_pos = min_y + (max_y - min_y) // 2
                    found_floors.append((
                        label, floor_num, y_pos,
                        conf * avg_conf,
                        group_bbox
                    ))
                    logger.debug(f"Found floor label: '{combined_text}' -> {label}")
                    break

        # Also check individual words for simple patterns like "PT"
        for result in results:
            text = normalize_text(result.text)
            for pattern, label, floor_num, conf in self._compiled_patterns:
                if pattern.search(text):
                    # Check if not already found in groups
                    already_found = any(
                        abs(f[2] - (result.bbox[1] + result.bbox[3] // 2)) < 30
                        for f in found_floors
                    )
                    if not already_found and result.bbox:
                        y_pos = result.bbox[1] + result.bbox[3] // 2
                        found_floors.append((
                            label, floor_num, y_pos,
                            conf * result.confidence,
                            result.bbox
                        ))
                        break

        # Remove duplicates (same floor at similar y positions)
        found_floors = self._deduplicate_floors(found_floors)

        # Sort by y-position
        found_floors.sort(key=lambda f: f[2])

        logger.info(f"Detected {len(found_floors)} floor labels")
        return found_floors

    def _group_nearby_words(
        self,
        results: list,
        y_threshold: int = 20,
        x_threshold: int = 80
    ) -> list[list]:
        """Group words that are on the same line and close together."""
        if not results:
            return []
        
        # Filter results with valid bboxes
        valid_results = [r for r in results if r.bbox and r.text.strip()]
        if not valid_results:
            return []
        
        # Sort by y, then x
        sorted_results = sorted(valid_results, key=lambda r: (r.bbox[1], r.bbox[0]))
        
        groups = []
        current_group = [sorted_results[0]]
        
        for result in sorted_results[1:]:
            last = current_group[-1]
            
            # Check if on same line (y close) and horizontally close
            y_close = abs(result.bbox[1] - last.bbox[1]) < y_threshold
            x_close = result.bbox[0] - (last.bbox[0] + last.bbox[2]) < x_threshold
            
            if y_close and x_close:
                current_group.append(result)
            else:
                if len(current_group) > 1:  # Only keep multi-word groups
                    groups.append(current_group)
                current_group = [result]
        
        # Don't forget last group
        if len(current_group) > 1:
            groups.append(current_group)
        
        return groups

    def _deduplicate_floors(
        self,
        floors: list[tuple[str, int, int, float, tuple[int, int, int, int]]]
    ) -> list[tuple[str, int, int, float, tuple[int, int, int, int]]]:
        """Remove duplicate floor detections at similar y positions."""
        if not floors:
            return []
        
        # Sort by confidence descending
        sorted_floors = sorted(floors, key=lambda f: f[3], reverse=True)
        
        unique = []
        for floor in sorted_floors:
            # Check if similar floor already exists
            duplicate = False
            for existing in unique:
                if floor[1] == existing[1] and abs(floor[2] - existing[2]) < 50:
                    duplicate = True
                    break
            if not duplicate:
                unique.append(floor)
        
        return unique

    def detect_floor_from_text(self, text: str) -> tuple[str, int, float] | None:
        """
        Detect floor label from text string.

        Returns:
            (label, floor_number, confidence) or None
        """
        normalized = normalize_text(text)

        best_match = None
        best_conf = 0.0

        for pattern, label, floor_num, conf in self._compiled_patterns:
            if pattern.search(normalized) and conf > best_conf:
                best_match = (label, floor_num, conf)
                best_conf = conf

        # Fuzzy matching for typos
        if not best_match:
            best_match = self._fuzzy_match_floor(normalized)

        return best_match

    def _fuzzy_match_floor(
        self,
        text: str
    ) -> tuple[str, int, float] | None:
        """Fuzzy match floor labels for OCR errors."""
        # Common OCR mistakes
        corrections = {
            "piane": "piano",
            "plano": "piano",
            "pirmo": "primo",
            "prino": "primo",
            "seoondo": "secondo",
            "seocndo": "secondo",
            "tera": "terra",
            "teira": "terra",
        }

        corrected = text
        for wrong, right in corrections.items():
            corrected = corrected.replace(wrong, right)

        if corrected != text:
            return self.detect_floor_from_text(corrected)

        return None

    def split_into_floors(
        self,
        image: np.ndarray,
        anchor: str = "up"
    ) -> list[FloorSection]:
        """
        Split planimetry image into floor sections.

        Args:
            image: Full planimetry image
            anchor: "up" = line above label, "down" = line below label

        Returns:
            List of FloorSection objects
        """
        floor_labels = self.detect_floor_labels(image)

        if not floor_labels:
            logger.warning("No floor labels detected, returning entire image as single section")
            return [FloorSection(
                floor_label="Unknown",
                floor_number=0,
                image=image.copy(),
                y_start=0,
                y_end=image.shape[0],
                confidence=0.0
            )]

        height = image.shape[0]
        sections = []

        # Calculate split positions
        margin = 6

        for i, (label, floor_num, y_pos, conf, bbox) in enumerate(floor_labels):
            if anchor == "up":
                # Line above the label
                y_split = max(bbox[1] - margin, 0) if bbox else y_pos - margin
            else:
                # Line below the label
                y_split = min(bbox[1] + bbox[3] + margin, height - 1) if bbox else y_pos + margin

            # Determine section boundaries
            if anchor == "up":
                y_start = y_split
                if i + 1 < len(floor_labels):
                    next_bbox = floor_labels[i + 1][4]
                    y_end = max(next_bbox[1] - margin, 0) if next_bbox else floor_labels[i + 1][2]
                else:
                    y_end = height
            else:
                if i > 0:
                    prev_bbox = floor_labels[i - 1][4]
                    y_start = min(prev_bbox[1] + prev_bbox[3] + margin, height) if prev_bbox else floor_labels[i - 1][2]
                else:
                    y_start = 0
                y_end = y_split

            if y_end > y_start:
                section_img = image[y_start:y_end, :].copy()
                sections.append(FloorSection(
                    floor_label=label,
                    floor_number=floor_num,
                    image=section_img,
                    y_start=y_start,
                    y_end=y_end,
                    confidence=conf
                ))

        logger.info(f"Split image into {len(sections)} floor sections")
        return sections

    def visualize_floor_lines(
        self,
        image: np.ndarray,
        sections: list[FloorSection]
    ) -> np.ndarray:
        """Draw floor separation lines on image."""
        result = image.copy()
        width = image.shape[1]

        for section in sections:
            # Draw line at section start
            cv2.line(result, (0, section.y_start), (width, section.y_start), (0, 255, 0), 2)

            # Add label
            label = f"{section.floor_label} ({section.confidence:.0%})"
            cv2.putText(
                result, label,
                (10, section.y_start + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
            )

        return result
