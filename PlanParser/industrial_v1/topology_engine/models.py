from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class CoordinateFrame:
    """Lossless transform between a region crop and its source page."""

    page_id: str
    region_id: str
    bbox_page_px_xywh: tuple[int, int, int, int]
    document_id: str = "unknown_document"

    def __post_init__(self) -> None:
        if not self.document_id or not self.page_id or not self.region_id:
            raise ValueError("document_id, page_id and region_id must be non-empty")
        bbox = tuple(int(value) for value in self.bbox_page_px_xywh)
        if len(bbox) != 4:
            raise ValueError("bbox_page_px_xywh must contain four values")
        if bbox[2] <= 0 or bbox[3] <= 0:
            raise ValueError("coordinate-frame width and height must be positive")
        object.__setattr__(self, "bbox_page_px_xywh", bbox)

    @property
    def offset_page_px(self) -> tuple[int, int]:
        return self.bbox_page_px_xywh[0], self.bbox_page_px_xywh[1]

    @property
    def width_px(self) -> int:
        return self.bbox_page_px_xywh[2]

    @property
    def height_px(self) -> int:
        return self.bbox_page_px_xywh[3]

    def crop_to_page(self, point_crop_px: Sequence[float]) -> tuple[float, float]:
        if len(point_crop_px) != 2:
            raise ValueError("point_crop_px must contain two values")
        offset_x, offset_y = self.offset_page_px
        return float(point_crop_px[0]) + offset_x, float(point_crop_px[1]) + offset_y

    def crop_bbox_xywh_to_page(
        self, bbox_crop_px_xywh: Sequence[float]
    ) -> tuple[float, float, float, float]:
        if len(bbox_crop_px_xywh) != 4:
            raise ValueError("bbox_crop_px_xywh must contain four values")
        x, y = self.crop_to_page(bbox_crop_px_xywh[:2])
        return x, y, float(bbox_crop_px_xywh[2]), float(bbox_crop_px_xywh[3])

    def crop_bbox_xyxy_to_page(
        self, bbox_crop_px_xyxy: Sequence[float]
    ) -> tuple[float, float, float, float]:
        if len(bbox_crop_px_xyxy) != 4:
            raise ValueError("bbox_crop_px_xyxy must contain four values")
        x1, y1 = self.crop_to_page(bbox_crop_px_xyxy[:2])
        x2, y2 = self.crop_to_page(bbox_crop_px_xyxy[2:])
        return x1, y1, x2, y2


@dataclass(frozen=True)
class BarrierResult:
    """Separate observed, artificial, synthetic and effective barrier layers.

    ``raw_observed`` preserves legacy behavior and is the union of actual
    candidate geometry and the optional artificial crop boundary.  The two
    contributors remain available separately so downstream code never needs
    to mistake the crop edge for observed plan geometry.
    """

    observed_geometry: np.ndarray = field(repr=False, compare=False)
    crop_boundary: np.ndarray = field(repr=False, compare=False)
    raw_observed: np.ndarray = field(repr=False, compare=False)
    synthetic_closures: np.ndarray = field(repr=False, compare=False)
    effective_barrier: np.ndarray = field(repr=False, compare=False)
    line_audit: tuple[Mapping[str, Any], ...]
    band_audit: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        layers = (
            self.observed_geometry,
            self.crop_boundary,
            self.raw_observed,
            self.synthetic_closures,
            self.effective_barrier,
        )
        shape = layers[0].shape
        if len(shape) != 2:
            raise ValueError("barrier layers must be two-dimensional")
        for layer in layers:
            if layer.shape != shape:
                raise ValueError("all barrier layers must have the same shape")
            if layer.dtype != np.uint8:
                raise ValueError("barrier layers must use uint8")

    @property
    def used_line_ids(self) -> frozenset[str]:
        return frozenset(
            str(item["id"]) for item in self.line_audit if item["used_as_barrier"]
        )

    @property
    def used_band_ids(self) -> frozenset[str]:
        return frozenset(
            str(item["id"]) for item in self.band_audit if item["used_as_barrier"]
        )
