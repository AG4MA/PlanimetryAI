from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from industrial_v1.topology_engine.application.contracts import ArtifactReference
from industrial_v1.topology_engine.application.provenance import (
    build_input_identity,
    build_input_snapshot,
    build_job_provenance,
    engine_source_digest,
    stable_job_id,
)


class ProvenanceTests(unittest.TestCase):
    def test_recursive_engine_digest_is_stable_and_excludes_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "application").mkdir()
            nested = root / "application" / "service.py"
            nested.write_text("VALUE = 2\n", encoding="utf-8")
            (root / "tests").mkdir()
            ignored = root / "tests" / "test_engine.py"
            ignored.write_text("VALUE = 3\n", encoding="utf-8")
            first = engine_source_digest(root)
            ignored.write_text("VALUE = 4\n", encoding="utf-8")
            self.assertEqual(engine_source_digest(root), first)
            nested.write_text("VALUE = 5\n", encoding="utf-8")
            self.assertNotEqual(engine_source_digest(root), first)

    def test_identity_snapshot_and_job_id_are_canonical(self):
        reference = ArtifactReference(
            role="input",
            path=Path("unused"),
            relative_path="input.json",
            sha256="a" * 64,
            byte_size=12,
        )
        identity = build_input_identity(
            engine_version="1.0.0",
            engine_source_sha256="b" * 64,
            config_snapshot={"z": 2, "a": 1},
            raw_job={"page_id": "P", "document_id": "D"},
            input_references=[reference],
        )
        same_different_key_order = {
            "inputs": identity["inputs"],
            "job": {"document_id": "D", "page_id": "P"},
            "config": {"a": 1, "z": 2},
            "engine_source_sha256": "b" * 64,
            "engine_version": "1.0.0",
        }
        self.assertEqual(stable_job_id(identity), stable_job_id(same_different_key_order))
        snapshot = build_input_snapshot(identity)
        self.assertEqual(snapshot["job_id"], stable_job_id(identity))
        self.assertEqual(snapshot["inputs"][0]["byte_size"], 12)

    def test_high_level_provenance_contains_source_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "engine.py").write_text("pass\n", encoding="utf-8")
            provenance = build_job_provenance(
                engine_root=root,
                engine_version="1",
                config_snapshot={},
                raw_job={"id": "job"},
                input_references=[
                    {"role": "x", "relative_path": "x", "sha256": "c" * 64, "byte_size": 1}
                ],
            )
            self.assertEqual(provenance.job_id, provenance.input_snapshot["job_id"])
            self.assertEqual(len(provenance.engine_source_sha256), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
