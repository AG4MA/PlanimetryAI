#!/usr/bin/env python3
"""
Pipeline (con logging massivo):
  1) base.png (copia originale)
  2) all_candidates.png (tutti i box in azzurro)
  3) candidates_all/ (tutti i ritagli RAW) + candidates_all/candidates_map.txt (section_n | image_split_name | ocr | tok)
  4) selected.png (SOLO parole target, in verde)
  5) graph_selected.png (grafo KNN sui selected)

Requisiti:
  pip install opencv-python numpy pytesseract
  + Tesseract installato (ita+eng). Se non è nel PATH, imposta pytesseract.pytesseract.tesseract_cmd.

Note logging:
- Log a console e su file rotating in out/<section>/logs/pipeline.log
- Livello default: DEBUG (verbosissimo)
- Ogni step cronometrato
- Per i primi N ritagli salva anche le varianti OCR (per audit)

Suggerimento:
- Esegui una volta per sezione: il log e gli artefatti sono self-contained dentro la cartella di output.

"""

import json
import logging
import math
import os
import re
import shutil
import sys
import time
import traceback
import unicodedata
from collections.abc import Callable, Iterable
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler

import cv2
import numpy as np
import pytesseract

# =========================
# CONFIGURAZIONE GENERALE
# =========================

# Se necessario, scommenta e imposta il path corretto a Tesseract:
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

# ---------- Debug artifacts ----------
SAVE_OCR_VARIANTS_FOR_FIRST_N_CROPS = 10   # salva le immagini dei preprocess OCR per i primi N crop
SAVE_INTERMEDIATE_BINARIES          = True # salva soglie/thresholding delle varianti OCR
LOG_CANDIDATE_TOKENS_LIMIT          = 200  # limite caratteri per log tokens (solo estetica log)
LOG_EVERY_N_CANDIDATES              = 1    # logga ogni N candidati (1 = tutti)

# =========================
# LOGGING UTILITIES
# =========================

def setup_logger(log_dir: str, name: str = "pipeline", level=logging.DEBUG) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Evita duplicazione handler se già configurato
    if logger.handlers:
        return logger

    log_path = os.path.join(log_dir, "pipeline.log")

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))

    # File rotating handler
    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.debug("Logger initialized. Path: %s", log_path)
    return logger

def timeit_step(desc: str) -> Callable:
    """Decoratore per loggare il tempo di esecuzione di uno step."""
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            logger: logging.Logger = kwargs.get("logger") or args[0]  # primo arg in molte funzioni è logger
            start = time.perf_counter()
            logger.debug("▶ START %s", desc)
            try:
                res = fn(*args, **kwargs)
                return res
            except Exception as e:
                logger.exception("❌ ERROR in %s: %s", desc, e)
                raise
            finally:
                dt = (time.perf_counter() - start) * 1000.0
                logger.debug("⏱ END %s (%.1f ms)", desc, dt)
        return wrapper
    return deco

def safe_json(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)

def log_img(path: str, img: np.ndarray, logger: logging.Logger, desc: str):
    """Salva un'immagine e logga dimensioni e path."""
    ok = cv2.imwrite(path, img)
    if ok:
        logger.debug("💾 Saved %s (%dx%d) -> %s", desc, img.shape[1], img.shape[0], path)
    else:
        logger.warning("⚠️ Failed to save %s -> %s", desc, path)

# =========================
# TESTO / TARGET UTILS
# =========================

