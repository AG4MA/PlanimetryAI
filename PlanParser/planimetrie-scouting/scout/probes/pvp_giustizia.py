"""Probe: PVP - Portale Vendite Pubbliche (pvp.giustizia.it).

Portale ufficiale delle vendite giudiziarie (categoria: auction; bucket legale:
public_document_internal_use). Il frontend e' un CMS Entando con micro-frontend
Angular; l'analisi offline del bundle della widget "area-annunci" (in cache)
ha rivelato l'API JSON interna:

  1. GET  {BASE}/bo-.../bo-ms/fe-config/area-annunci
        -> config runtime: { host, hostEntando, bucketsHost, msUrl: {ricerca, vendite, ...} }
  2. POST {host}/{msUrl.ricerca}/ricerca/vendite?language=it&isPreview=true&page=0&size=N
        body {"tipoLotto": "IMMOBILI", "filtroAnnunci": 0, "ricercaLibera": null}
        -> pagina Spring { content: [annunci], totalElements }
  3. GET  {host}/{msUrl.vendite}/allegato/{idEspVendita}
        -> metadati allegati dell'annuncio (perizia, planimetria, avviso...)
  4. download del file allegato (URL ricavato dai metadati / bucketsHost)

Disciplina di budget (max 12 richieste HTTP reali sommando TUTTE le run):
- ogni risposta e' messa in cache su disco (output/pvp_giustizia/cache/) e le
  run successive la riusano senza rifare la richiesta;
- un ledger in cache conta le richieste reali cumulative (incluse le fetch di
  robots.txt, che PoliteSession non conteggia, e i redirect);
- i passi facoltativi (allegati, download campioni) si fermano da soli quando
  il budget residuo cumulativo si esaurisce.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from scout.core import (
    OUTPUT_DIR,
    BudgetExceeded,
    Evidence,
    PoliteSession,
    ProbeResult,
    RobotsDisallowed,
    looks_like_protection,
)

SOURCE_ID = "pvp_giustizia"
SOURCE_NAME = "PVP - Portale Vendite Pubbliche (Giustizia)"
BASE = "https://pvp.giustizia.it"
ENTRY = BASE + "/pvp/"

OUT_DIR = OUTPUT_DIR / SOURCE_ID
CACHE_DIR = OUT_DIR / "cache"
LEDGER_PATH = CACHE_DIR / "ledger.json"

TOTAL_BUDGET = 12          # richieste reali cumulative su tutte le run
ROBOTS_CACHE_PATH = CACHE_DIR / "robots_cache.json"
PLAN_KEYWORDS = ("planimetr", "elaborato planimetrico", "perizia", "tavola", "floorplan")
FILEISH_KEYS = {
    "nomefile", "nome_file", "filename", "nomeallegato", "idallegato", "idfile",
    "urlfile", "estensione", "mimetype", "contenttype", "dimensione", "allegato",
    "tipoallegato", "tipodocumento", "iddocumento", "percorsofile", "path",
}
MAX_SAMPLE_BYTES = 5 * 1024 * 1024
MAX_SAMPLES = 2

_URL_STRING_RE = re.compile(r"[\"'`]((?:https?://|/)[^\"'`\s\\]{3,200})[\"'`]")
# base path dei microservizi Entando, es. /ve-3f723b85-986a1b71/ve-ms
_MS_BASE_RE = re.compile(r"(/(?:ve|bo|bdag|offerta)-[0-9a-f\-]{4,}/[a-z\-]{2,}ms)\b")


# ----------------------------------------------------------------- utilities

def _load_ledger() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {"total_real_requests": 0, "runs": 0}


def _run_real_requests(session: PoliteSession, ctx: dict) -> int:
    # fetch robots.txt per origine non pre-caricata da cache + redirect seguiti
    robots_fetches = len(session._robots) - ctx.get("robots_prefilled", 0)
    return session.requests_made + robots_fetches + ctx.get("redirect_hops", 0)


def _remaining_budget(session: PoliteSession, ctx: dict) -> int:
    return TOTAL_BUDGET - _load_ledger()["total_real_requests"] - _run_real_requests(session, ctx)


def _prefill_robots(session: PoliteSession, ctx: dict) -> None:
    """Riusa l'esito robots.txt osservato nelle run precedenti (nessun robots leggibile).

    E' una cache educata: evita di riscaricare robots.txt a ogni run. Vale solo
    per le origini gia' osservate SENZA robots leggibile; origini nuove o con
    robots presente vengono comunque verificate via rete da PoliteSession.
    """
    if not ROBOTS_CACHE_PATH.exists():
        ctx["robots_prefilled"] = 0
        return
    try:
        cached = json.loads(ROBOTS_CACHE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        ctx["robots_prefilled"] = 0
        return
    for origin in cached.get("none_origins", []):
        session._robots.setdefault(origin, None)
    ctx["robots_prefilled"] = len(cached.get("none_origins", []))


def _finalize_ledger(session: PoliteSession, ctx: dict, result: ProbeResult) -> None:
    ledger = _load_ledger()
    real = _run_real_requests(session, ctx)
    ledger["total_real_requests"] += real
    ledger["runs"] += 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger), encoding="utf-8")
    none_origins = sorted(o for o, parser in session._robots.items() if parser is None)
    ROBOTS_CACHE_PATH.write_text(
        json.dumps({"none_origins": none_origins}), encoding="utf-8"
    )
    result.notes.append(
        f"richieste reali questa run (incl. robots/redirect): {real}; "
        f"cumulative su tutte le run: {ledger['total_real_requests']} "
        "(requests_made riporta il cumulativo)"
    )
    # il campo requests_made del result.json finale deve riflettere il totale
    # reale cumulativo: standalone() copia session.requests_made nel result.
    session.requests_made = ledger["total_real_requests"]


def _fetch_cached(session: PoliteSession, ctx: dict, url: str, cache_name: str, *,
                  method: str = "get", params: dict | None = None,
                  json_body=None):
    """Ritorna (bytes|None, Response|None). Cache hit: nessuna richiesta.

    Solo le risposte HTTP 200 vengono messe in cache con il nome dato; gli
    errori finiscono in <cache_name>.error.txt per il debug offline.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / cache_name
    if path.exists():
        ctx["cache_hits"].append(cache_name)
        return path.read_bytes(), None
    if method == "post":
        resp = session.post(url, params=params, json=json_body)
    else:
        resp = session.get(url, params=params)
    ctx["redirect_hops"] = ctx.get("redirect_hops", 0) + len(resp.history)
    if resp.status_code == 200:
        path.write_bytes(resp.content)
        return resp.content, resp
    (CACHE_DIR / (cache_name + ".error.txt")).write_bytes(resp.content)
    return None, resp


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]


