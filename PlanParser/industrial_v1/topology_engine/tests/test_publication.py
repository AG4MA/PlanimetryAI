from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from industrial_v1.core.contracts import ContractViolation
from industrial_v1.topology_engine import publication
from industrial_v1.topology_engine.publication import (
    ArtifactSpec,
    publish_revision,
    verify_publication,
)


class PublicationTests(unittest.TestCase):
    def specs(self, payload: bytes = b'{"ok":true}\n') -> list[ArtifactSpec]:
        return [
            ArtifactSpec(
                artifact_id="graph:json",
                relative_path="machine/document_graph.json",
                payload=payload,
                media_type="application/json",
                producer="test.document_graph",
                derived_from=("input:topology",),
            ),
            ArtifactSpec(
                artifact_id="graph:preview",
                relative_path="visual/document_graph.png",
                payload=b"synthetic-png",
                media_type="image/png",
                producer="test.document_graph",
                role="evidence",
                derived_from=("graph:json",),
            ),
        ]

    def test_publish_and_verify_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            result = publish_revision(target, self.specs(), metadata={"run_id": "run_test"})

            self.assertEqual(result.target, target.resolve())
            self.assertEqual(result.manifest_path, target.resolve() / "artifact_manifest.json")
            manifest = verify_publication(target)
            self.assertEqual(manifest["metadata"], {"run_id": "run_test"})
            self.assertTrue(manifest["publication"]["manifest_written_last"])
            self.assertEqual(len(manifest["artifacts"]), 2)
            for item in manifest["artifacts"]:
                path = target / item["path"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
                self.assertEqual(path.stat().st_size, item["byte_size"])
            private = [item.name for item in target.parent.iterdir() if item.name.startswith(".")]
            self.assertEqual(private, [])

    def test_existing_target_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            publish_revision(target, self.specs(b"first"))
            original = (target / "machine/document_graph.json").read_bytes()

            with self.assertRaises(ContractViolation):
                publish_revision(target, self.specs(b"second"))

            self.assertEqual((target / "machine/document_graph.json").read_bytes(), original)
            verify_publication(target)

    def test_verifier_rejects_tampering_and_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            publish_revision(target, self.specs())
            artifact = target / "machine/document_graph.json"
            artifact.write_bytes(b"tampered")
            with self.assertRaisesRegex(ContractViolation, "hash mismatch"):
                verify_publication(target)

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            publish_revision(target, self.specs())
            (target / "undeclared.bin").write_bytes(b"extra")
            with self.assertRaisesRegex(ContractViolation, "differs from manifest"):
                verify_publication(target)

    def test_manifest_write_is_the_last_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            events: list[str] = []
            original_bytes = publication.write_bytes_atomic_exclusive
            original_json = publication.write_json_atomic_exclusive

            def bytes_wrapper(path: Path, payload: bytes) -> None:
                events.append(f"bytes:{Path(path).name}")
                original_bytes(path, payload)

            def json_wrapper(path: Path, payload: object) -> None:
                events.append(f"json:{Path(path).name}")
                original_json(path, payload)

            with mock.patch.object(
                publication, "write_bytes_atomic_exclusive", side_effect=bytes_wrapper
            ), mock.patch.object(
                publication, "write_json_atomic_exclusive", side_effect=json_wrapper
            ):
                publish_revision(target, self.specs())

            self.assertEqual(events[-1], "json:artifact_manifest.json")

    def test_unsafe_artifact_path_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "revision_001"
            spec = ArtifactSpec(
                artifact_id="escape",
                relative_path="../escape.bin",
                payload=b"no",
                media_type="application/octet-stream",
                producer="test",
            )
            with self.assertRaises(ContractViolation):
                publish_revision(target, [spec])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
