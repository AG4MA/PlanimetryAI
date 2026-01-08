"""
PlanParser Configuration
========================
Central configuration for all parsing parameters.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Package root directory - all paths relative to this
PACKAGE_DIR = Path(__file__).parent.resolve()


class SourceType(Enum):
    """Supported input source types."""
    PDF = "pdf"
    IMAGE = "image"  # PNG, JPG, TIFF, etc.
    DWG = "dwg"
    DXF = "dxf"
    
    @classmethod
    def from_extension(cls, path: str | Path) -> "SourceType":
        """Auto-detect source type from file extension."""
        ext = Path(path).suffix.lower()
        mapping = {
            ".pdf": cls.PDF,
            ".png": cls.IMAGE,
            ".jpg": cls.IMAGE,
            ".jpeg": cls.IMAGE,
            ".tiff": cls.IMAGE,
            ".tif": cls.IMAGE,
            ".bmp": cls.IMAGE,
            ".dwg": cls.DWG,
            ".dxf": cls.DXF,
        }
        if ext not in mapping:
            raise ValueError(f"Unsupported file extension: {ext}")
        return mapping[ext]


class Orientation(Enum):
    """Cardinal orientations."""
    NORTH = "N"
    SOUTH = "S"
    EAST = "E"
    WEST = "W"
    NORTH_EAST = "NE"
    NORTH_WEST = "NW"
    SOUTH_EAST = "SE"
    SOUTH_WEST = "SW"
    UNKNOWN = "?"


@dataclass
class ScaleConfig:
    """Scale and orientation configuration."""
    # Scale ratio (e.g., 100 means 1:100)
    scale_ratio: float | None = None
    
    # Pixels per meter (calculated from scale + DPI)
    pixels_per_meter: float | None = None
    
    # North orientation in degrees (0 = up, 90 = right, etc.)
    north_angle_degrees: float | None = None
    
    # Was scale auto-detected or provided by user?
    scale_detected: bool = False
    orientation_detected: bool = False
    
    # Default scale when --noscale is used (1:100 is common for apartments)
    default_scale_ratio: float = 100.0
    
    # Default north angle when --nocompass is used (0 = north is up)
    default_north_angle: float = 0.0
    
    def get_effective_scale(self) -> float:
        """Return detected scale or default."""
        return self.scale_ratio if self.scale_ratio else self.default_scale_ratio
    
    def get_effective_north_angle(self) -> float:
        """Return detected north angle or default."""
        return self.north_angle_degrees if self.north_angle_degrees is not None else self.default_north_angle


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
    psm_modes: list[int] = field(default_factory=lambda: [7, 6, 11])
    padding: int = 4
    scale_factor: int = 4
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .-_/"
    tesseract_path: str | None = None  # Set if not in PATH


@dataclass
class RoomLabels:
    """Room label recognition configuration."""
    # Target room types (Italian)
    targets: set[str] = field(default_factory=lambda: {
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
    blacklist: set[str] = field(default_factory=lambda: {
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
    ordinals: list[str] = field(default_factory=lambda: [
        "terra", "primo", "secondo", "terzo", "quarto",
        "quinto", "sesto", "settimo", "ottavo", "nono", "decimo"
    ])


@dataclass
class OutputConfig:
    """Output and debug configuration."""
    debug_dir: Path = field(default_factory=lambda: PACKAGE_DIR / "debug_image")
    output_dir: Path = field(default_factory=lambda: PACKAGE_DIR / "output")
    save_intermediate: bool = True
    log_level: str = "INFO"


@dataclass
class PlanParserConfig:
    """Master configuration combining all settings."""
    # Source configuration
    source_type: SourceType | None = None  # Auto-detected if None
    
    # Scale and orientation
    scale: ScaleConfig = field(default_factory=ScaleConfig)
    use_default_scale: bool = False  # --noscale flag
    use_default_compass: bool = False  # --nocompass flag
    
    # Processing configs
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    rooms: RoomLabels = field(default_factory=RoomLabels)
    floors: FloorLabels = field(default_factory=FloorLabels)
    output: OutputConfig = field(default_factory=OutputConfig)
    pdf_zoom: float = 2.0


# Default configuration instance
DEFAULT_CONFIG = PlanParserConfig()
