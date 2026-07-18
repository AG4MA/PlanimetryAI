from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
ATOMIC = ROOT / "atomic_v2"
INDUSTRIAL = ROOT / "industrial_v1"

SOURCE = (
    ATOMIC
    / "region_split/artifacts/scheda_catastale/page_0001/revision_002/region_001.png"
)
LINEWORK = (
    ATOMIC
    / "linework/artifacts/scheda_catastale/region_001/revision_001/linework.json"
)
WALL_BANDS = (
    ATOMIC
    / "wall_bands/artifacts/scheda_catastale/region_001/revision_001/wall_bands.json"
)
ROOM_SEEDS = (
    ATOMIC
    / "room_seeds/artifacts/scheda_catastale/region_001/revision_001/room_seeds.json"
)
OCR_ENSEMBLE = (
    ATOMIC
    / "ocr_ensemble/artifacts/scheda_catastale/region_001/revision_001/ocr_ensemble.json"
)
GEOMETRY_GRAPH = (
    INDUSTRIAL
    / "geometry_graph/artifacts/scheda_catastale/region_001/revision_001/geometry_graph.json"
)
OUTPUT = (
    INDUSTRIAL
    / "reading_map/artifacts/scheda_catastale/region_001/revision_001"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def panel(image: Image.Image, title: str, subtitle: str) -> Image.Image:
    width, height = image.size
    header = 72
    result = Image.new("RGB", (width, height + header), "white")
    result.paste(image.convert("RGB"), (0, header))
    draw = ImageDraw.Draw(result)
    draw.rectangle((0, 0, width - 1, height + header - 1), outline="#9ca3af", width=2)
    draw.text((12, 8), title, fill="#111827", font=font(21, True))
    draw.text((12, 39), subtitle, fill="#4b5563", font=font(14))
    return result


def draw_linework(base: Image.Image, linework: dict, graph: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for item in linework.get("candidates", []):
        points = [tuple(map(float, point)) for point in item["points_px"]]
        color = "#2563eb" if not item.get("abstained") else "#f59e0b"
        draw.line(points, fill=color, width=2 if not item.get("abstained") else 1)

    for index, node in enumerate(graph.get("nodes", []), start=1):
        x, y = map(float, node["coordinate_crop_px"])
        radius = 4
        if node.get("abstained"):
            color = "#d946ef"
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
        else:
            color = "#16a34a"
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        if index % 5 == 0 or node.get("abstained"):
            draw.text((x + 5, y - 7), node["node_id"].replace("node_", "n"), fill=color, font=font(9))
    return out


def draw_hypotheses(base: Image.Image, bands: dict, seeds: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")
    for seed in seeds.get("seeds", []):
        if seed.get("status") != "candidate":
            continue
        polygon = [tuple(map(float, point)) for point in seed.get("polygon_px", [])]
        if len(polygon) >= 3:
            draw.polygon(polygon, fill=(34, 197, 94, 28), outline=(22, 163, 74, 190), width=2)
        x, y, _, _ = seed["bbox_px"]
        draw.text((x + 3, y + 3), seed["id"], fill=(22, 101, 52, 255), font=font(10))

    for band in bands.get("candidates", []):
        polygon = [tuple(map(float, point)) for point in band["polygon_px"]]
        color = (220, 38, 38, 230) if not band.get("abstained") else (245, 158, 11, 220)
        if len(polygon) >= 3:
            draw.line(polygon + [polygon[0]], fill=color, width=3)
        x, y, _, _ = band["bbox_px"]
        draw.text((x + 2, max(2, y - 12)), band["id"], fill=color, font=font(9))
    return out


def text_label(alignment: dict) -> str:
    decision = alignment.get("decision", {})
    consensus = decision.get("consensus") or {}
    if consensus.get("text_normalized"):
        return str(consensus["text_normalized"])
    raw = alignment.get("raw_text_alternatives", {})
    left = (raw.get("ppocrv5") or {}).get("joined_text_raw", "")
    right = (raw.get("doctr") or {}).get("joined_text_raw", "")
    if left == right:
        return left
    return f"{left}|{right}".strip("|")


def draw_ocr(base: Image.Image, ensemble: dict) -> Image.Image:
    out = base.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    colors = {
        "consensus": "#16a34a",
        "fuzzy": "#f59e0b",
        "ambiguous": "#f59e0b",
        "fuzzy_or_ambiguous_abstained": "#f59e0b",
        "conflict": "#dc2626",
        "single_engine": "#6b7280",
    }
    for alignment in ensemble.get("alignments", []):
        bbox = alignment.get("spatial_audit", {}).get("alignment_bbox_xyxy")
        if not bbox:
            continue
        classification = alignment.get("decision", {}).get("classification", "single_engine")
        color = colors.get(classification, "#6b7280")
        draw.rectangle(tuple(map(float, bbox)), outline=color, width=3)
        x1, y1, _, _ = map(float, bbox)
        label = f"{alignment['id']} {text_label(alignment)}"
        draw.text((x1, max(1, y1 - 14)), label, fill=color, font=font(10, True))
    return out


def reading_payload(source: Image.Image, linework: dict, bands: dict, seeds: dict, ensemble: dict, graph: dict) -> dict:
    inputs = []
    for role, path in [
        ("source_crop", SOURCE),
        ("linework", LINEWORK),
        ("wall_band_hypotheses", WALL_BANDS),
        ("space_seed_hypotheses", ROOM_SEEDS),
        ("ocr_ensemble", OCR_ENSEMBLE),
        ("geometry_graph", GEOMETRY_GRAPH),
    ]:
        inputs.append({"role": role, "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)})

    return {
        "schema_version": "planparser.reading-map/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "observational_candidate_not_human_approved",
        "source": {"width_px": source.width, "height_px": source.height, "coordinate_system": "region_001_crop_px"},
        "inputs": inputs,
        "layers": {
            "raw_linework": {
                "count": len(linework.get("candidates", [])),
                "source_ids": [item["id"] for item in linework.get("candidates", [])],
            },
            "geometry_relations": {
                "node_count": len(graph.get("nodes", [])),
                "abstained_count": sum(bool(item.get("abstained")) for item in graph.get("nodes", [])),
                "nodes": [
                    {
                        "id": item["node_id"],
                        "coordinate_crop_px": item["coordinate_crop_px"],
                        "coordinate_source_page_px": item.get("coordinate_source_page_px"),
                        "geometric_class": item["geometric_class"],
                        "segment_ids": item["segment_ids"],
                        "confidence": item["confidence"],
                        "abstained": item["abstained"],
                    }
                    for item in graph.get("nodes", [])
                ],
            },
            "wall_band_hypotheses": {
                "count": len(bands.get("candidates", [])),
                "solid_count": sum(not item.get("abstained") for item in bands.get("candidates", [])),
                "items": bands.get("candidates", []),
            },
            "space_seed_hypotheses": {
                "count": len(seeds.get("seeds", [])),
                "candidate_count": sum(item.get("status") == "candidate" for item in seeds.get("seeds", [])),
                "items": seeds.get("seeds", []),
            },
            "text_readings": {
                "alignment_count": len(ensemble.get("alignments", [])),
                "consensus_count": sum(item.get("decision", {}).get("classification") == "consensus" for item in ensemble.get("alignments", [])),
                "items": ensemble.get("alignments", []),
            },
        },
        "explicit_non_claims": [
            "wall bands are not confirmed walls",
            "space seeds are not confirmed rooms",
            "geometry nodes are not assigned building semantics",
            "OCR alternatives are retained when engines disagree",
            "no human approval or correction has been applied",
        ],
    }


def main() -> int:
    required = [SOURCE, LINEWORK, WALL_BANDS, ROOM_SEEDS, OCR_ENSEMBLE, GEOMETRY_GRAPH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing inputs: {missing}")
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    source = Image.open(SOURCE).convert("RGB")
    linework = load_json(LINEWORK)
    bands = load_json(WALL_BANDS)
    seeds = load_json(ROOM_SEEDS)
    ensemble = load_json(OCR_ENSEMBLE)
    graph = load_json(GEOMETRY_GRAPH)

    panels = [
        panel(source, "1. SORGENTE", "crop completo del piano; nessuna annotazione"),
        panel(draw_linework(source, linework, graph), "2. OSSERVAZIONI E RELAZIONI", "linee raw + nodi geometrici; magenta = astensione"),
        panel(draw_hypotheses(source, bands, seeds), "3. IPOTESI GEOMETRICHE", "rosso/arancio = band; verde = spazio chiuso candidato"),
        panel(draw_ocr(source, ensemble), "4. LETTURA TESTO", "verde = consenso; arancio = ambiguo; rosso = conflitto"),
    ]

    gap = 18
    top = 104
    cell_w = source.width
    cell_h = source.height + 72
    canvas = Image.new("RGB", (cell_w * 2 + gap, top + cell_h * 2 + gap), "#f3f4f6")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), "PLANPARSER — MAPPA DI LETTURA r001", fill="#111827", font=font(28, True))
    counts = (
        f"linee={len(linework.get('candidates', []))}  nodi={len(graph.get('nodes', []))}  "
        f"band={len(bands.get('candidates', []))}  spazi={sum(s.get('status') == 'candidate' for s in seeds.get('seeds', []))}  "
        f"testi={len(ensemble.get('alignments', []))}"
    )
    draw.text((18, 50), counts, fill="#374151", font=font(16))
    draw.text((18, 76), "Evidenza algoritmica; nessuna approvazione umana e nessuna semantica edilizia definitiva.", fill="#991b1b", font=font(14, True))
    positions = [(0, top), (cell_w + gap, top), (0, top + cell_h + gap), (cell_w + gap, top + cell_h + gap)]
    for item, position in zip(panels, positions):
        canvas.paste(item, position)

    payload = reading_payload(source, linework, bands, seeds, ensemble, graph)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    json_path = OUTPUT / "reading_map.json"
    png_path = OUTPUT / "reading_map.png"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    canvas.save(png_path)
    manifest = {
        "schema_version": "planparser.artifact-manifest/1.0",
        "artifacts": [
            {"path": json_path.name, "sha256": sha256(json_path), "media_type": "application/json"},
            {"path": png_path.name, "sha256": sha256(png_path), "media_type": "image/png"},
        ],
    }
    (OUTPUT / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(png_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
