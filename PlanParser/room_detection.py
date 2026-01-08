"""
Room Detection Module
=====================
Detects and labels rooms from planimetry sections.
"""

import cv2
import numpy as np
from typing import List, Tuple, Dict, Optional, Set
from dataclasses import dataclass
import logging
import re

from .image_processing import find_text_regions, crop_region
from .ocr_engine import OCRManager, OCRResult, normalize_text
from .config import RoomLabels, DetectionConfig

logger = logging.getLogger(__name__)


@dataclass
class DetectedRoom:
    """Represents a detected room with its properties."""
    label: str
    normalized_label: str
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    center: Tuple[int, int]
    confidence: float
    raw_ocr_text: str
    
    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]


@dataclass
class RoomCandidate:
    """Intermediate candidate before final room classification."""
    bbox: Tuple[int, int, int, int]
    ocr_results: List[str]
    tokens: Set[str]
    image_crop: Optional[np.ndarray] = None


class RoomDetector:
    """
    Detects and classifies rooms in planimetry images.
    """
    
    def __init__(
        self,
        ocr_manager: OCRManager,
        room_labels: RoomLabels = None,
        detection_config: DetectionConfig = None
    ):
        self.ocr = ocr_manager
        self.labels = room_labels or RoomLabels()
        self.config = detection_config or DetectionConfig()
        
        # Build expanded target set from synonyms
        self._targets = self._build_targets()
    
    def _build_targets(self) -> Set[str]:
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
    
    def detect_candidates(self, image: np.ndarray) -> List[RoomCandidate]:
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
    
    def _extract_tokens(self, text: str) -> Set[str]:
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
    
    def classify_candidate(self, candidate: RoomCandidate) -> Optional[DetectedRoom]:
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
            
            # Fuzzy match for typos
            else:
                for target in self._targets:
                    similarity = self._similarity(token, target)
                    if similarity >= 0.75 and similarity > best_score:
                        best_score = similarity
                        best_match = self._get_canonical_label(target)
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
    
    def _similarity(self, a: str, b: str) -> float:
        """Calculate similarity between two strings (Levenshtein-based)."""
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        
        # Simple Levenshtein distance
        m, n = len(a), len(b)
        if m > n:
            a, b = b, a
            m, n = n, m
        
        current = list(range(m + 1))
        for i in range(1, n + 1):
            previous, current = current, [i] + [0] * m
            for j in range(1, m + 1):
                add, delete, change = previous[j] + 1, current[j - 1] + 1, previous[j - 1]
                if a[j - 1] != b[i - 1]:
                    change += 1
                current[j] = min(add, delete, change)
        
        distance = current[m]
        max_len = max(len(a), len(b))
        return 1.0 - (distance / max_len)
    
    def detect_rooms(self, image: np.ndarray) -> List[DetectedRoom]:
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
        rooms: List[DetectedRoom],
        candidates: List[RoomCandidate] = None
    ) -> np.ndarray:
        """
        Create visualization of detected rooms.
        
        Args:
            image: Original image
            rooms: Detected rooms to highlight
            candidates: Optional - all candidates (shown in lighter color)
            
        Returns:
            Annotated image
        """
        result = image.copy()
        
        # Draw all candidates in light blue
        if candidates:
            for cand in candidates:
                x, y, w, h = cand.bbox
                cv2.rectangle(result, (x, y), (x + w, y + h), (200, 200, 100), 1)
        
        # Draw detected rooms in green
        for room in rooms:
            x, y, w, h = room.bbox
            cv2.rectangle(result, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Add label
            label = f"{room.label} ({room.confidence:.0%})"
            cv2.putText(
                result, label,
                (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1
            )
        
        return result
