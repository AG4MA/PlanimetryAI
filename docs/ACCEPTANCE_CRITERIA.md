# Criteri di accettazione sequenziali PlanimetryAI

**Stato:** `P1 ATTIVO` — `P2 BLOCCATO DAL GATE 1` — `P3 BLOCCATO DAL GATE 2`  
**Sequenza vincolante:** `P1 SCOMPORRE → GATE 1 → P2 FORMALIZZARE/CONTROLLARE → GATE 2 → P3 SCRIVERE → GATE 3`

## Prodotti e responsabilità

- **PlanParser** possiede P1 e P2: parte da PDF/immagini e termina con una formalizzazione controllabile pubblicata tramite contratto/API.
- **PlanNL** è un consumer downstream distinto: interroga la formalizzazione senza inventare o correggere la geometria.
- **Plan2HVAC** è un consumer/writer downstream distinto: produce un layer HVAC separato e in scala, senza mutare la base.
- **PlanimetryDigitalConventions** è un prodotto futuro fuori scope; non è P2 e non è il contratto operativo corrente fra servizi.

I prodotti sono super-servizi indipendenti. L'accettazione vieta import interni tra prodotti, database condivisi e accessi diretti allo storage altrui; l'integrazione avviene esclusivamente tramite contratti/API versionati.

## Regole comuni

- I criteri del punto bloccato sono specifiche future, non autorizzazione a svilupparlo o prova di avanzamento.
- Ogni gate usa un dataset congelato e indipendente, metriche approvate, test riproducibili ed evidenze con hash.
- Tutte le celle `DA CONCORDARE` del gate devono essere risolte prima della delibera.
- Una media aggregata non compensa errori critici o regressioni nei sottogruppi.
- Il gate successivo non può iniziare senza verbale `GO`; un fallimento upstream blocca o riapre tutto il downstream.

## Gate 1 — PlanParser/P1 Scomporre perfettamente (`ATTIVO`)

| ID | Requisito | Evidenza / dataset | Metrica / test | Soglia | Approvatore |
|---|---|---|---|---|---|
| P1-01 | Ingerire PDF e raster supportati, incluse pagine/tavole multiple | Corpus formati/codec/qualità: **DA CONCORDARE** | Test parametrico ingestione e rifiuto | 100% corpus gestito o rifiutato strutturalmente; zero crash | QA lead |
| P1-02 | Tassonomia atomica completa e versionata | Manuale, esempi, casi ambigui e class owner | Review copertura e golden task | 100% classi obbligatorie definite con regole/owner | Product owner + data lead |
| P1-03 | Separare documenti, pagine, tavole, riquadri e piani | Dataset annotato: **DA CONCORDARE** | Precision/recall/F1 e associazione sorgente | **DA CONCORDARE** | Data QA lead |
| P1-04 | Estrarre primitive, contorni, retini e geometria architettonica | Ground truth vettoriale: **DA CONCORDARE** | Precision/recall; IoU; errore distanza/lunghezza/spessore | **DA CONCORDARE**; 100% geometrie emesse valide | Geometry lead + revisore tecnico |
| P1-05 | Rilevare ambienti, perimetri, pareti e spessori | Ground truth per sottogruppo: **DA CONCORDARE** | Detection F1, IoU, errore metrico | **DA CONCORDARE** | Geometry lead + revisore tecnico |
| P1-06 | Rilevare porte, finestre, passaggi, scale ed elementi obbligatori | Annotazioni elementi: **DA CONCORDARE** | Precision/recall per classe; errore posizione/dimensione | **DA CONCORDARE** | Revisore tecnico |
| P1-07 | Estrarre testi, label, numeri, quote, simboli e legende | Trascrizioni verificate: **DA CONCORDARE** | CER/WER e accuracy campi tecnici | **DA CONCORDARE**; 100% dati non rilevati marcati mancanti | OCR lead + data QA |
| P1-08 | Ricavare scala, misure e orientamento senza inventarli | Tavole con ground truth e casi assenti: **DA CONCORDARE** | Errore lunghezze/aree/angolo; accuracy astensione | **DA CONCORDARE** | Revisore tecnico |
| P1-09 | Estrarre appartenenze e relazioni osservabili | Grafo/relazioni ground truth: **DA CONCORDARE** | Precision/recall archi; simmetria e riferimenti | **DA CONCORDARE**; zero riferimenti orfani nell'output P1 | Data model observer |
| P1-10 | Esporre provenienza e confidenza calibrata | Dataset corretto/errato/OOD: **DA CONCORDARE** | ECE/Brier, coverage-risk, OOD e astensione | **DA CONCORDARE**; nessun dato incerto sintetizzato | ML/evaluation lead |
| P1-11 | Operare senza correzione geometrica manuale ordinaria | Test congelato completo | Audit interventi | 0 correzioni/tracciature manuali per superare i casi accettati | Product owner |
| P1-12 | Garantire lineage e riproducibilità pixel/vettore → elemento | Manifest dati/modello/config/run | Re-run ed evidence trace | 100% elementi tracciabili; output semanticamente deterministico | QA/release lead |
| P1-13 | Industrializzare Data Factory e labeling | Registry, app, audit, golden/consensus/escalation | IAA, golden accuracy, audit revisioni | Soglie per task: **DA CONCORDARE**; 100% label tecniche revisionate | Data Factory lead + professionista |
| P1-14 | Governare augmentation, training, evaluation e active learning | Pipeline/model registry e benchmark congelato | Reproducibility, regression, leakage e rollback test | Zero leakage; zero regressioni critiche; soglie modello: **DA CONCORDARE** | ML/MLOps + QA |
| P1-15 | Proteggere dati e partecipanti, inclusi studenti/minorenni | Licenze, privacy, accessi, accordi, remunerazione e audit | Privacy/security/safeguarding review | 100% asset autorizzati; zero incidenti critici aperti; programma approvato | DPO/legal + safeguarding lead |
| P1-16 | Riconoscere input fuori dominio e fallire in modo controllato | Corpus OOD/corrotto/ostile: **DA CONCORDARE** | Detection OOD, negative/fuzz test | **DA CONCORDARE**; zero falsa dichiarazione di completezza | Security/QA + ML lead |

