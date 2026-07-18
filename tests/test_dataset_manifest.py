import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PlanParser.dataset import (
    dataset_manifest_sha256,
    validate_dataset_manifest,
)
from PlanParser.decomposition import load_decomposition_schema, load_taxonomy
from tests.test_decomposition_contract import valid_decomposition


def _canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _asset(asset_id, split, source_byte, annotation_path):
    source_hash = hashlib.sha256(source_byte).hexdigest()
    return {
        "asset_id": asset_id,
        "source": {
            "filename": f"{asset_id}.pdf",
            "media_type": "application/pdf",
            "sha256": source_hash,
            "page_count": 1,
            "provenance_id": f"provenance-{asset_id}",
        },
        "rights": {
            "license_id": "internal-authorized",
            "permitted_uses": ["labeling", "training", "evaluation"],
            "authorization_verified": True,
            "privacy_review_status": "approved",
        },
        "split": split,
        "leakage_group_id": f"group-{asset_id}",
        "annotation": {
            "relative_path": annotation_path,
            "sha256": "0" * 64,
            "dataset_status": "reviewed" if split == "train" else "frozen_ground_truth",
        },
        "augmentation": {
            "is_augmented": False,
            "parent_asset_id": None,
            "recipe_id": None,
        },
        "strata": {
            "document_type": "architectural_plan",
            "capture_type": "vector_pdf",
            "source_quality": "high",
            "locale": "it-IT",
        },
    }


def valid_manifest():
    return {
        "schema_version": "1.0.0",
        "dataset_id": "p1-fixture",
        "release_version": "1.0.0",
        "created_at": "2026-07-17T10:00:00+00:00",
        "status": "frozen_benchmark",
        "taxonomy": {
            "name": "planimetry-atomic-taxonomy",
            "version": "1.0.0",
            "sha256": _canonical_hash(load_taxonomy()),
        },
        "decomposition_schema": {
            "name": "atomic-decomposition",
            "version": "1.0.0",
            "sha256": _canonical_hash(load_decomposition_schema()),
        },
        "split_policy": {
            "strategy": "grouped_deterministic",
            "seed": 1729,
            "group_key": "leakage_group_id",
            "frozen_splits": ["validation", "test"],
        },
        "assets": [
            _asset("train-1", "train", b"train", "annotations/train-1.json"),
            _asset("validation-1", "validation", b"validation", "annotations/validation-1.json"),
            _asset("test-1", "test", b"test", "annotations/test-1.json"),
        ],
        "notes": None,
    }


class DatasetManifestTests(unittest.TestCase):
    def test_valid_frozen_manifest(self):
        self.assertEqual(validate_dataset_manifest(valid_manifest()), [])

    def test_fingerprint_is_independent_of_key_order(self):
        manifest = valid_manifest()
        reordered = dict(reversed(list(manifest.items())))
        self.assertEqual(
            dataset_manifest_sha256(manifest), dataset_manifest_sha256(reordered)
        )

    def test_same_group_cannot_span_splits(self):
        manifest = valid_manifest()
        manifest["assets"][2]["leakage_group_id"] = manifest["assets"][0]["leakage_group_id"]
        codes = {issue.code for issue in validate_dataset_manifest(manifest)}
        self.assertIn("group_leakage", codes)

    def test_duplicate_source_is_rejected(self):
        manifest = valid_manifest()
        manifest["assets"][2]["source"]["sha256"] = manifest["assets"][0]["source"]["sha256"]
        codes = {issue.code for issue in validate_dataset_manifest(manifest)}
        self.assertIn("source_leakage", codes)

    def test_evaluation_assets_must_have_frozen_ground_truth(self):
        manifest = valid_manifest()
        manifest["assets"][2]["annotation"]["dataset_status"] = "reviewed"
        codes = {issue.code for issue in validate_dataset_manifest(manifest)}
        self.assertIn("evaluation_ground_truth_not_frozen", codes)

    def test_augmentation_must_stay_in_train_and_parent_group(self):
        manifest = valid_manifest()
        asset = manifest["assets"][2]
        asset["augmentation"] = {
            "is_augmented": True,
            "parent_asset_id": "train-1",
            "recipe_id": "rotate-1",
        }
        codes = {issue.code for issue in validate_dataset_manifest(manifest)}
        self.assertIn("augmented_evaluation_asset", codes)
        self.assertIn("augmentation_split_leakage", codes)
        self.assertIn("augmentation_group_mismatch", codes)

    def test_permissions_follow_split_use(self):
        manifest = valid_manifest()
        manifest["assets"][0]["rights"]["permitted_uses"] = ["labeling"]
        codes = {issue.code for issue in validate_dataset_manifest(manifest)}
        self.assertIn("use_not_permitted", codes)

    def test_file_verification_checks_hash_contract_and_source(self):
        manifest = valid_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            annotations = root / "annotations"
            annotations.mkdir()
            for asset in manifest["assets"]:
                decomposition = valid_decomposition()
                decomposition["source"]["filename"] = asset["source"]["filename"]
                decomposition["source"]["sha256"] = asset["source"]["sha256"]
                decomposition["dataset_status"] = asset["annotation"]["dataset_status"]
                if decomposition["dataset_status"] == "frozen_ground_truth":
                    decomposition["pages"][0]["observations"][0]["reviews"].append({
                        "reviewer_id": "senior-1",
                        "reviewer_role": "senior_reviewer",
                        "decision": "accepted",
                        "created_at": "2026-07-17T11:00:00+00:00",
                        "guideline_version": "1.0.0",
                        "notes": None,
                    })
                output = root / asset["annotation"]["relative_path"]
                raw = json.dumps(decomposition, sort_keys=True).encode("utf-8")
                output.write_bytes(raw)
                asset["annotation"]["sha256"] = hashlib.sha256(raw).hexdigest()

            self.assertEqual(
                validate_dataset_manifest(
                    manifest, base_dir=root, verify_annotation_files=True
                ),
                [],
            )

            manifest["assets"][2]["annotation"]["sha256"] = "f" * 64
            codes = {
                issue.code
                for issue in validate_dataset_manifest(
                    manifest, base_dir=root, verify_annotation_files=True
                )
            }
            self.assertIn("annotation_hash_mismatch", codes)

    def test_manifest_input_is_not_mutated(self):
        manifest = valid_manifest()
        original = copy.deepcopy(manifest)
        validate_dataset_manifest(manifest)
        self.assertEqual(manifest, original)


if __name__ == "__main__":
    unittest.main()
