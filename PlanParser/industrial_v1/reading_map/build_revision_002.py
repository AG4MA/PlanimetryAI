from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

import build_revision_001 as r1


ROOT = Path(__file__).resolve().parents[2]
FLOOR_IMAGE = (
    ROOT
    / "industrial_v1/floor_units/artifacts/scheda_catastale/page_0001/revision_001/fr_001.png"
)
FLOOR_UNITS = (
    ROOT
    / "industrial_v1/floor_units/artifacts/scheda_catastale/page_0001/revision_001/floor_units.json"
)
REGIONS = (
    ROOT
    / "atomic_v2/region_split/artifacts/scheda_catastale/page_0001/revision_002/regions.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/reading_map/artifacts/scheda_catastale/region_001/revision_002"
)


def rgba_draw(image: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(image, "RGBA")


def draw_floor_scope(
    floor: Image.Image,
    floor_bbox: dict,
    region_bbox: list[int],
) -> tuple[Image.Image, list[int]]:
    out = floor.convert("RGB").copy()
    draw = rgba_draw(out)
    page_x, page_y, width, height = map(int, region_bbox)
    local = [page_x - int(floor_bbox["x"]), page_y - int(floor_bbox["y"]), width, height]
    x, y, w, h = local
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(37, 99, 235, 22), outline=(220, 38, 38, 255), width=6)
    label = "REGION_001: area analizzata dagli algoritmi sottostanti"
    label_font = r1.font(18, True)
    box = draw.textbbox((0, 0), label, font=label_font)
    label_w = box[2] - box[0]
    label_h = box[3] - box[1]
    tx = min(max(x + 8, 4), out.width - label_w - 12)
    ty = max(4, y + 8)
    draw.rectangle((tx - 5, ty - 4, tx + label_w + 5, ty + label_h + 5), fill=(255, 255, 255, 235))
    draw.text((tx, ty), label, fill=(185, 28, 28, 255), font=label_font)
    return out, local


