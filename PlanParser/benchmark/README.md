# PlanParser P1 Benchmark & Evaluator

Roadmap workstream **8 — Benchmark e riproducibilità** of Point 1 (Scomporre).
This module *measures* the atomic decomposition against a frozen ground truth and
produces the **Gate-1 verdict**. It is the measurement half of P1 and is kept
independent from the decomposer that produces the data.

> Scope: it consumes **only** the published contract
> `PlanParser/decomposition/decomposition.schema.json` (+ `taxonomy.v1.json`).
> It imports no decomposer internals and writes nothing outside `PlanParser/benchmark/`.

## What it computes

Both prediction and ground truth are decomposition documents (same schema). The
evaluator matches observations per `class_id` + `page_id` (IoU for areas,
proximity for points/lines) and reports, mapped to `docs/ACCEPTANCE_CRITERIA.md`:

| Block | Metrics | Criteria |
|-------|---------|----------|
| Detection | precision / recall / F1 per class, micro, macro-F1 | P1-03, P1-05, P1-06 |
| Geometry | IoU, area-error ratio, length-error ratio, centroid distance | P1-04, P1-05, P1-08 |
| OCR | CER, WER on matched text | P1-07 |
| Measurements | mean relative value error (scale/dimensions) | P1-08 |
| Relationships | edge precision/recall/F1, orphan-reference count | P1-09 |
| Calibration | ECE, Brier, coverage–risk, abstention precision/recall | P1-10, P1-16 |

Abstained predictions are **excluded from detection** (an abstention is not a
committed detection) and scored only in the calibration/abstention block.

## Fail-closed gate

`gate.py` maps metrics to Gate-1 criteria via a threshold config. It is
deliberately fail-closed:

* threshold still `null` (**DA CONCORDARE**) → `UNRESOLVED`
* metric missing → `NO_DATA`
* otherwise → `PASS` / `FAIL`

Verdict: `FAIL` if any criterion fails; `HOLD` if any is unresolved/no-data;
`GO` **only** when every criterion is resolved and passes. A green light is
impossible while thresholds are unset — matching the roadmap rule that a gate
needs approved thresholds, frozen dataset and a formal `GO`.

## Usage

```powershell
python -m PlanParser.benchmark <prediction.json> <ground_truth.json> [--thresholds t.json] [--json]
```

Exit codes: `0` GO · `3` HOLD · `4` FAIL · `2` usage/load error.

```powershell
# fail-closed demo on the bundled fixtures (metrics computed, verdict HOLD)
python -m PlanParser.benchmark PlanParser/benchmark/tests/fixtures/pred.json PlanParser/benchmark/tests/fixtures/gt.json
```

As a library:

```python
from PlanParser.benchmark import evaluate, load, evaluate_gate, load_config
report  = evaluate(load("pred.json"), load("gt.json"))
verdict = evaluate_gate(report, load_config("PlanParser/benchmark/thresholds.example.json"))
```

## Thresholds

`thresholds.example.json` mirrors the Gate-1 acceptance rows. Every value is
`null` (DA CONCORDARE) except the fixed `P1-09 zero-orphans == 0`. The product
owner and reviewers must resolve the nulls before a `GO` is possible; do **not**
invent thresholds to force a green gate.

## Tests

```powershell
python -m unittest discover -s PlanParser/benchmark/tests -p "test_*.py" -v
```

28 tests: geometry (bbox/polygon IoU, point-in-polygon, area), text (Levenshtein,
CER, WER), calibration (ECE, Brier, abstention), the full evaluator on fixtures
(exact TP/FP/FN, OCR, measurements, relationships, abstention handling), the
fail-closed gate (HOLD / GO / FAIL / NO_DATA), and a ground-truth-vs-itself
perfect-score check.

## Dependencies

Python 3.9+ standard library only. Polygon IoU is computed by deterministic
rasterization (no shapely/numpy), so non-convex room polygons are handled and the
evaluator runs in any environment.

## Boundaries with the decomposer (other agent)

The decomposer (`PlanParser/decompose.py`, `decomposition/**`) and Data Factory
(`dataset/**`, `labeling/**`) are owned separately. Full JSON-Schema validation of
inputs is `decomposition/validator.py`'s job and should run before evaluation;
this module does defensive light checks only. If the decomposition contract
changes, this evaluator is updated to match.
