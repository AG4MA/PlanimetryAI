# PlanimetryAI — roadmap sequenziale a tre gate

**Stato operativo:** `PUNTO 1 ATTIVO`  
**Punto 2:** `BLOCCATO DAL GATE 1`  
**Punto 3:** `BLOCCATO DAL GATE 2`  
**Regola assoluta:** `P1 SCOMPORRE → GATE 1 → P2 FORMALIZZARE/CONTROLLARE → GATE 2 → P3 SCRIVERE → GATE 3`

## Architettura dei quattro prodotti

I tre punti sono gate di capacità e non corrispondono uno-a-uno ai prodotti:

| Prodotto | Responsabilità forte | Posizione nella sequenza |
|---|---|---|
| **PlanParser** | Ricevere PDF/immagini e produrre una formalizzazione controllabile, senza inventare dati. | Possiede P1 e, dopo Gate 1, P2. |
| **PlanNL** | Interrogare in sola lettura la formalizzazione pubblicata; rispondere dai dati disponibili e dichiarare l'assenza. | Consumer downstream, bloccato fino a Gate 2; non scrive layer tecnici e non corregge geometria. |
| **Plan2HVAC** | Produrre un layer/progetto HVAC separato, in scala esatta, senza mutare la base. | Writer P3, bloccato fino a Gate 2. |
| **PlanimetryDigitalConventions** | Dichiarare in futuro la visione delle planimetrie e dei documenti che ne parlano. | Prodotto futuro fuori dallo scope operativo; non è P2 né il contratto runtime corrente. |

PlanParser, PlanNL e Plan2HVAC sono super-servizi indipendenti. Comunicano tramite contratti/API pubblicati e versionati: sono vietati import del codice interno di un altro prodotto, accesso diretto al suo database o scritture su storage condiviso come meccanismo di integrazione. Ogni consumer tratta la formalizzazione ricevuta come immutabile e conserva versione/hash del contratto e dell'input.

## Regole di governo

1. Non si avvia ricerca, prototipazione, implementazione o integrazione del punto successivo prima dell'approvazione formale del gate precedente.
2. Il parallelismo è ammesso soltanto fra sottocomponenti indispensabili al punto attivo.
3. Codice o prototipi downstream già esistenti restano soltanto conservati e congelati: non vengono ricercati, estesi, eseguiti, testati o integrati durante il punto precedente. Questo include PlanNL e Plan2HVAC fino al Gate 2.
4. Nessun risultato downstream compensa lacune upstream. Se un gate viene riaperto per regressione, anche tutti i punti successivi tornano bloccati.
5. Ogni gate richiede dataset congelato, metriche approvate, test riproducibili, evidenze archiviate, zero difetti critici e verbale `GO`; altrimenti l'esito è `HOLD`, `ROLLBACK` o `STOP`.
6. Le date pianificano risorse; soltanto i gate dichiarano maturità.

---

## Punto 1 — Scomporre perfettamente

**Stato:** `ATTIVO`

### Obiettivo

Rispondere in modo completo e misurabile: che cosa è presente nella tavola, dove si trova, quanto misura e con quale certezza lo sappiamo. L'output di P1 è una decomposizione atomica tracciabile alla sorgente, non ancora la formalizzazione controllabile. P1 è il primo tratto interno di PlanParser.

### Prerequisiti

- Dominio supportato di PDF e immagini dichiarato.
- Tassonomia iniziale, responsabili di classe e failure taxonomy.
- Accesso autorizzato a planimetrie rappresentative e budget per ground truth/revisione.
- Policy privacy, sicurezza, licenze, retention e programma annotatori approvati.

### Workstream ammessi in parallelo dentro P1

1. **Ingestione e pagina/tavola:** documenti, pagine, riquadri, piani, rotazioni e qualità.
2. **Geometria atomica:** linee, archi, curve, contorni, retini, pareti, spessori, ambienti e perimetri.
3. **Elementi e relazioni osservabili:** porte, finestre, passaggi, scale, appartenenze e adiacenze osservabili.
4. **OCR tecnico:** testi, label, numeri, quote, simboli, legende, scala e orientamento.
5. **Confidenza e OOD:** calibrazione, astensione, casi fuori distribuzione e fallimento controllato.
6. **Data Factory:** acquisizione, anonimizzazione, labeling web, golden task, consensus, QA e dataset registry.
7. **Model Factory per la scomposizione:** augmentation, training, evaluation, model registry, active learning e rollback.
8. **Benchmark e riproducibilità:** ground truth, split per progetto, test congelato, analisi errori e lineage pixel/vettore → elemento.

