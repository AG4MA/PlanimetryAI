"""
PlanParser Bootstrap Module
===========================
Ensures Tesseract OCR is installed before running the parser.
This module is automatically called when importing PlanParser.
"""

import logging

from .tesseract_setup import (
    download_tessdata,
    get_tesseract_path,
    install_tesseract,
    is_tesseract_installed,
    REQUIRED_LANGS,
)

logger = logging.getLogger(__name__)

# ANSI colors for terminal
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def check_and_install_tesseract(auto_install: bool = True) -> str:
    """
    Check if Tesseract is installed, optionally install if missing.

    Args:
        auto_install: If True, automatically install Tesseract if not found

    Returns:
        Path to Tesseract executable

    Raises:
        RuntimeError: If Tesseract is not available and cannot be installed
    """
    # First check if already installed
    tesseract_path = get_tesseract_path()
    if tesseract_path:
        logger.info(f"Tesseract found at: {tesseract_path}")
        return tesseract_path

    print(f"\n{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}{RED}⚠  Tesseract OCR is not installed!{RESET}")
    print(f"{YELLOW}{'='*60}{RESET}")
    print()
    print("Tesseract is REQUIRED for PlanParser to work properly.")
    print("EasyOCR is a fallback but has limited accuracy.")
    print()

    if not auto_install:
        print(f"{RED}Please install Tesseract OCR manually:{RESET}")
        print()
        print("  Windows (winget):")
        print("    winget install UB-Mannheim.TesseractOCR")
        print()
        print("  Windows (chocolatey):")
        print("    choco install tesseract")
        print()
        print("  macOS:")
        print("    brew install tesseract tesseract-lang")
        print()
        print("  Linux (Ubuntu/Debian):")
        print("    sudo apt install tesseract-ocr tesseract-ocr-ita")
        print()
        raise RuntimeError("Tesseract OCR is not installed")

    # Try auto-installation
    print(f"{BLUE}Attempting automatic installation...{RESET}")
    print()

    success = install_tesseract()
    if success:
        # Download language data
        print()
        print(f"{BLUE}Downloading language data...{RESET}")
        for lang in REQUIRED_LANGS:
            download_tessdata(lang)

        tesseract_path = get_tesseract_path()
        if tesseract_path:
            print()
            print(f"{GREEN}✓ Tesseract installed successfully!{RESET}")
            print(f"  Location: {tesseract_path}")
            return tesseract_path

    # Installation failed
    print()
    print(f"{RED}✗ Automatic installation failed.{RESET}")
    print()
    print("Please install Tesseract manually:")
    print()
    print("  1. Download from: https://github.com/UB-Mannheim/tesseract/wiki")
    print("  2. Run the installer")
    print("  3. Add to PATH or set TESSERACT_PATH environment variable")
    print()

    raise RuntimeError("Failed to install Tesseract OCR automatically")


def ensure_tesseract() -> str:
    """
    Ensure Tesseract is available, installing if necessary.

    This is called automatically when importing PlanParser.

    Returns:
        Path to Tesseract executable
    """
    try:
        return check_and_install_tesseract(auto_install=True)
    except RuntimeError:
        # Log but don't crash - allow fallback to EasyOCR
        logger.warning(
            "Tesseract not available. OCR quality will be degraded. "
            "Install Tesseract for best results."
        )
        return ""


def get_tesseract_for_pytesseract() -> str | None:
    """
    Get Tesseract path and configure pytesseract if available.

    Returns:
        Path to Tesseract executable or None
    """
    tesseract_path = get_tesseract_path()
    if tesseract_path:
        try:
            import pytesseract  # type: ignore[import-untyped]
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            logger.debug(f"Configured pytesseract with: {tesseract_path}")
        except ImportError:
            pass
    return tesseract_path


# Check on import (but don't fail)
# Using lowercase to avoid "constant" warnings from type checkers
_tesseract_path_cache: str | None = None


def init_tesseract(require: bool = False) -> str | None:
    """
    Initialize Tesseract OCR.

    Args:
        require: If True, raise error if Tesseract not available

    Returns:
        Path to Tesseract or None
    """
    global _tesseract_path_cache

    if _tesseract_path_cache is not None:
        return _tesseract_path_cache if _tesseract_path_cache else None

    if is_tesseract_installed():
        _tesseract_path_cache = get_tesseract_for_pytesseract() or ""
        return _tesseract_path_cache if _tesseract_path_cache else None

    if require:
        _tesseract_path_cache = check_and_install_tesseract(auto_install=True)
        return _tesseract_path_cache

    # Try silent install
    try:
        _tesseract_path_cache = check_and_install_tesseract(auto_install=True)
    except RuntimeError:
        _tesseract_path_cache = ""
        logger.warning("Tesseract not available, falling back to EasyOCR")

    return _tesseract_path_cache if _tesseract_path_cache else None


if __name__ == "__main__":
    # Run as script to force installation
    logging.basicConfig(level=logging.INFO)
    path = check_and_install_tesseract(auto_install=True)
    print(f"\nTesseract ready at: {path}")
