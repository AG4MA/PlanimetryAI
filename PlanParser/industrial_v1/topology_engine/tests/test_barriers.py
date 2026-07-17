from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np


PLANPARSER_ROOT = Path(__file__).resolve().parents[3]
if str(PLANPARSER_ROOT) not in sys.path:
    sys.path.insert(0, str(PLANPARSER_ROOT))

from industrial_v1.topology_engine.barriers import (  # noqa: E402
    band_text_overlap,
    boundary_sources,
    build_barriers,
    line_text_overlap,
    nearby_source_ids,
)
from industrial_v1.topology_engine.config import (  # noqa: E402
    TextAbstentionPolicy,
    TopologyEngineConfig,
)
from industrial_v1.topology_engine.models import CoordinateFrame  # noqa: E402


def line(
    identifier: str,
    points: list[list[int]],
    *,
    orientation: str,
    length: float,
    status: str = "solid",
    abstained: bool = False,
) -> dict:
    return {
        "id": identifier,
        "points_px": points,
        "orientation": orientation,
        "length_px": length,
        "status": status,
        "abstained": abstained,
    }


def band(identifier: str, bbox: list[int], polygon: list[list[int]], *, length: float) -> dict:
    return {
        "id": identifier,
        "bbox_px": bbox,
        "polygon_px": polygon,
        "length_px": length,
        "status": "solid",
        "abstained": False,
    }


class TopologyConfigTests(unittest.TestCase):
    def test_legacy_profile_round_trips_dict_and_json(self):
        config = TopologyEngineConfig.legacy_v1()
        self.assertEqual(config.line_text_padding_px, 2)
        self.assertEqual(config.line_text_overlap_exclusion_ratio, 0.25)
        self.assertEqual(config.band_text_overlap_exclusion_ratio, 0.35)
        self.assertEqual(config.closure_kernel_length_px, 31)
        self.assertTrue(config.include_crop_boundary)
        self.assertTrue(
            config.abstention_policy.include_ocr_abstained_in_barrier_overlap
        )
        self.assertTrue(
            config.abstention_policy.include_semantic_role_abstained_in_barrier_overlap
        )
        self.assertEqual(TopologyEngineConfig.from_dict(config.to_dict()), config)
        self.assertEqual(TopologyEngineConfig.from_json(json.dumps(config.to_dict())), config)

    def test_ocr_and_semantic_abstention_policies_are_independent(self):
        policy = TextAbstentionPolicy(
            include_ocr_abstained_in_barrier_overlap=False,
            include_semantic_role_abstained_in_barrier_overlap=True,
        )
        config = replace(TopologyEngineConfig.legacy_v1(), profile="custom", abstention_policy=policy)
        candidate = line(
            "glyph", [[0, 10], [100, 10]], orientation="horizontal", length=100
        )
        ocr_abstained = {
            "bbox_crop_px_xyxy": [20, 8, 60, 12],
            "ocr_abstained": True,
            "semantic_role_abstained": False,
        }
        semantic_abstained = {
            "bbox_crop_px_xyxy": [20, 8, 60, 12],
            "ocr_abstained": False,
            "semantic_role_abstained": True,
        }
        self.assertEqual(line_text_overlap(candidate, [ocr_abstained], config), 0.0)
        self.assertEqual(line_text_overlap(candidate, [semantic_abstained], config), 0.44)


class CoordinateFrameTests(unittest.TestCase):
    def test_crop_coordinates_map_to_page_without_changing_extent(self):
        frame = CoordinateFrame("page_0001", "region_002", (829, 2093, 674, 729))
        self.assertEqual(frame.crop_to_page((0, 0)), (829.0, 2093.0))
        self.assertEqual(frame.crop_to_page((12.5, 20.25)), (841.5, 2113.25))
        self.assertEqual(
            frame.crop_bbox_xywh_to_page((3, 4, 20, 30)),
            (832.0, 2097.0, 20.0, 30.0),
        )
        self.assertEqual(
            frame.crop_bbox_xyxy_to_page((3, 4, 23, 34)),
            (832.0, 2097.0, 852.0, 2127.0),
        )


