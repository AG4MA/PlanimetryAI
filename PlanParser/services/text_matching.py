"""
Text Matching Service
=====================
Encapsulates text similarity and matching logic.
Extracted from RoomDetector to follow SRP.
"""

import re
from difflib import SequenceMatcher

from PlanParser.core.protocols import TextMatcher, TextNormalizer


class DefaultTextNormalizer(TextNormalizer):
    """Default text normalizer: lowercase, strip, remove punctuation."""

    _PUNCTUATION_RE = re.compile(r'[^\w\s]')

    def normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        text = text.lower().strip()
        text = self._PUNCTUATION_RE.sub('', text)
        return ' '.join(text.split())  # Collapse whitespace


class SequenceTextMatcher(TextMatcher):
    """
    Text matcher using SequenceMatcher.
    Provides configurable normalization.
    """

    def __init__(
        self,
        normalizer: TextNormalizer | None = None,
        case_sensitive: bool = False
    ) -> None:
        self._normalizer = normalizer or DefaultTextNormalizer()
        self._case_sensitive = case_sensitive

    def _prepare(self, text: str) -> str:
        """Prepare text for comparison."""
        if self._case_sensitive:
            return text.strip()
        return self._normalizer.normalize(text)

    def similarity(self, a: str, b: str) -> float:
        """Calculate similarity ratio between two strings."""
        a_norm = self._prepare(a)
        b_norm = self._prepare(b)
        
        if not a_norm or not b_norm:
            return 0.0
        
        return SequenceMatcher(None, a_norm, b_norm).ratio()

    def find_best_match(
        self,
        text: str,
        targets: set[str],
        threshold: float = 0.75
    ) -> tuple[str, float] | None:
        """
        Find the best matching target for the given text.
        
        Returns:
            Tuple of (best_match, score) or None if no match above threshold.
        """
        if not text or not targets:
            return None

        best_target = ""
        best_score = 0.0

        for target in targets:
            score = self.similarity(text, target)
            if score > best_score:
                best_score = score
                best_target = target

        if best_score >= threshold:
            return (best_target, best_score)
        return None


class FuzzyTextMatcher(TextMatcher):
    """
    Advanced fuzzy matcher with multiple strategies.
    Tries exact match, then prefix, then fuzzy.
    """

    def __init__(
        self,
        normalizer: TextNormalizer | None = None,
        prefix_weight: float = 0.9
    ) -> None:
        self._normalizer = normalizer or DefaultTextNormalizer()
        self._prefix_weight = prefix_weight

    def _prepare(self, text: str) -> str:
        return self._normalizer.normalize(text)

    def similarity(self, a: str, b: str) -> float:
        """Calculate similarity with prefix boost."""
        a_norm = self._prepare(a)
        b_norm = self._prepare(b)

        if not a_norm or not b_norm:
            return 0.0

        # Exact match
        if a_norm == b_norm:
            return 1.0

        # Prefix match (e.g., "cucina" matches "cucina abitabile")
        shorter, longer = sorted([a_norm, b_norm], key=len)
        if longer.startswith(shorter):
            return self._prefix_weight

        # Sequence similarity
        return SequenceMatcher(None, a_norm, b_norm).ratio()

    def find_best_match(
        self,
        text: str,
        targets: set[str],
        threshold: float = 0.75
    ) -> tuple[str, float] | None:
        """Find best match using fuzzy strategy."""
        if not text or not targets:
            return None

        best_target = ""
        best_score = 0.0

        for target in targets:
            score = self.similarity(text, target)
            if score > best_score:
                best_score = score
                best_target = target

        if best_score >= threshold:
            return (best_target, best_score)
        return None

    def find_all_matches(
        self,
        text: str,
        targets: set[str],
        threshold: float = 0.5
    ) -> list[tuple[str, float]]:
        """Find all matches above threshold, sorted by score."""
        if not text or not targets:
            return []

        matches = [
            (target, self.similarity(text, target))
            for target in targets
        ]
        
        return sorted(
            [(t, s) for t, s in matches if s >= threshold],
            key=lambda x: x[1],
            reverse=True
        )
