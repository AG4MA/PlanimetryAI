# PlanNL

Natural-language querying over the PlanimetryAI **Knowledge Model** — the third
pillar of the suite. PlanNL is a *consumer* of PlanParser's output (same contract
as Plan2HVAC): you point it at a `knowledge_model.json` and ask questions about
the plan in Italian or English.

It is **deterministic and offline by default**: questions are matched against a
closed set of intents and answered *only* from the loaded data. When the data
needed for an answer is missing (no scale, no wall classification, topology not
aligned to room ids), PlanNL says **"dato non disponibile"** and explains what is
missing — it never invents geometry. An optional LLM fallback exists but is off
unless explicitly enabled.

## Usage

```powershell
# a single question against a produced Knowledge Model
python -m PlanNL parser_output/knowledge_model.json "quante stanze ci sono?"

# interactive REPL (no question argument)
python -m PlanNL parser_output/knowledge_model.json

# run against the bundled parser sample (PlanParser/testV1/output)
python -m PlanNL --demo "elenca le stanze"

# machine-readable output
python -m PlanNL km.json "area totale" --json
```

No third-party dependencies — Python 3.9+ standard library only.

### As a library

```python
from PlanNL import load, answer
building = load("knowledge_model.json")
print(answer(building, "qual e la stanza piu grande?").format())
```

## Supported questions (rule-based)

| Intent | Examples | Needs |
|--------|----------|-------|
| `count_rooms` | "quante stanze ci sono?", "how many rooms?" | — |
| `list_rooms` | "elenca le stanze", "which rooms are there?" | — |
| `area_of_room` | "quanto e grande la cucina?", "area of the kitchen" | polygon/area |
| `extreme_room` | "stanza piu grande / piu piccola?" | area |
| `total_area` | "qual e l'area totale?" | **scale set** |
| `rooms_of_type` | "quanti bagni ci sono?", "le camere" | room labels |
| `adjacency` | "cosa confina con il bagno?" | **topology aligned to room ids** |
| `orientation` | "quali stanze sono esposte a sud?" | **walls + north** (not yet produced) |
| `scale` | "che scala ha la planimetria?" | — |

Every answer includes the room ids / fields it derives from.

## Data contract

PlanNL reads the Knowledge Model tolerantly, accepting both shapes seen in the
repo while the canonical schema is being frozen in
`PlanimetryDigitalConventions/`:

* flat parser output — `{"meta": {...}, "rooms": [...], "topology": {"adjacency": {...}}}`
* nested/HVAC form — `{"source": {...}, "floors": [{"rooms": [...]}], ...}`

Areas: a room may carry `area_m2` (used as-is) or `area_px`. Pixel areas are
converted to m² **only** when `scale_factor` (metres per pixel) is present;
otherwise the metric area is reported as unavailable. When the canonical schema
is frozen, this loader will converge onto it.

## Optional LLM fallback

`python -m PlanNL km.json "domanda libera" --llm` uses Claude for free-form
questions, but only if `ANTHROPIC_API_KEY` is set and `pip install anthropic` is
available. The model is constrained to answer solely from the Knowledge Model and
to reply "dato non disponibile" otherwise. Without a key it transparently falls
back to the rule-based engine.

## Tests

```powershell
python -m unittest discover -s PlanNL/tests -p "test_*.py" -v
```

Tests live under `PlanNL/tests/` (not the shared `tests/`) to avoid overlapping
with other agents' work.

## Known limitations

* Answer quality depends on the parser's OCR labels and geometry; garbage labels
  in, garbage matches out.
* `orientation` and metric `total_area` require data PlanParser does not yet
  emit reliably (wall classification, north, scale) — surfaced honestly rather
  than guessed.
* `adjacency` needs `topology.adjacency` keyed by real room ids; the current
  sample keys it by candidate indices, so PlanNL reports it unavailable there.
