"""
OCR Engine Abstraction
======================
Provides a unified interface for multiple OCR backends.
Falls back gracefully when primary OCR is unavailable.
"""

from __future__ import annotations

import logging
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    ImageArray = NDArray[np.uint8]
else:
    ImageArray = Any

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Structured OCR result."""
    text: str
    confidence: float
    bbox: tuple[int, int, int, int] | None = None  # x, y, w, h

    @property
    def normalized_text(self) -> str:
        """Return normalized, cleaned text."""
        return normalize_text(self.text)


def normalize_text(s: str) -> str:
    """Normalize text for comparison: lowercase, remove accents, clean spaces."""
    if not s:
        return ""
    # NFD decomposition to separate accents
    s = unicodedata.normalize("NFD", s)
    # Remove combining characters (accents)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.lower()
    s = s.replace("-", " ")
    # Keep only alphanumeric and basic punctuation
    s = "".join(ch for ch in s if ch.isalnum() or ch in " ._/")
    # Normalize whitespace
    s = " ".join(s.split())
    # Remove trailing periods from abbreviations
    if s.endswith(".") and len(s) <= 5:
        s = s[:-1]
    return s.strip()


class OCREngine(ABC):
    """Abstract base class for OCR engines."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this OCR engine is available."""
        pass

    @abstractmethod
    def recognize(self, image: ImageArray, lang: str = "ita+eng") -> list[OCRResult]:
        """Perform OCR on an image, return list of results."""
        pass

    @abstractmethod
    def recognize_text(self, image: ImageArray, lang: str = "ita+eng") -> str:
        """Perform OCR and return combined text."""
        pass


class TesseractEngine(OCREngine):
    """Tesseract OCR engine wrapper."""

    def __init__(self, tesseract_path: str | None = None):
        self._available = None
        self._tesseract_path = tesseract_path

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            import pytesseract  # type: ignore[import-untyped]
            if self._tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = self._tesseract_path
            # Test if tesseract is actually callable
            pytesseract.get_tesseract_version()
            self._available = True
            logger.info("Tesseract OCR is available")
        except Exception as e:
            logger.warning(f"Tesseract not available: {e}")
            self._available = False

        return self._available

    def _preprocess(self, image: ImageArray) -> list[ImageArray]:
        """Generate multiple preprocessed variants for better OCR."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        variants = [gray]

        # CLAHE enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        variants.append(enhanced)

        # Otsu thresholding
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)

        # Inverted Otsu (for light text on dark)
        _, otsu_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        variants.append(otsu_inv)

        # Adaptive threshold
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10
        )
        variants.append(adaptive)

        return variants

    def recognize(self, image: ImageArray, lang: str = "ita+eng") -> list[OCRResult]:
        if not self.is_available():
            return []

        import pytesseract  # type: ignore[import-untyped]
        results: list[OCRResult] = []

        try:
            # Get word-level bounding boxes
            data = pytesseract.image_to_data(
                image, lang=lang, config="--psm 6",
                output_type=pytesseract.Output.DICT
            )

            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i]
                conf = float(data['conf'][i]) if data['conf'][i] != '-1' else 0.0

                if text and text.strip():
                    bbox = (
                        data['left'][i],
                        data['top'][i],
                        data['width'][i],
                        data['height'][i]
                    )
                    results.append(OCRResult(
                        text=text.strip(),
                        confidence=conf / 100.0,
                        bbox=bbox
                    ))
        except Exception as e:
            logger.warning(f"Tesseract recognize failed: {e}")

        return results

    def recognize_text(self, image: ImageArray, lang: str = "ita+eng") -> str:
        if not self.is_available():
            return ""

        import pytesseract  # type: ignore[import-untyped]

        variants = self._preprocess(image)
        all_texts = []

        for variant in variants:
            # Upscale for better recognition
            scaled = cv2.resize(
                variant, None, fx=2.5, fy=2.5,
                interpolation=cv2.INTER_CUBIC
            )

            for psm in [6, 7, 11]:  # Block, single line, sparse
                try:
                    text = pytesseract.image_to_string(
                        scaled, lang=lang,
                        config=f"--psm {psm}"
                    )
                    if text and text.strip():
                        all_texts.append(text.strip())
                except Exception:
                    continue

        # Return the longest meaningful result
        if all_texts:
            return max(all_texts, key=len)
        return ""


class EasyOCREngine(OCREngine):
    """EasyOCR engine wrapper (GPU-accelerated, no external install)."""

    def __init__(self, languages: list[str] | None = None):
        self._available = None
        self._reader = None
        self._languages = languages or ['it', 'en']

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            import easyocr  # type: ignore[import-untyped]  # noqa: F401
            self._available = True
            logger.info("EasyOCR is available")
        except ImportError:
            logger.warning("EasyOCR not installed")
            self._available = False

        return self._available

    def _get_reader(self) -> Any:
        if self._reader is None and self.is_available():
            import easyocr  # type: ignore[import-untyped]
            self._reader = easyocr.Reader(self._languages, gpu=False)
        return self._reader

    def recognize(self, image: ImageArray, lang: str = "ita+eng") -> list[OCRResult]:
        reader = self._get_reader()
        if not reader:
            return []

        try:
            results = reader.readtext(image)
            return [
                OCRResult(
                    text=text,
                    confidence=conf,
                    bbox=(int(bbox[0][0]), int(bbox[0][1]),
                          int(bbox[2][0] - bbox[0][0]),
                          int(bbox[2][1] - bbox[0][1]))
                )
                for bbox, text, conf in results
            ]
        except Exception as e:
            logger.warning(f"EasyOCR recognize failed: {e}")
            return []

    def recognize_text(self, image: ImageArray, lang: str = "ita+eng") -> str:
        results = self.recognize(image, lang)
        return " ".join(r.text for r in results)


class OCRManager:
    """
    Manages multiple OCR engines with automatic fallback.
    """

    def __init__(self, tesseract_path: str | None = None):
        self.engines: list[OCREngine] = [
            TesseractEngine(tesseract_path),
            EasyOCREngine(),
        ]
        self._primary_engine = None

    def get_available_engine(self) -> OCREngine | None:
        """Get the first available OCR engine."""
        if self._primary_engine and self._primary_engine.is_available():
            return self._primary_engine

        for engine in self.engines:
            if engine.is_available():
                self._primary_engine = engine
                logger.info(f"Using OCR engine: {engine.__class__.__name__}")
                return engine

        logger.error("No OCR engine available!")
        return None

    def recognize(self, image: ImageArray, lang: str = "ita+eng") -> list[OCRResult]:
        """Recognize text in image using best available engine."""
        engine = self.get_available_engine()
        if engine:
            return engine.recognize(image, lang)
        return []

    def recognize_text(self, image: ImageArray, lang: str = "ita+eng") -> str:
        """Get combined text from image."""
        engine = self.get_available_engine()
        if engine:
            return engine.recognize_text(image, lang)
        return ""

    def extract_words(self, image: ImageArray) -> list[tuple[str, tuple[int, int, int, int] | None]]:
        """Extract words with their bounding boxes."""
        results = self.recognize(image)
        return [(r.normalized_text, r.bbox) for r in results if r.text.strip()]
