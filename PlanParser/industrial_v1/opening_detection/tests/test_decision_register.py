from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from industrial_v1.opening_detection.application import load_decision_register
from industrial_v1.opening_detection.domain.decision_register import (
    DecisionRegister,
    RegisterValidationError,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "knowledge" / "revision_001" / "decision_register.json"
MANIFEST_PATH = ROOT / "knowledge" / "revision_001" / "artifact_manifest.json"
QUESTION_KEY = "acri:p1:pranzo:south-opening:type"


def _payload() -> dict[str, object]:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def test_persistent_register_loads_all_confirmed_owner_decisions() -> None:
    register = load_decision_register(REGISTER_PATH)

    assert register.revision == 1
    assert len(register.confirmed_decisions()) == 12
    assert {item.evidence["actor"] for item in register.decisions} == {
        "project_owner"
    }


def test_already_asked_open_question_cannot_be_asked_again() -> None:
    register = load_decision_register(REGISTER_PATH)

    assert register.can_ask(QUESTION_KEY) is False
    assert [item.question_key for item in register.open_questions()] == [QUESTION_KEY]


def test_immutable_revision_manifest_matches_register_bytes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"][0]
    register_bytes = REGISTER_PATH.read_bytes()

    assert artifact["path"] == REGISTER_PATH.name
    assert artifact["byte_size"] == len(register_bytes)
    assert artifact["sha256"] == hashlib.sha256(register_bytes).hexdigest()


def test_resolved_question_also_cannot_be_asked_again() -> None:
    payload = _payload()
    question = payload["questions"][0]
    question["status"] = "resolved"
    question["resolution"] = {
        "actor": "project_owner",
        "normalized_value": "window",
        "response_raw": "finestra"
    }

    register = DecisionRegister.from_mapping(payload)

    assert register.can_ask(QUESTION_KEY) is False
    assert register.open_questions() == ()


def test_duplicate_question_key_is_rejected() -> None:
    payload = _payload()
    duplicate = copy.deepcopy(payload["questions"][0])
    duplicate["question_id"] = "question:duplicate"
    payload["questions"].append(duplicate)

    with pytest.raises(RegisterValidationError, match="Duplicate question key"):
        DecisionRegister.from_mapping(payload)


def test_resolved_question_requires_resolution() -> None:
    payload = _payload()
    payload["questions"][0]["status"] = "resolved"

    with pytest.raises(RegisterValidationError, match="requires a resolution"):
        DecisionRegister.from_mapping(payload)


def test_decisions_cannot_reference_an_unknown_scope() -> None:
    payload = _payload()
    payload["decisions"][0]["scope_key"] = "page:missing:1"

    with pytest.raises(RegisterValidationError, match="unknown scope"):
        DecisionRegister.from_mapping(payload)


def test_domain_has_no_filesystem_or_json_dependency() -> None:
    source = (ROOT / "domain" / "decision_register.py").read_text(encoding="utf-8")

    for forbidden in ("from pathlib", "import pathlib", "import json", "import os"):
        assert forbidden not in source


def test_opening_detection_modules_do_not_become_god_files() -> None:
    production_modules = [
        path
        for path in ROOT.rglob("*.py")
        if "tests" not in path.relative_to(ROOT).parts
        and "examples" not in path.relative_to(ROOT).parts
    ]

    assert {
        path.relative_to(ROOT).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in production_modules
        if len(path.read_text(encoding="utf-8").splitlines()) > 350
    } == {}
