"""
Step 2: Floor Detection and Splitting.

Detects the main drawing rectangle(s) on a page, finds Italian floor
labels via OCR, and splits the image into per-floor cropped images.
"""

import re
import cv2
import numpy as np
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import logging

from geometry_types import FloorImage

try:
    import pytesseract
except ImportError:
    pytesseract = None


# ============================================================
# Italian floor label patterns (from define_floor_v2.py)
# ============================================================

def _build_floor_patterns():
    degree = r"[°º]?"
    spaces = r"[\s_.-]*"
    patterns = [
        (rf"\bpiano{spaces}terra\b", "piano terra", 1.0),
        (rf"\bp{spaces}?\.?{spaces}?terra\b", "piano terra", 0.95),
        (rf"\bprimo{spaces}piano\b", "primo piano", 1.0),
        (rf"\bsecondo{spaces}piano\b", "secondo piano", 1.0),
        (rf"\bterzo{spaces}piano\b", "terzo piano", 1.0),
        (rf"\bquarto{spaces}piano\b", "quarto piano", 1.0),
        (rf"\bquinto{spaces}piano\b", "quinto piano", 1.0),
        (rf"\bsesto{spaces}piano\b", "sesto piano", 1.0),
        (rf"\bsettimo{spaces}piano\b", "settimo piano", 1.0),
        (rf"\bottavo{spaces}piano\b", "ottavo piano", 1.0),
        (rf"\bnono{spaces}piano\b", "nono piano", 1.0),
        (rf"\bdecimo{spaces}piano\b", "decimo piano", 1.0),
        (rf"\bpiano{spaces}primo\b", "primo piano", 0.95),
        (rf"\bpiano{spaces}secondo\b", "secondo piano", 0.95),
        (rf"\bpiano{spaces}terzo\b", "terzo piano", 0.95),
        (rf"\bpiano{spaces}quarto\b", "quarto piano", 0.95),
        (rf"\bpiano{spaces}quinto\b", "quinto piano", 0.95),
        (rf"\bpiano{spaces}sesto\b", "sesto piano", 0.95),
        (rf"\bpiano{spaces}settimo\b", "settimo piano", 0.95),
        (rf"\bpiano{spaces}ottavo\b", "ottavo piano", 0.95),
        (rf"\bpiano{spaces}nono\b", "nono piano", 0.95),
        (rf"\bpiano{spaces}decimo\b", "decimo piano", 0.95),
        (rf"\b1{degree}{spaces}piano\b", "primo piano", 0.9),
        (rf"\b2{degree}{spaces}piano\b", "secondo piano", 0.9),
        (rf"\b3{degree}{spaces}piano\b", "terzo piano", 0.9),
        (rf"\b4{degree}{spaces}piano\b", "quarto piano", 0.9),
        (rf"\b5{degree}{spaces}piano\b", "quinto piano", 0.9),
        (rf"\b6{degree}{spaces}piano\b", "sesto piano", 0.9),
        (rf"\b7{degree}{spaces}piano\b", "settimo piano", 0.9),
        (rf"\b8{degree}{spaces}piano\b", "ottavo piano", 0.9),
        (rf"\b9{degree}{spaces}piano\b", "nono piano", 0.9),
        (rf"\b10{degree}{spaces}piano\b", "decimo piano", 0.9),
        (rf"\bpiano{spaces}1{degree}\b", "primo piano", 0.8),
        (rf"\bpiano{spaces}2{degree}\b", "secondo piano", 0.8),
        (rf"\bpiano{spaces}3{degree}\b", "terzo piano", 0.8),
        (rf"\bpiano{spaces}4{degree}\b", "quarto piano", 0.8),
        (rf"\bpiano{spaces}5{degree}\b", "quinto piano", 0.8),
        (rf"\bpiano{spaces}6{degree}\b", "sesto piano", 0.8),
        (rf"\bpiano{spaces}7{degree}\b", "settimo piano", 0.8),
        (rf"\bpiano{spaces}8{degree}\b", "ottavo piano", 0.8),
        (rf"\bpiano{spaces}9{degree}\b", "nono piano", 0.8),
        (rf"\bpiano{spaces}10{degree}\b", "decimo piano", 0.8),
    ]
    return [(re.compile(p, re.IGNORECASE), label, conf) for p, label, conf in patterns]


FLOOR_PATTERNS = _build_floor_patterns()


