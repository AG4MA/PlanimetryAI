"""Dependency-free OCR metrics for matched text observations."""

from __future__ import annotations

import re
from typing import Sequence

from .config import EvaluationConfig


def normalize_text(value: str, config: EvaluationConfig) -> str:
    normalized = value if config.text_case_sensitive else value.casefold()
    if config.text_collapse_whitespace:
        normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def levenshtein_distance(first: Sequence[str], second: Sequence[str]) -> int:
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for first_index, first_value in enumerate(first, start=1):
        current = [first_index]
        for second_index, second_value in enumerate(second, start=1):
            current.append(min(
                current[-1] + 1,
                previous[second_index] + 1,
                previous[second_index - 1] + (first_value != second_value),
            ))
        previous = current
    return previous[-1]
