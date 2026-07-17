from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any


LEGACY_ROOM_ALIASES: dict[str, str] = {
    "bagno": "bagno",
    "camera": "camera",
    "dis": "disimpegno",
    "disimpegno": "disimpegno",
    "soggiorno-pranzo": "soggiorno-pranzo",
    "soggiorno pranzo": "soggiorno-pranzo",
    "rip": "ripostiglio",
    "ripostiglio": "ripostiglio",
    "balcone": "balcone",
    "cucina": "cucina",
    "sala": "sala",
    "portico": "portico",
}
LEGACY_OBJECT_TERMS: tuple[str, ...] = ("armadio", "arredo fisso")


def config_value(config: Any, name: str, default: Any) -> Any:
    """Read flat or nested configuration without owning its model."""

    if config is None:
        return default
    current: Any = config
    for part in name.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return default
            current = current[part]
        else:
            if not hasattr(current, part):
                return default
            current = getattr(current, part)
    return current


def first_config_value(
    config: Any,
    names: tuple[str, ...],
    default: Any,
) -> Any:
    sentinel = object()
    for name in names:
        value = config_value(config, name, sentinel)
        if value is not sentinel:
            return value
    return default


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(
        character for character in value if not unicodedata.combining(character)
    )
    value = value.casefold().strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.;:|_")


def room_aliases(config: Any) -> dict[str, str]:
    configured = first_config_value(
        config,
        ("text.room_aliases", "room_aliases"),
        LEGACY_ROOM_ALIASES,
    )
    return {
        normalize_text(str(key)): str(value)
        for key, value in dict(configured).items()
    }


def object_terms(config: Any) -> tuple[str, ...]:
    configured = first_config_value(
        config,
        ("text.object_terms", "object_terms"),
        LEGACY_OBJECT_TERMS,
    )
    return tuple(normalize_text(str(value)) for value in configured)


def role_from_values(
    values: list[str],
    *,
    image_width: int,
    bbox: list[float],
    adapter_name: str,
    source_role: Mapping[str, Any] | None,
    config: Any,
) -> tuple[str, str | None, list[str], bool]:
    aliases = room_aliases(config)
    normalized = {normalize_text(value) for value in values}
    for value in sorted(normalized):
        if value in aliases:
            role_abstained = bool((source_role or {}).get("abstained", False))
            reason_prefix = (
                "lexical_room_anchor"
                if adapter_name == "ocr_ensemble_v1"
                else "lexical_space_anchor"
            )
            return (
                "space_name_seed",
                aliases[value],
                [f"{reason_prefix}:{value}"],
                role_abstained,
            )

    if adapter_name == "ocr_ensemble_v1":
        for value in sorted(normalized):
            if any(term in value for term in object_terms(config)):
                return (
                    "contained_object_label",
                    None,
                    [f"lexical_contained_object:{value}"],
                    False,
                )
        if float(bbox[2]) >= image_width - 2:
            return "border_context_unresolved", None, ["touches_region_border"], True
    elif "altra uiu" in normalized or {"altra", "uiu"} <= normalized:
        return (
            "external_context_label",
            None,
            ["lexical_adjacent_unit_context"],
            False,
        )

    return "unresolved_text", None, ["no_supported_role_mapping"], True


__all__ = [
    "first_config_value",
    "normalize_text",
    "role_from_values",
]
