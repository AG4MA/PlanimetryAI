"""
Debug utilities: logging setup, image saving, visualization helpers.
"""

import cv2
import numpy as np
import logging
import sys
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING
from logging.handlers import RotatingFileHandler

if TYPE_CHECKING:
    from geometry_types import Segment, TextBlock


def setup_logger(name: str, log_dir: Path, level=logging.DEBUG) -> logging.Logger:
    """Create a logger with console + rotating file handlers."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    fmt_console = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    fmt_file = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt_console)

    fh = RotatingFileHandler(
        str(log_dir / "pipeline.log"),
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt_file)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


def save_debug_image(
    image: np.ndarray,
    path: Path,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Save a debug image, creating parent dirs if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), image)
    if logger:
        if ok:
            logger.debug("  Saved %s (%dx%d)", path.name, image.shape[1], image.shape[0])
        else:
            logger.warning("  Failed to save %s", path)


def draw_segments_on_image(
    image: np.ndarray,
    segments: List["Segment"],
    color=(0, 255, 0),
    thickness: int = 2,
) -> np.ndarray:
    """Draw line segments on an image copy."""
    out = image.copy()
    for s in segments:
        cv2.line(out, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)), color, thickness)
    return out


def draw_text_blocks_on_image(
    image: np.ndarray,
    text_blocks: List["TextBlock"],
    color=(255, 0, 0),
    thickness: int = 1,
) -> np.ndarray:
    """Draw OCR text block bounding boxes with labels on an image copy."""
    out = image.copy()
    for tb in text_blocks:
        cv2.rectangle(out, (tb.x, tb.y), (tb.x + tb.w, tb.y + tb.h), color, thickness)
        label = f"{tb.text} ({tb.confidence:.0f}%)"
        cv2.putText(
            out, label,
            (tb.x, max(tb.y - 4, 10)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1,
        )
    return out
