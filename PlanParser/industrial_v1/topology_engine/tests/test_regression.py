from __future__ import annotations

import unittest

from industrial_v1.topology_engine.regression import compare_with_baseline


class BaselineRegressionTests(unittest.TestCase):
    def test_additional_canonical_fields_do_not_break_frozen_projection(self) -> None:
        baseline = {
            "text_nodes": [{"id": "T1", "role": "seed"}],
            "geometry_barrier_audit": {"count": 1},
            "expansion_seed_audit": [],
            "space_candidates": [],
            "topology_edges": [],
            "summary": {"nodes": 1},
        }
        candidate = {
            **baseline,
            "text_nodes": [
                {"id": "T1", "role": "seed", "semantic_role_abstained": False}
            ],
            "engine_version": "1.0.0",
        }
        report = compare_with_baseline(baseline, candidate)
        self.assertTrue(report["match"])
        self.assertEqual(report["differences"], [])

    def test_changed_value_is_reported_with_path(self) -> None:
        baseline = {
            "text_nodes": [],
            "geometry_barrier_audit": {},
            "expansion_seed_audit": [],
            "space_candidates": [{"area": 10}],
            "topology_edges": [],
            "summary": {},
        }
        candidate = {
            **baseline,
            "space_candidates": [{"area": 11}],
        }
        report = compare_with_baseline(baseline, candidate)
        self.assertFalse(report["match"])
        self.assertEqual(report["differences"][0]["path"], "space_candidates[0].area")


if __name__ == "__main__":
    unittest.main()
