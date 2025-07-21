import cv2
import numpy as np
import fitz
from PIL import Image
import io

def render_pdf_to_gray(pdf_path, zoom=2.0):
    """
    Carica la prima pagina del PDF e restituisce un array grayscale.
    """
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
    return np.array(Image.open(io.BytesIO(pix.tobytes("png"))))

def detect_hough_lines(gray, min_len_ratio=0.3):
    """
    Applica Canny + HoughLinesP per ottenere liste di:
    - horiz: linee quasi orizzontali (y, x0, x1)
    - vert: linee quasi verticali  (x, y0, y1)
    """
    h, w = gray.shape
    edges = cv2.Canny(gray, 50, 150)
    min_len = int(min(w, h) * min_len_ratio)
    raw = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80,
                          minLineLength=min_len, maxLineGap=10)
    horiz, vert = [], []
    if raw is not None:
        for x0,y0,x1,y1 in raw[:,0]:
            if abs(y1-y0) <= 2:           # orizzontale
                horiz.append((y0, min(x0,x1), max(x0,x1)))
            elif abs(x1-x0) <= 2:         # verticale
                vert.append((x0, min(y0,y1), max(y0,y1)))
    return horiz, vert

def trace_side(center, horiz, vert, direction, img_shape):
    """
    Dato il centro e le liste horiz/vert, estende:
    - direction='left' o 'right'
    Ritorna (x, y) del lato trovato o fallback al bordo.
    """
    w, h = img_shape[1], img_shape[0]
    cx, cy = center
    best = None
    best_len = -1

    for y, x0, x1 in horiz:
        if abs(y - cy) > 2: continue
        # controlla che la linea copra il centro
        if not (x0 <= cx <= x1): continue

        # determinare il punto di espansione
        x_bar = x0 if direction=='left' else x1
        # cerca la verticale più lunga che passi per (x_bar,y)
        for xv, y0, y1 in vert:
            if abs(xv - x_bar) <= 2 and y0 <= y <= y1:
                length = y1 - y0
                if length > best_len:
                    best_len = length
                    best = (x_bar, y)

    # fallback: bordo pagina
    if best is None:
        return (0, cy) if direction=='left' else (w-1, cy)
    return best

def build_frame(gray):
    """
    Esegue:
    1. trova centro
    2. estrae horiz/vert
    3. traccia left/right/top/bottom con fallback
    4. salva debug di ogni step e del rettangolo finale
    """
    h, w = gray.shape
    center = (w//2, h//2)

    # debug: centro
    dbg = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.circle(dbg, center, 5, (255,0,0), -1)
    cv2.imwrite("debug_center.png", dbg)

    # 1) estrai linee Hough
    horiz, vert = detect_hough_lines(gray)

    # 2) left & right
    left_pt  = trace_side(center, horiz, vert, 'left',  gray.shape)
    right_pt = trace_side(center, horiz, vert, 'right', gray.shape)

    # Rotazione per top/bottom (scambiamo x<->y)
    horiz_r = [(x, y0, y1) for x,y0,y1 in vert]
    vert_r  = [(y, x0, x1) for y,x0,x1 in horiz]
    center_r = (center[1], center[0])

    # 3) top & bottom
    top_pt    = trace_side(center_r, horiz_r, vert_r, 'left',  gray.T.shape)
    bottom_pt = trace_side(center_r, horiz_r, vert_r, 'right', gray.T.shape)

    # ricostruisci coordinate finali
    x0, _ = left_pt
    x1, _ = right_pt
    _, y0 = top_pt
    _, y1 = bottom_pt

    # debug: disegna i lati
    dbg2 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.line(dbg2, (x0,0),(x0,h),(0,255,255),2)
    cv2.line(dbg2, (x1,0),(x1,h),(0,255,255),2)
    cv2.line(dbg2, (0,y0),(w,y0),(0,255,255),2)
    cv2.line(dbg2, (0,y1),(w,y1),(0,255,255),2)
    cv2.imwrite("debug_sides.png", dbg2)

    # rettangolo finale
    final = dbg2.copy()
    cv2.rectangle(final, (x0,y0),(x1,y1),(0,0,255),2)
    cv2.imwrite("debug_frame_final.png", final)

    print(f"Frame: x0={x0}, y0={y0}, x1={x1}, y1={y1}")
    return x0, y0, x1, y1

if __name__ == "__main__":
    pdf_path = "./data/scheda_catastale.pdf"
    gray = render_pdf_to_gray(pdf_path)
    build_frame(gray)
