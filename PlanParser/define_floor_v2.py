import os
import re
import cv2
import numpy as np
import unicodedata

try:
    import pytesseract  # Requires Tesseract OCR to be installed on the system
except Exception:  # pragma: no cover
    pytesseract = None

# ---------------- utility testo ----------------
def _normalize_text(value: str) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join([c for c in value if not unicodedata.combining(c)])
    value = value.lower()
    return value

# ---------------- crop dal rettangolo verde ----------------
def crop_base_rectangle_from_debug(
    debug_image_path: str = "./debug_image/largest_rect_debug.png",
    output_cropped_path: str = "./debug_image/base_rectangle.png",
    inner_padding_px: int = 5,
):
    print(f"[DEBUG] Step: crop_base_rectangle_from_debug")
    if not os.path.exists(debug_image_path):
        print(f"File non trovato: {debug_image_path}")
        return None, None

    image_bgr = cv2.imread(debug_image_path)
    if image_bgr is None:
        print("Impossibile leggere l'immagine di debug.")
        return None, None

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower_green = np.array([40, 100, 80], dtype=np.uint8)
    upper_green = np.array([85, 255, 255], dtype=np.uint8)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)
    green_mask = cv2.dilate(green_mask, np.ones((3, 3), np.uint8), iterations=1)

    ys, xs = np.where(green_mask > 0)
    if xs.size == 0 or ys.size == 0:
        # fallback su contorni
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 150)
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_rect, max_area = None, 0
        for cnt in contours:
            approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                x, y, w, h = cv2.boundingRect(approx)
                area = w * h
                if area > max_area:
                    max_area = area
                    best_rect = (x, y, w, h)
        if best_rect is None:
            print("Nessun rettangolo trovato nel fallback.")
            return None, None
        x, y, w, h = best_rect
        x1, y1, x2, y2 = x, y, x + w, y + h
    else:
        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())

    x1_in = max(x1 + inner_padding_px, 0)
    y1_in = max(y1 + inner_padding_px, 0)
    x2_in = min(x2 - inner_padding_px, image_bgr.shape[1])
    y2_in = min(y2 - inner_padding_px, image_bgr.shape[0])

    if x2_in <= x1_in or y2_in <= y1_in:
        print("Bounding box non valida dopo il padding interno.")
        return None, None

    cropped = image_bgr[y1_in:y2_in, x1_in:x2_in]
    if output_cropped_path:
        cv2.imwrite(output_cropped_path, cropped)
        print(f"Salvataggio immagine ritagliata: {output_cropped_path}")
    return cropped, (x1_in, y1_in, x2_in, y2_in)

# ---------------- pattern e fuzzy ----------------
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

def _levenshtein_distance(a: str, b: str) -> int:
    if a == b: return 0
    if len(a) == 0: return len(b)
    if len(b) == 0: return len(a)
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
        ("primo", "primo piano"), ("secondo", "secondo piano"), ("terzo", "terzo piano"),
        ("quarto", "quarto piano"), ("quinto", "quinto piano"), ("sesto", "sesto piano"),
        ("settimo", "settimo piano"), ("ottavo", "ottavo piano"), ("nono", "nono piano"),
        ("decimo", "decimo piano"),
    ]
    labels = ["piano terra"] + [canonical for _, canonical in ordinals]
    labels += [f"piano {word}" for word, _ in ordinals]
    return list(dict.fromkeys(labels))

