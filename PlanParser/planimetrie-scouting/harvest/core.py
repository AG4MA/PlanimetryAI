"""Nucleo dell'harvester massivo di planimetrie da portali di aste giudiziarie.

Differenze rispetto a scout/ (che e' ricognizione a bassissimo budget):
- pensato per girare a lungo su molte pagine, ma sempre EDUCATO:
  ritardo configurabile fra richieste, robots.txt rispettato, retry con backoff,
  nessuna elusione di blocchi anti-bot (un 403/429/challenge ferma quel dominio);
- RESUMABLE: manifest append-only in JSONL + file di stato per ripartire;
- DEDUP: per URL documento gia' visto e per SHA-256 del contenuto;
- provenienza tracciata per ogni documento (uso analitico interno, no ripubblicazione).

Layout output (fuori dal versionamento, vedi .gitignore):
  harvest_output/<site_id>/
    manifest.jsonl        un record per documento scaricato
    state.json            stato di ripresa (pagina corrente, contatori)
    docs/<aa>/<sha256>.<ext>   documenti, sharding per prime 2 cifre dell'hash
    cache/                pagine grezze salvate su richiesta (debug)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "PlanimetryAI-harvest/0.1 (raccolta planimetrie da documenti pubblici di aste "
    "giudiziarie per uso analitico interno; contatto: alessandro.galletta@outlook.com)"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HARVEST_ROOT = PROJECT_ROOT / "harvest_output"
# cartella UNICA e piatta con tutte le planimetrie, da tutti i portali
PLANIMETRIE_DIR = HARVEST_ROOT / "PLANIMETRIE"


def safe_name(text: str, maxlen: int = 60) -> str:
    """Nome file leggibile e sicuro (niente separatori di percorso)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-._")
    return (s[:maxlen] or "x")

MAX_DOC_BYTES = 40 * 1024 * 1024  # tetto per singolo documento (perizie possono essere grandi)

# classificazione del tipo di documento dal testo dell'ancora e dall'URL
_DOC_TYPES = [
    ("elaborato_planimetrico", re.compile(r"elaborato\s*planimetric", re.I)),
    ("planimetria", re.compile(r"planimetri|floor\s*plan|\bpiantina\b|\bpianta\b", re.I)),
    ("perizia", re.compile(r"perizi|c\.?t\.?u|consulenza\s+tecnic|stima", re.I)),
    ("tavola", re.compile(r"\btavol[ae]\b|\ballegat[oi]\s+grafic", re.I)),
    ("avviso_vendita", re.compile(r"avviso\s+di\s+vendita|bando", re.I)),
    ("ordinanza", re.compile(r"ordinanz|decreto", re.I)),
]

# cosa vogliamo raccogliere: SOLO planimetrie (piante). Le perizie/tavole sono
# escluse su richiesta: la perizia CTU contiene piante ma non e' una planimetria.
WANTED_TYPES = {"planimetria", "elaborato_planimetrico"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_doc_type(label: str, url: str) -> str:
    blob = f"{label} {url}"
    for name, pat in _DOC_TYPES:
        if pat.search(blob):
            return name
    return "altro"


def guess_ext(url: str, content_type: str, head: bytes) -> str:
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:2] == b"PK":
        return "zip"
    m = re.search(r"\.([a-z0-9]{2,4})(?:$|[?#])", urlparse(url).path, re.I)
    if m:
        ext = m.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    ct = (content_type or "").lower()
    for key, ext in (("pdf", "pdf"), ("jpeg", "jpg"), ("png", "png"), ("zip", "zip"), ("tiff", "tiff")):
        if key in ct:
            return ext
    return "bin"


class ProtectionBlocked(RuntimeError):
    """Il dominio ha risposto con un blocco anti-bot: fermarsi, non eludere."""


class RobotsDisallowed(RuntimeError):
    """URL vietato dal robots.txt."""


def _looks_like_protection(resp: requests.Response) -> bool:
    if resp.status_code in (401, 403, 429):
        return True
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        head = resp.content[:2500].lower()
        for m in (b"captcha", b"datadome", b"cf-challenge", b"attention required",
                  b"access denied", b"perimeterx", b"px-captcha"):
            if m in head:
                return True
    return False


