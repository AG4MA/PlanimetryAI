"""
Text metrics for OCR evaluation (ACCEPTANCE_CRITERIA P1-07): CER and WER via
Levenshtein edit distance. Standard library only.
"""

from __future__ import annotations

from typing import List, Sequence


def levenshtein(a: Sequence, b: Sequence) -> int:
    """Edit distance between two sequences (chars or tokens)."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1,        # deletion
                         cur[j - 1] + 1,     # insertion
                         prev[j - 1] + cost)  # substitution
        prev = cur
    return prev[m]


def cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate = edit_distance(chars) / len(reference chars)."""
    ref = reference or ""
    if len(ref) == 0:
        return 0.0 if not (hypothesis or "") else 1.0
    return levenshtein(list(ref), list(hypothesis or "")) / len(ref)


def _tokens(text: str) -> List[str]:
    return (text or "").split()


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate = edit_distance(tokens) / len(reference tokens)."""
    ref = _tokens(reference)
    if len(ref) == 0:
        return 0.0 if not _tokens(hypothesis) else 1.0
    return levenshtein(ref, _tokens(hypothesis)) / len(ref)


def corpus_cer(pairs: Sequence[tuple]) -> float:
    """Aggregate CER over (reference, hypothesis) pairs, weighted by ref length."""
    num = den = 0
    for ref, hyp in pairs:
        ref = ref or ""
        num += levenshtein(list(ref), list(hyp or ""))
        den += len(ref)
    return num / den if den > 0 else 0.0


def corpus_wer(pairs: Sequence[tuple]) -> float:
    num = den = 0
    for ref, hyp in pairs:
        rtok = _tokens(ref)
        num += levenshtein(rtok, _tokens(hyp))
        den += len(rtok)
    return num / den if den > 0 else 0.0
