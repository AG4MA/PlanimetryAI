"""Validation and leakage checks for Point 1 dataset releases."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from PlanParser.decomposition import (
    load_decomposition_schema,
    load_taxonomy,
    validate_decomposition,
)

DATASET_MANIFEST_VERSION = "1.0.0"


@dataclass(frozen=True)
class DatasetIssue:
    severity: str
    code: str
    path: str
    message: str


def _resource(name: str) -> Path:
    return Path(__file__).with_name(name)


def load_dataset_manifest_schema() -> dict[str, Any]:
    return json.loads(_resource("dataset_manifest.schema.json").read_text(encoding="utf-8"))


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def dataset_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the deterministic release fingerprint for a complete manifest."""
    return _canonical_sha256(manifest)


def _json_path(parts: Iterable[Any]) -> str:
    value = "/".join(str(part) for part in parts)
    return f"/{value}" if value else "/"


def _issue(code: str, path: str, message: str) -> DatasetIssue:
    return DatasetIssue("error", code, path, message)


def _safe_annotation_path(base_dir: Path, relative_path: str) -> Path | None:
    base = base_dir.resolve()
    candidate = (base / relative_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def validate_dataset_manifest(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path | None = None,
    verify_annotation_files: bool = False,
) -> list[DatasetIssue]:
    """Validate structure, rights, split isolation and optional annotation files."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("jsonschema is required; install root requirements.txt") from exc

    validator = Draft202012Validator(
        load_dataset_manifest_schema(), format_checker=FormatChecker()
    )
    issues = [
        DatasetIssue("error", "schema", _json_path(error.absolute_path), error.message)
        for error in sorted(
            validator.iter_errors(manifest), key=lambda item: list(item.absolute_path)
        )
    ]
    if issues:
        return issues

    expected_taxonomy_hash = _canonical_sha256(load_taxonomy())
    if manifest["taxonomy"]["name"] != "planimetry-atomic-taxonomy":
        issues.append(_issue(
            "taxonomy_name_mismatch", "/taxonomy/name",
            "Manifest must reference the bundled Point 1 taxonomy.",
        ))
    if manifest["taxonomy"]["version"] != "1.0.0":
        issues.append(_issue(
            "taxonomy_version_mismatch", "/taxonomy/version",
            "Manifest taxonomy version does not match the bundled taxonomy.",
        ))
    if manifest["taxonomy"]["sha256"] != expected_taxonomy_hash:
        issues.append(_issue(
            "taxonomy_hash_mismatch", "/taxonomy/sha256",
            "Manifest taxonomy hash does not match the bundled taxonomy.",
        ))

    expected_schema_hash = _canonical_sha256(load_decomposition_schema())
    if manifest["decomposition_schema"]["name"] != "atomic-decomposition":
        issues.append(_issue(
            "decomposition_schema_name_mismatch", "/decomposition_schema/name",
            "Manifest must reference the atomic decomposition schema.",
        ))
    if manifest["decomposition_schema"]["version"] != "1.0.0":
        issues.append(_issue(
            "decomposition_schema_version_mismatch", "/decomposition_schema/version",
            "Manifest decomposition schema version is unsupported.",
        ))
    if manifest["decomposition_schema"]["sha256"] != expected_schema_hash:
        issues.append(_issue(
            "decomposition_schema_hash_mismatch", "/decomposition_schema/sha256",
            "Manifest decomposition schema hash does not match the bundled schema.",
        ))

    assets = manifest["assets"]
    asset_by_id: dict[str, Mapping[str, Any]] = {}
    source_hash_owner: dict[str, tuple[str, str]] = {}
    leakage_group_split: dict[str, str] = {}
    split_counts = {"train": 0, "validation": 0, "test": 0}

    for index, asset in enumerate(assets):
        path = f"/assets/{index}"
        asset_id = asset["asset_id"]
        split = asset["split"]
        split_counts[split] += 1

        if asset_id in asset_by_id:
            issues.append(_issue(
                "duplicate_asset_id", f"{path}/asset_id",
                f"Asset id '{asset_id}' is duplicated.",
            ))
        else:
            asset_by_id[asset_id] = asset

        source_hash = asset["source"]["sha256"]
        previous_source = source_hash_owner.get(source_hash)
        if previous_source is not None:
            previous_id, previous_split = previous_source
            code = "source_leakage" if previous_split != split else "duplicate_source"
            issues.append(_issue(
                code, f"{path}/source/sha256",
                f"Source content is already used by '{previous_id}' in split '{previous_split}'.",
            ))
        else:
            source_hash_owner[source_hash] = (asset_id, split)

        group_id = asset["leakage_group_id"]
        previous_split = leakage_group_split.get(group_id)
        if previous_split is not None and previous_split != split:
            issues.append(_issue(
                "group_leakage", f"{path}/leakage_group_id",
                f"Leakage group '{group_id}' spans '{previous_split}' and '{split}'.",
            ))
        else:
            leakage_group_split[group_id] = split

        rights = asset["rights"]
        required_use = "training" if split == "train" else "evaluation"
        if not rights["authorization_verified"]:
            issues.append(_issue(
                "rights_not_verified", f"{path}/rights/authorization_verified",
                "Every included asset requires verified authorization.",
            ))
        if required_use not in rights["permitted_uses"]:
            issues.append(_issue(
                "use_not_permitted", f"{path}/rights/permitted_uses",
                f"Split '{split}' requires permission for '{required_use}'.",
            ))
        if rights["privacy_review_status"] == "rejected":
            issues.append(_issue(
                "privacy_rejected", f"{path}/rights/privacy_review_status",
                "An asset rejected by privacy review cannot be included.",
            ))

        annotation_status = asset["annotation"]["dataset_status"]
        if manifest["status"] == "frozen_benchmark":
            if rights["privacy_review_status"] not in {"not_required", "approved"}:
                issues.append(_issue(
                    "privacy_not_cleared", f"{path}/rights/privacy_review_status",
                    "A frozen benchmark may contain only privacy-cleared assets.",
                ))
            if annotation_status == "draft":
                issues.append(_issue(
                    "draft_annotation_in_frozen_release", f"{path}/annotation/dataset_status",
                    "A frozen benchmark cannot contain draft annotations.",
                ))
            if split in {"validation", "test"} and annotation_status != "frozen_ground_truth":
                issues.append(_issue(
                    "evaluation_ground_truth_not_frozen", f"{path}/annotation/dataset_status",
                    "Validation and test annotations must be frozen ground truth.",
                ))

        augmentation = asset["augmentation"]
        if augmentation["is_augmented"] and split != "train":
            issues.append(_issue(
                "augmented_evaluation_asset", f"{path}/augmentation/is_augmented",
                "Generated augmentations belong only in train; evaluation uses independent sources.",
            ))

    for index, asset in enumerate(assets):
        augmentation = asset["augmentation"]
        if not augmentation["is_augmented"]:
            continue
        parent_id = augmentation["parent_asset_id"]
        parent = asset_by_id.get(parent_id)
        path = f"/assets/{index}/augmentation/parent_asset_id"
        if parent is None:
            issues.append(_issue(
                "missing_augmentation_parent", path,
                f"Augmentation parent '{parent_id}' is not present in the release.",
            ))
            continue
        if parent["split"] != asset["split"]:
            issues.append(_issue(
                "augmentation_split_leakage", path,
                "Augmentation and parent must remain in the same split.",
            ))
        if parent["leakage_group_id"] != asset["leakage_group_id"]:
            issues.append(_issue(
                "augmentation_group_mismatch", path,
                "Augmentation and parent must share leakage_group_id.",
            ))

    if manifest["status"] == "frozen_benchmark":
        for split, count in split_counts.items():
            if count == 0:
                issues.append(_issue(
                    "missing_required_split", "/assets",
                    f"Frozen benchmark requires at least one '{split}' asset.",
                ))

    if not verify_annotation_files:
        return issues
    if base_dir is None:
        issues.append(_issue(
            "missing_base_dir", "/assets",
            "base_dir is required when verify_annotation_files=True.",
        ))
        return issues

    root = Path(base_dir)
    for index, asset in enumerate(assets):
        annotation = asset["annotation"]
        path = f"/assets/{index}/annotation"
        annotation_path = _safe_annotation_path(root, annotation["relative_path"])
        if annotation_path is None:
            issues.append(_issue(
                "annotation_path_escape", f"{path}/relative_path",
                "Annotation path must remain inside base_dir.",
            ))
            continue
        if not annotation_path.is_file():
            issues.append(_issue(
                "annotation_missing", f"{path}/relative_path",
                f"Annotation file '{annotation['relative_path']}' does not exist.",
            ))
            continue
        raw = annotation_path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != annotation["sha256"]:
            issues.append(_issue(
                "annotation_hash_mismatch", f"{path}/sha256",
                "Annotation file hash differs from the manifest.",
            ))
            continue
        try:
            decomposition = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(_issue(
                "annotation_invalid_json", f"{path}/relative_path", str(exc),
            ))
            continue
        for decomposition_issue in validate_decomposition(decomposition):
            issues.append(_issue(
                f"annotation_{decomposition_issue.code}",
                f"{path}{decomposition_issue.path}",
                decomposition_issue.message,
            ))
        if decomposition.get("source", {}).get("sha256") != asset["source"]["sha256"]:
            issues.append(_issue(
                "annotation_source_mismatch", f"{path}/relative_path",
                "Annotation source hash does not match the registered source.",
            ))
        if decomposition.get("source", {}).get("page_count") != asset["source"]["page_count"]:
            issues.append(_issue(
                "annotation_page_count_mismatch", f"{path}/relative_path",
                "Annotation page count does not match the registered source.",
            ))
        if annotation["dataset_status"] != decomposition.get("dataset_status"):
            issues.append(_issue(
                "annotation_status_mismatch", f"{path}/dataset_status",
                "Manifest and annotation dataset statuses differ.",
            ))
    return issues


def assert_valid_dataset_manifest(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path | None = None,
    verify_annotation_files: bool = False,
) -> None:
    issues = validate_dataset_manifest(
        manifest,
        base_dir=base_dir,
        verify_annotation_files=verify_annotation_files,
    )
    if issues:
        detail = "; ".join(
            f"{issue.code} at {issue.path}: {issue.message}" for issue in issues
        )
        raise ValueError(f"Invalid dataset manifest: {detail}")
