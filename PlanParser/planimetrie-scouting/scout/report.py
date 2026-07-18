"""Aggregazione dei risultati dei probe in results.json e REPORT.md."""
from __future__ import annotations

import json
from pathlib import Path

from .core import OUTPUT_DIR, ProbeResult

_YIELD_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3, "": 4}


def write_report(results: list[ProbeResult]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = [r.to_dict() for r in results]
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = sorted(results, key=lambda r: (_YIELD_ORDER.get(r.yield_estimate, 4), -r.plan_documents_found))
    lines = [
        "# Ricognizione portali planimetrie — verdetto",
        "",
        "| Fonte | Categoria | Raggiungibile | Doc. piano | Formati | Accesso | Programmatico | Resa | Bucket legale |",
        "|---|---|---|---:|---|---|---|---|---|",
    ]
    for r in rows:
        reach = "si" if r.reachable else ("BLOCCATO" if r.blocked_by_protection else "NO")
        lines.append(
            f"| {r.source_name} | {r.category} | {reach} | {r.plan_documents_found} | "
            f"{', '.join(r.formats) or '-'} | {r.access_method or '-'} | {r.programmatic or '-'} | "
            f"{r.yield_estimate or '-'} | {r.legal_bucket} |"
        )
    lines.append("")
    for r in rows:
        lines.append(f"## {r.source_name} (`{r.source_id}`)")
        lines.append(f"richieste effettuate: {r.requests_made}")
        for n in r.notes:
            lines.append(f"- {n}")
        for e in r.errors:
            lines.append(f"- ERRORE: {e}")
        for d in r.sample_documents[:5]:
            lines.append(f"- campione: {d.url} ({d.content_type}, {d.size_bytes} B) {d.note}")
        lines.append("")
    path = OUTPUT_DIR / "REPORT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
