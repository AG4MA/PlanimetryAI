"""
Scale and Orientation Detection
===============================
Detects scale indicators and compass/orientation markers in planimetry.

Scale formats commonly found:
- "1:100", "1:50", "1:200"
- "Scala 1:100"
- Graphic scale bars with measurements

Orientation formats:
- Compass rose with N/S/E/W
- Arrow pointing North
- Text "NORD" or "N"
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from .config import Orientation, ScaleConfig

if TYPE_CHECKING:
    from .ocr_engine import OCRManager

logger = logging.getLogger(__name__)


# Scale patterns (Italian and international)
SCALE_PATTERNS = [
    # "1:100", "1 : 100", "1/100"
    (r"1\s*[:/]\s*(\d+)", 1.0),
    # "Scala 1:100", "scala 1/50"
    (r"scala\s*1\s*[:/]\s*(\d+)", 1.0),
    # "Scale 1:100" (English)
    (r"scale\s*1\s*[:/]\s*(\d+)", 0.95),
    # "SC. 1:100"
    (r"sc\.?\s*1\s*[:/]\s*(\d+)", 0.9),
]

# Orientation patterns
ORIENTATION_PATTERNS = [
    (r"\bnord\b", Orientation.NORTH, 1.0),
    (r"\bsud\b", Orientation.SOUTH, 1.0),
    (r"\best\b", Orientation.EAST, 1.0),
    (r"\bovest\b", Orientation.WEST, 1.0),
    (r"\bnorth\b", Orientation.NORTH, 0.95),
    (r"\bsouth\b", Orientation.SOUTH, 0.95),
    (r"\bwest\b", Orientation.WEST, 0.95),
    # Single letters (lower confidence - could be other things)
    (r"(?<![a-z])[N](?![a-z])", Orientation.NORTH, 0.7),
    (r"(?<![a-z])[S](?![a-z])", Orientation.SOUTH, 0.6),
    (r"(?<![a-z])[E](?![a-z])", Orientation.EAST, 0.6),
    (r"(?<![a-z])[W|O](?![a-z])", Orientation.WEST, 0.6),
]


@dataclass
class ScaleDetectionResult:
    """Result of scale detection."""
    scale_ratio: float | None = None
    confidence: float = 0.0
    bbox: tuple[int, int, int, int] | None = None
    raw_text: str = ""


@dataclass
class OrientationDetectionResult:
    """Result of orientation detection."""
    orientation: Orientation = Orientation.UNKNOWN
    north_angle_degrees: float | None = None  # 0 = up, 90 = right
    confidence: float = 0.0
    bbox: tuple[int, int, int, int] | None = None


class ScaleDetector:
    """
    Detects scale and orientation markers in planimetry images.
    """
    
    def __init__(self, ocr_manager: "OCRManager"):
        self.ocr = ocr_manager
        self._scale_patterns = [
            (re.compile(p, re.IGNORECASE), conf) 
            for p, conf in SCALE_PATTERNS
        ]
        self._orientation_patterns = [
            (re.compile(p, re.IGNORECASE), orient, conf)
            for p, orient, conf in ORIENTATION_PATTERNS
        ]
    
    def detect_scale(self, image: np.ndarray) -> ScaleDetectionResult:
        """
        Detect scale ratio from image.
        
        Searches for text patterns like "1:100" and graphic scale bars.
        
        Args:
            image: BGR image
            
        Returns:
            ScaleDetectionResult with detected scale or None
        """
        result = ScaleDetectionResult()
        
        # Strategy 1: OCR-based detection (text "1:100", "Scala 1:50", etc.)
        ocr_result = self._detect_scale_from_text(image)
        if ocr_result.scale_ratio:
            logger.info(f"Scale detected via OCR: 1:{ocr_result.scale_ratio} (conf={ocr_result.confidence:.2f})")
            return ocr_result
        
        # Strategy 2: Graphic scale bar detection
        bar_result = self._detect_scale_bar(image)
        if bar_result.scale_ratio:
            logger.info(f"Scale detected via bar: 1:{bar_result.scale_ratio} (conf={bar_result.confidence:.2f})")
            return bar_result
        
        logger.warning("No scale detected in image")
        return result
    
    def _detect_scale_from_text(self, image: np.ndarray) -> ScaleDetectionResult:
        """Detect scale from OCR text."""
        result = ScaleDetectionResult()
        
        # Run OCR on the image
        ocr_results = self.ocr.recognize(image)
        
        best_match = None
        best_conf = 0.0
        
        for ocr_item in ocr_results:
            text = ocr_item.text
            
            for pattern, pattern_conf in self._scale_patterns:
                match = pattern.search(text)
                if match:
                    try:
                        scale_value = int(match.group(1))
                        combined_conf = pattern_conf * ocr_item.confidence
                        
                        if combined_conf > best_conf and 10 <= scale_value <= 1000:
                            best_conf = combined_conf
                            best_match = (scale_value, ocr_item.bbox, text)
                    except (ValueError, IndexError):
                        continue
        
        if best_match:
            scale_value, bbox, raw_text = best_match
            result.scale_ratio = float(scale_value)
            result.confidence = best_conf
            result.bbox = bbox
            result.raw_text = raw_text
        
        return result
    
    def _detect_scale_bar(self, image: np.ndarray) -> ScaleDetectionResult:
        """
        Detect graphic scale bar.
        
        Looks for:
        - Horizontal line with tick marks
        - Text with measurements nearby (e.g., "0  1  2  3 m")
        
        This is more complex and would need measurements + OCR combined.
        For now, returns empty result - to be implemented.
        """
        # TODO: Implement graphic scale bar detection
        # This requires:
        # 1. Find horizontal lines with regular tick marks
        # 2. Find nearby text with numbers and units (m, cm, mm)
        # 3. Calculate pixels-per-meter from the bar length
        return ScaleDetectionResult()
    
    def detect_orientation(self, image: np.ndarray) -> OrientationDetectionResult:
        """
        Detect compass/orientation from image.
        
        Looks for:
        - Compass rose symbol
        - Arrow with "N" or "NORD"
        - Text indicating cardinal directions
        
        Args:
            image: BGR image
            
        Returns:
            OrientationDetectionResult
        """
        result = OrientationDetectionResult()
        
        # Strategy 1: Text-based detection
        text_result = self._detect_orientation_from_text(image)
        if text_result.orientation != Orientation.UNKNOWN:
            logger.info(f"Orientation detected: {text_result.orientation.value} (conf={text_result.confidence:.2f})")
            return text_result
        
        # Strategy 2: Symbol detection (arrow, compass rose)
        # TODO: Implement visual compass detection
        
        logger.warning("No orientation detected in image")
        return result
    
    def _detect_orientation_from_text(self, image: np.ndarray) -> OrientationDetectionResult:
        """Detect orientation from OCR text."""
        result = OrientationDetectionResult()
        
        ocr_results = self.ocr.recognize(image)
        
        best_match = None
        best_conf = 0.0
        
        for ocr_item in ocr_results:
            text = ocr_item.text
            
            for pattern, orientation, pattern_conf in self._orientation_patterns:
                if pattern.search(text):
                    combined_conf = pattern_conf * ocr_item.confidence
                    
                    if combined_conf > best_conf:
                        best_conf = combined_conf
                        best_match = (orientation, ocr_item.bbox)
        
        if best_match:
            orientation, bbox = best_match
            result.orientation = orientation
            result.confidence = best_conf
            result.bbox = bbox
            
            # For now, assume north is up (0 degrees) when we find a north indicator
            if orientation == Orientation.NORTH:
                result.north_angle_degrees = 0.0
        
        return result
    
    def detect_all(self, image: np.ndarray) -> ScaleConfig:
        """
        Detect both scale and orientation, returning a ScaleConfig.
        
        Args:
            image: BGR image
            
        Returns:
            ScaleConfig with detected values
        """
        config = ScaleConfig()
        
        # Detect scale
        scale_result = self.detect_scale(image)
        if scale_result.scale_ratio:
            config.scale_ratio = scale_result.scale_ratio
            config.scale_detected = True
        
        # Detect orientation
        orient_result = self.detect_orientation(image)
        if orient_result.orientation != Orientation.UNKNOWN:
            config.north_angle_degrees = orient_result.north_angle_degrees
            config.orientation_detected = True
        
        return config


def prompt_user_for_scale() -> float:
    """
    Interactive prompt for user to enter scale.
    
    Returns:
        Scale ratio (e.g., 100 for 1:100)
    """
    print("\n" + "=" * 50)
    print("⚠️  SCALA NON RILEVATA")
    print("=" * 50)
    print("Non è stato possibile rilevare automaticamente la scala.")
    print("Inserisci la scala della planimetria.")
    print("Esempi comuni: 100 (per 1:100), 50 (per 1:50), 200 (per 1:200)")
    print()
    
    while True:
        try:
            user_input = input("Scala (solo il numero, es. 100): ").strip()
            scale = float(user_input)
            
            if 10 <= scale <= 1000:
                print(f"✅ Scala impostata: 1:{int(scale)}")
                return scale
            else:
                print("⚠️  Valore non valido. Inserisci un numero tra 10 e 1000.")
        except ValueError:
            print("⚠️  Input non valido. Inserisci un numero.")
        except KeyboardInterrupt:
            print("\n❌ Operazione annullata. Uso scala default 1:100")
            return 100.0


def prompt_user_for_compass() -> float:
    """
    Interactive prompt for user to enter north orientation.
    
    Returns:
        North angle in degrees (0 = up/north, 90 = right/east, etc.)
    """
    print("\n" + "=" * 50)
    print("🧭 ORIENTAMENTO NON RILEVATO")
    print("=" * 50)
    print("Non è stato possibile rilevare automaticamente l'orientamento.")
    print("Inserisci l'angolo del Nord rispetto all'alto della pagina.")
    print()
    print("  0° = Nord in alto (default)")
    print(" 90° = Nord a destra")
    print("180° = Nord in basso")
    print("270° = Nord a sinistra")
    print()
    
    while True:
        try:
            user_input = input("Angolo Nord (0-360, default 0): ").strip()
            
            if not user_input:
                print("✅ Orientamento impostato: 0° (Nord in alto)")
                return 0.0
            
            angle = float(user_input)
            angle = angle % 360  # Normalize to 0-360
            
            print(f"✅ Orientamento impostato: {angle}°")
            return angle
        except ValueError:
            print("⚠️  Input non valido. Inserisci un numero tra 0 e 360.")
        except KeyboardInterrupt:
            print("\n❌ Operazione annullata. Uso orientamento default 0°")
            return 0.0
