import os
import re
import cv2
import numpy as np

try:
    import pytesseract  # Requires Tesseract OCR to be installed on the system
except Exception:  # pragma: no cover
    pytesseract = None

import unicodedata


def _normalize_text(value: str) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join([c for c in value if not unicodedata.combining(c)])
    value = value.lower()
    return value


def crop_base_rectangle_from_debug(
    debug_image_path: str = "largest_rect_debug.png",
    output_cropped_path: str = "base_rectangle.png",
    inner_padding_px: int = 5,
):
    """
    From the debug image that contains a green rectangle overlay, detect the green frame,
    then crop the interior area (cutting off the edge) and save it as a new image.

    Returns (cropped_image (numpy array, BGR), crop_bbox(x1, y1, x2, y2)) or (None, None) on failure.
    """
    print(f"[DEBUG] Step: crop_base_rectangle_from_debug")
    print(f"[DEBUG] Checking if file exists: {debug_image_path}")
    if not os.path.exists(debug_image_path):
        print(f"File non trovato: {debug_image_path}")
        return None, None

    print(f"[DEBUG] Reading image: {debug_image_path}")
    image_bgr = cv2.imread(debug_image_path)
    if image_bgr is None:
        print("Impossibile leggere l'immagine di debug.")
        return None, None
    print(f"[DEBUG] Image shape: {image_bgr.shape}")

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    print(f"[DEBUG] Converted to HSV")

    lower_green = np.array([40, 100, 80], dtype=np.uint8)
    upper_green = np.array([85, 255, 255], dtype=np.uint8)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)
    print(f"[DEBUG] Green mask created")

    kernel = np.ones((3, 3), np.uint8)
    green_mask = cv2.dilate(green_mask, kernel, iterations=1)
    print(f"[DEBUG] Green mask dilated")

    ys, xs = np.where(green_mask > 0)
    print(f"[DEBUG] Green mask nonzero pixels: xs.size={xs.size}, ys.size={ys.size}")
    if xs.size == 0 or ys.size == 0:
        print("Bordo verde non rilevato. Provo fallback su contorni più grandi...")
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        print(f"[DEBUG] Converted to gray for fallback")
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        print(f"[DEBUG] Blurred for fallback")
        edged = cv2.Canny(blurred, 50, 150)
        print(f"[DEBUG] Edged for fallback")
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        print(f"[DEBUG] Found {len(contours)} contours in fallback")
        best_rect = None
        max_area = 0
        for cnt in contours:
            approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                x, y, w, h = cv2.boundingRect(approx)
                area = w * h
                print(f"[DEBUG] Fallback contour: x={x}, y={y}, w={w}, h={h}, area={area}")
                if area > max_area:
                    max_area = area
                    best_rect = (x, y, w, h)
        if best_rect is None:
            print("Nessun rettangolo trovato nel fallback.")
            return None, None
        x, y, w, h = best_rect
        x1, y1, x2, y2 = x, y, x + w, y + h
        print(f"[DEBUG] Fallback rectangle: x1={x1}, y1={y1}, x2={x2}, y2={y2}")
    else:
        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())
        print(f"[DEBUG] Green rectangle: x1={x1}, y1={y1}, x2={x2}, y2={y2}")

    x1_in = max(x1 + inner_padding_px, 0)
    y1_in = max(y1 + inner_padding_px, 0)
    x2_in = min(x2 - inner_padding_px, image_bgr.shape[1])
    y2_in = min(y2 - inner_padding_px, image_bgr.shape[0])
    print(f"[DEBUG] Cropping inside rectangle: x1_in={x1_in}, y1_in={y1_in}, x2_in={x2_in}, y2_in={y2_in}")

    if x2_in <= x1_in or y2_in <= y1_in:
        print("Bounding box non valida dopo il padding interno.")
        return None, None

    cropped = image_bgr[y1_in:y2_in, x1_in:x2_in]
    print(f"[DEBUG] Cropped image shape: {cropped.shape}")

    if output_cropped_path:
        cv2.imwrite(output_cropped_path, cropped)
        print(f"Salvataggio immagine ritagliata: {output_cropped_path}")

    return cropped, (x1_in, y1_in, x2_in, y2_in)


