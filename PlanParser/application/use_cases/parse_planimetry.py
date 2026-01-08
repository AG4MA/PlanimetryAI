"""
PlanParser - Main Pipeline
==========================
Unified entry point for parsing planimetry files (PDF, images, DWG, DXF).
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from PlanParser.domain.config import DEFAULT_CONFIG, PlanParserConfig, SourceType
from PlanParser.extraction.floor.detector import FloorDetector
from PlanParser.domain.models.primitives import Point2D, Polygon, RawPlanGeometry, TextEntity
from PlanParser.extraction.image_processing import crop_region, draw_rectangles, find_largest_rectangle
from PlanParser.infrastructure.ocr.engine import OCRManager
from PlanParser.infrastructure.readers.pdf_reader import render_pdf_page
from PlanParser.extraction.room.detector import RoomDetector
from PlanParser.extraction.scale.detector import ScaleDetector, prompt_user_for_scale, prompt_user_for_compass

logger = logging.getLogger(__name__)


@dataclass
class ParsedFloor:
    """Result for a single floor."""
    floor_label: str
    floor_number: int
    rooms: list[dict[str, Any]]
    image_path: str | None = None
    confidence: float = 0.0


@dataclass
class ParseResult:
    """Complete parsing result for a planimetry."""
    success: bool
    source_file: str
    source_type: str = "unknown"
    floors: list[ParsedFloor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    debug_images: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class PlanParser:
    """
    Main planimetry parser class.

    Workflow:
    1. Load source file → Render/convert to image
    2. Detect scale and orientation
    3. Detect main planimetry rectangle (if needed)
    4. Detect floor labels → Split into sections
    5. For each floor section → Detect rooms
    6. Output structured data + debug images
    """

    def __init__(self, config: PlanParserConfig = None):
        self.config = config or DEFAULT_CONFIG

        # Initialize OCR
        self.ocr = OCRManager(tesseract_path=self.config.ocr.tesseract_path)

        # Initialize detectors
        self.floor_detector = FloorDetector(self.ocr)
        self.room_detector = RoomDetector(
            self.ocr,
            self.config.rooms,
            self.config.detection
        )
        self.scale_detector = ScaleDetector(self.ocr)

        # Ensure output directories exist
        self.config.output.debug_dir.mkdir(parents=True, exist_ok=True)
        self.config.output.output_dir.mkdir(parents=True, exist_ok=True)

    def _detect_scale_and_orientation(self, image, result: ParseResult) -> None:
        """
        Detect or set scale and orientation for the planimetry.
        
        Modifies result.metadata with scale and orientation information.
        """
        scale_config = self.config.scale
        
        # --- SCALE ---
        if scale_config.scale_ratio:
            # Scale was provided by user via --scale
            result.metadata["scale"] = {
                "ratio": scale_config.scale_ratio,
                "detected": False,
                "source": "user_provided"
            }
            logger.info(f"Using user-provided scale: 1:{int(scale_config.scale_ratio)}")
            
        elif self.config.use_default_scale:
            # --noscale flag: use default without detection
            result.metadata["scale"] = {
                "ratio": scale_config.default_scale_ratio,
                "detected": False,
                "source": "default"
            }
            logger.info(f"Using default scale: 1:{int(scale_config.default_scale_ratio)}")
            
        else:
            # Attempt auto-detection
            logger.info("Attempting scale auto-detection...")
            detected_config = self.scale_detector.detect_all(image)
            
            if detected_config.scale_ratio:
                result.metadata["scale"] = {
                    "ratio": detected_config.scale_ratio,
                    "detected": True,
                    "source": "auto_detected"
                }
                logger.info(f"Scale auto-detected: 1:{int(detected_config.scale_ratio)}")
                # Store detected orientation for later use
                scale_config.north_angle_degrees = detected_config.north_angle_degrees
                scale_config.orientation_detected = detected_config.orientation_detected
            else:
                # Scale not found - prompt user
                logger.warning("Scale not detected automatically")
                user_scale = prompt_user_for_scale()
                result.metadata["scale"] = {
                    "ratio": user_scale,
                    "detected": False,
                    "source": "user_input"
                }
                # Also try to get orientation from the detection
                scale_config.north_angle_degrees = detected_config.north_angle_degrees
                scale_config.orientation_detected = detected_config.orientation_detected
        
        # --- ORIENTATION ---
        if scale_config.north_angle_degrees is not None:
            # Orientation was provided by user via --compass OR auto-detected
            result.metadata["orientation"] = {
                "north_angle_degrees": scale_config.north_angle_degrees,
                "detected": scale_config.orientation_detected,
                "source": "user_provided" if not scale_config.orientation_detected else "auto_detected"
            }
            logger.info(f"Orientation: {scale_config.north_angle_degrees}° (detected={scale_config.orientation_detected})")
            
        elif self.config.use_default_compass:
            # --nocompass flag: use default without detection
            result.metadata["orientation"] = {
                "north_angle_degrees": scale_config.default_north_angle,
                "detected": False,
                "source": "default"
            }
            logger.info(f"Using default orientation: {scale_config.default_north_angle}° (--nocompass)")
            
        else:
            # Orientation not detected and not using default - prompt user
            logger.warning("Orientation not detected automatically")
            user_angle = prompt_user_for_compass()
            result.metadata["orientation"] = {
                "north_angle_degrees": user_angle,
                "detected": False,
                "source": "user_input"
            }

    def parse(
        self,
        pdf_path: str | Path,
        page_num: int = 0,
        floor_anchor: str = "up"
    ) -> ParseResult:
        """
        Parse a planimetry PDF file.

        Args:
            pdf_path: Path to the PDF file
            page_num: Page number to process (0-indexed)
            floor_anchor: "up" or "down" - where to draw floor split lines

        Returns:
            ParseResult with detected floors and rooms
        """
        pdf_path = Path(pdf_path)
        source_type = self.config.source_type or SourceType.PDF

        result = ParseResult(
            success=False,
            source_file=str(pdf_path),
            source_type=source_type.value,
            floors=[],
            metadata={
                "processed_at": datetime.now().isoformat(),
                "page_number": page_num,
                "config": {
                    "floor_anchor": floor_anchor,
                    "pdf_zoom": self.config.pdf_zoom
                }
            }
        )

        try:
            # Step 1: Render PDF to image
            logger.info(f"Parsing: {pdf_path}")
            image = render_pdf_page(pdf_path, page_num, zoom=self.config.pdf_zoom)

            if image is None:
                result.errors.append(f"Failed to render PDF page {page_num}")
                return result

            result.metadata["image_size"] = {"width": image.shape[1], "height": image.shape[0]}

            # Save original
            if self.config.output.save_intermediate:
                orig_path = self.config.output.debug_dir / "01_original.png"
                cv2.imwrite(str(orig_path), image)
                result.debug_images["original"] = str(orig_path)

            # Step 2: Detect scale and orientation
            self._detect_scale_and_orientation(image, result)

            # Step 3: Find main rectangle (planimetry boundary)
            main_rect = find_largest_rectangle(image)

            if main_rect:
                x, y, w, h = main_rect
                logger.info(f"Found main rectangle: x={x}, y={y}, w={w}, h={h}")

                # Draw and save
                if self.config.output.save_intermediate:
                    rect_img = draw_rectangles(image, [main_rect], color=(0, 255, 0), thickness=3)
                    rect_path = self.config.output.debug_dir / "02_rectangle.png"
                    cv2.imwrite(str(rect_path), rect_img)
                    result.debug_images["rectangle"] = str(rect_path)

                # Crop to main rectangle with small padding
                padding = 5
                cropped = crop_region(image, main_rect, padding=-padding)
            else:
                logger.warning("No main rectangle found, using full image")
                cropped = image

            # Save cropped base
            if self.config.output.save_intermediate:
                base_path = self.config.output.debug_dir / "03_base.png"
                cv2.imwrite(str(base_path), cropped)
                result.debug_images["base"] = str(base_path)

            # Step 3: Detect floors and split
            floor_sections = self.floor_detector.split_into_floors(cropped, anchor=floor_anchor)

            # Visualize floor lines
            if self.config.output.save_intermediate:
                floor_viz = self.floor_detector.visualize_floor_lines(cropped, floor_sections)
                floor_path = self.config.output.debug_dir / "04_floors.png"
                cv2.imwrite(str(floor_path), floor_viz)
                result.debug_images["floors"] = str(floor_path)

            # Step 4: Process each floor section
            for i, section in enumerate(floor_sections):
                logger.info(f"Processing floor: {section.floor_label}")

                # Detect rooms in this section
                rooms = self.room_detector.detect_rooms(section.image)

                # Save section image
                section_name = f"section_{i+1}_{section.floor_label.replace(' ', '_')}"
                if self.config.output.save_intermediate:
                    section_path = self.config.output.debug_dir / f"05_{section_name}.png"
                    cv2.imwrite(str(section_path), section.image)

                    # Room visualization
                    room_viz = self.room_detector.visualize(section.image, rooms)
                    viz_path = self.config.output.debug_dir / f"06_{section_name}_rooms.png"
                    cv2.imwrite(str(viz_path), room_viz)
                    result.debug_images[f"rooms_{section_name}"] = str(viz_path)

                # Build floor result
                parsed_floor = ParsedFloor(
                    floor_label=section.floor_label,
                    floor_number=section.floor_number,
                    rooms=[
                        {
                            "label": r.label,
                            "bbox": r.bbox,
                            "center": r.center,
                            "confidence": r.confidence,
                            "raw_text": r.raw_ocr_text
                        }
                        for r in rooms
                    ],
                    confidence=section.confidence
                )
                result.floors.append(parsed_floor)

            result.success = True
            logger.info(f"Successfully parsed {len(result.floors)} floors")

        except Exception as e:
            logger.exception(f"Parsing failed: {e}")
            result.errors.append(str(e))

        return result

    def parse_image(
        self,
        image_path: str | Path,
        floor_anchor: str = "up"
    ) -> ParseResult:
        """
        Parse a planimetry image file (PNG, JPG, etc.).

        Args:
            image_path: Path to the image file
            floor_anchor: "up" or "down"

        Returns:
            ParseResult
        """
        image_path = Path(image_path)
        source_type = self.config.source_type or SourceType.IMAGE

        result = ParseResult(
            success=False,
            source_file=str(image_path),
            source_type=source_type.value,
            floors=[],
            metadata={
                "processed_at": datetime.now().isoformat(),
                "config": {"floor_anchor": floor_anchor}
            }
        )

        try:
            image = cv2.imread(str(image_path))
            if image is None:
                result.errors.append(f"Failed to load image: {image_path}")
                return result

            result.metadata["image_size"] = {"width": image.shape[1], "height": image.shape[0]}

            # Detect scale and orientation
            self._detect_scale_and_orientation(image, result)

            # Use same processing as PDF (skip rectangle detection for pre-cropped)
            floor_sections = self.floor_detector.split_into_floors(image, anchor=floor_anchor)

            for _i, section in enumerate(floor_sections):
                rooms = self.room_detector.detect_rooms(section.image)

                parsed_floor = ParsedFloor(
                    floor_label=section.floor_label,
                    floor_number=section.floor_number,
                    rooms=[
                        {
                            "label": r.label,
                            "bbox": r.bbox,
                            "center": r.center,
                            "confidence": r.confidence
                        }
                        for r in rooms
                    ],
                    confidence=section.confidence
                )
                result.floors.append(parsed_floor)

            result.success = True

        except Exception as e:
            logger.exception(f"Image parsing failed: {e}")
            result.errors.append(str(e))

        return result

    def to_geometry(self, result: ParseResult) -> RawPlanGeometry:
        """
        Convert parse result to geometry format.

        Useful for downstream processing (Plan2HVAC, etc.)
        """
        geometry = RawPlanGeometry()

        for floor in result.floors:
            for room in floor.rooms:
                # Create polygon from bbox
                x, y, w, h = room["bbox"]
                vertices = [
                    Point2D(x, y),
                    Point2D(x + w, y),
                    Point2D(x + w, y + h),
                    Point2D(x, y + h)
                ]
                geometry.polygons.append(Polygon(
                    vertices=vertices,
                    layer=f"floor_{floor.floor_number}"
                ))

                # Create text entity for label
                cx, cy = room["center"]
                geometry.texts.append(TextEntity(
                    text=room["label"],
                    position=Point2D(cx, cy),
                    layer=f"floor_{floor.floor_number}"
                ))

        return geometry


def parse_planimetry(
    pdf_path: str | Path,
    config: PlanParserConfig = None
) -> ParseResult:
    """
    Convenience function to parse a planimetry PDF.

    Args:
        pdf_path: Path to PDF file
        config: Optional configuration

    Returns:
        ParseResult
    """
    parser = PlanParser(config)
    return parser.parse(pdf_path)
