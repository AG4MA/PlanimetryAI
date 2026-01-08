#!/usr/bin/env python3
"""
Pipeline:
  1) base.png (copia originale)
  2) all_candidates.png (tutti i box in azzurro)
  3) candidates_all/ (tutti i ritagli RAW) + candidates_all/candidates_map.txt (section_n | image_split_name | ocr | tok)
  4) selected.png (SOLO parole target, in verde)
  5) graph_selected.png (grafo KNN sui selected)

Requisiti:
  pip install opencv-python numpy pytesseract
  + Tesseract installato (ita+eng). Se non è nel PATH, imposta pytesseract.pytesseract.tesseract_cmd.
"""

import math
import os
import re
import shutil
import unicodedata
from collections.abc import Iterable

import cv2
import numpy as np
import pytesseract

# Se necessario, scommenta e imposta il path corretto:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------- Parametri detection ----------
MIN_AREA, MAX_AREA   = 50, 14000
MIN_RATIO, MAX_RATIO = 1.1, 22.0
MIN_H, MAX_H         = 6, 64
TOPHAT_KERNEL        = 5
DILATE_KERNEL        = 3
BOX_THICKNESS        = 1

# ---------- OCR ----------
OCR_LANGS = "ita+eng"
OCR_OEM   = 3
PSM_TRY   = [7, 6, 11]  # riga singola -> blocco -> sparse
WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .-_/"
PAD, SCALE = 4, 4

# ---------- Grafo ----------
K_NEIGHBOURS    = 4
MAX_RADIUS_FRAC = 0.66
CAND_COLOR      = (160,160,255)  # azzurro
SEL_COLOR       = (0,200,0)      # verde
EDGE_COLOR      = (255,128,0)    # arancione

# ---------- Sinonimi/abbr. per i target + blacklist ----------
EQUIV = {
    "sala": {"sala","soggiorno","soggiorno-pranzo"},
    "soggiorno": {"soggiorno","sala","soggiorno-pranzo"},
    "dis": {"dis","dis.","disimpegno","corridoio"},
    "bagno": {"bagno","wc"},
    "ripostiglio": {"ripostiglio","rip.","rip"},
    "balcone": {"balcone","terrazzo"},
    "cucina": {"cucina","angolo cottura","cottura"},
    "camera": {"camera","letto","stanza"},
    "portico": {"portico","veranda"},
}
BLACKLIST = {"arredo", "armadio", "altra", "uiu", "stessa"}