Data Factory, augmentation, training, evaluation, MLOps e active learning non sono fasi downstream: restano dentro P1 finché Gate 1 non è chiuso.

### Deliverable

- Tassonomia atomica versionata con manuale, esempi positivi/negativi e regole di ambiguità.
- Piattaforma di labeling verticale e dataset registry con provenienza, licenze, hash e split anti-leakage.
- Dataset train/validation e dataset di accettazione congelato, indipendente e revisionato.
- Pipeline di scomposizione riproducibile per tutte le classi obbligatorie.
- Modelli e motori geometrici/OCR con confidenza calibrata, OOD e astensione.
- Benchmark per classe, sottogruppo e tipologia di tavola; error registry e audit completo.
- Viewer diagnostico limitato alla verifica delle annotazioni/decomposizioni di P1; non è il viewer canonico di P2.

### Metriche di uscita — Gate 1

- Tutti i criteri `P1-*` di `ACCEPTANCE_CRITERIA.md` hanno soglie risolte e sono superati sul test congelato.
- 100% classi obbligatorie hanno ground truth, owner, metrica, soglia e failure policy.
- Geometria, OCR, scala, orientamento, ambienti, aperture e relazioni superano le soglie per ogni sottogruppo approvato.
- Confidenza calibrata e casi OOD/insufficienti riconosciuti entro le soglie; nessun dato incerto viene inventato.
- Zero correzioni geometriche manuali ordinarie sul dataset di accettazione.
- Ogni elemento è riproducibile e riconducibile a pixel/vettori sorgente, modello, configurazione e versione dati.
- Zero contaminazione del test, zero difetti critici aperti e audit privacy/sicurezza superato.
- Approvazione formale del product owner con responsabile dataset, QA e revisori delle classi.

### Dipendenze

Planimerie legittime e diversificate; annotatori formati; docenti e professionisti revisori; compute; data/ML platform; DPO/privacy e security.

### Rischi e mitigazioni

- **“Perfetto” interpretato come universale:** dominio supportato esplicito, metriche per sottogruppo e OOD.
- **Leakage e ground truth debole:** split per edificio/progetto, blind test e doppia revisione.
- **Modelli promossi automaticamente:** nessun auto-deploy; promozione solo dopo benchmark congelato.
- **Consensus non competente:** veto professionale su label tecniche; astensione ed escalation.
- **Sfruttamento annotatori/studenti:** programma tutelato, retribuito e auditabile descritto sotto.

### Ruoli

Product owner P1, perception/geometry lead, OCR lead, ML/MLOps lead, Data Factory lead, data steward, labeling QA lead, evaluation scientist, DPO/privacy, security, docenti tutor, annotatori senior e revisori tecnici.

---

## Gate 1 — Delibera

Il board esamina evidenze P1, risultati ciechi, errori critici, audit dati e riproducibilità. Solo un verbale `GO GATE 1`, riferito agli hash delle evidenze, sblocca P2. Un prototipo di schema o HVAC non costituisce evidenza per Gate 1.

---

## Punto 2 — Formalizzare e controllare

**Stato:** `BLOCCATO DAL GATE 1`

**Prodotto proprietario:** `PlanParser` (secondo tratto della sua responsabilità end-to-end).

### Divieto corrente

Fino al `GO GATE 1` PlanParser non estende formalizzazione canonica, validator di prodotto, viewer di controllo, query, trasformazioni, mapping IFC o conformance suite. Gli artefatti già presenti restano prototipi congelati. PlanimetryDigitalConventions non viene usato per svolgere questo lavoro.

### Obiettivo

Trasformare la decomposizione approvata in un modello digitale canonico, preciso, misurabile, ispezionabile, trasformabile, versionato e completamente controllabile.

### Prerequisiti

- Gate 1 formalmente approvato e dataset ammesso congelato.
- Tassonomia P1 stabile e change-control attivo.
- Requisiti informativi, casi d'uso di controllo e profili di scambio approvati.

### Workstream ammessi dopo lo sblocco

1. Schema/semantica, unità, coordinate, identificativi, provenienza, confidenza e revisioni.
2. Invarianti geometriche, topologiche e dimensionali; constraint engine.
3. Validator strutturale/semantico/geometrico/topologico/dimensionale.
4. Viewer canonico, ispezione, misure, query, trasformazioni e override eccezionali auditabili.
5. Migrazioni, round-trip, serializzazione deterministica e conformance suite.
6. Mapping per profilo verso IFC/ISO 16739 e gestione informativa coerente con UNI 11337/ISO 19650.

