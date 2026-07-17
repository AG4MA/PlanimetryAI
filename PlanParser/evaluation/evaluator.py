"""Fail-closed Point 1 decomposition evaluator."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from PlanParser.decomposition import load_taxonomy, validate_decomposition

from .config import EvaluationConfig
from .geometry import geometry_points, polyline_length
from .matching import ObservationMatch, match_observations
from .text_metrics import levenshtein_distance, normalize_text

EVALUATOR_VERSION = "0.1.0"
REPORT_SCHEMA_VERSION = "1.0.0"

SYMMETRIC_RELATIONSHIPS = {
    "touches",
    "intersects",
    "overlaps",
    "parallel_to",
    "perpendicular_to",
    "collinear_with",
    "adjacent_candidate",
}


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _detection_stats(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1_denominator = 2 * tp + fp + fn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,
        "predicted": tp + fp,
        "precision": precision,
        "recall": recall,
        "f1": (2 * tp / f1_denominator) if f1_denominator else None,
    }


def _sum_stats(stats: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(stats)
    return _detection_stats(
        sum(int(item["tp"]) for item in values),
        sum(int(item["fp"]) for item in values),
        sum(int(item["fn"]) for item in values),
    )


def _preflight_issue(source: str, code: str, path: str, message: str) -> dict[str, str]:
    return {"source": source, "code": code, "path": path, "message": message}


def _page_map(document: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    return {int(page["page_index"]): page for page in document["pages"]}


def _preflight(
    prediction: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    config: EvaluationConfig,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    prediction_issues = validate_decomposition(prediction)
    ground_truth_issues = validate_decomposition(ground_truth)
    for issue in prediction_issues:
        issues.append(_preflight_issue(
            "prediction", issue.code, issue.path, issue.message
        ))
    for issue in ground_truth_issues:
        issues.append(_preflight_issue(
            "ground_truth", issue.code, issue.path, issue.message
        ))
    if prediction_issues or ground_truth_issues:
        return issues

    if config.require_frozen_ground_truth and ground_truth["dataset_status"] != "frozen_ground_truth":
        issues.append(_preflight_issue(
            "ground_truth",
            "ground_truth_not_frozen",
            "/dataset_status",
            "Evaluation requires dataset_status=frozen_ground_truth.",
        ))
    for page_position, page in enumerate(prediction["pages"]):
        for observation_position, observation in enumerate(page["observations"]):
            if (
                observation["provenance"]["method"] == "model"
                and observation["confidence"]["calibration_version"] is None
            ):
                issues.append(_preflight_issue(
                    "prediction",
                    "missing_calibration_version",
                    f"/pages/{page_position}/observations/{observation_position}/confidence/calibration_version",
                    "Model confidence requires a versioned calibration for evaluation.",
                ))
    if prediction["source"]["sha256"] != ground_truth["source"]["sha256"]:
        issues.append(_preflight_issue(
            "pair", "source_hash_mismatch", "/source/sha256",
            "Prediction and ground truth must refer to identical source content.",
        ))
    if prediction["taxonomy"] != ground_truth["taxonomy"]:
        issues.append(_preflight_issue(
            "pair", "taxonomy_mismatch", "/taxonomy",
            "Prediction and ground truth must use the same taxonomy reference.",
        ))

    prediction_indices = [int(page["page_index"]) for page in prediction["pages"]]
    ground_truth_indices = [int(page["page_index"]) for page in ground_truth["pages"]]
    if len(set(prediction_indices)) != len(prediction_indices):
        issues.append(_preflight_issue(
            "prediction", "duplicate_page_index", "/pages",
            "Prediction page_index values must be unique.",
        ))
    if len(set(ground_truth_indices)) != len(ground_truth_indices):
        issues.append(_preflight_issue(
            "ground_truth", "duplicate_page_index", "/pages",
            "Ground-truth page_index values must be unique.",
        ))
    if set(prediction_indices) != set(ground_truth_indices):
        issues.append(_preflight_issue(
            "pair", "page_index_mismatch", "/pages",
            "Prediction and ground truth must contain the same page indices.",
        ))
        return issues

    prediction_pages = _page_map(prediction)
    ground_truth_pages = _page_map(ground_truth)
    for page_index in sorted(ground_truth_pages):
        actual = prediction_pages[page_index]
        expected = ground_truth_pages[page_index]
        for field in ("width_px", "height_px", "render_dpi", "rotation_deg"):
            if actual[field] != expected[field]:
                issues.append(_preflight_issue(
                    "pair",
                    "page_render_mismatch",
                    f"/pages/{page_index}/{field}",
                    f"Prediction value {actual[field]!r} differs from ground truth {expected[field]!r}.",
                ))
    return issues


def _base_report(
    prediction: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    config: EvaluationConfig,
) -> dict[str, Any]:
    prediction_hash = canonical_sha256(prediction)
    ground_truth_hash = canonical_sha256(ground_truth)
    identity = {
        "evaluator_version": EVALUATOR_VERSION,
        "prediction_sha256": prediction_hash,
        "ground_truth_sha256": ground_truth_hash,
        "config_sha256": config.sha256(),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator": {"name": "PlanParser-P1-Evaluator", "version": EVALUATOR_VERSION},
        "report_id": canonical_sha256(identity),
        "status": "invalid",
        "config": config.to_dict(),
        "config_sha256": config.sha256(),
        "inputs": {
            "prediction_sha256": prediction_hash,
            "ground_truth_sha256": ground_truth_hash,
            "source_sha256": ground_truth.get("source", {}).get("sha256"),
            "taxonomy_sha256": ground_truth.get("taxonomy", {}).get("sha256"),
        },
        "issues": [],
        "summary": None,
    }


def _observation_groups(
    observations: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[(str(observation["layer"]), str(observation["class_id"]))].append(observation)
    return grouped


def _relation_key(
    relation_type: str, from_id: str, to_id: str
) -> tuple[str, str, str]:
    if relation_type in SYMMETRIC_RELATIONSHIPS and to_id < from_id:
        from_id, to_id = to_id, from_id
    return relation_type, from_id, to_id


def _summarize_values(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def _calibration_summary(
    predictions: Sequence[Mapping[str, Any]],
    matched_prediction_ids: set[str],
    bins: int,
) -> dict[str, Any]:
    covered = [
        prediction
        for prediction in predictions
        if not bool(prediction["confidence"]["abstained"])
    ]
    abstained = len(predictions) - len(covered)
    pairs = [
        (
            float(prediction["confidence"]["score"]),
            1.0 if str(prediction["id"]) in matched_prediction_ids else 0.0,
            str(prediction["id"]),
        )
        for prediction in covered
    ]
    brier = mean((score - outcome) ** 2 for score, outcome, _ in pairs) if pairs else None
    ece = 0.0 if pairs else None
    bin_rows: list[dict[str, Any]] = []
    ordered_for_bins = sorted(pairs, key=lambda item: (item[0], item[2]))
    effective_bins = min(bins, len(ordered_for_bins))
    if effective_bins:
        base_size, remainder = divmod(len(ordered_for_bins), effective_bins)
    else:
        base_size, remainder = 0, 0
    offset = 0
    for index in range(effective_bins):
        size = base_size + (1 if index < remainder else 0)
        values = ordered_for_bins[offset:offset + size]
        offset += size
        mean_confidence = mean(score for score, _, _ in values)
        accuracy = mean(outcome for _, outcome, _ in values)
        gap = abs(mean_confidence - accuracy)
        assert ece is not None
        ece += len(values) / len(pairs) * gap
        bin_rows.append({
            "lower": min(score for score, _, _ in values),
            "upper": max(score for score, _, _ in values),
            "count": len(values),
            "mean_confidence": mean_confidence,
            "accuracy": accuracy,
            "gap": gap,
        })
    matched_covered = sum(
        str(prediction["id"]) in matched_prediction_ids for prediction in covered
    )
    risk_coverage: list[dict[str, Any]] = []
    cumulative_errors = 0
    ordered_for_risk = sorted(pairs, key=lambda item: (-item[0], item[2]))
    for rank, (score, outcome, _) in enumerate(ordered_for_risk, start=1):
        cumulative_errors += int(1.0 - outcome)
        risk_coverage.append({
            "coverage": rank / len(predictions) if predictions else None,
            "risk": cumulative_errors / rank,
            "threshold": score,
            "selected": rank,
        })
    aurc = (
        sum(point["risk"] for point in risk_coverage) / len(predictions)
        if predictions and risk_coverage
        else None
    )
    return {
        "prediction_count": len(predictions),
        "covered_count": len(covered),
        "abstained_count": abstained,
        "coverage": _ratio(len(covered), len(predictions)),
        "selective_risk": _ratio(len(covered) - matched_covered, len(covered)),
        "brier_score": brier,
        "expected_calibration_error": ece,
        "binning": "equal_frequency",
        "bins": bin_rows,
        "risk_coverage": risk_coverage,
        "area_under_risk_coverage": aurc,
    }


def evaluate_decompositions(
    prediction: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """Return a deterministic report; invalid inputs fail closed without metrics."""
    config = config or EvaluationConfig()
    report = _base_report(prediction, ground_truth, config)
    issues = _preflight(prediction, ground_truth, config)
    report["issues"] = issues
    if issues:
        return report

    taxonomy = load_taxonomy()
    class_to_layer = {
        class_id: layer
        for layer, class_ids in taxonomy["layers"].items()
        for class_id in class_ids
    }
    class_counts: dict[str, dict[str, int]] = {
        class_id: {"tp": 0, "fp": 0, "fn": 0}
        for class_id in class_to_layer
    }
    layer_counts: dict[str, dict[str, int]] = {
        layer: {"tp": 0, "fp": 0, "fn": 0}
        for layer in taxonomy["layers"]
    }

    ground_truth_pages = _page_map(ground_truth)
    prediction_pages = _page_map(prediction)
    ground_truth_by_id: dict[str, Mapping[str, Any]] = {}
    prediction_by_id: dict[str, Mapping[str, Any]] = {}
    matched_ground_truth_ids: set[str] = set()
    matched_prediction_ids: set[str] = set()
    id_mapping: dict[str, str] = {}
    all_matches: list[dict[str, Any]] = []
    metric_values: dict[str, list[float]] = defaultdict(list)
    metric_approximate: Counter[str] = Counter()
    polyline_length_relative_errors: list[float] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    all_predictions: list[Mapping[str, Any]] = []

    for page_index in sorted(ground_truth_pages):
        expected_page = ground_truth_pages[page_index]
        actual_page = prediction_pages[page_index]
        page_diagonal_px = math.hypot(
            float(expected_page["width_px"]), float(expected_page["height_px"])
        )
        id_mapping[str(expected_page["id"])] = str(actual_page["id"])
        expected_observations = list(expected_page["observations"])
        actual_observations_all = list(actual_page["observations"])
        all_predictions.extend(actual_observations_all)
        actual_observations = [
            observation
            for observation in actual_observations_all
            if not bool(observation["confidence"]["abstained"])
        ]
        ground_truth_by_id.update({str(item["id"]): item for item in expected_observations})
        prediction_by_id.update({str(item["id"]): item for item in actual_observations_all})
        expected_groups = _observation_groups(expected_observations)
        actual_groups = _observation_groups(actual_observations)
        group_keys = sorted(set(expected_groups) | set(actual_groups))
        for layer, class_id in group_keys:
            expected_group = expected_groups.get((layer, class_id), [])
            actual_group = actual_groups.get((layer, class_id), [])
            matches = match_observations(
                expected_group, actual_group, config, page_diagonal_px
            )
            match_count = len(matches)
            class_counts[class_id]["tp"] += match_count
            class_counts[class_id]["fp"] += len(actual_group) - match_count
            class_counts[class_id]["fn"] += len(expected_group) - match_count
            layer_counts[layer]["tp"] += match_count
            layer_counts[layer]["fp"] += len(actual_group) - match_count
            layer_counts[layer]["fn"] += len(expected_group) - match_count
            for match in matches:
                expected = expected_group[match.ground_truth_index]
                actual = actual_group[match.prediction_index]
                expected_id = str(expected["id"])
                actual_id = str(actual["id"])
                matched_ground_truth_ids.add(expected_id)
                matched_prediction_ids.add(actual_id)
                id_mapping[expected_id] = actual_id
                comparison = match.comparison
                assert comparison.value is not None
                metric_values[comparison.metric].append(float(comparison.value))
                if (
                    comparison.secondary_metric is not None
                    and comparison.secondary_value is not None
                ):
                    metric_values[comparison.secondary_metric].append(
                        float(comparison.secondary_value)
                    )
                if comparison.approximate:
                    metric_approximate[comparison.metric] += 1
                if expected["geometry"]["type"] == actual["geometry"]["type"] == "polyline":
                    expected_length = polyline_length(geometry_points(expected["geometry"]))
                    actual_length = polyline_length(geometry_points(actual["geometry"]))
                    if expected_length > 0:
                        polyline_length_relative_errors.append(
                            abs(actual_length - expected_length) / expected_length
                        )
                all_matches.append({
                    "page_index": page_index,
                    "layer": layer,
                    "class_id": class_id,
                    "ground_truth_id": expected_id,
                    "prediction_id": actual_id,
                    "metric": comparison.metric,
                    "value": comparison.value,
                    "threshold": comparison.threshold,
                    "similarity": comparison.similarity,
                    "approximate": comparison.approximate,
                    "secondary_metric": comparison.secondary_metric,
                    "secondary_value": comparison.secondary_value,
                    "secondary_threshold": comparison.secondary_threshold,
                })

        for layer in taxonomy["layers"]:
            expected_layer = [
                item for item in expected_observations if item["layer"] == layer
            ]
            actual_layer = [
                item for item in actual_observations if item["layer"] == layer
            ]
            layer_matches = match_observations(
                expected_layer,
                actual_layer,
                config,
                page_diagonal_px,
                require_same_layer=True,
                require_same_class=False,
            )
            matched_expected_indices = {match.ground_truth_index for match in layer_matches}
            matched_actual_indices = {match.prediction_index for match in layer_matches}
            for match in layer_matches:
                expected_class = str(expected_layer[match.ground_truth_index]["class_id"])
                actual_class = str(actual_layer[match.prediction_index]["class_id"])
                confusion[expected_class][actual_class] += 1
            for index, expected in enumerate(expected_layer):
                if index not in matched_expected_indices:
                    confusion[str(expected["class_id"])]["__missing__"] += 1
            for index, actual in enumerate(actual_layer):
                if index not in matched_actual_indices:
                    confusion["__spurious__"][str(actual["class_id"])] += 1

    by_class = {
        class_id: {
            "layer": class_to_layer[class_id],
            **_detection_stats(**counts),
        }
        for class_id, counts in sorted(class_counts.items())
    }
    by_layer = {
        layer: _detection_stats(**counts)
        for layer, counts in sorted(layer_counts.items())
    }
    overall_observations = _sum_stats(by_class.values())
    eligible_f1 = [
        stats["f1"]
        for stats in by_class.values()
        if stats["support"] or stats["predicted"]
    ]
    macro_f1 = mean(value for value in eligible_f1 if value is not None) if eligible_f1 else None

    matched_pairs = [
        (ground_truth_by_id[item["ground_truth_id"]], prediction_by_id[item["prediction_id"]])
        for item in all_matches
    ]
    text_pairs = [
        (expected, actual)
        for expected, actual in matched_pairs
        if expected["layer"] == "text"
    ]
    character_edits = 0
    ground_truth_characters = 0
    word_edits = 0
    ground_truth_words = 0
    exact_matches = 0
    scored_text_pairs = 0
    for expected, actual in text_pairs:
        expected_text = expected.get("attributes", {}).get("transcription")
        actual_text = actual.get("attributes", {}).get("transcription")
        if not isinstance(expected_text, str) or not isinstance(actual_text, str):
            continue
        expected_normalized = normalize_text(expected_text, config)
        actual_normalized = normalize_text(actual_text, config)
        character_edits += levenshtein_distance(expected_normalized, actual_normalized)
        ground_truth_characters += len(expected_normalized)
        expected_tokens = expected_normalized.split()
        actual_tokens = actual_normalized.split()
        word_edits += levenshtein_distance(expected_tokens, actual_tokens)
        ground_truth_words += len(expected_tokens)
        exact_matches += expected_normalized == actual_normalized
        scored_text_pairs += 1
    text_summary = {
        "matched_pairs": len(text_pairs),
        "scored_pairs": scored_text_pairs,
        "unscored_pairs": len(text_pairs) - scored_text_pairs,
        "character_edits": character_edits,
        "ground_truth_characters": ground_truth_characters,
        "character_error_rate": _ratio(character_edits, ground_truth_characters),
        "word_edits": word_edits,
        "ground_truth_words": ground_truth_words,
        "word_error_rate": _ratio(word_edits, ground_truth_words),
        "exact_match_accuracy": _ratio(exact_matches, scored_text_pairs),
    }

    expected_relations = [
        relation for page in ground_truth["pages"] for relation in page["relationships"]
    ]
    actual_relations = [
        relation for page in prediction["pages"] for relation in page["relationships"]
    ]
    expected_relation_keys: Counter[tuple[str, str, str]] = Counter()
    for relation in expected_relations:
        relation_type = str(relation["type"])
        from_id = id_mapping.get(str(relation["from_id"]), f"__unmatched__:{relation['from_id']}")
        to_id = id_mapping.get(str(relation["to_id"]), f"__unmatched__:{relation['to_id']}")
        expected_relation_keys[_relation_key(relation_type, from_id, to_id)] += 1
    actual_relation_keys = Counter(
        _relation_key(
            str(relation["type"]), str(relation["from_id"]), str(relation["to_id"])
        )
        for relation in actual_relations
    )
    relation_types = list(taxonomy["relationship_types"])
    relations_by_type: dict[str, dict[str, Any]] = {}
    for relation_type in relation_types:
        expected_type = Counter({
            key: count for key, count in expected_relation_keys.items() if key[0] == relation_type
        })
        actual_type = Counter({
            key: count for key, count in actual_relation_keys.items() if key[0] == relation_type
        })
        true_positives = sum((expected_type & actual_type).values())
        relations_by_type[relation_type] = _detection_stats(
            true_positives,
            sum(actual_type.values()) - true_positives,
            sum(expected_type.values()) - true_positives,
        )
    relationships_summary = {
        "overall": _sum_stats(relations_by_type.values()),
        "by_type": relations_by_type,
    }

    geometry_summary = {
        "by_metric": {
            metric: {
                **_summarize_values(values),
                "approximate_count": metric_approximate[metric],
            }
            for metric, values in sorted(metric_values.items())
        },
        "polyline_length_relative_error": _summarize_values(
            polyline_length_relative_errors
        ),
    }
    calibration = _calibration_summary(
        all_predictions, matched_prediction_ids, config.calibration_bins
    )
    unmatched_ground_truth = sorted(set(ground_truth_by_id) - matched_ground_truth_ids)
    unmatched_predictions = sorted(set(prediction_by_id) - matched_prediction_ids)

    report["status"] = "valid"
    report["summary"] = {
        "observations": overall_observations,
        "macro_f1": macro_f1,
        "by_layer": by_layer,
        "by_class": by_class,
        "geometry": geometry_summary,
        "text": text_summary,
        "relationships": relationships_summary,
        "calibration": calibration,
        "confusion": {
            expected: dict(sorted(actual.items()))
            for expected, actual in sorted(confusion.items())
        },
        "matches": sorted(
            all_matches,
            key=lambda item: (item["page_index"], item["ground_truth_id"], item["prediction_id"]),
        ),
        "unmatched": {
            "ground_truth_ids": unmatched_ground_truth,
            "prediction_ids": unmatched_predictions,
        },
    }
    return report


def load_evaluation_report_schema() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("evaluation_report.schema.json").read_text(encoding="utf-8")
    )


def validate_evaluation_report(report: Mapping[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("jsonschema is required; install root requirements.txt") from exc
    validator = Draft202012Validator(load_evaluation_report_schema())
    return [
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(
            validator.iter_errors(report), key=lambda item: list(item.absolute_path)
        )
    ]