def append_map_line(path: str, line: str, logger: logging.Logger | None = None) -> None:
    with open(path, "a", encoding="utf-8", buffering=1) as f:
        f.write(line + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    if logger:
        logger.debug("🗺  map_line: %s", line)

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

# =========================
# IMAGING HELPERS
# =========================

def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    # CLAHE + unsharp-like
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cla   = clahe.apply(gray)
    blur  = cv2.GaussianBlur(cla, (0, 0), 1.2)
    return cv2.addWeighted(cla, 1.5, blur, -0.5, 0)

def small_deskew(img_gray: np.ndarray) -> np.ndarray:
    # Prova ±1..±3 gradi, sceglie quello con varianza maggiore
    best, best_var = img_gray, img_gray.var()
    for ang in (-3,-2,-1,1,2,3):
        h,w = img_gray.shape
        M = cv2.getRotationMatrix2D((w/2, h/2), ang, 1.0)
        rot = cv2.warpAffine(img_gray, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        v = rot.var()
        if v > best_var: best, best_var = rot, v
    return best

def ocr_variants(gray_deskewed_enhanced: np.ndarray) -> list[tuple[str, np.ndarray]]:
    # Genera varianti con diversi thresholding
    g = gray_deskewed_enhanced
    _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, inv  = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mean = cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY,31,5)
    gaus = cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,3)
    bold = cv2.dilate(otsu, cv2.getStructuringElement(cv2.MORPH_RECT,(2,2)), 1)
    return [("otsu", otsu), ("mean", mean), ("gaus", gaus), ("bold", bold), ("inv", inv)]

