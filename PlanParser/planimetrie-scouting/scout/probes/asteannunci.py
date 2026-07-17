"""Probe di ricognizione per AsteAnnunci (www.asteannunci.it).

Portale di annunci di aste giudiziarie (gruppo Edicom): l'obiettivo e' capire se
le schede-annuncio espongono allegati planimetria/perizia scaricabili in modo
programmatico, con quali formati e con quale resa attesa.

Strategia (budget-conscious, max ~8 richieste contate per run):
  1. robots.txt + homepage;
  2. individuazione link a pagina elenco/ricerca e/o schede annuncio;
  3. visita di 1-2 schede annuncio, conteggio allegati con parole chiave
     (planimetria, elaborato planimetrico, perizia, tavola, floorplan);
  4. download di 1-3 campioni piccoli (<5MB) se consentito da robots e senza auth.

Tutte le pagine grezze vengono salvate in output/asteannunci/cache/ per il
debug offline.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scout.core import (
    OUTPUT_DIR,
    BudgetExceeded,
    Evidence,
    PoliteSession,
    ProbeResult,
    RobotsDisallowed,
    looks_like_protection,
)

SOURCE_ID = "asteannunci"
SOURCE_NAME = "AsteAnnunci (aste giudiziarie, gruppo Edicom)"
BASE_URL = "https://www.asteannunci.it/"

CACHE_DIR = OUTPUT_DIR / SOURCE_ID / "cache"
SAMPLE_DIR = OUTPUT_DIR / SOURCE_ID

MAX_SAMPLE_BYTES = 5 * 1024 * 1024
MAX_SAMPLES = 2  # prudenziale: il tetto di missione e' 3 campioni per fonte
# tetto interno prudenziale di richieste contate per run (robots escluso dal contatore)
SOFT_REQUEST_CAP = 8

# parole chiave dei documenti-planimetria richieste dal mandato
DOC_KEYWORDS = re.compile(
    r"planimetri\w*|elaborato\s+planimetric\w*|perizi\w*|\btavol\w*|floor\s*_?plan",
    re.I,
)
# sottoinsieme "planimetria in senso stretto" (per le note)
STRICT_PLAN_KEYWORDS = re.compile(
    r"planimetri\w*|elaborato\s+planimetric\w*|floor\s*_?plan", re.I
)

FILE_EXT_RE = re.compile(r"\.(pdf|p7m|jpe?g|png|tiff?|gif|dwg|dxf|zip)(?:$|[?#])", re.I)
LISTING_HINT_RE = re.compile(
    r"ricerca|risultati|elenco|vendite|aste(?!rischi)|annunc|immobil|search|lista", re.I
)
DETAIL_HINT_RE = re.compile(r"scheda|dettagl|annunci?o|vendita|immobile|lotto|\basta\b", re.I)
# le schede residenziali hanno piu' spesso allegati planimetria espliciti
RESIDENTIAL_RE = re.compile(
    r"abitazion|appartament|villa\b|villini|casa\b|porzione-di-immobile|residenzial", re.I
)


def _cache(name: str, content: bytes) -> str:
    path = PoliteSession.save_bytes(content, CACHE_DIR, name)
    return str(path)


def _clean_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(fragment)).strip()


def _extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Ritorna coppie (url assoluto, testo ancora) da un HTML."""
    links: list[tuple[str, str]] = []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        text = _clean_text(a.get_text(" "))
        title = _clean_text(a.get("title", ""))
        label = text if text else title
        if title and title.lower() not in label.lower():
            label = f"{label} {title}".strip()
        links.append((urljoin(base_url, href), label))
    return links


def _same_host(url: str, host: str) -> bool:
    return urlparse(url).netloc.lower().endswith(host.lower().lstrip("www."))


def _pick_listing_urls(links: list[tuple[str, str]], host: str) -> list[str]:
    seen: set[str] = set()
    picked: list[str] = []
    for url, text in links:
        if not _same_host(url, host):
            continue
        blob = f"{url} {text}"
        if LISTING_HINT_RE.search(blob) and not FILE_EXT_RE.search(url):
            key = url.split("#")[0]
            if key not in seen:
                seen.add(key)
                picked.append(key)
    return picked


def _pick_detail_urls(links: list[tuple[str, str]], host: str) -> list[str]:
    seen: set[str] = set()
    picked: list[str] = []
    for url, text in links:
        if not _same_host(url, host):
            continue
        if FILE_EXT_RE.search(url):
            continue
        blob = f"{url} {text}"
        # una scheda annuncio ha di norma un id numerico nel percorso o in query;
        # su asteannunci.it il pattern canonico e' /aste/<id>/<categoria>/<slug>
        if re.search(r"/aste/\d{4,}/", url) or (
            DETAIL_HINT_RE.search(blob) and re.search(r"\d{3,}", url)
        ):
            # via frammenti e query di tracking (_gl, gclid...): la scheda e' path-based
            key = url.split("#")[0].split("?")[0]
            if key not in seen:
                seen.add(key)
                picked.append(key)
    # prima le schede residenziali: sono quelle con piu' allegati planimetria
    picked.sort(key=lambda u: 0 if RESIDENTIAL_RE.search(u) else 1)
    return picked


