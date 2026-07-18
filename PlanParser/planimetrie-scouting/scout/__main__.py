"""CLI: esegue i probe registrati in scout/probes e scrive il report aggregato."""
from __future__ import annotations

import argparse
import importlib
import pkgutil
import traceback

from . import probes
from .core import PoliteSession, ProbeResult
from .report import write_report


def discover() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(probes.__path__))


def main() -> None:
    parser = argparse.ArgumentParser(prog="scout", description="Ricognizione educata dei portali con planimetrie")
    parser.add_argument("--only", help="probe da eseguire, separati da virgola (default: tutti)")
    parser.add_argument("--max-requests", type=int, default=10, help="budget richieste HTTP per probe")
    args = parser.parse_args()
    names = [n.strip() for n in args.only.split(",")] if args.only else discover()
    results: list[ProbeResult] = []
    for name in names:
        module = importlib.import_module(f"scout.probes.{name}")
        session = PoliteSession(max_requests=args.max_requests)
        try:
            result = module.probe(session)
        except Exception as exc:  # il fallimento di un probe non ferma la ricognizione
            result = ProbeResult(source_id=name, source_name=name, category="?", legal_bucket="unclear")
            result.errors.append(f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        result.requests_made = session.requests_made
        results.append(result)
        print(f"[{name}] richieste={session.requests_made} resa={result.yield_estimate or '?'}")
    report_path = write_report(results)
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
