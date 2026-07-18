# Flywheel dati–modelli di PlanParser/P1

**Stato:** `PROPOSTA` — non approvata; soglie, strumenti e dimensionamenti `DA CONCORDARE`

**Ambito:** interno al Punto 1 (workstream 6 *Data Factory* e workstream 7 *Model Factory* di `../docs/ATOMIC_ROADMAP.md`). Non è un prodotto nuovo, non anticipa P2/P3 e non modifica alcun gate.

**Origine:** direttiva dell'utente del 2026-07-17. Questo documento rende operativi i passi 1–12 del "Flywheel dei dati e dei modelli" di `../docs/ATOMIC_VISION.md`.

**Documenti vincolanti a monte:** `DECOMPOSITION_SPEC.md`, `decomposition/taxonomy.v1.json`, `dataset/DATASET_SPEC.md`, `labeling/QA_WORKFLOW.md`, `labeling/ANNOTATION_GUIDELINES.md`, `evaluation/METRICS_SPEC.md`, `../docs/ACCEPTANCE_CRITERIA.md`. In caso di conflitto, prevalgono loro.

---

## 1. L'idea in una frase

Ogni planimetria elaborata rende il sistema più capace di elaborare la successiva: il modello corrente pre-etichetta, gli umani correggono, le correzioni diventano dataset, il dataset addestra un modello migliore, il modello migliore pre-etichetta meglio — e il costo umano per unità di verità scende a ogni giro.

```text
        ┌──────────────────────────────────────────────────────────┐
        │                                                          │
        ▼                                                          │
  S1 ACQUISIZIONE ──▶ S2 COMPRENSIONE ──▶ S3 LABELLING ──▶ S4 DATASET
   planimetrie          algoritmica         assistito        release
   autorizzate          (pre-label)         + QA umano       versionata
        ▲                    ▲                                     │
        │                    │                                     ▼
  S8 ACTIVE LEARNING ◀── S7 PROMOZIONE ◀── S6 VALUTAZIONE ◀── S5 TRAINING
   scelta prossimi        governata          benchmark          solo train
   casi da annotare       (mai auto)         congelato          + augmentation
```

Il ciclo S2→S3 è il cuore del volano: la qualità delle pre-label del giro *n* determina la velocità di labelling del giro *n+1*.

## 2. Gli otto stadi

| # | Stadio | Input | Output | Componente esistente | Regola fail-closed |
|---|---|---|---|---|---|
| S1 | Acquisizione | PDF/immagini con diritti | Asset registrati nel manifest con hash, licenza, privacy review, `leakage_group_id` | `dataset/` (manifest + validator) | Nessun asset senza diritti/privacy verificati entra nel ciclo |
| S2 | Comprensione algoritmica | Asset + modello/parser corrente | Pre-decomposizione conforme a `decomposition.schema.json`, con confidenza e astensione | `decompose.py` + `decomposition/` | La pre-label porta sempre versione modello/config; mai presentata come verità |
| S3 | Labelling assistito | Pre-decomposizione + tavola sorgente | Annotazioni corrette/validate secondo QA multilivello | `labeling/` (guidelines, QA, golden, consensus) | Nessuna pre-label diventa ground truth senza revisione umana indipendente (Legge 3) |
| S4 | Dataset release | Annotazioni approvate | Nuova release del manifest: split `grouped_deterministic`, fingerprint SHA-256 | `dataset/DATASET_SPEC.md` | Ogni giro = nuova release immutabile; mai mutare una release esistente |
| S5 | Training | Solo split `train` (+ augmentation governata) | Modello candidato nel model registry con lineage dati/config/seed | Model Factory (da costruire) | `validation`/`test` mai visti in training (Legge 1) |
| S6 | Valutazione | Modello candidato + `validation`; benchmark congelato solo per delibere | Report metriche per classe/sottogruppo | `evaluation/` (motore pairwise) + orchestratore batch | Soglia non fissata → verdetto `HOLD`, mai `GO` |
| S7 | Promozione | Report + delibera umana | Modello promosso a "corrente" per S2, con rollback disponibile | Model registry (da costruire) | Nessuna promozione automatica (Legge 2); regressione critica → rollback |
| S8 | Active learning | Confidenze, disaccordi, strati scoperti | Coda prioritaria dei prossimi asset da annotare | Da costruire su output S2+S6 | Seleziona SOLO dentro `train`/non-assegnato; mai dentro `validation`/`test` |

## 3. Le tre leggi del volano (invarianti non negoziabili)

1. **Il test congelato non entra mai nel volano.** Niente pre-label, niente active learning, niente scelta di soglie, niente correzione di linee guida basata sugli errori di `validation`/`test` congelati (già vincolante in `dataset/DATASET_SPEC.md`). Un giro che contamina il test invalida la release e riporta il benchmark a una nuova raccolta indipendente.
2. **Nessuna promozione automatica.** Un modello entra in S2 solo dopo benchmark su dataset congelato e delibera registrata con hash delle evidenze (già vincolante in `../docs/ATOMIC_ROADMAP.md`, rischi P1). Il volano accelera i dati, non salta i gate.
3. **Il modello non valida se stesso.** Una pre-label accettata senza intervento umano resta `machine_generated` e non è ground truth; solo la filiera QA di `labeling/QA_WORKFLOW.md` (doppia annotazione, golden task, consensus, revisione senior/professionale) produce `frozen_ground_truth`. Vietato il self-training su pseudo-label non revisionate.