class HarvestSession:
    """requests.Session educata: robots, ritardo, retry con backoff, rilevamento blocchi."""

    def __init__(self, delay_s: float = 1.2, timeout_s: float = 40.0, retries: int = 3) -> None:
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.retries = retries
        self.requests_made = 0
        self._last_ts = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": USER_AGENT})

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_ts
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)
        self._last_ts = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait()
                r = self.http.get(origin + "/robots.txt", timeout=self.timeout_s)
                if r.status_code == 200 and r.text.strip():
                    parser.parse(r.text.splitlines())
                    self._robots[origin] = parser
                else:
                    self._robots[origin] = None
            except requests.RequestException:
                self._robots[origin] = None
        return self._robots[origin]

    def allowed_by_robots(self, url: str) -> bool | None:
        parser = self._robots_for(url)
        if parser is None:
            return None
        return parser.can_fetch(USER_AGENT, url)

    def get(self, url: str, *, check_robots: bool = True, stream: bool = False, **kwargs) -> requests.Response:
        if check_robots and self.allowed_by_robots(url) is False:
            raise RobotsDisallowed(url)
        kwargs.setdefault("timeout", self.timeout_s)
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._wait()
            self.requests_made += 1
            try:
                resp = self.http.get(url, stream=stream, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else min(2 ** attempt * 3, 60)
                time.sleep(wait)
                last_exc = ProtectionBlocked(f"429 su {url}")
                continue
            if resp.status_code in (500, 502, 503, 504):
                last_exc = requests.HTTPError(f"{resp.status_code} su {url}")
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            return resp
        if isinstance(last_exc, Exception):
            raise last_exc
        raise requests.RequestException(f"fallite {self.retries} richieste su {url}")


@dataclass
class DocRecord:
    source_name: str
    source_family: str
    listing_id: str
    listing_url: str
    doc_url: str
    doc_label: str
    doc_type: str
    file_name: str
    sha256: str
    size_bytes: int
    format: str
    http_status: int
    comune: str = ""
    acquisition_basis: str = "public_document_internal_use"
    license: str = "documento di procedura pubblica"
    fetched_at: str = field(default_factory=utc_now_iso)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


class Manifest:
    """Manifest append-only con indici in memoria per la deduplica e la ripresa."""

    def __init__(self, site_dir: Path) -> None:
        self.site_dir = site_dir
        self.path = site_dir / "manifest.jsonl"
        self.state_path = site_dir / "state.json"
        self.docs_dir = site_dir / "docs"
        self.seen_doc_urls: set[str] = set()
        self.seen_sha: set[str] = set()
        self.seen_listing_ids: set[str] = set()
        self.doc_count = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.seen_doc_urls.add(rec.get("doc_url", ""))
            self.seen_sha.add(rec.get("sha256", ""))
            self.seen_listing_ids.add(str(rec.get("listing_id", "")))
            self.doc_count += 1

    def load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def save_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def append(self, rec: DocRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(rec.to_json() + "\n")
        self.seen_doc_urls.add(rec.doc_url)
        self.seen_sha.add(rec.sha256)
        self.seen_listing_ids.add(str(rec.listing_id))
        self.doc_count += 1

    def store_doc(self, file_name: str, content: bytes) -> Path:
        """Salva la planimetria nella cartella UNICA e piatta PLANIMETRIE/."""
        PLANIMETRIE_DIR.mkdir(parents=True, exist_ok=True)
        path = PLANIMETRIE_DIR / file_name
        if not path.exists():
            path.write_bytes(content)
        return path


def site_dir(site_id: str) -> Path:
    d = HARVEST_ROOT / site_id
    (d / "docs").mkdir(parents=True, exist_ok=True)
    (d / "cache").mkdir(parents=True, exist_ok=True)
    return d


def download_document(session: HarvestSession, url: str) -> tuple[bytes, str, int, str]:
    """Scarica un documento in streaming con tetto di dimensione.

    Ritorna (contenuto, sha256, http_status, content_type). Solleva ProtectionBlocked
    su blocco anti-bot; ritorna contenuto vuoto se HTML (viewer) o troppo grande.
    """
    resp = session.get(url, stream=True)
    status = resp.status_code
    ctype = resp.headers.get("Content-Type", "")
    if _looks_like_protection(resp):
        resp.close()
        raise ProtectionBlocked(f"blocco anti-bot su {url} (HTTP {status})")
    if status != 200:
        resp.close()
        return b"", "", status, ctype
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_DOC_BYTES:
        resp.close()
        return b"", "", status, ctype
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=131072):
            total += len(chunk)
            if total > MAX_DOC_BYTES:
                resp.close()
                return b"", "", status, ctype
            hasher.update(chunk)
            chunks.append(chunk)
    finally:
        resp.close()
    body = b"".join(chunks)
    head = body[:8]
    if head[:5].lower() in (b"<!doc", b"<html") or "text/html" in ctype.lower():
        return b"", "", status, ctype  # viewer/redirect applicativo, non un documento
    return body, hasher.hexdigest(), status, ctype