class BarrierKernelTests(unittest.TestCase):
    def setUp(self):
        self.config = TopologyEngineConfig.legacy_v1()

    def test_line_and_band_overlap_match_legacy_arithmetic(self):
        text_nodes = [{"bbox_crop_px_xyxy": [20, 8, 60, 12]}]
        horizontal = line(
            "line_h", [[0, 10], [100, 10]], orientation="horizontal", length=100
        )
        self.assertEqual(line_text_overlap(horizontal, text_nodes, self.config), 0.44)
        candidate_band = band(
            "band_1", [0, 0, 10, 10], [[0, 0], [10, 0], [10, 10], [0, 10]], length=10
        )
        self.assertEqual(
            band_text_overlap(
                candidate_band, [{"bbox_crop_px_xyxy": [5, 0, 15, 10]}], self.config
            ),
            0.5,
        )

    def test_probable_glyph_strokes_are_excluded_but_preserved_in_audit(self):
        text_nodes = [{"bbox_crop_px_xyxy": [8, 7, 32, 13]}]
        glyph = line(
            "glyph", [[10, 10], [30, 10]], orientation="horizontal", length=20
        )
        geometry = line(
            "geometry", [[8, 20], [42, 20]], orientation="horizontal", length=34
        )
        glyph_band = band(
            "glyph_band",
            [10, 8, 20, 4],
            [[10, 8], [30, 8], [30, 12], [10, 12]],
            length=20,
        )
        result = build_barriers(
            50,
            30,
            {"candidates": [glyph, geometry]},
            {"candidates": [glyph_band]},
            text_nodes,
            self.config,
        )
        line_audit = {item["id"]: item for item in result.line_audit}
        band_audit = {item["id"]: item for item in result.band_audit}
        self.assertFalse(line_audit["glyph"]["used_as_barrier"])
        self.assertEqual(line_audit["glyph"]["reason"], "excluded_probable_text_stroke")
        self.assertTrue(line_audit["geometry"]["used_as_barrier"])
        self.assertFalse(band_audit["glyph_band"]["used_as_barrier"])
        self.assertEqual(result.observed_geometry[10, 20], 0)
        self.assertEqual(result.observed_geometry[20, 20], 255)
        self.assertEqual(result.used_line_ids, frozenset({"geometry"}))
        self.assertEqual(result.used_band_ids, frozenset())

    def test_layers_reproduce_legacy_barrier_and_separate_crop_boundary(self):
        geometry = line(
            "geometry", [[10, 15], [30, 15]], orientation="horizontal", length=20
        )
        result = build_barriers(
            40,
            30,
            {"candidates": [geometry]},
            {"candidates": []},
            [],
            self.config,
        )
        expected_raw = np.zeros((30, 40), dtype=np.uint8)
        cv2.rectangle(expected_raw, (0, 0), (39, 29), 255, 4)
        cv2.line(expected_raw, (10, 15), (30, 15), 255, 3, cv2.LINE_8)
        horizontal = cv2.morphologyEx(expected_raw, cv2.MORPH_CLOSE, np.ones((1, 31), np.uint8))
        vertical = cv2.morphologyEx(expected_raw, cv2.MORPH_CLOSE, np.ones((31, 1), np.uint8))
        closed = cv2.bitwise_or(expected_raw, cv2.bitwise_or(horizontal, vertical))
        closed = cv2.dilate(closed, np.ones((3, 3), np.uint8), iterations=1)
        dilated_raw = cv2.dilate(expected_raw, np.ones((3, 3), np.uint8), iterations=1)
        expected_synthetic = cv2.bitwise_and(closed, cv2.bitwise_not(dilated_raw))
        self.assertTrue(np.array_equal(result.raw_observed, expected_raw))
        self.assertTrue(np.array_equal(result.synthetic_closures, expected_synthetic))
        self.assertTrue(np.array_equal(result.effective_barrier, closed))
        self.assertGreater(int((result.crop_boundary > 0).sum()), 0)
        self.assertEqual(result.observed_geometry[0, 0], 0)

        no_boundary = replace(self.config, profile="custom", include_crop_boundary=False)
        without_boundary = build_barriers(
            40,
            30,
            {"candidates": [geometry]},
            {"candidates": []},
            [],
            no_boundary,
        )
        self.assertEqual(int(without_boundary.crop_boundary.sum()), 0)
        self.assertTrue(np.array_equal(without_boundary.raw_observed, without_boundary.observed_geometry))

    def test_nearby_and_boundary_sources_keep_only_used_ids(self):
        source_line = line(
            "line_used", [[5, 10], [30, 10]], orientation="horizontal", length=25
        )
        ignored_line = line(
            "line_ignored", [[5, 20], [30, 20]], orientation="horizontal", length=25
        )
        source_band = band(
            "band_used",
            [28, 8, 4, 8],
            [[28, 8], [32, 8], [32, 16], [28, 16]],
            length=8,
        )
        linework = {"candidates": [source_line, ignored_line]}
        bands = {"candidates": [source_band]}
        self.assertEqual(
            nearby_source_ids(
                [30, 11], linework, bands, {"line_used"}, {"band_used"}, self.config
            ),
            ["band_used", "line_used"],
        )
        perimeter = np.zeros((30, 40), dtype=bool)
        perimeter[10, 5:31] = True
        evidence = boundary_sources(
            perimeter, linework, bands, {"line_used"}, {"band_used"}, self.config
        )
        self.assertEqual({item["source_id"] for item in evidence}, {"line_used", "band_used"})
        self.assertTrue(all(item["support_pixels_near_space_boundary"] > 0 for item in evidence))


if __name__ == "__main__":
    unittest.main(verbosity=2)
