"""
PlanParser P1 Benchmark & evaluator (roadmap workstream 8).

Measures a decomposition *prediction* against a *ground truth* (both conforming
to decomposition.schema.json) and produces the Gate-1 metrics + a fail-closed
verdict. Consumes only the published decomposition contract; owns no decomposer
internals.

    from PlanParser.benchmark import evaluate, load, evaluate_gate
    report = evaluate(load("pred.json"), load("gt.json"))
    verdict = evaluate_gate(report, load_config("thresholds.example.json"))
"""
from .loader import load, from_dict, Decomposition
from .evaluator import evaluate
from .gate import evaluate_gate, load_config

__all__ = [
    "load", "from_dict", "Decomposition",
    "evaluate", "evaluate_gate", "load_config",
]
