# PlanimetryAI — stato operativo

**Data:** 17 luglio 2026

**Stato vincolante:** `PLANPARSER/P1 ATTIVO` — `PLANPARSER/P2 BLOCCATO` — `CONSUMER BLOCCATI`

**Input ammessi:** PDF e immagini

**Modalità obiettivo:** automatica

**Qualità futura Plan2HVAC:** livello cantiere, dopo i gate di PlanParser e revisione professionale

## Architettura corretta: quattro prodotti

| Prodotto | Una responsabilità | Stato attuale |
|---|---|---|
| `PlanParser` | Sorgente PDF/immagine → scomposizione → formalizzazione controllabile | P1 attivo; P2 interno bloccato dal Gate 1 |
| `PlanNL` | Formalizzazione → risposte tracciabili alle domande | Bloccato dal Gate 2 di PlanParser |
| `Plan2HVAC` | Formalizzazione → progetto HVAC separato in scala esatta | Bloccato dal Gate 2 di PlanParser |
| `PlanimetryDigitalConventions` | Dichiarare il futuro delle planimetrie e dei documenti che ne parlano | Futuro; fuori scope operativo |

PlanimetryDigitalConventions non è il contratto operativo corrente e non è il sistema di formalizzazione P2. PlanNL e Plan2HVAC consumano il futuro contratto pubblico di PlanParser e non i suoi formati interni.

## Sequenza di maturità dentro e dopo PlanParser

1. **P1 — Scomporre:** PlanParser osserva e separa completamente gli elementi, mantenendo il collegamento alla sorgente.
2. **P2 — Formalizzare e controllare:** PlanParser trasforma la scomposizione in una planimetria digitale precisa, interrogabile, misurabile e governabile.
3. **Consumer indipendenti:** PlanNL risponde; Plan2HVAC scrive un layer tecnico in scala. Nessuno dei due modifica la formalizzazione.

Si apre un punto soltanto dopo il `GO` misurabile del gate precedente. I tre punti sono problemi molto grandi; non sono tre semplici funzioni e non coincidono uno-a-uno con i quattro prodotti.

## Gate

| Gate | Stato | Cosa abilita |
|---|---|---|
| Gate 1 — scomposizione PlanParser | **HOLD / ATTIVO** | Apertura del sistema interno di formalizzazione |
| Gate 2 — formalizzazione PlanParser | **BLOCCATO DAL GATE 1** | Contratto pubblico stabile per PlanNL e Plan2HVAC |
| Gate PlanNL | **BLOCCATO DAL GATE 2** | Risposte affidabili sul dominio supportato |
| Gate Plan2HVAC | **BLOCCATO DAL GATE 2** | Progetto HVAC validato; stato cantiere solo con approvazione prevista |
| PlanimetryDigitalConventions | **NON APPLICABILE ORA** | Prodotto futuro, senza gate operativo corrente |

## Stato reale di PlanParser/P1

### Completato come infrastruttura baseline

- tassonomia atomica versionata: 64 classi e 13 relazioni;
- contratto intermedio della scomposizione, interno a PlanParser e distinto dalla futura formalizzazione;
- provenienza, evidenza sorgente, confidenza, astensione e review;
- validator strutturale e semantico fail-closed;
- CLI PDF/immagine → `decomposition.json`;
- manuale di labeling, casi ambigui, QA, consensus e freeze;
- manifest dataset con diritti, privacy, split deterministici e controlli anti-leakage;
- baseline eseguita sui tre PDF disponibili.

### Evidenza attuale

- test del contratto e dell'exporter P1: **8/8 superati**;
- test del manifest dataset: **9/9 superati**;
- i tre PDF del repository producono JSON strutturalmente validi;
- accuratezza percettiva non ancora sufficiente: OCR operativo assente, zero stanze affidabili, topologia non ricostruita e confidenze non calibrate.

**Delibera corrente Gate 1: `HOLD`.** La validità del file non viene confusa con la corretta comprensione della planimetria.

## Lavoro consentito adesso

Tutto il lavoro operativo resta dentro il sistema di scomposizione di PlanParser:

1. ottenere un corpus PDF/immagini autorizzato e rappresentativo;
2. produrre ground truth con il protocollo di labeling;
3. congelare split train/validation/test senza leakage;
4. implementare il valutatore per classe, geometria, OCR, relazioni, calibrazione e sottogruppi;
5. migliorare parser e modelli usando soltanto train/validation;
6. eseguire la valutazione finale sul test cieco e deliberare il Gate 1.

Non è autorizzato lavoro operativo su formalizzazione P2, PlanNL, Plan2HVAC o PlanimetryDigitalConventions.

## Regole di indipendenza

- Ogni prodotto ha API, release, test, errori e responsabilità propri.
- Nessun consumer importa gli interni di PlanParser o usa il suo database.
- PlanNL non inventa dati mancanti.
- Plan2HVAC non corregge la planimetria e salva il progetto tecnico come layer separato.
- Un fallimento upstream viene esposto; non viene nascosto downstream.

## Collaborazione senza sovrapposizioni

Il team operativo è composto da due soli agenti:

- `/root`: coordinamento, integrazione, parser, dataset e valutazione;
- `project_audit`: labeling, QA documentale e review indipendente dei deliverable assegnati.

Prima di modificare un file, ogni agente registra un `CLAIMED` in `ASYNC_LOG.md`. Al completamento registra `DONE` e `HANDOFF`, con file e verifiche. I claim non possono sovrapporsi. Le regole complete sono in `COLLAB_RULES.md`.

## Fonti di verità

1. `PROJECT_OBJECTIVE.md` — prodotti, responsabilità e sequenza approvati;
2. `PROJECT_STATUS.md` — stato corrente fail-closed;
3. `ACCEPTANCE_CRITERIA.md` — criteri misurabili dei gate;
4. `ATOMIC_ROADMAP.md` — lavoro ammesso nel punto attivo;
5. `COLLAB_RULES.md` — divisione tra i due agenti;
6. `ASYNC_LOG.md` — claim, messaggi e handoff asincroni.
