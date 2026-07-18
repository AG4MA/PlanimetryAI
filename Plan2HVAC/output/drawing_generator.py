"""Dependency-free SVG drawing generation for HVAC layouts."""

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable, List, Tuple

from ..models.hvac_elements import HVACSystem
from ..models.knowledge_model import KnowledgeModel


@dataclass
class DrawingConfig:
    """Visual settings for an exported SVG."""

    padding: float = 30.0
    room_fill: str = "#f8fafc"
    room_stroke: str = "#475569"
    radiator_color: str = "#dc2626"
    ac_color: str = "#0284c7"
    supply_color: str = "#ef4444"
    return_color: str = "#2563eb"
    boiler_color: str = "#f59e0b"
    document_status: str = "BOZZA_DIAGNOSTICA"


class DrawingGenerator:
    """Render rooms and HVAC elements as a portable SVG document."""

    def __init__(self, config: DrawingConfig | None = None):
        self.config = config or DrawingConfig()

    @staticmethod
    def _points(points: Iterable[Tuple[float, float]]) -> str:
        return " ".join(f"{x:g},{y:g}" for x, y in points)

    @staticmethod
    def _extent(model: KnowledgeModel) -> Tuple[float, float, float, float]:
        points: List[Tuple[float, float]] = []
        for floor in model.floors:
            bounds = floor.bounds
            if bounds.get("width", 0) > 0 and bounds.get("height", 0) > 0:
                x, y = bounds.get("x", 0), bounds.get("y", 0)
                points.extend([(x, y), (x + bounds["width"], y + bounds["height"])])
            for room in floor.rooms:
                points.extend(room.polygon)
        if not points:
            return 0.0, 0.0, 800.0, 600.0
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return min(xs), min(ys), max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0)

    def build_svg(self, model: KnowledgeModel, system: HVACSystem) -> str:
        """Return a complete SVG string without writing a file."""
        x, y, width, height = self._extent(model)
        pad = self.config.padding
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x-pad:g} {y-pad:g} {width+2*pad:g} {height+2*pad:g}" role="img" aria-label="Plan2HVAC layout">',
            "<style>text{font-family:Arial,sans-serif}.label{font-size:12px;fill:#0f172a}.small{font-size:9px;fill:#334155}</style>",
            f'<text x="{x:g}" y="{y-10:g}" fill="#b91c1c" font-size="14" font-weight="bold">{escape(self.config.document_status)}</text>',
            '<g id="rooms">',
        ]
        for floor in model.floors:
            for room in floor.rooms:
                if room.polygon:
                    parts.append(
                        f'<polygon points="{self._points(room.polygon)}" fill="{self.config.room_fill}" stroke="{self.config.room_stroke}" stroke-width="1.5"/>'
                    )
                cx, cy = room.get_centroid()
                parts.append(f'<text class="label" x="{cx:g}" y="{cy:g}" text-anchor="middle">{escape(room.label)}</text>')
        parts.append("</g><g id=\"pipes\" fill=\"none\">")
        for pipe in system.pipes:
            color = self.config.return_color if "return" in pipe.pipe_type.value else self.config.supply_color
            dash = ' stroke-dasharray="6 4"' if "return" in pipe.pipe_type.value else ""
            for segment in pipe.segments:
                parts.append(
                    f'<line x1="{segment.start[0]:g}" y1="{segment.start[1]:g}" x2="{segment.end[0]:g}" y2="{segment.end[1]:g}" stroke="{color}" stroke-width="2"{dash}/>'
                )
        parts.append("</g><g id=\"equipment\">")
        for radiator in system.radiators:
            px, py = radiator.position
            parts.append(f'<rect x="{px-8:g}" y="{py-3:g}" width="16" height="6" rx="1" fill="{self.config.radiator_color}"/>')
            parts.append(f'<text class="small" x="{px:g}" y="{py-6:g}" text-anchor="middle">{radiator.power_watts:g} W</text>')
        for unit in system.ac_units:
            px, py = unit.position
            parts.append(f'<rect x="{px-9:g}" y="{py-4:g}" width="18" height="8" rx="2" fill="{self.config.ac_color}"/>')
            parts.append(f'<text class="small" x="{px:g}" y="{py-7:g}" text-anchor="middle">AC</text>')
        for boiler in system.boilers:
            px, py = boiler.position
            parts.append(f'<circle cx="{px:g}" cy="{py:g}" r="7" fill="{self.config.boiler_color}"/>')
            parts.append(f'<text class="small" x="{px:g}" y="{py-10:g}" text-anchor="middle">{escape(boiler.id)}</text>')
        parts.append("</g></svg>\n")
        return "\n".join(parts)

    def export_svg(self, model: KnowledgeModel, system: HVACSystem, filepath: str) -> str:
        """Write an SVG drawing, creating parent directories as needed."""
        svg = self.build_svg(model, system)
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        return svg
