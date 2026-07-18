"""Probe: dati.gov.it, catalogo nazionale dei dati aperti (CKAN).

Verifica se il catalogo espone dataset con planimetrie scaricabili via API CKAN
(package_search). dati.gov.it e' un aggregatore: le risorse puntano quasi sempre
ai portali degli enti sorgente, quindi i download campione possono toccare
domini terzi (robots.txt verificato per ciascuno di essi).

Richieste contate previste: 1-2 per la ricerca iniziale (con fallback di path
API), 2 ricerche extra, max 2 download campione = 5-6 totali; i soli robots.txt
non sono contati dalla sessione. Le risposte grezze finiscono in
output/datigov/cache/ per il debug offline.
"""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

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

SOURCE_ID = "datigov"
SOURCE_NAME = "dati.gov.it (CKAN)"

# path API noti del portale (il catalogo ha vissuto sia in / sia in /opendata/)
API_BASES = (
    "https://www.dati.gov.it/api/3/action",
    "https://www.dati.gov.it/opendata/api/3/action",
)
MAIN_QUERY = ("planimetria", 50, "planimetria")
EXTRA_QUERIES = (
    ('"elaborato planimetrico"', 20, "elaborato_planimetrico"),
    ("planimetrie", 20, "planimetrie"),
)
# match "forte" = quasi certamente una planimetria; "debole" = rumoroso (tavola/perizia)
STRICT_RE = re.compile(r"planimetr|floorplan|elaborat[oi]\s+planimetric[oi]")
LOOSE_RE = re.compile(r"\btavol[ae]\b|\bperizi[ae]\b")
DOC_FORMATS = {
    "pdf", "dwg", "dxf", "zip", "shp", "jpg", "jpeg", "png",
    "tif", "tiff", "gml", "p7m", "dgn",
}
FMT_PRIORITY = {"pdf": 0, "dwg": 1, "dxf": 1, "zip": 2, "shp": 2}
MAX_SAMPLE_BYTES = 5 * 1024 * 1024
MAX_SAMPLES = 2
OUT_DIR = OUTPUT_DIR / SOURCE_ID
CACHE_DIR = OUT_DIR / "cache"


def _cache_raw(slug: str, content: bytes) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{slug}.json").write_bytes(content)
    except OSError:
        pass  # la cache e' solo un aiuto al debug, mai bloccante


def _dataset_text(ds: dict) -> str:
    parts = [str(ds.get("title") or ""), str(ds.get("notes") or "")]
    for tag in ds.get("tags") or []:
        parts.append(str(tag.get("name") or "") if isinstance(tag, dict) else str(tag))
    return " ".join(parts).lower()


def _resource_text(res: dict) -> str:
    return " ".join(
        str(res.get(k) or "") for k in ("name", "description", "url")
    ).lower()


def _norm_fmt(res: dict) -> str:
    fmt = str(res.get("format") or "").strip().lower().lstrip(".")
    if fmt:
        return fmt
    tail = urlparse(str(res.get("url") or "")).path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else ""


def _declared_size(res: dict) -> int | None:
    raw = res.get("size")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _safe_name(url: str, fmt: str, index: int) -> str:
    base = urlparse(url).path.rsplit("/", 1)[-1] or "campione"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80].strip("._") or "campione"
    if "." not in base and fmt:
        base = f"{base}.{fmt}"
    return f"sample{index}_{base}"


def _search(session: PoliteSession, api_base: str, query: str, rows: int, slug: str,
            result: ProbeResult) -> dict | None:
    """Una package_search; salva la risposta grezza in cache e la decodifica."""
    url = f"{api_base}/package_search"
    try:
        resp = session.get(url, params={"q": query, "rows": rows})
    except RobotsDisallowed:
        result.robots_allows = False
        result.notes.append(f"robots.txt vieta {url}: mi fermo su questo percorso")
        return None
    except requests.RequestException as exc:
        result.errors.append(f"ricerca {query!r}: {type(exc).__name__}: {exc}")
        return None
    result.reachable = True
    _cache_raw(f"search_{slug}", resp.content)
    if looks_like_protection(resp):
        result.blocked_by_protection = True
        result.notes.append(
            f"HTTP {resp.status_code}/challenge su {url}: nessuna elusione, stop sul dominio"
        )
        return None
    if resp.status_code != 200:
        result.errors.append(f"ricerca {query!r}: HTTP {resp.status_code}")
        return None
    try:
        data = resp.json()
    except ValueError:
        result.errors.append(f"ricerca {query!r}: risposta non JSON (vedi cache)")
        return None
    if not (isinstance(data, dict) and data.get("success") and isinstance(data.get("result"), dict)):
        result.errors.append(f"ricerca {query!r}: JSON senza success/result (vedi cache)")
        return None
    return data["result"]


