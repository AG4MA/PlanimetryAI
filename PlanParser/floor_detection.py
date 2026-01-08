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

from .core.text_utils import normalize_text
from .ocr_engine import OCRManager

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

        found_floors = []

        for result in results:
            text = normalize_text(result.text)

            for pattern, label, floor_num, conf in self._compiled_patterns:
                if pattern.search(text):
                    # Use the y-coordinate from the bbox center
                    if result.bbox:
                        y_pos = result.bbox[1] + result.bbox[3] // 2
                        found_floors.append((
                            label, floor_num, y_pos,
                            conf * result.confidence,
                            result.bbox
                        ))
                    break

        # Sort by y-position
        found_floors.sort(key=lambda f: f[2])

        logger.info(f"Detected {len(found_floors)} floor labels")
        return found_floors

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
