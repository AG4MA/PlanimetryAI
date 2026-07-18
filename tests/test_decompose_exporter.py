import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from PlanParser.decomposition import validate_decomposition
from PlanParser.decomposition.exporter import build_document, build_page_record


class DecompositionExporterTests(unittest.TestCase):
    def test_floor_local_coordinates_are_mapped_back_to_page(self):
        floor = SimpleNamespace(
            source_rect=(100, 200, 400, 300),
            image=np.zeros((300, 400, 3), dtype=np.uint8),
            confidence=0.9,
            label="piano terra",
        )
        segment = SimpleNamespace(
            x1=10, y1=20, x2=110, y2=20, length=100, angle_deg=0
        )
        text = SimpleNamespace(
            x=20, y=30, w=80, h=20, text="Soggiorno", confidence=91
        )
        extraction = SimpleNamespace(segments=[segment], text_blocks=[text])
        wall = {
            "start_point": (10, 20),
            "end_point": (110, 20),
            "length_px": 100,
            "wall_type": "external",
        }
        room = SimpleNamespace(
            polygon=[(10, 20), (110, 20), (110, 120), (10, 120)],
            label="Soggiorno",
            label_confidence=0.91,
            area_px=10000,
            walls=[wall],
        )
        page, warnings = build_page_record(
            page_index=0,
            width_px=1000,
            height_px=800,
            render_dpi=300,
            floor_results=[{"floor": floor, "extraction": extraction, "rooms": [room]}],
            cv_version="test",
        )
        line = next(obs for obs in page["observations"] if obs["id"].endswith("line-0"))
        room_obs = next(obs for obs in page["observations"] if "-room-" in obs["id"] and "-wall-" not in obs["id"])
        self.assertEqual(line["geometry"]["points"], [[110.0, 220.0], [210.0, 220.0]])
        self.assertEqual(room_obs["geometry"]["points"][0], [110.0, 220.0])
        self.assertEqual(warnings, [])

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.png"
            source.write_bytes(b"not-an-image-needed-for-exporter-test")
            document = build_document(
                source_path=source,
                page_records=[page],
                warnings=warnings,
                render_dpi=300,
            )
        self.assertEqual(validate_decomposition(document), [])


if __name__ == "__main__":
    unittest.main()
