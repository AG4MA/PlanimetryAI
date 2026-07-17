from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Mapping

from PIL import Image

from industrial_v1.topology_engine.application.artifact_assembly import (
    ArtifactLayout,
    assemble_artifact_specs,
)
from industrial_v1.topology_engine.application.contracts import JobContractError


@dataclass
class Computation:
    region_id: str
    payload: Mapping[str, Any]


@dataclass
class Rendering:
    contact_sheet: Image.Image
    artifacts: Mapping[str, bytes]


class ArtifactAssemblyTests(unittest.TestCase):
    def inputs(self):
        computation = Computation("R1", {"summary": {"space_candidate_count": 2}})
        rendering = Rendering(
            Image.new("RGB", (80, 60), "white"),
            {
                "barrier_overlay.png": b"barrier",
                "text_space_topology_contact_sheet.png": b"sheet",
            },
        )
        equivalence = {"all_match": True, "regions": []}
        graph = {
            "summary": {
                "node_count": 4,
                "edge_count": 3,
                "duplicate_node_ids": 1,
                "duplicate_edge_ids": 2,
                "dangling_edge_endpoints": 0,
            }
        }
        return computation, rendering, equivalence, graph

    def test_specs_and_final_review_preserve_ancestry(self):
        computation, rendering, equivalence, graph = self.inputs()
        assembly = assemble_artifact_specs(
            engine_version="1.0.0",
            document_id="D",
            page_id="P",
            input_snapshot={"job_id": "J"},
            computations=[computation],
            renderings={"R1": rendering},
            equivalence_report=equivalence,
            document_graph=graph,
        )
        by_id = {item.artifact_id: item for item in assembly.artifacts}
        self.assertEqual(len(by_id), 8)
        self.assertEqual(
            by_id["region:R1:topology"].derived_from, ("batch:input_snapshot",)
        )
        expected_review_ancestry = (
            "region:R1:text_space_topology_contact_sheet",
            "batch:equivalence_report",
            "page:document_graph",
        )
        self.assertEqual(
            by_id["review:consolidation_png"].derived_from,
            expected_review_ancestry,
        )
        self.assertTrue(by_id["review:consolidation_png"].payload.startswith(b"\x89PNG"))
        self.assertTrue(by_id["review:consolidation_pdf"].payload.startswith(b"%PDF"))
        self.assertEqual(assembly.review.graph_summary["duplicate_id_count"], 3)
        self.assertEqual(assembly.review.region_ids, ("R1",))

    def test_layout_is_injected_not_bound_to_filesystem(self):
        computation, rendering, equivalence, graph = self.inputs()
        layout = ArtifactLayout(machine_directory="m", regions_directory="r", review_directory="v")
        assembly = assemble_artifact_specs(
            engine_version="1",
            document_id="D",
            page_id="P",
            input_snapshot={},
            computations=[computation],
            renderings={"R1": rendering},
            equivalence_report=equivalence,
            document_graph=graph,
            layout=layout,
        )
        paths = {item.relative_path for item in assembly.artifacts}
        self.assertIn("m/input_snapshot.json", paths)
        self.assertIn("r/R1/text_space_topology.json", paths)
        self.assertIn("v/consolidation_review.pdf", paths)

    def test_missing_contact_sheet_artifact_is_rejected(self):
        computation, rendering, equivalence, graph = self.inputs()
        rendering = Rendering(rendering.contact_sheet, {"barrier_overlay.png": b"x"})
        with self.assertRaises(JobContractError):
            assemble_artifact_specs(
                engine_version="1",
                document_id="D",
                page_id="P",
                input_snapshot={},
                computations=[computation],
                renderings={"R1": rendering},
                equivalence_report=equivalence,
                document_graph=graph,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
