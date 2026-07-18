import json
import tempfile
import unittest
from pathlib import Path

from Plan2HVAC.core.thermal_calculator import RoomUsage, ThermalRequirements
from Plan2HVAC.models.hvac_elements import Boiler, HVACSystem, Radiator
from Plan2HVAC.models.knowledge_model import Floor, KnowledgeModel, Room
from Plan2HVAC.output.drawing_generator import DrawingGenerator
from Plan2HVAC.output.json_exporter import JSONExporter


def sample_model():
    room = Room(
        id="room-1",
        label="Sala & cucina",
        polygon=[(0, 0), (100, 0), (100, 80), (0, 80)],
        area_m2=20,
    )
    return KnowledgeModel(
        source_file="sample.pdf",
        scale="1:100",
        scale_factor=0.01,
        orientation_north=0,
        floors=[Floor("floor-0", "Piano terra", {"x": 0, "y": 0, "width": 100, "height": 80}, [room])],
    )


def sample_system():
    return HVACSystem(
        radiators=[Radiator("rad-1", "room-1", (10, 10), 800, 600, 100, 1500)],
        boilers=[Boiler("boiler-1", (50, 40), "room-1", 24)],
        total_heating_power_kw=1.5,
    )


class JSONExporterTests(unittest.TestCase):
    def test_export_writes_expected_document_and_enum_values(self):
        requirement = ThermalRequirements(
            "room-1", "Sala", 20, 54, 4, 1500, 1000, 20, 1500, 1000, RoomUsage.LIVING
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "result.json"
            JSONExporter().export_to_file(
                sample_system(), sample_model(), {"room-1": requirement}, str(target), "D"
            )
            data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["meta"]["generator"], "Plan2HVAC")
        self.assertEqual(data["meta"]["climate_zone"], "D")
        self.assertEqual(data["meta"]["document_status"], "BOZZA_DIAGNOSTICA")
        self.assertEqual(data["thermal_requirements"]["room-1"]["room_usage"], "living")
        self.assertEqual(data["summary"]["n_radiators"], 1)


class DrawingGeneratorTests(unittest.TestCase):
    def test_svg_contains_geometry_equipment_and_escaped_labels(self):
        svg = DrawingGenerator().build_svg(sample_model(), sample_system())
        self.assertIn('<polygon points="0,0 100,0 100,80 0,80"', svg)
        self.assertIn("Sala &amp; cucina", svg)
        self.assertIn('id="equipment"', svg)
        self.assertIn("1500 W", svg)
        self.assertIn("BOZZA_DIAGNOSTICA", svg)

    def test_export_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "drawing.svg"
            DrawingGenerator().export_svg(sample_model(), sample_system(), str(target))
            self.assertTrue(target.is_file())
            self.assertTrue(target.read_text(encoding="utf-8").endswith("</svg>\n"))


if __name__ == "__main__":
    unittest.main()