def _ocr_variants(image_gray: np.ndarray) -> list:
    variants = [image_gray]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    variants.append(clahe.apply(image_gray))
    _, th_otsu = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(th_otsu)
    _, th_otsu_inv = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    variants.append(th_otsu_inv)
    th_adp = cv2.adaptiveThreshold(image_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    variants.append(th_adp)
    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(image_gray, cv2.MORPH_CLOSE, kernel, iterations=1)
    th_closed = cv2.adaptiveThreshold(closed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    variants.append(th_closed)
    th_adp2 = cv2.adaptiveThreshold(image_gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 5)
    variants.append(th_adp2)
    return variants

def _run_tesseract_on_variants(variants: list) -> list:
    if pytesseract is None:
        return []
    texts, psms, langs = [], [6, 11, 4, 7, 3], ["ita", "ita+eng"]
    for v in variants:
        v_up = cv2.resize(v, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        for lang in langs:
            for psm in psms:
                try:
                    txt = pytesseract.image_to_string(v_up, lang=lang, config=f"--psm {psm}")
                    if txt:
                        texts.append(txt)
                except Exception:
                    continue
    unique, seen = [], set()
    for t in texts:
        nt = t.strip()
        if nt and nt not in seen:
            unique.append(nt); seen.add(nt)
    return unique

# ---------------- CORE: OCR + linee UP/DOWN + sezioni ----------------
def detect_floor_label_from_image(cropped_bgr: np.ndarray, split_anchor: str = "up") -> dict:
    """
    split_anchor:
      - 'up'   → traccia la linea SOPRA la parola 'piano' e crea sezioni [linea_i, linea_{i+1})
      - 'down' → traccia la linea SOTTO la parola 'piano' e crea sezioni [linea_{i-1}, linea_i)
                 (cioè la sezione è presa verso l’alto fino alla linea precedente)
    """
    if cropped_bgr is None:
        return {"floor": None, "confidence": 0.0, "raw_text": ""}

    anchor = (split_anchor or "up").lower()
    if anchor not in ("up", "down"):
        anchor = "up"
    print(f"[DEBUG] Anchor mode: {anchor.upper()}")

    gray = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)

    all_text_candidates, ocr_boxes = [], []
    if pytesseract is not None:
        variants = _ocr_variants(gray)
        all_text_candidates.extend(_run_tesseract_on_variants(variants))
        try:
            data = pytesseract.image_to_data(gray, lang="ita+eng", config="--psm 6", output_type=pytesseract.Output.DICT)
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                word = data['text'][i]
                if word and 'piano' in word.lower():
                    (x, y, w, h) = (data['left'][i], data['top'][i], data['width'][i], data['height'][i])
                    ocr_boxes.append((x, y, w, h, word))
        except Exception as e:
            print(f"[DEBUG] image_to_data exception: {e}")

    if not all_text_candidates:
        all_text_candidates = [""]

    # Disegno linee e calcolo sezioni
    img_h, img_w = cropped_bgr.shape[:2]
    debug_img = cropped_bgr.copy()
    piano_lines = []
    margin = 6

    for (x, y, w, h, word) in ocr_boxes:
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(debug_img, word, (x, max(y - 10, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        if anchor == "up":
            line_y = max(y - margin, 0)
        else:  # down
            line_y = min(y + h + margin, img_h - 1)

        if not any(abs(line_y - existing) <= 3 for existing in piano_lines):
            cv2.line(debug_img, (0, line_y), (img_w - 1, line_y), (0, 255, 0), 2)
            piano_lines.append(line_y)

    piano_lines_sorted = sorted(piano_lines)
    cv2.imwrite("./debug_image/base_rectangle_piano_lines.png", debug_img)
    print("[DEBUG] Salvata immagine con linee 'piano': base_rectangle_piano_lines.png")

    # Logica sezioni diversa per UP/DOWN
    print("[DEBUG] Sections:")
    if piano_lines_sorted:
        if anchor == "up":
            # [line_i, line_{i+1}) verso il basso
            for i, y_top in enumerate(piano_lines_sorted):
                y_bottom = piano_lines_sorted[i + 1] if i + 1 < len(piano_lines_sorted) else img_h - 1
                print(f"  Section {i + 1}: top={y_top}, left=0, right={img_w - 1}, bottom={y_bottom}")
                section_img = cropped_bgr[y_top:y_bottom, 0:img_w]
                cv2.imwrite(f"./debug_image/base_rectangle_section_{i+1}.png", section_img)
        else:
            # [line_{i-1}, line_i) verso l'alto
            for i, y_curr in enumerate(piano_lines_sorted):
                y_top = piano_lines_sorted[i - 1] if i - 1 >= 0 else 0
                y_bottom = y_curr
                if y_bottom <= y_top:
                    continue
                print(f"  Section {i + 1}: top={y_top}, left=0, right={img_w - 1}, bottom={y_bottom}")
                section_img = cropped_bgr[y_top:y_bottom, 0:img_w]
                cv2.imwrite(f"./debug_image/base_rectangle_section_{i+1}.png", section_img)

    # ------ Matching etichetta piano ------
    canonical_labels = _generate_canonical_floor_labels()
    best = {"floor": None, "confidence": 0.0, "raw_text": ""}

    for text in all_text_candidates:
        processed_text = _normalize_text(text)
        # Regex esatte
        for pattern, label, conf in FLOOR_PATTERNS:
            if pattern.search(processed_text) and conf > best["confidence"]:
                best = {"floor": label, "confidence": conf, "raw_text": text}

        # Fuzzy linea per linea
        lines = [ln.strip() for ln in processed_text.splitlines() if ln.strip()]
        for line in lines:
            contains_piano = ("piano" in line) or (_levenshtein_distance(line.replace(" ", ""), "piano") <= 1)
            if not contains_piano:
                continue
            for label in canonical_labels:
                d = _levenshtein_distance(line, label)
                ratio = 1.0 - (d / max(len(label), 1))
                if ratio >= 0.6 and ratio > best["confidence"]:
                    canonical = label
                    if canonical.startswith("piano ") and canonical != "piano terra":
                        canonical = canonical.replace("piano ", "") + " piano"
                    best = {"floor": canonical, "confidence": ratio, "raw_text": text}

    return best

# ---------------- API esterna ----------------
def define_floor(
    debug_image_path: str = "./debug_image/largest_rect_debug.png",
    output_cropped_path: str = "./debug_image/base_rectangle.png",
    split_anchor: str = "up",
):
    print(f"[DEBUG] Step: define_floor (anchor={split_anchor})")
    cropped, bbox = crop_base_rectangle_from_debug(
        debug_image_path=debug_image_path,
        output_cropped_path=output_cropped_path,
        inner_padding_px=5,
    )
    print(f"[DEBUG] Cropped image: {cropped.shape if cropped is not None else None}, bbox={bbox}")
    result = detect_floor_label_from_image(cropped, split_anchor=split_anchor)
    floor = result.get("floor")
    print(f"[DEBUG] OCR result: {result}")
    if floor:
        print(f"Piano rilevato: {floor} (confidenza {result.get('confidence'):.2f})")
    else:
        print("Nessun piano rilevato nel testo OCR.")
    return result

if __name__ == "__main__":
    define_floor(
        debug_image_path="./debug_image/largest_rect_debug.png",
        output_cropped_path="./debug_image/base_rectangle.png",
        split_anchor="up",  # cambia in "down" per linea sotto
    )
