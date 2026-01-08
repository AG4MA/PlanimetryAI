"""
Tesseract OCR Auto-Installer.

Downloads and installs Tesseract OCR locally if not found.
"""

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# Tesseract download URLs (Windows portable builds)
TESSERACT_URLS = {
    "win64": "https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
    "win64_zip": "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
}

# Language data URLs
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main"
REQUIRED_LANGS = ["eng", "ita"]


def get_project_root() -> Path:
    """Get PlanParser project root directory."""
    return Path(__file__).parent


def get_tesseract_dir() -> Path:
    """Get local Tesseract installation directory."""
    return get_project_root() / "tesseract"


def get_tesseract_exe() -> Path:
    """Get path to Tesseract executable."""
    tesseract_dir = get_tesseract_dir()
    if platform.system() == "Windows":
        return tesseract_dir / "tesseract.exe"
    return tesseract_dir / "bin" / "tesseract"


def get_tessdata_dir() -> Path:
    """Get path to tessdata directory."""
    return get_tesseract_dir() / "tessdata"


def is_tesseract_installed() -> bool:
    """Check if Tesseract is installed (system or local)."""
    # Check local installation first
    local_exe = get_tesseract_exe()
    if local_exe.exists():
        return True

    # Check system PATH
    tesseract_cmd = shutil.which("tesseract")
    if tesseract_cmd:
        return True

    # Check common Windows installation paths
    common_paths = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for path in common_paths:
        if path.exists():
            return True

    return False


def get_tesseract_path() -> str | None:
    """Get path to Tesseract executable."""
    # Check local installation first
    local_exe = get_tesseract_exe()
    if local_exe.exists():
        return str(local_exe)

    # Check system PATH
    tesseract_cmd = shutil.which("tesseract")
    if tesseract_cmd:
        return tesseract_cmd

    # Check common Windows paths
    common_paths = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for path in common_paths:
        if path.exists():
            return str(path)

    return None


