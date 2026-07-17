# Workflow QA e review

## 1. Ruoli

- `annotator`: produce o corregge annotazioni entro le classi per cui è abilitato.
- `senior_reviewer`: verifica geometria, tassonomia, relazioni, ambiguità e coerenza con le linee guida.
- `domain_professional`: decide casi con significato tecnico che superano le competenze del reviewer; non è richiesto per ogni primitiva semplice.
- Data QA lead: governa sampling, golden task, metriche, escalation e release; è un ruolo di workflow, non un valore `reviewer_role` nello schema.

Gli studenti partono come annotatori in formazione e non svolgono review professionale.

## 2. Stati del task nella piattaforma

Gli stati operativi non estendono il JSON di decomposizione:

`UNASSIGNED → IN_PROGRESS → SUBMITTED → AUTO_QA_FAILED | SENIOR_REVIEW → CHANGES_REQUESTED | ESCALATED | APPROVED`

- `CHANGES_REQUESTED` torna a `IN_PROGRESS` con motivazione.
- `ESCALATED` passa a un senior specializzato o professionista.
- `APPROVED` non equivale automaticamente a ground truth congelata.

Nel documento serializzato si usano soltanto:

- `dataset_status`: `draft`, `reviewed`, `frozen_ground_truth`;
- review decision: `accepted`, `rejected`, `modified`;
- reviewer role: `annotator`, `senior_reviewer`, `domain_professional`.

## 3. Pipeline di qualità

1. **Preflight:** hash sorgente, media type, pagine, DPI/rotazione e tassonomia verificati.
2. **Annotazione:** task atomico con istruzione, classi consentite e contesto sufficiente.
3. **Auto-QA:** bounds, geometria minima, ID, tassonomia, endpoint, attributi richiesti dal profilo e conflitti grossolani.
4. **Review umana:** ispezione cieca rispetto all'identità dell'annotatore quando possibile.
5. **Consensus:** doppia annotazione per task/casi campionati; divergenze oltre soglia vanno in adjudication.
6. **Adjudication:** senior; professionista per casi tecnici/semantici definiti.
7. **Release QA:** validatore, statistiche, leakage check, manifest e campionamento finale.
8. **Freeze:** snapshot immutabile, hash e changelog; correzioni successive generano una nuova versione.

L'assegnazione a `train`, `validation` o `test`, i gruppi di leakage e il freeze della release sono governati da [`../dataset/DATASET_SPEC.md`](../dataset/DATASET_SPEC.md) e dal relativo manifest machine-readable. Il workflow di labeling non può riassegnare asset o derogare ai controlli anti-leakage.

## 4. Regole di review

Il reviewer valuta separatamente:

- classe/layer;
- geometria e coordinate pagina;
- completezza dell'evidenza;
- attributi e trascrizione;
- relazioni e direzione;
- gestione di unknown/ambiguità;
- provenienza e storia.

`accepted`: nessuna modifica sostanziale.  
`modified`: il reviewer corregge e documenta cosa/perché.  
`rejected`: evidenza falsa, duplicata, fuori task o non recuperabile.

Una review non elimina quella precedente. Per `frozen_ground_truth`, ogni osservazione e relazione richiede almeno una decisione `accepted` o `modified` di senior/professionista, come previsto dal validator.

## 5. QA multilivello

- 100% auto-QA.
- 100% review senior durante pilot e onboarding.
- Dopo qualifica, sampling rate per classe/rischio: **DA CONCORDARE**; classi rare, unknown, inferenze parziali e conflitti restano al 100%.
- 100% casi tecnici definiti dal piano di escalation revisionati dal professionista.
- Golden task nascosti e ricorrenti; soglia di qualifica e sospensione: **DA CONCORDARE**.
- Inter-annotator agreement per classe e geometria; metrica/soglia: **DA CONCORDARE**.

Non ridurre il QA per raggiungere throughput o budget.

## 6. Metriche

- classificazione: precision/recall/F1 e confusion matrix;
- geometria: IoU per regioni, distanza/errore vertici o linee, completezza bordo;
- testo: CER/WER più accuratezza esatta sui valori tecnici;
- relazioni: precision/recall per tipo ed endpoint;
- workflow: acceptance senza modifica, rework, escalation, tempo per unità;
- qualità annotatore: golden accuracy e trend, mai ranking pubblico;
- dataset: copertura classi/sottogruppi, unknown/abstention rate, leakage e duplicati.

Le metriche individuali servono a formazione e controllo del processo, non a penalità automatiche o retribuzione a cottimo opaca.

## 7. Escalation obbligatoria

- conflitto fra scala e quote;
- simbolo con implicazione tecnica non coperto;
- parete/apertura non distinguibile per sovrastampa o occlusione;
- disaccordo persistente dopo secondo reviewer;
- sospetto dato personale o documento non autorizzato;
- errore nelle linee guida/tassonomia;
- possibile contaminazione del set di accettazione.

## 8. Tutela e privacy

- least privilege, accesso per task, download limitato e audit proporzionato;
- minimizzazione/pseudonimizzazione prima dell'assegnazione;
- minorenni esclusi da dati ad alto rischio o non adeguatamente trattati;
- compenso e condizioni dichiarati; PCTO non usato come produzione gratuita mascherata;
- canale di reclamo e ritiro senza ritorsioni;
- sospensione automatica in caso di incidente grave, dubbio di liceità o tutela insufficiente.
