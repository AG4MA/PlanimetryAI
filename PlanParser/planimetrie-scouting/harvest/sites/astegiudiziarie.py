"""Adapter di sito: Aste Giudiziarie Inlinea (www.astegiudiziarie.it).

Portale storico delle vendite giudiziarie. Le schede immobiliari espongono gli
allegati come URL diretti /Allegato/<nomefile.ext>/<id> (JPG planimetrie e foto,
PDF perizia/avviso/ordinanza), scaricabili senza login.

Paginazione della RICERCA
-------------------------
La ricerca a form (`POST /results`, con anti-forgery token) non e' percorribile
con sole GET, e le pagine di elenco caricano i risultati via JS. Il portale pero'
pubblica il proprio sitemap: `robots.txt` indica `/sitemapindex`, che a sua volta
elenca `/SiteMap/SchedeDettagliateImmobili` -- l'urlset (gzip) con TUTTE le schede
immobiliari (categoria immobili). Iteriamo quelle `<loc>` come "pagine" della
ricerca: e' pura GET, rispetta robots, ed e' l'elenco piu' completo e stabile.

`state["page"]` memorizza l'offset gia' consumato nell'elenco di schede, cosi' una
run successiva riparte da dove si era fermata (i duplicati sono comunque filtrati
a monte dal manifest per listing_id / sha).
"""
from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..core import HarvestSession
from .base import SiteAdapter

_HOST = "astegiudiziarie.it"

# <loc> nel sitemap
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
# una scheda immobile: .../vendita-asta-...-l<id>-p<proc>  oppure  .../vendita-asta-...-<id>
_DETAIL_RE = re.compile(r"/vendita-asta-.+?(?:-l\d+-p\d+|-\d{5,})$", re.I)
_LID_LP_RE = re.compile(r"-l(\d+)-p\d+$", re.I)
_LID_TAIL_RE = re.compile(r"-(\d{5,})$")
# allegato diretto: /Allegato/<nomefile.ext>/<id>  (case-insensitive)
_ALLEGATO_RE = re.compile(r"^/?allegato/", re.I)


def _same_host(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith(_HOST)


class Adapter(SiteAdapter):
    site_id = "astegiudiziarie"
    source_name = "Aste Giudiziarie Inlinea"
    base_url = "https://www.astegiudiziarie.it/"

    # sitemap urlset con le schede dettagliate degli immobili (categoria immobili)
    sitemap_url = "https://www.astegiudiziarie.it/SiteMap/SchedeDettagliateImmobili"
    # fallback: indice dei sitemap, da cui filtrare i sotto-sitemap degli immobili
    sitemap_index_url = "https://www.astegiudiziarie.it/sitemapindex"

    # -- ricerca: iterazione paginata delle schede via sitemap --------------------

    def iter_detail_urls(
        self, session: HarvestSession, state: dict, max_listings: int
    ) -> Iterator[dict]:
        detail_urls = self._collect_detail_urls(session)
        if not detail_urls:
            return

        start = int(state.get("page", 0) or 0)
        if start >= len(detail_urls):
            return  # elenco esaurito rispetto alla ripresa

        yielded = 0
        for idx in range(start, len(detail_urls)):
            if yielded >= max_listings:
                break
            url = detail_urls[idx]
            listing_id = self._listing_id(url)
            state["page"] = idx + 1  # prossima posizione da cui riprendere
            yielded += 1
            yield {"listing_id": listing_id, "listing_url": url}

    def _collect_detail_urls(self, session: HarvestSession) -> list[str]:
        """Scarica il sitemap degli immobili e ne estrae le <loc> delle schede.

        Gestisce sia l'urlset diretto sia (fallback) l'indice dei sitemap.
        """
        locs = self._fetch_locs(session, self.sitemap_url)
        details = [u for u in locs if _same_host(u) and _DETAIL_RE.search(urlparse(u).path)]
        if details:
            return details

        # fallback: passa dall'indice e recupera i sotto-sitemap "SchedeDettagliateImmobili"
        index_locs = self._fetch_locs(session, self.sitemap_index_url)
        subs = [u for u in index_locs if _same_host(u) and "schededettagliateimmobili" in u.lower()]
        out: list[str] = []
        seen: set[str] = set()
        for sub in subs:
            for u in self._fetch_locs(session, sub):
                if _same_host(u) and _DETAIL_RE.search(urlparse(u).path) and u not in seen:
                    seen.add(u)
                    out.append(u)
        return out

    def _fetch_locs(self, session: HarvestSession, url: str) -> list[str]:
        resp = session.get(url)
        if resp.status_code != 200:
            return []
        data = resp.content
        if data[:2] == b"\x1f\x8b":  # sitemap servito come gzip grezzo (senza Content-Encoding)
            try:
                data = gzip.decompress(data)
            except OSError:
                return []
        text = data.decode("utf-8", "replace")
        return _LOC_RE.findall(text)

    @staticmethod
    def _listing_id(url: str) -> str:
        path = urlparse(url).path
        m = _LID_LP_RE.search(path)
        if m:
            return m.group(1)
        m = _LID_TAIL_RE.search(path)
        if m:
            return m.group(1)
        return path.rstrip("/").rsplit("/", 1)[-1] or url

    # -- estrazione allegati dalla scheda ----------------------------------------

    def extract_docs(self, session: HarvestSession, listing_url: str, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        docs: list[dict] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            raw = a["href"].strip()
            if not _ALLEGATO_RE.match(raw):
                continue
            url = urljoin(listing_url, raw)
            if not _same_host(url) or url in seen:
                continue
            seen.add(url)
            label = a.get_text(" ", strip=True) or Path(urlparse(url).path).name
            docs.append(
                {
                    "label": label[:200],
                    "url": url,
                    "doc_type": self.doc_type(label, url),
                }
            )
        return docs
