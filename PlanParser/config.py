"""
PlanParser Configuration
========================
Central configuration for all parsing parameters.
"""

from dataclasses import dataclass, field
from typing import List, Set, Optional
from pathlib import Path


@dataclass
class DetectionConfig:
    """Parameters for text/element detection."""
    min_area: int = 50
    max_area: int = 14000
    min_aspect_ratio: float = 1.1
    max_aspect_ratio: float = 22.0
    min_height: int = 6
    max_height: int = 64
    tophat_kernel: int = 5
    dilate_kernel: int = 3


@dataclass
class OCRConfig:
    """Parameters for OCR processing."""
    languages: str = "ita+eng"
    oem: int = 3  # OCR Engine Mode
    psm_modes: List[int] = field(default_factory=lambda: [7, 6, 11])
    padding: int = 4
    scale_factor: int = 4
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .-_/"
    tesseract_path: Optional[str] = None  # Set if not in PATH


@dataclass 
class RoomLabels:
    """Room label recognition configuration."""
    # Target room types (Italian)
    targets: Set[str] = field(default_factory=lambda: {
        "sala", "soggiorno", "soggiorno-pranzo", "pranzo",
        "camera", "letto", "stanza",
        "bagno", "wc", "servizio",
        "cucina", "angolo cottura", "cottura",
        "ingresso", "corridoio", "disimpegno", "dis",
        "ripostiglio", "rip", "lavanderia",
        "balcone", "terrazzo", "loggia",
        "portico", "veranda",
        "studio", "ufficio",
        "cantina", "garage", "box",
    })
    
    # Words to ignore
    blacklist: Set[str] = field(default_factory=lambda: {
        "arredo", "armadio", "altra", "uiu", "stessa",
        "scala", "scale", "ascensore",
    })
    
    # Synonyms mapping (canonical -> alternatives)
    synonyms: dict = field(default_factory=lambda: {
        "soggiorno": {"sala", "soggiorno-pranzo", "living"},
        "camera": {"letto", "stanza", "bedroom"},
        "bagno": {"wc", "servizio", "bathroom"},
        "cucina": {"angolo cottura", "cottura", "kitchen"},
        "disimpegno": {"dis", "dis.", "corridoio", "hallway"},
        "ripostiglio": {"rip", "rip.", "storage"},
        "balcone": {"terrazzo", "loggia", "balcony"},
    })


@dataclass
class FloorLabels:
    """Floor label patterns (Italian)."""
    ordinals: List[str] = field(default_factory=lambda: [
        "terra", "primo", "secondo", "terzo", "quarto",
        "quinto", "sesto", "settimo", "ottavo", "nono", "decimo"
    ])


@dataclass
class OutputConfig:
    """Output and debug configuration."""
    debug_dir: Path = field(default_factory=lambda: Path("./debug_image"))
    output_dir: Path = field(default_factory=lambda: Path("./planimetry_output"))
    save_intermediate: bool = True
    log_level: str = "INFO"


@dataclass
class PlanParserConfig:
    """Master configuration combining all settings."""
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    rooms: RoomLabels = field(default_factory=RoomLabels)
    floors: FloorLabels = field(default_factory=FloorLabels)
    output: OutputConfig = field(default_factory=OutputConfig)
    pdf_zoom: float = 2.0


# Default configuration instance
DEFAULT_CONFIG = PlanParserConfig()
