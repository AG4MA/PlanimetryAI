from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "atomic_v2/ingest/artifacts/scheda_catastale/pages/page_0001.png"
SHEET_MAP = (
    ROOT
    / "industrial_v1/sheet_mapper/artifacts/scheda_catastale/page_0001/revision_001/sheet_map.json"
)
OUTPUT = (
    ROOT
    / "industrial_v1/floor_units/artifacts/scheda_catastale/page_0001/revision_001"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def bbox_tuple(value: dict) -> tuple[int, int, int, int]:
    x = int(value["x"])
    y = int(value["y"])
    width = int(value["width"])
    height = int(value["height"])
    return x, y, x + width, y + height


def fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    scale = min(max_width / image.width, max_height / image.height, 1.0)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def build_contact_sheet(items: list[dict]) -> Image.Image:
    tile_width = 1040
    tile_height = 900
    gap = 24
    header = 156
    footer = 92
    canvas = Image.new(
        "RGB",
        (tile_width * len(items) + gap * (len(items) - 1), header + tile_height + footer),
        "#f3f4f6",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), "PLANPARSER - UNITÀ PIANO r001", fill="#111827", font=font(31, True))
    draw.text(
        (20, 56),
        "Divisione automatica del foglio lungo l'asse verticale; ogni crop conserva l'intera larghezza della cornice.",
        fill="#374151",
        font=font(17),
    )
    draw.text(
        (20, 88),
        "Sono regioni-piano candidate: nessun muro, stanza, proprietà, scala o orientamento è dichiarato.",
        fill="#991b1b",
        font=font(17, True),
    )
    draw.text(
        (20, 120),
        "Provenienza: page_0001 -> sheet_mapper r001 -> floor_units r001",
        fill="#4b5563",
        font=font(15),
    )

    for index, item in enumerate(items):
        x0 = index * (tile_width + gap)
        draw.rectangle(
            (x0, header, x0 + tile_width - 1, header + tile_height - 1),
            fill="white",
            outline="#6b7280",
            width=2,
        )
        display = fit(item["image"], tile_width - 28, tile_height - 94)
        image_x = x0 + (tile_width - display.width) // 2
        image_y = header + 76
        canvas.paste(display, (image_x, image_y))
        label = item["title_text"] or "titolo non risolto"
        draw.text((x0 + 14, header + 10), f"{item['id']}  {label}", fill="#075985", font=font(22, True))
        bbox = item["bbox"]
        detail = (
            f"bbox pagina: x={bbox['x']} y={bbox['y']} w={bbox['width']} h={bbox['height']}  "
            f"conf={item['confidence']:.3f}"
        )
        draw.text((x0 + 14, header + 43), detail, fill="#374151", font=font(14))

    draw.text(
        (20, header + tile_height + 18),
        "Il contenuto estraneo o ancora non classificato resta nel crop: viene preservato, non eliminato.",
        fill="#111827",
        font=font(17, True),
    )
    draw.text(
        (20, header + tile_height + 50),
        "Nessuna revisione umana applicata; i file sorgente e gli artefatti precedenti restano immutati.",
        fill="#4b5563",
        font=font(15),
    )
    return canvas


