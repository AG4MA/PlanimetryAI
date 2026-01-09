"""
TestV1 - Pipeline di test per l'approccio matematico al parsing planimetrico.

Questo modulo definisce il path di Tesseract locale e le configurazioni base.
"""

import os
from pathlib import Path

# Paths
TESTV1_ROOT = Path(__file__).parent
TESSERACT_ROOT = TESTV1_ROOT / "tesseract"
TESSERACT_EXE = TESSERACT_ROOT / "tesseract.exe"
TESSDATA_DIR = TESSERACT_ROOT / "tessdata"
OUTPUT_DIR = TESTV1_ROOT / "output"
CORE_DIR = TESTV1_ROOT / "core"

# Crea output dir se non esiste
OUTPUT_DIR.mkdir(exist_ok=True)

# Configura pytesseract per usare il Tesseract locale
def configure_tesseract():
    """Configura pytesseract per usare l'installazione locale"""
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
        os.environ['TESSDATA_PREFIX'] = str(TESSDATA_DIR)
        return True
    except ImportError:
        print("pytesseract non installato. Esegui: pip install pytesseract")
        return False

def verify_tesseract():
    """Verifica che Tesseract sia disponibile"""
    if not TESSERACT_EXE.exists():
        print(f"❌ Tesseract non trovato: {TESSERACT_EXE}")
        print("   Esegui: python setup_tesseract.py")
        return False
    
    print(f"✅ Tesseract trovato: {TESSERACT_EXE}")
    return True

# Data path (planimetrie di test)
DATA_DIR = TESTV1_ROOT.parent / "data"