def try_ocr(roi_bgr: np.ndarray, logger: logging.Logger, audit_dir: str | None, crop_idx: int) -> str:
    """OCR con più varianti e PSM; salva eventualmente le immagini di audit."""
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.copyMakeBorder(gray, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
    gray = cv2.resize(gray, (gray.shape[1]*SCALE, gray.shape[0]*SCALE), interpolation=cv2.INTER_CUBIC)

    # Preprocess comuni
    g0 = small_deskew(gray)
    g1 = enhance_contrast(g0)

    out_text = ""

    variants = ocr_variants(g1)
    for vname, prep in variants:
        for psm in PSM_TRY:
            cfg = f'--oem {OCR_OEM} --psm {psm} -l {OCR_LANGS} -c tessedit_char_whitelist="{WHITELIST}"'
            try:
                raw = pytesseract.image_to_string(prep, config=cfg)
            except Exception as e:
                logger.warning("OCR exception (psm=%s, var=%s): %s", psm, vname, e)
                raw = ""
            t = normalize_text(raw)
            logger.debug("OCR (crop=%04d, var=%s, psm=%s): raw='%s' -> norm='%s'",
                         crop_idx, vname, psm, raw.strip().replace("\n"," "), t)

            # Audit immagini delle varianti (solo primi N crop per non esplodere)
            if audit_dir and crop_idx < SAVE_OCR_VARIANTS_FOR_FIRST_N_CROPS and SAVE_INTERMEDIATE_BINARIES:
                var_path = os.path.join(audit_dir, f"{crop_idx:04d}_var_{vname}_psm{psm}.png")
                log_img(var_path, prep, logger, f"OCR variant {vname}/psm{psm}")

            if t:
                out_text = t
                return out_text  # primo testo non vuoto vince (euristica semplice)

    return out_text  # può essere "" se tutto fallisce

def try_ocr_tokens(roi_bgr: np.ndarray, logger: logging.Logger, audit_dir: str | None, crop_idx: int) -> list[str]:
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.copyMakeBorder(gray, PAD, PAD, PAD, PAD, cv2.BORDER_REPLICATE)
    gray = cv2.resize(gray, (gray.shape[1]*SCALE, gray.shape[0]*SCALE), interpolation=cv2.INTER_CUBIC)

    texts = []

    g0 = small_deskew(gray)
    g1 = enhance_contrast(g0)
    variants = ocr_variants(g1)

    for vname, prep in variants:
        for psm in PSM_TRY:
            cfg = f'--oem {OCR_OEM} --psm {psm} -l {OCR_LANGS} -c tessedit_char_whitelist="{WHITELIST}"'
            try:
                raw = pytesseract.image_to_string(prep, config=cfg)
            except Exception as e:
                logger.warning("OCR exception (TOK) (psm=%s, var=%s): %s", psm, vname, e)
                raw = ""
            t = normalize_text(raw)
            if t:
                texts.append(t)
            logger.debug("TOK OCR (crop=%04d, var=%s, psm=%s): raw='%s' -> norm='%s'",
                         crop_idx, vname, psm, raw.strip().replace("\n"," "), t)

            if audit_dir and crop_idx < SAVE_OCR_VARIANTS_FOR_FIRST_N_CROPS and SAVE_INTERMEDIATE_BINARIES:
                var_path = os.path.join(audit_dir, f"{crop_idx:04d}_TOK_var_{vname}_psm{psm}.png")
                log_img(var_path, prep, logger, f"TOK variant {vname}/psm{psm}")

    tokens = set()
    for t in texts:
        tokens.add(t)             # frase intera
        tokens.update(t.split())  # singole parole

    tokens = {tok for tok in tokens if tok and tok not in BLACKLIST}
    tokens_sorted = sorted(tokens)

    # Log compattato per non esplodere il file
    joined = ", ".join(tokens_sorted)
    if len(joined) > LOG_CANDIDATE_TOKENS_LIMIT:
        joined = joined[:LOG_CANDIDATE_TOKENS_LIMIT] + "…"
    logger.debug("TOK (crop=%04d): %s", crop_idx, joined)

    return tokens_sorted

def match_targets_tokens(tokens: Iterable[str], targets_canon: set[str]) -> bool:
    toks = set(tokens)
    if any(tok in targets_canon for tok in toks):
        return True
    return ("soggiorno" in toks and "pranzo" in toks and "soggiorno pranzo" in targets_canon)

@timeit_step("detect_text_boxes")
def detect_text_boxes(img: np.ndarray, logger: logging.Logger, audit_dir: str | None = None) -> list[tuple[int,int,int,int]]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if audit_dir:
        log_img(os.path.join(audit_dir, "00_gray.png"), gray, logger, "gray")

    gray2 = enhance_contrast(gray)
    if audit_dir:
        log_img(os.path.join(audit_dir, "01_gray_enhanced.png"), gray2, logger, "gray_enhanced")

    top  = cv2.morphologyEx(gray2, cv2.MORPH_TOPHAT,
                            cv2.getStructuringElement(cv2.MORPH_RECT,(TOPHAT_KERNEL,TOPHAT_KERNEL)))
    if audit_dir:
        log_img(os.path.join(audit_dir, "02_tophat.png"), top, logger, "tophat")

    _, th = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if audit_dir:
        log_img(os.path.join(audit_dir, "03_otsu.png"), th, logger, "tophat_otsu")

    dil   = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_RECT,(DILATE_KERNEL,DILATE_KERNEL)), 1)
    if audit_dir:
        log_img(os.path.join(audit_dir, "04_dilate.png"), dil, logger, "dilate")

    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x,y,w,h = cv2.boundingRect(c)
        area  = w*h
        ratio = w/float(h) if h>0 else 1e9
        # Applicazione filtri
        pass_area   = (MIN_AREA <= area <= MAX_AREA)
        pass_ratio  = (MIN_RATIO <= ratio <= MAX_RATIO)
        pass_height = (MIN_H <= h <= MAX_H)
        if pass_area and pass_ratio and pass_height:
            boxes.append((x,y,w,h))
    boxes_sorted = sorted(boxes, key=lambda b: (b[1], b[0]))

    logger.debug("Contours: %d | Boxes (filtered): %d", len(contours), len(boxes_sorted))
    return boxes_sorted

def draw_rect(img, box, color, thick=1):
    x,y,w,h = box
    cv2.rectangle(img, (x-1,y-1), (x+w+1,y+h+1), color, thick)

# =========================
# PIPELINE PER UN FILE
# =========================

