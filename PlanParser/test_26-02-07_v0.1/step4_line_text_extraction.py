"""
Step 4: Line and Text Extraction.

The most critical step. Extracts:
  A) All line segments (walls) via Canny + HoughLinesP + collinear merge
  B) All text blocks with positions via multi-variant Tesseract OCR

Without accurate lines and text, no downstream knowledge can be built.
"""

import cv2
import numpy as np
import math
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional
import logging

from geometry_types import Segment, TextBlock, ExtractionResult

try:
    import pytesseract
except ImportError:
    pytesseract = None


# ============================================================
# PART A: LINE EXTRACTION
# ============================================================

class LineExtractor:
    """
    Extract line segments from a floor plan image.

    Pipeline: preprocess -> Canny edges -> HoughLinesP -> merge collinear
    """

    def __init__(
        self,
        canny_low: int = 50,
        canny_high: int = 150,
        hough_threshold: int = 40,
        min_line_length: int = 20,
        max_line_gap: int = 15,
        merge_distance: float = 10.0,
        merge_angle_tolerance: float = 5.0,
        merge_perp_tolerance: float = 5.0,
    ):
        self.canny_low = canny_low
        self.canny_high = canny_high
        self.hough_threshold = hough_threshold
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap
        self.merge_distance = merge_distance
        self.merge_angle_tolerance = merge_angle_tolerance
        self.merge_perp_tolerance = merge_perp_tolerance

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Grayscale + bilateral filter (edge-preserving noise reduction)."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        filtered = cv2.bilateralFilter(blurred, 9, 75, 75)
        return filtered

    def detect_edges(self, gray: np.ndarray) -> np.ndarray:
        """Canny edge detection + light dilation for connectivity."""
        edges = cv2.Canny(gray, self.canny_low, self.canny_high)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        return edges

    def detect_lines(self, edges: np.ndarray) -> List[Segment]:
        """Detect line segments via Probabilistic Hough Transform."""
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self.hough_threshold,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap,
        )
        if lines is None:
            return []
        return [Segment(float(l[0][0]), float(l[0][1]), float(l[0][2]), float(l[0][3]))
                for l in lines]

    def merge_collinear(self, segments: List[Segment]) -> List[Segment]:
        """
        Merge collinear segments that are close together.

        Two segments are merged if:
        1. Their angles differ by less than merge_angle_tolerance
        2. The minimum endpoint distance is less than merge_distance
        3. The perpendicular distance between the lines is less than merge_perp_tolerance
           (prevents "jumper segments" connecting non-collinear parallel lines)

        Runs in a loop until convergence (no more merges possible).
        """
        if len(segments) < 2:
            return segments

        current_segs = list(segments)
        changed = True

        while changed:
            changed = False
            merged = []
            used = set()

            for i, s1 in enumerate(current_segs):
                if i in used:
                    continue

                current = s1
                for j in range(i + 1, len(current_segs)):
                    if j in used:
                        continue

                    s2 = current_segs[j]

                    # Check angle similarity
                    angle_diff = abs(current.angle_deg - s2.angle_deg)
                    if angle_diff > 90:
                        angle_diff = 180 - angle_diff
                    if angle_diff > self.merge_angle_tolerance:
                        continue

                    # Check endpoint distance
                    dist = self._min_endpoint_distance(current, s2)
                    if dist > self.merge_distance:
                        continue

                    # Check perpendicular distance (prevents jumper segments)
                    mid2 = s2.midpoint
                    perp_dist = current.perpendicular_distance_to_point(mid2[0], mid2[1])
                    if perp_dist > self.merge_perp_tolerance:
                        continue

                    # All checks passed: merge
                    current = self._merge_two_segments(current, s2)
                    used.add(j)
                    changed = True

                merged.append(current)
                used.add(i)

            current_segs = merged

        return current_segs

    def _min_endpoint_distance(self, s1: Segment, s2: Segment) -> float:
        """Minimum distance between any pair of endpoints."""
        dists = [
            math.sqrt((s1.x1 - s2.x1) ** 2 + (s1.y1 - s2.y1) ** 2),
            math.sqrt((s1.x1 - s2.x2) ** 2 + (s1.y1 - s2.y2) ** 2),
            math.sqrt((s1.x2 - s2.x1) ** 2 + (s1.y2 - s2.y1) ** 2),
            math.sqrt((s1.x2 - s2.x2) ** 2 + (s1.y2 - s2.y2) ** 2),
        ]
        return min(dists)

    def _merge_two_segments(self, s1: Segment, s2: Segment) -> Segment:
        """Merge two segments by finding the two most distant endpoints."""
        points = [
            (s1.x1, s1.y1),
            (s1.x2, s1.y2),
            (s2.x1, s2.y1),
            (s2.x2, s2.y2),
        ]
        max_dist = 0
        best_pair = (points[0], points[1])
        for i, p1 in enumerate(points):
            for p2 in points[i + 1:]:
                d = math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
                if d > max_dist:
                    max_dist = d
                    best_pair = (p1, p2)
        return Segment(best_pair[0][0], best_pair[0][1], best_pair[1][0], best_pair[1][1])

    def extract(
        self,
        image: np.ndarray,
        debug_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> Tuple[List[Segment], dict]:
        """
        Full line extraction pipeline with optional debug output.

        Returns:
            (merged_segments, debug_dict)
        """
        debug = {}

        # Preprocessing
        gray = self.preprocess(image)
        debug["preprocessed"] = gray

        # Edge detection
        edges = self.detect_edges(gray)
        debug["edges"] = edges

        # Raw line detection
        raw_segments = self.detect_lines(edges)
        debug["raw_count"] = len(raw_segments)

        if logger:
            logger.info("    Lines: %d raw segments detected", len(raw_segments))

        # Merge collinear segments
        merged = self.merge_collinear(raw_segments)
        debug["merged_count"] = len(merged)

        if logger:
            logger.info("    Lines: %d after merge", len(merged))

        # Save debug images
        if debug_dir:
            debug_dir = Path(debug_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / "01_preprocessed.png"), gray)
            cv2.imwrite(str(debug_dir / "02_edges.png"), edges)

            raw_img = image.copy()
            for s in raw_segments:
                cv2.line(raw_img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)),
                         (0, 0, 255), 1)
            cv2.imwrite(str(debug_dir / "03_raw_lines.png"), raw_img)

            merged_img = image.copy()
            for s in merged:
                cv2.line(merged_img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)),
                         (0, 255, 0), 2)
            cv2.imwrite(str(debug_dir / "04_merged_lines.png"), merged_img)

        return merged, debug


