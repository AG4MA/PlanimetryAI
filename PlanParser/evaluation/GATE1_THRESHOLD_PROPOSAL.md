# Proposta iniziale soglie Gate 1

> **PROPOSTA DA VALIDARE — NON APPROVATA.**
>
> Questi numeri sono una baseline di discussione per il pilot. Non autorizzano `GO GATE 1`, non sostituiscono lo studio statistico e non possono essere modificati dopo l'apertura del `test`. L'approvazione spetta ai responsabili indicati in `docs/ACCEPTANCE_CRITERIA.md`.

## 1. Regola di decisione proposta

- Applicare le definizioni di `METRICS_SPEC.md` e congelarne versione/codice prima del test.
- Per metriche “alto è meglio”, il limite inferiore del CI 95% cluster-bootstrap deve superare la soglia.
- Per errori “basso è meglio”, il limite superiore del CI 95% deve essere sotto soglia.
- Veto e requisiti 100% richiedono il valore osservato indicato, non solo il CI.
- Tutte le classi obbligatorie e i sottogruppi supportati devono avere supporto sufficiente; altrimenti `INSUFFICIENT_EVIDENCE`.
- Nessuna compensazione fra righe: il Gate 1 passa soltanto se passano tutte le soglie approvate e non esiste alcun difetto critico.

## 2. Soglie candidate

Tutte le soglie della tabella sono **PROPOSTA DA VALIDARE**.

| Famiglia | Metrica | Soglia iniziale proposta | Razionale da verificare |
|---|---|---:|---|
| Ingestione supportata | success rate e page-count/order accuracy | 100% osservato | Il fallimento rende impossibile valutare il resto. |
| Input invalido/OOD | controlled rejection, zero crash/hang | 100%; 0 eventi | Fail-closed di base. |
| Pagine/tavole/piani | macro-classe F1 | ≥0,98 | Una regione/piano perso propaga errori a molte entità. |
| Regioni sorgente | per-class precision e recall | ≥0,97 ciascuna | Target alto ma da calibrare su classi piccole/ambigue. |
| Regioni sorgente | IoU mediana / P5 | ≥0,98 / ≥0,90 | Separare qualità tipica dalla coda. |
| Primitive geometriche | macro-classe F1 | ≥0,97 | Base percettiva per candidati architettonici. |
| Linee/polyline | Chamfer normalizzata P95 | ≤0,002 diagonale pagina | Circa 2 px ogni 1000 px; indipendente dalla risoluzione. |
| Linee/polyline | overlap longitudinale P5 | ≥0,95 | Evita segmenti corretti solo localmente. |
| Regioni geometriche | IoU mediana / P5 | ≥0,97 / ≥0,88 | La coda resta esplicita; da validare per retini/forme sottili. |
| `room_region` | precision e recall per classe | ≥0,98 / ≥0,99 | Una stanza mancante è più grave di una proposta spuria. |
| `room_region` | IoU mediana / P5 | ≥0,98 / ≥0,92 | Necessario per misure successive, ma ancora P1 candidate. |
| Pareti (`wall_*`) | precision e recall per classe | ≥0,98 ciascuna | Errori di parete alterano stanze/aperture. |
| Pareti | boundary F-score / Hausdorff95 norm. | ≥0,97 / ≤0,003 | Controlla bordo oltre all'IoU. |
| Aperture (`door/window/passage`) | precision e recall per classe | ≥0,97 / ≥0,98 | Recall leggermente privilegiato per non perdere connessioni. |
| Aperture | localization P95 / width rel. P95 | ≤0,005 diagonale / ≤5% | Da correlare con risoluzione e ground truth. |
| Text region detection | precision e recall | ≥0,99 / ≥0,99 | OCR non può riuscire su regioni perse o spurie. |
| OCR generale | CER micro / macro-blocco | ≤1,0% / ≤2,0% | Baseline severa per tavole tecniche. |
| OCR tecnico | exact accuracy quote/scala/livelli | ≥99,5% | Un singolo carattere può cambiare una misura. |
| OCR | hallucinated-text rate | ≤0,1% | Quasi-zero; gli eventi critici restano veto manuale. |
| Scala | detection precision/recall | ≥0,995 ciascuna | Scala errata propaga errore metrico globale. |
| Scala | exact ratio / errore fattore P95 | ≥99,5% / ≤0,5% | Da verificare su scale testuali e grafiche. |
| Orientamento | detection precision/recall | ≥0,99 ciascuna | Include corretta assenza quando non osservabile. |
| Orientamento | errore angolare mediana / P95 | ≤0,5° / ≤2° | Target iniziale per simboli leggibili. |
| Relazioni | per-type precision e recall | ≥0,97 ciascuna | Nessun tipo obbligatorio può essere nascosto dal micro. |
| Relazioni | micro/macro F1 | ≥0,98 / ≥0,97 | Bilancia volume e classi rare. |
| Calibrazione | ECE per famiglia / Brier | ≤0,03 / ≤0,05 | Richiede controllo con reliability plot e supporto. |
| Selective prediction | selective error al coverage target | ≤1% a coverage ≥95% | Impedisce pass ottenuto astenendosi troppo. |
| Astensione casi insufficienti | precision / recall | ≥0,95 / ≥0,98 | Privilegia intercettare casi non affidabili. |
| False abstention casi chiari | rate | ≤2% | Preserva utilità/copertura. |
| OOD | AUROC / AUPRC | ≥0,98 / ≥0,95 | AUPRC obbligatoria per prevalenze realistiche. |
| OOD | FPR@95TPR | ≤5% | Cutoff operativo interpretabile. |
| OOD | false-supported rate | ≤1% | OOD erroneamente dichiarato supportato. |
| Lineage | evidence/provenance/hash resolvibili | 100% | Bloccante, non mediabile. |
| Integrità | ID/riferimenti/bounds/split violations | 0 | Bloccante. |
| Riproducibilità | semantic determinism rate | 100% | A parità di input/config/ambiente dichiarato. |
| Ground truth | senior/pro review richiesta | 100% | Vincolo del freeze. |
| Manualità | correzioni geometriche ordinarie sul test | 0 | Vincolo dell'obiettivo automatico. |

