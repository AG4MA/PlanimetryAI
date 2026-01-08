"""
Floor Extraction
================
Detection of floor labels and section boundaries.
Splits multi-floor planimetries into separate floor images.
"""

from PlanParser.extraction.floor.detector import FloorDetector

__all__ = ["FloorDetector"]
