# PlanimetryAI

PlanimetryAI è un ecosistema di quattro prodotti indipendenti che lavorano sulle planimetrie senza condividere responsabilità o nascondere gli errori l'uno dell'altro.

## I quattro prodotti

```text
PDF / immagini
      │
      ▼
PlanParser
  sorgente → scomposizione → formalizzazione controllabile
      │ contratto pubblico versionato
      ├──────────────────────┐
      ▼                      ▼
PlanNL                  Plan2HVAC
domande → risposte      formalizzazione → progetto HVAC in scala

PlanimetryDigitalConventions
prodotto futuro: visione e convenzioni dei futuri documenti planimetrici
```

- **PlanParser** riceve soltanto PDF e immagini e possiede l'intero percorso fino alla formalizzazione. Scomposizione e formalizzazione sono due sistemi interni distinti e sequenziali.
- **PlanNL** consuma la formalizzazione per rispondere a domande. Non inventa dati e non modifica la planimetria.
- **Plan2HVAC** consuma la stessa formalizzazione e crea un progetto tecnico separato, tracciabile e in scala esatta sopra la base.
- **PlanimetryDigitalConventions** dichiarerà in futuro come dovranno essere le planimetrie e i documenti che ne parlano. Non è il contratto runtime corrente, non è P2 ed è fuori dallo scope operativo attuale.

Ogni prodotto è un super-servizio con API, contratti, test, release ed errori propri. Sono vietati accoppiamento agli interni e database condivisi come canale di integrazione.

## Sequenza vincolante

1. **PlanParser/P1 — Scomporre:** osservare e separare perfettamente regioni, primitive, testi, simboli, elementi architettonici candidati, misure e relazioni, sempre con evidenza sulla sorgente.
2. **PlanParser/P2 — Formalizzare e controllare:** trasformare la scomposizione in una planimetria digitale precisa e governabile.
3. **Consumer indipendenti:** PlanNL risponde; Plan2HVAC scrive un layer HVAC in scala senza alterare la formalizzazione.

Si apre un punto soltanto dopo il `GO` misurabile del gate precedente. Lo stato corrente è:

`PLANPARSER/P1 ATTIVO` — `PLANPARSER/P2 BLOCCATO DAL GATE 1` — `PLANNL E PLAN2HVAC BLOCCATI DAL GATE 2` — `PLANIMETRYDIGITALCONVENTIONS FUTURO`

## Workflow attivo: PlanParser/P1

Installazione:

```powershell
python -m pip install -r requirements.txt
```

Scomposizione di un PDF o di un'immagine:

```powershell
python -m PlanParser.decompose PlanParser/data/scheda_catastale.pdf --output decomposition.json
```

L'output attuale è un contratto intermedio di scomposizione con coordinate pagina, provenienza, confidenza e riferimenti all'evidenza. Rimane interno al percorso di PlanParser e non è ancora la formalizzazione pubblica consumabile da PlanNL o Plan2HVAC.

Test del solo Punto 1:

```powershell
python -m unittest discover -s tests -p "test_decom*.py" -v
python -m unittest tests.test_dataset_manifest -v
```

Validazione forte di una release dataset:

```powershell
python -m PlanParser.dataset path\to\dataset-manifest.json --verify-files
```

## Componenti P1 attivi

- `PlanParser/decomposition/`: tassonomia, schema intermedio, validator ed exporter atomico.
- `PlanParser/labeling/`: linee guida, review, QA e composizione minima del corpus.
- `PlanParser/dataset/`: manifest, diritti, privacy, split, freeze e anti-leakage.

`PlanNL/`, `Plan2HVAC/` e `PlanimetryDigitalConventions/` sono conservati ma non fanno parte del lavoro operativo corrente.

## Stato onesto

L'infrastruttura iniziale P1 è eseguibile, ma il Gate 1 è `HOLD`: sui tre PDF disponibili il parser produce output strutturalmente valido, però non ricostruisce ancora stanze e topologia in modo affidabile e l'OCR non è operativo nell'ambiente corrente. La validità del JSON non viene trattata come prova di comprensione.

Lo stato dettagliato è in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md); l'obiettivo approvato in [docs/PROJECT_OBJECTIVE.md](docs/PROJECT_OBJECTIVE.md); i criteri dei gate in [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md).

## Collaborazione

Il team operativo contiene due soli agenti. I claim esclusivi sono regolati da [COLLAB_RULES.md](COLLAB_RULES.md) e ogni messaggio/handoff asincrono è registrato in [ASYNC_LOG.md](ASYNC_LOG.md).
