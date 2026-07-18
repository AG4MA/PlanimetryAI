# PlanimetryAI — visione atomica

**Stato:** VISIONE STRATEGICA APPROVATA  
**Data:** 2026-07-17  
**Orizzonte:** pluriennale  
**Punto attivo:** 1 — scomposizione perfetta della planimetria

## Tesi

Una planimetria non deve essere trattata come una semplice immagine. Deve diventare una struttura computabile in cui ogni entita ha geometria, significato, relazioni, unita, fonte, versione e livello di confidenza.

PlanimetryAI mira a costruire questo livello atomico e a usarlo per automatizzare la progettazione tecnica con misure reali. HVAC e il primo dominio applicativo; altri impianti e discipline potranno essere aggiunti soltanto dopo aver raggiunto qualita misurabile nel nucleo comune.

## I tre punti separati

La visione e governata da una sequenza non negoziabile:

1. **Scomporre:** capire esaustivamente che cosa contiene la planimetria e dove si trova.
2. **Formalizzare e controllare:** trasformare la decomposizione in un modello digitale canonico, misurabile, ispezionabile e governabile.
3. **Scrivere:** aggiungere sopra il modello validato HVAC o altri layer tecnici in scala esatta.

Non si procede al punto successivo prima di aver chiuso il precedente con un gate formale. Data Factory, labeling, augmentation e training sono strumenti interni al Punto 1 finche la scomposizione non e completata. Il Knowledge Model completo appartiene al Punto 2. HVAC e ogni altro generatore appartengono al Punto 3.

## I mattoni atomici

Il modello dovra rappresentare almeno:

- documento, pagina, tavola, revisione e sorgente;
- sistema di coordinate, scala, quote e orientamento;
- piano, spazio, perimetro, parete, spessore, apertura e collegamento;
- testo, simbolo, legenda, retino e annotazione;
- componente tecnico, punto di connessione, rete, percorso e attraversamento;
- vincolo geometrico, tecnico, normativo e di installazione;
- dato osservato, fornito o derivato, con provenienza e confidenza;
- stato di lavorazione, verifica, approvazione e validita.

Questi elementi formano un grafo tecnico versionato, non una collezione di coordinate senza contesto.

## Flywheel dei dati e dei modelli

Il miglioramento continuo segue un processo controllato:

1. acquisizione autorizzata di PDF e immagini con licenza, provenienza e metadati;
2. anonimizzazione o trattamento dei dati sensibili secondo le policy applicabili;
3. pre-labeling automatico effettuato dai modelli correnti;
4. correzione e annotazione nella piattaforma di labeling;
5. doppia revisione, consensus e controllo professionale sui casi tecnici;
6. versionamento di immagini, annotazioni, tassonomia e linee guida;
7. separazione rigida fra training, validation e test congelato;
8. augmentation raster, geometrica e semantica che preservi la ground truth;
9. training riproducibile di modelli specializzati;
10. benchmark per tipologia di tavola e analisi degli errori;
11. rilascio soltanto se i gate migliorano senza regressioni critiche;
12. active learning sui casi incerti o nuovi, che rientrano nel ciclo di labeling.

Nessun modello addestrato continuamente viene promosso in produzione o nello stato `CANTIERE` senza valutazione su dataset congelato e gate di sicurezza.

## Piattaforma di labeling

La Data Factory dovra includere un'applicazione web specializzata, non un annotatore generico. Dovra supportare:

- poligoni di ambienti, pareti con spessore, assi e facce;
- porte, finestre, passaggi, scale e simboli tecnici;
- testi, quote, scale grafiche, nord e legende;
- topologia e relazioni fra entita;
- livelli di confidenza, casi ambigui e astensione;
- suggerimenti del modello con accettazione o correzione tracciata;
- task atomici, scorciatoie, snap geometrico e controlli in tempo reale;
- golden task, consensus fra annotatori e code di revisione;
- audit log, versioni, metriche individuali e metriche per classe/corpus.

Il coinvolgimento di studenti di ITIS e indirizzi geometra puo diventare un programma formativo e occupazionale: task adeguati alle competenze, formazione iniziale, remunerazione corretta, supervisione di docenti e professionisti, tutela rafforzata per eventuali minorenni, privacy e riconoscimento delle competenze. Le annotazioni con significato progettuale o normativo richiedono revisione qualificata e non vengono affidate alla sola maggioranza degli annotatori.

## Dataset e augmentation

Ogni release del dataset deve avere:

- manifest, hash, licenze, provenienza e condizioni d'uso;
- tassonomia e manuale di labeling versionati;
- annotazioni geometriche e semantiche collegate alla sorgente;
- statistiche per formato, qualita, epoca, stile grafico e dominio;
- split per edificio/progetto, evitando che varianti della stessa tavola contaminino test e training;
- set di accettazione non utilizzato per calibrare modelli o soglie;
- registro degli errori e delle decisioni sui casi ambigui.

