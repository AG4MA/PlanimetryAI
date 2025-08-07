#!/usr/bin/env python3
"""
Test semplice per verificare che le dipendenze funzionino
"""

def test_imports():
    """Testa che tutte le dipendenze siano importabili"""
    try:
        import cv2
        print("✅ OpenCV importato correttamente")
    except ImportError as e:
        print(f"❌ Errore importando OpenCV: {e}")
        return False
    
    try:
        import numpy as np
        print("✅ NumPy importato correttamente")
    except ImportError as e:
        print(f"❌ Errore importando NumPy: {e}")
        return False
    
    try:
        import fitz
        print("✅ PyMuPDF importato correttamente")
    except ImportError as e:
        print(f"❌ Errore importando PyMuPDF: {e}")
        return False
    
    try:
        from PIL import Image
        print("✅ Pillow importato correttamente")
    except ImportError as e:
        print(f"❌ Errore importando Pillow: {e}")
        return False
    
    return True

def test_basic_operations():
    """Testa operazioni base"""
    try:
        import numpy as np
        import cv2
        
        # Crea un'immagine di test
        test_img = np.zeros((100, 100, 3), dtype=np.uint8)
        test_img[25:75, 25:75] = [255, 255, 255]  # Rettangolo bianco
        
        # Testa operazioni OpenCV
        gray = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)
        contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        print(f"✅ Operazioni base OpenCV funzionanti (trovati {len(contours)} contorni)")
        return True
        
    except Exception as e:
        print(f"❌ Errore nelle operazioni base: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Test delle dipendenze...")
    
    if test_imports() and test_basic_operations():
        print("🎉 Tutti i test sono passati!")
    else:
        print("❌ Alcuni test sono falliti")
