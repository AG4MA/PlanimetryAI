"""Structural and semantic validation for Point 1 decomposition documents."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

DECOMPOSITION_VERSION = "1.0.0"


@dataclass(frozen=True)
class DecompositionIssue:
    severity: str
    code: str
    path: str
    message: str


def _resource(name: str) -> Path:
    return Path(__file__).with_name(name)


def load_decomposition_schema() -> dict[str, Any]:
    return json.loads(_resource("decomposition.schema.json").read_text(encoding="utf-8"))


def load_taxonomy() -> dict[str, Any]:
    return json.loads(_resource("taxonomy.v1.json").read_text(encoding="utf-8"))


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path(parts: Iterable[Any]) -> str:
    value = "/".join(str(part) for part in parts)
    return f"/{value}" if value else "/"


def _contains_point(geometry: Mapping[str, Any], width: float, height: float) -> bool:
    points = geometry.get("points", [])
    return all(0 <= point[0] <= width and 0 <= point[1] <= height for point in points)


def _contains_bbox(bbox: list[float], width: float, height: float) -> bool:
    x, y, box_width, box_height = bbox
    return x + box_width <= width and y + box_height <= height


def validate_decomposition(document: Mapping[str, Any]) -> list[DecompositionIssue]:
    """Return schema, taxonomy, reference and page-bound issues."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("jsonschema is required; install root requirements.txt") from exc

    issues: list[DecompositionIssue] = []
    schema_validator = Draft202012Validator(
        load_decomposition_schema(), format_checker=FormatChecker()
    )
    for error in sorted(
        schema_validator.iter_errors(document), key=lambda item: list(item.absolute_path)
    ):
        issues.append(DecompositionIssue(
            "error", "schema", _path(error.absolute_path), error.message
        ))
    if issues:
        return issues

    taxonomy = load_taxonomy()
    if document["taxonomy"]["sha256"] != _canonical_sha256(taxonomy):
        issues.append(DecompositionIssue(
            "error", "taxonomy_hash_mismatch", "/taxonomy/sha256",
            "Taxonomy hash does not match the bundled version.",
        ))
    taxonomy_layers = {
        layer: set(classes) for layer, classes in taxonomy["layers"].items()
    }
    relationship_types = set(taxonomy["relationship_types"])

    ids: set[str] = set()
    page_ids = {page["id"] for page in document["pages"]}
    for page_index, page in enumerate(document["pages"]):
        base = f"/pages/{page_index}"
        width, height = page["width_px"], page["height_px"]
        if page["id"] in ids:
            issues.append(DecompositionIssue(
                "error", "duplicate_id", f"{base}/id", f"Duplicate id '{page['id']}'."
            ))
        ids.add(page["id"])

        for observation_index, observation in enumerate(page["observations"]):
            obs_path = f"{base}/observations/{observation_index}"
            obs_id = observation["id"]
            if obs_id in ids:
                issues.append(DecompositionIssue(
                    "error", "duplicate_id", f"{obs_path}/id", f"Duplicate id '{obs_id}'."
                ))
            ids.add(obs_id)
            if observation["class_id"] not in taxonomy_layers[observation["layer"]]:
                issues.append(DecompositionIssue(
                    "error", "unknown_class", f"{obs_path}/class_id",
                    f"Class '{observation['class_id']}' is not valid for layer '{observation['layer']}'.",
                ))
            geometry = observation["geometry"]
            if geometry.get("points") and not _contains_point(geometry, width, height):
                issues.append(DecompositionIssue(
                    "error", "geometry_out_of_bounds", f"{obs_path}/geometry/points",
                    "Observation geometry lies outside its page.",
                ))
            if geometry.get("bbox") and not _contains_bbox(geometry["bbox"], width, height):
                issues.append(DecompositionIssue(
                    "error", "geometry_out_of_bounds", f"{obs_path}/geometry/bbox",
                    "Observation bounding box lies outside its page.",
                ))
            evidence = observation["evidence"]
            if evidence["page_id"] != page["id"]:
                issues.append(DecompositionIssue(
                    "error", "wrong_evidence_page", f"{obs_path}/evidence/page_id",
                    "Observation evidence must reference the containing page.",
                ))
            if not _contains_bbox(evidence["crop_bbox_px"], width, height):
                issues.append(DecompositionIssue(
                    "error", "evidence_out_of_bounds", f"{obs_path}/evidence/crop_bbox_px",
                    "Evidence crop lies outside its page.",
                ))
            if document["dataset_status"] == "frozen_ground_truth":
                accepted_human_review = any(
                    review["decision"] in {"accepted", "modified"}
                    and review["reviewer_role"] in {"senior_reviewer", "domain_professional"}
                    for review in observation["reviews"]
                )
                if not accepted_human_review:
                    issues.append(DecompositionIssue(
                        "error", "missing_ground_truth_review", f"{obs_path}/reviews",
                        "Frozen ground truth requires an accepted senior or professional review.",
                    ))

        for relation in page["relationships"]:
            relation_id = relation["id"]
            if relation_id in ids:
                issues.append(DecompositionIssue(
                    "error", "duplicate_id", f"{base}/relationships",
                    f"Duplicate id '{relation_id}'.",
                ))
            ids.add(relation_id)

    for page_index, page in enumerate(document["pages"]):
        for relation_index, relation in enumerate(page["relationships"]):
            rel_path = f"/pages/{page_index}/relationships/{relation_index}"
            if relation["type"] not in relationship_types:
                issues.append(DecompositionIssue(
                    "error", "unknown_relationship", f"{rel_path}/type",
                    f"Unknown relationship type '{relation['type']}'.",
                ))
            for key in ("from_id", "to_id"):
                if relation[key] not in ids:
                    issues.append(DecompositionIssue(
                        "error", "orphan_reference", f"{rel_path}/{key}",
                        f"Reference '{relation[key]}' does not exist.",
                    ))
            for derived_id in relation["provenance"]["derived_from"]:
                if derived_id not in ids:
                    issues.append(DecompositionIssue(
                        "error", "orphan_derivation", f"{rel_path}/provenance/derived_from",
                        f"Derived reference '{derived_id}' does not exist.",
                    ))
            if document["dataset_status"] == "frozen_ground_truth":
                accepted_human_review = any(
                    review["decision"] in {"accepted", "modified"}
                    and review["reviewer_role"] in {"senior_reviewer", "domain_professional"}
                    for review in relation["reviews"]
                )
                if not accepted_human_review:
                    issues.append(DecompositionIssue(
                        "error", "missing_ground_truth_review", f"{rel_path}/reviews",
                        "Frozen ground-truth relationships require accepted senior review.",
                    ))

        for observation_index, observation in enumerate(page["observations"]):
            for derived_id in observation["provenance"]["derived_from"]:
                if derived_id not in ids:
                    issues.append(DecompositionIssue(
                        "error", "orphan_derivation",
                        f"/pages/{page_index}/observations/{observation_index}/provenance/derived_from",
                        f"Derived reference '{derived_id}' does not exist.",
                    ))

    if len(page_ids) != len(document["pages"]):
        issues.append(DecompositionIssue(
            "error", "duplicate_page_id", "/pages", "Page ids must be unique."
        ))
    if document["source"]["page_count"] != len(document["pages"]):
        issues.append(DecompositionIssue(
            "error", "page_count_mismatch", "/source/page_count",
            "Source page_count must equal the number of page records.",
        ))
    return issues


def assert_valid_decomposition(document: Mapping[str, Any]) -> None:
    issues = validate_decomposition(document)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        detail = "; ".join(
            f"{issue.code} at {issue.path}: {issue.message}" for issue in errors
        )
        raise ValueError(f"Invalid decomposition: {detail}")
