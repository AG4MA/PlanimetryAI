# Ricognizione portali planimetrie — scoperte (2026-07-17)

Ricognizione **estensiva ma non massiva**: 18 portali sondati con un probe Python
dedicato ciascuno (≤4-12 richieste HTTP l'uno, robots rispettato, nessuna elusione
di blocchi anti-bot). Fonte di partenza: `PlanimetryAI/PlanParser/deep-research-report.md`.

## Verdetto sintetico

| Portale | Categoria | Esito | Doc. planimetria | Formati | Accesso | Bucket legale |
|---|---|---|---|---|---|---|
| **AsteAnnunci.it** | asta | 🟢 **massivo** | planimetrie PDF scaricate | pdf | download diretto, no login | public_document_internal_use |
| **AsteGiudiziarie.it** | asta | 🟢 **massivo** | planimetrie JPG + perizia PDF scaricate | jpg, pdf | download diretto, no login | public_document_internal_use |
| **PVP Giustizia** | asta | 🔴 WAF | API ricostruita (7.923 immobili, 793 pagine) ma ogni richiesta automatica → "Web Page Blocked" | — | json-api bloccata da WAF | public_document_internal_use |
| **dati.gov.it (CKAN)** | catalogo | 🟡 canale legale | 35 dataset, 77 risorse (36 PDF) — **ma urbanistiche/tecniche, non piante di unità** | pdf, zip, gml, shp | CKAN API `package_search` | open_ccby (CC BY 4.0) |
| Astalegale.net | asta | 🔴 robots | planimetria+perizia individuate ma `documents.astalegale.net` vietato da robots | — | html-crawl | public_document_internal_use |
| Fallco Aste | asta | 🔴 robots | pagine di dettaglio vietate da robots | — | — | tos_risk (vieta riproduzione) |
| Immobiliare.it | annunci | 🔴 bloccato | 403 DataDome alla 1ª richiesta | — | — | tos_risk |
| Casa.it | annunci | 🔴 bloccato | 403 DataDome/CloudFront alla 1ª richiesta | — | — | tos_risk |
| Idealista.it | annunci | 🔴 bloccato | 403 DataDome (captcha-delivery) alla 1ª richiesta | — | — | tos_risk |
| Catasto AE WMS/WFS | ufficiale | ⚪ backbone | 0 planimetrie (solo particelle/fogli/fabbricati) | gml, png | WMS/WFS | open_ccby (CC BY 4.0) |
| Geoportale Lazio | geoportale | ⚪ no target | 45 layer con keyword, ma tavole vettoriali PTPR/PRG, non file | shp, gml, geojson | WFS/CSW | open_ccby |
| Geoportale Emilia-Romagna | geoportale | ⚪ no target | DBTR/CTR (anche DWG), nessuna pianta di edificio | pdf, shp, tiff | OGC + download | open_ccby |
| Toscana GEOscopio | geoportale | ⚪ no target | cartografia territoriale, non edilizia | png, tiff, … | WMS/WFS | open_ccby |
| Sardegna Geoportale | geoportale | ⚪ no target | 378 layer WMS, nessuna keyword planimetria | png, geotiff | WMS/WFS | open_ccby |
| GeoRoma | geoportale | ⚪ no target | API documents 404, 0 link utili in home | — | html-crawl | open_ccby |
| Torino Geoportale | geoportale | ⚪ no target | tavole PRG citate ma non file diretti nel campione | — | html-crawl | open_ccby |
| RNDT (CSW) | catalogo | ⚪ discovery | 13 record `planimetri*`, 245 `elaborato planimetrico` — tavole urbanistiche, non catastali | jpg, png | CSW | open_ccby |
| Lombardia | geoportale | ⚪ non completato | run interrotta (fonte non-target) | — | — | open_ccby |

Legenda: 🟢 usabile per raccolta massiva · 🟡 recuperabile con lavoro mirato ·
🔴 disponibile ma non praticabile educatamente (robots/anti-bot) ·
⚪ funziona ma non fornisce piante di unità immobiliari.

## Conclusione operativa

Il filone giusto per il corpus PlanParser/P1 è quello delle **aste giudiziarie**:
espongono planimetrie e perizie come allegati scaricabili senza login, tipicamente
le piante catastali allegate alla perizia CTU — proprio il tipo di planimetria utile.

- **Raccolta massiva ATTIVA** → AsteAnnunci + AsteGiudiziarie. Adapter scritti e testati
  (`harvest/sites/`), harvester resumable in `harvest/`. Paginazione: AsteAnnunci
  `/aste-immobiliari/case/page/N` (~325 pagine × 12 schede); AsteGiudiziarie via sitemap
  gzip (~14.064 schede immobili).
- **PVP Giustizia — scartato dopo tentativo serio** → ripreso passo per passo con
  client paziente (sessione + cookie, delay 8-22s). Scoperte:
  1. l'endpoint di ricerca **corretto** è `ric-ms/ricerca/vendite` (non
     `ve-ms/vendite/ricerca`, che è un bug e dà 401): è **pubblico** e ha già
     restituito dati reali (7.923 immobili) durante la ricognizione;
  2. il portale è però frontato da un **WAF che filtra sull'identità del client**:
     con User-Agent onesto la homepage stessa risponde "Web Page Blocked / Attack ID";
     con User-Agent di browser la home passa e rilascia i cookie.
  Superare quel WAF in modo affidabile richiederebbe **impersonare un browser** (ed
  eventualmente gestire la reputazione IP): è elusione di un controllo anti-bot
  esplicito → **non lo faccio**. L'adapter resta in `harvest/sites/pvp_giustizia.py`
  con l'endpoint corretto documentato, come riferimento per un eventuale accesso
  ufficiale/autorizzato futuro.
- **Canale legale pulito ma tipo diverso** → dati.gov.it (CC BY 4.0): planimetrie
  urbanistiche/tecniche comunali, utili come materiale secondario, non piante di appartamenti.
- **Georeferenziazione** → Catasto AE WMS/WFS (CC BY 4.0): non dà planimetrie ma
  serve ad ancorare a terra quelle raccolte altrove (particelle/fogli).

## Portali scartati (probe + output cancellati)

astalegale, casa_it, catasto, emilia_romagna, fallco, georoma, idealista, immobiliare,
lazio, lombardia, rndt, sardegna, torino, toscana. Le loro scoperte restano in questa tabella.

## Note legali (dal deep-research-report)

- Le **planimetrie catastali ufficiali** dell'Agenzia Entrate NON sono open data:
  riservate agli aventi diritto o delegati. Non presenti in nessuna fonte aperta.
- Le planimetrie da **aste giudiziarie** sono documenti di procedura pubblicamente
  scaricabili: harvest per **uso analitico interno** con provenienza tracciata;
  **niente ripubblicazione** dei documenti originali su larga scala.
- Fallco vieta esplicitamente replica/riproduzione → bucket `tos_risk`, escluso.
- I portali di annunci (Immobiliare/Casa/Idealista) proteggono con anti-bot e non
  dichiarano licenze aperte sulle piante: esclusi per via programmatica.
