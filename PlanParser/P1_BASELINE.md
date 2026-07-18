# Punto 1 — baseline iniziale di decomposizione

**Data:** 2026-07-17  
**Stato Gate 1:** `HOLD`  
**Comando:** `python -m PlanParser.decompose <input> --output <path> --dpi 100`

## Scopo della prova

Verificare che il nuovo percorso esclusivo del Punto 1 produca osservazioni collegate alla sorgente e un documento conforme al contratto. Questa prova non misura ancora l'accuratezza: manca una ground truth indipendente.

## Corpus disponibile

| File | SHA-256 breve | Pagine | Regioni sorgente | Candidati piano | Segmenti geometrici | Testi | Candidati ambiente | Warning |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `scheda_catastale.pdf` | `7483495c3288` | 1 | 1 | 1 | 43 | 0 | 0 | 2 |
| `scheda_catastale_.pdf` | `61f54f8f50c1` | 1 | 1 | 1 | 6 | 0 | 0 | 2 |
| `scheda_catastale_4.pdf` | `02ad9554738d` | 1 | 1 | 1 | 37 | 0 | 0 | 2 |

## Esito verificato

- Tutti e tre i PDF vengono letti senza crash.
- Ogni output rispetta `decomposition.schema.json` e la tassonomia v1.
- Le coordinate dei crop vengono ritrasformate nel sistema della pagina sorgente.
- Ogni osservazione dichiara evidenza, confidenza non calibrata e provenienza.
- Gli output sono correttamente marcati `draft`.
- Nessun output viene presentato come modello formale o progetto tecnico.

## Lacune osservate

1. **OCR assente:** l'eseguibile Tesseract non e disponibile nell'ambiente. Il sistema registra zero testi invece di inventarli.
2. **Topologia non chiusa:** il controllo di Eulero fallisce sui tre campioni; il semantic analyzer produce zero ambienti.
3. **Line extraction instabile:** a parita di famiglia documentale vengono prodotti 6, 37 e 43 segmenti dopo merge. Senza annotazioni non e possibile stabilire precision e recall.
4. **Confidenza non calibrata:** gli score correnti sono euristiche dichiarate, non probabilita validate.
5. **Corpus insufficiente:** tre PDF catastali non coprono la variabilita richiesta dal Gate 1.
6. **Nessuna ground truth:** non sono calcolabili IoU, errore metrico, precision/recall o copertura.

## Perche il Gate 1 resta HOLD

La validita JSON dimostra soltanto che sappiamo registrare l'output. Non dimostra che sappiamo scomporre correttamente la planimetria. In particolare, zero ambienti su tutti i campioni impedisce qualunque claim di completezza.

## Prossimo ordine di lavoro P1

1. congelare la tassonomia minima e le linee guida di annotazione;
2. rendere disponibile un motore OCR riproducibile e versionato;
3. creare ground truth sui campioni iniziali con il nuovo contratto;
4. costruire un evaluator per classe, geometria, testo, scala e relazioni;
5. correggere estrazione/ricostruzione topologica guidandosi con errori misurati;
6. ampliare il corpus soltanto con provenienza, licenza e split corretti;
7. calibrare confidenze e astensione sul validation set;
8. deliberare Gate 1 soltanto sul test set congelato.

## Test automatici P1

La baseline del contratto conta 8 test dedicati:

- documento valido;
- classe coerente con il layer;
- bounds della pagina;
- riferimenti orfani;
- conteggio pagine;
- hash della tassonomia;
- revisione senior obbligatoria per ground truth congelata;
- trasformazione corretta da coordinate del crop a coordinate pagina.
