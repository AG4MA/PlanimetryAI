import fitz  # PyMuPDF
import os
from typing import Tuple
import csv
from datetime import datetime

def log_parsing_result(pdf_path: str, pdf_type: str, method: str):
    log_path = "parsing_log.csv"
    file_exists = os.path.isfile(log_path)
    with open(log_path, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "filename", "pdf_type", "method"])
        writer.writerow([
            datetime.now().isoformat(timespec='seconds'),
            os.path.basename(pdf_path),
            pdf_type,
            method
        ])

def detect_with_pymupdf(pdf_path: str) -> Tuple[bool, str]:
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        drawings = page.get_drawings()
        texts = page.get_text("blocks")
        if drawings or texts:
            print("[✓] PyMuPDF ha trovato contenuto grafico o testuale.")
            return True, "pymupdf"
        else:
            print("[×] PyMuPDF non ha trovato nulla.")
            return False, "pymupdf"
    except Exception as e:
        print(f"[!] Errore PyMuPDF: {e}")
        return False, "pymupdf"

def detect_with_pdfplumber(pdf_path: str) -> Tuple[bool, str]:
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[0]
            if page.chars or page.lines or page.rects:
                print("[✓] pdfplumber ha trovato elementi.")
                return True, "pdfplumber"
            else:
                print("[×] pdfplumber non ha trovato nulla.")
                return False, "pdfplumber"
    except Exception as e:
        print(f"[!] Errore pdfplumber: {e}")
        return False, "pdfplumber"

def fallback_ocr_mode(pdf_path: str) -> Tuple[bool, str]:
    try:
        import pytesseract
        import cv2
        from PIL import Image
        doc = fitz.open(pdf_path)
        pix = doc[0].get_pixmap(dpi=200)
        img_path = "ocr_fallback.png"
        pix.save(img_path)

        image = cv2.imread(img_path)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)

        if len(text.strip()) > 10:
            print("[✓] OCR ha riconosciuto del testo.")
            return True, "ocr"
        else:
            print("[×] OCR non ha riconosciuto nulla.")
            return False, "ocr"
    except Exception as e:
        print(f"[!] Errore OCR: {e}")
        return False, "ocr"

def robust_parse_entrypoint(pdf_path: str):
    print("===[ Robust Planimetry Parser ]===")
    for method in [detect_with_pymupdf, detect_with_pdfplumber, fallback_ocr_mode]:
        success, name = method(pdf_path)
        if success:
            pdf_type = "vettoriale" if name in ["pymupdf", "pdfplumber"] else "raster"
            log_parsing_result(pdf_path, pdf_type, name)
            print(f"\n➡️ Metodo riuscito: {name}\n")
            return
    log_parsing_result(pdf_path, "non_identificato", "fallito")
    print("\n❌ Nessun metodo ha funzionato. File non parsificabile in automatico.")


# Esegui solo se lanciato direttamente
if __name__ == "__main__":
    robust_parse_entrypoint("./data/scheda_catastale.pdf")
