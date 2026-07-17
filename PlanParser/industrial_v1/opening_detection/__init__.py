"""Atomic opening-detection service."""

from .domain.decision_register import DecisionRegister, RegisterValidationError

__all__ = ["DecisionRegister", "RegisterValidationError"]
