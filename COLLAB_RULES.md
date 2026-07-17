# Regole di collaborazione asincrona

## Obiettivo

Completare PlanimetryAI mantenendo il repository funzionante e verificabile.

## Ruoli

- **Coordinatore (`/root`)**: non esegue piu implementazione applicativa. E l'unica interfaccia autorizzata con l'utente; scompone il lavoro, assegna agenti, governa claim/handoff, legge le evidenze e aggiorna esclusivamente i file di coordinamento/governance necessari.
- **Agenti esecutori:** realizzano codice, documentazione tecnica e test nei file assegnati. Parlano soltanto con `/root` attraverso `ASYNC_LOG.md` o i canali inter-agente richiesti dal coordinatore. Contatto diretto con l'utente vietato.
- **Composizione del team:** il numero di agenti esecutori puo crescere su indicazione dell'utente; i claim restano individuali, espliciti e non sovrapposti.

Le eventuali voci storiche di agenti non piu attivi in `ASYNC_LOG.md` restano parte dell'audit trail, ma non conferiscono autorizzazioni correnti.

## Sequenza assoluta dei prodotti

1. Un solo prodotto puo avere stato operativo `ATTIVO`.
2. Il prodotto attivo corrente e `PlanParser`; al suo interno si chiude prima P1 e poi P2.
3. Finche `PlanParser` non e formalmente chiuso, `PlanNL`, `Plan2HVAC` e `PlanimetryDigitalConventions` restano congelati: niente ricerca, codice, test, integrazione o correzioni non conservative.
4. La chiusura richiede criteri superati, evidenze, zero difetti critici e decisione esplicita del responsabile del progetto.
5. Dopo la chiusura, il coordinatore non sceglie implicitamente il prodotto successivo: registra la decisione dell'utente e solo allora apre nuovi claim.
6. Il parallelismo e ammesso soltanto fra sottocompiti non sovrapposti del prodotto attivo.

## Regole operative

1. Prima di modificare un file, l'agente completa il protocollo `READY -> QUESTION/ANSWER -> AUTHORIZED -> CLAIMED`. `CLAIMED` senza precedente `AUTHORIZED` non consente scritture.
2. Non modificare file già assegnati all'altro agente senza accordo scritto nel log.
3. Ogni messaggio nel log include data/ora, agente, stato e percorsi coinvolti.
4. Stati ammessi: `INFO`, `READY`, `QUESTION`, `ANSWER`, `AUTHORIZED`, `CLAIMED`, `CHECKPOINT`, `PAUSED`, `BLOCKED`, `DONE`, `HANDOFF`.
5. Non eliminare o sovrascrivere modifiche preesistenti dell'utente.
6. Ogni blocco completato deve indicare verifiche eseguite e relativo esito.
7. Le decisioni architetturali e i cambi di scope passano dal coordinatore e richiedono conferma dell'utente quando modificano prodotti, responsabilita o gate.
8. Commit e pubblicazione remota si eseguono solo su richiesta esplicita dell'utente.
9. Un cambio di scope registrato in `docs/PROJECT_OBJECTIVE.md` prevale sui claim precedenti; il lavoro fuori scope va consegnato e preservato, ma non integrato nella release.
10. Il coordinatore non prende claim su codice applicativo: se un lavoro esecutivo resta incompleto, lo consegna a un agente con stato e verifiche note.

## Modalita obbligatoria degli agenti

Ogni agente opera in modalita `ESECUTORE_STRICT_FILE_BASED`:

1. legge i file canonici e il task packet senza scrivere;
2. registra `READY` con comprensione, input, output, non-obiettivi, file proposti e test previsti;
3. registra ogni ambiguita come `QUESTION` indirizzata esclusivamente a `/root`, anche se sembra piccola;
4. non risponde da solo alle proprie domande e non trasforma ipotesi in requisiti;
5. il coordinatore risponde dai requisiti gia approvati oppure, se serve una decisione, parla direttamente con l'utente e poi registra la risposta come `ANSWER`; l'agente non entra mai in quel dialogo;
6. soltanto il coordinatore registra `AUTHORIZED`, indicando scope, file e criteri finali;
7. l'agente registra `CLAIMED` e puo iniziare le modifiche;
8. ogni `AUTHORIZED` copre un solo micro-task esplicitamente descritto; al termine l'agente registra `CHECKPOINT` con evidenze e proposta del passo successivo, quindi attende un nuovo `AUTHORIZED`;
9. qualunque nuova ambiguita, dipendenza, conflitto o espansione di scope impone `PAUSED` o `BLOCKED` e una nuova domanda a `/root`;
10. `DONE` richiede evidenze e `HANDOFF`; non autorizza il prodotto o il punto successivo.

Il loop obbligatorio e:

`AGENTE -> QUESTION/READY/CHECKPOINT in ASYNC_LOG -> /root -> ANSWER/AUTHORIZED -> AGENTE`

L'utente comunica soltanto con `/root`. Gli agenti non chiedono all'utente cosa fare, non lo menzionano come destinatario operativo e non attendono una sua risposta diretta.

Sono vietati: assunzioni silenziose, valori/soglie inventati, nuove dipendenze non autorizzate, refactor collaterali, modifiche fuori claim, riparazioni dei test per nascondere difetti, uso di output downstream come prova upstream e dichiarazioni `GO` non deliberate.

## Task packet minimo

Il coordinatore non autorizza un task finche sono definiti almeno:

- obiettivo osservabile e non-obiettivi;
- input, output e loro contratti/versioni;
- file leggibili, file modificabili e file vietati;
- comportamento nominale, errori, casi limite e astensione;
- soglie/tolleranze oppure marcatura esplicita `DA DECIDERE`;
- dipendenze consentite, ambiente e limiti di compatibilita;
- sicurezza, privacy, licenze e dati disponibili quando applicabili;
- test obbligatori, fixture, comando di verifica e criterio di completamento;
- rischi noti, condizioni di pausa e contenuto dell'handoff.

Il modello completo da inviare a ogni nuovo agente e in `AGENT_ONBOARDING.md`.

## Protocollo di handoff

Un handoff deve specificare: risultato, file modificati, test eseguiti, problemi residui e prossimo passo consigliato.
