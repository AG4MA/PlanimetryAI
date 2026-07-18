from __future__ import annotations

import copy
import unittest

from industrial_v1.topology_engine.document_graph import (
    GraphContractError,
    aggregate_document_graph,
    validate_document_graph,
)


def region_payload(name: str, evidence_id: str, evidence_type: str) -> dict:
    return {
        "status": "automatic_candidates_not_human_approved",
        "source": {"bbox_page_px_xywh": [10, 20, 100, 120]},
        "summary": {"name": name},
        "text_nodes": [
            {
                "id": "text_node_001",
                "raw_text_alternatives": [name],
                "role_hypothesis": "space_name_seed",
            },
            {
                "id": "text_node_context",
                "raw_text_alternatives": ["altra uiu"],
                "role_hypothesis": "external_context_label",
            },
        ],
        "space_candidates": [
            {
                "id": "space_candidate_001",
                "name_hypothesis": name,
                "boundary_evidence": [
                    {
                        "source_id": evidence_id,
                        "source_type": evidence_type,
                        "support_pixels_near_space_boundary": 12,
                    },
                    {
                        "source_id": "band_unlinked",
                        "source_type": "parallel_edge_band_hypothesis",
                        "support_pixels_near_space_boundary": 4,
                    },
                ],
            }
        ],
        "geometry_barrier_audit": {
            "line_candidates": [
                {"id": evidence_id, "used_as_barrier": True}
                if evidence_id.startswith("line_")
                else {"id": "line_unused", "used_as_barrier": False}
            ],
            "band_candidates": [
                {"id": evidence_id, "used_as_barrier": True}
                if evidence_id.startswith("band_")
                else {"id": "band_unlinked", "used_as_barrier": True}
            ],
        },
        "topology_edges": [
            {
                "id": "edge_001",
                "relation": "names_space_candidate",
                "from": "text_node_001",
                "to": "space_candidate_001",
                "status": "hypothesis",
            },
            {
                "id": "edge_002",
                "relation": "bounded_by_candidate_evidence",
                "from": "space_candidate_001",
                "to": evidence_id,
                "target_type": evidence_type,
                "status": "observed_relation_not_building_semantics",
            },
        ],
    }


class DocumentGraphTests(unittest.TestCase):
    def build(self) -> dict:
        return aggregate_document_graph(
            document_id="doc_test",
            page_id="page_0001",
            floor_units=[
                {"id": "FR-001", "title_text_raw": "Piano Primo"},
                {"id": "FR-002", "title_text_raw": "Piano Terra"},
            ],
            regional_payloads={
                "region_001": region_payload(
                    "bagno", "line_001", "raw_linework_candidate"
                ),
                "region_002": region_payload(
                    "cucina", "band_001", "parallel_edge_band_hypothesis"
                ),
            },
            region_to_floor={"region_001": "FR-001", "region_002": "FR-002"},
            page_attributes={"width_px": 2481, "height_px": 3508},
        )

    def test_aggregation_prefixes_local_ids_and_materializes_evidence(self) -> None:
        graph = self.build()
        node_ids = {node["id"] for node in graph["nodes"]}
        edge_ids = [edge["id"] for edge in graph["edges"]]

        self.assertIn("text:region_001:text_node_001", node_ids)
        self.assertIn("text:region_002:text_node_001", node_ids)
        self.assertIn("space:region_001:space_candidate_001", node_ids)
        self.assertIn("evidence:region_001:line_001", node_ids)
        self.assertIn("evidence:region_002:band_001", node_ids)
        self.assertIn("evidence:region_001:band_unlinked", node_ids)
        self.assertEqual(len(edge_ids), len(set(edge_ids)))
        self.assertIn("edge:region_001:edge_001", edge_ids)
        self.assertIn("edge:region_002:edge_001", edge_ids)
        self.assertEqual(graph["summary"]["dangling_edge_endpoints"], 0)
        self.assertEqual(graph["summary"]["cross_floor_edges"], 0)
        self.assertEqual(validate_document_graph(graph)["duplicate_edge_ids"], 0)

        context_nodes = [
            node
            for node in graph["nodes"]
            if node["type"] == "text_node"
            and node["attributes"].get("role_hypothesis") == "external_context_label"
        ]
        self.assertEqual(len(context_nodes), 2)
        context_ids = {node["id"] for node in context_nodes}
        naming_edges = {
            edge["from"]
            for edge in graph["edges"]
            if edge["relation"] == "names_space_candidate"
        }
        self.assertTrue(context_ids.isdisjoint(naming_edges))

    def test_validator_rejects_duplicate_node_and_edge_ids(self) -> None:
        graph = self.build()
        duplicate_node = copy.deepcopy(graph)
        duplicate_node["nodes"].append(copy.deepcopy(duplicate_node["nodes"][0]))
        with self.assertRaisesRegex(GraphContractError, "Duplicate graph node id"):
            validate_document_graph(duplicate_node)

        duplicate_edge = copy.deepcopy(graph)
        duplicate_edge["edges"].append(copy.deepcopy(duplicate_edge["edges"][0]))
        with self.assertRaisesRegex(GraphContractError, "Duplicate graph edge id"):
            validate_document_graph(duplicate_edge)

    def test_validator_rejects_dangling_endpoint(self) -> None:
        graph = self.build()
        graph["edges"].append(
            {
                "id": "edge:test:dangling",
                "relation": "invalid_test_relation",
                "from": "space:region_001:space_candidate_001",
                "to": "evidence:region_001:missing",
            }
        )
        with self.assertRaisesRegex(GraphContractError, "dangling"):
            validate_document_graph(graph)

    def test_validator_rejects_cross_floor_edge(self) -> None:
        graph = self.build()
        graph["edges"].append(
            {
                "id": "edge:test:cross-floor",
                "relation": "forbidden_cross_floor_relation",
                "from": "space:region_001:space_candidate_001",
                "to": "space:region_002:space_candidate_001",
            }
        )
        with self.assertRaisesRegex(GraphContractError, "cross-floor"):
            validate_document_graph(graph)

    def test_builder_rejects_unknown_topology_endpoint(self) -> None:
        payload = region_payload("bagno", "line_001", "raw_linework_candidate")
        payload["topology_edges"].append(
            {
                "id": "edge_unknown",
                "relation": "unknown_relation",
                "from": "space_candidate_001",
                "to": "unknown_local_id",
            }
        )
        with self.assertRaisesRegex(GraphContractError, "dangling"):
            aggregate_document_graph(
                document_id="doc",
                page_id="page",
                floor_units=[{"id": "FR-001"}],
                regional_payloads={"region_001": payload},
                region_to_floor={"region_001": "FR-001"},
            )


if __name__ == "__main__":
    unittest.main()