### Deliverable

- Knowledge Model canonico versionato e reference implementation.
- JSON Schema/vocabolari, migration toolkit e changelog.
- Validator completo, viewer di controllo e strumenti di misura/query.
- Audit trail e lineage sorgente → decomposizione P1 → entità canonica.
- Profili IFC con mapping bidirezionale, coverage/loss report e fixture indipendenti.
- Conformance suite e manuale di governo delle versioni.
- Contratto/API di uscita di PlanParser, autonomo e versionato, consumabile senza import interni o database condivisi.

### Metriche di uscita — Gate 2

- Tutti i criteri `P2-*` di `ACCEPTANCE_CRITERIA.md` superati su tutti i casi ammessi da Gate 1.
- 100% output validi conformi; fixture invalide rifiutate; zero ID orfani, unità implicite o default occulti.
- Invarianti geometriche/topologiche/dimensionali, round-trip e migrazioni entro soglie approvate.
- Ogni dato ispezionabile e riconducibile alla decomposizione/sorgente; override espliciti e auditabili.
- Viewer, validator e query producono risultati coerenti e riproducibili.
- Mapping interoperabili testati con perdita dichiarata; nessun claim generico di conformità.
- Contract/API test dimostrano che consumer esterni possono leggere l'output senza accedere a internals o storage di PlanParser.
- Zero difetti critici e approvazione formale di architecture lead, QA, responsabile interoperabilità e product owner.

### Dipendenze

Gate 1, esperti data modeling/geometria, strumenti indipendenti IFC/openBIM e responsabili informativi.

### Rischi e mitigazioni

- **Schema che altera l'osservazione:** lineage immutabile e separazione observed/derived/overridden.
- **Modello monolitico:** core piccolo e profili di scambio versionati.
- **Falsa interoperabilità:** conformance e round-trip con implementazioni indipendenti, loss report obbligatorio.

### Ruoli

Product owner P2, data model/architecture lead, computational geometry lead, validator/viewer lead, QA/conformance lead, interoperability/openBIM lead, information manager e security/privacy.

---

## Gate 2 — Delibera

Solo un verbale `GO GATE 2`, successivo al `GO GATE 1`, sblocca P3. Un writer che produce tavole plausibili non compensa errori del modello e non è prova per Gate 2.

---

## Punto 3 — Scrivere sopra

**Stato:** `BLOCCATO DAL GATE 2`

### Divieto corrente

Plan2HVAC resta un prototipo diagnostico congelato. PlanNL resta un consumer prototipale congelato. Non si sviluppano query downstream, calcoli, layout, fascicoli esecutivi o nuovi domini finché Gate 2 non è formalmente approvato.

### Obiettivo

Consumare esclusivamente la formalizzazione validata pubblicata da PlanParser e aggiungere layer tecnici separati, tracciabili e in scala esatta. Plan2HVAC è il primo writer; ogni dominio successivo ripete un proprio Gate 3. Il layer HVAC non modifica, corregge o sostituisce la base.

### Prerequisiti

- Gate 2 approvato e versione del Knowledge Model congelata per il writer.
- Dati tecnici, casi professionali, cataloghi e profilo normativo del dominio approvati.
- Professionista responsabile e criteri di accettazione specifici nominati.

### Deliverable HVAC

- Carichi ambiente per ambiente con input, formule, unità e assunzioni tracciabili.
- Selezione/dimensionamento di terminali e generatori da cataloghi versionati.
- Reti con portate, diametri, perdite, prevalenze, bilanciamento, dispositivi e condense applicabili.
- Layout/clash detection e tavole esecutive quotate sopra il modello P2 immutato.
- Relazione, distinta, specifiche di posa, controlli/messa in servizio, anomalie e manifest.
- Gate fail-closed `BOZZA_DIAGNOSTICA → CANTIERE` e registrazione dell'approvazione professionale esterna.

### Metriche di uscita — Gate 3 HVAC

- Tutti i criteri `P3-HVAC-*` e `P3-RE-*` superati su casi indipendenti verificati da professionisti.
- Zero incongruenze, collisioni critiche o modifiche occulte al modello P2.
- Calcoli e reti ricalcolabili entro tolleranze approvate; componenti e dati interamente tracciati.
- 100% casi incompleti/sotto confidenza bloccati da `CANTIERE`.
- E2E riproducibile P1 → P2 → writer, con fascicolo completo e approvazione del professionista abilitato.
- Zero difetti critici e delibera congiunta product owner, responsabile tecnico, QA e professionista HVAC.