def append_map_line(path: str, line: str) -> None:
    # buffering=1 = line-buffered; flush + fsync per forzare su disco (utile su Windows)
    with open(path, "a", encoding="utf-8", buffering=1) as f:
        f.write(line + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            # su alcuni FS potrebbe non essere disponibile: ignora
            pass

# ---------- Utils testo ----------
def normalize_text(s: str) -> str:
    s = s.lower()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    s = s.replace("-", " ")
    s = "".join(ch for ch in s if (ch.isalnum() or ch in " ._/"))
    s = " ".join(s.split())
    if s.endswith(".") and len(s) <= 5:  # dis. -> dis, rip. -> rip
        s = s[:-1]
    return s.strip()

def expand_targets_from_equiv(equiv: dict[str,set[str]]) -> set[str]:
    return { normalize_text(w) for k,vals in equiv.items() for w in ({k}|set(vals)) }
TARGETS_CANON = expand_targets_from_equiv(EQUIV)

def extract_section_n(base_name: str) -> str:
    m = re.search(r'section[_-]?(\d+)', base_name, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'(\d+)$', base_name)
    return m.group(1) if m else base_name

# ---------- Imaging helpers ----------
def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    # Step 1: Create a CLAHE object
    # CLAHE = Contrast Limited Adaptive Histogram Equalization
    # It improves local contrast by adjusting brightness region by region
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    # Step 2: Apply CLAHE to the grayscale image
    cla = clahe.apply(gray)

    # Step 3: Apply Gaussian blur (soft blur)
    # This removes high-frequency noise but keeps main structures
    blur = cv2.GaussianBlur(cla, (0, 0), 1.2)

    # Step 4: Combine original (enhanced) image with blurred version
    # cv2.addWeighted does a weighted sum: (1.5 * cla - 0.5 * blur)
    # Effect: sharpens edges and increases clarity
    return cv2.addWeighted(cla, 1.5, blur, -0.5, 0)


def small_deskew(img_gray: np.ndarray) -> np.ndarray:
    # Start with the original image as the "best" one
    best, best_var = img_gray, img_gray.var()

    # Try rotating a few small angles left and right
    for ang in (-3, -2, -1, 1, 2, 3):
        h, w = img_gray.shape

        # Build a 2D rotation matrix centered on the image
        M = cv2.getRotationMatrix2D((w/2, h/2), ang, 1.0)

        # Apply the rotation (warpAffine = geometric transform)
        # borderMode=REPLICATE fills missing pixels by copying nearby values
        rot = cv2.warpAffine(img_gray, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        # Compute variance of pixel intensities
        v = rot.var()

        # Higher variance means sharper, less blurry image → better alignment
        if v > best_var:
            best, best_var = rot, v

    return best


def ocr_variants(roi_gray: np.ndarray) -> list[np.ndarray]:
    # Step 1: Correct small tilt in the text region (deskew)
    # OCR works much better if text lines are horizontal
    g = small_deskew(roi_gray)

    # Step 2: Enhance local contrast
    # Makes faint letters stand out more clearly
    g = enhance_contrast(g)

    # Step 3: Otsu's threshold (binary)
    # Automatically decides the best cutoff to split black/white
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Step 4: Inverted Otsu
    # Same as above but swapped colors (white text on black background)
    _, inv = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Step 5: Adaptive Mean threshold
    # Each pixel’s threshold is the average of its neighborhood
    # Useful when lighting is uneven
    mean = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5
    )

    # Step 6: Adaptive Gaussian threshold
    # Like adaptive mean, but weights neighbors using a Gaussian (closer pixels count more)
    gaus = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3
    )

    # Step 7: "Bold" version
    # Dilate the Otsu image to thicken strokes, useful if text is very faint or broken
    bold = cv2.dilate(
        otsu, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), 1
    )

    # Return a list of all prepared variants
    # Each one might give better OCR results depending on text quality
    return [otsu, mean, gaus, bold, inv]


