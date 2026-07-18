"""
Unit tests for the P1 benchmark. Standard-library unittest only.

    python -m unittest discover -s PlanParser/benchmark/tests -v
"""
import copy
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PlanParser.benchmark import evaluate, load, evaluate_gate, load_config  # noqa: E402
from PlanParser.benchmark import geometry_metrics as gm  # noqa: E402
from PlanParser.benchmark import text_metrics as tm  # noqa: E402
from PlanParser.benchmark import calibration as cal  # noqa: E402

FIX = os.path.join(_HERE, "fixtures")
PRED = os.path.join(FIX, "pred.json")
GT = os.path.join(FIX, "gt.json")
THRESH = os.path.normpath(os.path.join(_HERE, "..", "thresholds.example.json"))


class TestGeometry(unittest.TestCase):
    def test_bbox_iou_identical(self):
        self.assertAlmostEqual(gm.bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)

    def test_bbox_iou_half(self):
        # [0,0,10,10] vs [5,0,10,10] -> inter 50, union 150 -> 1/3
        self.assertAlmostEqual(gm.bbox_iou([0, 0, 10, 10], [5, 0, 10, 10]), 1 / 3, places=6)

    def test_polygon_iou_identical(self):
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        self.assertGreater(gm.polygon_iou(sq, sq), 0.98)

    def test_polygon_iou_disjoint(self):
        a = [(0, 0), (10, 0), (10, 10), (0, 10)]
        b = [(100, 100), (110, 100), (110, 110), (100, 110)]
        self.assertEqual(gm.polygon_iou(a, b), 0.0)

    def test_polygon_iou_half_overlap(self):
        a = [(0, 0), (100, 0), (100, 100), (0, 100)]
        b = [(50, 0), (150, 0), (150, 100), (50, 100)]
        self.assertAlmostEqual(gm.polygon_iou(a, b), 1 / 3, delta=0.03)

    def test_polygon_area(self):
        self.assertAlmostEqual(gm.polygon_area([(0, 0), (100, 0), (100, 50), (0, 50)]), 5000.0)

    def test_point_in_polygon(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(gm.point_in_polygon(5, 5, sq))
        self.assertFalse(gm.point_in_polygon(15, 5, sq))


class TestText(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(tm.levenshtein("kitten", "sitting"), 3)

    def test_cer(self):
        self.assertAlmostEqual(tm.cer("Cucina", "Cucna"), 1 / 6, places=6)

    def test_cer_perfect(self):
        self.assertEqual(tm.cer("Bagno", "Bagno"), 0.0)

    def test_wer(self):
        self.assertAlmostEqual(tm.wer("camera da letto", "camera letto"), 1 / 3, places=6)


class TestCalibration(unittest.TestCase):
    def test_brier_perfect(self):
        s = [cal.ConfidenceSample(1.0, True), cal.ConfidenceSample(0.0, False)]
        self.assertAlmostEqual(cal.brier_score(s), 0.0)

    def test_ece_perfect(self):
        s = [cal.ConfidenceSample(1.0, True), cal.ConfidenceSample(1.0, True)]
        self.assertAlmostEqual(cal.expected_calibration_error(s), 0.0)

    def test_abstention(self):
        s = [
            cal.ConfidenceSample(0.2, correct=False, abstained=True, should_abstain=True),
            cal.ConfidenceSample(0.9, correct=True, abstained=False, should_abstain=False),
        ]
        m = cal.abstention_metrics(s)
        self.assertEqual(m["abstention_precision"], 1.0)
        self.assertEqual(m["abstention_recall"], 1.0)


class TestEvaluatorOnFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate(load(PRED), load(GT))

    def test_micro_counts(self):
        micro = self.report["detection"]["micro"]
        self.assertEqual((micro["tp"], micro["fp"], micro["fn"]), (6, 1, 1))

    def test_room_region_f1(self):
        # tp=2 fp=1 fn=0 -> P=2/3 R=1 F1=0.8
        prf = self.report["detection"]["per_class"]["room_region"]
        self.assertAlmostEqual(prf["f1"], 0.8, places=6)

    def test_window_missed(self):
        prf = self.report["detection"]["per_class"]["window"]
        self.assertEqual(prf["recall"], 0.0)
        self.assertEqual(prf["fn"], 1)

    def test_abstained_not_a_false_positive(self):
        # unknown_geometry (abstained) must NOT appear as a detection class
        self.assertNotIn("unknown_geometry", self.report["detection"]["per_class"])

    def test_geometry_iou_high(self):
        self.assertGreater(self.report["geometry"]["room_region"]["iou"], 0.9)

    def test_ocr(self):
        self.assertAlmostEqual(self.report["ocr"]["cer"], 1 / 6, places=6)
        self.assertEqual(self.report["ocr"]["n_pairs"], 1)

    def test_measurements(self):
        self.assertAlmostEqual(self.report["measurements"]["mean_value_error_ratio"], 0.05, places=6)

    def test_relationships(self):
        rel = self.report["relationships"]
        self.assertAlmostEqual(rel["f1"], 1.0)
        self.assertEqual(len(rel["orphan_refs_pred"]), 0)

    def test_abstention_in_report(self):
        cal_block = self.report["calibration"]
        self.assertEqual(cal_block["abstention_precision"], 1.0)
        self.assertAlmostEqual(cal_block["abstention_recall"], 0.5, places=6)


class TestGate(unittest.TestCase):
    def setUp(self):
        self.report = evaluate(load(PRED), load(GT))

    def test_default_thresholds_hold(self):
        # thresholds.example.json leaves everything DA CONCORDARE except orphans==0
        verdict = evaluate_gate(self.report, load_config(THRESH))
        self.assertEqual(verdict["verdict"], "HOLD")
        orphan = next(c for c in verdict["criteria"] if c["id"] == "P1-09-zero-orphans")
        self.assertEqual(orphan["status"], "PASS")

    def test_all_resolved_pass_gives_go(self):
        cfg = {"gate": "GATE_1", "criteria": [
            {"id": "orphans", "metric": "relationships.orphan_refs_pred.__len__", "op": "==", "threshold": 0},
            {"id": "room-f1", "metric": "detection.per_class.room_region.f1", "op": ">=", "threshold": 0.5},
            {"id": "ocr", "metric": "ocr.cer", "op": "<=", "threshold": 0.5},
        ]}
        self.assertEqual(evaluate_gate(self.report, cfg)["verdict"], "GO")

    def test_failing_threshold_gives_fail(self):
        cfg = {"gate": "GATE_1", "criteria": [
            {"id": "room-f1", "metric": "detection.per_class.room_region.f1", "op": ">=", "threshold": 0.99},
        ]}
        self.assertEqual(evaluate_gate(self.report, cfg)["verdict"], "FAIL")

    def test_missing_metric_is_no_data_not_pass(self):
        cfg = {"gate": "GATE_1", "criteria": [
            {"id": "ghost", "metric": "detection.per_class.nonexistent.f1", "op": ">=", "threshold": 0.5},
        ]}
        v = evaluate_gate(self.report, cfg)
        self.assertEqual(v["verdict"], "HOLD")
        self.assertEqual(v["criteria"][0]["status"], "NO_DATA")


class TestPerfectPrediction(unittest.TestCase):
    def test_gt_vs_itself_is_perfect(self):
        gt = load(GT)
        gt2 = load(GT)
        report = evaluate(gt, gt2)
        micro = report["detection"]["micro"]
        self.assertEqual(micro["fp"], 0)
        self.assertEqual(micro["fn"], 0)
        self.assertAlmostEqual(micro["f1"], 1.0)
        self.assertAlmostEqual(report["ocr"]["cer"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