### Delibera Gate 1

Richiede: tutti i `P1-*` superati, tutte le soglie definite, zero difetti critici, dataset congelato non contaminato e verbale `GO GATE 1` del product owner con QA, data lead e revisori. Fino ad allora P2 e P3 restano bloccati.

## Gate 2 — PlanParser/P2 Formalizzare e controllare (`BLOCCATO DAL GATE 1`)

| ID | Requisito futuro | Evidenza | Metrica / test | Soglia | Approvatore |
|---|---|---|---|---|---|
| P2-01 | Knowledge Model canonico, schema e semantica versionati | Schema, vocabolari, fixture e changelog | Schema/conformance test | 100% validi accettati e invalidi rifiutati | Architecture lead |
| P2-02 | Unità, coordinate, trasformazioni e geometria metrica esplicite | Fixture a risultato noto | Round-trip e controlli dimensionali | Entro soglie P1 approvate; zero unità implicite | Geometry + architecture lead |
| P2-03 | Identificativi, relazioni, topologia e vincoli deterministici | Fixture invalide/valide | Invariant/constraint test | Zero duplicati, orfani o incoerenze | Validator lead |
| P2-04 | Provenienza, confidenza, revisioni e audit trail | Fixture observed/derived/override | Lineage e history test | 100% dati critici tracciati; zero default occulti | QA + information manager |
| P2-05 | Validator strutturale, geometrico, topologico e dimensionale | Corpus Gate 1 e negative fixture | Detection difetti e falsi esiti | **DA CONCORDARE**; 100% difetti critici noti bloccati | QA/conformance lead |
| P2-06 | Viewer canonico e strumenti di misura/ispezione/query | Scenari utente e valori noti | Usability, visual/measurement consistency | **DA CONCORDARE**; zero discrepanze critiche | Product owner P2 + revisore tecnico |
| P2-07 | Override eccezionali espliciti e auditabili | Fixture edit/review | Permission, diff e provenance test | 100% override attribuiti/versionati/reversibili | Security + QA |
| P2-08 | Migrazioni e serializzazione riproducibili | Versioni supportate | Migration/rollback/determinism test | Zero perdita non dichiarata; policy versioni: **DA CONCORDARE** | Architecture lead |
| P2-09 | Mapping IFC e processi informativi verificabili | Profili ISO 16739/UNI 11337/ISO 19650 | Coverage, loss report, independent round-trip | Soglie per profilo: **DA CONCORDARE**; nessun claim generico | Interoperability lead |
| P2-10 | Controllo completo su tutti i casi ammessi da Gate 1 | Dataset Gate 1 congelato | E2E decomposizione → modello → viewer/validator | 100% casi conformi o rifiutati con motivazione | Product owner P2 + QA |
| P2-11 | Pubblicare contratto/API autonomo di PlanParser | Specifica API, schema, fixture consumer e compatibility policy | Contract, compatibility e black-box test | 100% fixture consumabili senza import interni, database/storage condivisi; version/hash esposti | Architecture + API lead |

### Delibera Gate 2

Può essere valutata soltanto dopo `GO GATE 1`. Richiede tutti i `P2-*` superati, zero difetti critici e verbale `GO GATE 2`. Fino ad allora P3 resta bloccato; prototipi HVAC non valgono come evidenza.

## Release downstream PlanNL (`BLOCCATA DAL GATE 2`)

PlanNL non è P2 e non è un writer P3. Dopo Gate 2 viene accettato come consumer read-only distinto mediante i criteri seguenti; il suo esito non sostituisce Gate 3 HVAC.

