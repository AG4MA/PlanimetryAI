"""
PlanParser test_26-02-07_v0.1 - Pipeline di parsing planimetrico.

Configures paths and Tesseract OCR for the local environment.
"""

import os
from pathlib import Path

# Paths
TEST_ROOT = Path(__file__).parent
TESSERACT_ROOT = TEST_ROOT.parent / "testV1" / "tesseract"
TESSERACT_EXE = TESSERACT_ROOT / "tesseract.exe"
TESSDATA_DIR = TESSERACT_ROOT / "tessdata"
OUTPUT_DIR = TEST_ROOT / "output"
DATA_DIR = TEST_ROOT.parent / "data"

OUTPUT_DIR.mkdir(exist_ok=True)


def configure_tesseract() -> bool:
    """Configure pytesseract to use the bundled Tesseract installation."""
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
        return True
    except ImportError:
        print("pytesseract not installed. Run: pip install pytesseract")
        return False


def verify_tesseract() -> bool:
    """Verify that Tesseract is available at the expected path."""
    if not TESSERACT_EXE.exists():
        print(f"Tesseract not found: {TESSERACT_EXE}")
        return False
    print(f"Tesseract found: {TESSERACT_EXE}")
    return True
