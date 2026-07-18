import copy
import hashlib
import json
import unittest

from PlanParser.decomposition import load_taxonomy, validate_decomposition
from PlanParser.evaluation import (
    EvaluationConfig,
    evaluate_decompositions,
    validate_evaluation_report,
)


def _canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review():
    return {
        "reviewer_id": "senior-1",
        "reviewer_role": "senior_reviewer",
        "decision": "accepted",
        "created_at": "2026-07-17T10:00:00+00:00",
        "guideline_version": "labeling-guidelines/1.0.0",
        "notes": None,
    }


def _provenance(method="human"):
    return {
        "method": method,
        "producer": "fixture",
        "producer_version": "1.0.0",
        "created_at": "2026-07-17T10:00:00+00:00",
        "derived_from": [],
    }


def _confidence(score=1.0, abstained=False):
    return {
        "score": score,
        "calibration_version": "fixture-calibration/1.0.0",
        "abstained": abstained,
        "reasons": ["fixture-abstention"] if abstained else [],
    }


def frozen_ground_truth():
    taxonomy = load_taxonomy()
    source_hash = hashlib.sha256(b"evaluation-source").hexdigest()
    observations = [
        {
            "id": "gt-line",
            "layer": "geometry",
            "class_id": "line_segment",
            "geometry": {"type": "polyline", "points": [[10, 20], [200, 20]]},
            "evidence": {
                "page_id": "gt-page",
                "crop_bbox_px": [8, 18, 194, 4],
                "source_object_refs": [],
            },
            "confidence": _confidence(),
            "provenance": _provenance(),
            "reviews": [_review()],
            "attributes": {},
        },
        {
            "id": "gt-text",
            "layer": "text",
            "class_id": "room_label",
            "geometry": {"type": "bbox", "bbox": [60, 60, 90, 24]},
            "evidence": {
                "page_id": "gt-page",
                "crop_bbox_px": [55, 55, 100, 34],
                "source_object_refs": [],
            },
            "confidence": _confidence(),
            "provenance": _provenance(),
            "reviews": [_review()],
            "attributes": {"transcription": "Soggiorno"},
        },
        {
            "id": "gt-room",
            "layer": "architectural_candidate",
            "class_id": "room_region",
            "geometry": {
                "type": "polygon",
                "points": [[40, 40], [240, 40], [240, 180], [40, 180]],
            },
            "evidence": {
                "page_id": "gt-page",
                "crop_bbox_px": [35, 35, 210, 150],
                "source_object_refs": [],
            },
            "confidence": _confidence(),
            "provenance": _provenance(),
            "reviews": [_review()],
            "attributes": {},
        },
    ]
    relation = {
        "id": "gt-labels-room",
        "type": "labels",
        "from_id": "gt-text",
        "to_id": "gt-room",
        "confidence": 1.0,
        "provenance": _provenance(),
        "reviews": [_review()],
    }
    return {
        "schema_version": "1.0.0",
        "document_id": "ground-truth-document",
        "source": {
            "filename": "fixture.pdf",
            "media_type": "application/pdf",
            "sha256": source_hash,
            "page_count": 1,
            "license_id": "fixture-license",
            "provenance_id": "fixture-provenance",
        },
        "taxonomy": {
            "name": "planimetry-atomic-taxonomy",
            "version": "1.0.0",
            "sha256": _canonical_hash(taxonomy),
        },
        "run": {
            "producer": "fixture-ground-truth",
            "producer_version": "1.0.0",
            "created_at": "2026-07-17T10:00:00+00:00",
            "config_sha256": hashlib.sha256(b"gt-config").hexdigest(),
            "model_versions": {},
        },
        "dataset_status": "frozen_ground_truth",
        "pages": [
            {
                "id": "gt-page",
                "page_index": 0,
                "width_px": 400,
                "height_px": 300,
                "render_dpi": 300,
                "rotation_deg": 0,
                "observations": observations,
                "relationships": [relation],
            }
        ],
        "warnings": [],
    }


def perfect_prediction():
    prediction = copy.deepcopy(frozen_ground_truth())
    prediction["document_id"] = "prediction-document"
    prediction["dataset_status"] = "draft"
    prediction["run"]["producer"] = "fixture-model"
    prediction["run"]["config_sha256"] = hashlib.sha256(b"prediction-config").hexdigest()
    page = prediction["pages"][0]
    page["id"] = "prediction-page"
    id_mapping = {
        "gt-line": "prediction-line",
        "gt-text": "prediction-text",
        "gt-room": "prediction-room",
    }
    for observation in page["observations"]:
        observation["id"] = id_mapping[observation["id"]]
        observation["evidence"]["page_id"] = page["id"]
        observation["provenance"] = _provenance("model")
        observation["confidence"] = _confidence(0.9)
        observation["reviews"] = []
    relation = page["relationships"][0]
    relation["id"] = "prediction-labels-room"
    relation["from_id"] = id_mapping[relation["from_id"]]
    relation["to_id"] = id_mapping[relation["to_id"]]
    relation["provenance"] = _provenance("derived")
    relation["reviews"] = []
    return prediction


