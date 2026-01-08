"""
Extraction Layer
================
Pipeline for extracting structured data from planimetry sources.

This layer transforms raw inputs (PDF, images, CAD) into the domain model.
It orchestrates the extraction process through multiple stages:

1. READING: Load source file (PDF, DWG, image) → raw pixels/vectors
2. PREPROCESSING: Image enhancement, noise reduction
3. GEOMETRY: Line detection, polygon extraction
4. FLOOR: Floor label detection, section splitting
5. ROOM: Room label detection, room polygon association
6. SCALE: Scale detection, measurement calibration
7. SEMANTIC: Element classification (doors, windows, walls)
8. TOPOLOGY: Adjacency graph, connectivity analysis

The final output is a DigitalTwin in the domain layer.
"""

# Sub-modules
from PlanParser.extraction import geometry
from PlanParser.extraction import floor
from PlanParser.extraction import room
from PlanParser.extraction import scale

# Image processing utilities
from PlanParser.extraction.image_processing import (
    find_largest_rectangle,
    crop_region,
    draw_rectangles,
)

__all__ = [
    # Modules
    "geometry",
    "floor",
    "room", 
    "scale",
    
    # Image processing
    "find_largest_rectangle",
    "crop_region",
    "draw_rectangles",
]