def main() -> int:
    for required in (SOURCE, SHEET_MAP):
        if not required.is_file():
            raise FileNotFoundError(required)
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {OUTPUT}")

    sheet_map = json.loads(SHEET_MAP.read_text(encoding="utf-8"))
    if sha256(SOURCE) != sheet_map["source"]["sha256"]:
        raise ValueError("Source raster hash does not match the sheet-map input hash")

    source = Image.open(SOURCE).convert("RGB")
    titles = {
        item["id"]: item
        for item in sheet_map.get("observations", {}).get("floor_title_candidates", [])
    }
    regions = sheet_map.get("observations", {}).get("floor_regions", [])
    if not regions:
        raise ValueError("The sheet map contains no floor-region candidates")

    prepared: list[dict] = []
    for region in regions:
        x1, y1, x2, y2 = bbox_tuple(region["bbox_page_px"])
        if not (0 <= x1 < x2 <= source.width and 0 <= y1 < y2 <= source.height):
            raise ValueError(f"Out-of-bounds floor region: {region['id']}")
        title = titles.get(region.get("title_candidate_id"), {})
        prepared.append(
            {
                "id": region["id"],
                "title_id": region.get("title_candidate_id"),
                "title_text": title.get("text_raw"),
                "designation_raw": title.get("designation_raw"),
                "bbox": region["bbox_page_px"],
                "confidence": float(region["confidence"]),
                "abstained": bool(region["abstained"]),
                "structural_candidate_ids": region.get("structural_candidate_ids", []),
                "image": source.crop((x1, y1, x2, y2)),
            }
        )

    OUTPUT.mkdir(parents=True, exist_ok=False)
    floor_payloads: list[dict] = []
    artifacts: list[dict] = []
    for item in prepared:
        filename = f"{item['id'].lower().replace('-', '_')}.png"
        path = OUTPUT / filename
        item["image"].save(path)
        artifacts.append({"path": filename, "sha256": sha256(path), "media_type": "image/png"})
        floor_payloads.append(
            {
                "id": item["id"],
                "status": "automatic_floor_region_candidate",
                "title_candidate_id": item["title_id"],
                "title_text_raw": item["title_text"],
                "designation_raw": item["designation_raw"],
                "bbox_page_px": item["bbox"],
                "width_px": item["image"].width,
                "height_px": item["image"].height,
                "confidence_from_sheet_mapper": item["confidence"],
                "abstained_from_sheet_mapper": item["abstained"],
                "structural_candidate_ids": item["structural_candidate_ids"],
                "artifact": filename,
                "artifact_sha256": artifacts[-1]["sha256"],
                "scope_policy": "full_horizontal_slice_inside_primary_planimetric_frame",
                "unclassified_content_preserved": True,
            }
        )

    contact_path = OUTPUT / "floor_units_contact_sheet.png"
    build_contact_sheet(prepared).save(contact_path)
    artifacts.append(
        {"path": contact_path.name, "sha256": sha256(contact_path), "media_type": "image/png"}
    )

    payload = {
        "schema_version": "planparser.industrial_v1.floor_units.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "automatic_candidates_not_human_approved",
        "source": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": sha256(SOURCE),
            "width_px": source.width,
            "height_px": source.height,
        },
        "input_sheet_map": {
            "path": SHEET_MAP.relative_to(ROOT).as_posix(),
            "sha256": sha256(SHEET_MAP),
            "revision": "revision_001",
        },
        "method": {
            "name": "materialize_sheet_mapper_floor_regions",
            "new_detection_performed": False,
            "split_axis": sheet_map["observations"]["floor_layout"]["axis"],
            "crop_policy": "exact_half_open_floor_region_bbox_from_sheet_map",
            "preserve_full_frame_width": True,
        },
        "floor_units": floor_payloads,
        "summary": {
            "count": len(floor_payloads),
            "all_source_pixels_inside_each_region_preserved": True,
            "human_review_applied": False,
        },
        "explicit_non_claims": [
            "a floor-region candidate is not a validated floor",
            "content inside a floor crop is not automatically part of the target property",
            "no wall, room, door, window or building-element semantics are assigned",
            "no geometric scale calibration is performed",
            "north or compass orientation is not inferred",
            "no human approval or correction has been applied",
        ],
    }
    json_path = OUTPUT / "floor_units.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifacts.append(
        {"path": json_path.name, "sha256": sha256(json_path), "media_type": "application/json"}
    )
    manifest = {
        "schema_version": "planparser.artifact-manifest/1.0",
        "artifacts": artifacts,
    }
    manifest_path = OUTPUT / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(contact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
