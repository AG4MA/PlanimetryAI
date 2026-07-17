"""Versioned matching configuration for Point 1 evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class EvaluationConfig:
    """Technical matching tolerances, not Gate 1 acceptance thresholds."""

    config_version: str = "1.0.0"
    bbox_iou_threshold: float = 0.50
    polygon_iou_threshold: float = 0.50
    line_distance_threshold_fraction: float = 0.002
    line_min_coverage: float = 0.80
    point_distance_threshold_fraction: float = 0.005
    max_polyline_samples: int = 256
    max_polygon_raster_pixels: int = 4_000_000
    calibration_bins: int = 10
    calibration_binning: str = "equal_frequency"
    text_case_sensitive: bool = False
    text_collapse_whitespace: bool = True
    require_frozen_ground_truth: bool = True

    def __post_init__(self) -> None:
        if self.config_version != "1.0.0":
            raise ValueError("Unsupported evaluation config_version")
        for name in ("bbox_iou_threshold", "polygon_iou_threshold"):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in (
            "line_distance_threshold_fraction",
            "point_distance_threshold_fraction",
        ):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if not 0 < self.line_min_coverage <= 1:
            raise ValueError("line_min_coverage must be in (0, 1]")
        if self.max_polyline_samples < 2:
            raise ValueError("max_polyline_samples must be at least 2")
        if self.max_polygon_raster_pixels < 1_024:
            raise ValueError("max_polygon_raster_pixels must be at least 1024")
        if self.calibration_bins < 2:
            raise ValueError("calibration_bins must be at least 2")
        if self.calibration_binning != "equal_frequency":
            raise ValueError("calibration_binning must be 'equal_frequency'")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvaluationConfig":
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"Unknown evaluation config fields: {', '.join(unknown)}")
        return cls(**dict(value))
