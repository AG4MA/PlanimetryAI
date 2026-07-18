"""Pure domain contracts for opening detection."""

from .decision_register import (
    Decision,
    DecisionRegister,
    Question,
    RegisterValidationError,
    Scope,
)

__all__ = [
    "Decision",
    "DecisionRegister",
    "Question",
    "RegisterValidationError",
    "Scope",
]
