# Proposta minima di dataset — Punto 1

Questa è una baseline per avviare il pilot, non la dimensione sufficiente per Gate 1. Numeri e soglie finali devono essere approvati dopo uno studio di copertura e potenza statistica.

La fonte vincolante per nomi degli split, assegnazione, `leakage_group_id`, augmentation, diritti e congelamento è [`../dataset/DATASET_SPEC.md`](../dataset/DATASET_SPEC.md), insieme al manifest machine-readable della specifica release. Questo documento propone soltanto numerosità e copertura: non può ridefinire split o regole anti-leakage.

## 1. Unità di campionamento e split

L'unità primaria è il **progetto/edificio**, non la singola pagina. Tutte le pagine, revisioni, scansioni e derivati dello stesso progetto restano nello stesso split.

Split distinti:

- `train`: annotazione iterativa, training, augmentation e analisi errori;
- `validation`: scelta modelli e calibrazione;
- `test`: acceptance set cieco e congelato; vietati training, selezione attiva, tuning di soglie e modifica delle linee guida basata sui risultati specifici.

Deduplicare per hash esatto e similarità percettiva; registrare famiglie di derivati.

## 2. Pilot minimo proposto

| Blocco | Minimo proposto | Scopo |
|---|---:|---|
| Progetti/edifici `train` | 30 | Provare tassonomia, UI, QA, failure taxonomy e training. |
| Progetti/edifici `validation` | 10 | Prime metriche, scelta modelli e calibrazione, senza toccare `test`. |
| Progetti/edifici `test` cieco/congelato | 15 | Smoke benchmark di accettazione indipendente; non sufficiente da solo per claim “perfetto”. |
| Annotazione doppia | ≥20% pagine e 100% classi rare/ambigue | Stimare agreement e costo di adjudication. |
| Golden task | ≥2 esempi positivi + 1 negativo per classe obbligatoria | Onboarding e controllo ricorrente. |

La release Gate 1 richiederà dimensioni **DA CONCORDARE** sulla base della prevalenza delle classi, intervalli di confidenza e sottogruppi supportati.

## 3. Copertura obbligatoria

Stratificare e riportare almeno:

- input: PDF nativo, PDF rasterizzato, PNG/JPEG/TIFF/WebP;
- qualità: DPI/risoluzione, compressione, rumore, skew, rotazione, contrasto, scansioni e foto prospettiche se nel dominio;
- struttura: singola/multipagina, singolo/multipiano, cartigli, legende, tabelle e più riquadri;
- stile: epoca, convenzioni grafiche, spessori, retini, font e colore/monocromia;
- geometria: ortogonale e non ortogonale, curve, pareti sottili/spesse, ambienti irregolari;
- contenuti: tutte le classi obbligatorie della tassonomia, unknown e casi negativi;
- difficoltà: sovrastampe, occlusioni, crop, quote conflittuali e fuori distribuzione;
- provenienza: fonte/territorio/organizzazione senza permettere che una sola sorgente domini uno split.

Ogni sottogruppo dichiarato supportato deve avere numerosità minima **DA CONCORDARE** nel `test` di accettazione.

## 4. Ground truth e release

Per ogni asset:

- licenza/base d'uso, provenienza, privacy class e retention;
- hash sorgente, manifest pagine, parametri di rendering e versione tassonomia/linee guida;
- annotazioni e relazioni con storia completa;
- auto-QA superato;
- review senior accettata/modificata per ogni elemento congelato;
- adjudication professionale per i casi definiti dal piano QA;
- statistiche di classi, geometrie, unknown, relazioni e sottogruppi.

Una release è immutabile. Una correzione produce nuova versione e changelog; il benchmark conserva i risultati precedenti.

## 5. Criteri di ammissione al `test` di accettazione

- progetto mai usato in `train`, training, sorgenti di augmentation, `validation`, selezione attiva o scelta soglie;
- nessun duplicato/derivato presente negli altri split;
- diritti e privacy verificati;
- copertura utile a uno o più sottogruppi dichiarati;
- ground truth completa secondo la tassonomia applicabile;
- disaccordi risolti e audit trail integro.

## 6. Criteri di esclusione o quarantena

- licenza/provenienza incerta;
- dati sensibili non trattabili secondo policy;
- corruzione che impedisce la lettura tecnica, salvo corpus negativo dedicato;
- versione/derivato di un progetto in altro split;
- conflitto irrisolto nella ground truth;
- classe necessaria ma non rappresentabile nella tassonomia: quarantena e proposta di change, non label forzata.

## 7. Report minimo del dataset

- versione, data freeze, owner, hash manifest e guideline/taxonomy version;
- conteggi per progetto, pagina, formato, sottogruppo, classe e relazione;
- distribuzione geometrie, unknown/abstention e severità difficoltà;
- agreement/rework/escalation e copertura review;
- matrice `train`/`validation`/`test` con attestazione anti-leakage prodotta dal manifest;
- limitazioni note e dominio esplicitamente non supportato.
