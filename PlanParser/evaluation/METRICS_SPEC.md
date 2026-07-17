# Specifica metriche PlanParser/P1 — Gate 1

**Stato:** specifica operativa da implementare e validare sul pilot  
**Ambito:** soltanto scomposizione P1; non valuta formalizzazione P2 o consumer downstream  
**Fonti:** `../DECOMPOSITION_SPEC.md`, `../labeling/**`, `../dataset/DATASET_SPEC.md`, tassonomia e manifest della release

## 1. Principi non negoziabili

1. Il `test` è l'acceptance set cieco e congelato. Soglie, matching, metriche e codice di evaluation vengono congelati prima di aprirlo.
2. L'unità indipendente per inferenza statistica è il `leakage_group_id` (progetto/famiglia), non pagina, oggetto o pixel.
3. Si riportano sempre risultati per classe obbligatoria, layer e sottogruppo, oltre agli aggregati micro/macro.
4. Una metrica aggregata non compensa una classe, un sottogruppo o un requisito bloccante fallito.
5. `unknown_*`, astensione e rifiuto OOD sono risultati separati: non contano come true positive delle classi obbligatorie.
6. Predizioni invalide, fuori pagina, senza lineage o con riferimenti orfani sono errori; non vengono riparate dall'evaluator.
7. Il report conserva manifest fingerprint, taxonomy/guideline/evaluator/model/config version, seed e hash degli output.

## 2. Set, unità e denominatori

- `train`: sviluppo e training; mai usato per stime finali.
- `validation`: scelta modello, calibrazione confidence/OOD, definizione matching e proposta soglie.
- `test`: una sola valutazione finale per la delibera; riuso degli errori genera una nuova release con nuovo test indipendente.

Denominatori obbligatori:

- documenti e pagine per ingestione;
- istanze ground truth per detection/classificazione;
- caratteri/parole/blocchi per OCR;
- relazioni ground truth per grafi osservabili;
- `leakage_group_id` per intervalli di confidenza e paired comparison.

Assenze vere devono essere incluse nei test di falsi positivi. Classi senza supporto sufficiente non ricevono un punteggio “pass”: il dataset è insufficiente per il gate.

## 3. Matching comune

Il matching è uno-a-uno e deterministico per pagina e classe, tramite assegnazione bipartita a costo minimo/massimo score. È vietato il matching greedy dipendente dall'ordine.

Procedura:

1. scartare come false positive le predizioni strutturalmente invalide;
2. costruire coppie eleggibili con le regole geometriche della famiglia;
3. risolvere l'assegnazione uno-a-uno massimizzando lo score primario;
4. una coppia sotto la soglia di matching resta unmatched: FP + FN;
5. classificazione errata con localizzazione corretta produce FP della classe predetta e FN della classe vera;
6. calcolare la qualità geometrica soltanto sulle coppie matched, ma riportare detection e geometria insieme per impedire survivorship bias.

Soglie di matching fanno parte della versione dell'evaluator e vengono fissate su `validation`.

### 3.1 Regole per geometria

- regioni/poligoni/mask/bbox: IoU; eleggibile se IoU ≥ soglia per famiglia;
- linee/polyline/assi/facce: distanza Chamfer simmetrica normalizzata sulla diagonale pagina più overlap longitudinale; entrambi devono passare;
- point/marker: distanza euclidea normalizzata sulla diagonale;
- archi/circonferenze/ellissi: distanza del bordo campionato più errore di parametri quando annotati;
- testo/simboli: IoU della bbox/polygon per detection, poi contenuto/classe separatamente.

La rasterizzazione per IoU usa la risoluzione pagina nativa e regole di bordo versionate. Coordinate metriche derivate non sostituiscono le coordinate pixel P1.

## 4. Aggregazioni

Per ogni metrica di classificazione/detection:

- **micro:** sommare TP/FP/FN su tutte le istanze eleggibili e poi calcolare precision/recall/F1;
- **macro-classe:** media non pesata delle classi obbligatorie con supporto minimo;
- **macro-progetto:** calcolare per `leakage_group_id`, poi media non pesata;
- **per-layer:** micro e macro dentro ciascuno dei sei layer;
- **worst-group:** minimo sui sottogruppi con supporto sufficiente.

Il report mostra conteggi e intervalli, non solo percentuali. Per classi rare si pubblicano precision/recall con CI esatti e tutti gli errori; non si nascondono in un macro instabile.

