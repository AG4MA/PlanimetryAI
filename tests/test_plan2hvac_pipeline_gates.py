import json
import tempfile
import unittest
from pathlib import Path

from Plan2HVAC.models.knowledge_model import Floor, KnowledgeModel
from Plan2HVAC.pipeline import PipelineConfig, Plan2HVACPipeline


class Plan2HVACPipelineGateTests(unittest.TestCase):
    def test_construction_status_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "professional approval"):
            PipelineConfig(document_status="CANTIERE")

    def test_legacy_unversioned_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps({"meta": {}, "floors": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version"):
                KnowledgeModel.from_json_file(str(path))

    def test_empty_model_does_not_invent_boiler(self):
        model = KnowledgeModel(
            source_file="empty.pdf",
            scale="1:100",
            scale_factor=0.01,
            orientation_north=0,
            floors=[Floor("floor-0", "Unknown", {}, [])],
        )
        pipeline = Plan2HVACPipeline(PipelineConfig(
            generate_json=False,
            generate_svg=False,
        ))
        result = pipeline.run_from_model(model)
        self.assertEqual(result.boilers, [])
        self.assertEqual(result.pipes, [])
        self.assertEqual(result.total_heating_power_kw, 0)


if __name__ == "__main__":
    unittest.main()
