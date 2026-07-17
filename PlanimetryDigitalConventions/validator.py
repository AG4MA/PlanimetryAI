"""Validation helpers for the canonical PlanimetryAI Knowledge Model."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

KNOWLEDGE_MODEL_VERSION = "1.0.0"
VALIDATOR_VERSION = "1.0.0"
DEFAULT_MIN_CONFIDENCE = 0.80


@dataclass(frozen=True)
class ValidationIssue:
    """A machine-readable validation problem."""

    severity: str
    code: str
    path: str
    message: str


def load_knowledge_model_schema() -> dict[str, Any]:
    """Load the bundled JSON Schema."""
    schema_path = Path(__file__).with_name("knowledge_model.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _path(parts: Iterable[Any]) -> str:
    rendered = "/".join(str(part) for part in parts)
    return f"/{rendered}" if rendered else "/"


def _schema_issues(document: Mapping[str, Any]) -> list[ValidationIssue]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - explicit environment failure
        raise RuntimeError(
            "jsonschema is required; install the root requirements.txt"
        ) from exc

    validator = Draft202012Validator(
        load_knowledge_model_schema(), format_checker=FormatChecker()
    )
    return [
        ValidationIssue("error", "schema", _path(error.absolute_path), error.message)
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    ]


def _construction_issues(
    document: Mapping[str, Any], min_confidence: float
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    meta = document.get("meta", {})
    if not meta.get("scale_factor_m_per_px"):
        issues.append(ValidationIssue(
            "error", "missing_metric_scale", "/meta/scale_factor_m_per_px",
            "A metric scale is mandatory before HVAC sizing or construction output.",
        ))
    if meta.get("orientation_north_deg") is None:
        issues.append(ValidationIssue(
            "error", "missing_orientation", "/meta/orientation_north_deg",
            "North orientation is mandatory for construction readiness.",
        ))

    floors = document.get("floors", [])
    if not floors:
        issues.append(ValidationIssue(
            "error", "no_floors", "/floors", "At least one floor is required."
        ))

    seen_room_ids: set[str] = set()
    for floor_index, floor in enumerate(floors):
        floor_path = f"/floors/{floor_index}"
        if float(floor.get("confidence", 0)) < min_confidence:
            issues.append(ValidationIssue(
                "error", "low_floor_confidence", f"{floor_path}/confidence",
                f"Floor confidence must be at least {min_confidence:.2f}.",
            ))
        rooms = floor.get("rooms", [])
        if not rooms:
            issues.append(ValidationIssue(
                "error", "no_rooms", f"{floor_path}/rooms",
                "Every construction-ready floor must contain detected rooms.",
            ))
        for room_index, room in enumerate(rooms):
            room_path = f"{floor_path}/rooms/{room_index}"
            room_id = str(room.get("id", ""))
            if room_id in seen_room_ids:
                issues.append(ValidationIssue(
                    "error", "duplicate_room_id", f"{room_path}/id",
                    f"Room id '{room_id}' is not unique across the building.",
                ))
            seen_room_ids.add(room_id)
            if not room.get("label"):
                issues.append(ValidationIssue(
                    "error", "missing_room_label", f"{room_path}/label",
                    "Room usage cannot be inferred without a label.",
                ))
            if float(room.get("confidence", 0)) < min_confidence:
                issues.append(ValidationIssue(
                    "error", "low_room_confidence", f"{room_path}/confidence",
                    f"Room confidence must be at least {min_confidence:.2f}.",
                ))
            if not room.get("area_m2"):
                issues.append(ValidationIssue(
                    "error", "missing_metric_area", f"{room_path}/area_m2",
                    "Metric room area is mandatory for load calculations.",
                ))
            walls = room.get("walls", [])
            if not walls:
                issues.append(ValidationIssue(
                    "error", "missing_walls", f"{room_path}/walls",
                    "Room walls are mandatory for construction readiness.",
                ))
            for wall_index, wall in enumerate(walls):
                wall_path = f"{room_path}/walls/{wall_index}"
                if wall.get("wall_type") == "unknown":
                    issues.append(ValidationIssue(
                        "error", "unknown_wall_type", f"{wall_path}/wall_type",
                        "Every wall must be classified before thermal calculation.",
                    ))
                if not wall.get("length_m"):
                    issues.append(ValidationIssue(
                        "error", "missing_wall_length", f"{wall_path}/length_m",
                        "Metric wall length is mandatory.",
                    ))
                if float(wall.get("confidence", 0)) < min_confidence:
                    issues.append(ValidationIssue(
                        "error", "low_wall_confidence", f"{wall_path}/confidence",
                        f"Wall confidence must be at least {min_confidence:.2f}.",
                    ))

    return issues


def validate_knowledge_model(
    document: Mapping[str, Any],
    *,
    construction_ready: bool = False,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[ValidationIssue]:
    """Validate structure and, optionally, construction-readiness invariants."""
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    issues = _schema_issues(document)
    if construction_ready and not issues:
        issues.extend(_construction_issues(document, min_confidence))
    return issues


def assert_valid_knowledge_model(
    document: Mapping[str, Any],
    *,
    construction_ready: bool = False,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> None:
    """Raise ValueError when validation produces one or more errors."""
    issues = validate_knowledge_model(
        document,
        construction_ready=construction_ready,
        min_confidence=min_confidence,
    )
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        details = "; ".join(
            f"{issue.code} at {issue.path}: {issue.message}" for issue in errors
        )
        raise ValueError(f"Invalid Knowledge Model: {details}")
