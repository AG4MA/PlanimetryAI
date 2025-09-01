import cv2
import numpy as np
import fitz
from PIL import Image
import io
import sys
import argparse

def render_pdf_to_image(pdf_path, zoom=2.0):
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.open(io.BytesIO(pix.tobytes("png")))

def detect_largest_rectangle(image, split_anchor="up"):
    cv_image = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(cv_image, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    max_area = 0
    best_rect = None

    for cnt in contours:
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            if area > max_area:
                max_area = area
                best_rect = (x, y, w, h)

    if best_rect:
        x, y, w, h = best_rect
        cv2.rectangle(cv_image, (x, y), (x + w, y + h), (0, 255, 0), 3)
        print(f"✅ Trovato rettangolo più grande: x={x}, y={y}, w={w}, h={h}")
    else:
        print("❌ Nessun rettangolo rilevato.")

    debug_path = "./debug_image/largest_rect_debug.png"
    cv2.imwrite(debug_path, cv2.cvtColor(cv_image, cv2.COLOR_RGB2BGR))
    print(f"Salvataggio immagine: {debug_path}")

    # Dopo il debug, tenta lo split dei piani
    try:
        try:
            from PlanParser.define_floor_v2 import define_floor as _run_define_floor
        except Exception:  # pragma: no cover
            from define_floor_v2 import define_floor as _run_define_floor
        result = _run_define_floor(
            debug_image_path=debug_path,
            output_cropped_path="./debug_image/base_rectangle.png",
            split_anchor=split_anchor,
        )
        if result and result.get("floor"):
            print(f"Risultato piano: {result['floor']} (conf {result.get('confidence'):.2f})")
        else:
            print("Nessuna etichetta piano trovata.")
    except Exception as e:  # pragma: no cover
        print(f"⚠️ Errore durante la definizione del piano: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rileva rettangolo e split per piani.")
    parser.add_argument("--pdf", default="./data/scheda_catastale.pdf")
    parser.add_argument("--zoom", type=float, default=2.0)
    parser.add_argument("--anchor", choices=["up", "down"], default="up",
                        help="Posizione della linea rispetto alla scritta 'piano': up= sopra, down= sotto.")
    args = parser.parse_args()

    image = render_pdf_to_image(args.pdf, zoom=args.zoom)
    detect_largest_rectangle(image, split_anchor=args.anchor)
