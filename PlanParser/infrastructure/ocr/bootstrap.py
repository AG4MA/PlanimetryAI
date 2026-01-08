"""
PlanParser Bootstrap
====================
Auto-configures Tesseract OCR on import.
Installs if missing, configures path automatically.
"""

import logging
import sys

from .tesseract_setup import configure_pytesseract, ensure_tesseract, get_tesseract_path, is_tesseract_installed

logger = logging.getLogger(__name__)

# Module state
_tesseract_path: str | None = None
_initialized: bool = False


def init_tesseract(require: bool = False, silent: bool = False) -> str | None:
    """
    Initialize Tesseract OCR - find, install if needed, configure pytesseract.

    Args:
        require: Raise RuntimeError if Tesseract cannot be configured
        silent: Suppress installation output (default: False - logs everything)

    Returns:
        Path to tesseract executable or None
    """
    global _tesseract_path, _initialized

    if _initialized:
        return _tesseract_path

    _initialized = True

    # Quick check if already available
    if is_tesseract_installed():
        _tesseract_path = get_tesseract_path()
        if _tesseract_path:
            configure_pytesseract(_tesseract_path)
            logger.info(f"Tesseract found: {_tesseract_path}")
            return _tesseract_path

    # Not installed - try auto-install
    logger.warning("Tesseract not found. Attempting automatic installation...")
    print("=" * 60, file=sys.stderr)
    print("🔧 Tesseract OCR not found - installing automatically...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    _tesseract_path = ensure_tesseract()

    if _tesseract_path:
        configure_pytesseract(_tesseract_path)
        logger.info(f"✅ Tesseract installed and configured: {_tesseract_path}")
        print(f"✅ Tesseract installed: {_tesseract_path}", file=sys.stderr)
        return _tesseract_path

    # Failed
    if require:
        raise RuntimeError(
            "Tesseract OCR required. Install: winget install UB-Mannheim.TesseractOCR"
        )

    logger.warning("Tesseract unavailable - OCR quality degraded")
    print("⚠️  Tesseract unavailable - using EasyOCR fallback", file=sys.stderr)
    return None


def get_configured_path() -> str | None:
    """Get configured Tesseract path (call init_tesseract first)."""
    return _tesseract_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = init_tesseract(require=True, silent=False)
    print(f"Tesseract: {path}")