def _extract_endpoints(js_text: str) -> dict[str, list[str]]:
    hits = {m.group(1) for m in _URL_STRING_RE.finditer(js_text)}
    hits = {
        h for h in hits
        if not h.lower().endswith((".js", ".css", ".png", ".svg", ".ico", ".woff",
                                   ".woff2", ".ttf", ".jpg", ".gif", ".html", ".map"))
    }

    def pick(*subs: str) -> list[str]:
        return sorted(h for h in hits if any(s in h.lower() for s in subs))

    config = re.findall(
        r"(?:apiUrl|apiBaseUrl|baseUrl|urlBase|basePath)[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']",
        js_text,
    )
    return {
        "config_urls": sorted(set(config)),
        "ms_bases": sorted(set(_MS_BASE_RE.findall(js_text))),
        "search": pick("ricerca", "search"),
        "vendite": pick("vendit", "annunc", "inserz", "lotti", "immobil"),
        "allegati": pick("allegat", "document", "download", "file"),
        "api_all": pick("/api", "ms-", "rest"),
    }


def _walk_documents(obj) -> list[dict]:
    """Trova ricorsivamente i dict che sembrano allegati con keyword planimetria/perizia."""
    found: list[dict] = []
    if isinstance(obj, dict):
        keys = {k.lower() for k in obj}
        text = " ".join(str(v).lower() for v in obj.values() if isinstance(v, (str, int)))
        if (keys & FILEISH_KEYS) and any(kw in text for kw in PLAN_KEYWORDS):
            found.append(obj)
        for v in obj.values():
            found.extend(_walk_documents(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_walk_documents(v))
    return found


def _doc_label(doc: dict) -> str:
    for key in ("nomeFile", "nomefile", "nome_file", "filename", "nomeAllegato",
                "descrizione", "titolo", "tipoAllegato"):
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return "allegato"


def _doc_formats(docs: list[dict]) -> list[str]:
    fmts: list[str] = []
    for doc in docs:
        text = " ".join(str(v).lower() for v in doc.values() if isinstance(v, str))
        for ext in ("pdf", "p7m", "jpg", "jpeg", "png", "tif", "tiff", "dwg", "zip"):
            if f".{ext}" in text and ext not in fmts:
                fmts.append(ext)
    return fmts


def _candidate_file_url(doc: dict, buckets_host: str, host: str) -> str | None:
    """URL di download piu' plausibile dai metadati di un allegato."""
    for val in doc.values():
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            return val
    for key in ("percorsoFile", "percorsofile", "path", "urlFile", "urlfile"):
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            base = buckets_host or host or BASE
            return urljoin(base.rstrip("/") + "/", val.lstrip("/"))
    return None


def _download_sample(session: PoliteSession, ctx: dict, result: ProbeResult,
                     url: str, name_hint: str) -> bool:
    dest = OUT_DIR / _safe_name(name_hint)
    if dest.exists():
        result.notes.append(f"campione gia' presente, salto il download: {dest.name}")
        return True
    try:
        resp = session.get(url, stream=True)
    except (RobotsDisallowed, requests.RequestException) as exc:
        result.errors.append(f"download campione fallito {url}: {type(exc).__name__}: {exc}")
        return False
    ctx["redirect_hops"] = ctx.get("redirect_hops", 0) + len(resp.history)
    ctype = resp.headers.get("Content-Type", "")
    clen = int(resp.headers.get("Content-Length") or 0)
    if resp.status_code != 200 or looks_like_protection(resp):
        result.errors.append(f"download campione {url}: HTTP {resp.status_code} ({ctype})")
        return False
    if clen > MAX_SAMPLE_BYTES:
        result.notes.append(f"campione troppo grande ({clen} B), salto: {url}")
        return False
    data = b""
    for chunk in resp.iter_content(65536):
        data += chunk
        if len(data) > MAX_SAMPLE_BYTES:
            resp.close()
            result.notes.append(f"campione oltre 5MB durante il download, abortito: {url}")
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    fmt = "pdf" if (data[:5] == b"%PDF-" or "pdf" in ctype) else (ctype.split(";")[0] or "?")
    if fmt not in result.formats:
        result.formats.append(fmt)
    result.sample_documents.append(Evidence(
        url=url, status=resp.status_code, content_type=ctype,
        size_bytes=len(data), note=name_hint, saved_to=str(dest),
    ))
    return True


# ---------------------------------------------------------------------- probe

def probe(session: PoliteSession) -> ProbeResult:
    result = ProbeResult(
        source_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        category="auction",
        legal_bucket="public_document_internal_use",
    )
    ctx: dict = {"cache_hits": [], "redirect_hops": 0}
    _prefill_robots(session, ctx)
    try:
        _probe_inner(session, ctx, result)
    except RobotsDisallowed as exc:
        result.robots_allows = False
        result.errors.append(f"robots.txt vieta l'accesso: {exc}")
    except BudgetExceeded as exc:
        result.errors.append(f"budget richieste esaurito: {exc}")
    except requests.RequestException as exc:
        result.errors.append(f"errore di rete: {type(exc).__name__}: {exc}")
    if ctx["cache_hits"]:
        result.notes.append("artefatti riusati da cache: " + ", ".join(ctx["cache_hits"]))
    _finalize_ledger(session, ctx, result)
    return result


def _probe_inner(session: PoliteSession, ctx: dict, result: ProbeResult) -> None:
    # --- 1. raggiungibilita' + robots ---------------------------------------
    result.robots_allows = session.allowed_by_robots(ENTRY)
    home_bytes, home_resp = _fetch_cached(session, ctx, ENTRY, "home.html")
    if home_bytes is None:
        result.reachable = False
        if home_resp is not None and looks_like_protection(home_resp):
            result.blocked_by_protection = True
        result.errors.append(
            f"home non raggiungibile: HTTP {home_resp.status_code if home_resp else '?'}"
        )
        return
    home_html = home_bytes.decode("utf-8", errors="replace")
    result.reachable = True
    if home_resp is not None:
        result.notes.append(f"home: HTTP {home_resp.status_code}, {len(home_bytes)} B")
    else:
        result.notes.append("home da cache (run precedente: HTTP 200)")

    # --- 2. discovery: base bo-ms dalla home + endpoint dai bundle in cache --
    bo_match = re.search(r"(/bo-[0-9a-f\-]{4,}/bo-ms)", home_html)
    if not bo_match:
        result.errors.append("base bo-ms non trovata nella home: markup cambiato")
        result.programmatic = "partial"
        return
    bo_ms_base = bo_match.group(1)
    endpoint_parts = [_extract_endpoints(home_html)]
    for cached_bundle in ("area_annunci_main.js", "main.js"):
        bpath = CACHE_DIR / cached_bundle
        if bpath.exists():
            endpoint_parts.append(
                _extract_endpoints(bpath.read_bytes().decode("utf-8", errors="replace"))
            )
    merged: dict[str, list[str]] = {}
    for part in endpoint_parts:
        for key, vals in part.items():
            merged[key] = sorted(set(merged.get(key, [])) | set(vals))
    (CACHE_DIR / "endpoints.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- 3. config runtime della widget area-annunci ------------------------
    cfg_url = BASE + bo_ms_base + "/fe-config/area-annunci"
    cfg_bytes, cfg_resp = _fetch_cached(session, ctx, cfg_url, "fe_config.json")
    if cfg_bytes is None:
        status = cfg_resp.status_code if cfg_resp else "?"
        if cfg_resp is not None and looks_like_protection(cfg_resp):
            result.blocked_by_protection = True
        result.errors.append(f"fe-config non disponibile ({cfg_url}): HTTP {status}")
        result.programmatic = "partial"
        return
    try:
        cfg = json.loads(cfg_bytes.decode("utf-8", errors="replace"))
    except ValueError:
        result.errors.append("fe-config non e' JSON valido (vedi cache/fe_config.json)")
        result.programmatic = "partial"
        return
    host = (cfg.get("host") or BASE).rstrip("/")
    if not host.startswith("http"):
        host = BASE
    buckets_host = cfg.get("bucketsHost") or ""
    ms_url = cfg.get("msUrl") or {}
    ricerca_base = host + "/" + str(ms_url.get("ricerca", "")).strip("/")
    vendite_base = host + "/" + str(ms_url.get("vendite", "")).strip("/")
    result.notes.append(
        f"fe-config ok: host={host} ricerca={ms_url.get('ricerca')} "
        f"vendite={ms_url.get('vendite')} bucketsHost={buckets_host or '-'}"
    )
    if not ms_url.get("ricerca"):
        result.errors.append("fe-config senza msUrl.ricerca: impossibile chiamare la ricerca")
        result.programmatic = "partial"
        return

    # --- 4. ricerca annunci immobiliari (API JSON pubblica) -----------------
    search_url = ricerca_base + "/ricerca/vendite"
    search_bytes, search_resp = _fetch_cached(
        session, ctx, search_url, "search_vendite.json",
        method="post",
        params={"language": "it", "isPreview": "true", "page": 0, "size": 10},
        json_body={"tipoLotto": "IMMOBILI", "filtroAnnunci": 0, "ricercaLibera": None},
    )
    if search_bytes is None:
        status = search_resp.status_code if search_resp else "?"
        if search_resp is not None and looks_like_protection(search_resp):
            result.blocked_by_protection = True
        result.errors.append(f"ricerca vendite fallita ({search_url}): HTTP {status}")
        result.programmatic = "partial"
        return
    result.access_method = "json-api"
    try:
        payload = json.loads(search_bytes.decode("utf-8", errors="replace"))
    except ValueError:
        result.errors.append("risposta ricerca non JSON (vedi cache/search_vendite.json)")
        result.programmatic = "partial"
        return
    # le risposte sono avvolte in {"messaggio": ..., "body": ..., "error": ...}
    page = payload.get("body") if isinstance(payload, dict) and "body" in payload else payload
    page = page or {}
    annunci = page.get("content") or []
    total = page.get("totalElements")
    result.notes.append(
        f"ricerca IMMOBILI: {len(annunci)} annunci nella pagina campione, "
        f"totalElements={total}"
    )

    # --- 5. allegati dei primi annunci (tenendo 1 richiesta per il download) -
    plan_docs: list[dict] = _walk_documents(page)
    for annuncio in annunci[:3]:
        ann_id = annuncio.get("id")
        if ann_id is None:
            continue
        if _remaining_budget(session, ctx) < 2:
            result.notes.append("budget cumulativo quasi esaurito: stop richieste allegati")
            break
        alle_url = vendite_base + f"/allegato/{ann_id}"
        alle_bytes, alle_resp = _fetch_cached(
            session, ctx, alle_url, f"allegati_{ann_id}.json"
        )
        if alle_bytes is None:
            status = alle_resp.status_code if alle_resp else "?"
            result.notes.append(f"allegati annuncio {ann_id}: HTTP {status}")
            continue
        try:
            alle_payload = json.loads(alle_bytes.decode("utf-8", errors="replace"))
        except ValueError:
            result.errors.append(f"allegati annuncio {ann_id}: risposta non JSON")
            continue
        docs = _walk_documents(alle_payload)
        result.notes.append(
            f"annuncio {ann_id}: {len(docs)} allegati con keyword planimetria/perizia"
        )
        plan_docs.extend(docs)
        if docs:
            break  # un annuncio con allegati keyword basta per il campione
    result.plan_documents_found = len(plan_docs)
    for fmt in _doc_formats(plan_docs):
        if fmt not in result.formats:
            result.formats.append(fmt)

    # --- 6. download campioni (<5MB, entro il budget cumulativo) ------------
    downloaded = 0
    skipped_cost = False
    for doc in plan_docs:
        if downloaded >= MAX_SAMPLES:
            break
        url = _candidate_file_url(doc, buckets_host, host)
        if not url:
            continue
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        cost = 1 + (0 if origin in session._robots else 1)  # +1 se serve robots nuovo
        if _remaining_budget(session, ctx) < cost:
            skipped_cost = True
            continue
        if _download_sample(session, ctx, result, url, _doc_label(doc)):
            downloaded += 1
    if skipped_cost:
        result.notes.append(
            "download campione saltato: il budget cumulativo residuo non copre "
            "la richiesta (piu' eventuale robots.txt di un nuovo dominio)"
        )
    if plan_docs and not downloaded and not any(
        _candidate_file_url(d, buckets_host, host) for d in plan_docs
    ):
        result.notes.append(
            "metadati allegati senza URL diretto: serve l'endpoint file del "
            "widget di dettaglio (vedi cache/allegati_*.json)"
        )

    # --- 7. verdetto ---------------------------------------------------------
    if downloaded and result.plan_documents_found:
        result.programmatic = "yes"
        result.yield_estimate = "high"
    elif result.plan_documents_found:
        result.programmatic = "partial"
        result.yield_estimate = "medium" if not downloaded else "high"
    elif annunci:
        result.programmatic = "partial"
        result.yield_estimate = "low"
    else:
        result.programmatic = "no"
        result.yield_estimate = "none"


if __name__ == "__main__":
    from scout.core import standalone
    standalone(probe, SOURCE_ID)
