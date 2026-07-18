# Dataset e benchmark del Punto 1

**Stato:** contratto baseline v1  
**Ambito:** soltanto `P1 — Scomporre`

## Scopo

Il manifest rende ogni release di dati riproducibile, autorizzata e resistente al leakage. Collega ogni PDF o immagine alla relativa decomposizione, alla provenienza, ai diritti d'uso, allo split e agli strati con cui misurare i sottogruppi.

Il manifest non definisce il modello digitale del Punto 2 e non contiene output HVAC o di altri writer del Punto 3.

## Regole bloccanti

- Sono ammessi soltanto PDF e immagini nei media type elencati dallo schema.
- Ogni asset ha hash sorgente, provenienza e licenza identificabili.
- L'autorizzazione deve essere verificata; `train` richiede uso `training`, mentre `validation` e `test` richiedono uso `evaluation`.
- Un benchmark congelato contiene solo asset con privacy review `approved` o `not_required`.
- Lo stesso contenuto non può comparire due volte, nemmeno nello stesso split.
- Tutti i documenti della stessa origine logica, variante o progetto condividono `leakage_group_id` e restano nello stesso split.
- Le augmentation sono ammesse soltanto nel train, devono indicare parent e ricetta e restano nello stesso leakage group del parent.
- In un benchmark congelato, validation e test usano decomposizioni `frozen_ground_truth`; nessuna annotation può essere `draft`.
- Un benchmark congelato contiene almeno un elemento train, validation e test. Le quantità reali e la copertura per sottogruppo sono soglie del Gate 1 ancora da concordare.

## Verifica forte

Il comando seguente valida anche esistenza, hash e contratto di ogni file di annotazione:

```powershell
python -m PlanParser.dataset path\to\dataset-manifest.json --verify-files
```

La modalità `--verify-files` controlla inoltre che l'hash e il numero di pagine della sorgente dichiarata nella decomposizione coincidano con l'asset registrato. Per il congelamento e per ogni prova Gate 1 questa verifica è obbligatoria.

## Split e leakage

Lo split è `grouped_deterministic`, con seed registrato. `leakage_group_id` deve raggruppare almeno:

- pagine o tavole dello stesso documento;
- revisioni dello stesso progetto;
- scansioni e conversioni dello stesso originale;
- crop derivati dalla stessa pagina;
- augmentation e relativo parent;
- documenti che condividono geometria o template in modo tale da falsare la generalizzazione.

Validation e test, una volta congelati, non vengono usati per training, selezione attiva, scelta soglie o correzione delle linee guida. Un nuovo ciclo che usa quegli errori richiede una nuova release e un nuovo test indipendente.

## Strati minimi

Ogni asset dichiara almeno `document_type`, `capture_type`, `source_quality` e `locale`. Il Gate 1 non usa soltanto una media globale: metriche e difetti critici vengono riportati anche per questi strati e per le classi atomiche.

## Immutabilità

Il fingerprint della release è l'SHA-256 della serializzazione JSON canonica del manifest. Qualunque modifica a contenuto, split, diritti, annotation o metadati produce un fingerprint diverso e quindi una release diversa.
