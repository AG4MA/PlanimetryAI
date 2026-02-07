"""
Step 1: PDF to Image.

Loads a PDF page and renders it to a high-resolution BGR numpy array.
Also handles plain image files (PNG, JPG) as pass-through.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional
import logging


def pdf_to_image(
    file_path: Path,
    page: int = 0,
    dpi: int = 300,
    logger: Optional[logging.Logger] = None,
) -> np.ndarray:
    """
    Load a PDF or image file and return a BGR numpy array.

    Args:
        file_path: Path to PDF or image file.
        page: PDF page index (0-based). Ignored for images.
        dpi: Rendering resolution for PDFs. 300 recommended.
        logger: Optional logger.

    Returns:
        np.ndarray in BGR format (OpenCV convention).
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(file_path, page, dpi, logger)
    else:
        return _load_image(file_path, logger)


def _load_pdf(
    pdf_path: Path,
    page: int,
    dpi: int,
    logger: Optional[logging.Logger],
) -> np.ndarray:
    """Render a PDF page to BGR numpy array using PyMuPDF."""
    import fitz  # PyMuPDF

    if logger:
        logger.info("  Loading PDF: %s (page=%d, dpi=%d)", pdf_path.name, page, dpi)

    doc = fitz.open(str(pdf_path))
    if page >= len(doc):
        raise ValueError(f"Page {page} does not exist (PDF has {len(doc)} pages)")

    pdf_page = doc[page]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = pdf_page.get_pixmap(matrix=mat)

    # Convert to numpy array (RGB)
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)

    # Convert RGB -> BGR for OpenCV
    if pix.n == 4:  # RGBA
        bgr = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
    elif pix.n == 3:  # RGB
        bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    else:  # Grayscale
        bgr = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)

    doc.close()

    if logger:
        logger.info("  Rendered: %dx%d pixels", bgr.shape[1], bgr.shape[0])

    return bgr


def _load_image(
    image_path: Path,
    logger: Optional[logging.Logger],
) -> np.ndarray:
    """Load a plain image file."""
    if logger:
        logger.info("  Loading image: %s", image_path.name)

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    if logger:
        logger.info("  Loaded: %dx%d pixels", img.shape[1], img.shape[0])

    return img