def process_one(path_in: str, targets: Iterable[str], out_root: str = "out") -> None:
    # --- Preparazione output / logger
    base_name = os.path.splitext(os.path.basename(path_in))[0]
    out_dir   = os.path.join(out_root, base_name)

    # Clean rebuild
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    logs_dir  = os.path.join(out_dir, "logs")
    crops_dir = os.path.join(out_dir, "candidates_all")
    audit_dir = os.path.join(out_dir, "audit")
    os.makedirs(crops_dir, exist_ok=True)
    os.makedirs(audit_dir, exist_ok=True)

    logger = setup_logger(logs_dir)

    # --- Header diagnostico
    logger.info("====== PIPELINE START (%s) ======", datetime.now().isoformat(timespec="seconds"))
    logger.info("Input path: %s", path_in)
    logger.info("Output dir: %s", out_dir)
    logger.info("Versions: cv2=%s | numpy=%s | pytesseract=%s", cv2.__version__, np.__version__, pytesseract.get_tesseract_version())
    logger.info("Params detection: area=[%s,%s], ratio=[%.2f,%.2f], h=[%d,%d], kernels(top=%d, dil=%d)",
                MIN_AREA, MAX_AREA, MIN_RATIO, MAX_RATIO, MIN_H, MAX_H, TOPHAT_KERNEL, DILATE_KERNEL)
    logger.info("Params OCR: langs=%s, oem=%d, psm=%s, scale=%d, pad=%d", OCR_LANGS, OCR_OEM, PSM_TRY, SCALE, PAD)
    logger.info("Targets canon size: %d | Blacklist size: %d", len(TARGETS_CANON), len(BLACKLIST))

    # --- MAPPING: file + header
    section_n = extract_section_n(base_name)
    map_path  = os.path.join(crops_dir, "candidates_map.txt")
    with open(map_path, "w", encoding="utf-8") as f:
        f.write("section_n | image_split_name | ocr | tok\n")
    logger.debug("Mapping file initialized: %s", map_path)

    # --- Caricamento immagine
    img = cv2.imread(path_in)
    if img is None:
        logger.error("Immagine non trovata o illeggibile: %s", path_in)
        raise FileNotFoundError(path_in)

    H, W = img.shape[:2]
    logger.info("Image loaded: %s (%dx%d)", path_in, W, H)

    # 1) base
    base_path = os.path.join(out_dir, f"{base_name}_base.png")
    log_img(base_path, img, logger, "base")

    # 2) all_candidates + salvataggio ritagli RAW
    try:
        boxes = detect_text_boxes(img, logger=logger, audit_dir=audit_dir)
    except Exception:
        logger.exception("Errore in detect_text_boxes")
        raise

    allc  = img.copy()
    candidates_count = 0

    for i, b in enumerate(boxes):
        x,y,w,h = b
        area = w*h
        ratio = w / float(h) if h else 1e9

        # Disegno box candidato
        draw_rect(allc, b, CAND_COLOR, BOX_THICKNESS)

        roi = img[y:y+h, x:x+w]
        crop_name = f"{i:04d}.png"
        crop_path = os.path.join(crops_dir, crop_name)
        log_img(crop_path, roi, logger, f"crop_raw #{i}")

        # Audit opzionale: salva anche ROI grigia per i primi N crop
        if i < SAVE_OCR_VARIANTS_FOR_FIRST_N_CROPS:
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            log_img(os.path.join(audit_dir, f"{i:04d}_roi_gray.png"), roi_gray, logger, f"roi_gray #{i}")

        # OCR singolo + tokens
        ocr_text = try_ocr(roi, logger=logger, audit_dir=audit_dir, crop_idx=i)
        tokens   = try_ocr_tokens(roi, logger=logger, audit_dir=audit_dir, crop_idx=i)
        line_ocr = (ocr_text or "").replace("\n", " ").replace("|", "/").strip()
        line_tok = ", ".join(tokens).replace("|", "/").strip()

        append_map_line(map_path, f"{section_n} | {crop_name} | {line_ocr} | {line_tok}", logger=logger)

        candidates_count += 1

        # Log dettagliato per ogni candidato (o ogni N)
        if (i % LOG_EVERY_N_CANDIDATES) == 0:
            logger.debug(
                "CANDIDATE #%04d: pos=(%d,%d) size=(%dx%d) area=%d ratio=%.3f | OCR='%s' | TOK=%s",
                i, x, y, w, h, area, ratio, line_ocr, line_tok[:LOG_CANDIDATE_TOKENS_LIMIT] + ("…" if len(line_tok) > LOG_CANDIDATE_TOKENS_LIMIT else "")
            )

    allcand_path = os.path.join(out_dir, f"{base_name}_all_candidates.png")
    log_img(allcand_path, allc, logger, "all_candidates")

    # 3) selected (token-based)
    targets_canon = {normalize_text(t) for t in targets} | TARGETS_CANON
    logger.info("Targets (merged) size: %d", len(targets_canon))

    kept_boxes, kept_pts = [], []
    for b in boxes:
        x,y,w,h = b
        roi = img[y:y+h, x:x+w]
        toks = try_ocr_tokens(roi, logger=logger, audit_dir=None, crop_idx=9999)  # per la selezione basta 1 pass
        is_match = match_targets_tokens(toks, targets_canon)
        logger.debug("SELECT test box(%d,%d,%d,%d): match=%s | tokens=%s", x,y,w,h, is_match, toks)
        if is_match:
            kept_boxes.append(b)
            kept_pts.append((x+w/2.0, y+h/2.0))

    selected = img.copy()
    for b in kept_boxes:
        draw_rect(selected, b, SEL_COLOR, BOX_THICKNESS)
    selected_path = os.path.join(out_dir, f"{base_name}_selected.png")
    log_img(selected_path, selected, logger, "selected")

    # 4) graph su selected
    pts = np.array(kept_pts, dtype=np.float32)
    graph = selected.copy()
    if len(pts) >= 2:
        # KNN edges
        edges = knn_edges(pts)
        logger.debug("Graph: points=%d, edges=%d", len(pts), len(edges))
        for (i,j) in edges:
            p1 = (int(pts[i][0]), int(pts[i][1]))
            p2 = (int(pts[j][0]), int(pts[j][1]))
            cv2.line(graph, p1, p2, EDGE_COLOR, 1, cv2.LINE_AA)
        for (cx,cy) in pts:
            cv2.circle(graph, (int(cx), int(cy)), 2, EDGE_COLOR, -1, cv2.LINE_AA)
    else:
        logger.info("Graph: insufficient points (%d) -> no edges", len(pts))

    graph_path = os.path.join(out_dir, f"{base_name}_graph_selected.png")
    log_img(graph_path, graph, logger, "graph_selected")

    # --- SUMMARY
    logger.info("[DONE] %s | candidates: %d | selected: %d | out: %s", base_name, len(boxes), len(kept_boxes), out_dir)
    logger.info("       map: %s", map_path)
    logger.info("====== PIPELINE END ======")