def try_ocr(roi_bgr: np.ndarray) -> str:
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.copyMakeBorder(gray, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
    gray = cv2.resize(gray, (gray.shape[1]*SCALE, gray.shape[0]*SCALE), interpolation=cv2.INTER_CUBIC)
    for prep in ocr_variants(gray):
        for psm in PSM_TRY:
            cfg = f'--oem {OCR_OEM} --psm {psm} -l {OCR_LANGS} -c tessedit_char_whitelist="{WHITELIST}"'
            try:
                out = pytesseract.image_to_string(prep, config=cfg)
            except Exception:
                out = ""
            t = normalize_text(out)
            if t: return t
    return ""

def try_ocr_tokens(roi_bgr: np.ndarray) -> list[str]:
    # Convert the input ROI (region of interest) from color (BGR) to grayscale
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

    # Add a constant border around the image.
    # Reason: OCR sometimes cuts off letters near the edge; border gives breathing space.
    gray = cv2.copyMakeBorder(gray, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)

    # Enlarge the image by a scaling factor.
    # Reason: OCR (Tesseract) works better on larger, clearer text.
    gray = cv2.resize(
        gray,
        (gray.shape[1] * SCALE, gray.shape[0] * SCALE),
        interpolation=cv2.INTER_CUBIC
    )

    texts = []  # will store raw OCR results (normalized)

    # Try OCR on multiple preprocessed variants of the ROI
    for prep in ocr_variants(gray):
        # Try multiple PSM (page segmentation modes) for robustness
        for psm in PSM_TRY:
            # Configure OCR engine:
            # - --oem: OCR Engine mode
            # - --psm: Page segmentation mode
            # - -l: language models (ita+eng, etc.)
            # - tessedit_char_whitelist: only allow certain characters
            cfg = (
                f'--oem {OCR_OEM} --psm {psm} '
                f'-l {OCR_LANGS} '
                f'-c tessedit_char_whitelist="{WHITELIST}"'
            )
            try:
                out = pytesseract.image_to_string(prep, config=cfg)
            except Exception:
                out = ""

            # Normalize the OCR output (lowercase, remove accents/punctuation, etc.)
            t = normalize_text(out)

            # If something meaningful came out, keep it
            if t:
                texts.append(t)

    # Collect tokens from all OCR results
    tokens = set()
    for t in texts:
        tokens.add(t)             # add full phrase as recognized
        tokens.update(t.split())  # also add individual words

    # Remove empty tokens and blacklisted ones
    tokens = {tok for tok in tokens if tok and tok not in BLACKLIST}

    # Return a sorted list of tokens
    return sorted(tokens)


def match_targets_tokens(tokens: Iterable[str], targets_canon: set[str]) -> bool:
    toks = set(tokens)
    if any(tok in targets_canon for tok in toks):
        return True
    return ("soggiorno" in toks and "pranzo" in toks and "soggiorno pranzo" in targets_canon)

def detect_text_boxes(img: np.ndarray) -> list[tuple[int,int,int,int]]:
    # Convert the image from color (BGR) to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Enhance local contrast to make faint text stand out
    gray = enhance_contrast(gray)

    # Apply a morphological "top-hat" filter:
    # highlights small bright regions (like white letters) on darker backgrounds
    top  = cv2.morphologyEx(
        gray,
        cv2.MORPH_TOPHAT,
        cv2.getStructuringElement(cv2.MORPH_RECT, (TOPHAT_KERNEL, TOPHAT_KERNEL))
    )

    # Apply Otsu's threshold:
    # automatically converts grayscale into a clean black/white image
    _, th = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Dilate (thicken) the white regions to reconnect broken letters/words
    dil = cv2.dilate(
        th,
        cv2.getStructuringElement(cv2.MORPH_RECT, (DILATE_KERNEL, DILATE_KERNEL)),
        1
    )

    # Find contours (outlines of connected white regions)
    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out = []
    for c in contours:
        # Get bounding box for each contour
        x, y, w, h = cv2.boundingRect(c)
        area  = w * h                # area of the box
        ratio = w / float(h) if h > 0 else 1e9  # width/height ratio

        # Filter out boxes that are too small/large, weirdly shaped, or wrong height
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            continue
        if not (MIN_H <= h <= MAX_H):
            continue

        # Keep this box
        out.append((x, y, w, h))

    # Return boxes sorted top-to-bottom, then left-to-right
    return sorted(out, key=lambda b: (b[1], b[0]))


def knn_edges(points: np.ndarray, k: int = K_NEIGHBOURS, max_radius_frac: float = MAX_RADIUS_FRAC):
    # If we have fewer than 2 points, we cannot create any edges
    if len(points) < 2:
        return []

    # Find the bounding box of all points (min and max x/y)
    minx, miny = points.min(axis=0)
    maxx, maxy = points.max(axis=0)

    # Compute the diagonal length of the bounding box
    # This gives a "scale" for the whole plan
    diag = math.hypot(maxx - minx, maxy - miny)

    # Define the maximum allowed connection distance
    # (fraction of the diagonal size, e.g., 0.66 * diag)
    max_r = max_radius_frac * diag

    edges = set()  # use a set to avoid duplicate edges

    # Loop through each point
    for i, p in enumerate(points):
        # Compute Euclidean distance from this point to all others
        d = np.linalg.norm(points - p, axis=1)

        # Sort indices of neighbors by distance (skip the first = itself)
        idx = np.argsort(d)[1:k+1]

        # For each of the k nearest neighbors
        for j in idx:
            # Only connect if the distance is within the allowed max radius
            if d[j] <= max_r:
                # Sort indices so (i,j) and (j,i) are treated the same
                a, b = sorted((i, j))
                edges.add((a, b))  # add edge to set

    # Return the edges as a sorted list of pairs (i, j)
    return sorted(edges)


def draw_rect(img, box, color, thick=1):
    x,y,w,h = box
    cv2.rectangle(img, (x-1,y-1), (x+w+1,y+h+1), color, thick)

# ---------- Pipeline per un file ----------
def process_one(path_in: str, targets: Iterable[str], out_root: str = "out") -> None:
    img = cv2.imread(path_in)
    if img is None: raise FileNotFoundError(path_in)

    base_name = os.path.splitext(os.path.basename(path_in))[0]
    out_dir   = os.path.join(out_root, base_name)

    # Clean rebuild per sezione
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    crops_dir = os.path.join(out_dir, "candidates_all")
    os.makedirs(crops_dir, exist_ok=True)

    # --- MAPPING: preparazione file e header ---
    section_n = extract_section_n(base_name)
    map_path  = os.path.join(crops_dir, "candidates_map.txt")

    # crea/azzera il file e scrive solo l'header, poi si appende per ogni crop
    with open(map_path, "w", encoding="utf-8") as f:
        f.write("section_n | image_split_name | ocr | tok\n")

    # 1) base
    cv2.imwrite(os.path.join(out_dir, f"{base_name}_base.png"), img)

    # 2) all_candidates + salvataggio ritagli RAW
    boxes = detect_text_boxes(img)
    allc  = img.copy()
    for i, b in enumerate(boxes):
        x,y,w,h = b
        draw_rect(allc, b, CAND_COLOR, BOX_THICKNESS)
        roi = img[y:y+h, x:x+w]

        # salva il crop RAW (nessuna etichetta disegnata)
        crop_name = f"{i:04d}.png"
        cv2.imwrite(os.path.join(crops_dir, crop_name), roi)

        # OCR + TOK per la mappa (APPEND IMMEDIATO)
        ocr_text = try_ocr(roi)
        tokens   = try_ocr_tokens(roi)
        line_ocr = (ocr_text or "").replace("\n", " ").replace("|", "/").strip()
        line_tok = ", ".join(tokens).replace("|", "/").strip()

        append_map_line(
            map_path,
            f"{section_n} | {crop_name} | {line_ocr} | {line_tok}"
        )

    cv2.imwrite(os.path.join(out_dir, f"{base_name}_all_candidates.png"), allc)

    # 3) selected (token-based)
    targets_canon = {normalize_text(t) for t in targets} | TARGETS_CANON
    kept_boxes, kept_pts = [], []
    for b in boxes:
        x,y,w,h = b
        roi = img[y:y+h, x:x+w]
        toks = try_ocr_tokens(roi)
        if match_targets_tokens(toks, targets_canon):
            kept_boxes.append(b)
            kept_pts.append((x+w/2.0, y+h/2.0))

    selected = img.copy()
    for b in kept_boxes:
        draw_rect(selected, b, SEL_COLOR, BOX_THICKNESS)
    cv2.imwrite(os.path.join(out_dir, f"{base_name}_selected.png"), selected)

    # 4) graph su selected
    pts = np.array(kept_pts, dtype=np.float32)
    graph = selected.copy()
    if len(pts) >= 2:
        edges = knn_edges(pts)
        for (i,j) in edges:
            p1 = (int(pts[i][0]), int(pts[i][1]))
            p2 = (int(pts[j][0]), int(pts[j][1]))
            cv2.line(graph, p1, p2, EDGE_COLOR, 1, cv2.LINE_AA)
        for (cx,cy) in pts:
            cv2.circle(graph, (int(cx), int(cy)), 2, EDGE_COLOR, -1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(out_dir, f"{base_name}_graph_selected.png"), graph)

    print(f"[DONE] {base_name} | candidates: {len(boxes)} | selected: {len(kept_boxes)} | out: {out_dir}")
    print(f"       map: {map_path}")

# ---------- Main ----------
if __name__ == "__main__":
    files = [
        r"C:\projects\extra\PlanimetryAI\PlanParser\debug_image\base_rectangle_section_1.png",
        r"C:\projects\extra\PlanimetryAI\PlanParser\debug_image\base_rectangle_section_2.png",
    ]

    # files = [
    #     r"C:\projects\extra\PlanimetryAI\PlanParser\debug_image\base_rectangle_piano_lines.png"
    # ]

    target_words = [
        "camera","bagno","cucina","sala","soggiorno",
        "ingresso","dis","dis.","disimpegno","corridoio",
        "lavanderia","ripostiglio","balcone","terrazzo",
        "giardino","portico","studio","rip.", "ripostiglio",
        "pranzo", "soggiorno pranzo", "soggiomo", "dranzo", "3gnos"
    ]
    for f in files:
        process_one(f, target_words, out_root="planimetry_output")
