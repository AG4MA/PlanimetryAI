"""
Tesseract OCR Auto-Setup
========================
Trova, verifica o installa Tesseract OCR automaticamente al bootstrap.

Segue la guida ufficiale: https://tesseract-ocr.github.io/tessdoc/Installation.html
"""

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

# ============================================================================
# CONFIGURAZIONE
# ============================================================================

# Directory locale del progetto per Tesseract
PROJECT_TESSERACT_DIR = Path(__file__).parent / "tools" / "tesseract"

# URL per download diretto (UB Mannheim - versione portable ZIP)
TESSERACT_ZIP_URL = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-5.4.0.20240606.zip"

# URL tessdata (language models) - usiamo fast per velocità
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
REQUIRED_LANGS = ["eng", "ita"]


# ============================================================================
# LOGGING CON COLORI
# ============================================================================

class Colors:
    """ANSI color codes per logging colorato."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"


def _supports_color() -> bool:
    """Verifica se il terminale supporta i colori."""
    if os.environ.get("NO_COLOR"):
        return False
    if platform.system() == "Windows":
        # Windows 10+ supporta ANSI se abilitato
        return os.environ.get("TERM") or os.environ.get("WT_SESSION")
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def log(msg: str, level: str = "INFO") -> None:
    """Log colorato in console."""
    use_color = _supports_color()
    
    colors = {
        "INFO": Colors.CYAN,
        "OK": Colors.GREEN,
        "WARN": Colors.YELLOW,
        "ERROR": Colors.RED,
        "STEP": Colors.BLUE,
    }
    
    symbols = {
        "INFO": "ℹ️ ",
        "OK": "✅",
        "WARN": "⚠️ ",
        "ERROR": "❌",
        "STEP": "▶️ ",
    }
    
    color = colors.get(level, Colors.RESET)
    symbol = symbols.get(level, "")
    
    if use_color:
        print(f"{color}{symbol} {msg}{Colors.RESET}", file=sys.stderr)
    else:
        print(f"[{level}] {msg}", file=sys.stderr)


# ============================================================================
# ENVIRONMENT INFO
# ============================================================================

class EnvironmentInfo(NamedTuple):
    """Informazioni sull'ambiente di esecuzione."""
    os_name: str  # Windows, Linux, Darwin
    os_version: str
    arch: str  # AMD64, ARM64, x86_64
    is_windows: bool
    is_linux: bool
    is_macos: bool


def get_environment() -> EnvironmentInfo:
    """Rileva l'ambiente di esecuzione."""
    os_name = platform.system()
    os_version = platform.version()
    arch = platform.machine()
    
    return EnvironmentInfo(
        os_name=os_name,
        os_version=os_version,
        arch=arch,
        is_windows=(os_name == "Windows"),
        is_linux=(os_name == "Linux"),
        is_macos=(os_name == "Darwin"),
    )


def get_project_tesseract_dir() -> Path:
    """Ritorna la directory per Tesseract nel progetto."""
    return PROJECT_TESSERACT_DIR


def get_project_tesseract_exe() -> Path:
    """Ritorna il path dell'eseguibile Tesseract nel progetto."""
    env = get_environment()
    if env.is_windows:
        return PROJECT_TESSERACT_DIR / "tesseract.exe"
    else:
        return PROJECT_TESSERACT_DIR / "bin" / "tesseract"


# ============================================================================
# RICERCA TESSERACT
# ============================================================================

def find_tesseract() -> str | None:
    """
    Trova tesseract - PRIMA nel progetto, poi nel sistema.
    
    Priorità:
    1. Directory locale del progetto (PlanParser/tools/tesseract/)
    2. PATH di sistema
    3. Percorsi noti del sistema operativo
    """
    # 1. PRIORITÀ: directory del progetto
    project_exe = get_project_tesseract_exe()
    if project_exe.exists():
        return str(project_exe)
    
    # 2. PATH di sistema
    path = shutil.which("tesseract")
    if path:
        return path
    
    # 3. Percorsi noti per OS (fallback)
    env = get_environment()
    if env.is_windows:
        windows_paths = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")),
        ]
        for p in windows_paths:
            if p.exists():
                return str(p)
    else:
        unix_paths = [
            Path("/usr/bin/tesseract"),
            Path("/usr/local/bin/tesseract"),
            Path("/opt/homebrew/bin/tesseract"),
        ]
        for p in unix_paths:
            if p.exists():
                return str(p)
    
    return None


