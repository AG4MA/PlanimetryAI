"""
PlanNL — optional LLM fallback for free-form questions.

Disabled by default. The rule-based engine (``PlanNL.query``) is the primary,
fully-offline path. This module is only used when the CLI is invoked with
``--llm`` AND both an API key (``ANTHROPIC_API_KEY``) and the ``anthropic``
package are present. Even then, the model is instructed to answer *only* from the
structured Knowledge Model passed as context and to reply "dato non disponibile"
when the data is absent — it must never invent geometry.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .knowledge import Building

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "Sei l'interfaccia di interrogazione di PlanNL su una planimetria. "
    "Rispondi ESCLUSIVAMENTE usando i dati del Knowledge Model forniti in JSON. "
    "Non inventare aree, stanze, pareti o adiacenze. Se un dato non e presente, "
    "rispondi esattamente 'dato non disponibile' spiegando quale campo manca. "
    "Cita sempre gli id delle stanze da cui ricavi la risposta. Rispondi nella "
    "lingua della domanda."
)


class LLMUnavailable(RuntimeError):
    """Raised when the optional LLM path cannot be used."""


def _building_context(building: Building) -> str:
    payload = {
        "meta": {
            "source_file": building.source_file,
            "scale": building.scale,
            "scale_factor": building.scale_factor,
            "orientation_north": building.orientation_north,
        },
        "rooms": [
            {
                "id": r.id,
                "label": r.label,
                "category": r.category,
                "area_m2": r.area_m2,
                "area_px": r.area_px,
                "neighbors": r.neighbors,
            }
            for r in building.rooms
        ],
        "adjacency_available": bool(building.adjacency),
    }
    return json.dumps(payload, ensure_ascii=False)


def is_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def answer_with_llm(building: Building, question: str) -> str:
    """Answer a free-form question via Claude, grounded on the Knowledge Model."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailable("ANTHROPIC_API_KEY non impostata; usa la modalita rule-based (default).")
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("pacchetto 'anthropic' non installato (pip install anthropic).") from exc

    client = anthropic.Anthropic()
    context = _building_context(building)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Knowledge Model (JSON):\n{context}\n\nDomanda: {question}",
            }
        ],
    )
    parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
    return "\n".join(parts).strip() or "dato non disponibile"
