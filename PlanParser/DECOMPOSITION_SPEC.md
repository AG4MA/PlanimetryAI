# Specifica di decomposizione atomica — Punto 1

**Stato:** baseline v1 da misurare e ampliare con il dataset  
**Gate:** Punto 1 / Gate 1  
**Non e:** il Knowledge Model formale del Punto 2

## Scopo

La decomposizione descrive cio che il sistema osserva nella sorgente senza trasformarlo prematuramente in un modello progettuale definitivo. Ogni elemento deve restare collegato alla pagina, alla geometria sorgente, al produttore e alla relativa confidenza.

Il medesimo contratto viene usato per:

- output di PlanParser;
- pre-label automatici;
- annotazioni della piattaforma di labeling;
- ground truth congelata;
- augmentation con geometrie trasformate coerentemente;
- evaluation e analisi degli errori.

## Confine con il Punto 2

Nel Punto 1 una sequenza di tratti puo essere candidata a `wall_region`, ma non diventa ancora una parete canonica con tutte le proprieta tecniche. Un testo puo essere candidato a `room_label`, ma la stanza formale, i suoi vincoli e la sua identita versionata appartengono al Punto 2.

Questa separazione impedisce che un'ipotesi del modello venga confusa con un fatto certo.

## Livelli di osservazione

1. `source_region`: zone della pagina come area di disegno, cartiglio, legenda, tabella e note.
2. `geometry`: primitive grafiche osservate, indipendentemente dal significato.
3. `text`: token e blocchi testuali con trascrizione, posizione e confidenza.
4. `symbol`: simboli o marker grafici candidati.
5. `architectural_candidate`: aggregazioni candidate come pareti, ambienti, aperture, scale e pilastri.
6. `measurement`: quote, scala, livelli, angoli e altre misure candidate.

Le relazioni osservabili sono separate dalle entita. Esempi: `contains`, `touches`, `intersects`, `collinear_with`, `labels`, `dimensions`, `bounds`, `candidate_part_of`.

## Regole invarianti

- Ogni documento dichiara hash, media type, numero di pagine e versione della tassonomia.
- Ogni pagina dichiara dimensioni raster e trasformazioni note.
- Ogni osservazione ha ID univoco nel documento.
- La classe deve appartenere al livello dichiarato nella tassonomia versionata.
- La geometria e sempre espressa in pixel della pagina renderizzata; eventuali coordinate PDF o metriche sono attributi espliciti e non sostituiscono la sorgente.
- Ogni osservazione include evidenza sorgente, confidenza e provenienza.
- Ogni relazione usa riferimenti esistenti.
- Valori mancanti restano mancanti; non si applicano default semantici nascosti.
- L'astensione e un risultato valido e misurabile.
- Una ground truth `frozen` puo contenere pre-label automatici solo dopo revisione umana registrata.

## Geometrie supportate

- `point`: un punto;
- `bbox`: rettangolo assiale `[x, y, width, height]`;
- `polyline`: sequenza aperta di punti;
- `polygon`: sequenza chiusa semanticamente, senza duplicare obbligatoriamente il primo punto;
- `mask`: riferimento a una maschera raster esterna con hash.

Il validator controlla bounds, cardinalita minima, riferimenti, ID e appartenenza alla tassonomia. Controlli geometrici avanzati, come auto-intersezioni e IoU, verranno aggiunti insieme alle fixture del benchmark.

## Provenienza

Il campo `provenance` distingue almeno:

- `model`: predizione di un modello versionato;
- `human`: annotazione o revisione umana;
- `imported`: dato importato da una sorgente dichiarata;
- `derived`: risultato deterministico derivato da altre osservazioni.

Produttore, versione, timestamp e riferimenti di derivazione sono obbligatori secondo il metodo. Le revisioni non sovrascrivono silenziosamente la storia nel dataset registry.

## Confidenza e astensione

La confidenza non e una decorazione. Ogni score deve dichiarare la versione di calibrazione quando proviene da un modello. `abstained=true` indica che il sistema ha localizzato un'evidenza ma non assegna una classe affidabile; il motivo viene registrato in `reasons`.

Il Gate 1 definira cutoff e metriche per classe usando curve di calibrazione e copertura, non una singola soglia globale scelta arbitrariamente.

## Tassonomia

La tassonomia machine-readable e in `decomposition/taxonomy.v1.json`. Ogni modifica incompatibile crea una nuova versione e una migrazione esplicita. `unknown_*` e ammesso per raccogliere casi nuovi, ma non conta come successo sulle classi obbligatorie del benchmark.

## Stato del dataset

- `draft`: output di pipeline o annotazione incompleta;
- `reviewed`: controlli automatici e revisione prevista completati;
- `frozen_ground_truth`: release immutabile destinata a benchmark/test, con manifest e hash.

Il passaggio di stato appartiene al dataset workflow, non al modello di visione.

## Criterio di completamento di questa baseline

La specifica e pronta come baseline quando schema, tassonomia e validator hanno test positivi e negativi. Il Punto 1 non e completato finche il contratto non viene provato e raffinato su un dataset rappresentativo con le metriche del Gate 1.