| ID | Requisito futuro | Evidenza | Metrica / test | Soglia | Approvatore |
|---|---|---|---|---|---|
| NL-01 | Consumare soltanto contratto/API pubblici di PlanParser | Deploy separati e fixture versionate | Architecture/contract test | Zero import interni, query a database o storage condiviso | Architecture lead |
| NL-02 | Non mutare/correggere la formalizzazione | Snapshot input prima/dopo e richieste avverse | Immutability/authorization test | Zero mutazioni di geometria, topologia, misure o confidenza | Security + QA |
| NL-03 | Rispondere soltanto con dati presenti e riferimenti verificabili | Corpus Q&A grounded: **DA CONCORDARE** | Exact/semantic accuracy e citation-to-ID check | **DA CONCORDARE**; 100% risposte tecniche riferite a input/versione | PlanNL product owner + QA |
| NL-04 | Astenersi quando il dato manca o è insufficiente | Casi negativi/ambigui/OOD: **DA CONCORDARE** | Abstention precision/recall | **DA CONCORDARE**; zero valori geometrici inventati | QA + revisore tecnico |
| NL-05 | Isolare failure e versioni | Versioni supportate/non supportate, timeout e input invalidi | Compatibility/resilience test | Fail closed con errore strutturato; nessuna alterazione di PlanParser | Release lead |

## Gate 3 — Plan2HVAC/P3 Scrivere sopra (`BLOCCATO DAL GATE 2`)

### Writer HVAC iniziale

| ID | Requisito futuro | Evidenza | Metrica / test | Soglia | Approvatore |
|---|---|---|---|---|---|
| P3-HVAC-01 | Consumare esclusivamente il contratto/API PlanParser valido e una base immutabile | Deploy separati e fixture valide/invalide/incomplete | Architecture, contract, immutability e negative test | 100% input invalidi bloccati; zero import interni/database condivisi/correzioni occulte | HVAC lead + QA |
| P3-HVAC-02 | Calcolare carichi ambiente con input/formule/unità tracciati | Casi professionali indipendenti: **DA CONCORDARE** | Confronto per ambiente/totale | Tolleranze: **DA CONCORDARE** | Professionista HVAC |
| P3-HVAC-03 | Dimensionare terminali e generatori da cataloghi versionati | Cataloghi e casi verificati: **DA CONCORDARE** | Copertura, modulazione, limiti, SKU lineage | **DA CONCORDARE**; zero prodotti inventati | Professionista HVAC |
| P3-HVAC-04 | Dimensionare reti, portate, diametri, perdite, prevalenze e bilanciamento | Reti benchmark: **DA CONCORDARE** | Bilanci e confronto idraulico | **DA CONCORDARE** | Professionista HVAC |
| P3-HVAC-05 | Gestire layout, clash, dispositivi e condense applicabili | Modello P2 + casi installativi | Constraint/clash e review tecnica | Zero clash critici; criteri tecnici: **DA CONCORDARE** | Professionista HVAC |
| P3-HVAC-06 | Produrre tavole, relazione, distinta, posa e piano prove coerenti | Fascicoli attesi | Cross-check artefatti e ricalcolo | 100% campi/ID coerenti e risultati ricalcolabili | Professionista HVAC + QA |
| P3-HVAC-07 | Applicare profilo normativo versionato e ruoli corretti | Registro fonti e workflow | Audit applicabilità/ruoli | 100% fonti/edizioni/campo tracciati; software non firma | Responsabile normativo/legal |
| P3-HVAC-08 | Gate fail-closed per `CANTIERE` | Casi mancanti, low confidence e no approval | State-machine/authorization test | 100% casi negativi restano diagnostici | QA/security + professionista |

### Release ed E2E del writer

| ID | Requisito futuro | Evidenza | Metrica / test | Soglia | Approvatore |
|---|---|---|---|---|---|
| P3-RE-01 | E2E pulito P1 → P2 → HVAC | Ambiente e dataset congelati | Automated clean-run | 100% casi completano o falliscono controllatamente | Release lead |
| P3-RE-02 | Artefatti machine-readable e leggibili coerenti | JSON + PDF; extra: **DA CONCORDARE** | Parsing e cross-check | 100% apribili e senza discrepanze tecniche | QA + professionista |
| P3-RE-03 | Riproducibilità, sicurezza e archivio evidenze | Manifest/run ripetuti/negative corpus | Hash/equivalence/security/audit | 100% requisiti con evidenza; zero difetti critici | Release + security lead |
| P3-RE-04 | Approvazione professionale esterna autenticata | Meccanismo: **DA CONCORDARE** | Identity, scope, hash, timestamp e revoca | Senza approvazione valida mai `CANTIERE` | Legal + professionista abilitato |

### Delibera Gate 3

Può essere valutata soltanto dopo `GO GATE 2`. Richiede tutti i criteri del writer e release superati su casi indipendenti, zero incongruenze con P2, zero difetti critici e approvazione professionale. Il software non firma, assevera o dichiara conformità.

Ogni nuovo writer ripete un proprio Gate 3 con dataset, norme, metriche e professionista specifici; non eredita automaticamente l'accettazione HVAC.

## Prodotto futuro PlanimetryDigitalConventions

Non ha criteri operativi in questa baseline. Qualunque futuro gate deve essere approvato separatamente e non può essere usato come schema runtime, implementazione di P2 o dipendenza implicita di PlanParser, PlanNL o Plan2HVAC.

## Stato corrente obbligatorio

`P1 ATTIVO` — `P2 BLOCCATO DAL GATE 1` — `P3 BLOCCATO DAL GATE 2`.
