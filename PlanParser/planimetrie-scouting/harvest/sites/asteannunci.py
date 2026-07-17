"""Adapter di sito per AsteAnnunci.it (www.asteannunci.it, gruppo Edicom).

Portale di aste giudiziarie immobiliari. Le schede-annuncio sono servite
lato server (HTML statico) all'URL canonico:

    /aste/<id>/<categoria>/<slug>

e nella sezione "Allegati" espongono link DIRETTI ai documenti, tipicamente:

    /public/<..>/articoli/<hash>_planimetria.pdf   (planimetria)
    /public/<..>/articoli/<hash>_perizia.pdf       (perizia CTU, con piante catastali)

scaricabili senza login (verificato in ricognizione, vedi output/asteannunci/).

RICERCA / PAGINAZIONE (scoperta dal vivo):
    L'elenco delle vendite residenziali e' a /aste-immobiliari/case, con
    paginazione PATH-BASED: pagina 1 = /aste-immobiliari/case, pagine
    successive = /aste-immobiliari/case/page/<N> (12 schede per pagina,
    ~325 pagine). Le card sono link server-rendered a /aste/<id>/...,
    quindi iterabili senza JavaScript.

Regole rispettate: ogni richiesta passa da session.get (robots + ritardo +
retry gia' inclusi); nessun login/captcha/elusione (403/429 -> ProtectionBlocked
e stop); si resta sul dominio del portale; URL sempre assoluti.

La logica di estrazione degli allegati e' quella gia' collaudata in
scout/probes/asteannunci.py: viene RIUSATA qui (con fallback interno equivalente
nel caso il modulo scout non sia importabile).
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..core import HarvestSession, ProtectionBlocked, classify_doc_type
from .base import SiteAdapter

# Riuso della logica di estrazione allegati gia' funzionante in scout/.
try:  # pragma: no cover - dipende dalla presenza del package scout
    from scout.probes.asteannunci import _pick_doc_links as _scout_pick_doc_links
except Exception:  # fallback interno equivalente (definito piu' sotto)
    _scout_pick_doc_links = None

PORTAL_HOST = "asteannunci.it"

# scheda annuncio: /aste/<id>/<categoria>/<slug>
_DETAIL_RE = re.compile(r"/aste/(\d{3,})/\d+/[a-z0-9][a-z0-9\-]*", re.I)
# "Comune (PROV)" nel testo della card, es. "Ponte di legno (BS)"
_COMUNE_RE = re.compile(r"([A-Za-zÀ-ÿ'’.\- ]{2,60}?\([A-Z]{2}\))")

# --- solo per il fallback interno (equivalente a scout/probes/asteannunci.py) ---
_DOC_KEYWORDS = re.compile(
    r"planimetri\w*|elaborato\s+planimetric\w*|perizi\w*|\btavol\w*|floor\s*_?plan", re.I
)
_FILE_EXT_RE = re.compile(r"\.(pdf|p7m|jpe?g|png|tiff?|gif|dwg|dxf|zip)(?:$|[?#])", re.I)
_DOC_URL_HINT = re.compile(r"download|allegat|document|file|attach|view|pdf", re.I)
_BARE_FILE_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:pdf|p7m|jpe?g|png|tiff?|dwg)\b[^\s\"'<>\\]*", re.I
)


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _same_portal(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc == "" or netloc == PORTAL_HOST or netloc.endswith("." + PORTAL_HOST)


class Adapter(SiteAdapter):
    site_id = "asteannunci"
    source_name = "AsteAnnunci.it"
    base_url = "https://www.asteannunci.it/"

    # elenco vendite residenziali (categoria "case"): buona resa di allegati planimetria
    search_path = "/aste-immobiliari/case"
    # tetto di sicurezza: la paginazione si ferma comunque da sola su pagina vuota
    max_pages = 5000

    # ------------------------------------------------------------------ ricerca
    def _search_url(self, page: int) -> str:
        base = urljoin(self.base_url, self.search_path)
        if page <= 1:
            return base
        return f"{base}/page/{page}"

    @staticmethod
    def _card_comune(anchor) -> str:
        """Comune (PROV) della card. La riga localita' e' "Comune (PROV), indirizzo":
        si sceglie l'elemento-foglia piu' corto che la contiene, cosi' da evitare il
        rumore di badge/titolo concatenati nel testo dell'intera card."""
        best: str | None = None
        for el in anchor.find_all(["div", "span", "p", "li"]):
            txt = el.get_text(" ", strip=True)
            if _COMUNE_RE.search(txt) and (best is None or len(txt) < len(best)):
                best = txt
        if best is None:
            return ""
        m = _COMUNE_RE.search(best)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    def _parse_cards(self, html: str, base_url: str) -> list[dict]:
        """Estrae dalle card di una pagina di ricerca (id, url assoluto, comune)."""
        out: list[dict] = []
        seen: set[str] = set()
        for a in _soup(html).find_all("a", href=True):
            href = a["href"].strip()
            m = _DETAIL_RE.search(href)
            if not m:
                continue
            listing_id = m.group(1)
            if listing_id in seen:
                continue
            seen.add(listing_id)
            listing_url = urljoin(base_url, href.split("#")[0].split("?")[0])
            if not _same_portal(listing_url):
                continue
            out.append(
                {
                    "listing_id": listing_id,
                    "listing_url": listing_url,
                    "comune": self._card_comune(a),
                }
            )
        return out

    def iter_detail_urls(
        self, session: HarvestSession, state: dict, max_listings: int
    ) -> Iterator[dict]:
        page = int(state.get("page", 1) or 1)
        if page < 1:
            page = 1
        yielded = 0
        seen_ids: set[str] = set()
        while yielded < max_listings and page <= self.max_pages:
            state["page"] = page  # ripresa: rieseguendo si riparte da questa pagina
            url = self._search_url(page)
            resp = session.get(url)
            # 401/403/429 -> blocco anti-bot: propaga e fermati (nessuna elusione)
            if resp.status_code in (401, 403, 429):
                raise ProtectionBlocked(
                    f"blocco anti-bot sulla ricerca {url} (HTTP {resp.status_code})"
                )
            if resp.status_code != 200:
                return
            cards = self._parse_cards(resp.text, str(resp.url))
            if not cards:
                return  # fine dei risultati
            for item in cards:
                if item["listing_id"] in seen_ids:
                    continue
                seen_ids.add(item["listing_id"])
                yield item
                yielded += 1
                if yielded >= max_listings:
                    return
            page += 1

    # -------------------------------------------------------------- allegati
    def _doc_pairs(self, html: str, base_url: str) -> list[tuple[str, str]]:
        """Coppie (url, label) degli allegati planimetria/perizia/tavola.

        Riusa scout.probes.asteannunci._pick_doc_links se disponibile, altrimenti
        applica localmente la stessa euristica.
        """
        if _scout_pick_doc_links is not None:
            try:
                return list(_scout_pick_doc_links(html, base_url))
            except Exception:
                pass
        return self._fallback_pairs(html, base_url)

    @staticmethod
    def _fallback_pairs(html: str, base_url: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for a in _soup(html).find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
                continue
            text = a.get_text(" ", strip=True)
            blob = f"{href} {text}"
            if _DOC_KEYWORDS.search(blob) and (
                _FILE_EXT_RE.search(href) or _DOC_URL_HINT.search(href)
            ):
                pairs.append((urljoin(base_url, href), text))
        for m in _BARE_FILE_RE.finditer(html):
            if _DOC_KEYWORDS.search(m.group(0)):
                pairs.append((m.group(0), ""))
        return pairs

    def extract_docs(self, session: HarvestSession, listing_url: str, html: str) -> list[dict]:
        docs: list[dict] = []
        seen: set[str] = set()
        for url, label in self._doc_pairs(html, listing_url):
            if not url or url in seen:
                continue
            if not _same_portal(url):  # resta sul dominio del portale
                continue
            seen.add(url)
            docs.append(
                {
                    "label": label,
                    "url": url,
                    "doc_type": classify_doc_type(label, url),
                }
            )
        return docs
