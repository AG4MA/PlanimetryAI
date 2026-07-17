"""Nucleo condiviso dei probe di ricognizione fonti planimetrie.

Regole non negoziabili incorporate qui:
- budget di richieste per run (superarlo solleva BudgetExceeded);
- ritardo minimo fra richieste sullo stesso processo;
- robots.txt rispettato (RobotsDisallowed se il percorso e' vietato);
- nessuna elusione di blocchi anti-bot: 403/429/challenge si registrano come esito.
"""
from __future__ import annotations

import json
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "PlanimetryAI-scout/0.1 (ricognizione non massiva di fonti di planimetrie; "
    "contatto: alessandro.galletta@outlook.com)"
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


class BudgetExceeded(RuntimeError):
    """Superato il tetto di richieste HTTP del probe."""


class RobotsDisallowed(RuntimeError):
    """URL vietato dal robots.txt del sito."""


@dataclass
class Evidence:
    url: str
    status: int | None = None
    content_type: str = ""
    size_bytes: int = 0
    note: str = ""
    saved_to: str = ""


@dataclass
class ProbeResult:
    source_id: str
    source_name: str
    category: str            # auction | catalogue | geoportal | listing | official
    legal_bucket: str        # open_ccby | public_document_internal_use | rights_gated | tos_risk | unclear
    reachable: bool = False
    robots_allows: bool | None = None
    blocked_by_protection: bool = False
    plan_documents_found: int = 0
    formats: list[str] = field(default_factory=list)
    access_method: str = ""  # es. html-crawl | json-api | ckan-api | csw | wms/wfs | download-diretto
    programmatic: str = ""   # yes | partial | no
    yield_estimate: str = "" # high | medium | low | none
    sample_documents: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests_made: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class PoliteSession:
    """Wrapper di requests con budget richieste, ritardo fisso e controllo robots.txt."""

    def __init__(self, max_requests: int = 10, delay_s: float = 1.5, timeout_s: float = 25.0) -> None:
        self.max_requests = max_requests
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.requests_made = 0
        self._last_request_ts = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": USER_AGENT})

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)
        self._last_request_ts = time.monotonic()

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait()
                resp = self.http.get(origin + "/robots.txt", timeout=self.timeout_s)
                if resp.status_code == 200 and resp.text.strip():
                    parser.parse(resp.text.splitlines())
                    self._robots[origin] = parser
                else:
                    self._robots[origin] = None  # nessun robots leggibile -> nessun divieto noto
            except requests.RequestException:
                self._robots[origin] = None
        return self._robots[origin]

    def allowed_by_robots(self, url: str) -> bool | None:
        parser = self._robots_for(url)
        if parser is None:
            return None
        return parser.can_fetch(USER_AGENT, url)

    def get(self, url: str, *, check_robots: bool = True, stream: bool = False, **kwargs) -> requests.Response:
        if self.requests_made >= self.max_requests:
            raise BudgetExceeded(f"budget di {self.max_requests} richieste esaurito")
        if check_robots and self.allowed_by_robots(url) is False:
            raise RobotsDisallowed(url)
        self._wait()
        self.requests_made += 1
        kwargs.setdefault("timeout", self.timeout_s)
        return self.http.get(url, stream=stream, **kwargs)

    def post(self, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        if self.requests_made >= self.max_requests:
            raise BudgetExceeded(f"budget di {self.max_requests} richieste esaurito")
        if check_robots and self.allowed_by_robots(url) is False:
            raise RobotsDisallowed(url)
        self._wait()
        self.requests_made += 1
        kwargs.setdefault("timeout", self.timeout_s)
        return self.http.post(url, **kwargs)

    @staticmethod
    def save_bytes(content: bytes, dest_dir: Path, name: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / name
        path.write_bytes(content)
        return path


def looks_like_protection(resp: requests.Response) -> bool:
    """Euristica per challenge anti-bot (Cloudflare, DataDome, Akamai...)."""
    if resp.status_code in (403, 429, 503):
        return True
    text_head = resp.text[:2000].lower() if "text" in resp.headers.get("Content-Type", "") else ""
    markers = ("captcha", "datadome", "cf-challenge", "attention required", "access denied", "perimeterx")
    return any(m in text_head for m in markers)


def standalone(probe_fn, source_id: str, max_requests: int = 10) -> ProbeResult:
    """Esegue un probe da riga di comando e salva output/<source_id>/result.json."""
    session = PoliteSession(max_requests=max_requests)
    result = probe_fn(session)
    result.requests_made = session.requests_made
    out_dir = OUTPUT_DIR / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result
