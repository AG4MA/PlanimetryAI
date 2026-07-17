"""Probe: Aste Giudiziarie Inlinea (www.astegiudiziarie.it).

Storico portale di vendite giudiziarie: le schede degli immobili espongono
allegati (perizia, planimetria, avviso di vendita...) tipicamente in PDF.
Il probe verifica raggiungibilita', robots, individua schede immobili via
html-crawl, cerca link a documenti-planimetria e scarica al massimo 2-3
campioni piccoli (<5 MB) se consentito.

Budget interno per run: ~7 richieste contate (homepage + lista + 2 schede
+ 2-3 download), entro il tetto della PoliteSession.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scout.core import (
    OUTPUT_DIR,
    Evidence,
    PoliteSession,
    ProbeResult,
    RobotsDisallowed,
    looks_like_protection,
)

SOURCE_ID = "astegiudiziarie"
SOURCE_NAME = "Aste Giudiziarie Inlinea"
BASE = "https://www.astegiudiziarie.it/"

OUT_DIR = OUTPUT_DIR / SOURCE_ID
CACHE_DIR = OUT_DIR / "cache"

MAX_SAMPLE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_SAMPLES = 3

# parole chiave documenti-planimetria (regex con confini di parola dove serve)
PLAN_PATTERNS = (
    re.compile(r"planimetri", re.I),                 # planimetria/planimetrie
    re.compile(r"elaborato\s+planimetrico", re.I),
    re.compile(r"\bperizia\b|\bperizie\b", re.I),
    re.compile(r"\btavola\b|\btavole\b", re.I),
    re.compile(r"floor\s*plan", re.I),
)

DOC_HREF_HINTS = ("allegat", "download", "documento", "attachment", "perizia",
                  "planimetri", "getfile", "file", ".pdf")


def _save_cache(name: str, content: bytes) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / name).write_bytes(content)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _same_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("astegiudiziarie.it")


def _matches_plan(text: str) -> bool:
    return any(p.search(text) for p in PLAN_PATTERNS)


def _find_listing_url(soup: BeautifulSoup, page_url: str) -> str | None:
    """Cerca un link a una pagina di ricerca/elenco vendite immobiliari."""
    best: tuple[int, str] | None = None
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        if not _same_host(href):
            continue
        blob = (a["href"] + " " + a.get_text(" ", strip=True)).lower()
        score = 0
        for kw, pts in (("immobil", 3), ("ricerca", 3), ("vendite", 2),
                        ("aste", 1), ("elenco", 2), ("cerca", 2)):
            if kw in blob:
                score += pts
        if score >= 3 and (best is None or score > best[0]):
            best = (score, href)
    return best[1] if best else None


def _find_detail_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Link a schede di vendita: href con id numerici lunghi o parole tipiche."""
    seen: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        if not _same_host(href) or href.rstrip("/") == BASE.rstrip("/"):
            continue
        path = urlparse(href).path.lower()
        query = urlparse(href).query.lower()
        blob = path + "?" + query
        score = 0
        if re.search(r"(vendita|scheda|annunc|dettagl|lotto|inserzione)", blob):
            score += 2
        if re.search(r"\d{5,}", blob):
            score += 2
        text = a.get_text(" ", strip=True).lower()
        if re.search(r"(appartament|villa|immobile|terreno|magazzin|locale|box|capannone|fabbricat)", text + " " + blob):
            score += 1
        if score >= 3:
            seen[href] = max(seen.get(href, 0), score)
    return [u for u, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def _find_doc_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    """(label, url) dei link che sembrano documenti/allegati della scheda."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        raw = a["href"]
        if raw.startswith(("javascript:", "mailto:", "#")):
            continue
        href = urljoin(page_url, raw)
        label = a.get_text(" ", strip=True) or Path(urlparse(href).path).name
        blob = (raw + " " + label).lower()
        is_doc = any(h in blob for h in DOC_HREF_HINTS) or _matches_plan(blob)
        if is_doc and href not in seen:
            seen.add(href)
            out.append((label[:120], href))
    return out


def _guess_format(url: str, content_type: str, head: bytes = b"") -> str:
    if head.startswith(b"%PDF") or "pdf" in content_type:
        return "pdf"
    ext = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "png", "tif", "tiff", "gif", "webp"):
        return "immagine"
    if ext in ("dwg", "dxf"):
        return ext
    if ext == "pdf":
        return "pdf"
    if content_type.startswith("image/"):
        return "immagine"
    if "html" in content_type:
        return "html"
    return ext or (content_type.split(";")[0].strip() or "sconosciuto")


def _download_sample(session: PoliteSession, url: str, label: str,
                     result: ProbeResult, idx: int) -> Evidence | None:
    """Scarica un campione piccolo rispettando robots; None se saltato."""
    try:
        resp = session.get(url, stream=True)
    except RobotsDisallowed:
        result.notes.append(f"robots vieta il download di {url}")
        return None
    ev = Evidence(url=url, status=resp.status_code,
                  content_type=resp.headers.get("Content-Type", ""))
    if resp.status_code in (401, 403, 429):
        ev.note = f"accesso negato ({resp.status_code}) su '{label}'"
        if resp.status_code in (403, 429):
            result.blocked_by_protection = True
        resp.close()
        return ev
    if resp.status_code != 200:
        ev.note = f"status inatteso per '{label}'"
        resp.close()
        return ev
    declared = resp.headers.get("Content-Length")
    if declared and int(declared) > MAX_SAMPLE_BYTES:
        ev.size_bytes = int(declared)
        ev.note = f"'{label}': troppo grande (> 5MB), non scaricato"
        resp.close()
        return ev
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_SAMPLE_BYTES:
            resp.close()
            ev.size_bytes = total
            ev.note = f"'{label}': superati 5MB in download, interrotto e scartato"
            return ev
    content = b"".join(chunks)
    fmt = _guess_format(url, ev.content_type.lower(), content[:8])
    if fmt == "html":
        ev.note = f"'{label}': il link restituisce HTML (viewer/pagina), non un documento diretto"
        _save_cache(f"doc_{idx}_unexpected.html", content)
        ev.size_bytes = len(content)
        return ev
    # su questo portale l'URL e' /Allegato/<nomefile.ext>/<id>: prendi il
    # segmento di path con estensione, altrimenti l'ultimo
    segments = [s for s in urlparse(url).path.split("/") if s]
    named = [s for s in segments if "." in s]
    base_name = named[-1] if named else (segments[-1] if segments else f"doc_{idx}")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name) or f"doc_{idx}"
    if "." not in safe:
        ext = {"pdf": ".pdf", "immagine": ".jpg"}.get(fmt, ".bin")
        safe += ext
    path = PoliteSession.save_bytes(content, OUT_DIR, f"sample_{idx}_{safe}")
    ev.size_bytes = len(content)
    ev.saved_to = str(path)
    ev.note = f"campione '{label}' ({fmt})"
    if fmt not in result.formats:
        result.formats.append(fmt)
    return ev


def probe(session: PoliteSession) -> ProbeResult:
    result = ProbeResult(
        source_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        category="auction",
        legal_bucket="public_document_internal_use",
    )

    # 1) homepage + robots
    try:
        resp = session.get(BASE)
    except RobotsDisallowed:
        result.robots_allows = False
        result.notes.append("robots.txt vieta la homepage: stop")
        return result
    except Exception as exc:  # rete giu', DNS, timeout
        result.errors.append(f"homepage irraggiungibile: {exc}")
        return result

    result.robots_allows = session.allowed_by_robots(BASE)
    _save_cache("homepage.html", resp.content)
    if looks_like_protection(resp):
        result.reachable = True
        result.blocked_by_protection = True
        result.notes.append(f"protezione anti-bot sulla homepage (status {resp.status_code}): stop")
        return result
    if resp.status_code != 200:
        result.errors.append(f"homepage status {resp.status_code}")
        return result
    result.reachable = True
    if resp.url.rstrip("/") != BASE.rstrip("/"):
        result.notes.append(f"homepage redirige a {resp.url}")

    home = _soup(resp.text)

    # 2) schede: prima direttamente dalla homepage, altrimenti via pagina elenco
    detail_urls = _find_detail_links(home, resp.url)
    listing_url = None
    if len(detail_urls) < 2:
        listing_url = _find_listing_url(home, resp.url)
        if listing_url:
            try:
                lresp = session.get(listing_url)
                _save_cache("listing.html", lresp.content)
                if looks_like_protection(lresp):
                    result.blocked_by_protection = True
                    result.notes.append(f"protezione anti-bot sull'elenco {listing_url}: stop")
                    return result
                if lresp.status_code == 200:
                    detail_urls = _find_detail_links(_soup(lresp.text), lresp.url) or detail_urls
                    result.notes.append(f"elenco vendite esplorato: {listing_url}")
                else:
                    result.notes.append(f"elenco {listing_url} status {lresp.status_code}")
            except RobotsDisallowed:
                result.notes.append(f"robots vieta l'elenco {listing_url}")
            except Exception as exc:
                result.errors.append(f"errore su elenco {listing_url}: {exc}")

    if not detail_urls:
        result.access_method = "html-crawl"
        result.programmatic = "no"
        result.yield_estimate = "none"
        result.notes.append(
            "nessun link a schede di vendita individuato nell'HTML: "
            "probabile rendering via JavaScript o struttura diversa (vedi cache/)"
        )
        return result

    # 3) fino a 2 schede: cerca documenti-planimetria
    plan_docs: list[tuple[str, str]] = []       # (label, url) che matchano keyword
    other_docs = 0
    pages_checked = 0
    for i, durl in enumerate(detail_urls[:2]):
        try:
            dresp = session.get(durl)
        except RobotsDisallowed:
            result.notes.append(f"robots vieta la scheda {durl}")
            continue
        except Exception as exc:
            result.errors.append(f"errore su scheda {durl}: {exc}")
            continue
        _save_cache(f"detail_{i}.html", dresp.content)
        if looks_like_protection(dresp):
            result.blocked_by_protection = True
            result.notes.append(f"protezione anti-bot sulla scheda {durl}: stop")
            break
        if dresp.status_code != 200:
            result.notes.append(f"scheda {durl} status {dresp.status_code}")
            continue
        pages_checked += 1
        dsoup = _soup(dresp.text)
        docs = _find_doc_links(dsoup, dresp.url)
        for label, url in docs:
            if _matches_plan(label + " " + url):
                if (label, url) not in plan_docs:
                    plan_docs.append((label, url))
            else:
                other_docs += 1
        page_text = dsoup.get_text(" ", strip=True)
        if not docs and _matches_plan(page_text):
            result.notes.append(
                f"la scheda {durl} cita planimetria/perizia nel testo ma senza link diretti visibili"
            )
        if plan_docs:
            break  # basta una scheda con documenti utili, risparmiamo budget

    result.plan_documents_found = len(plan_docs)
    if pages_checked:
        result.notes.append(f"schede esaminate: {pages_checked}; allegati non-planimetria visti: {other_docs}")

    # formati desumibili dagli URL anche senza download
    for _, url in plan_docs:
        fmt = _guess_format(url, "")
        if fmt not in ("sconosciuto", "html") and fmt not in result.formats:
            result.formats.append(fmt)

    # 4) download campioni (max 3, piccoli), prima le planimetrie poi le perizie
    ranked = sorted(
        plan_docs,
        key=lambda d: 0 if re.search(r"planimetri", (d[0] + d[1]), re.I) else 1,
    )
    downloaded = 0
    for label, url in ranked:
        if downloaded >= MAX_SAMPLES or session.requests_made >= session.max_requests - 1:
            break
        ev = _download_sample(session, url, label, result, downloaded)
        if ev is not None:
            result.sample_documents.append(ev)
            if ev.saved_to:
                downloaded += 1
        if result.blocked_by_protection:
            break

    # 5) verdetto
    if result.blocked_by_protection:
        result.access_method = "html-crawl"
        result.programmatic = "partial" if downloaded else "no"
        result.yield_estimate = "low" if plan_docs else "none"
        return result

    if downloaded:
        result.access_method = "html-crawl + download-diretto"
        result.programmatic = "yes"
        result.yield_estimate = "high" if downloaded >= 2 or len(plan_docs) >= 2 else "medium"
        result.notes.append(
            "documenti perizia/planimetria scaricabili senza login: harvest per uso interno fattibile"
        )
    elif plan_docs:
        result.access_method = "html-crawl"
        result.programmatic = "partial"
        result.yield_estimate = "medium"
        result.notes.append("link a documenti individuati ma download non riuscito nel campione")
    else:
        result.access_method = "html-crawl"
        result.programmatic = "partial" if pages_checked else "no"
        result.yield_estimate = "low" if pages_checked else "none"
        if pages_checked:
            result.notes.append("nessun documento-planimetria visibile nelle schede osservate")
    return result


if __name__ == "__main__":
    from scout.core import standalone

    standalone(probe, SOURCE_ID)
