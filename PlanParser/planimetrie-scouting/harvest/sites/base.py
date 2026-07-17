"""Interfaccia comune degli adapter di sito per l'harvester massivo.

Un adapter implementa DUE cose:
  1. iter_detail_urls(session, state, max_listings): generatore che paginando la
     ricerca del portale produce dict {"listing_id", "listing_url"} per ogni scheda
     immobile. Deve aggiornare `state` (dict persistito su disco) per permettere la
     ripresa: es. state["page"], e fermarsi da solo quando la ricerca e' esaurita.
  2. extract_docs(session, listing_url, html): dato l'HTML della scheda, ritorna la
     lista dei documenti-planimetria come dict {"label", "url", "doc_type"}.

L'adapter NON scarica i documenti e NON scrive il manifest: se ne occupa il runner
(harvest/__main__.py), che applica dedup, tetti e provenienza in modo uniforme.

Regole che ogni adapter DEVE rispettare:
- passare da session.get (robots + ritardo + retry gia' inclusi);
- non tentare login, captcha o elusioni; su ProtectionBlocked propagare l'eccezione;
- restare sul dominio del portale.
"""
from __future__ import annotations

from typing import Iterator

from ..core import HarvestSession, classify_doc_type


class SiteAdapter:
    site_id: str = ""
    source_name: str = ""
    base_url: str = ""
    source_family: str = "auction"
    acquisition_basis: str = "public_document_internal_use"
    license: str = "documento di procedura pubblica"

    def iter_detail_urls(
        self, session: HarvestSession, state: dict, max_listings: int
    ) -> Iterator[dict]:
        raise NotImplementedError

    def extract_docs(self, session: HarvestSession, listing_url: str, html: str) -> list[dict]:
        raise NotImplementedError

    # utilita' condivisa: gli adapter possono usarla per etichettare i documenti
    @staticmethod
    def doc_type(label: str, url: str) -> str:
        return classify_doc_type(label, url)


def get_adapter(site_id: str) -> SiteAdapter:
    """Factory: importa e istanzia l'adapter <site_id> dal package sites."""
    import importlib

    module = importlib.import_module(f"harvest.sites.{site_id}")
    adapter_cls = getattr(module, "Adapter")
    return adapter_cls()
