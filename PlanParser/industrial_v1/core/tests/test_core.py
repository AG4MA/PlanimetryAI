from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

INDUSTRIAL_ROOT = Path(__file__).resolve().parents[2]
if str(INDUSTRIAL_ROOT) not in sys.path:
    sys.path.insert(0, str(INDUSTRIAL_ROOT))

from core.bootstrap import bootstrap_run, default_config
from core.contracts import (
    ArtifactRegistry,
    ArtifactRecord,
    ContractViolation,
    ErrorRecord,
    RunManifest,
    RunState,
    assert_transition,
    deterministic_run_id,
)
from core.storage import write_bytes_atomic_exclusive


class CoreContractTests(unittest.TestCase):
    def test_registry_preserves_provenance_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.pdf"
            derived = root / "derived.json"
            source.write_bytes(b"source")
            derived.write_bytes(b"{}")
            registry = ArtifactRegistry()
            registry.register_existing_file(
                artifact_id="input:primary",
                path=source,
                media_type="application/pdf",
                producer="external",
                role="source",
            )
            registry.register_existing_file(
                artifact_id="artifact:derived",
                path=derived,
                media_type="application/json",
                producer="test",
                derived_from=("input:primary",),
            )
            records = registry.records()
            self.assertEqual(
                [record.artifact_id for record in records],
                ["input:primary", "artifact:derived"],
            )
            self.assertEqual(records[1].derived_from, ("input:primary",))

    def test_run_id_is_deterministic_and_config_sensitive(self) -> None:
        digest = "a" * 64
        versions = {"core": "1"}
        first = deterministic_run_id(digest, {"mode": "strict"}, versions)
        second = deterministic_run_id(digest, {"mode": "strict"}, versions)
        changed = deterministic_run_id(digest, {"mode": "lenient"}, versions)
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_terminal_state_cannot_transition(self) -> None:
        with self.assertRaises(ContractViolation):
            assert_transition(RunState.COMPLETED, RunState.RUNNING)

    def test_failed_manifest_requires_structured_error(self) -> None:
        source = ArtifactRecord(
            artifact_id="input:primary",
            uri="file:///example.pdf",
            sha256="b" * 64,
            byte_size=1,
            media_type="application/pdf",
            producer="external",
            role="source",
        )
        manifest = RunManifest(
            run_id="run_" + "c" * 24,
            revision=1,
            state=RunState.FAILED,
            input_sha256="b" * 64,
            created_at_utc="2026-01-01T00:00:00.000Z",
            config_snapshot={},
            version_snapshot={},
            artifacts=(source,),
        )
        with self.assertRaises(ContractViolation):
            manifest.validate()
        valid = RunManifest(
            **{
                **manifest.__dict__,
                "errors": (
                    ErrorRecord(
                        code="EXAMPLE",
                        stage="test",
                        message="controlled failure",
                        retryable=False,
                    ),
                ),
            }
        )
        valid.validate()

    def test_atomic_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            write_bytes_atomic_exclusive(path, b"first")
            with self.assertRaises(ContractViolation):
                write_bytes_atomic_exclusive(path, b"second")
            self.assertEqual(path.read_bytes(), b"first")

    def test_bootstrap_references_input_without_copying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.pdf"
            source.write_bytes(b"%PDF-1.4\nminimal fixture\n%%EOF\n")
            original = source.read_bytes()
            manifest_path = bootstrap_run(source, root / "runs")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["state"], "completed")
            self.assertEqual(
                payload["input_sha256"], hashlib.sha256(original).hexdigest()
            )
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(payload["artifacts"][0]["role"], "source")
            self.assertEqual(payload["artifacts"][0]["uri"], source.resolve().as_uri())
            self.assertEqual(
                list(manifest_path.parent.glob("*")), [manifest_path]
            )
            with self.assertRaises(ContractViolation):
                bootstrap_run(source, root / "runs")


if __name__ == "__main__":
    unittest.main()
