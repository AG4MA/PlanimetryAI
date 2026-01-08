"""
Room Extraction
===============
Detection of room labels and room boundaries.
Associates OCR-detected labels with geometric polygons.
"""

from PlanParser.extraction.room.detector import RoomDetector

__all__ = ["RoomDetector"]