def draw_geometry(base: Image.Image, linework: dict, graph: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for item in linework.get("candidates", []):
        points = [tuple(map(float, point)) for point in item["points_px"]]
        draw.line(points, fill="#f59e0b" if item.get("abstained") else "#2563eb", width=2)
    for node in graph.get("nodes", []):
        x, y = map(float, node["coordinate_crop_px"])
        color = "#d946ef" if node.get("abstained") else "#16a34a"
        radius = 4
        if node.get("abstained"):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
        else:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    return out


def draw_hypotheses(base: Image.Image, bands: dict, seeds: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = rgba_draw(out)
    for seed in seeds.get("seeds", []):
        if seed.get("status") != "candidate":
            continue
        polygon = [tuple(map(float, point)) for point in seed.get("polygon_px", [])]
        if len(polygon) >= 3:
            draw.polygon(polygon, fill=(34, 197, 94, 28), outline=(22, 163, 74, 210), width=2)
    for band in bands.get("candidates", []):
        polygon = [tuple(map(float, point)) for point in band.get("polygon_px", [])]
        if len(polygon) < 3:
            continue
        color = (245, 158, 11, 235) if band.get("abstained") else (220, 38, 38, 235)
        draw.line(polygon + [polygon[0]], fill=color, width=3)
    return out


def is_border_clipped(alignment: dict) -> bool:
    spatial = alignment.get("spatial_audit", {})
    return bool(
        spatial.get("ppocrv5_border_clipped_computed")
        or spatial.get("doctr_border_clipped_computed")
    )


def draw_ocr_ids(base: Image.Image, ensemble: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")
    colors = {
        "consensus": (22, 163, 74, 255),
        "fuzzy_or_ambiguous_abstained": (245, 158, 11, 255),
        "conflict": (220, 38, 38, 255),
    }
    label_font = r1.font(10, True)
    occupied: list[tuple[float, float, float, float]] = []
    for alignment in ensemble.get("alignments", []):
        bbox = alignment.get("spatial_audit", {}).get("alignment_bbox_xyxy")
        if not bbox:
            continue
        x1, y1, x2, y2 = map(float, bbox)
        classification = alignment.get("decision", {}).get("classification", "other")
        color = colors.get(classification, (107, 114, 128, 255))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        label = alignment["id"] + (" !B" if is_border_clipped(alignment) else "")
        text_box = draw.textbbox((0, 0), label, font=label_font)
        label_w = text_box[2] - text_box[0]
        label_h = text_box[3] - text_box[1]
        tx = min(max(x1, 2), out.width - label_w - 4)
        candidates = [y1 - label_h - 5, y2 + 3, y1 + 2]
        ty = max(2, min(candidates[-1], out.height - label_h - 3))
        for candidate_y in candidates:
            candidate_y = max(2, min(candidate_y, out.height - label_h - 3))
            candidate_box = (tx - 2, candidate_y - 2, tx + label_w + 2, candidate_y + label_h + 2)
            if not any(
                candidate_box[0] < box[2]
                and candidate_box[2] > box[0]
                and candidate_box[1] < box[3]
                and candidate_box[3] > box[1]
                for box in occupied
            ):
                ty = candidate_y
                occupied.append(candidate_box)
                break
        draw.rectangle((tx - 2, ty - 2, tx + label_w + 2, ty + label_h + 2), fill=(255, 255, 255, 225))
        draw.text((tx, ty), label, fill=color, font=label_font)
    return out


def short_text(value: str, limit: int = 29) -> str:
    value = value.replace("\n", " ").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def draw_footer(
    canvas: Image.Image,
    y: int,
    ensemble: dict,
    linework: dict,
    bands: dict,
    seeds: dict,
    graph: dict,
) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, y, canvas.width - 1, canvas.height - 1), fill="#ffffff", outline="#9ca3af", width=2)
    x = 22
    draw.text((x, y + 14), "PROVENIENZA E LIMITI", fill="#111827", font=r1.font(21, True))
    draw.text(
        (x, y + 48),
        "page_0001 -> sheet_mapper r001 -> FR-001 -> region_split r002 / region_001 -> detector r001 -> reading_map r002",
        fill="#374151",
        font=r1.font(14),
    )
    draw.text(
        (x, y + 75),
        "Algoritmi: Hough H/V; grafo geometrico non semantico; coppie di bordi paralleli; flood-fill dello spazio bianco; ensemble PP-OCRv5 + docTR.",
        fill="#374151",
        font=r1.font(14),
    )
    ls = linework["summary"]
    gs = graph["summary"]
    bs = bands["summary"]
    ss = seeds["summary"]
    os = ensemble["summary"]
    draw.text(
        (x, y + 102),
        f"Linee {ls['candidate_count']} = {ls['solid_count']} supportate + {ls['uncertain_count']} incerte.  "
        f"Nodi {gs['node_count']} = {gs['abstained_node_count']} in astensione.  "
        f"Intersezioni esatte {gs['exact_intersection_count']}; prossimità {gs['near_junction_count']}; overlap {gs['collinear_overlap_count']}.",
        fill="#111827",
        font=r1.font(14, True),
    )
    draw.text(
        (x, y + 129),
        f"Coppie parallele {gs['parallel_pair_count']} (non disegnate).  Bande {bs['candidate_count']} = {bs['solid_count']} supportate + {bs['uncertain_count']} incerte.  "
        f"Spazi bianchi {ss['reported_component_count']}: {ss['candidate']} candidati, {ss['small_excluded']} piccoli esclusi, {ss['external_background']} background.",
        fill="#111827",
        font=r1.font(14, True),
    )
    draw.text(
        (x, y + 156),
        f"OCR {os['alignment_count']}: {os['consensus_alignment_count']} consensi, 5 ambigui/astenuti, 1 conflitto; {os['unassigned_geometry_candidate_count']} candidati geometrici non assegnati.",
        fill="#111827",
        font=r1.font(14, True),
    )
    draw.text(
        (x, y + 187),
        "NON DICHIARATO: linee!=muri; nodi senza semantica edilizia; bande!=muri; spazi!=stanze; consenso OCR!=verità.",
        fill="#991b1b",
        font=r1.font(14, True),
    )
    draw.text(
        (x, y + 212),
        "Nessuna inferenza su porte, finestre, proprietà/appartenenza, scala o nord. Nessuna approvazione umana. REGION_001 non è l'intero piano.",
        fill="#991b1b",
        font=r1.font(14, True),
    )

    draw.text((x, y + 246), "LETTURE OCR  C=consenso  A=ambiguo/astensione  X=conflitto  B=tagliato dal bordo", fill="#111827", font=r1.font(15, True))
    class_code = {"consensus": "C", "fuzzy_or_ambiguous_abstained": "A", "conflict": "X"}
    columns = 3
    column_width = (canvas.width - 44) // columns
    for index, alignment in enumerate(ensemble.get("alignments", [])):
        column = index // 5
        row = index % 5
        decision_class = alignment.get("decision", {}).get("classification", "?")
        code = class_code.get(decision_class, "?") + ("B" if is_border_clipped(alignment) else "")
        label = f"{alignment['id']} [{code}] {short_text(r1.text_label(alignment))}"
        tx = x + column * column_width
        ty = y + 278 + row * 24
        fill = "#991b1b" if "X" in code else "#92400e" if "A" in code or "B" in code else "#166534"
        draw.text((tx, ty), label, fill=fill, font=r1.font(13))


def main() -> int:
    required = [
        FLOOR_IMAGE,
        FLOOR_UNITS,
        REGIONS,
        r1.SOURCE,
        r1.LINEWORK,
        r1.WALL_BANDS,
        r1.ROOM_SEEDS,
        r1.OCR_ENSEMBLE,
        r1.GEOMETRY_GRAPH,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing inputs: {missing}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    floor_units = r1.load_json(FLOOR_UNITS)
    floor_record = next(item for item in floor_units["floor_units"] if item["id"] == "FR-001")
    regions = r1.load_json(REGIONS)
    region_record = next(item for item in regions["regions"] if item["id"] == "region_001")
    floor = Image.open(FLOOR_IMAGE).convert("RGB")
    source = Image.open(r1.SOURCE).convert("RGB")
    if floor.size != (floor_record["width_px"], floor_record["height_px"]):
        raise ValueError("Floor image dimensions do not match floor_units.json")
    if source.size != (region_record["bbox_px"][2], region_record["bbox_px"][3]):
        raise ValueError("Region image dimensions do not match regions.json")

    linework = r1.load_json(r1.LINEWORK)
    bands = r1.load_json(r1.WALL_BANDS)
    seeds = r1.load_json(r1.ROOM_SEEDS)
    ensemble = r1.load_json(r1.OCR_ENSEMBLE)
    graph = r1.load_json(r1.GEOMETRY_GRAPH)

    floor_scope, local_region_bbox = draw_floor_scope(
        floor,
        floor_record["bbox_page_px"],
        region_record["bbox_px"],
    )
    top_panel = r1.panel(
        floor_scope,
        "1. UNITÀ-PIANO COMPLETA E AMBITO ANALIZZATO",
        "FR-001 conserva tutta la fascia; il rettangolo rosso è region_001, candidato geometrico analizzato sotto",
    )
    bottom_panels = [
        r1.panel(
            draw_geometry(source, linework, graph),
            "2. OSSERVAZIONI GEOMETRICHE",
            "blu=linea supportata; arancio=linea incerta; verde=nodo supportato; magenta=nodo astenuto",
        ),
        r1.panel(
            draw_hypotheses(source, bands, seeds),
            "3. IPOTESI NON SEMANTICHE",
            "rosso=band supportata; arancio=band incerta; verde=spazio bianco candidato; ID completi nel JSON",
        ),
        r1.panel(
            draw_ocr_ids(source, ensemble),
            "4. LETTURA TESTO",
            "verde=consenso; arancio=ambiguo; rosso=conflitto; !B=taglio al bordo; testo nella tabella",
        ),
    ]

    canvas_width = floor.width
    header_height = 146
    gap = 20
    footer_height = 420
    bottom_height = bottom_panels[0].height
    canvas_height = header_height + top_panel.height + gap + bottom_height + footer_height
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#f3f4f6")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), "PLANPARSER - MAPPA DI LETTURA r002", fill="#111827", font=r1.font(31, True))
    draw.text(
        (20, 56),
        "Prima il piano completo; poi l'ambito effettivamente analizzato e le evidenze prodotte dai singoli algoritmi.",
        fill="#374151",
        font=r1.font(17),
    )
    draw.text(
        (20, 88),
        "Evidenza automatica tracciabile: le ipotesi restano ipotesi e il contenuto non classificato non viene perso.",
        fill="#991b1b",
        font=r1.font(17, True),
    )
    draw.text(
        (20, 118),
        "Coordinate pagina preservate; nessuna revisione umana applicata.",
        fill="#4b5563",
        font=r1.font(15),
    )
    top_y = header_height
    canvas.paste(top_panel, (0, top_y))
    bottom_y = top_y + top_panel.height + gap
    total_bottom_width = sum(item.width for item in bottom_panels) + gap * (len(bottom_panels) - 1)
    x = (canvas.width - total_bottom_width) // 2
    for item in bottom_panels:
        canvas.paste(item, (x, bottom_y))
        x += item.width + gap
    footer_y = bottom_y + bottom_height
    draw_footer(canvas, footer_y, ensemble, linework, bands, seeds, graph)

    payload = r1.reading_payload(source, linework, bands, seeds, ensemble, graph)
    payload.update(
        {
            "schema_version": "planparser.reading-map/1.1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "automatic_observations_and_hypotheses_not_human_approved",
            "source_floor_unit": {
                "id": "FR-001",
                "path": FLOOR_IMAGE.relative_to(ROOT).as_posix(),
                "sha256": r1.sha256(FLOOR_IMAGE),
                "bbox_page_px": floor_record["bbox_page_px"],
                "title_text_raw": floor_record["title_text_raw"],
            },
            "analysis_scope": {
                "id": "region_001",
                "path": r1.SOURCE.relative_to(ROOT).as_posix(),
                "bbox_page_px_xywh": region_record["bbox_px"],
                "bbox_floor_unit_px_xywh": local_region_bbox,
                "confidence_from_region_split": region_record["confidence"],
                "complete_floor_claimed": False,
            },
            "visualization": {
                "parallel_relations_drawn": False,
                "band_ids_drawn": False,
                "all_ids_and_raw_records_preserved_in_json": True,
                "ocr_border_clipping_marked": True,
            },
            "algorithms": [
                "axis-aligned Hough segment observation",
                "non-semantic geometry relation graph",
                "parallel-edge band proposal",
                "morphological white-space component proposal",
                "PP-OCRv5 and docTR reading ensemble",
            ],
            "explicit_non_claims": [
                "region_001 is not claimed to be the complete floor",
                "observed linework is not exhaustive and is not a wall declaration",
                "supported or solid is detector state, not physical-building truth",
                "geometry nodes are not assigned building semantics",
                "parallel-edge bands are not confirmed walls",
                "white-space components are not confirmed rooms",
                "OCR consensus is engine agreement, not ground truth",
                "doors, windows, property membership, scale and north are not inferred",
                "no human approval or correction has been applied",
            ],
        }
    )
    payload["inputs"].extend(
        [
            {"role": "floor_unit", "path": FLOOR_IMAGE.relative_to(ROOT).as_posix(), "sha256": r1.sha256(FLOOR_IMAGE)},
            {"role": "floor_units_contract", "path": FLOOR_UNITS.relative_to(ROOT).as_posix(), "sha256": r1.sha256(FLOOR_UNITS)},
            {"role": "region_split_contract", "path": REGIONS.relative_to(ROOT).as_posix(), "sha256": r1.sha256(REGIONS)},
        ]
    )

    parent = OUTPUT.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".revision_002.building-{uuid.uuid4().hex}"
    temporary.mkdir(exist_ok=False)
    json_path = temporary / "reading_map.json"
    png_path = temporary / "reading_map.png"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    canvas.save(png_path)
    manifest = {
        "schema_version": "planparser.artifact-manifest/1.0",
        "artifacts": [
            {"path": json_path.name, "sha256": r1.sha256(json_path), "media_type": "application/json"},
            {"path": png_path.name, "sha256": r1.sha256(png_path), "media_type": "image/png"},
        ],
    }
    manifest_path = temporary / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for artifact in manifest["artifacts"]:
        if r1.sha256(temporary / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Hash verification failed: {artifact['path']}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")
    temporary.rename(OUTPUT)
    print(OUTPUT / "reading_map.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