## 5. Intervalli di confidenza e confronti

- CI predefinito: 95% cluster bootstrap, ricampionando `leakage_group_id` con 10.000 repliche e seed registrato.
- Proporzioni con pochi eventi: intervallo binomiale esatto/Clopper-Pearson come controllo conservativo.
- Errori continui: mediana, P90, P95 e CI bootstrap del progetto.
- Confronti fra modelli: paired cluster bootstrap sugli stessi leakage group; pubblicare differenza e CI.
- Se i cluster sono troppo pochi per CI stabile, l'esito è `INSUFFICIENT_EVIDENCE`, non `PASS`.

Per il gate si confronta con la soglia il limite inferiore del CI per metriche “più alto è meglio” e il limite superiore per errori “più basso è meglio”. I requisiti esatti/bloccanti richiedono zero eventi, non un CI favorevole.

## 6. Metriche per famiglia P1

### 6.1 Ingestione

- supported-ingest success rate per media type/capture type;
- controlled-rejection rate sugli input non supportati/corrotti;
- page-count accuracy, page-order accuracy, dimension/rotation metadata accuracy;
- crash/hang/resource-exhaustion count;
- determinism rate a parità di input/configurazione.

### 6.2 Pagine, tavole e `source_region`

- precision/recall/F1 per `drawing_area`, frame, cartiglio, legenda, tabelle, note e altri region types;
- IoU matched: media, mediana, P5 e quota sopra target;
- page/tavola/floor-plan count exact-match per documento;
- assignment accuracy pagina → regione/piano.

### 6.3 Primitive geometriche

- AP/precision/recall/F1 per classe a soglia di matching congelata;
- region IoU e boundary F-score con tolleranza normalizzata;
- line/polyline Chamfer P50/P95, endpoint error e overlap longitudinale;
- curve: boundary distance e, quando disponibili, errori centro/raggio/assi/angolo;
- valid-geometry rate, duplicate rate e spurious-length/area rate.

### 6.4 Pareti, stanze e aperture candidate

- instance precision/recall/F1 per `room_region`, `wall_axis`, `wall_face`, `wall_region`, `door`, `window`, `passage`;
- room/wall IoU, boundary F-score e Hausdorff95 normalizzata;
- wall centerline distance, orientation error, length error e thickness error quando osservabile;
- opening localization error, width error e host-wall association accuracy se annotata come relazione;
- room closure/completeness rate solo come proprietà osservata P1, senza imporre invarianti canoniche P2.

### 6.5 OCR e testo

- text-region detection precision/recall/F1;
- CER e WER micro, macro-blocco e per sottogruppo;
- exact transcription accuracy per `dimension_text`, `scale_text`, `level_text`, `elevation_text`, identificatori e room label;
- numeric exact-match e parsed-value error separati; segno, separatore e unità contano;
- text-function classification macro-F1;
- hallucinated-text rate su regioni negative/illeggibili.

### 6.6 Scala, quote e orientamento

- scale detection precision/recall;
- exact ratio accuracy e absolute percentage error del fattore scala;
- linear/area measurement relative error quando la ground truth lo consente;
- north-arrow detection F1 e circular angular error (mediana/P95);
- correct-absence/abstention rate nei documenti senza scala/orientamento osservabile;
- conflict-detection recall per quote/scale incoerenti annotate.

### 6.7 Relazioni osservabili

Prima si mappano gli endpoint tramite il matching delle osservazioni; una relazione è TP solo se tipo, direzione e due endpoint sono corretti.

- precision/recall/F1 micro e macro per i 13 tipi;
- endpoint-pair accuracy e relation-type accuracy;
- orphan, duplicate e invalid-direction count;
- per relazioni simmetriche, canonicalizzare l'ordine degli ID prima del confronto;
- graph edit components riportati separatamente (node miss, edge miss, spurious edge), senza ridurli a un solo score.

### 6.8 Confidenza e calibrazione

- Brier score multiclass/binario per famiglia;
- ECE adaptive-bin con binning/versione pubblicati e reliability diagram;
- negative log-likelihood dove le probabilità sono definite;
- risk-coverage curve e AURC per selective prediction;
- calibration-in-the-large e slope quando il supporto è sufficiente;
- metriche per classe/sottogruppo, non solo globali.

