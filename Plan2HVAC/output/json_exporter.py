"""JSON output generation for complete HVAC designs."""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from ..core.thermal_calculator import ThermalRequirements
from ..models.hvac_elements import HVACSystem
from ..models.knowledge_model import KnowledgeModel


class JSONExporter:
    """Build and persist a stable, human-readable Plan2HVAC result document."""

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return JSONExporter._json_value(asdict(value))
        if isinstance(value, Mapping):
            return {str(key): JSONExporter._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [JSONExporter._json_value(item) for item in value]
        return value

    def build_document(
        self,
        hvac_system: HVACSystem,
        knowledge_model: KnowledgeModel,
        requirements: Mapping[str, ThermalRequirements],
        climate_zone: str = "E",
        document_status: str = "BOZZA_DIAGNOSTICA",
    ) -> Dict[str, Any]:
        """Return the serializable document without touching the filesystem."""
        thermal = {
            str(room_id): self._json_value(requirement)
            for room_id, requirement in requirements.items()
        }
        system = self._json_value(hvac_system.to_dict())
        return {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generator": "Plan2HVAC",
                "climate_zone": climate_zone,
                "source_file": knowledge_model.source_file,
                "scale": knowledge_model.scale,
                "document_status": document_status,
            },
            "thermal_requirements": thermal,
            "hvac_system": system,
            "summary": system["totals"],
        }

    def export_to_file(
        self,
        hvac_system: HVACSystem,
        knowledge_model: KnowledgeModel,
        requirements: Mapping[str, ThermalRequirements],
        filepath: str,
        climate_zone: str = "E",
        document_status: str = "BOZZA_DIAGNOSTICA",
    ) -> Dict[str, Any]:
        """Write a UTF-8 JSON result, creating parent directories as needed."""
        document = self.build_document(
            hvac_system,
            knowledge_model,
            requirements,
            climate_zone,
            document_status,
        )
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return document
