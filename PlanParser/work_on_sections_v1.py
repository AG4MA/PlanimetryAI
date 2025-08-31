#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seleziona SOLO le parole indicate e costruisce un grafo tra di esse.

Input hardcoded:
  C:\projects\extra\PlanimetryAI\base_rectangle_section_1.png
  C:\projects\extra\PlanimetryAI\base_rectangle_section_2.png

Output per ciascun file:
  *_selected.png         -> solo i box delle parole target (verde)
  *_graph_selected.png   -> come sopra + grafo (archi KNN)

Requisiti:
  pip install opencv-python numpy pytesseract
"""

import os, math, unicodedata
from typing import List, Tuple
import cv2
import numpy as np

# ---- Parametri detection (come nelle versioni efficaci) ----
MIN_AREA, MAX_AREA = 100, 6000
MIN_RATIO, MAX_RATIO = 1.2, 10.0
MIN_H, MAX_H       = 8, 40
TOPHAT_KERNEL      = 5
DILATE_KERNEL      = 3
BOX_THICKNESS      = 1

# ---- Grafo ----
K_NEIGHBOURS     = 4
MAX_RADIUS_FRAC  = 0.66     # raggio max = 66% della diagonale dei punti
NODE_COLOR       = (0, 200, 0)     # verde
EDGE_COLOR       = (255, 128, 0)   # arancione

# ---- OCR ----
try:
    import pytesseract
    TESS_AVAILABLE = True
except Exception:
    TESS_AVAILABLE = False

OCR_LANG = "ita"  # italiano
OCR_PSM  = 7     # riga singola
OCR_OEM  = 3

# ---- Funzioni utili ----
def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """CLAHE + unsharp per esaltare testi chiari/sottili."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cla   = clahe.apply(gray)
    blur  = cv2.GaussianBlur(cla, (0, 0), 1.2)
    sharp = cv2.addWeighted(cla, 1.5, blur, -0.5, 0)
    return sharp

