"""
Loading & light structural checks for decomposition documents.

The benchmark consumes the PUBLISHED contract (decomposition.schema.json). Full
JSON-Schema validation is the decomposer's own concern
(PlanParser/decomposition/validator.py); here we only need robust, defensive
access to observations/relationships, so a missing optional field never crashes
the evaluator. Prediction and ground-truth documents share the same schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass
class Observation:
    id: str
    layer: str
    class_id: str
    geometry: Dict
    confidence_score: float
    abstained: bool
    page_id: str
    attributes: Dict = field(default_factory=dict)

    @property
    def text(self) -> Optional[str]:
        # OCR text is carried in attributes; accept a few common keys.
        for k in ("text", "value", "content", "transcription"):
            if k in self.attributes and self.attributes[k] is not None:
                return str(self.attributes[k])
        return None


@dataclass
class Relationship:
    id: str
    type: str
    from_id: str
    to_id: str
    confidence: float
    page_id: str


@dataclass
class Decomposition:
    document_id: str
    dataset_status: str
    observations: List[Observation] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    raw: Dict = field(default_factory=dict)

    @property
    def observation_ids(self) -> set:
        return {o.id for o in self.observations}

    def by_class(self) -> Dict[str, List[Observation]]:
        out: Dict[str, List[Observation]] = {}
        for o in self.observations:
            out.setdefault(o.class_id, []).append(o)
        return out

    def observations_on(self, page_id: str) -> List[Observation]:
        return [o for o in self.observations if o.page_id == page_id]


def from_dict(data: Dict) -> Decomposition:
    if not isinstance(data, dict):
        raise ValueError("decomposition root must be a JSON object")
    observations: List[Observation] = []
    relationships: List[Relationship] = []
    for page in data.get("pages", []) or []:
        pid = str(page.get("id", ""))
        for o in page.get("observations", []) or []:
            conf = o.get("confidence", {}) or {}
            observations.append(Observation(
                id=str(o.get("id", "")),
                layer=str(o.get("layer", "")),
                class_id=str(o.get("class_id", "")),
                geometry=o.get("geometry", {}) or {},
                confidence_score=float(conf.get("score", 0.0)),
                abstained=bool(conf.get("abstained", False)),
                page_id=pid,
                attributes=o.get("attributes", {}) or {},
            ))
        for rel in page.get("relationships", []) or []:
            relationships.append(Relationship(
                id=str(rel.get("id", "")),
                type=str(rel.get("type", "")),
                from_id=str(rel.get("from_id", "")),
                to_id=str(rel.get("to_id", "")),
                confidence=float(rel.get("confidence", 0.0)),
                page_id=pid,
            ))
    return Decomposition(
        document_id=str(data.get("document_id", "")),
        dataset_status=str(data.get("dataset_status", "")),
        observations=observations,
        relationships=relationships,
        raw=data,
    )


def load(path: str) -> Decomposition:
    with open(path, "r", encoding="utf-8") as f:
        return from_dict(json.load(f))


def orphan_relationship_refs(decomp: Decomposition) -> List[str]:
    """Relationship endpoints that don't point to an existing observation id."""
    ids = decomp.observation_ids
    orphans: List[str] = []
    for r in decomp.relationships:
        if r.from_id not in ids:
            orphans.append(f"{r.id}:from={r.from_id}")
        if r.to_id not in ids:
            orphans.append(f"{r.id}:to={r.to_id}")
    return orphans