def verify_tesseract(path: str) -> tuple[bool, str]:
    """Verifica che tesseract funzioni e ritorna la versione."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.split("\n")[0] if result.stdout else "unknown"
            return True, version
        return False, result.stderr
    except FileNotFoundError:
        return False, "File not found"
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


# ============================================================================
# INSTALLAZIONE LOCALE NEL PROGETTO
# ============================================================================

def download_file(url: str, dest: Path, desc: str = "file") -> bool:
    """Scarica un file con progress logging."""
    import urllib.error
    
    log(f"Download {desc}...", "INFO")
    log(f"  URL: {url}", "INFO")
    
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        log(f"  Scaricato: {dest}", "OK")
        return True
    except urllib.error.URLError as e:
        log(f"  Errore download: {e}", "ERROR")
        return False
    except Exception as e:
        log(f"  Errore: {e}", "ERROR")
        return False


def install_tesseract_windows_local() -> str | None:
    """
    Scarica e installa Tesseract nella directory del progetto.
    
    Usa la versione portable ZIP da UB Mannheim.
    """
    import zipfile
    import tempfile
    
    log("Installazione Tesseract locale (nel progetto)...", "STEP")
    
    dest_dir = get_project_tesseract_dir()
    dest_exe = dest_dir / "tesseract.exe"
    
    # Se già presente, usa quello
    if dest_exe.exists():
        log(f"Tesseract già presente: {dest_exe}", "OK")
        return str(dest_exe)
    
    # Scarica ZIP
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "tesseract.zip"
        
        if not download_file(TESSERACT_ZIP_URL, zip_path, "Tesseract ZIP"):
            return None
        
        # Estrai ZIP
        log("Estrazione archivio...", "INFO")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Estrai in temp
                zf.extractall(tmpdir)
            
            # Trova la directory estratta
            extracted_dirs = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
            if not extracted_dirs:
                log("Archivio vuoto o corrotto", "ERROR")
                return None
            
            extracted_dir = extracted_dirs[0]
            
            # Sposta nella directory del progetto
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            if dest_dir.exists():
                import shutil as sh
                sh.rmtree(dest_dir)
            
            import shutil as sh
            sh.move(str(extracted_dir), str(dest_dir))
            
            if dest_exe.exists():
                log(f"Tesseract installato: {dest_exe}", "OK")
                return str(dest_exe)
            else:
                log("tesseract.exe non trovato dopo estrazione", "ERROR")
                return None
                
        except zipfile.BadZipFile:
            log("Archivio ZIP corrotto", "ERROR")
            return None
        except Exception as e:
            log(f"Errore estrazione: {e}", "ERROR")
            return None


def install_tesseract_linux_local() -> str | None:
    """
    Su Linux, usa il package manager (richiede sudo).
    
    Alternativa: AppImage (non richiede sudo).
    """
    log("Installazione Tesseract per Linux...", "STEP")
    
    # Prima prova apt/dnf
    try:
        # Prova apt
        result = subprocess.run(
            ["which", "apt-get"],
            capture_output=True
        )
        if result.returncode == 0:
            log("Uso apt per installare tesseract...", "INFO")
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", 
                 "tesseract-ocr", "tesseract-ocr-ita", "tesseract-ocr-eng"],
                check=True
            )
            path = shutil.which("tesseract")
            if path:
                log(f"Tesseract installato: {path}", "OK")
                return path
    except Exception as e:
        log(f"apt fallito: {e}", "WARN")
    
    try:
        # Prova dnf
        result = subprocess.run(
            ["which", "dnf"],
            capture_output=True
        )
        if result.returncode == 0:
            log("Uso dnf per installare tesseract...", "INFO")
            subprocess.run(
                ["sudo", "dnf", "install", "-y", 
                 "tesseract", "tesseract-langpack-ita", "tesseract-langpack-eng"],
                check=True
            )
            path = shutil.which("tesseract")
            if path:
                log(f"Tesseract installato: {path}", "OK")
                return path
    except Exception as e:
        log(f"dnf fallito: {e}", "WARN")
    
    log("Installazione automatica non riuscita", "ERROR")
    log("Esegui manualmente: sudo apt install tesseract-ocr tesseract-ocr-ita", "INFO")
    return None


def install_tesseract_macos_local() -> str | None:
    """Su macOS, usa Homebrew."""
    log("Installazione Tesseract per macOS...", "STEP")
    
    try:
        log("Uso Homebrew per installare tesseract...", "INFO")
        subprocess.run(
            ["brew", "install", "tesseract"],
            check=True
        )
        path = shutil.which("tesseract")
        if path:
            log(f"Tesseract installato: {path}", "OK")
            return path
    except FileNotFoundError:
        log("Homebrew non trovato", "WARN")
        log("Installa Homebrew: https://brew.sh", "INFO")
    except Exception as e:
        log(f"Homebrew fallito: {e}", "WARN")
    
    return None


def install_tesseract() -> str | None:
    """Installa Tesseract per il sistema corrente - LOCALE nel progetto."""
    env = get_environment()
    
    if env.is_windows:
        return install_tesseract_windows_local()
    elif env.is_linux:
        return install_tesseract_linux_local()
    elif env.is_macos:
        return install_tesseract_macos_local()
    else:
        log(f"Sistema non supportato: {env.os_name}", "ERROR")
        return None


# ============================================================================
# DOWNLOAD TESSDATA
# ============================================================================

def download_tessdata(tesseract_path: str, lang: str) -> bool:
    """Scarica i dati di lingua per Tesseract."""
    # Trova tessdata directory
    tesseract_dir = Path(tesseract_path).parent
    
    # Cerca tessdata in varie posizioni
    tessdata_dirs = [
        tesseract_dir / "tessdata",
        tesseract_dir.parent / "tessdata",
        tesseract_dir.parent / "share" / "tessdata",
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tesseract-ocr/5/tessdata"),
    ]
    
    tessdata_dir = None
    for d in tessdata_dirs:
        if d.exists():
            tessdata_dir = d
            break
    
    if not tessdata_dir:
        log(f"Directory tessdata non trovata", "WARN")
        return False
    
    traineddata_file = tessdata_dir / f"{lang}.traineddata"
    if traineddata_file.exists():
        return True  # Già presente
    
    log(f"Scaricamento dati lingua '{lang}'...", "INFO")
    url = f"{TESSDATA_URL}/{lang}.traineddata"
    
    try:
        urllib.request.urlretrieve(url, traineddata_file)
        log(f"Lingua '{lang}' scaricata", "OK")
        return True
    except Exception as e:
        log(f"Errore download {lang}: {e}", "WARN")
        return False


# ============================================================================
# CONFIGURAZIONE PYTESSERACT
# ============================================================================

def configure_pytesseract(tesseract_path: str) -> bool:
    """Configura pytesseract con il path di Tesseract."""
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        log(f"pytesseract configurato: {tesseract_path}", "OK")
        return True
    except ImportError:
        log("pytesseract non installato", "WARN")
        return False


# ============================================================================
# FUNZIONE PRINCIPALE
# ============================================================================

def ensure_tesseract() -> str | None:
    """
    Assicura che Tesseract sia disponibile.
    
    1. Cerca nel PATH
    2. Cerca in percorsi noti
    3. Se non trovato, installa
    4. Verifica funzionamento
    5. Configura pytesseract
    
    Returns:
        Path a tesseract.exe/tesseract, o None se non disponibile
    """
    env = get_environment()
    log(f"Ambiente: {env.os_name} {env.arch}", "INFO")
    
    # Step 1: Cerca tesseract
    log("Ricerca Tesseract...", "STEP")
    tesseract_path = find_tesseract()
    
    if tesseract_path:
        log(f"Tesseract trovato: {tesseract_path}", "OK")
    else:
        log("Tesseract non trovato nel sistema", "WARN")
        
        # Step 2: Installa
        log("Avvio installazione automatica...", "STEP")
        tesseract_path = install_tesseract()
        
        if not tesseract_path:
            log("Impossibile installare Tesseract", "ERROR")
            return None
    
    # Step 3: Verifica
    log("Verifica funzionamento...", "STEP")
    ok, version = verify_tesseract(tesseract_path)
    
    if not ok:
        log(f"Tesseract non funziona: {version}", "ERROR")
        return None
    
    log(f"Tesseract OK: {version}", "OK")
    
    # Step 4: Configura pytesseract
    configure_pytesseract(tesseract_path)
    
    # Step 5: Verifica/scarica tessdata
    for lang in REQUIRED_LANGS:
        download_tessdata(tesseract_path, lang)
    
    return tesseract_path


def is_tesseract_installed() -> bool:
    """Verifica veloce se Tesseract è disponibile."""
    path = find_tesseract()
    if not path:
        return False
    ok, _ = verify_tesseract(path)
    return ok


def get_tesseract_path() -> str | None:
    """Ritorna il path di Tesseract se disponibile."""
    return find_tesseract()


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("TESSERACT OCR SETUP")
    print("=" * 60)
    
    path = ensure_tesseract()
    
    if path:
        print("\n" + "=" * 60)
        print(f"✅ Tesseract pronto: {path}")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("❌ Setup fallito")
        print("=" * 60)
        sys.exit(1)
