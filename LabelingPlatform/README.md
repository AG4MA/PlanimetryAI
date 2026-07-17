# LabelingPlatform

Piattaforma web della Data Factory di PlanimetryAI (interna a PlanParser/P1). Qui arrivano le planimetrie: ingestione di PDF e immagini, archiviazione immutabile, rendering delle pagine e consultazione. Il labelling vero e proprio (annotazioni, code di lavoro, QA) arriverà negli step successivi, dopo la prova di questa base.

## Architettura v0

```text
Browser (wwwroot: HTML/CSS/JS puri)
   │  upload multipart · lista · viewer zoom/pan
   ▼
LabelingPlatform.Api (.NET 10, minimal API)
   │
   ├── DocumentIngestionService
   │     spool → SHA-256 → dedup → archivio originale
   │     PDF  → pdfium (PDFtoImage) → PNG 200 DPI per pagina + thumbnail
   │     IMG  → ImageSharp → PNG normalizzato + thumbnail
   │
   ├── SQLite (EF Core) — indice documenti/pagine
   └── data/  — storage su filesystem, content-addressed
         originals/{sha256}.pdf|.png|…
         pages/{sha256}/p001.png
         thumbnails/{sha256}/p001.png
         labeling.db
```

Scelte vincolanti:

- **Identità = SHA-256 del contenuto**, come il manifest dataset di PlanParser (`PlanParser/dataset/DATASET_SPEC.md`): lo stesso file caricato due volte non viene duplicato e l'hash è il ponte verso le future voci di manifest.
- **L'originale non si tocca mai**: le pagine PNG sono derivati riproducibili.
- **Utente singolo, nessuna autenticazione** (decisione del responsabile per la v0).
- Nessun riferimento a codice interno di altri prodotti: la piattaforma è un servizio autonomo.

## Avvio

```powershell
cd LabelingPlatform/src/LabelingPlatform.Api
dotnet run
```

Poi aprire l'URL indicato in console (es. `http://localhost:5000`). I dati finiscono in `LabelingPlatform/data/` (escluso dal versionamento). Per cambiare posizione: `dotnet run --DataRoot=D:\percorso\dati`.

## API

| Metodo | Percorso | Descrizione |
|---|---|---|
| `POST` | `/api/documents` | Upload multipart (campo `file`): PDF o immagine. `201` con documento e pagine; `200` se identico contenuto già presente; `415` se non elaborabile |
| `GET` | `/api/documents` | Elenco documenti con pagine |
| `GET` | `/api/documents/{id}` | Dettaglio documento |
| `GET` | `/api/pages/{id}/image` | PNG pieno della pagina (200 DPI per i PDF) |
| `GET` | `/api/pages/{id}/thumbnail` | Thumbnail PNG (lato max 480 px) |
| `GET` | `/healthz` | Stato del servizio e data root |

## Prossimi step (dopo la prova del responsabile)

1. Entità `Annotation` + endpoint CRUD conformi al contratto di decomposizione P1 (`PlanParser/decomposition/decomposition.schema.json`).
2. Import delle pre-formalizzazioni degli algoritmi di PlanParser come proposte da confermare/correggere.
3. Coda di lavoro (tavola intera vs ritagli incerti) — UX da decidere con l'utente.
4. Export verso il manifest dataset (`PlanParser/dataset/`) con diritti/privacy per asset.