def detect_text_boxes(img: np.ndarray) -> List[Tuple[int,int,int,int]]:
    """Box candidati tramite morfologia + filtri geometrici."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = enhance_contrast(gray)
    top  = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
                            cv2.getStructuringElement(cv2.MORPH_RECT,(TOPHAT_KERNEL,TOPHAT_KERNEL)))
    _, th = cv2.threshold(top, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dil   = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_RECT,(DILATE_KERNEL,DILATE_KERNEL)), 1)
    contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        x,y,w,h = cv2.boundingRect(c)
        area = w*h
        ratio = w/float(h) if h>0 else 1e6
        if not (MIN_AREA <= area <= MAX_AREA): continue
        if not (MIN_RATIO <= ratio <= MAX_RATIO): continue
        if not (MIN_H <= h <= MAX_H): continue
        out.append((x,y,w,h))
    return sorted(out, key=lambda b: (b[1], b[0]))

def ocr_text(roi_bgr: np.ndarray) -> str:
    """OCR sul ROI (upscale + binarizzazione). Ritorna lower senza accenti."""
    if not TESS_AVAILABLE:
        return ""
    scale = 3
    roi = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    roi = enhance_contrast(roi)
    roi = cv2.resize(roi, (roi.shape[1]*scale, roi.shape[0]*scale), interpolation=cv2.INTER_CUBIC)
    _, roi = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    try:
        txt = pytesseract.image_to_string(roi, lang=OCR_LANG, config=f"--oem {OCR_OEM} --psm {OCR_PSM}")
    except Exception:
        return ""
    return normalize_text(txt)

def normalize_text(s: str) -> str:
    """lowercase + rimozione accenti/spazi extra."""
    s = s.strip().lower()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    s = " ".join(s.split())
    return s

def match_targets(text: str, targets_norm: List[str]) -> bool:
    """Match esatto o contenuto (robusto a spazi/accents)."""
    if not text:
        return False
    for t in targets_norm:
        if t == text or t in text:
            return True
    return False

def centers_from_boxes(boxes: List[Tuple[int,int,int,int]]) -> np.ndarray:
    return np.array([(x + w/2.0, y + h/2.0) for (x,y,w,h) in boxes], dtype=np.float32)

def knn_edges(points: np.ndarray, k: int = K_NEIGHBOURS, max_radius_frac: float = MAX_RADIUS_FRAC):
    if len(points) < 2:
        return []
    minx, miny = points.min(axis=0)
    maxx, maxy = points.max(axis=0)
    diag = math.hypot(maxx - minx, maxy - miny)
    max_r = max_radius_frac * diag
    edges = set()
    for i, p in enumerate(points):
        d = np.linalg.norm(points - p, axis=1)
        idx = np.argsort(d)[1:k+1]
        for j in idx:
            if d[j] <= max_r:
                a, b = sorted((i, j))
                edges.add((a, b))
    return sorted(edges)

def process_one(path_in: str, targets: List[str]) -> None:
    """Seleziona SOLO i box che matchano le parole target e costruisce il grafo."""
    img = cv2.imread(path_in)
    if img is None:
        raise FileNotFoundError(path_in)

    # normalizza targets
    targets_norm = [normalize_text(t) for t in targets if t.strip()]

    # 1) candidati
    boxes = detect_text_boxes(img)

    # 2) OCR + filtro SOLO match target
    kept_boxes = []
    for (x,y,w,h) in boxes:
        roi = img[y:y+h, x:x+w]
        txt = ocr_text(roi)
        if match_targets(txt, targets_norm):
            kept_boxes.append((x,y,w,h))

    # 3) disegno selezione
    base = img.copy()
    for (x,y,w,h) in kept_boxes:
        cv2.rectangle(base, (x-1,y-1), (x+w+1, y+h+1), NODE_COLOR, BOX_THICKNESS)

    root, ext = os.path.splitext(path_in)
    out_sel   = root + "_selected.png"
    out_graph = root + "_graph_selected.png"
    cv2.imwrite(out_sel, base)

    # 4) grafo
    pts = centers_from_boxes(kept_boxes)
    edges = knn_edges(pts)

    graph = base.copy()
    for (i,j) in edges:
        p1 = (int(pts[i][0]), int(pts[i][1]))
        p2 = (int(pts[j][0]), int(pts[j][1]))
        cv2.line(graph, p1, p2, EDGE_COLOR, 1, cv2.LINE_AA)
    for (cx,cy) in pts:
        cv2.circle(graph, (int(cx), int(cy)), 2, EDGE_COLOR, -1, cv2.LINE_AA)

    cv2.imwrite(out_graph, graph)

    print(f"[DONE] {os.path.basename(path_in)} | kept: {len(kept_boxes)} | "
          f"saved: {os.path.basename(out_sel)}, {os.path.basename(out_graph)}")

def main():
    # --- file hardcoded (come da tua richiesta) ---
    files = [
        r"C:\projects\extra\PlanimetryAI\base_rectangle_section_1.png",
        r"C:\projects\extra\PlanimetryAI\base_rectangle_section_2.png",
    ]
    # --- PAROLE DA CERCARE (inserisci qui) ---
    target_words = [
        "camera",
        "bagno",
        "cucina",
        "salotto",
        "studio",
        "ingresso",
        "disimpegno",
        "corridoio",
        "lavanderia",
        "ripostiglio",
        "soggiorno",
        "balcone",
        "terrazzo",
        "giardino",
        "dis",
        "dis.",
        "portico",
        # aggiungi altre parole se vuoi…
    ]

    if not TESS_AVAILABLE:
        print("[ATTENZIONE] pytesseract/tesseract non disponibile: senza OCR non verranno trovati match.")

    for f in files:
        process_one(f, target_words)

if __name__ == "__main__":
    main()
