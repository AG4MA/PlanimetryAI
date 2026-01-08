"""
PDF to Image Conversion
=======================
Handles PDF rendering to images with proper scaling.
"""

import io
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def render_pdf_page(
    pdf_path: str | Path,
    page_num: int = 0,
    zoom: float = 2.0,
    dpi: int = 150
) -> np.ndarray | None:
    """
    Render a PDF page to a numpy array (BGR format for OpenCV).

    Args:
        pdf_path: Path to the PDF file
        page_num: Page number (0-indexed)
        zoom: Zoom factor for rendering
        dpi: Base DPI for rendering

    Returns:
        numpy array in BGR format, or None on failure
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        if page_num >= len(doc):
            logger.error(f"Page {page_num} does not exist in PDF (has {len(doc)} pages)")
            return None

        page = doc.load_page(page_num)

        # Create transformation matrix with zoom
        mat = fitz.Matrix(zoom, zoom)

        # Render to pixmap
        pix = page.get_pixmap(matrix=mat, dpi=dpi)

        # Convert to PIL Image then to numpy
        img_data = pix.tobytes("png")
        pil_image = Image.open(io.BytesIO(img_data))

        # Convert to numpy array (RGB)
        img_array = np.array(pil_image.convert("RGB"))

        # Convert RGB to BGR for OpenCV
        import cv2
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        doc.close()

        logger.info(f"Rendered PDF page {page_num}: {img_bgr.shape[1]}x{img_bgr.shape[0]} px")
        return img_bgr

    except Exception as e:
        logger.error(f"Failed to render PDF: {e}")
        return None


def get_pdf_page_count(pdf_path: str | Path) -> int:
    """Get the number of pages in a PDF."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        logger.error(f"Failed to get PDF page count: {e}")
        return 0


def render_all_pages(
    pdf_path: str | Path,
    zoom: float = 2.0
) -> list[np.ndarray]:
    """Render all pages of a PDF to images."""
    page_count = get_pdf_page_count(pdf_path)
    images = []

    for i in range(page_count):
        img = render_pdf_page(pdf_path, page_num=i, zoom=zoom)
        if img is not None:
            images.append(img)

    return images


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """
    Extract embedded text from PDF (if available).
    This is faster than OCR when text is embedded.
    """
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        text_parts = []

        for page in doc:
            text = page.get_text()
            if text:
                text_parts.append(text)

        doc.close()
        return "\n".join(text_parts)

    except Exception as e:
        logger.warning(f"Failed to extract PDF text: {e}")
        return ""


def get_pdf_metadata(pdf_path: str | Path) -> dict:
    """Extract metadata from PDF."""
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        metadata = doc.metadata or {}

        # Add page info
        if len(doc) > 0:
            page = doc[0]
            rect = page.rect
            metadata['page_width'] = rect.width
            metadata['page_height'] = rect.height
            metadata['page_count'] = len(doc)

        doc.close()
        return metadata

    except Exception as e:
        logger.warning(f"Failed to get PDF metadata: {e}")
        return {}
