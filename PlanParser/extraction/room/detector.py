"""
Room Detection Module
=====================
Detects and labels rooms from planimetry sections.

Follows SRP: detection logic only, visualization delegated to services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np

from PlanParser.domain.config import DetectionConfig, RoomLabels
from PlanParser.domain.protocols import TextMatcher
from PlanParser.domain.text_utils import normalize_text
from PlanParser.extraction.image_processing import crop_region, find_text_regions
from PlanParser.infrastructure.ocr.engine import OCRManager
from PlanParser.application.text_matching import FuzzyTextMatcher
from PlanParser.application.visualization import VisualizationService, VisualStyle

if TYPE_CHECKING:
    from PlanParser.domain.protocols import ImageArray

logger = logging.getLogger(__name__)


@dataclass
class DetectedRoom:
    """Represents a detected room with its properties."""
    label: str
    normalized_label: str
    bbox: tuple[int, int, int, int]  # x, y, w, h
    center: tuple[int, int]
    confidence: float
    raw_ocr_text: str

    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]


@dataclass
class RoomCandidate:
    """Intermediate candidate before final room classification."""
    bbox: tuple[int, int, int, int]
    ocr_results: list[str]
    tokens: set[str]
    image_crop: np.ndarray | None = None


class RoomDetector:
    """
    Detects and classifies rooms in planimetry images.
    
    Dependencies are injected for testability and SRP compliance.
    """

    def __init__(
        self,
        ocr_manager: OCRManager,
        room_labels: RoomLabels | None = None,
        detection_config: DetectionConfig | None = None,
        text_matcher: TextMatcher | None = None,
        visualizer: VisualizationService | None = None
    ):
        self.ocr = ocr_manager
        self.labels = room_labels or RoomLabels()
        self.config = detection_config or DetectionConfig()
        
        # Injected services (with defaults for backward compatibility)
        self._matcher = text_matcher or FuzzyTextMatcher()
        self._visualizer = visualizer or VisualizationService(
            VisualStyle(box_color=(0, 255, 0), line_thickness=2)
        )

        # Build expanded target set from synonyms
        self._targets = self._build_targets()

    def _build_targets(self) -> set[str]:
        """Build complete set of target labels including synonyms."""
        targets = set()

        # Add base targets
        for t in self.labels.targets:
            targets.add(normalize_text(t))

        # Add synonyms
        for canonical, alternatives in self.labels.synonyms.items():
            targets.add(normalize_text(canonical))
            for alt in alternatives:
                targets.add(normalize_text(alt))

        return targets

    def detect_candidates(self, image: np.ndarray) -> list[RoomCandidate]:
        """
        Detect all potential room label regions in an image.

        Args:
            image: BGR image

        Returns:
            List of room candidates
        """
        # Find text regions using morphological operations
        boxes = find_text_regions(
            image,
            min_area=self.config.min_area,
            max_area=self.config.max_area,
            min_aspect_ratio=self.config.min_aspect_ratio,
            max_aspect_ratio=self.config.max_aspect_ratio,
            min_height=self.config.min_height,
            max_height=self.config.max_height
        )

        # Limit candidates to avoid OCR explosion (sort by area, take largest)
        MAX_CANDIDATES = 50
        if len(boxes) > MAX_CANDIDATES:
            boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)[:MAX_CANDIDATES]
            logger.warning(f"Limiting candidates from {len(boxes)} to {MAX_CANDIDATES}")

        candidates = []
        for bbox in boxes:
            # Crop region
            crop = crop_region(image, bbox, padding=2)

            # Run OCR
            ocr_text = self.ocr.recognize_text(crop)

            # Extract tokens
            tokens = self._extract_tokens(ocr_text)

            candidates.append(RoomCandidate(
                bbox=bbox,
                ocr_results=[ocr_text] if ocr_text else [],
                tokens=tokens,
                image_crop=crop
            ))

        logger.info(f"Detected {len(candidates)} room candidates")
        return candidates

    def _extract_tokens(self, text: str) -> set[str]:
        """Extract normalized tokens from OCR text."""
        if not text:
            return set()

        normalized = normalize_text(text)

        # Split into words
        words = normalized.split()

        # Filter out blacklisted words
        blacklist = {normalize_text(b) for b in self.labels.blacklist}
        tokens = {w for w in words if w and w not in blacklist}

        # Also add the full normalized text
        if normalized:
            tokens.add(normalized)

        return tokens

    def classify_candidate(self, candidate: RoomCandidate) -> DetectedRoom | None:
        """
        Classify a candidate as a specific room type.

        Returns:
            DetectedRoom if it matches a known room type, None otherwise
        """
        best_match = None
        best_score = 0.0
        matched_token = ""

        for token in candidate.tokens:
            # Direct match
            if token in self._targets:
                score = 1.0
                if score > best_score:
                    best_score = score
                    best_match = self._get_canonical_label(token)
                    matched_token = token

            # Fuzzy match for typos using injected matcher
            else:
                match_result = self._matcher.find_best_match(
                    token, self._targets, threshold=0.75
                )
                if match_result and match_result[1] > best_score:
                    best_score = match_result[1]
                    best_match = self._get_canonical_label(match_result[0])
                    matched_token = token

        if best_match:
            x, y, w, h = candidate.bbox
            return DetectedRoom(
                label=best_match,
                normalized_label=normalize_text(best_match),
                bbox=candidate.bbox,
                center=(x + w // 2, y + h // 2),
                confidence=best_score,
                raw_ocr_text=matched_token
            )

        return None

    def _get_canonical_label(self, token: str) -> str:
        """Get canonical (preferred) label for a token."""
        normalized = normalize_text(token)

        # Check synonyms
        for canonical, alternatives in self.labels.synonyms.items():
            if normalized == normalize_text(canonical):
                return canonical
            for alt in alternatives:
                if normalized == normalize_text(alt):
                    return canonical

        return token

    # _similarity removed: now delegated to self._matcher

    def detect_rooms(self, image: np.ndarray) -> list[DetectedRoom]:
        """
        Full room detection pipeline.

        Args:
            image: BGR image

        Returns:
            List of detected rooms
        """
        candidates = self.detect_candidates(image)
        rooms = []

        for candidate in candidates:
            room = self.classify_candidate(candidate)
            if room:
                rooms.append(room)
                logger.debug(f"Classified room: {room.label} at {room.bbox}")

        logger.info(f"Detected {len(rooms)} rooms from {len(candidates)} candidates")
        return rooms

    def visualize(
        self,
        image: np.ndarray,
        rooms: list[DetectedRoom],
        candidates: list[RoomCandidate] | None = None
    ) -> np.ndarray:
        """
        Create visualization of detected rooms.
        Delegates to VisualizationService for actual drawing.

        Args:
            image: Original image
            rooms: Detected rooms to highlight
            candidates: Optional - all candidates (shown in lighter color)

        Returns:
            Annotated image
        """
        from .core.protocols import DetectionResult

        result = image.copy()

        # Draw all candidates in light gray
        if candidates:
            candidate_style = VisualStyle(
                box_color=(200, 200, 100),
                line_thickness=1
            )
            for cand in candidates:
                result = self._visualizer.draw_bbox(
                    result, cand.bbox, style=candidate_style
                )

        # Convert rooms to DetectionResults and draw
        detections = [
            DetectionResult(
                label=room.label,
                confidence=room.confidence,
                bbox=room.bbox
            )
            for room in rooms
        ]
        result = self._visualizer.draw_detections(result, detections)

        return result
