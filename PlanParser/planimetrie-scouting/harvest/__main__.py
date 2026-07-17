"""Runner dell'harvester massivo.

Uso:
  python -m harvest --site asteannunci                 # raccolta con default
  python -m harvest --site asteannunci,astegiudiziarie --max-docs 5000
  python -m harvest --site asteannunci --delay 1.5 --max-listings 2000

Il runner e' RESUMABLE: rieseguendolo riparte dallo stato salvato e salta
listing/documenti gia' presenti nel manifest. Ctrl-C lo ferma in modo pulito.
"""
from __future__ import annotations

import argparse
import sys

from .core import (
    DocRecord,
    HarvestSession,
    Manifest,
    ProtectionBlocked,
    RobotsDisallowed,
    WANTED_TYPES,
    download_document,
    guess_ext,
    safe_name,
    site_dir,
)
from .sites.base import get_adapter

import requests


def harvest_site(site_id: str, *, max_docs: int, max_listings: int, delay: float) -> int:
    adapter = get_adapter(site_id)
    sdir = site_dir(site_id)
    manifest = Manifest(sdir)
    session = HarvestSession(delay_s=delay)
    state = manifest.load_state()

    print(f"[{site_id}] avvio · gia' nel manifest: {manifest.doc_count} documenti, "
          f"{len(manifest.seen_listing_ids)} schede viste · stato: {state or 'nuovo'}", flush=True)

    new_docs = 0
    listings_seen = 0
    consecutive_blocks = 0
    try:
        for item in adapter.iter_detail_urls(session, state, max_listings):
            listing_id = str(item["listing_id"])
            listing_url = item["listing_url"]
            listings_seen += 1
            manifest.save_state(state)

            if listing_id in manifest.seen_listing_ids:
                continue
            try:
                resp = session.get(listing_url)
            except RobotsDisallowed:
                continue
            except (requests.RequestException, ProtectionBlocked) as exc:
                print(f"[{site_id}] scheda {listing_id} saltata: {exc}", flush=True)
                continue
            if resp.status_code != 200:
                continue

            docs = adapter.extract_docs(session, listing_url, resp.text)
            wanted = [d for d in docs if d.get("doc_type", adapter.doc_type(d.get("label", ""), d["url"])) in WANTED_TYPES]
            comune = item.get("comune", "")
            got_here = 0
            for d in wanted:
                doc_url = d["url"]
                if doc_url in manifest.seen_doc_urls:
                    continue
                doc_type = d.get("doc_type") or adapter.doc_type(d.get("label", ""), doc_url)
                try:
                    body, sha, status, ctype = download_document(session, doc_url)
                except RobotsDisallowed:
                    continue
                except ProtectionBlocked as exc:
                    consecutive_blocks += 1
                    print(f"[{site_id}] BLOCCO anti-bot: {exc} · blocchi consecutivi={consecutive_blocks}", flush=True)
                    if consecutive_blocks >= 5:
                        print(f"[{site_id}] troppi blocchi consecutivi: interrompo per rispetto del sito.", flush=True)
                        raise
                    break
                except requests.RequestException as exc:
                    print(f"[{site_id}] errore su {doc_url}: {exc}", flush=True)
                    continue
                consecutive_blocks = 0
                if not body or not sha:
                    continue
                if sha in manifest.seen_sha:
                    manifest.seen_doc_urls.add(doc_url)  # stesso file, URL diverso
                    continue
                ext = guess_ext(doc_url, ctype, body[:8])
                # nome leggibile: <sito>__<comune>__<listing>__<hash8>.<ext>, tutto in PLANIMETRIE/
                fname = f"{site_id}__{safe_name(comune) or 'na'}__{listing_id}__{sha[:8]}.{ext}"
                manifest.store_doc(fname, body)
                rec = DocRecord(
                    source_name=adapter.source_name,
                    source_family=adapter.source_family,
                    listing_id=listing_id,
                    listing_url=listing_url,
                    doc_url=doc_url,
                    doc_label=d.get("label", "")[:200],
                    doc_type=doc_type,
                    file_name=fname,
                    sha256=sha,
                    size_bytes=len(body),
                    format=ext,
                    http_status=status,
                    comune=comune,
                    acquisition_basis=adapter.acquisition_basis,
                    license=adapter.license,
                )
                manifest.append(rec)
                new_docs += 1
                got_here += 1
                if new_docs % 25 == 0:
                    print(f"[{site_id}] +{new_docs} documenti (totale manifest: {manifest.doc_count})", flush=True)
                if new_docs >= max_docs:
                    print(f"[{site_id}] raggiunto max-docs={max_docs}", flush=True)
                    return new_docs
            if got_here:
                print(f"[{site_id}] scheda {listing_id}: +{got_here} doc ({listing_url})", flush=True)
    except ProtectionBlocked:
        print(f"[{site_id}] fermato dai blocchi anti-bot (nessuna elusione tentata).", flush=True)
    except KeyboardInterrupt:
        print(f"[{site_id}] interrotto dall'utente.", flush=True)
    finally:
        manifest.save_state(state)
        print(f"[{site_id}] fine · nuovi documenti in questa run: {new_docs} · "
              f"schede scorse: {listings_seen} · totale manifest: {manifest.doc_count} · "
              f"richieste HTTP: {session.requests_made}", flush=True)
    return new_docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvest", description="Harvester massivo di planimetrie da aste giudiziarie")
    parser.add_argument("--site", required=True, help="site_id (uno o piu' separati da virgola)")
    parser.add_argument("--max-docs", type=int, default=100000, help="tetto documenti NUOVI per sito in questa run")
    parser.add_argument("--max-listings", type=int, default=100000, help="tetto schede da scorrere per sito")
    parser.add_argument("--delay", type=float, default=1.2, help="ritardo minimo fra richieste (s)")
    args = parser.parse_args(argv)

    total = 0
    for site_id in [s.strip() for s in args.site.split(",") if s.strip()]:
        try:
            total += harvest_site(site_id, max_docs=args.max_docs, max_listings=args.max_listings, delay=args.delay)
        except Exception as exc:  # un sito non deve fermare gli altri
            print(f"[{site_id}] errore fatale: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    print(f"TOTALE nuovi documenti: {total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