def _download_sample(session: PoliteSession, result: ProbeResult, url: str, fmt: str,
                     index: int, blocked_domains: set[str]) -> bool:
    domain = urlparse(url).netloc
    if domain in blocked_domains:
        return False
    try:
        resp = session.get(url, stream=True)
    except RobotsDisallowed:
        result.notes.append(f"robots.txt del dominio {domain} vieta il download: saltato")
        return False
    except requests.RequestException as exc:
        result.errors.append(f"download campione {url}: {type(exc).__name__}")
        return False
    with resp:
        if resp.status_code in (403, 429, 503):
            blocked_domains.add(domain)
            result.notes.append(
                f"HTTP {resp.status_code} dal dominio terzo {domain}: dominio abbandonato (no elusione)"
            )
            return False
        if resp.status_code != 200:
            result.errors.append(f"download campione {url}: HTTP {resp.status_code}")
            return False
        clen = resp.headers.get("Content-Length", "")
        if clen.isdigit() and int(clen) > MAX_SAMPLE_BYTES:
            result.notes.append(f"campione saltato, {clen} B dichiarati > 5MB: {url}")
            return False
        buf = bytearray()
        try:
            for chunk in resp.iter_content(64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_SAMPLE_BYTES:
                    result.notes.append(f"campione scartato, corpo effettivo > 5MB: {url}")
                    return False
        except requests.RequestException as exc:
            result.errors.append(f"download campione {url}: {type(exc).__name__} durante lo stream")
            return False
        content_type = resp.headers.get("Content-Type", "")
    note = f"formato dichiarato {fmt or 'n/d'}"
    if bytes(buf[:5]) == b"%PDF-":
        note += "; magic bytes PDF validi"
    elif fmt == "pdf":
        note += "; ATTENZIONE: magic bytes non PDF"
    path = PoliteSession.save_bytes(bytes(buf), OUT_DIR, _safe_name(url, fmt, index))
    result.sample_documents.append(Evidence(
        url=url, status=200, content_type=content_type,
        size_bytes=len(buf), note=note, saved_to=str(path),
    ))
    return True


def probe(session: PoliteSession) -> ProbeResult:
    result = ProbeResult(
        source_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        category="catalogue",
        legal_bucket="open_ccby",
    )

    # 1) ricerca principale, con fallback sul path API alternativo
    api_base = None
    main = None
    query, rows, slug = MAIN_QUERY
    for base in API_BASES:
        main = _search(session, base, query, rows, slug, result)
        if result.blocked_by_protection or result.robots_allows is False:
            return result
        if main is not None:
            api_base = base
            break
    result.robots_allows = session.allowed_by_robots(f"{API_BASES[0]}/package_search")
    if api_base is None or main is None:
        result.programmatic = "no"
        result.yield_estimate = "none"
        result.notes.append("nessun endpoint CKAN valido trovato fra i path noti")
        return result
    result.access_method = "ckan-api"
    result.notes.append(f"endpoint CKAN funzionante: {api_base}/package_search")

    # 2) ricerche extra e aggregazione dataset deduplicati
    counts = {query: int(main.get("count") or 0)}
    datasets: dict[str, dict] = {}
    for ds in main.get("results") or []:
        datasets[str(ds.get("id") or ds.get("name"))] = ds
    for q, r, s in EXTRA_QUERIES:
        try:
            extra = _search(session, api_base, q, r, s, result)
        except BudgetExceeded:
            result.errors.append("budget richieste esaurito durante le ricerche extra")
            break
        if result.blocked_by_protection:
            return result
        if extra is None:
            continue
        counts[q] = int(extra.get("count") or 0)
        for ds in extra.get("results") or []:
            datasets.setdefault(str(ds.get("id") or ds.get("name")), ds)
    result.notes.append(
        "count dichiarati dall'API: "
        + "; ".join(f"{q} -> {n} dataset" for q, n in counts.items())
    )
    result.notes.append(f"campione osservato: {len(datasets)} dataset unici")

    # 3) analisi del campione: risorse-documento, formati, licenze
    licenses: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    strict_docs = 0
    loose_docs = 0
    matched_datasets = 0
    seen_urls: set[str] = set()  # la stessa risorsa compare in piu' dataset: conta una volta
    candidates: list[tuple[tuple[int, int], str, str]] = []  # (chiave ordinamento, url, fmt)
    for ds in datasets.values():
        ds_text = _dataset_text(ds)
        ds_strict = bool(STRICT_RE.search(ds_text))
        ds_loose = bool(LOOSE_RE.search(ds_text))
        licenses[str(ds.get("license_id") or ds.get("license_title") or "n/d")] += 1
        ds_matched = False
        for res in ds.get("resources") or []:
            url = str(res.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            fmt = _norm_fmt(res)
            if fmt not in DOC_FORMATS:
                continue
            res_text = _resource_text(res)
            if ds_strict or STRICT_RE.search(res_text):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                strict_docs += 1
                ds_matched = True
                formats[fmt] += 1
                size = _declared_size(res)
                if size is not None and size > MAX_SAMPLE_BYTES:
                    continue
                key = (FMT_PRIORITY.get(fmt, 3), size if size is not None else MAX_SAMPLE_BYTES)
                candidates.append((key, url, fmt))
            elif ds_loose or LOOSE_RE.search(res_text):
                loose_docs += 1
    for ds in datasets.values():
        if STRICT_RE.search(_dataset_text(ds)):
            matched_datasets += 1
    result.plan_documents_found = strict_docs
    result.formats = sorted(formats)
    result.notes.append(
        f"nel campione: {matched_datasets} dataset con match forte (planimetr*/floorplan), "
        f"{strict_docs} risorse-documento scaricabili; altre {loose_docs} solo tavola/perizia"
    )
    if formats:
        result.notes.append(
            "formati risorse-documento: "
            + ", ".join(f"{f}={n}" for f, n in formats.most_common())
        )
    if licenses:
        result.notes.append(
            "licenze dichiarate nei metadati: "
            + ", ".join(f"{l}={n}" for l, n in licenses.most_common(6))
        )
    result.notes.append(
        "nota: dati.gov.it e' un aggregatore, le risorse puntano ai portali degli enti; "
        "harvest completo possibile via package_search con paginazione start/rows"
    )

    # 4) download di al massimo MAX_SAMPLES campioni piccoli (domini distinti se possibile)
    candidates.sort(key=lambda c: c[0])
    downloaded = 0
    used_domains: set[str] = set()
    blocked_domains: set[str] = set()
    attempts_per_domain: Counter[str] = Counter()
    for _, url, fmt in candidates:
        if downloaded >= MAX_SAMPLES:
            break
        domain = urlparse(url).netloc
        if domain in used_domains:
            continue
        if attempts_per_domain[domain] >= 2:
            continue  # dominio con soli file troppo grandi/falliti: non sprecare budget
        attempts_per_domain[domain] += 1
        try:
            if _download_sample(session, result, url, fmt, downloaded + 1, blocked_domains):
                downloaded += 1
                used_domains.add(domain)
        except BudgetExceeded:
            result.errors.append("budget richieste esaurito durante i download campione")
            break
    if not candidates:
        result.notes.append("nessuna risorsa-candidato piccola da scaricare nel campione")

    # 5) verdetto
    result.programmatic = "yes" if downloaded else "partial"
    count_main = counts.get(query, 0)
    if strict_docs >= 25 or count_main >= 200:
        result.yield_estimate = "high"
    elif strict_docs >= 8 or count_main >= 50:
        result.yield_estimate = "medium"
    elif strict_docs >= 1 or count_main >= 1:
        result.yield_estimate = "low"
    else:
        result.yield_estimate = "none"
    return result


if __name__ == "__main__":
    from scout.core import standalone
    standalone(probe, SOURCE_ID)
