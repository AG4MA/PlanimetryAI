# Obiettivo approvato di PlanimetryAI

**Stato:** APPROVATO DAL RESPONSABILE DEL PROGETTO

**Data prima approvazione:** 2026-07-17

**Ultima precisazione vincolante:** 2026-07-17

**Punto attivo:** 1 — Scomposizione perfetta dentro PlanParser

## Obiettivo essenziale

Arriva una planimetria. PlanimetryAI deve:

1. scomporla perfettamente nei suoi elementi;
2. formalizzarla in un modello digitale preciso e completamente controllabile;
3. usare quella formalizzazione senza alterarla, rispondendo a domande e scrivendo sopra progetti tecnici in scala esatta, iniziando dall'HVAC.

I tre punti sono distinti e strettamente sequenziali. Il punto successivo non entra nello scope operativo finché il precedente non è completato e approvato con evidenze.

I tre punti non coincidono con il numero dei prodotti. Scomposizione e formalizzazione appartengono entrambe a `PlanParser`, ma restano due sistemi interni difficili, separati da un gate reale.

## Quattro prodotti distinti

### 1. PlanParser

Super-servizio che trasforma una sorgente PDF/immagine in una planimetria formalizzata e controllabile. Contiene, in sequenza:

1. il sistema di scomposizione percettiva;
2. il sistema di formalizzazione e controllo.

Il suo output pubblico finale è la formalizzazione della planimetria. I consumatori non accedono agli algoritmi, ai database o ai formati interni di PlanParser.

### 2. PlanNL

Super-servizio che consuma la formalizzazione prodotta da PlanParser per rispondere a domande. Non ricostruisce la planimetria, non inventa dati mancanti e non corregge silenziosamente la formalizzazione.

### 3. Plan2HVAC

Super-servizio che consuma la stessa formalizzazione e produce un progetto HVAC separato, tracciabile e in scala esatta sopra la planimetria. Non modifica la base formalizzata e non compensa errori di PlanParser.

### 4. PlanimetryDigitalConventions

Prodotto futuro destinato a dichiarare come dovranno essere in futuro le planimetrie e i documenti che parlano di planimetrie. Non è il contratto operativo corrente, non è il Punto 2, non si trova fra PlanParser e i consumer e non appartiene allo scope operativo attuale.

### Regola fra prodotti

Ogni prodotto deve fare una cosa bene ed essere indipendente: interfacce e contratti pubblici versionati, release e test propri, errori isolati e nessuna dipendenza dagli interni o da un database condiviso. PlanNL e Plan2HVAC ricevono la formalizzazione tramite il contratto pubblico di PlanParser.

## Regola assoluta di avanzamento

`PUNTO 1 — SCOMPORRE → GATE 1 → PUNTO 2 — FORMALIZZARE/CONTROLLARE → GATE 2 → CONSUMER INDIPENDENTI`

- Non si sviluppano contemporaneamente i tre punti di maturità.
- Il lavoro parallelo è ammesso soltanto fra sottocomponenti necessari al punto attivo.
- Ricerca, prototipi o codice già esistenti dei punti successivi restano congelati e non determinano lo stato del progetto.
- Nessun risultato downstream può compensare un punto precedente incompleto.
- Ogni gate richiede test, dataset congelato, metriche e riesame esplicito.
- PlanNL e Plan2HVAC non sono moduli interni di PlanParser: diventano consumer soltanto dopo un contratto pubblico stabile.
- PlanimetryDigitalConventions resta futuro e non partecipa ai gate operativi correnti.

## Punto 1 — Scomporre perfettamente la planimetria

**Prodotto proprietario:** PlanParser

### Domanda a cui deve rispondere

“Che cosa è presente nella tavola, dove si trova, quanto misura e con quale certezza lo sappiamo?”

### Input

- PDF;
- immagini raster dichiarate supportate.

### Risultato intermedio interno a PlanParser

Una decomposizione atomica completa e tracciabile della sorgente, comprendente almeno:

- documento, pagina, tavola, riquadro e piano;
- coordinate, scala, quote e orientamento;
- linee, archi, curve, contorni e retini;
- pareti, spessori, ambienti e perimetri;
- porte, finestre, passaggi, scale e altri elementi architettonici;
- testi, label, numeri, simboli, legende e annotazioni;
- appartenenze e relazioni osservabili;
- posizione nella sorgente, provenienza e confidenza di ogni elemento;
- esplicita astensione quando un elemento non può essere determinato.

“Perfettamente” significa: corretto entro soglie approvate sul dominio di planimetrie dichiarato supportato, con rilevamento dei casi fuori distribuzione e fallimento controllato. Non significa fingere accuratezza universale o inventare elementi nei casi incerti.

### Infrastruttura ammessa nel Punto 1

La Data Factory, il sito di labeling, l'augmentation, il training, l'evaluation e l'active learning appartengono al Punto 1 quando servono a migliorare la scomposizione di PlanParser. Non sono prodotti downstream.