def download_file(url: str, dest: Path, desc: str = "Downloading") -> bool:
    """Download a file with progress indicator."""
    print(f"{desc}: {url}")
    try:

        def reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                progress = min(100, block_num * block_size * 100 // total_size)
                print(f"\r  Progress: {progress}%", end="", flush=True)

        urllib.request.urlretrieve(url, dest, reporthook)
        print()  # Newline after progress
        return True
    except Exception as e:
        print(f"\n  Error downloading: {e}")
        return False


def download_tessdata(lang: str) -> bool:
    """Download language data for Tesseract."""
    tessdata_dir = get_tessdata_dir()
    tessdata_dir.mkdir(parents=True, exist_ok=True)

    traineddata_file = tessdata_dir / f"{lang}.traineddata"
    if traineddata_file.exists():
        print(f"  Language '{lang}' already downloaded")
        return True

    url = f"{TESSDATA_URL}/{lang}.traineddata"
    return download_file(url, traineddata_file, f"  Downloading {lang} language data")


def install_tesseract_windows_portable() -> bool:
    """Install portable Tesseract on Windows using winget or direct download."""
    tesseract_dir = get_tesseract_dir()
    tesseract_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("Installing Tesseract OCR locally...")
    print("=" * 60)

    # Try winget first (cleanest method)
    try:
        print("\nTrying winget installation...")
        result = subprocess.run(
            [
                "winget",
                "install",
                "--id",
                "UB-Mannheim.TesseractOCR",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print("✅ Tesseract installed via winget!")
            print("   Installed to: C:\\Program Files\\Tesseract-OCR")
            return True
        print(f"   winget failed: {result.stderr}")
    except FileNotFoundError:
        print("   winget not available")
    except subprocess.TimeoutExpired:
        print("   winget timed out")
    except Exception as e:
        print(f"   winget error: {e}")

    # Try chocolatey
    try:
        print("\nTrying Chocolatey installation...")
        result = subprocess.run(
            ["choco", "install", "tesseract", "-y", "--no-progress"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print("✅ Tesseract installed via Chocolatey!")
            return True
        print(f"   choco failed: {result.stderr}")
    except FileNotFoundError:
        print("   Chocolatey not available")
    except Exception as e:
        print(f"   choco error: {e}")

    # Manual download fallback - provide instructions
    print("\n" + "-" * 60)
    print("⚠️  Automatic installation not available.")
    print("Please install Tesseract manually:")
    print("")
    print("Option 1 - winget (recommended):")
    print("  winget install UB-Mannheim.TesseractOCR")
    print("")
    print("Option 2 - Download installer:")
    print("  https://github.com/UB-Mannheim/tesseract/releases")
    print("  Download: tesseract-ocr-w64-setup-*.exe")
    print("  Run installer and select Italian language pack")
    print("-" * 60)

    return False


def install_tesseract_linux() -> bool:
    """Install Tesseract on Linux using package manager."""
    print("\n" + "=" * 60)
    print("Installing Tesseract OCR...")
    print("=" * 60)

    # Try apt (Debian/Ubuntu)
    try:
        print("\nTrying apt installation...")
        subprocess.run(["sudo", "apt-get", "update"], check=True, timeout=60)
        subprocess.run(
            [
                "sudo",
                "apt-get",
                "install",
                "-y",
                "tesseract-ocr",
                "tesseract-ocr-ita",
                "tesseract-ocr-eng",
            ],
            check=True,
            timeout=120,
        )
        print("✅ Tesseract installed via apt!")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Try dnf (Fedora/RHEL)
    try:
        print("\nTrying dnf installation...")
        subprocess.run(
            [
                "sudo",
                "dnf",
                "install",
                "-y",
                "tesseract",
                "tesseract-langpack-ita",
                "tesseract-langpack-eng",
            ],
            check=True,
            timeout=120,
        )
        print("✅ Tesseract installed via dnf!")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Try pacman (Arch)
    try:
        print("\nTrying pacman installation...")
        subprocess.run(
            ["sudo", "pacman", "-S", "--noconfirm", "tesseract", "tesseract-data-ita", "tesseract-data-eng"],
            check=True,
            timeout=120,
        )
        print("✅ Tesseract installed via pacman!")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    print("\n⚠️  Could not install Tesseract automatically.")
    print("Please install manually using your package manager.")
    return False


def install_tesseract_macos() -> bool:
    """Install Tesseract on macOS using Homebrew."""
    print("\n" + "=" * 60)
    print("Installing Tesseract OCR...")
    print("=" * 60)

    try:
        print("\nTrying Homebrew installation...")
        subprocess.run(["brew", "install", "tesseract", "tesseract-lang"], check=True, timeout=300)
        print("✅ Tesseract installed via Homebrew!")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"   Homebrew error: {e}")

    print("\n⚠️  Could not install Tesseract automatically.")
    print("Please install Homebrew first: https://brew.sh")
    print("Then run: brew install tesseract tesseract-lang")
    return False


def install_tesseract() -> bool:
    """Install Tesseract for the current platform."""
    system = platform.system()

    if system == "Windows":
        return install_tesseract_windows_portable()
    elif system == "Linux":
        return install_tesseract_linux()
    elif system == "Darwin":
        return install_tesseract_macos()
    else:
        print(f"Unsupported platform: {system}")
        return False


def ensure_tesseract() -> str | None:
    """
    Ensure Tesseract is installed, installing if necessary.

    Returns:
        Path to Tesseract executable, or None if installation failed.
    """
    print("\n🔍 Checking for Tesseract OCR...")

    tesseract_path = get_tesseract_path()
    if tesseract_path:
        print(f"✅ Tesseract found: {tesseract_path}")

        # Verify it works
        try:
            result = subprocess.run([tesseract_path, "--version"], capture_output=True, text=True, timeout=10)
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            print(f"   Version: {version_line}")
            return tesseract_path
        except Exception as e:
            print(f"   Warning: Could not verify version: {e}")
            return tesseract_path

    print("❌ Tesseract not found")

    # Try to install
    if install_tesseract():
        tesseract_path = get_tesseract_path()
        if tesseract_path:
            print(f"\n✅ Tesseract ready: {tesseract_path}")
            return tesseract_path

    return None


def configure_pytesseract(tesseract_path: str | None = None) -> bool:
    """
    Configure pytesseract to use the correct Tesseract installation.

    Returns:
        True if configuration successful, False otherwise.
    """
    if tesseract_path is None:
        tesseract_path = ensure_tesseract()

    if tesseract_path is None:
        print("\n❌ Tesseract is required but could not be installed.")
        print("Please install Tesseract manually and try again.")
        return False

    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        print(f"\n✅ pytesseract configured: {tesseract_path}")
        return True
    except ImportError:
        print("\n⚠️  pytesseract not installed. Install with: pip install pytesseract")
        return False


if __name__ == "__main__":
    tesseract_path = ensure_tesseract()
    if tesseract_path:
        print("\n" + "=" * 60)
        print("✅ Tesseract OCR is ready!")
        print(f"   Path: {tesseract_path}")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("❌ Tesseract OCR installation failed")
        print("   Please install manually")
        print("=" * 60)
        sys.exit(1)
