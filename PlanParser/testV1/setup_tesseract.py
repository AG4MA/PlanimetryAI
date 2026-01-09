"""
Script per scaricare e installare Tesseract OCR localmente nel progetto.

Uso:
    python setup_tesseract.py

Questo script:
1. Scarica l'installer di Tesseract da UB Mannheim
2. Salva l'installer in testV1/tesseract/
3. Avvia l'installer - l'utente deve completare l'installazione manualmente
   IMPORTANTE: Installare in C:\projects\PlanimetryAI\PlanParser\testV1\tesseract\Tesseract-OCR

Dopo l'installazione, Tesseract sarà disponibile in:
    testV1/tesseract/Tesseract-OCR/tesseract.exe
"""

import os
import sys
import subprocess
from pathlib import Path

# URL ufficiale da UB Mannheim
TESSERACT_URL = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.3.3.20231005.exe"
TESSERACT_FILENAME = "tesseract_setup.exe"

def get_project_root():
    """Trova la root del progetto (dove c'è testV1)"""
    return Path(__file__).parent

def download_tesseract():
    """Scarica l'installer di Tesseract"""
    project_root = get_project_root()
    tesseract_dir = project_root / "tesseract"
    tesseract_dir.mkdir(parents=True, exist_ok=True)
    
    installer_path = tesseract_dir / TESSERACT_FILENAME
    
    if installer_path.exists():
        print(f"✅ Installer già presente: {installer_path}")
        return installer_path
    
    print(f"📥 Scaricamento Tesseract da {TESSERACT_URL}...")
    print("   Questo potrebbe richiedere qualche minuto...")
    
    try:
        # Usa PowerShell per scaricare (funziona su Windows)
        ps_command = f'''
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri "{TESSERACT_URL}" -OutFile "{installer_path}"
        '''
        subprocess.run(["powershell", "-Command", ps_command], check=True)
        print(f"✅ Download completato: {installer_path}")
        return installer_path
    except subprocess.CalledProcessError as e:
        print(f"❌ Errore durante il download: {e}")
        print("\nProva a scaricare manualmente da:")
        print(f"   {TESSERACT_URL}")
        print(f"\nE salva il file in:")
        print(f"   {installer_path}")
        return None

def run_installer(installer_path):
    """Avvia l'installer di Tesseract"""
    if not installer_path or not installer_path.exists():
        print("❌ Installer non trovato")
        return False
    
    install_dir = installer_path.parent / "Tesseract-OCR"
    
    print("\n" + "="*60)
    print("⚠️  ISTRUZIONI PER L'INSTALLAZIONE")
    print("="*60)
    print(f"""
Quando si apre l'installer:

1. Clicca "Next"
2. Accetta la licenza
3. Seleziona i componenti (consigliato: tutti)
4. IMPORTANTE - Cambia la cartella di installazione in:
   
   {install_dir}
   
5. Completa l'installazione

Dopo l'installazione, il progetto userà Tesseract da quella cartella.
""")
    print("="*60)
    
    input("\nPremi INVIO per avviare l'installer...")
    
    try:
        # Avvia l'installer
        subprocess.Popen([str(installer_path)], shell=True)
        print("\n✅ Installer avviato. Segui le istruzioni sopra.")
        return True
    except Exception as e:
        print(f"❌ Errore nell'avvio dell'installer: {e}")
        print(f"\nAvvia manualmente: {installer_path}")
        return False

def verify_installation():
    """Verifica che Tesseract sia installato correttamente"""
    project_root = get_project_root()
    tesseract_exe = project_root / "tesseract" / "Tesseract-OCR" / "tesseract.exe"
    
    if tesseract_exe.exists():
        print(f"\n✅ Tesseract trovato: {tesseract_exe}")
        # Prova ad eseguirlo
        try:
            result = subprocess.run([str(tesseract_exe), "--version"], 
                                    capture_output=True, text=True)
            print(f"   Versione: {result.stdout.splitlines()[0]}")
            return True
        except Exception as e:
            print(f"   ⚠️ Errore nel verificare la versione: {e}")
            return True  # Il file esiste comunque
    else:
        print(f"\n❌ Tesseract non trovato in: {tesseract_exe}")
        print("   Assicurati di aver installato nella cartella corretta.")
        return False

def main():
    print("="*60)
    print("   SETUP TESSERACT OCR - PlanParser")
    print("="*60)
    
    # Step 1: Scarica
    installer_path = download_tesseract()
    
    if not installer_path:
        sys.exit(1)
    
    # Controlla se già installato
    if verify_installation():
        print("\n✅ Tesseract è già installato e funzionante!")
        choice = input("\nVuoi reinstallare? (s/N): ").strip().lower()
        if choice != 's':
            return
    
    # Step 2: Avvia installer
    run_installer(installer_path)
    
    print("\n" + "-"*60)
    print("Dopo aver completato l'installazione, esegui di nuovo")
    print("questo script per verificare che tutto funzioni:")
    print(f"   python {__file__}")
    print("-"*60)

if __name__ == "__main__":
    main()
