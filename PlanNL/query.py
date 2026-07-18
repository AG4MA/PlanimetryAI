"""
PlanNL — rule-based natural-language query engine over the Knowledge Model.

Deterministic and offline (no network, no LLM): a question in Italian or English
is matched to one of a closed set of intents and answered *only* from the loaded
Building. Every answer carries the data it derives from (``citations``); when the
required data is missing the engine returns an honest "dato non disponibile"
answer rather than inventing a value.

An optional LLM fallback lives in ``PlanNL.llm`` and is never invoked from here.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .knowledge import Building, Room, ROOM_CATEGORIES, normalize_text


@dataclass
class Answer:
    text: str
    intent: str
    data: dict = field(default_factory=dict)
    citations: List[str] = field(default_factory=list)
    available: bool = True

    def format(self) -> str:
        lines = [self.text]
        if self.citations:
            lines.append("  fonte: " + "; ".join(self.citations))
        return "\n".join(lines)


def _fmt_area(room: Room) -> str:
    if room.area_m2 is not None:
        return f"{room.area_m2:.2f} m2"
    if room.area_px is not None:
        return f"{room.area_px:.0f} px2 (scala non impostata -> m2 non disponibile)"
    return "area non disponibile"


def _room_ref(room: Room) -> str:
    return f"room id={room.id} label='{room.display_label}'"


# --------------------------------------------------------------------------- #
# Room resolution by name
# --------------------------------------------------------------------------- #
def _find_rooms_by_name(building: Building, phrase: str) -> List[Room]:
    """Resolve a room reference in a phrase, by category keyword or fuzzy label."""
    norm = normalize_text(phrase)
    # 1) category keyword present in the phrase
    matched_categories = [
        cat for cat, kws in ROOM_CATEGORIES.items() if any(kw in norm for kw in kws)
    ]
    hits: List[Room] = []
    for cat in matched_categories:
        hits.extend(building.rooms_of_category(cat))
    if hits:
        return _dedup(hits)
    # 2) fuzzy match against raw labels
    scored = []
    for r in building.rooms:
        label = normalize_text(r.label)
        if not label:
            continue
        if label in norm or norm in label:
            scored.append((1.0, r))
            continue
        ratio = difflib.SequenceMatcher(None, label, norm).ratio()
        if ratio >= 0.6:
            scored.append((ratio, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return _dedup([r for _, r in scored])


def _dedup(rooms: List[Room]) -> List[Room]:
    seen = set()
    out = []
    for r in rooms:
        if r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out


# --------------------------------------------------------------------------- #
# Intent handlers  (each: (Building, question_norm, raw_question) -> Answer|None)
# --------------------------------------------------------------------------- #
def _h_count_rooms(b: Building, q: str, raw: str) -> Optional[Answer]:
    if re.search(r"\bquant[ei]\b.*\bstanz|\bhow many\b.*\broom|\bnumero.*stanz", q):
        n = len(b.rooms)
        return Answer(
            text=f"Ci sono {n} stanze rilevate nella planimetria.",
            intent="count_rooms",
            data={"count": n},
            citations=[f"{n} room record(s) nel Knowledge Model"],
        )
    return None


def _h_list_rooms(b: Building, q: str, raw: str) -> Optional[Answer]:
    if re.search(r"\belenc|\blista\b|\blist\b.*\broom|quali stanze|which rooms\b", q):
        if not b.rooms:
            return Answer("Nessuna stanza presente nel Knowledge Model.", "list_rooms", available=False)
        items = [f"- {r.display_label} (id={r.id}, {_fmt_area(r)})" for r in b.rooms]
        return Answer(
            text="Stanze rilevate:\n" + "\n".join(items),
            intent="list_rooms",
            data={"rooms": [r.id for r in b.rooms]},
            citations=[f"{len(b.rooms)} room record(s)"],
        )
    return None


def _h_total_area(b: Building, q: str, raw: str) -> Optional[Answer]:
    if re.search(r"area totale|superficie totale|totale.*mq|total area|overall area", q):
        total = b.total_area_m2
        if total is None:
            return Answer(
                text="Area totale in m2 non disponibile: la scala non e impostata "
                     "(scale_factor mancante), quindi le aree restano in pixel.",
                intent="total_area",
                available=False,
                citations=["scale_factor=None"],
            )
        return Answer(
            text=f"La superficie totale rilevata e circa {total:.2f} m2.",
            intent="total_area",
            data={"total_area_m2": total},
            citations=[f"somma di {sum(1 for r in b.rooms if r.area_m2 is not None)} stanze con area metrica"],
        )
    return None


def _h_extreme_room(b: Building, q: str, raw: str) -> Optional[Answer]:
    want_large = re.search(r"piu grand|più grand|largest|biggest|maggiore", q)
    want_small = re.search(r"piu piccol|più piccol|smallest|minore", q)
    if not (want_large or want_small):
        return None
    measurable = [r for r in b.rooms if (r.area_m2 or r.area_px)]
    if not measurable:
        return Answer("Nessuna area disponibile per confrontare le stanze.", "extreme_room", available=False)
    key = lambda r: (r.area_m2 if r.area_m2 is not None else (r.area_px or 0.0))
    room = max(measurable, key=key) if want_large else min(measurable, key=key)
    which = "piu grande" if want_large else "piu piccola"
    return Answer(
        text=f"La stanza {which} e '{room.display_label}' (id={room.id}), {_fmt_area(room)}.",
        intent="extreme_room",
        data={"room_id": room.id},
        citations=[_room_ref(room)],
    )


def _h_area_of_room(b: Building, q: str, raw: str) -> Optional[Answer]:
    if not re.search(r"\barea\b|quanto.*grand|how big|dimension|superficie|grande e", q):
        return None
    rooms = _find_rooms_by_name(b, raw)
    if not rooms:
        return None  # let other handlers try; falls through to unknown
    if len(rooms) > 1:
        opts = ", ".join(f"{r.display_label} (id={r.id}, {_fmt_area(r)})" for r in rooms[:6])
        return Answer(
            text=f"Trovate {len(rooms)} stanze compatibili: {opts}. Specifica quale (per id).",
            intent="area_of_room",
            data={"candidates": [r.id for r in rooms]},
            citations=[_room_ref(r) for r in rooms[:6]],
        )
    room = rooms[0]
    return Answer(
        text=f"La stanza '{room.display_label}' (id={room.id}) misura {_fmt_area(room)}.",
        intent="area_of_room",
        data={"room_id": room.id, "area_m2": room.area_m2, "area_px": room.area_px},
        citations=[_room_ref(room)],
    )


def _h_rooms_of_type(b: Building, q: str, raw: str) -> Optional[Answer]:
    for cat, kws in ROOM_CATEGORIES.items():
        if any(kw in q for kw in kws):
            rooms = b.rooms_of_category(cat)
            if not rooms:
                return Answer(
                    text=f"Nessuna stanza di tipo '{cat}' rilevata.",
                    intent="rooms_of_type",
                    data={"category": cat, "rooms": []},
                    available=False,
                )
            items = ", ".join(f"{r.display_label} (id={r.id}, {_fmt_area(r)})" for r in rooms)
            return Answer(
                text=f"Stanze di tipo '{cat}': {len(rooms)} -> {items}.",
                intent="rooms_of_type",
                data={"category": cat, "rooms": [r.id for r in rooms]},
                citations=[_room_ref(r) for r in rooms],
            )
    return None


def _h_adjacency(b: Building, q: str, raw: str) -> Optional[Answer]:
    if not re.search(r"confin|adiacent|vicin|adjacent|next to|attorno|around", q):
        return None
    rooms = _find_rooms_by_name(b, raw)
    if not rooms:
        return None
    room = rooms[0]
    if not b.adjacency:
        return Answer(
            text=f"Le adiacenze per '{room.display_label}' non sono disponibili: la "
                 f"topologia del Knowledge Model non e allineata agli id delle stanze.",
            intent="adjacency",
            available=False,
            citations=["topology.adjacency non mappata sugli id stanza"],
        )
    if not room.neighbors:
        return Answer(
            text=f"Nessuna stanza risulta confinante con '{room.display_label}' (id={room.id}).",
            intent="adjacency",
            data={"room_id": room.id, "neighbors": []},
            citations=[_room_ref(room)],
        )
    names = []
    for nid in room.neighbors:
        nb = b.room_by_id(nid)
        names.append(f"{nb.display_label} (id={nid})" if nb else f"id={nid}")
    return Answer(
        text=f"'{room.display_label}' (id={room.id}) confina con: " + ", ".join(names) + ".",
        intent="adjacency",
        data={"room_id": room.id, "neighbors": room.neighbors},
        citations=[_room_ref(room), "topology.adjacency"],
    )


def _h_orientation(b: Building, q: str, raw: str) -> Optional[Answer]:
    if not re.search(r"espost|orient['a ]|verso (nord|sud|est|ovest)|face (north|south|east|west)|sun|sole", q):
        return None
    # Requires per-wall orientation + a north reference, which the current model
    # does not carry. Answer honestly rather than guessing.
    return Answer(
        text="Esposizione/orientamento delle stanze non disponibile: il Knowledge "
             "Model attuale non contiene pareti classificate per lato ne un nord "
             "affidabile (orientation_north). Questa risposta sara possibile quando "
             "PlanParser esportera pareti + bussola.",
        intent="orientation",
        available=False,
        citations=[f"orientation_north={b.orientation_north}", "walls: assenti"],
    )


def _h_scale(b: Building, q: str, raw: str) -> Optional[Answer]:
    if re.search(r"\bscala\b|\bscale\b|orientament|\bnord\b|\bnorth\b|metad|metadat", q):
        parts = [
            f"scala: {b.scale if b.scale else 'non impostata'}",
            f"scale_factor (m/px): {b.scale_factor if b.scale_factor else 'non disponibile'}",
            f"nord: {b.orientation_north if b.orientation_north is not None else 'non disponibile'}",
            f"file: {b.source_file or 'n/d'}",
        ]
        return Answer(
            text="Metadati planimetria -> " + "; ".join(parts) + ".",
            intent="scale",
            data={"scale": b.scale, "scale_factor": b.scale_factor, "north": b.orientation_north},
            citations=["meta/source del Knowledge Model"],
        )
    return None


# Order matters: more specific intents first. A question naming one room and
# asking its size ("quanto e grande la cucina?") must resolve to `area_of_room`
# before the broader `rooms_of_type` (which only counts/lists a category).
HANDLERS: List[Callable[[Building, str, str], Optional[Answer]]] = [
    _h_count_rooms,
    _h_scale,
    _h_orientation,
    _h_adjacency,
    _h_extreme_room,
    _h_total_area,
    _h_area_of_room,
    _h_rooms_of_type,
    _h_list_rooms,
]


SUPPORTED = [
    "Quante stanze ci sono?",
    "Elenca le stanze / Which rooms are there?",
    "Quanto e grande la cucina? / What is the area of the kitchen?",
    "Qual e la stanza piu grande / piu piccola?",
    "Qual e l'area totale? (richiede scala impostata)",
    "Quanti bagni / camere ci sono?",
    "Cosa confina con il bagno? (richiede topologia allineata)",
    "Quali stanze sono esposte a sud? (richiede pareti + nord)",
    "Che scala ha la planimetria?",
]


def answer(building: Building, question: str) -> Answer:
    """Answer a single natural-language question deterministically."""
    raw = question.strip()
    q = normalize_text(raw)
    if not q:
        return _unknown(building)
    for handler in HANDLERS:
        try:
            res = handler(building, q, raw)
        except Exception as exc:  # defensive: never crash on a query
            return Answer(f"Errore nell'elaborare la domanda: {exc}", "error", available=False)
        if res is not None:
            return res
    return _unknown(building)


def _unknown(building: Building) -> Answer:
    return Answer(
        text="Non ho capito la domanda. Domande supportate:\n"
        + "\n".join(f"  - {s}" for s in SUPPORTED),
        intent="unknown",
        available=False,
    )