def _pick_doc_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Link a documenti (allegati) che matchano le parole chiave del mandato."""
    docs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, text in _extract_links(html, base_url):
        blob = f"{url} {text}"
        if DOC_KEYWORDS.search(blob) and (
            FILE_EXT_RE.search(url)
            or re.search(r"download|allegat|document|file|attach|view|pdf", url, re.I)
        ):
            if url not in seen:
                seen.add(url)
                docs.append((url, text))
    # URL di file "nudi" fuori dalle ancore (js, attributi data-*)
    for m in re.finditer(r"https?://[^\s\"'<>\\]+?\.(?:pdf|p7m|jpe?g|png|tiff?|dwg)\b[^\s\"'<>\\]*", html, re.I):
        url = unescape(m.group(0))
        if DOC_KEYWORDS.search(url) and url not in seen:
            seen.add(url)
            docs.append((url, ""))
    return docs


def _format_from(url: str, content_type: str = "", head: bytes = b"") -> str:
    m = FILE_EXT_RE.search(urlparse(url).path)
    if m:
        ext = m.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "pdf"
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    if "png" in ct:
        return "png"
    if "zip" in ct:
        return "zip"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8"):
        return "jpg"
    if head.startswith(b"\x89PNG"):
        return "png"
    return "sconosciuto"


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return s or fallback


def _fetch_page(session: PoliteSession, url: str, cache_name: str, result: ProbeResult):
    """GET con salvataggio cache e rilevamento protezioni. Ritorna Response o None."""
    try:
        resp = session.get(url)
    except RobotsDisallowed:
        result.notes.append(f"robots.txt vieta {url}: pagina saltata")
        return None
    except requests.RequestException as exc:
        result.errors.append(f"errore rete su {url}: {exc}")
        return None
    body = resp.content or b""
    saved = _cache(cache_name, body)
    if looks_like_protection(resp):
        result.blocked_by_protection = True
        result.notes.append(
            f"possibile protezione anti-bot su {url} (HTTP {resp.status_code}); "
            f"grezzo in {saved}; nessun tentativo di elusione"
        )
        return None
    if resp.status_code != 200:
        result.errors.append(f"HTTP {resp.status_code} su {url} (grezzo in {saved})")
        return None
    return resp


def _download_sample(session: PoliteSession, url: str, label: str, idx: int, result: ProbeResult) -> None:
    try:
        resp = session.get(url, stream=True)
    except RobotsDisallowed:
        result.notes.append(f"robots.txt vieta il download di {url}")
        return
    except requests.RequestException as exc:
        result.errors.append(f"errore rete scaricando {url}: {exc}")
        return
    ev = Evidence(url=url, status=resp.status_code,
                  content_type=resp.headers.get("Content-Type", ""))
    if looks_like_protection(resp):
        result.blocked_by_protection = True
        ev.note = "risposta tipo challenge/blocco: download non eseguito"
        result.sample_documents.append(ev)
        resp.close()
        return
    if resp.status_code != 200:
        ev.note = "status non 200: download scartato"
        result.sample_documents.append(ev)
        resp.close()
        return
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_SAMPLE_BYTES:
        ev.size_bytes = int(declared)
        ev.note = "oltre 5MB dichiarati: scartato senza scaricare il corpo"
        result.sample_documents.append(ev)
        resp.close()
        return
    chunks: list[bytes] = []
    total = 0
    aborted = False
    try:
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_SAMPLE_BYTES:
                aborted = True
                break
            chunks.append(chunk)
    except requests.RequestException as exc:
        result.errors.append(f"errore in streaming da {url}: {exc}")
        resp.close()
        return
    finally:
        resp.close()
    if aborted:
        ev.size_bytes = total
        ev.note = "superati 5MB in streaming: download interrotto e scartato"
        result.sample_documents.append(ev)
        return
    body = b"".join(chunks)
    head = body[:8]
    fmt = _format_from(url, ev.content_type, head)
    if head[:5].lower() in (b"<!doc", b"<html") or "text/html" in ev.content_type.lower():
        ev.size_bytes = len(body)
        ev.note = "risposta HTML (probabile viewer/redirect applicativo), non un documento diretto"
        ev.saved_to = _cache(f"sample_{idx}_response.html", body)
        result.sample_documents.append(ev)
        return
    name = f"sample_{idx}_{_slug(label, 'documento')}.{fmt if fmt != 'sconosciuto' else 'bin'}"
    path = PoliteSession.save_bytes(body, SAMPLE_DIR, name)
    ev.size_bytes = len(body)
    ev.saved_to = str(path)
    ev.note = f"campione {fmt} salvato ({label or 'senza etichetta'})"
    result.sample_documents.append(ev)
    if fmt not in result.formats and fmt != "sconosciuto":
        result.formats.append(fmt)


def probe(session: PoliteSession) -> ProbeResult:
    result = ProbeResult(
        source_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        category="auction",
        legal_bucket="public_document_internal_use",
    )
    host = urlparse(BASE_URL).netloc

    # robots.txt (la fetch avviene qui, una sola volta per dominio)
    result.robots_allows = session.allowed_by_robots(BASE_URL)

    try:
        # 1) homepage
        resp = _fetch_page(session, BASE_URL, "home.html", result)
        if resp is None:
            return result
        result.reachable = True
        home_html = resp.text
        final_base = str(resp.url)
        if urlparse(final_base).netloc != host:
            result.notes.append(f"redirect della homepage verso {final_base}")
            host = urlparse(final_base).netloc

        links = _extract_links(home_html, final_base)
        detail_urls = _pick_detail_urls(links, host)
        doc_links: list[tuple[str, str]] = list(_pick_doc_links(home_html, final_base))

        # 2) se la home non offre schede, passa da una pagina elenco/ricerca
        if len(detail_urls) < 2:
            for listing_url in _pick_listing_urls(links, host)[:1]:
                lresp = _fetch_page(session, listing_url, "listing.html", result)
                if lresp is None:
                    continue
                llinks = _extract_links(lresp.text, str(lresp.url))
                detail_urls.extend(u for u in _pick_detail_urls(llinks, host) if u not in detail_urls)
                doc_links.extend(d for d in _pick_doc_links(lresp.text, str(lresp.url)) if d not in doc_links)
        if result.blocked_by_protection:
            return result

        # 3) fino a 2 schede annuncio
        visited = 0
        for durl in detail_urls:
            if visited >= 2 or session.requests_made >= SOFT_REQUEST_CAP - 1:
                break
            dresp = _fetch_page(session, durl, f"detail_{visited + 1}.html", result)
            visited += 1
            if dresp is None:
                if result.blocked_by_protection:
                    return result
                continue
            new_docs = _pick_doc_links(dresp.text, str(dresp.url))
            doc_links.extend(d for d in new_docs if d not in doc_links)
            result.notes.append(
                f"scheda {durl}: {len(new_docs)} allegati con parole chiave planimetria/perizia/tavola"
            )
        if not detail_urls:
            result.notes.append(
                "nessun link a scheda annuncio individuato nell'HTML statico: "
                "possibile rendering via JavaScript (vedi cache/)"
            )

        # conteggio e formati sul campione osservato
        result.plan_documents_found = len(doc_links)
        strict = [d for d in doc_links if STRICT_PLAN_KEYWORDS.search(f"{d[0]} {d[1]}")]
        if doc_links:
            result.notes.append(
                f"{len(doc_links)} documenti con keyword nel campione, di cui "
                f"{len(strict)} planimetrie in senso stretto (resto: perizie/tavole)"
            )
        for url, _text in doc_links:
            fmt = _format_from(url)
            if fmt != "sconosciuto" and fmt not in result.formats:
                result.formats.append(fmt)

        # 4) campioni: prima le planimetrie in senso stretto, poi il resto
        ordered = strict + [d for d in doc_links if d not in strict]
        downloaded = 0
        for url, label in ordered:
            if downloaded >= MAX_SAMPLES or session.requests_made >= SOFT_REQUEST_CAP:
                break
            _download_sample(session, url, label, downloaded + 1, result)
            downloaded += 1
            if result.blocked_by_protection:
                break

    except BudgetExceeded as exc:
        result.errors.append(f"budget richieste esaurito: {exc}")
    except Exception as exc:  # difensivo: il probe deve sempre restituire un esito
        result.errors.append(f"errore inatteso: {type(exc).__name__}: {exc}")

    # verdetto
    ok_samples = [e for e in result.sample_documents if e.saved_to and not e.saved_to.endswith(".html")]
    if result.blocked_by_protection:
        result.access_method = "html-crawl"
        result.programmatic = "no"
        result.yield_estimate = "none" if not ok_samples else "low"
    elif ok_samples:
        result.access_method = "html-crawl + download-diretto"
        result.programmatic = "yes"
        result.yield_estimate = "high" if result.plan_documents_found >= 2 else "medium"
    elif result.plan_documents_found > 0:
        result.access_method = "html-crawl"
        result.programmatic = "partial"
        result.yield_estimate = "medium"
    else:
        result.access_method = "html-crawl"
        result.programmatic = "no" if result.reachable else ""
        result.yield_estimate = "low" if result.reachable else "none"
    return result


if __name__ == "__main__":
    from scout.core import standalone

    standalone(probe, SOURCE_ID)
