from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..domain.decision_register import DecisionRegister, RegisterValidationError


def load_decision_register(path: Path) -> DecisionRegister:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegisterValidationError(f"Cannot read decision register: {path}") from exc
    if not isinstance(payload, Mapping):
        raise RegisterValidationError("Decision register root must be an object")
    return DecisionRegister.from_mapping(payload)