def filter_by_orientation(
    segments: List[Segment],
    keep_horizontal: bool = True,
    keep_vertical: bool = True,
    tolerance_deg: float = 15.0,
) -> List[Segment]:
    """Filter segments by orientation (horizontal/vertical)."""
    filtered = []
    for s in segments:
        if keep_horizontal and s.is_horizontal(tolerance_deg):
            filtered.append(s)
        elif keep_vertical and s.is_vertical(tolerance_deg):
            filtered.append(s)
    return filtered


def filter_by_length(
    segments: List[Segment],
    min_length: float = 0,
    max_length: float = float("inf"),
) -> List[Segment]:
    """Filter segments by length."""
    return [s for s in segments if min_length <= s.length <= max_length]


# ============================================================
# PART B: TEXT EXTRACTION (OCR)
# ============================================================

def _enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """CLAHE + unsharp mask for better OCR."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cla = clahe.apply(gray)
    blur = cv2.GaussianBlur(cla, (0, 0), 1.2)
    return cv2.addWeighted(cla, 1.5, blur, -0.5, 0)


def _small_deskew(img_gray: np.ndarray) -> np.ndarray:
    """Try small rotation angles, pick the one with highest variance (sharpest)."""
    best, best_var = img_gray, float(img_gray.var())
    for ang in (-3, -2, -1, 1, 2, 3):
        h, w = img_gray.shape
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rot = cv2.warpAffine(
            img_gray, M, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        v = float(rot.var())
        if v > best_var:
            best, best_var = rot, v
    return best


def _ocr_preprocessing_variants(gray: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """
    Generate multiple preprocessed versions for robust OCR.

    Returns list of (variant_name, preprocessed_image).
    """
    g = _enhance_contrast(gray)
    g = _small_deskew(g)

    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, inv = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mean = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5
    )
    gaus = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3
    )
    bold = cv2.dilate(otsu, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), 1)

    return [("otsu", otsu), ("mean", mean), ("gaus", gaus), ("bold", bold), ("inv", inv)]


def _normalize_ocr_text(s: str) -> str:
    """Normalize OCR output: lowercase, remove diacritics, clean whitespace."""
    s = s.lower()
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )
    s = s.replace("-", " ")
    s = "".join(ch for ch in s if ch.isalnum() or ch in " ._/")
    s = " ".join(s.split())
    if s.endswith(".") and len(s) <= 5:
        s = s[:-1]
    return s.strip()


class TextExtractor:
    """
    Extract all text blocks with positions from a floor plan image.

    Uses Tesseract OCR with multiple preprocessing variants for robustness.
    """

    def __init__(
        self,
        lang: str = "ita+eng",
        psm_modes: Optional[List[int]] = None,
        min_confidence: float = 20.0,
    ):
        self.lang = lang
        self.psm_modes = psm_modes or [6, 11, 4]
        self.min_confidence = min_confidence

    def extract_text_blocks(
        self,
        image: np.ndarray,
        debug_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> List[TextBlock]:
        """
        Extract text blocks from the image.

        Strategy:
        1. Run pytesseract.image_to_data() on multiple preprocessing variants
        2. For each variant, collect words with confidence >= min_confidence
        3. Merge overlapping blocks, keep highest-confidence text
        4. Return deduplicated TextBlock list
        """
        if pytesseract is None:
            if logger:
                logger.warning("    pytesseract not available, skipping text extraction")
            return []

        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Generate preprocessing variants
        variants = _ocr_preprocessing_variants(gray)

        # Also include the raw enhanced version
        enhanced = _enhance_contrast(gray)
        variants.insert(0, ("enhanced", enhanced))

        all_blocks: List[TextBlock] = []

        for vname, prep in variants:
            if debug_dir:
                debug_dir = Path(debug_dir)
                debug_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(debug_dir / f"ocr_variant_{vname}.png"), prep)

            for psm in self.psm_modes:
                try:
                    data = pytesseract.image_to_data(
                        prep,
                        lang=self.lang,
                        config=f"--psm {psm}",
                        output_type=pytesseract.Output.DICT,
                    )
                except Exception as e:
                    if logger:
                        logger.debug("    OCR failed (var=%s, psm=%d): %s", vname, psm, e)
                    continue

                n = len(data["text"])
                for i in range(n):
                    text = data["text"][i].strip()
                    conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0.0

                    if not text or conf < self.min_confidence:
                        continue

                    block = TextBlock(
                        text=text,
                        x=int(data["left"][i]),
                        y=int(data["top"][i]),
                        w=int(data["width"][i]),
                        h=int(data["height"][i]),
                        confidence=conf,
                    )
                    all_blocks.append(block)

        # Deduplicate: merge overlapping blocks
        merged = self._merge_overlapping_blocks(all_blocks)

        if logger:
            logger.info("    OCR: %d raw blocks -> %d after dedup", len(all_blocks), len(merged))

        return merged

    def _merge_overlapping_blocks(self, blocks: List[TextBlock]) -> List[TextBlock]:
        """
        Merge text blocks that overlap significantly.
        Keeps the version with highest confidence for each spatial region.
        """
        if not blocks:
            return []

        # Sort by confidence descending
        sorted_blocks = sorted(blocks, key=lambda b: b.confidence, reverse=True)
        kept: List[TextBlock] = []

        for candidate in sorted_blocks:
            is_duplicate = False
            for existing in kept:
                # Check overlap via IoU-like metric
                overlap = self._overlap_fraction(candidate, existing)
                if overlap > 0.5:
                    # Same region, keep the one already in kept (higher confidence)
                    is_duplicate = True
                    break
                # Also check if same text at similar position
                if (candidate.text.lower() == existing.text.lower()
                        and abs(candidate.cx - existing.cx) < 30
                        and abs(candidate.cy - existing.cy) < 30):
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(candidate)

        return kept

    def _overlap_fraction(self, a: TextBlock, b: TextBlock) -> float:
        """Compute overlap fraction between two text blocks."""
        x1 = max(a.x, b.x)
        y1 = max(a.y, b.y)
        x2 = min(a.x + a.w, b.x + b.w)
        y2 = min(a.y + a.h, b.y + b.h)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area_a = a.w * a.h
        area_b = b.w * b.h
        min_area = min(area_a, area_b)

        if min_area == 0:
            return 0.0

        return intersection / min_area


# ============================================================
# COMBINED EXTRACTION ENTRY POINT
# ============================================================

def extract_lines_and_text(
    image: np.ndarray,
    debug_dir: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> ExtractionResult:
    """
    Step 4 main entry: extract both lines and text from a floor image.

    Args:
        image: BGR floor image (already cropped to a single floor).
        debug_dir: If set, saves intermediate images.
        logger: Optional logger.

    Returns:
        ExtractionResult with segments and text_blocks.
    """
    line_debug_dir = Path(debug_dir) / "lines" if debug_dir else None
    text_debug_dir = Path(debug_dir) / "text" if debug_dir else None

    # Extract lines
    extractor = LineExtractor()
    segments, debug_dict = extractor.extract(image, debug_dir=line_debug_dir, logger=logger)

    # Extract text
    text_extractor = TextExtractor()
    text_blocks = text_extractor.extract_text_blocks(
        image, debug_dir=text_debug_dir, logger=logger,
    )

    return ExtractionResult(
        segments=segments,
        text_blocks=text_blocks,
        debug_images=debug_dict,
    )