## 3. Veto critici proposti

**PROPOSTA DA VALIDARE:** un solo evento confermato delle categorie seguenti produce `FAIL`, anche se tutte le soglie numeriche passano:

- sorgente/pagina errata, leakage o test contaminato;
- scala, quota, orientamento o testo tecnico inventato senza evidenza;
- stanza/parete/apertura mancante o spuria che il revisore classifica come capace di cambiare misure/topologia downstream;
- OOD presentato come decomposizione completa affidabile;
- lineage/hash non risolvibile, ID orfano o geometria fuori pagina;
- crash/hang non controllato;
- modifica evaluator/soglia dopo un risultato del test;
- intervento geometrico manuale ordinario sul caso di test.

Il pilot deve produrre esempi positivi/negativi per rendere ripetibile la classificazione della severità, evitando un veto puramente soggettivo.

## 4. Supporto minimo proposto

**PROPOSTA DA VALIDARE:** prima del test definitivo:

- almeno 30 `leakage_group_id` indipendenti complessivi nel `test` per bootstrap preliminare; aumentare dopo power analysis;
- almeno 100 istanze per classe obbligatoria comune;
- almeno 30 istanze per classe rara, con intervalli binomiali esatti e review completa;
- almeno 10 leakage group per ogni sottogruppo dichiarato supportato;
- almeno 50 casi OOD per categoria principale e un corpus negativo realistico;
- doppia annotazione su almeno 20% delle pagine e 100% dei casi rari/ambigui, coerente con il pilot labeling.

Questi minimi non garantiscono potenza sufficiente per soglie vicine al 99%. Se il limite CI non può dimostrare il target, occorre ampliare il dataset, non abbassare la soglia dopo aver visto il test.

## 5. Piano di calibrazione sul pilot

### Passo A — Qualificare ground truth ed evaluator

1. misurare agreement e adjudication per classe/geometria;
2. creare fixture di matching per duplicati, split/merge, class confusion e casi limite;
3. verificare che due implementazioni/review indipendenti producano gli stessi conteggi;
4. congelare guideline, taxonomy, manifest contract e evaluator version.

### Passo B — Usare soltanto `train` e `validation`

1. stimare prevalenza, difficulty e distribuzione errori per classe/sottogruppo;
2. fissare soglie di matching senza ottimizzarle sul `test`;
3. calibrare confidence per famiglia/classe e cutoff astensione/OOD;
4. costruire curve precision-recall, reliability e risk-coverage;
5. stimare numerosità necessaria affinché il CI possa discriminare le soglie candidate;
6. eseguire stress test e paired comparison delle baseline.

### Passo C — Riesame delle soglie proposte

Per ogni riga, il board documenta:

- rischio downstream dell'errore;
- qualità/accordo della ground truth;
- prevalenza e supporto;
- baseline e best-achievable su `validation`;
- costo di falso positivo, falso negativo e astensione;
- soglia finale, approvatore e motivazione.

Soglie irrealistiche non vengono abbassate solo per far passare il modello: si può restringere esplicitamente il dominio supportato prima del freeze oppure migliorare dati/modello.

### Passo D — Pre-registrazione e test cieco

1. congelare manifest, `test`, evaluator, soglie, cutoff, seed e piano analisi;
2. firmare/hashare il pacchetto di pre-registrazione;
3. eseguire una sola valutazione automatica sul `test`;
4. svolgere review dei difetti critici senza correggere predizioni/ground truth in-place;
5. emettere `PASS`, `FAIL` o `INSUFFICIENT_EVIDENCE` per ogni requisito e la delibera `GO|HOLD|ROLLBACK|STOP`.

Qualunque uso degli errori del `test` avvia una nuova release dataset e richiede un nuovo acceptance set indipendente.

## 6. Decisioni richieste prima dell'approvazione

- dominio preciso supportato e sottogruppi obbligatori;
- classi obbligatorie vs diagnostiche della tassonomia;
- criteri ripetibili di severità critica;
- supporto/power analysis e metodo CI definitivo;
- soglie di matching per famiglia;
- target coverage per selective prediction;
- cutoff e mix realistico OOD;
- approvatori e procedura formale del Gate 1.
