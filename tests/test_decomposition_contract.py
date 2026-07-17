import copy
import hashlib
import json
import unittest

from PlanParser.decomposition import load_taxonomy, validate_decomposition


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def valid_decomposition():
    taxonomy_bytes = json.dumps(
        load_taxonomy(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    provenance = {
        "method": "model",
        "producer": "wall-detector",
        "producer_version": "0.1.0",
        "created_at": "2026-07-17T10:00:00+00:00",
        "derived_from": [],
    }
    return {
        "schema_version": "1.0.0",
        "document_id": "doc-001",
        "source": {
            "filename": "sample.pdf",
            "media_type": "application/pdf",
            "sha256": _sha(b"sample"),
            "page_count": 1,
            "license_id": "internal-test",
            "provenance_id": "fixture",
        },
        "taxonomy": {
            "name": "planimetry-atomic-taxonomy",
            "version": "1.0.0",
            "sha256": _sha(taxonomy_bytes),
        },
        "run": {
            "producer": "PlanParser",
            "producer_version": "0.1.0",
            "created_at": "2026-07-17T10:00:00+00:00",
            "config_sha256": _sha(b"config"),
            "model_versions": {"wall_detector": "0.1.0"},
        },
        "dataset_status": "draft",
        "pages": [{
            "id": "page-0",
            "page_index": 0,
            "width_px": 1000,
            "height_px": 800,
            "render_dpi": 300,
            "rotation_deg": 0,
            "observations": [{
                "id": "obs-wall-1",
                "layer": "architectural_candidate",
                "class_id": "wall_axis",
                "geometry": {"type": "polyline", "points": [[10, 20], [500, 20]]},
                "evidence": {"page_id": "page-0", "crop_bbox_px": [10, 15, 490, 10], "source_object_refs": []},
                "confidence": {"score": 0.94, "calibration_version": "cal-1", "abstained": False, "reasons": []},
                "provenance": provenance,
                "reviews": [],
                "attributes": {"observed_thickness_px": 8},
            }],
            "relationships": [],
        }],
        "warnings": [],
    }


class DecompositionContractTests(unittest.TestCase):
    def test_valid_fixture_has_no_issues(self):
        self.assertEqual(validate_decomposition(valid_decomposition()), [])

    def test_taxonomy_layer_mismatch_is_rejected(self):
        document = valid_decomposition()
        document["pages"][0]["observations"][0]["class_id"] = "north_arrow"
        issues = validate_decomposition(document)
        self.assertIn("unknown_class", {issue.code for issue in issues})

    def test_geometry_outside_page_is_rejected(self):
        document = valid_decomposition()
        document["pages"][0]["observations"][0]["geometry"]["points"][1] = [1200, 20]
        issues = validate_decomposition(document)
        self.assertIn("geometry_out_of_bounds", {issue.code for issue in issues})

    def test_orphan_relationship_is_rejected(self):
        document = valid_decomposition()
        relation = {
            "id": "rel-1",
            "type": "candidate_part_of",
            "from_id": "obs-wall-1",
            "to_id": "missing-room",
            "confidence": 0.8,
            "provenance": {
                "method": "derived",
                "producer": "relation-builder",
                "producer_version": "0.1.0",
                "created_at": "2026-07-17T10:00:00+00:00",
                "derived_from": ["obs-wall-1"],
            },
            "reviews": [],
        }
        document["pages"][0]["relationships"].append(relation)
        issues = validate_decomposition(document)
        self.assertIn("orphan_reference", {issue.code for issue in issues})

    def test_page_count_mismatch_is_rejected(self):
        document = copy.deepcopy(valid_decomposition())
        document["source"]["page_count"] = 2
        issues = validate_decomposition(document)
        self.assertIn("page_count_mismatch", {issue.code for issue in issues})

    def test_taxonomy_digest_must_match_bundled_taxonomy(self):
        document = valid_decomposition()
        document["taxonomy"]["sha256"] = "0" * 64
        issues = validate_decomposition(document)
        self.assertIn("taxonomy_hash_mismatch", {issue.code for issue in issues})

    def test_frozen_ground_truth_requires_senior_review(self):
        document = valid_decomposition()
        document["dataset_status"] = "frozen_ground_truth"
        issues = validate_decomposition(document)
        self.assertIn("missing_ground_truth_review", {issue.code for issue in issues})

        observation = document["pages"][0]["observations"][0]
        observation["reviews"].append({
            "reviewer_id": "reviewer-1",
            "reviewer_role": "senior_reviewer",
            "decision": "accepted",
            "created_at": "2026-07-17T11:00:00+00:00",
            "guideline_version": "1.0.0",
            "notes": None,
        })
        self.assertEqual(validate_decomposition(document), [])


if __name__ == "__main__":
    unittest.main()
