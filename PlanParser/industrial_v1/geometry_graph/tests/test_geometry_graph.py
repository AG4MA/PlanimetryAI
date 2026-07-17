from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "geometry_graph.py"
SPEC = importlib.util.spec_from_file_location("industrial_geometry_graph", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Point = MODULE.Point
Segment = MODULE.Segment
analyze_segments = MODULE.analyze_segments


def segment(identifier: str, points: tuple[tuple[float, float], tuple[float, float]]) -> Segment:
    start, end = points
    return Segment(
        id=identifier,
        start=Point(*start),
        end=Point(*end),
        confidence=1.0,
        raw={"id": identifier, "points_px": [list(start), list(end)], "confidence": 1.0},
    )


class GeometryGraphSyntheticTests(unittest.TestCase):
    def analyze(self, items: list[Segment]):
        return analyze_segments(
            items,
            near_tolerance_px=8.0,
            endpoint_tolerance_px=0.5,
            parallel_angle_tolerance_deg=2.0,
        )

    def test_x_crossing(self):
        result = self.analyze(
            [segment("a", ((0, 0), (10, 10))), segment("b", ((0, 10), (10, 0)))]
        )
        relation = result["junction_relations"][0]
        self.assertEqual(relation["kind"], "exact_intersection")
        self.assertEqual(relation["geometric_class"], "crossing")
        self.assertEqual(relation["coordinate_crop_px"], [5.0, 5.0])
        self.assertTrue(relation["continuity"]["a"]["continuous_through_node"])
        self.assertTrue(relation["continuity"]["b"]["continuous_through_node"])

    def test_t_endpoint_to_interior(self):
        result = self.analyze(
            [segment("bar", ((0, 5), (10, 5))), segment("stem", ((5, 0), (5, 5)))]
        )
        relation = result["junction_relations"][0]
        self.assertEqual(relation["geometric_class"], "endpoint_to_interior")
        self.assertTrue(relation["continuity"]["bar"]["continuous_through_node"])
        self.assertFalse(relation["continuity"]["stem"]["continuous_through_node"])

    def test_l_endpoint_to_endpoint(self):
        result = self.analyze(
            [segment("horizontal", ((0, 0), (5, 0))), segment("vertical", ((5, 0), (5, 5)))]
        )
        relation = result["junction_relations"][0]
        self.assertEqual(relation["geometric_class"], "endpoint_to_endpoint")
        self.assertEqual(relation["separation_px"], 0.0)

    def test_parallel_distance(self):
        result = self.analyze(
            [segment("upper", ((0, 0), (10, 0))), segment("lower", ((0, 4), (10, 4)))]
        )
        self.assertEqual(len(result["parallel_relations"]), 1)
        relation = result["parallel_relations"][0]
        self.assertEqual(relation["angle_degrees"], 0.0)
        self.assertEqual(relation["minimum_distance_px"], 4.0)
        self.assertEqual(len(result["junction_relations"]), 0)

    def test_gap_becomes_near_junction_and_abstains(self):
        result = self.analyze(
            [segment("left", ((0, 0), (4, 0))), segment("right", ((7, 0), (12, 0)))]
        )
        relation = result["junction_relations"][0]
        self.assertEqual(relation["kind"], "near_junction")
        self.assertEqual(relation["geometric_class"], "endpoint_to_endpoint")
        self.assertEqual(relation["separation_px"], 3.0)
        self.assertTrue(relation["abstained"])
        self.assertEqual(len(result["parallel_relations"]), 1)

    def test_collinear_overlap_is_not_a_point_node(self):
        result = self.analyze(
            [segment("long", ((0, 0), (10, 0))), segment("short", ((3, 0), (7, 0)))]
        )
        self.assertEqual(len(result["overlap_relations"]), 1)
        self.assertEqual(result["overlap_relations"][0]["overlap_length_px"], 4.0)
        self.assertEqual(len(result["junction_relations"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