La correctness usata per calibrazione deve corrispondere alla regola di matching congelata. Score non calibrati o senza `calibration_version` falliscono il requisito di lineage.

### 6.9 Astensione

- coverage = quota di unità su cui il sistema emette una decisione;
- selective risk = errore condizionato sulle decisioni non astenute;
- abstention precision: quota delle astensioni che sarebbero casi errati/insufficienti;
- abstention recall: quota dei casi errati/insufficienti intercettati;
- false-abstention rate sui casi chiari;
- missed-abstention rate sui casi impossibili/ambigui.

Il gate richiede simultaneamente rischio basso e copertura minima per famiglia: un sistema non passa astenendosi su tutto.

### 6.10 Out-of-distribution

Corpus OOD congelato e separato per cause: formato/contenuto/stile/qualità fuori dominio.

- AUROC e AUPRC OOD;
- FPR@95TPR e TPR al cutoff operativo;
- false-supported rate: OOD dichiarato supportato;
- controlled-failure rate e crash count;
- detection delay/costo soltanto se rilevante al deployment.

La prevalenza OOD artificiale rende AUROC insufficiente: AUPRC e metriche al cutoff sono obbligatorie.

### 6.11 Lineage, integrità e riproducibilità

- percentuale osservazioni/relazioni con source evidence, producer/version, config/model/taxonomy/guideline e derivazioni risolvibili;
- taxonomy/manifest/output hash verification rate;
- orphan/duplicate ID count;
- semantic determinism rate su re-run;
- split/leakage violations e unauthorized-asset count;
- human-review coverage per `frozen_ground_truth`.

Queste sono metriche bloccanti: non vengono mediate con accuratezza percettiva.

## 7. Sottogruppi obbligatori

Riportare almeno per `document_type`, `capture_type`, `source_quality`, `locale`, media type e inoltre, se presenti nel manifest/report:

- PDF nativo vs rasterizzato vs immagine;
- risoluzione/DPI, compressione, rumore, skew/rotazione, contrasto;
- singola/multipagina, singolo/multipiano, uno/più riquadri;
- stile/epoca/font/retini, colore vs monocromia;
- geometria ortogonale/non ortogonale, curve, ambienti irregolari;
- classi rare, occlusioni, sovrastampe, crop e conflitti di quota/scala.

Ogni gruppo dichiarato supportato deve avere supporto minimo pre-registrato. Gruppi insufficienti sono `INSUFFICIENT_EVIDENCE`; non vengono fusi in “altro” per ottenere il pass.

## 8. Difetti critici

Qualunque evento seguente determina `FAIL` indipendentemente dalle medie:

- crash, hang non controllato o output associato alla pagina/sorgente sbagliata;
- contaminazione `train`/`validation`/`test` o violazione di `leakage_group_id`;
- asset senza diritti/privacy richiesti nel benchmark congelato;
- geometria fuori pagina, ID duplicato/orfano o hash/lineage critico non verificabile;
- valore tecnico inventato (testo, quota, scala, orientamento) senza evidenza;
- OOD/errore critico presentato come decomposizione completa affidabile;
- modifica del `test`, delle soglie o dell'evaluator dopo l'apertura dei risultati;
- correzione geometrica manuale ordinaria necessaria per superare il test;
- errore che rende impossibile ricondurre un'osservazione alla sorgente.

## 9. Regole no-aggregation

Il Gate 1 richiede tutti i seguenti esiti contemporaneamente:

- ogni classe obbligatoria con supporto sufficiente supera precision e recall;
- ogni famiglia critica (stanze, pareti, aperture, quote/scala/orientamento, relazioni) supera i propri veto;
- ogni sottogruppo supportato supera la soglia minima o riceve una decisione formale di restringimento del dominio prima del test;
- metriche micro, macro-classe, macro-progetto e worst-group sono tutte pubblicate;
- zero difetti critici e tutti i controlli di integrità passano.

È vietato creare un “Gate1 score” pesato unico.

## 10. Output dell'evaluator

- `evaluation-summary.json`: versioni, fingerprint, esito per requisito e difetti critici;
- tabelle per classe/layer/sottogruppo con conteggi, metriche e CI;
- curve PR, calibration e risk-coverage;
- error ledger con ID, classe, severità e riferimenti a sorgente/ground truth/predizione;
- report umano con limiti, supporto insufficiente e decisione `PASS|FAIL|INSUFFICIENT_EVIDENCE` per ogni criterio.
