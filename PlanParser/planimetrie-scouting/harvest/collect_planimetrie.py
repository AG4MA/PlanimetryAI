"""Consolida TUTTE le planimetrie in un'unica cartella piatta e cancella il resto.

- copia ogni planimetria (doc_type planimetria/elaborato_planimetrico) dai docs/
  shardati di ogni sito in harvest_output/PLANIMETRIE/ con nome leggibile;
- scrive harvest_output/PLANIMETRIE/INDEX.csv con la provenienza;
- riscrive i manifest tenendo SOLO le planimetrie (con il nuovo nome file);
- CANCELLA le cartelle docs/ shardate (via perizie, tavole e i file sparsi).

Rieseguibile: rilanciandolo dopo altri harvest ricolloca le nuove planimetrie e
ripulisce di nuovo. Uso:  python -m harvest.collect_planimetrie
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from .core import HARVEST_ROOT, PLANIMETRIE_DIR, WANTED_TYPES, safe_name

SITES = ("asteannunci", "astegiudiziarie", "pvp_giustizia")
INDEX_FIELDS = ["file_name", "site", "comune", "listing_id", "doc_type",
                "format", "sha256", "doc_url", "listing_url"]


def collect() -> None:
    PLANIMETRIE_DIR.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict] = []
    per_site: dict[str, int] = {}
    deleted_non_plan = 0

    for site in SITES:
        sdir = HARVEST_ROOT / site
        man = sdir / "manifest.jsonl"
        if not man.exists():
            continue
        kept: list[dict] = []
        for line in man.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("doc_type") not in WANTED_TYPES:
                deleted_non_plan += 1
                continue
            sha = rec["sha256"]
            ext = rec.get("format") or "bin"
            src = sdir / "docs" / sha[:2] / f"{sha}.{ext}"
            fname = f"{site}__{safe_name(rec.get('comune', '')) or 'na'}__{rec['listing_id']}__{sha[:8]}.{ext}"
            dst = PLANIMETRIE_DIR / fname
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
            rec["file_name"] = fname
            kept.append(rec)
            index_rows.append({
                "file_name": fname, "site": site, "comune": rec.get("comune", ""),
                "listing_id": rec.get("listing_id", ""), "doc_type": rec.get("doc_type", ""),
                "format": ext, "sha256": sha, "doc_url": rec.get("doc_url", ""),
                "listing_url": rec.get("listing_url", ""),
            })
        # manifest tenuto SOLO con le planimetrie
        man.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + ("\n" if kept else ""),
                       encoding="utf-8")
        per_site[site] = len(kept)
        # via le cartelle shardate (perizie + originali gia' copiati + file sparsi)
        docs = sdir / "docs"
        if docs.exists():
            shutil.rmtree(docs, ignore_errors=True)

    with (PLANIMETRIE_DIR / "INDEX.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
        w.writeheader()
        w.writerows(index_rows)

    total = len(index_rows)
    fmt: dict[str, int] = {}
    for r in index_rows:
        fmt[r["format"]] = fmt.get(r["format"], 0) + 1
    print(f"PLANIMETRIE consolidate in: {PLANIMETRIE_DIR}")
    for s, n in per_site.items():
        print(f"  {s}: {n} planimetrie")
    print(f"  TOTALE planimetrie: {total} · formati: {fmt}")
    print(f"  documenti NON-planimetria eliminati (perizie/tavole): {deleted_non_plan}")
    print(f"  indice: {PLANIMETRIE_DIR / 'INDEX.csv'}")


if __name__ == "__main__":
    collect()
