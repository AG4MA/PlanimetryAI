import copy
import unittest

from PlanimetryDigitalConventions.validator import validate_knowledge_model


def valid_document():
    return {
        "schema_version": "1.0.0",
        "document_status": "validated",
        "meta": {
            "source_file": "sample.pdf",
            "source_type": "pdf",
            "parser_version": "0.1.0",
            "created_at": "2026-07-17T10:00:00+00:00",
            "coordinate_system": {
                "unit": "pixel",
                "origin": "top_left",
                "x_axis": "right",
                "y_axis": "down",
            },
            "scale": "1:100",
            "scale_factor_m_per_px": 0.01,
            "orientation_north_deg": 0,
            "overall_confidence": 0.95,
            "warnings": [],
        },
        "floors": [{
            "id": "floor_0",
            "label": "piano terra",
            "confidence": 0.95,
            "source_rect_px": [0, 0, 1000, 800],
            "rooms": [{
                "id": "room_0",
                "label": "soggiorno",
                "confidence": 0.95,
                "polygon_px": [[0, 0], [400, 0], [400, 300], [0, 300]],
                "area_px2": 120000,
                "area_m2": 12,
                "height_m": 2.7,
                "walls": [{
                    "id": "wall_0_0",
                    "wall_type": "external",
                    "start_px": [0, 0],
                    "end_px": [400, 0],
                    "length_px": 400,
                    "length_m": 4,
                    "confidence": 0.95,
                }],
                "openings": [],
                "connections": [],
            }],
            "topology": {"room_0": []},
        }],
        "validation": {
            "validated_at": "2026-07-17T10:00:01+00:00",
            "validator_version": "1.0.0",
            "errors": 0,
            "warnings": 0,
        },
    }


class KnowledgeModelContractTests(unittest.TestCase):
    def test_valid_construction_document_has_no_issues(self):
        self.assertEqual(
            validate_knowledge_model(valid_document(), construction_ready=True), []
        )

    def test_schema_rejects_ambiguous_legacy_geometry_fields(self):
        document = valid_document()
        room = document["floors"][0]["rooms"][0]
        room["polygon"] = room.pop("polygon_px")
        issues = validate_knowledge_model(document)
        self.assertTrue(any(issue.code == "schema" for issue in issues))

    def test_construction_gate_reports_missing_metric_and_confidence_data(self):
        document = copy.deepcopy(valid_document())
        document["meta"]["scale_factor_m_per_px"] = None
        room = document["floors"][0]["rooms"][0]
        room["confidence"] = 0.2
        room["walls"][0]["wall_type"] = "unknown"
        codes = {
            issue.code
            for issue in validate_knowledge_model(document, construction_ready=True)
        }
        self.assertEqual(
            codes,
            {"missing_metric_scale", "low_room_confidence", "unknown_wall_type"},
        )


if __name__ == "__main__":
    unittest.main()
