"""
Unit tests for PlanNL. Standard-library unittest only (no pytest dependency),
matching the project's existing test style. Run from the repo root:

    python -m unittest discover -s PlanNL/tests -v
"""
import json
import os
import sys
import unittest

# Make the repo root importable so `import PlanNL` works when run from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PlanNL import load, answer, build_from_dict  # noqa: E402
from PlanNL.knowledge import polygon_area_px, categorize_label  # noqa: E402

FIXTURE = os.path.join(_HERE, "fixtures", "sample_km.json")
REAL_SAMPLE = os.path.normpath(
    os.path.join(_ROOT, "PlanParser", "testV1", "output", "knowledge_model.json")
)


class TestKnowledgeLoader(unittest.TestCase):
    def setUp(self):
        self.b = load(FIXTURE)

    def test_room_count(self):
        self.assertEqual(len(self.b.rooms), 4)

    def test_scale_converts_px_to_m2(self):
        # scale_factor = 0.02 m/px -> area_m2 = area_px * 0.0004
        cucina = self.b.room_by_id("1")
        self.assertIsNotNone(cucina.area_m2)
        self.assertAlmostEqual(cucina.area_m2, 12.0, places=2)

    def test_total_area(self):
        self.assertAlmostEqual(self.b.total_area_m2, 35.2, places=2)

    def test_shoelace_matches_declared_area(self):
        # Cucina polygon is 200x150 = 30000 px^2, equal to declared area_px.
        cucina = self.b.room_by_id("1")
        self.assertAlmostEqual(polygon_area_px(cucina.polygon), 30000.0, places=1)

    def test_categorization(self):
        self.assertEqual(categorize_label("Camera da letto"), "camera")
        self.assertEqual(categorize_label("WC"), "bagno")
        self.assertIsNone(categorize_label("Zona non identificata xyz"))

    def test_adjacency_mapped_when_keys_match_ids(self):
        cucina = self.b.room_by_id("1")
        self.assertEqual(sorted(cucina.neighbors), ["2", "3"])

    def test_no_scale_leaves_area_m2_none(self):
        data = {"rooms": [{"id": "9", "label": "X", "area_px": 1000,
                           "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}]}
        b = build_from_dict(data)
        self.assertIsNone(b.room_by_id("9").area_m2)
        self.assertIsNone(b.total_area_m2)

    def test_nested_floors_shape(self):
        data = {"source": {"scale": "1:50"},
                "floors": [{"id": "f0", "rooms": [{"id": "r1", "label": "Sala", "area_m2": 20.0}]}]}
        b = build_from_dict(data)
        self.assertEqual(len(b.rooms), 1)
        self.assertEqual(b.room_by_id("r1").floor_id, "f0")
        self.assertAlmostEqual(b.total_area_m2, 20.0)


class TestQueries(unittest.TestCase):
    def setUp(self):
        self.b = load(FIXTURE)

    def _ask(self, q):
        return answer(self.b, q)

    def test_count_rooms(self):
        a = self._ask("quante stanze ci sono?")
        self.assertEqual(a.intent, "count_rooms")
        self.assertEqual(a.data["count"], 4)

    def test_count_rooms_english(self):
        self.assertEqual(self._ask("how many rooms are there?").data["count"], 4)

    def test_area_of_kitchen(self):
        a = self._ask("quanto e grande la cucina?")
        self.assertEqual(a.intent, "area_of_room")
        self.assertEqual(a.data["room_id"], "1")
        self.assertAlmostEqual(a.data["area_m2"], 12.0, places=2)

    def test_largest_room(self):
        a = self._ask("qual e la stanza piu grande?")
        self.assertEqual(a.intent, "extreme_room")
        self.assertEqual(a.data["room_id"], "3")  # Camera, 16 m2

    def test_smallest_room(self):
        a = self._ask("qual e la stanza piu piccola?")
        self.assertEqual(a.data["room_id"], "4")  # Bagno 2, 3.2 m2

    def test_total_area_query(self):
        a = self._ask("qual e l'area totale?")
        self.assertTrue(a.available)
        self.assertAlmostEqual(a.data["total_area_m2"], 35.2, places=2)

    def test_rooms_of_type_bathrooms(self):
        a = self._ask("quanti bagni ci sono?")
        self.assertEqual(a.intent, "rooms_of_type")
        self.assertEqual(sorted(a.data["rooms"]), ["2", "4"])

    def test_adjacency(self):
        a = self._ask("cosa confina con la cucina?")
        self.assertEqual(a.intent, "adjacency")
        self.assertEqual(sorted(a.data["neighbors"]), ["2", "3"])

    def test_orientation_unavailable_not_invented(self):
        a = self._ask("quali stanze sono esposte a sud?")
        self.assertEqual(a.intent, "orientation")
        self.assertFalse(a.available)

    def test_scale_metadata(self):
        a = self._ask("che scala ha la planimetria?")
        self.assertEqual(a.intent, "scale")
        self.assertEqual(a.data["scale"], "1:100")

    def test_unknown_question(self):
        a = self._ask("qual e il colore preferito dell'architetto?")
        self.assertEqual(a.intent, "unknown")
        self.assertFalse(a.available)

    def test_answers_never_crash(self):
        for q in ["", "?!?", "bagno", "area", "confina", "nord",
                  "list rooms", "superficie totale", "stanza piu piccola"]:
            self.assertIsNotNone(answer(self.b, q))


class TestRealSampleIfPresent(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(REAL_SAMPLE), "parser sample knowledge_model.json not present")
    def test_loads_real_parser_output(self):
        b = load(REAL_SAMPLE)
        self.assertGreater(len(b.rooms), 0)
        # No scale in that sample -> metric area must be unavailable, not invented.
        self.assertFalse(b.has_metric_area)
        # count query works regardless of scale
        self.assertEqual(answer(b, "quante stanze ci sono?").data["count"], len(b.rooms))
        # adjacency in that sample is candidate-indexed, not room-indexed -> unavailable
        adj = answer(b, "cosa confina con la prima stanza?")
        self.assertIn(adj.intent, {"adjacency", "unknown", "area_of_room"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
