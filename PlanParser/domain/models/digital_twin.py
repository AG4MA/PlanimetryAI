"""
Digital Twin Model
==================
The canonical output of PlanParser.

This is the "single source of truth" that downstream projects consume:
- Plan2HVAC: uses topology and room types for HVAC layout
- PlanNL: uses all data for natural language queries

Downstream projects should NEVER re-parse the original files.
They consume only this structured output.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import json

from PlanParser.domain.models.building import Building
from PlanParser.domain.value_objects.measurements import Scale
from PlanParser.domain.value_objects.orientation import Compass


@dataclass
class ProcessingMetadata:
    """Metadata about how the planimetry was processed."""
    parser_version: str = "0.3.0"
    processed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Source info
    source_file: str | None = None
    source_type: str | None = None  # "pdf", "dwg", "dxf", "image"
    source_pages: int = 1
    
    # Processing options used
    pdf_dpi: int = 300
    ocr_engine: str = "tesseract"
    ocr_languages: list[str] = field(default_factory=lambda: ["ita", "eng"])
    
    # Quality metrics
    processing_time_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "processed_at": self.processed_at,
            "source": {
                "file": self.source_file,
                "type": self.source_type,
                "pages": self.source_pages,
            },
            "options": {
                "pdf_dpi": self.pdf_dpi,
                "ocr_engine": self.ocr_engine,
                "ocr_languages": self.ocr_languages,
            },
            "metrics": {
                "processing_time_seconds": self.processing_time_seconds,
            },
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass
class DigitalTwin:
    """
    The complete digital representation of a planimetry.
    
    This is THE canonical output format of PlanParser.
    All downstream consumers (Plan2HVAC, PlanNL) depend on this schema.
    
    Contract guarantees:
    - Every room has an id, label, room_type
    - Every room has at least a bbox OR a polygon
    - Topology graph is always populated (even if empty)
    - Scale is always present (detected or default)
    - All measurements in meters (when scale is known)
    
    Usage:
        twin = parser.parse("floor_plan.pdf")
        
        # Save for downstream
        twin.save_json("output/plan_twin.json")
        
        # Consume in Plan2HVAC
        twin = DigitalTwin.load_json("output/plan_twin.json")
        for floor in twin.building.floors:
            for room in floor.rooms:
                if room.is_wet_room:
                    plan_drainage(room)
    """
    
    # Core content
    building: Building
    
    # Processing info
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)
    
    # Quick access summaries
    success: bool = True
    
    @property
    def floors(self):
        """Shortcut to building.floors."""
        return self.building.floors
    
    @property
    def all_rooms(self):
        """All rooms across all floors."""
        return self.building.get_all_rooms()
    
    @property
    def scale(self) -> Scale | None:
        """Building scale."""
        return self.building.scale
    
    @property
    def compass(self) -> Compass | None:
        """Building orientation."""
        return self.building.compass
    
    def get_room(self, room_id: str):
        """Find room by ID across all floors."""
        for floor in self.floors:
            room = floor.get_room_by_id(room_id)
            if room:
                return room
        return None
    
    def query_rooms(self, **filters):
        """
        Query rooms by attributes.
        
        Examples:
            twin.query_rooms(room_type=RoomType.BATHROOM)
            twin.query_rooms(is_wet_room=True)
            twin.query_rooms(floor_id="floor_0", is_habitable=True)
        """
        results = []
        for room in self.all_rooms:
            match = True
            for key, value in filters.items():
                if hasattr(room, key):
                    if getattr(room, key) != value:
                        match = False
                        break
                elif key in ("room_type",):
                    if room.room_type != value:
                        match = False
                        break
            if match:
                results.append(room)
        return results
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schema_version": "1.0",
            "success": self.success,
            "metadata": self.metadata.to_dict(),
            "building": self.building.to_dict(),
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save_json(self, path: str):
        """Save to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: dict) -> "DigitalTwin":
        """
        Deserialize from dictionary.
        
        Note: This creates a simplified version for downstream consumption.
        Full reconstruction requires more complex logic.
        """
        # This is a simplified loader - downstream projects use this
        # Full reconstruction would need to rebuild all objects
        raise NotImplementedError(
            "Full deserialization not yet implemented. "
            "Downstream projects should use the JSON directly or implement "
            "their own domain models."
        )
    
    @classmethod
    def load_json(cls, path: str) -> dict:
        """
        Load from JSON file.
        
        Returns the raw dict - downstream projects can use this directly
        or build their own domain objects from it.
        """
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Digital Twin: {self.building.name or 'Unnamed'}",
            f"  Source: {self.metadata.source_file}",
            f"  Scale: {self.scale.label if self.scale else 'Unknown'}",
            f"  Floors: {len(self.floors)}",
            f"  Total rooms: {len(self.all_rooms)}",
        ]
        
        for floor in self.floors:
            lines.append(f"\n  {floor.label}:")
            lines.append(f"    Rooms: {len(floor.rooms)}")
            if floor.total_area_sqm:
                lines.append(f"    Area: {floor.total_area_sqm:.1f} m²")
            
            room_types = {}
            for room in floor.rooms:
                t = room.room_type.value
                room_types[t] = room_types.get(t, 0) + 1
            
            if room_types:
                types_str = ", ".join(f"{k}: {v}" for k, v in sorted(room_types.items()))
                lines.append(f"    Types: {types_str}")
        
        if self.metadata.warnings:
            lines.append(f"\n  Warnings: {len(self.metadata.warnings)}")
        if self.metadata.errors:
            lines.append(f"  Errors: {len(self.metadata.errors)}")
        
        return "\n".join(lines)