Il programma di labeling può coinvolgere studenti di ITIS e indirizzi geometra con formazione, remunerazione, supervisione, QA multilivello, privacy e tutela rafforzata per eventuali minorenni. Le decisioni tecniche o normative richiedono revisione qualificata.

### Gate 1

Il Punto 1 è completato soltanto quando:

- esiste una tassonomia atomica versionata;
- esiste un dataset di accettazione rappresentativo, congelato e separato dal training;
- tutte le classi obbligatorie hanno ground truth e metriche approvate;
- geometria, OCR, scala, aperture, ambienti e relazioni superano le soglie concordate;
- la confidenza è calibrata e i casi non supportati vengono riconosciuti;
- il flusso non richiede correzione geometrica manuale ordinaria;
- ogni output è riproducibile e riconducibile ai pixel o vettori sorgente;
- non restano difetti critici aperti;
- il responsabile del prodotto approva formalmente il Gate 1.

Fino al Gate 1, il lavoro operativo resta qui.

## Punto 2 — Formalizzare benissimo e avere controllo

**Prodotto proprietario:** PlanParser

### Stato

`BLOCCATO DAL GATE 1`. È il secondo grande sistema interno di PlanParser. Contratti e prototipi già presenti sono materiale preparatorio, non prova di completamento.

### Domanda a cui deve rispondere

“Come rappresentiamo, verifichiamo, misuriamo, ispezioniamo e trasformiamo senza ambiguità tutto ciò che è stato scomposto?”

### Risultato finale pubblico di PlanParser

Una planimetria formalizzata in un modello digitale canonico che offra:

- schema e semantica versionati;
- unità e sistemi di coordinate espliciti;
- geometria metrica e topologia coerenti;
- identificativi, relazioni e vincoli deterministici;
- provenienza, confidenza, revisioni e audit trail;
- validator strutturale, geometrico, topologico e dimensionale;
- visualizzatore e strumenti di ispezione/controllo;
- trasformazioni, misure e query riproducibili;
- override eccezionali tracciati, mai default occulti;
- mapping verificabili verso formati di interoperabilità quando applicabile.

“Avere controllo” significa poter verificare ogni dato, risalire alla sorgente, misurarlo, validarlo, versionarlo e modificarlo in modo esplicito e auditabile. Non significa nascondere decisioni non verificabili in un modello opaco.

### Gate 2

Il Punto 2 è completato soltanto quando la formalizzazione supera conformance test, invarianti geometriche/topologiche, round-trip, migrazioni di versione, controlli di unità, tracciabilità e riesame su tutti i casi ammessi dal Gate 1.

Con il `GO GATE 2`, PlanParser dispone finalmente del proprio output pubblico affidabile. Solo allora i consumer indipendenti possono essere sviluppati e valutati sul contratto stabile.

## Consumer della formalizzazione

### PlanNL — Rispondere a domande

`BLOCCATO DAL GATE 2`. PlanNL legge la formalizzazione di PlanParser e restituisce risposte tracciabili ai campi utilizzati. Se il dato non esiste o non è affidabile, dichiara che non è disponibile. Non altera la formalizzazione. Ha test, release e criteri di accettazione propri.

### Plan2HVAC — Scrivere sopra in scala

`BLOCCATO DAL GATE 2`. Plan2HVAC aggiunge un layer/progetto HVAC tecnico separato, tracciabile e in scala reale. Non altera la formalizzazione di PlanParser.

Per HVAC il risultato obiettivo è un fascicolo esecutivo di livello cantiere: calcoli verificabili, componenti, reti, dimensionamenti, tavole quotate, distinta, specifiche e controlli. Lo stato `CANTIERE` richiede dati tecnici sufficienti, gate automatici e approvazione del professionista abilitato prevista dal processo applicabile.

Ogni dominio tecnico futuro sarà un prodotto o servizio specializzato con dati, norme, calcoli, gate e validazione propri; non verrà incorporato impropriamente in PlanParser.

## Futuro — PlanimetryDigitalConventions

PlanimetryDigitalConventions inizierà soltanto quando l'esperienza reale dei prodotti avrà prodotto evidenze sufficienti. Dichiarerà una visione e convenzioni pubbliche per il futuro delle planimetrie e dei documenti che ne parlano, eventualmente con specifica, esempi, validator e conformance suite.

Non è oggi il modello operativo di PlanParser, non decide il Gate 2 e non è una dipendenza necessaria di PlanNL o Plan2HVAC. L'obiettivo di diventare standard de facto italiano dovrà derivare dall'utilità e dall'adozione reale, non da una dichiarazione unilaterale.

La visione estesa è descritta in `ATOMIC_VISION.md`; la sequenza operativa è in `ATOMIC_ROADMAP.md`; i criteri misurabili sono in `ACCEPTANCE_CRITERIA.md`.

## Regola di modifica

Qualunque modifica ai quattro prodotti, alle responsabilità, all'ordine dei punti, ai gate o al perimetro richiede conferma esplicita del responsabile del progetto e registrazione in `ASYNC_LOG.md`.
