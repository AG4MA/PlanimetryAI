from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "planparser.opening-detection.decision-register/1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECISION_STATUSES = frozenset({"confirmed", "superseded"})
_QUESTION_STATUSES = frozenset({"open", "resolved", "superseded"})


class RegisterValidationError(ValueError):
    """Raised when persistent project knowledge is ambiguous or unsafe."""


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegisterValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_sha256(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise RegisterValidationError(f"{field_name} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class Scope:
    scope_key: str
    kind: str
    source: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Scope":
        scope = cls(
            scope_key=_required_text(value.get("scope_key"), "scope.scope_key"),
            kind=_required_text(value.get("kind"), "scope.kind"),
            source=value.get("source"),
        )
        scope.validate()
        return scope

    def validate(self) -> None:
        if self.kind not in {"global", "page"}:
            raise RegisterValidationError(f"Unsupported scope kind: {self.kind}")
        if self.kind == "global":
            if self.source is not None:
                raise RegisterValidationError("A global scope cannot have a page source")
            return
        if not isinstance(self.source, Mapping):
            raise RegisterValidationError("A page scope requires source metadata")
        _required_text(self.source.get("filename"), "scope.source.filename")
        _optional_sha256(
            self.source.get("document_sha256"), "scope.source.document_sha256"
        )
        _optional_sha256(
            self.source.get("page_image_sha256"), "scope.source.page_image_sha256"
        )
        if not isinstance(self.source.get("page_number"), int) or self.source["page_number"] < 1:
            raise RegisterValidationError("scope.source.page_number must be positive")
        dimensions = self.source.get("dimensions_px")
        if (
            not isinstance(dimensions, list)
            or len(dimensions) != 2
            or any(not isinstance(item, int) or item <= 0 for item in dimensions)
        ):
            raise RegisterValidationError(
                "scope.source.dimensions_px must be [width, height]"
            )
        if not isinstance(self.source.get("render_dpi"), int) or self.source["render_dpi"] <= 0:
            raise RegisterValidationError("scope.source.render_dpi must be positive")


@dataclass(frozen=True)
class Decision:
    decision_id: str
    status: str
    topic: str
    assertion: str
    scope_key: str
    evidence: Mapping[str, Any]
    constraints: tuple[str, ...]
    supersedes: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Decision":
        constraints = value.get("constraints", [])
        if not isinstance(constraints, list) or any(
            not isinstance(item, str) or not item.strip() for item in constraints
        ):
            raise RegisterValidationError("decision.constraints must contain text")
        evidence = value.get("evidence")
        if not isinstance(evidence, Mapping):
            raise RegisterValidationError("decision.evidence must be an object")
        decision = cls(
            decision_id=_required_text(value.get("decision_id"), "decision.decision_id"),
            status=_required_text(value.get("status"), "decision.status"),
            topic=_required_text(value.get("topic"), "decision.topic"),
            assertion=_required_text(value.get("assertion"), "decision.assertion"),
            scope_key=_required_text(value.get("scope_key"), "decision.scope_key"),
            evidence=dict(evidence),
            constraints=tuple(constraints),
            supersedes=value.get("supersedes"),
        )
        decision.validate()
        return decision

    def validate(self) -> None:
        if self.status not in _DECISION_STATUSES:
            raise RegisterValidationError(f"Unsupported decision status: {self.status}")
        if self.evidence.get("actor") != "project_owner":
            raise RegisterValidationError("Confirmed decisions require project_owner evidence")
        if self.evidence.get("method") != "explicit_confirmation":
            raise RegisterValidationError("Decision evidence must be explicit confirmation")
        if self.status == "superseded" and not self.supersedes:
            raise RegisterValidationError("A superseded decision requires supersedes")


@dataclass(frozen=True)
class Question:
    question_id: str
    question_key: str
    status: str
    topic: str
    prompt: str
    scope_key: str
    target: Mapping[str, Any]
    resolution: Mapping[str, Any] | None = None
    supersedes: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Question":
        target = value.get("target")
        if not isinstance(target, Mapping):
            raise RegisterValidationError("question.target must be an object")
        resolution = value.get("resolution")
        if resolution is not None and not isinstance(resolution, Mapping):
            raise RegisterValidationError("question.resolution must be an object or null")
        question = cls(
            question_id=_required_text(value.get("question_id"), "question.question_id"),
            question_key=_required_text(value.get("question_key"), "question.question_key"),
            status=_required_text(value.get("status"), "question.status"),
            topic=_required_text(value.get("topic"), "question.topic"),
            prompt=_required_text(value.get("prompt"), "question.prompt"),
            scope_key=_required_text(value.get("scope_key"), "question.scope_key"),
            target=dict(target),
            resolution=dict(resolution) if resolution is not None else None,
            supersedes=value.get("supersedes"),
        )
        question.validate()
        return question

    def validate(self) -> None:
        if self.status not in _QUESTION_STATUSES:
            raise RegisterValidationError(f"Unsupported question status: {self.status}")
        if self.status == "resolved" and self.resolution is None:
            raise RegisterValidationError("A resolved question requires a resolution")
        if self.status != "resolved" and self.resolution is not None:
            raise RegisterValidationError(
                "Only a resolved question may contain a resolution"
            )
        if self.status == "superseded" and not self.supersedes:
            raise RegisterValidationError("A superseded question requires supersedes")


@dataclass(frozen=True)
class DecisionRegister:
    register_id: str
    revision: int
    predecessor_sha256: str | None
    scopes: tuple[Scope, ...]
    decisions: tuple[Decision, ...]
    questions: tuple[Question, ...]
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DecisionRegister":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise RegisterValidationError("Unsupported decision-register schema")
        register = cls(
            register_id=_required_text(value.get("register_id"), "register_id"),
            revision=value.get("revision"),
            predecessor_sha256=_optional_sha256(
                value.get("predecessor_sha256"), "predecessor_sha256"
            ),
            scopes=tuple(Scope.from_mapping(item) for item in value.get("scopes", [])),
            decisions=tuple(
                Decision.from_mapping(item) for item in value.get("decisions", [])
            ),
            questions=tuple(
                Question.from_mapping(item) for item in value.get("questions", [])
            ),
        )
        register.validate()
        return register

    def validate(self) -> None:
        if not isinstance(self.revision, int) or self.revision < 1:
            raise RegisterValidationError("revision must be a positive integer")
        if self.revision == 1 and self.predecessor_sha256 is not None:
            raise RegisterValidationError("revision 1 cannot have a predecessor")
        if self.revision > 1 and self.predecessor_sha256 is None:
            raise RegisterValidationError("later revisions require predecessor_sha256")
        scope_keys = self._unique(
            "scope", (item.scope_key for item in self.scopes)
        )
        decision_ids = self._unique(
            "decision", (item.decision_id for item in self.decisions)
        )
        self._unique(
            "question id", (item.question_id for item in self.questions)
        )
        self._unique(
            "question key", (item.question_key for item in self.questions)
        )
        for decision in self.decisions:
            if decision.scope_key not in scope_keys:
                raise RegisterValidationError(
                    f"Decision references unknown scope: {decision.scope_key}"
                )
            if decision.supersedes and decision.supersedes not in decision_ids:
                raise RegisterValidationError(
                    f"Decision supersedes unknown decision: {decision.supersedes}"
                )
        for question in self.questions:
            if question.scope_key not in scope_keys:
                raise RegisterValidationError(
                    f"Question references unknown scope: {question.scope_key}"
                )

    @staticmethod
    def _unique(label: str, values: Any) -> frozenset[str]:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                raise RegisterValidationError(f"Duplicate {label}: {value}")
            seen.add(value)
        return frozenset(seen)

    def question(self, question_key: str) -> Question | None:
        return next(
            (item for item in self.questions if item.question_key == question_key),
            None,
        )

    def can_ask(self, question_key: str) -> bool:
        """Return false once a stable question key has ever been registered."""

        return self.question(question_key) is None

    def open_questions(self) -> tuple[Question, ...]:
        return tuple(item for item in self.questions if item.status == "open")

    def confirmed_decisions(self) -> tuple[Decision, ...]:
        return tuple(item for item in self.decisions if item.status == "confirmed")