def _build_floor_patterns():
    # Regex patterns mapped to canonical labels
    # Use word boundaries and allow optional punctuation/degree symbol spacing
    degree = r"[°º]?"  # optional degree symbol
    spaces = r"[\s_.-]*"
    patterns = [
        # Common forms
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
        # Alternate order: "piano primo", etc.
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
        # Numeric forms
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
        # Alternate numeric order
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


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
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


def _generate_canonical_floor_labels() -> list:
    ordinals = [
        ("primo", "primo piano"),
        ("secondo", "secondo piano"),
        ("terzo", "terzo piano"),
        ("quarto", "quarto piano"),
        ("quinto", "quinto piano"),
        ("sesto", "sesto piano"),
        ("settimo", "settimo piano"),
        ("ottavo", "ottavo piano"),
        ("nono", "nono piano"),
        ("decimo", "decimo piano"),
    ]
    labels = ["piano terra"] + [canonical for _, canonical in ordinals]
    # Include alternate word orders for distance comparison
    labels += [f"piano {word}" for word, _ in ordinals]
    return list(dict.fromkeys(labels))  # de-duplicate preserving order


def _ocr_variants(image_gray: np.ndarray) -> list:
    print(f"[DEBUG] Step: _ocr_variants")
    variants = []
    # Raw gray
    variants.append(image_gray)
    print(f"[DEBUG] Added raw gray variant, shape={image_gray.shape}")
    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    clahe_img = clahe.apply(image_gray)
    variants.append(clahe_img)
    print(f"[DEBUG] Added CLAHE variant")
    # Otsu
    _, th_otsu = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(th_otsu)
    print(f"[DEBUG] Added Otsu variant")
    # Inverted Otsu
    _, th_otsu_inv = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    variants.append(th_otsu_inv)
    print(f"[DEBUG] Added Inverted Otsu variant")
    # Adaptive
    th_adp = cv2.adaptiveThreshold(image_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    variants.append(th_adp)
    print(f"[DEBUG] Added Adaptive Gaussian variant")
    # Morphological close then adaptive
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(image_gray, cv2.MORPH_CLOSE, kernel, iterations=1)
    th_closed = cv2.adaptiveThreshold(closed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    variants.append(th_closed)
    print(f"[DEBUG] Added Morphological close + Adaptive Gaussian variant")
    # More aggressive adaptive threshold
    th_adp2 = cv2.adaptiveThreshold(image_gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 5)
    variants.append(th_adp2)
    print(f"[DEBUG] Added Adaptive Mean variant")
    print(f"[DEBUG] Total variants: {len(variants)}")
    return variants


def _run_tesseract_on_variants(variants: list) -> list:
    print(f"[DEBUG] Step: _run_tesseract_on_variants")
    if pytesseract is None:
        print(f"[DEBUG] pytesseract is None")
        return []
    texts = []
    psms = [6, 11, 4, 7, 3]
    langs = ["ita", "ita+eng"]
    for v_idx, v in enumerate(variants):
        v_up = cv2.resize(v, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        print(f"[DEBUG] Variant {v_idx}: shape={v.shape}, upscaled shape={v_up.shape}")
        for lang in langs:
            for psm in psms:
                print(f"[DEBUG] OCR with lang={lang}, psm={psm}")
                try:
                    txt = pytesseract.image_to_string(v_up, lang=lang, config=f"--psm {psm}")
                    print(f"[DEBUG] OCR result: {txt!r}")
                    if txt:
                        texts.append(txt)
                except Exception as e:
                    print(f"[DEBUG] OCR exception: {e}")
                    continue
    unique = []
    seen = set()
    for t in texts:
        nt = t.strip()
        if nt and nt not in seen:
            unique.append(nt)
            seen.add(nt)
    print(f"[DEBUG] Unique OCR results: {len(unique)}")
    return unique


def detect_floor_label_from_image(cropped_bgr: np.ndarray) -> dict:
    """
    Run OCR over the cropped base rectangle image to find floor labels.
    Returns a dict like {"floor": str or None, "confidence": float, "raw_text": str}.
    """
    if cropped_bgr is None:
        return {"floor": None, "confidence": 0.0, "raw_text": ""}

    print(f"[DEBUG] Step: detect_floor_label_from_image")
    print(f"[DEBUG] Cropped image shape: {cropped_bgr.shape if cropped_bgr is not None else None}")
    # Preprocess for OCR
    gray = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
    print(f"[DEBUG] Converted to gray")
    gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)
    print(f"[DEBUG] Applied bilateral filter")

    all_text_candidates = []
    ocr_boxes = []
    if pytesseract is None:
        print("pytesseract non disponibile. Restituisco senza OCR.")
    else:
        variants = _ocr_variants(gray)
        ocr_texts = _run_tesseract_on_variants(variants)
        all_text_candidates.extend(ocr_texts)
        # Get bounding boxes for the word 'piano' using pytesseract.image_to_data
        try:
            data = pytesseract.image_to_data(gray, lang="ita+eng", config="--psm 6", output_type=pytesseract.Output.DICT)
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                word = data['text'][i]
                if word and 'piano' in word.lower():
                    (x, y, w, h) = (data['left'][i], data['top'][i], data['width'][i], data['height'][i])
                    ocr_boxes.append((x, y, w, h, word))
                    print(f"[DEBUG] Found 'piano' at box: x={x}, y={y}, w={w}, h={h}, word={word}")
        except Exception as e:
            print(f"[DEBUG] Exception in image_to_data: {e}")

    # Always include empty candidate to avoid crashes
    if not all_text_candidates:
        all_text_candidates = [""]

    print("\n--- OCR Candidates ---")
    for idx, cand in enumerate(all_text_candidates):
        print(f"[{idx}] {cand!r}")
    print("--- End OCR Candidates ---\n")

    # Draw rectangles and horizontal lines for 'piano' words if found
    if ocr_boxes:
        debug_img = cropped_bgr.copy()
        img_h, img_w = debug_img.shape[:2]
        piano_lines = []
        for (x, y, w, h, word) in ocr_boxes:
            # Draw rectangle
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(debug_img, word, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            # Draw horizontal line at vertical center of box
            y_center = y + h // 2
            cv2.line(debug_img, (0, y_center), (img_w - 1, y_center), (0, 255, 0), 2)
            piano_lines.append(y_center)
        cv2.imwrite("base_rectangle_piano_lines.png", debug_img)
        print("[DEBUG] Saved image with 'piano' lines: base_rectangle_piano_lines.png")
        # Sort lines top to bottom
        piano_lines_sorted = sorted(piano_lines)
        # Print section coordinates
        print("[DEBUG] Sections:")
        for i, y_top in enumerate(piano_lines_sorted):
            y_bottom = piano_lines_sorted[i + 1] if i + 1 < len(piano_lines_sorted) else img_h - 1
            print(f"  Section {i + 1}: top={y_top}, left=0, right={img_w - 1}, bottom={y_bottom}")
            # Crop and save each section as a separate image
            section_img = cropped_bgr[y_top:y_bottom, 0:img_w]
            section_path = f"base_rectangle_section_{i+1}.png"
            cv2.imwrite(section_path, section_img)
            print(f"[DEBUG] Saved section image: {section_path}")

    canonical_labels = _generate_canonical_floor_labels()
    best = {"floor": None, "confidence": 0.0, "raw_text": ""}

    for text in all_text_candidates:
        processed_text = _normalize_text(text)
        # Exact/regex first
        for pattern, label, conf in FLOOR_PATTERNS:
            if pattern.search(processed_text):
                if conf > best["confidence"]:
                    best = {"floor": label, "confidence": conf, "raw_text": text}

        # Fuzzy: line by line, prefer lines containing (approx) "piano"
        lines = [ln.strip() for ln in processed_text.splitlines() if ln.strip()]
        for line in lines:
            # quick filter: require 'piano' approximate
            base = "piano"
            dist_piano = _levenshtein_distance(line.replace(" ", ""), base)
            contains_piano = ("piano" in line) or (dist_piano <= 1)
            if not contains_piano and "piano" not in line:
                continue
            for label in canonical_labels:
                d = _levenshtein_distance(line, label)
                ratio = 1.0 - (d / max(len(label), 1))
                # threshold tolerant to minor OCR errors
                if ratio >= 0.6 and ratio > best["confidence"]:
                    # Map to canonical form without the alternate order
                    canonical = label
                    if canonical.startswith("piano ") and canonical != "piano terra":
                        # turn "piano primo" -> "primo piano"
                        alt = canonical.replace("piano ", "") + " piano"
                        canonical = alt
                    best = {"floor": canonical, "confidence": ratio, "raw_text": text}

    return best


def define_floor(
    debug_image_path: str = "largest_rect_debug.png",
    output_cropped_path: str = "base_rectangle.png",
):
    print(f"[DEBUG] Step: define_floor")
    print(f"[DEBUG] debug_image_path={debug_image_path}, output_cropped_path={output_cropped_path}")
    cropped, bbox = crop_base_rectangle_from_debug(
        debug_image_path=debug_image_path,
        output_cropped_path=output_cropped_path,
        inner_padding_px=5,
    )
    print(f"[DEBUG] Cropped image: {cropped.shape if cropped is not None else None}, bbox={bbox}")
    result = detect_floor_label_from_image(cropped)
    floor = result.get("floor")
    print(f"[DEBUG] OCR result: {result}")
    if floor:
        print(f"Piano rilevato: {floor} (confidenza {result.get('confidence'):.2f})")
    else:
        print("Nessun piano rilevato nel testo OCR.")
    return result


if __name__ == "__main__":
    # By default, consume the debug image saved by detect_largest_rectangle.py in the project root
    define_floor(debug_image_path="largest_rect_debug.png", output_cropped_path="base_rectangle.png")


