"""
PlanParser - Main Pipeline
==========================
Unified entry point for parsing planimetry PDFs.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field, asdict
import json
import logging
from datetime import datetime

from .config import PlanParserConfig, DEFAULT_CONFIG
from .pdf_reader import render_pdf_page, get_pdf_page_count, extract_text_from_pdf
from .image_processing import find_largest_rectangle, crop_region, draw_rectangles
from .ocr_engine import OCRManager
from .floor_detection import FloorDetector, FloorSection
from .room_detection import RoomDetector, DetectedRoom
from .geometry import RawPlanGeometry, Point2D, Polygon, TextEntity

logger = logging.getLogger(__name__)


@dataclass
class ParsedFloor:
    """Result for a single floor."""
    floor_label: str
    floor_number: int
    rooms: List[Dict[str, Any]]
    image_path: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ParseResult:
    """Complete parsing result for a planimetry."""
    success: bool
    source_file: str
    floors: List[ParsedFloor]
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    debug_images: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class PlanParser:
    """
    Main planimetry parser class.
    
    Workflow:
    1. Load PDF → Render to image
    2. Detect main planimetry rectangle (if needed)
    3. Detect floor labels → Split into sections
    4. For each floor section → Detect rooms
    5. Output structured data + debug images
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
        
        # Ensure output directories exist
        self.config.output.debug_dir.mkdir(parents=True, exist_ok=True)
        self.config.output.output_dir.mkdir(parents=True, exist_ok=True)
    
    def parse(
        self,
        pdf_path: Union[str, Path],
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
        
        result = ParseResult(
            success=False,
            source_file=str(pdf_path),
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
            
            # Step 2: Find main rectangle (planimetry boundary)
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
        image_path: Union[str, Path],
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
        
        result = ParseResult(
            success=False,
            source_file=str(image_path),
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
            
            # Use same processing as PDF (skip rectangle detection for pre-cropped)
            floor_sections = self.floor_detector.split_into_floors(image, anchor=floor_anchor)
            
            for i, section in enumerate(floor_sections):
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
    pdf_path: Union[str, Path],
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