# =========================
# KNN EDGES
# =========================

def knn_edges(points: np.ndarray, k: int = K_NEIGHBOURS, max_radius_frac: float = MAX_RADIUS_FRAC):
    if len(points) < 2: return []
    minx, miny = points.min(axis=0); maxx, maxy = points.max(axis=0)
    diag = math.hypot(maxx - minx, maxy - miny)
    max_r = max_radius_frac * diag
    edges=set()
    for i,p in enumerate(points):
        d = np.linalg.norm(points - p, axis=1)
        idx = np.argsort(d)[1:k+1]
        for j in idx:
            if d[j] <= max_r:
                a,b = sorted((i,j)); edges.add((a,b))
    return sorted(edges)

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    try:
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

        out_root = "planimetry_output"

        # Log generale di bootstrap (prima che i per-file creino i loro logger)
        print("[BOOT] Python:", sys.version.replace("\n"," "))
        print("[BOOT] OpenCV:", cv2.__version__, "| numpy:", np.__version__)
        try:
            print("[BOOT] Tesseract:", pytesseract.get_tesseract_version())
        except Exception as e:
            print("[BOOT] Tesseract version retrieval failed:", e)

        for f in files:
            process_one(f, target_words, out_root=out_root)

    except Exception as e:
        # Fallback log su stderr, così non perdi il trace se il logger non è ancora pronto
        sys.stderr.write("FATAL: " + str(e) + "\n")
        traceback.print_exc()
        sys.exit(1)