def _normalize_text(value: str) -> str:
    """Normalize text for matching: NFKD, remove diacritics, lowercase."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.lower()


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i]
        for j, cb in enumerate(b, start=1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (ca != cb)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _ocr_variants(image_gray: np.ndarray) -> list:
    """Generate multiple preprocessed versions for robust OCR."""
    variants = [image_gray]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants.append(clahe.apply(image_gray))
    _, th_otsu = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(th_otsu)
    _, th_otsu_inv = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    variants.append(th_otsu_inv)
    th_adp = cv2.adaptiveThreshold(
        image_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )
    variants.append(th_adp)
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(image_gray, cv2.MORPH_CLOSE, kernel, iterations=1)
    th_closed = cv2.adaptiveThreshold(
        closed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )
    variants.append(th_closed)
    th_adp2 = cv2.adaptiveThreshold(
        image_gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 5
    )
    variants.append(th_adp2)
    return variants


def _run_tesseract_on_variants(variants: list) -> list:
    """Run Tesseract OCR on multiple image variants with multiple configs."""
    if pytesseract is None:
        return []
    texts = []
    psms = [6, 11, 4, 7, 3]
    langs = ["ita", "ita+eng"]
    for v in variants:
        v_up = cv2.resize(v, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        for lang in langs:
            for psm in psms:
                try:
                    txt = pytesseract.image_to_string(v_up, lang=lang, config=f"--psm {psm}")
                    if txt and txt.strip():
                        texts.append(txt)
                except Exception:
                    continue
    unique, seen = [], set()
    for t in texts:
        nt = t.strip()
        if nt and nt not in seen:
            unique.append(nt)
            seen.add(nt)
    return unique


# ============================================================
# Main floor detection functions
# ============================================================

def find_main_rectangle(
    image: np.ndarray,
    min_area_fraction: float = 0.05,
    logger: Optional[logging.Logger] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Find the main drawing rectangle on the page.

    Returns:
        (x, y, w, h) of the largest 4-sided convex contour,
        or None if not found.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_area = image.shape[0] * image.shape[1]
    min_area = img_area * min_area_fraction
    best_rect = None
    max_area = 0

    for cnt in contours:
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            if area > max_area and area > min_area:
                max_area = area
                best_rect = (x, y, w, h)

    # Fallback: largest bounding rect from any contour
    if best_rect is None and contours:
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area > max_area and area > min_area:
                max_area = area
                best_rect = (x, y, w, h)

    if logger:
        if best_rect:
            logger.info("  Main rectangle: x=%d y=%d w=%d h=%d", *best_rect)
        else:
            logger.warning("  No main rectangle found")

    return best_rect


def _detect_piano_positions(
    image_bgr: np.ndarray,
    logger: Optional[logging.Logger] = None,
) -> List[Dict]:
    """
    Use OCR to find positions of "piano" words in the image.

    Returns:
        List of {"word": str, "x": int, "y": int, "w": int, "h": int}
    """
    if pytesseract is None:
        return []

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)

    boxes = []
    try:
        data = pytesseract.image_to_data(
            gray, lang="ita+eng", config="--psm 6", output_type=pytesseract.Output.DICT
        )
        n_boxes = len(data["text"])
        for i in range(n_boxes):
            word = data["text"][i]
            if word and "piano" in word.lower():
                boxes.append({
                    "word": word,
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "w": data["width"][i],
                    "h": data["height"][i],
                })
    except Exception as e:
        if logger:
            logger.warning("  OCR image_to_data failed: %s", e)

    if logger:
        logger.info("  Found %d 'piano' word(s) via OCR", len(boxes))

    return boxes


def _match_floor_label(text_candidates: List[str]) -> Dict:
    """
    Match floor label from OCR text candidates using regex patterns + fuzzy matching.

    Returns:
        {"floor": str or None, "confidence": float, "raw_text": str}
    """
    canonical_labels = ["piano terra"]
    for word in ["primo", "secondo", "terzo", "quarto", "quinto",
                 "sesto", "settimo", "ottavo", "nono", "decimo"]:
        canonical_labels.append(f"{word} piano")

    best = {"floor": None, "confidence": 0.0, "raw_text": ""}

    for text in text_candidates:
        processed = _normalize_text(text)

        # Regex exact matching
        for pattern, label, conf in FLOOR_PATTERNS:
            if pattern.search(processed) and conf > best["confidence"]:
                best = {"floor": label, "confidence": conf, "raw_text": text}

        # Fuzzy line-by-line matching
        lines = [ln.strip() for ln in processed.splitlines() if ln.strip()]
        for line in lines:
            contains_piano = "piano" in line or _levenshtein_distance(
                line.replace(" ", ""), "piano"
            ) <= 1
            if not contains_piano:
                continue
            for label in canonical_labels:
                d = _levenshtein_distance(line, label)
                ratio = 1.0 - (d / max(len(label), 1))
                if ratio >= 0.6 and ratio > best["confidence"]:
                    best = {"floor": label, "confidence": ratio, "raw_text": text}

    return best


def split_floors(
    image: np.ndarray,
    debug_dir: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> List[FloorImage]:
    """
    Main entry: detect floors in the image and split into per-floor images.

    Strategy:
    1. Find the main drawing rectangle
    2. Crop to the drawing area
    3. Run OCR to find "piano" labels and their vertical positions
    4. Split the cropped image at the detected floor boundaries
    5. For each section, run OCR to identify the floor label

    If no floor labels are detected, returns a single FloorImage with label "unknown".

    Args:
        image: Full page BGR image from Step 1.
        debug_dir: If set, saves intermediate images here.
        logger: Optional logger.

    Returns:
        List of FloorImage (one per detected floor).
    """
    if debug_dir:
        debug_dir = Path(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)

    img_h, img_w = image.shape[:2]

    # 1. Find main rectangle
    rect = find_main_rectangle(image, logger=logger)
    if rect is None:
        if logger:
            logger.warning("  No rectangle found, using full image")
        cropped = image.copy()
        rect = (0, 0, img_w, img_h)
        crop_rect = rect
    else:
        x, y, w, h = rect
        padding = 5
        x1 = max(x + padding, 0)
        y1 = max(y + padding, 0)
        x2 = min(x + w - padding, img_w)
        y2 = min(y + h - padding, img_h)
        cropped = image[y1:y2, x1:x2]
        crop_rect = (x1, y1, x2 - x1, y2 - y1)

    if debug_dir:
        debug_img = image.copy()
        if rect:
            x, y, w, h = rect
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 3)
        cv2.imwrite(str(debug_dir / "floor_0_detected_rect.png"), debug_img)
        cv2.imwrite(str(debug_dir / "floor_0_cropped.png"), cropped)

    # 2. Find "piano" word positions
    piano_boxes = _detect_piano_positions(cropped, logger)

    if not piano_boxes:
        # No floor labels found -> return single floor
        if logger:
            logger.info("  No floor labels detected, returning single floor")

        # Still try to identify the floor via full OCR
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)
        variants = _ocr_variants(gray)
        text_candidates = _run_tesseract_on_variants(variants)
        match = _match_floor_label(text_candidates)

        label = match["floor"] if match["floor"] else "unknown"
        confidence = match["confidence"]

        return [FloorImage(
            image=cropped,
            label=label,
            confidence=confidence,
            source_rect=crop_rect,
        )]

    # 3. Compute split lines from piano positions (anchor = "up")
    margin = 6
    piano_lines = []
    for box in piano_boxes:
        line_y = max(box["y"] - margin, 0)
        if not any(abs(line_y - existing) <= 3 for existing in piano_lines):
            piano_lines.append(line_y)

    piano_lines.sort()

    if debug_dir:
        split_img = cropped.copy()
        for ly in piano_lines:
            cv2.line(split_img, (0, ly), (cropped.shape[1] - 1, ly), (0, 255, 0), 2)
        cv2.imwrite(str(debug_dir / "floor_split_lines.png"), split_img)

    if logger:
        logger.info("  Split lines at y: %s", piano_lines)

    # 4. Split into sections
    crop_h = cropped.shape[0]
    sections = []
    for i, y_top in enumerate(piano_lines):
        y_bottom = piano_lines[i + 1] if i + 1 < len(piano_lines) else crop_h
        if y_bottom - y_top < 50:  # Skip tiny sections
            continue
        section_img = cropped[y_top:y_bottom, :]
        sections.append((section_img, y_top))

    if not sections:
        sections = [(cropped, 0)]

    # 5. Identify floor labels for each section
    floors = []
    for i, (section, section_y) in enumerate(sections):
        gray = cv2.cvtColor(section, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)
        variants = _ocr_variants(gray)
        text_candidates = _run_tesseract_on_variants(variants)
        match = _match_floor_label(text_candidates)

        label = match["floor"] if match["floor"] else f"floor_{i}"
        confidence = match["confidence"]

        if debug_dir:
            cv2.imwrite(str(debug_dir / f"floor_{i}_{label.replace(' ', '_')}.png"), section)

        floors.append(FloorImage(
            image=section,
            label=label,
            confidence=confidence,
            source_rect=(
                crop_rect[0],
                crop_rect[1] + section_y,
                section.shape[1],
                section.shape[0],
            ),
        ))

        if logger:
            logger.info("  Floor %d: '%s' (confidence=%.2f, size=%dx%d)",
                        i, label, confidence, section.shape[1], section.shape[0])

    return floors