L'augmentation puo simulare scansioni, compressione, rumore, rotazioni, deformazioni prospettiche, risoluzioni, font, spessori, retini e stili diversi. Deve trasformare coerentemente geometrie, quote, simboli e annotazioni; non puo introdurre esempi fisicamente o topologicamente impossibili senza etichettarli come negativi sintetici.

## Architettura dei modelli

Il sistema evolvera come insieme orchestrato di modelli e motori verificabili:

- classificazione e segmentazione di pagine, tavole e piani;
- OCR tecnico e comprensione di quote, simboli e legende;
- estrazione di pareti, aperture e geometrie vettoriali;
- ricostruzione topologica e graph reasoning;
- stima calibrata dell'incertezza e rilevamento out-of-distribution;
- fusione fra evidenze raster, testo, geometria e regole;
- motori deterministici per unita, controlli, calcoli e vincoli;
- ottimizzazione degli impianti con clash detection e verifiche tecniche;
- tracciabilita completa dal pixel all'elaborato finale.

I modelli probabilistici propongono e interpretano; schema, controlli dimensionali, calcoli tecnici e gate di rilascio restano deterministici e ispezionabili.

## Evoluzione dei prodotti

1. **Punto 1 — Decomposition Factory:** parser, tassonomia, labeling web, gestione corpus, QA, augmentation, training, evaluation e active learning fino al Gate 1.
2. **Punto 2 — Planimetry Control Model:** Knowledge Model canonico, validator, viewer, controlli, versioni, query e interoperabilita fino al Gate 2.
3. **Punto 3 — Technical Writing:** HVAC come primo writer; ogni altro impianto o analisi come writer separato fino al proprio Gate 3.
4. **Ecosistema:** API, SDK, plugin, import/export e programmi per scuole, studi, imprese e produttori.
5. **Standard de facto:** specifica pubblica, validator di riferimento, test di conformita, governance e adozione diffusa.
6. **Percorso istituzionale:** collaborazione con enti, associazioni professionali, organismi di normazione e comunita openBIM per un eventuale riconoscimento formale.

## Strategia di standardizzazione

PlanimetryAI non deve creare un formato chiuso incompatibile con il settore. Il Knowledge Model sara AI-first e ottimizzato per planimetrie 2D, ma dovra prevedere mapping verificabili verso IFC/openBIM e allineamento con i processi informativi italiani.

La strategia comprende:

- specifica pubblica e semantic versioning;
- JSON Schema e ontologie/tassonomie versionate;
- validator open e suite ufficiale di conformance test;
- profili di scambio per casi d'uso, anziche un unico formato monolitico;
- mapping lossless o perdita dichiarata verso IFC quando applicabile;
- governance con proposte, review, deprecazioni e migrazioni pubbliche;
- dataset benchmark e reference implementation;
- neutralita rispetto a software, produttori e studi professionali.

IFC 4.3 e pubblicato come ISO 16739-1:2024 ed e il riferimento aperto internazionale per lo scambio BIM. In Italia la serie UNI 11337 e la serie UNI EN ISO 19650 costituiscono riferimenti essenziali per gestione e processi informativi digitali. PlanimetryAI dovra interoperare con questo ecosistema, non fingere che non esista.

## Principi non negoziabili

- precisione metrica e unita sempre esplicite;
- nessun dato tecnico inventato;
- confidenza e provenienza per ogni informazione critica;
- fallimento controllato e gate fail-closed;
- separazione fra suggerimento AI, calcolo tecnico e approvazione professionale;
- dataset legittimi, tracciabili e protetti;
- misure di qualita pubblicabili e riproducibili;
- interoperabilita prima del lock-in;
- crescita per evidenza, non per dichiarazioni di marketing.

## Misura del potere reale

Il progetto non misura il proprio progresso dal numero di feature o modelli. Lo misura da:

- percentuale di planimetrie comprese correttamente per classe;
- errore metrico e topologico;
- copertura dei casi tecnici senza intervento geometrico manuale;
- affidabilita calibrata e capacita di astenersi;
- tempo risparmiato ai professionisti senza ridurre controllo e responsabilita;
- numero di workflow e strumenti interoperabili;
- ampiezza, diversita e qualita del dataset autorizzato;
- adozione reale da parte di tecnici, scuole, imprese, software e istituzioni.

Diventare standard de facto sara una conseguenza di questi risultati, non un'etichetta assegnata in anticipo.

## Riferimenti di interoperabilita iniziali

- ISO 16739-1:2024 / IFC 4.3, schema aperto per scambio BIM.
- Serie UNI 11337, gestione digitale dei processi informativi delle costruzioni.
- Serie UNI EN ISO 19650, gestione informativa mediante BIM.
- Profili tecnici e norme di dominio elencati in `PROJECT_OBJECTIVE.md` e versionati nel registro normativo futuro.