class PointOneEvaluationTests(unittest.TestCase):
    def test_fixtures_satisfy_decomposition_contract(self):
        self.assertEqual(validate_decomposition(frozen_ground_truth()), [])
        self.assertEqual(validate_decomposition(perfect_prediction()), [])

    def test_perfect_prediction_matches_ids_through_geometry(self):
        report = evaluate_decompositions(perfect_prediction(), frozen_ground_truth())
        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["summary"]["observations"]["tp"], 3)
        self.assertEqual(report["summary"]["observations"]["fp"], 0)
        self.assertEqual(report["summary"]["observations"]["fn"], 0)
        self.assertEqual(report["summary"]["observations"]["f1"], 1.0)
        self.assertEqual(report["summary"]["relationships"]["overall"]["tp"], 1)
        self.assertEqual(report["summary"]["text"]["character_error_rate"], 0.0)
        self.assertEqual(validate_evaluation_report(report), [])

    def test_geometry_outside_matching_tolerance_is_fp_and_fn(self):
        prediction = perfect_prediction()
        room = prediction["pages"][0]["observations"][2]
        room["geometry"]["points"] = [
            [260, 40], [390, 40], [390, 180], [260, 180]
        ]
        report = evaluate_decompositions(prediction, frozen_ground_truth())
        room_stats = report["summary"]["by_class"]["room_region"]
        self.assertEqual((room_stats["tp"], room_stats["fp"], room_stats["fn"]), (0, 1, 1))

    def test_class_confusion_is_visible_separately(self):
        prediction = perfect_prediction()
        text = prediction["pages"][0]["observations"][1]
        text["class_id"] = "unknown_text"
        report = evaluate_decompositions(prediction, frozen_ground_truth())
        self.assertEqual(report["summary"]["by_class"]["room_label"]["fn"], 1)
        self.assertEqual(report["summary"]["by_class"]["unknown_text"]["fp"], 1)
        self.assertEqual(report["summary"]["confusion"]["room_label"]["unknown_text"], 1)

    def test_text_metrics_use_matched_transcriptions(self):
        prediction = perfect_prediction()
        prediction["pages"][0]["observations"][1]["attributes"]["transcription"] = "Sogiorno"
        report = evaluate_decompositions(prediction, frozen_ground_truth())
        text = report["summary"]["text"]
        self.assertEqual(text["character_edits"], 1)
        self.assertAlmostEqual(text["character_error_rate"], 1 / 9)
        self.assertEqual(text["word_error_rate"], 1.0)

    def test_abstention_reduces_coverage_and_does_not_become_true_positive(self):
        prediction = perfect_prediction()
        prediction["pages"][0]["observations"][2]["confidence"] = _confidence(
            0.2, abstained=True
        )
        report = evaluate_decompositions(prediction, frozen_ground_truth())
        calibration = report["summary"]["calibration"]
        self.assertEqual(calibration["prediction_count"], 3)
        self.assertEqual(calibration["covered_count"], 2)
        self.assertAlmostEqual(calibration["coverage"], 2 / 3)
        self.assertEqual(report["summary"]["by_class"]["room_region"]["fn"], 1)

    def test_source_mismatch_fails_closed_without_metrics(self):
        prediction = perfect_prediction()
        prediction["source"]["sha256"] = hashlib.sha256(b"other").hexdigest()
        report = evaluate_decompositions(prediction, frozen_ground_truth())
        self.assertEqual(report["status"], "invalid")
        self.assertIsNone(report["summary"])
        self.assertIn("source_hash_mismatch", {issue["code"] for issue in report["issues"]})
        self.assertEqual(validate_evaluation_report(report), [])

    def test_non_frozen_ground_truth_fails_closed_by_default(self):
        ground_truth = frozen_ground_truth()
        ground_truth["dataset_status"] = "reviewed"
        report = evaluate_decompositions(perfect_prediction(), ground_truth)
        self.assertEqual(report["status"], "invalid")
        self.assertIn(
            "ground_truth_not_frozen", {issue["code"] for issue in report["issues"]}
        )

    def test_matching_configuration_is_not_an_acceptance_threshold(self):
        config = EvaluationConfig(line_distance_threshold_fraction=0.004)
        prediction = perfect_prediction()
        prediction["pages"][0]["observations"][0]["geometry"]["points"] = [
            [10, 23], [200, 23]
        ]
        report = evaluate_decompositions(prediction, frozen_ground_truth(), config)
        self.assertEqual(report["summary"]["by_class"]["line_segment"]["tp"], 0)
        self.assertEqual(report["config"]["line_distance_threshold_fraction"], 0.004)

    def test_report_is_deterministic(self):
        first = evaluate_decompositions(perfect_prediction(), frozen_ground_truth())
        second = evaluate_decompositions(perfect_prediction(), frozen_ground_truth())
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
