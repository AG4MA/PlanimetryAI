from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from industrial_v1.topology_engine.application.contracts import (
    ArtifactReferenceError,
    FloorContractError,
    JOB_SCHEMA_VERSION,
)
from industrial_v1.topology_engine.application.input_loader import (
    load_region_payloads,
    load_topology_job,
    resolve_inside,
    scope_floor_records,
)
from industrial_v1.topology_engine.config import TopologyEngineConfig


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class JobLoaderTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        write_json(root / "config.json", TopologyEngineConfig.legacy_v1().to_dict())
        write_json(root / "floors.json", {"floor_units": [{"id": "FR-001"}]})
        (root / "page.png").write_bytes(b"page")
        (root / "region.png").write_bytes(b"region")
        write_json(root / "regions.json", {"regions": [{"id": "region_001", "bbox_px": [10, 20, 30, 40]}]})
        for name in ("text.json", "linework.json", "bands.json", "baseline.json"):
            write_json(root / name, {"name": name})

        def ref(name: str) -> dict[str, str]:
            path = root / name
            return {"path": name, "sha256": sha256(path)}

        job = {
            "schema_version": JOB_SCHEMA_VERSION,
            "document_id": "doc-1",
            "page_id": "page-1",
            "engine_config": ref("config.json"),
            "floor_units": ref("floors.json"),
            "page_image": ref("page.png"),
            "regions": [
                {
                    "region_id": "region_001",
                    "floor_id": "FR-001",
                    "text_adapter": "synthetic_v1",
                    "config_overrides": {"text_assignment_policy": "none"},
                    "source_image": ref("region.png"),
                    "region_contract": ref("regions.json"),
                    "text_input": ref("text.json"),
                    "linework": ref("linework.json"),
                    "wall_bands": ref("bands.json"),
                    "baseline": ref("baseline.json"),
                }
            ],
        }
        write_json(root / "job.json", job)
        return root / "job.json"

    def test_job_refs_floor_region_and_frame_are_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            loaded = load_topology_job(job_path=self.fixture(root), root=root)
            self.assertEqual(loaded.document_id, "doc-1")
            self.assertEqual(loaded.floor_scope, {"FR-001": "page-1:FR-001"})
            self.assertEqual(len(loaded.input_references), 9)
            region = loaded.region("region_001")
            self.assertEqual(region.scoped_floor_id, "page-1:FR-001")
            self.assertEqual(region.frame.bbox_page_px_xywh, (10, 20, 30, 40))
            self.assertEqual(region.frame.document_id, "doc-1")
            self.assertEqual(region.config.text_assignment_policy, "none")
            payloads = load_region_payloads(region)
            self.assertEqual(set(payloads), {"region_contract", "text_input", "linework", "wall_bands", "baseline"})
            self.assertEqual(region.references.computation_descriptors()[0]["role"], "source_image")
            self.assertEqual(region.references.computation_descriptors()[0]["path"], "region.png")

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path = self.fixture(root)
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["engine_config"]["sha256"] = "0" * 64
            write_json(job_path, job)
            with self.assertRaises(ArtifactReferenceError):
                load_topology_job(job_path=job_path, root=root)

    def test_existing_escape_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            (base / "outside.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ArtifactReferenceError):
                resolve_inside(root, "../outside.json")

    def test_duplicate_floor_ids_are_rejected(self):
        with self.assertRaises(FloorContractError):
            scope_floor_records("page", [{"id": "F1"}, {"id": "F1"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
