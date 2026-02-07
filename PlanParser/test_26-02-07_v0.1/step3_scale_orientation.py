"""
Step 3: Scale and Orientation extraction (STUB).

These functions are placeholders. Scale and orientation detection
will be implemented in a future iteration.
"""

import numpy as np
from typing import Optional
import logging


def extract_scale(
    image: np.ndarray,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    """
    STUB: Extract scale information from the floor plan image.

    TODO: Detect scale bar or scale text in the image.
    Possible approaches:
      - OCR for text like "1:100", "1:200", "SCALA 1:100"
      - Detect scale bar graphic and measure pixel length vs label
      - User provides via CLI arg (already supported in run_pipeline.py)

    Returns:
        None (not implemented yet).
    """
    print("  TODO: extract scale from image (not implemented)")
    if logger:
        logger.info("  STUB: scale extraction not implemented")
    return None


def extract_orientation(
    image: np.ndarray,
    logger: Optional[logging.Logger] = None,
) -> Optional[float]:
    """
    STUB: Extract north orientation from the floor plan image.

    TODO: Detect compass/north arrow symbol in the image.
    Possible approaches:
      - Template matching for common north arrow symbols
      - OCR for "N" label near an arrow
      - User provides via CLI arg

    Returns:
        None (not implemented yet). Would return degrees from top.
    """
    print("  TODO: extract orientation from image (not implemented)")
    if logger:
        logger.info("  STUB: orientation extraction not implemented")
    return None