### Nuovi writer

Dopo Gate 3 HVAC, ogni nuovo dominio richiede sponsor, dati, norme, professionista, plugin isolato, criteri e un proprio Gate 3. Nessun writer eredita automaticamente la validazione HVAC.

### Consumer PlanNL dopo Gate 2

PlanNL non è un writer P3 e i tre punti non diventano quattro. Dopo Gate 2 può aprire un proprio percorso di release downstream, separato da Plan2HVAC, con questi vincoli:

- consuma soltanto il contratto/API versionato di PlanParser;
- non importa moduli interni, non legge database di PlanParser e non condivide stato mutabile;
- non modifica né corregge geometria, topologia, misure o confidenze;
- risponde con riferimenti agli ID/versioni dell'input e dice “dato non disponibile” quando manca evidenza;
- supera contract test, answer-grounding test, negative test e test di immutabilità prima della release.

La validazione di PlanNL non sostituisce Gate 3 di Plan2HVAC e viceversa.

### Dipendenze

Gate 2, dati edificio/clima, cataloghi, norme vigenti, casi professionali e revisori abilitati.

### Rischi e mitigazioni

- **Writer che corregge il modello:** input P2 immutabile; errori rispediti al gate precedente.
- **Dati tecnici inventati:** fail closed e lineage obbligatorio.
- **Software presentato come firmatario:** separazione dei ruoli; il software non firma, assevera o dichiara conformità.

### Ruoli

Product owner P3, writer/domain lead, calculation/network lead, drawing/document lead, QA/release lead, responsabile normativo, security e professionista abilitato.

---

## Dopo Gate 3 — Ecosistema e standardizzazione

API ecosistemiche, SDK, plugin, nuovi writer, programmi partner, specifica pubblica, governance, standard de facto e percorso istituzionale iniziano soltanto dopo Gate 3 del primo writer. La loro maturità sarà definita da gate separati quando P3 sarà chiuso; non sono attività operative correnti. Le API minime tra super-servizi, invece, sono deliverable tecnici di P2 necessari a separare PlanParser dai consumer.

### Interoperabilità futura già vincolante come requisito di P2

- [ISO 16739-1:2024](https://www.iso.org/standard/84123.html): mapping IFC per profilo/caso d'uso, validazione indipendente e perdita dichiarata.
- [Serie UNI 11337](https://www.uni.com/edilizia-e-opere-di-ingegneria-civile/): requisiti, stati, ruoli e processi informativi applicati parte-per-parte e per edizione vigente.
- [ISO 19650-1:2018](https://www.iso.org/standard/68078.html): scopo, destinatari, requisiti, scambio, registrazione, versionamento e organizzazione degli artefatti; profilo aggiornato quando cambia l'edizione.

Questi mapping appartengono alla formalizzazione controllabile di PlanParser. Non trasformano PlanimetryDigitalConventions nel contratto operativo: quel prodotto resta futuro, separato e fuori scope.

---

## Programma studenti ITIS e indirizzo geometra — interno a P1

- Accordi scritti con scuole, docenti, famiglie/tutori ove applicabile; finalità, tempi, compensi, sicurezza, privacy e proprietà dei risultati espliciti.
- Formazione su tavole, tassonomia, strumenti, ambiguità, astensione, qualità e protezione dati; abilitazione progressiva tramite golden task.
- QA multilivello: controlli automatici, golden task, doppia annotazione/consensus, revisione senior/docente e revisione professionale obbligatoria per significati tecnici.
- Remunerazione equa e trasparente; eventuali percorsi formativi non diventano produzione gratuita mascherata; carichi e pause compatibili con età e scuola.
- Minorenni esclusi da dati ad alto rischio/non anonimizzati; least privilege, ambienti segregati, retention limitata, reclamo e ritiro senza ritorsioni.
- Gli studenti non approvano ground truth tecnica finale, calcoli, classificazioni normative o output `CANTIERE` e non sostituiscono professionisti.
- Il programma si sospende automaticamente se tutela, privacy, valore formativo o qualità non sono dimostrabili.

## Registro di avanzamento

Il board registra per ogni gate: hash delle evidenze, metriche per sottogruppo, rischi residui, firme/approvazioni, decisione e condizioni di riapertura. Lo stato corrente resta `P1 ATTIVO / P2 BLOCCATO / P3 BLOCCATO` fino a verbale formale contrario.
