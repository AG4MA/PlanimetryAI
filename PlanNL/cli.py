"""
PlanNL command-line interface.

Examples
--------
    # single question
    python -m PlanNL path/to/knowledge_model.json "quante stanze ci sono?"

    # interactive REPL
    python -m PlanNL path/to/knowledge_model.json

    # run against the bundled sample output
    python -m PlanNL --demo "elenca le stanze"

    # machine-readable answer
    python -m PlanNL km.json "area totale" --json

    # optional LLM fallback (needs ANTHROPIC_API_KEY + `pip install anthropic`)
    python -m PlanNL km.json "quali stanze danno sul cortile?" --llm
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __doc__ as _pkg_doc
from .knowledge import load
from .query import answer, SUPPORTED

# Bundled sample produced by the parser (read-only; owned by PlanParser).
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO_KM = os.path.normpath(
    os.path.join(_HERE, "..", "PlanParser", "testV1", "output", "knowledge_model.json")
)


def _resolve_path(args) -> str:
    if args.demo:
        if not os.path.exists(_DEMO_KM):
            print(f"[PlanNL] campione demo non trovato: {_DEMO_KM}", file=sys.stderr)
            sys.exit(2)
        return _DEMO_KM
    if not args.knowledge_model:
        print("[PlanNL] specifica un knowledge_model.json oppure usa --demo.", file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(args.knowledge_model):
        print(f"[PlanNL] file non trovato: {args.knowledge_model}", file=sys.stderr)
        sys.exit(2)
    return args.knowledge_model


def _emit(ans, as_json: bool) -> None:
    if as_json:
        print(json.dumps(
            {
                "intent": ans.intent,
                "available": ans.available,
                "text": ans.text,
                "data": ans.data,
                "citations": ans.citations,
            },
            ensure_ascii=False,
        ))
    else:
        print(ans.format())


def _answer_one(building, question, use_llm, as_json) -> None:
    if use_llm:
        from . import llm
        try:
            text = llm.answer_with_llm(building, question)
            if as_json:
                print(json.dumps({"intent": "llm", "text": text}, ensure_ascii=False))
            else:
                print(text)
            return
        except llm.LLMUnavailable as exc:
            print(f"[PlanNL] LLM non disponibile ({exc}) -> uso il motore rule-based.", file=sys.stderr)
    _emit(answer(building, question), as_json)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="PlanNL",
        description="Interroga in linguaggio naturale il Knowledge Model di PlanimetryAI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Domande supportate (rule-based):\n" + "\n".join(f"  - {s}" for s in SUPPORTED),
    )
    parser.add_argument("knowledge_model", nargs="?", help="percorso di knowledge_model.json")
    parser.add_argument("question", nargs="?", help="domanda; se assente parte la REPL")
    parser.add_argument("--demo", action="store_true", help="usa il campione bundled di PlanParser")
    parser.add_argument("--json", dest="as_json", action="store_true", help="output JSON")
    parser.add_argument("--llm", action="store_true", help="fallback LLM (opzionale, offline di default)")
    args = parser.parse_args(argv)

    # With --demo the model path is implicit, so a lone positional is the question.
    if args.demo and args.question is None and args.knowledge_model is not None:
        args.question = args.knowledge_model
        args.knowledge_model = None

    path = _resolve_path(args)
    try:
        building = load(path)
    except Exception as exc:
        print(f"[PlanNL] impossibile caricare il Knowledge Model: {exc}", file=sys.stderr)
        return 1

    if not args.as_json:
        metric = "con aree in m2" if building.has_metric_area else "aree solo in pixel (scala non impostata)"
        print(f"[PlanNL] caricate {len(building.rooms)} stanze da {os.path.basename(path)} ({metric}).")

    if args.question:
        _answer_one(building, args.question, args.llm, args.as_json)
        return 0

    # Interactive REPL
    print("[PlanNL] modalita interattiva. Scrivi una domanda ('?' per l'elenco, 'exit' per uscire).")
    while True:
        try:
            q = input("planNL> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", ":q"}:
            break
        if q == "?":
            print("\n".join(f"  - {s}" for s in SUPPORTED))
            continue
        _answer_one(building, q, args.llm, args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
