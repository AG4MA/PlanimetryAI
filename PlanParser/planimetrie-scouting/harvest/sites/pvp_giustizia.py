"""Adapter per il PVP - Portale Vendite Pubbliche del Ministero della Giustizia.

Sito: https://pvp.giustizia.it  (SPA Angular / Entando).

Come funziona il portale (ricostruito OFFLINE dai bundle JS in
output/pvp_giustizia/cache/ e confermato dalla risposta di ricerca gia'
catturata in cache/search_vendite.json):

  * La ricerca annunci NON e' una pagina HTML paginata ma un'API JSON:
        POST  {VE_BASE}/vendite/ricerca?page=N&size=K&isPreview=false&language=it
        body: {"filtroAnnunci":0,"ricercaLibera":null,"tipoLotto":"IMMOBILI"}
    Risposta (envelope custom + Spring Page):
        {"messaggio":"Operazione effettuata con successo",
         "body":{"content":[{...annuncio...}], "totalPages":793,
                 "totalElements":7923, "last":false, "number":0, ...}}
    Ogni annuncio ha: id (idAnnuncio), tipoLotto, indirizzo.citta, descLotto, ...

  * Il dettaglio di un annuncio (con i lotti/beni e i relativi allegati:
    perizia/CTU, planimetrie, avviso di vendita) e' anch'esso un'API JSON:
        GET   {VE_BASE}/vendite/{id}
    e la lista allegati dell'esperimento vendita:
        GET   {VE_BASE}/allegato/{idEspVendita}
    Il singolo file allegato si scarica (GET) da {VE_BASE}/allegato/{idAllegato}.

  * VE_BASE si ricava da fe-config: host + "/" + msUrl.vendite =
        https://pvp.giustizia.it + / + ve-3f723b85-986a1b71/ve-ms

IMPORTANTE — perche' questo adapter NON e' operativo (verificato 2026-07-17):
  L'API di ricerca (RIC_BASE/ricerca/vendite) e' pubblica e ha restituito dati
  reali (cache/search_vendite.json, 7923 immobili). MA il portale e' frontato da
  un WAF che filtra sull'IDENTITA' del client:
    - con User-Agent onesto/non-browser -> "Web Page Blocked / Attack ID" (500/403)
      gia' sulla homepage;
    - con User-Agent di browser -> la homepage passa e rilascia i cookie, ma il
      superamento del WAF dipende dall'impersonare un browser.
  Passare quel WAF in modo affidabile richiede impersonazione di browser (ed
  eventuale gestione della reputazione IP): e' elusione di un controllo anti-bot
  esplicito, quindi NON lo facciamo. L'adapter solleva ProtectionBlocked e il
  runner si ferma pulito. Resta qui come riferimento dell'API corretta nel caso
  in futuro si ottenga un accesso autorizzato/legittimo (es. convenzione, API
  ufficiale) che non richieda di aggirare la protezione.

Nota: anche la catena dettaglio->allegati->download non e' verificabile end-to-end
finche' il WAF blocca il client. L'endpoint di ricerca invece e' confermato.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterator
from urllib.parse import urlparse

import requests

from ..core import HarvestSession, ProtectionBlocked, RobotsDisallowed
from .base import SiteAdapter


HOST = "https://pvp.giustizia.it"
# basi microservizio da output/pvp_giustizia/cache/fe_config.json (msUrl.*)
RIC_BASE = f"{HOST}/ric-496b258c-986a1b71/ric-ms"  # microservizio RICERCA
VE_BASE = f"{HOST}/ve-3f723b85-986a1b71/ve-ms"     # microservizio VENDITE (dettaglio/allegati)

# CORREZIONE (verificata): la ricerca pubblica sta sul microservizio 'ricerca',
# non su vendite. L'endpoint qui sotto e' quello che ha restituito dati reali
# durante la ricognizione (cache/search_vendite.json, 7923 immobili).
# L'endpoint sbagliato precedente (VE_BASE/vendite/ricerca) rispondeva 401.
SEARCH_URL = f"{RIC_BASE}/ricerca/vendite"
DETAIL_URL = f"{VE_BASE}/vendite/{{id}}"          # GET dettaglio annuncio (JSON)
ALLEGATI_LIST_URL = f"{VE_BASE}/allegato/{{id}}"  # GET lista allegati per esperimento

PAGE_SIZE = 48  # size di pagina per la ricerca

# marcatori della pagina di blocco del WAF (da rispettare, non eludere)
_WAF_MARKERS = (
    "web page blocked",
    "the url you requested has been blocked",
    "attack id",
    "request blocked",
)


def _is_waf_block(resp: requests.Response) -> bool:
    """True se la risposta e' un blocco di protezione (WAF/gateway).

    Le API del PVP rispondono SEMPRE in JSON: una risposta text/html a errore
    e' quindi il WAF o il gateway che intercetta il client, e va rispettata.
    N.B.: la pagina di blocco del WAF ha un'immagine base64 enorme nell'header,
    quindi il testo "Web Page Blocked" compare ben oltre i primi KB: scansiono
    tutto il corpo, non solo l'inizio.
    """
    if resp.status_code in (401, 403, 429):
        return True
    ct = resp.headers.get("Content-Type", "").lower()
    if "text/html" in ct:
        body = (resp.text or "").lower()
        if any(m in body for m in _WAF_MARKERS):
            return True
        # HTML su un endpoint JSON in stato d'errore = interferenza gateway/WAF
        if resp.status_code >= 400:
            return True
    return False


class Adapter(SiteAdapter):
    site_id = "pvp_giustizia"
    source_name = "PVP - Portale Vendite Pubbliche"
    base_url = HOST

    # ------------------------------------------------------------------ #
    # POST educato riusando la SESSIONE unica dell'harvester.
    # HarvestSession espone solo .get(); la ricerca del PVP e' POST-only,
    # quindi riuso session.http (la STESSA requests.Session: stesso UA,
    # niente sessioni parallele) applicando a mano robots + ritardo +
    # conteggio richieste + rilevamento blocchi, esattamente come session.get.
    # ------------------------------------------------------------------ #
    def _polite_post(self, session: HarvestSession, url: str, *, json_body: dict, params: dict) -> requests.Response:
        if session.allowed_by_robots(url) is False:
            raise RobotsDisallowed(url)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(session.retries):
            session._wait()
            session.requests_made += 1
            try:
                resp = session.http.post(
                    url, json=json_body, params=params, headers=headers, timeout=session.timeout_s
                )
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            # blocco anti-bot: fermarsi, NON eludere
            if _is_waf_block(resp):
                raise ProtectionBlocked(f"WAF block su {url} (HTTP {resp.status_code})")
            if resp.status_code in (500, 502, 503, 504):
                last_exc = requests.HTTPError(f"{resp.status_code} su {url}")
                time.sleep(min(2 ** attempt * 2, 20))
                continue
            return resp
        if isinstance(last_exc, Exception):
            raise last_exc
        raise requests.RequestException(f"POST fallito su {url}")

    # ------------------------------------------------------------------ #
    # 1) paginazione della RICERCA immobili -> yield delle schede
    # ------------------------------------------------------------------ #
    def iter_detail_urls(self, session: HarvestSession, state: dict, max_listings: int) -> Iterator[dict]:
        page = int(state.get("page", 0))
        yielded = 0
        body = {"filtroAnnunci": 0, "ricercaLibera": None, "tipoLotto": "IMMOBILI"}

        while yielded < max_listings:
            params = {"page": page, "size": PAGE_SIZE, "isPreview": "false", "language": "it"}
            resp = self._polite_post(session, SEARCH_URL, json_body=body, params=params)
            if resp.status_code != 200:
                return
            try:
                payload = resp.json()
            except ValueError:
                # risposta non-JSON inattesa: mi fermo senza inventare nulla
                return
            data = payload.get("body") or {}
            content = data.get("content") or []
            if not content:
                return

            for item in content:
                ann_id = item.get("id")
                if ann_id is None:
                    continue
                indirizzo = item.get("indirizzo") or {}
                comune = indirizzo.get("citta") or indirizzo.get("descComune") or ""
                yield {
                    "listing_id": str(ann_id),
                    # uso l'API di dettaglio come listing_url: cosi' il runner con la
                    # sua session.get scarica direttamente il JSON di dettaglio, che
                    # extract_docs riceve in `html` e analizza per gli allegati.
                    "listing_url": DETAIL_URL.format(id=ann_id),
                    "comune": comune,
                }
                yielded += 1
                if yielded >= max_listings:
                    break

            # avanzamento pagina + stato per la ripresa
            page += 1
            state["page"] = page
            if data.get("last") is True:
                return
            total_pages = data.get("totalPages")
            if isinstance(total_pages, int) and page >= total_pages:
                return

    # ------------------------------------------------------------------ #
    # 2) estrazione allegati (planimetria / perizia / tavola) dal dettaglio
    #    `html` = corpo della GET su listing_url (=DETAIL_URL) fatta dal runner,
    #    che per questo portale e' JSON, non HTML.
    # ------------------------------------------------------------------ #
    def extract_docs(self, session: HarvestSession, listing_url: str, html: str) -> list[dict]:
        text = html or ""
        low = text.lower()
        # se il runner ha ricevuto la pagina di blocco del WAF: rispettarla
        if any(m in low for m in _WAF_MARKERS):
            raise ProtectionBlocked(f"WAF block sul dettaglio {listing_url}")

        detail = self._parse_json(text)
        allegati = self._collect_allegati(detail) if detail is not None else []

        # se il dettaglio non contiene gli allegati inline, provo la lista
        # allegati dell'esperimento vendita (GET, quindi via session.get educato)
        if not allegati:
            ann_id = self._id_from_url(listing_url)
            if ann_id:
                try:
                    r = session.get(ALLEGATI_LIST_URL.format(id=ann_id))
                except (RobotsDisallowed, requests.RequestException):
                    r = None
                if r is not None and r.status_code == 200:
                    if _is_waf_block(r):
                        raise ProtectionBlocked(f"WAF block su allegati {ann_id}")
                    lst = self._parse_json(r.text)
                    allegati = self._collect_allegati(lst) if lst is not None else []

        docs: list[dict] = []
        seen: set[str] = set()
        for al in allegati:
            al_id = al.get("id") or al.get("idAllegato")
            if al_id is None:
                continue
            label = " ".join(
                str(al.get(k, ""))
                for k in ("descTipoAllegato", "tipoAllegato", "descrizione", "nome", "nomeFile", "titolo")
                if al.get(k)
            ).strip()
            url = f"{VE_BASE}/allegato/{al_id}"
            if url in seen:
                continue
            seen.add(url)
            docs.append({
                "label": label or f"allegato {al_id}",
                "url": url,
                "doc_type": self.doc_type(label, url),
            })
        return docs

    # ------------------------------------------------------------------ #
    # helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_json(text: str):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _id_from_url(url: str) -> str:
        m = re.search(r"/(\d+)(?:[/?#]|$)", urlparse(url).path)
        return m.group(1) if m else ""

    @staticmethod
    def _collect_allegati(obj) -> list[dict]:
        """Raccoglie ricorsivamente ogni lista di dict sotto una chiave 'allegat*'.

        Regge sia l'envelope {'body': {...}} sia strutture annidate
        (vendita -> lotti[] -> beni[] -> allegati[]).
        """
        found: list[dict] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if "allegat" in k.lower() and isinstance(v, list):
                        for el in v:
                            if isinstance(el, dict):
                                found.append(el)
                    walk(v)
            elif isinstance(node, list):
                for el in node:
                    walk(el)

        walk(obj)
        return found