## 4. Metriche del volano

Il volano è sano solo se queste curve migliorano giro dopo giro. Sono metriche di *processo*, distinte dalle metriche Gate 1 di `evaluation/METRICS_SPEC.md`.

| Metrica | Definizione | Direzione attesa |
|---|---|---|
| **Acceptance rate pre-label** | % osservazioni pre-etichettate accettate senza modifica dal reviewer, per classe | ↑ per giro |
| **Correction effort** | Tempo mediano di correzione per unità annotata (assistito vs da zero) | ↓ per giro |
| **Costo per unità di verità** | Costo totale QA / osservazioni promosse a ground truth | ↓ per giro |
| **IAA e golden accuracy** | Già definite in `labeling/QA_WORKFLOW.md` §6 | stabili o ↑ |
| **Delta modello per giro** | Variazione metriche su `validation` tra modello *n* e *n−1*, per classe e sottogruppo | ↑ senza regressioni critiche |
| **Copertura strati** | Asset annotati per strato/sottogruppo del manifest | nessuno strato abbandonato |
| **Resa active learning** | Guadagno metrico per asset annotato: batch scelti da S8 vs batch casuali | S8 > casuale, altrimenti S8 va rivisto |

Soglie e cadenza di misura: `DA CONCORDARE`.

## 5. Fasi di maturità

Il volano non parte "girato": parte fermo e si accende per gradi. Ogni passaggio di fase è una delibera registrata, non un fatto emergente.

| Fase | Nome | Come si lavora | Criterio di ingresso (proposto, `DA CONCORDARE`) |
|---|---|---|---|
| **M0** | Cold start | Labelling interamente manuale sul corpus pilota; le uscite del parser corrente si usano solo come diagnostica, non come pre-label | Corpus autorizzato + programma annotatori attivo |
| **M1** | Pre-label assistito | Le pre-decomposizioni entrano nella piattaforma come proposte correggibili | Acceptance rate su un campione pilota sopra soglia minima per le classi proposte; sotto soglia la classe resta manuale |
| **M2** | Active learning | S8 sceglie i prossimi asset (incertezza, disaccordo, strati scoperti, candidati OOD) | Almeno un giro M1 completo + resa S8 > selezione casuale su esperimento controllato |
| **M3** | Quasi-automazione | Campionamento a spot-check sulle classi ad alta affidabilità; QA pieno sulle altre | Confidenza calibrata (ECE sotto soglia) per le classi in spot-check + audit senza difetti critici |

Una classe può stare in fase diversa dalle altre (es. `wall` in M2 mentre `stair` resta in M0). La fase è per classe, non per sistema.

## 6. Anti-pattern vietati

- **Circolarità:** addestrare su pre-label non revisionate e poi misurare il modello su annotazioni derivate dalle stesse pre-label.
- **Anchoring bias:** l'annotatore accetta la pre-label perché è già lì. Contromisura obbligatoria da M1: golden task seminati con pre-label deliberatamente sbagliate; il tasso di correzione mancata è una metrica QA bloccante.
- **Reward hacking dell'acceptance rate:** ottimizzare il modello per "non essere corretto" invece che per essere giusto (es. astenersi sempre). L'acceptance rate si legge sempre insieme a coverage e astensione.
- **Leakage morbido:** usare errori visti su `validation` congelato per riscrivere linee guida o tassonomia dentro lo stesso ciclo di release. Ogni revisione di linee guida vale dalla release successiva.
- **Crescita cieca:** aumentare il volume annotato senza coprire gli strati; il volano che gira solo sulle tavole facili produce un modello che legge solo tavole facili.
- **Promozione per fretta:** saltare S6/S7 perché "il modello sembra meglio". Vietato dalla Legge 2.

## 7. Cosa esiste già e cosa manca

| Pezzo del volano | Stato |
|---|---|
| Contratto di decomposizione + tassonomia (S2) | Esiste, versionato |
| CLI parser PDF/immagine → decomposition.json (S2) | Esiste; accuratezza insufficiente (è il motivo per cui serve il volano) |
| Protocollo labeling/QA/golden/consensus (S3) | Esiste come specifica; piattaforma web da costruire |
| Manifest dataset, split anti-leakage, freeze (S4) | Esiste, con validator e test |
| Motore di valutazione pairwise (S6) | In completamento (owner `project_audit`) |
| Orchestratore batch/verdetto (S6) | Esiste come prototipo; collisione ownership in delibera presso `/root` |
| Pipeline training + model registry + rollback (S5, S7) | Da costruire |
| Selettore active learning (S8) | Da costruire |
| Piattaforma di labeling web (S3) | Da costruire |

## 8. Decisioni richieste al responsabile (`DA CONCORDARE`)

1. Soglie di ingresso M1/M2/M3 per classe e metrica di calibrazione ammessa per lo spot-check.
2. Stack e ownership della piattaforma di labeling web e del model registry.
3. Budget e cadenza dei giri (dimensione batch di annotazione per giro).
4. Composizione del corpus pilota M0 e priorità degli strati.
5. Owner dei nuovi componenti S5/S7/S8 (assegnazione agenti senza sovrapposizioni).
6. Politica di retention delle pre-label rifiutate (utili come hard negatives, ma vanno governate nel manifest).

---

*Questo documento è una proposta operativa interna a P1. Non dichiara completato alcun gate, non autorizza lavoro e non modifica i vincoli dei documenti a monte.*
