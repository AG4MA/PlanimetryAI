from __future__ import annotations

import hashlib
from typing import Any, Iterable

from industrial_v1.core.contracts import canonical_json_bytes


DEFAULT_BASELINE_FIELDS: tuple[str, ...] = (
    "text_nodes",
    "geometry_barrier_audit",
    "expansion_seed_audit",
    "space_candidates",
    "topology_edges",
    "summary",
)


def _project_like(reference: Any, candidate: Any) -> Any:
    """Project a richer candidate onto the exact shape of a frozen reference."""
    if isinstance(reference, dict):
        if not isinstance(candidate, dict):
            return candidate
        return {
            key: _project_like(value, candidate.get(key))
            for key, value in reference.items()
        }
    if isinstance(reference, list):
        if not isinstance(candidate, list):
            return candidate
        return [
            _project_like(reference[index], candidate[index])
            if index < len(candidate)
            else None
            for index in range(len(reference))
        ]
    return candidate


def _diff(
    reference: Any,
    candidate: Any,
    path: str,
    output: list[dict[str, Any]],
    limit: int,
) -> None:
    if len(output) >= limit:
        return
    if type(reference) is not type(candidate):
        output.append(
            {
                "path": path,
                "kind": "type_mismatch",
                "expected_type": type(reference).__name__,
                "actual_type": type(candidate).__name__,
                "expected": reference,
                "actual": candidate,
            }
        )
        return
    if isinstance(reference, dict):
        for key in sorted(set(reference) | set(candidate)):
            child = f"{path}.{key}" if path else key
            if key not in reference:
                output.append({"path": child, "kind": "unexpected_key"})
            elif key not in candidate:
                output.append({"path": child, "kind": "missing_key"})
            else:
                _diff(reference[key], candidate[key], child, output, limit)
            if len(output) >= limit:
                return
        return
    if isinstance(reference, list):
        if len(reference) != len(candidate):
            output.append(
                {
                    "path": path,
                    "kind": "length_mismatch",
                    "expected": len(reference),
                    "actual": len(candidate),
                }
            )
        for index, (expected, actual) in enumerate(zip(reference, candidate)):
            _diff(expected, actual, f"{path}[{index}]", output, limit)
            if len(output) >= limit:
                return
        return
    if reference != candidate:
        output.append(
            {
                "path": path,
                "kind": "value_mismatch",
                "expected": reference,
                "actual": candidate,
            }
        )


def compare_with_baseline(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    *,
    fields: Iterable[str] = DEFAULT_BASELINE_FIELDS,
    diff_limit: int = 100,
) -> dict[str, Any]:
    selected_fields = tuple(fields)
    expected = {field: reference.get(field) for field in selected_fields}
    actual_rich = {field: candidate.get(field) for field in selected_fields}
    actual = _project_like(expected, actual_rich)
    differences: list[dict[str, Any]] = []
    _diff(expected, actual, "", differences, diff_limit)
    expected_bytes = canonical_json_bytes(expected)
    actual_bytes = canonical_json_bytes(actual)
    return {
        "match": expected_bytes == actual_bytes,
        "fields": list(selected_fields),
        "reference_projection_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "candidate_projection_sha256": hashlib.sha256(actual_bytes).hexdigest(),
        "difference_count_capped": len(differences),
        "difference_limit": diff_limit,
        "differences": differences,
    }


__all__ = ["DEFAULT_BASELINE_FIELDS", "compare_with_baseline"]
