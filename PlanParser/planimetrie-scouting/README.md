# planimetrie-scouting

Due fasi:

1. **`scout/`** — ricognizione *estensiva ma non massiva* di 18 portali, un probe per fonte,
   per capire quali danno davvero planimetrie. Esito in [FINDINGS.md](FINDINGS.md).
2. **`harvest/`** — raccolta *massiva* dalle fonti risultate verdi (aste giudiziarie:
   AsteAnnunci, AsteGiudiziarie), con manifest resumable e dedup SHA-256.

Basato su `PlanimetryAI/PlanParser/deep-research-report.md`. Questo progetto è
**separato** dal repo PlanimetryAI (attualmente in stato PAUSED di governance).

## Harvest massivo

```powershell
$env:PYTHONPATH='c:\projects\planimetrie-scouting'
python -m harvest --site asteannunci,astegiudiziarie --delay 1.5
# resumable: rilanciando riparte dallo stato salvato e salta i doc gia' presenti
```

Output in `harvest_output/<site>/`: `manifest.jsonl` (un record per documento, con
provenienza), `docs/<aa>/<sha256>.<ext>` (i documenti, deduplicati), `state.json` (ripresa).

Regole harvest: `session.get` con robots + ritardo + retry; nessuna elusione di blocchi
anti-bot (403/429/WAF fermano il dominio); provenienza tracciata; uso analitico interno,
niente ripubblicazione dei documenti originali.

Stato adapter: AsteAnnunci 🟢, AsteGiudiziarie 🟢, PVP 🔴 (WAF, adapter presente ma non eseguibile).

## Regole di ingaggio (non negoziabili)

- budget per probe: ~10-12 richieste HTTP totali, ritardo >= 1.5s fra richieste;
- `robots.txt` rispettato; nessuna elusione di blocchi anti-bot: un 403/429/challenge
  è un **esito da registrare**, non un ostacolo da aggirare;
- nessun login, nessun captcha, User-Agent dichiarato e con contatto;
- al massimo 2-3 documenti campione scaricati per fonte (< 5 MB l'uno);
- harvest per uso analitico interno: nessuna ripubblicazione dei documenti originali.

## Uso

```powershell
# tutti i probe
python -m scout

# solo alcuni
python -m scout --only pvp_giustizia,fallco

# budget richieste per probe
python -m scout --max-requests 8
```

Output in `output/`: un `result.json` per probe, più `results.json` e `REPORT.md` aggregati.

## Struttura

- `scout/core.py` — sessione HTTP educata (budget, delay, robots), dataclass risultato;
- `scout/probes/*.py` — un probe per fonte, interfaccia `probe(session) -> ProbeResult`;
- `scout/report.py` — aggregazione in `results.json` + `REPORT.md`;
- `scout/__main__.py` — CLI.

## Bucket legali (dal report)

| Bucket | Significato |
|---|---|
| `open_ccby` | dati aperti con licenza esplicita (es. CC BY 4.0) |
| `public_document_internal_use` | documenti pubblicamente scaricabili, uso interno, no ripubblicazione |
| `rights_gated` | riservato ad aventi diritto/delegati (es. planimetrie Catasto) |
| `tos_risk` | pubblicamente visibile ma ToS/copyright ostili al riuso |
| `unclear` | da chiarire |
