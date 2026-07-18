from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


PROJECT_ROOT = Path(r"C:\projects\PlanimetryAI")
ATOMIC_ROOT = PROJECT_ROOT / "PlanParser" / "atomic_v2"
INPUT_JSON = (
    ATOMIC_ROOT
    / "ocr_text_candidates"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
    / "text_candidates.json"
)
OUTPUT_DIR = (
    ATOMIC_ROOT
    / "ocr_tiles"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def relative_to_atomic(path: Path) -> str:
    return path.relative_to(ATOMIC_ROOT).as_posix()


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def centered_interval(
    start: int, end: int, minimum_size: int, limit: int
) -> tuple[int, int]:
    if end - start >= minimum_size or limit <= minimum_size:
        return clamp(start, 0, limit), clamp(end, 0, limit)

    center = (start + end) / 2.0
    new_start = int(math.floor(center - minimum_size / 2.0))
    new_end = new_start + minimum_size
    if new_start < 0:
        new_start = 0
        new_end = minimum_size
    if new_end > limit:
        new_end = limit
        new_start = limit - minimum_size
    return new_start, new_end


def crop_window(
    bbox: dict[str, float], image_width: int, image_height: int
) -> tuple[dict[str, int], dict[str, int | bool]]:
    x = float(bbox["x"])
    y = float(bbox["y"])
    width = float(bbox["width"])
    height = float(bbox["height"])

    base_left = int(math.floor(x))
    base_top = int(math.floor(y))
    base_right = int(math.ceil(x + width))
    base_bottom = int(math.ceil(y + height))

    # Preserve every candidate while giving recognizers enough adjacent glyph and
    # baseline context.  The minimum window is intentionally small enough not to
    # swallow an entire room when the candidate is a false positive.
    margin_x = max(8, int(math.ceil(height * 1.25)), int(math.ceil(width * 0.08)))
    margin_y = max(6, int(math.ceil(height * 0.85)))

    wanted_left = base_left - margin_x
    wanted_top = base_top - margin_y
    wanted_right = base_right + margin_x
    wanted_bottom = base_bottom + margin_y

    left = clamp(wanted_left, 0, image_width)
    top = clamp(wanted_top, 0, image_height)
    right = clamp(wanted_right, 0, image_width)
    bottom = clamp(wanted_bottom, 0, image_height)
    left, right = centered_interval(left, right, 48, image_width)
    top, bottom = centered_interval(top, bottom, 32, image_height)

    if right <= left or bottom <= top:
        raise ValueError(f"Empty crop for bbox {bbox}")

    window = {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
    }
    diagnostics: dict[str, int | bool] = {
        "requested_margin_x_px": margin_x,
        "requested_margin_y_px": margin_y,
        "context_clipped_left": wanted_left < 0,
        "context_clipped_top": wanted_top < 0,
        "context_clipped_right": wanted_right > image_width,
        "context_clipped_bottom": wanted_bottom > image_height,
    }
    return window, diagnostics


def bbox_relative_to_window(
    bbox: dict[str, float], window: dict[str, int], scale: int = 1
) -> dict[str, float]:
    return {
        "x": round((float(bbox["x"]) - window["x"]) * scale, 6),
        "y": round((float(bbox["y"]) - window["y"]) * scale, 6),
        "width": round(float(bbox["width"]) * scale, 6),
        "height": round(float(bbox["height"]) * scale, 6),
    }


def fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((width, height), Image.Resampling.LANCZOS)
    return copy


def make_contact_sheet(
    records: list[dict[str, object]], staging: Path, destination: Path
) -> None:
    columns = 4
    cell_width = 420
    cell_height = 170
    header_height = 44
    rows = math.ceil(len(records) / columns)
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    small_font = ImageFont.load_default(size=14)

    for index, record in enumerate(records):
        row = index // columns
        column = index % columns
        x0 = column * cell_width
        y0 = row * cell_height
        state = "ABSTAINED" if record["abstained"] else "candidate"
        border = "#b91c1c" if record["abstained"] else "#1d4ed8"
        draw.rectangle(
            (x0 + 2, y0 + 2, x0 + cell_width - 3, y0 + cell_height - 3),
            outline=border,
            width=3,
        )
        draw.text(
            (x0 + 10, y0 + 7),
            f"{index + 1:02d}  {record['candidate_id']}  {state}",
            fill=border,
            font=font,
        )
        bbox = record["candidate_bbox_original_px"]
        draw.text(
            (x0 + 10, y0 + 26),
            f"original x={bbox['x']:.1f} y={bbox['y']:.1f} w={bbox['width']:.1f} h={bbox['height']:.1f}",
            fill="#333333",
            font=small_font,
        )

        tile_path = staging / str(record["ocr_ready_tile"]["path_in_revision"])
        with Image.open(tile_path) as tile:
            fitted = fit_image(tile.convert("RGB"), cell_width - 20, cell_height - header_height - 16)
        paste_x = x0 + (cell_width - fitted.width) // 2
        paste_y = y0 + header_height + (cell_height - header_height - fitted.height) // 2
        canvas.paste(fitted, (paste_x, paste_y))

        candidate_tile_bbox = record["candidate_bbox_ocr_ready_px"]
        tile_w = int(record["ocr_ready_tile"]["width_px"])
        tile_h = int(record["ocr_ready_tile"]["height_px"])
        if tile_w > 0 and tile_h > 0:
            scale = min((cell_width - 20) / tile_w, (cell_height - header_height - 16) / tile_h)
            box_left = paste_x + candidate_tile_bbox["x"] * scale
            box_top = paste_y + candidate_tile_bbox["y"] * scale
            box_right = box_left + candidate_tile_bbox["width"] * scale
            box_bottom = box_top + candidate_tile_bbox["height"] * scale
            draw.rectangle((box_left, box_top, box_right, box_bottom), outline="#16a34a", width=2)

    canvas.save(destination, format="PNG", optimize=True)


def main() -> None:
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"Immutable output already exists: {OUTPUT_DIR}")
    if not INPUT_JSON.is_file():
        raise FileNotFoundError(INPUT_JSON)

    source_payload = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    candidates = source_payload.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates in input JSON")

    source_rel = source_payload["source"]["path"]
    source_path = ATOMIC_ROOT / Path(source_rel)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_hash = sha256_file(source_path)
    if source_hash != source_payload["source"]["sha256"]:
        raise ValueError("Source image hash differs from text-candidate manifest")

    output_parent = OUTPUT_DIR.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="ocr_tiles_revision_001_", dir=r"C:\tmp"))
    staging = temp_root / "revision_001"
    original_tiles_dir = staging / "tiles_original"
    ocr_ready_tiles_dir = staging / "tiles_ocr_ready"
    original_tiles_dir.mkdir(parents=True)
    ocr_ready_tiles_dir.mkdir(parents=True)

    records: list[dict[str, object]] = []
    with Image.open(source_path) as source_image:
        source_image.load()
        image_width, image_height = source_image.size
        if image_width != int(source_payload["source"]["width_px"]):
            raise ValueError("Source width differs from text-candidate manifest")
        if image_height != int(source_payload["source"]["height_px"]):
            raise ValueError("Source height differs from text-candidate manifest")

        for sheet_index, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate["id"])
            if not candidate_id.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"Unsafe candidate id: {candidate_id}")
            bbox = candidate["bbox_original_px"]
            window, crop_diagnostics = crop_window(bbox, image_width, image_height)
            crop_box = (
                window["x"],
                window["y"],
                window["x"] + window["width"],
                window["y"] + window["height"],
            )
            original_tile = source_image.crop(crop_box)
            original_name = f"{candidate_id}_context.png"
            original_path = original_tiles_dir / original_name
            original_tile.save(original_path, format="PNG", optimize=True)

            scale = 4
            grayscale = ImageOps.grayscale(original_tile)
            grayscale = ImageOps.autocontrast(grayscale, cutoff=(1, 1))
            grayscale = ImageEnhance.Contrast(grayscale).enhance(1.15)
            ocr_ready = grayscale.resize(
                (original_tile.width * scale, original_tile.height * scale),
                Image.Resampling.LANCZOS,
            )
            ocr_ready_name = f"{candidate_id}_context_4x.png"
            ocr_ready_path = ocr_ready_tiles_dir / ocr_ready_name
            ocr_ready.save(ocr_ready_path, format="PNG", optimize=True)

            relative_bbox = bbox_relative_to_window(bbox, window, scale=1)
            ready_bbox = bbox_relative_to_window(bbox, window, scale=scale)
            record: dict[str, object] = {
                "sheet_index": sheet_index,
                "candidate_id": candidate_id,
                "abstained": bool(candidate.get("abstained", False)),
                "input_border_clipped": bool(candidate.get("border_clipped", False)),
                "input_confidence_geometry": candidate.get("confidence_geometry"),
                "input_candidate_record_sha256": sha256_json(candidate),
                "candidate_bbox_original_px": bbox,
                "crop_window_original_px": window,
                "candidate_bbox_tile_px": relative_bbox,
                "candidate_bbox_ocr_ready_px": ready_bbox,
                "crop_diagnostics": crop_diagnostics,
                "original_tile": {
                    "path": (
                        "ocr_tiles/artifacts/scheda_catastale/region_001/revision_001/"
                        f"tiles_original/{original_name}"
                    ),
                    "path_in_revision": f"tiles_original/{original_name}",
                    "sha256": sha256_file(original_path),
                    "width_px": original_tile.width,
                    "height_px": original_tile.height,
                    "mode": original_tile.mode,
                    "tile_to_original_homogeneous_3x3": [
                        [1.0, 0.0, float(window["x"])],
                        [0.0, 1.0, float(window["y"])],
                        [0.0, 0.0, 1.0],
                    ],
                },
                "ocr_ready_tile": {
                    "path": (
                        "ocr_tiles/artifacts/scheda_catastale/region_001/revision_001/"
                        f"tiles_ocr_ready/{ocr_ready_name}"
                    ),
                    "path_in_revision": f"tiles_ocr_ready/{ocr_ready_name}",
                    "sha256": sha256_file(ocr_ready_path),
                    "width_px": ocr_ready.width,
                    "height_px": ocr_ready.height,
                    "mode": ocr_ready.mode,
                    "normalization": {
                        "grayscale": True,
                        "autocontrast_cutoff_percent": [1, 1],
                        "contrast_factor": 1.15,
                        "upscale_factor": scale,
                        "resampling": "lanczos",
                    },
                    "tile_to_original_homogeneous_3x3": [
                        [1.0 / scale, 0.0, float(window["x"])],
                        [0.0, 1.0 / scale, float(window["y"])],
                        [0.0, 0.0, 1.0],
                    ],
                },
            }
            records.append(record)

    contact_sheet_path = staging / "ocr_tiles_contact_sheet.png"
    make_contact_sheet(records, staging, contact_sheet_path)

    manifest = {
        "schema_version": "planparser.ocr_tiles.v1",
        "component": "ocr_tiles",
        "revision": "revision_001",
        "source": {
            "text_candidates_path": relative_to_atomic(INPUT_JSON),
            "text_candidates_sha256": sha256_file(INPUT_JSON),
            "text_candidates_schema_version": source_payload.get("schema_version"),
            "image_path": source_rel,
            "image_sha256": source_hash,
            "image_width_px": source_payload["source"]["width_px"],
            "image_height_px": source_payload["source"]["height_px"],
        },
        "policy": {
            "candidate_retention": "all_input_candidates_preserved",
            "recognition_performed": False,
            "semantic_assignment_performed": False,
            "abstention_policy": "input_abstained_state_preserved_verbatim",
            "crop_coordinates": "integer_left_top_inclusive_right_bottom_exclusive",
            "minimum_context_window_px": {"width": 48, "height": 32},
            "requested_context_margin": {
                "horizontal": "max(8px, ceil(1.25*candidate_height), ceil(0.08*candidate_width))",
                "vertical": "max(6px, ceil(0.85*candidate_height))",
            },
            "ocr_ready_upscale_factor": 4,
        },
        "summary": {
            "input_candidate_count": len(candidates),
            "output_tile_count": len(records),
            "abstained_count": sum(1 for item in records if item["abstained"]),
            "non_abstained_count": sum(1 for item in records if not item["abstained"]),
            "context_clipped_count": sum(
                1
                for item in records
                if any(
                    value
                    for key, value in item["crop_diagnostics"].items()
                    if key.startswith("context_clipped_")
                )
            ),
        },
        "contact_sheet": {
            "path": "ocr_tiles/artifacts/scheda_catastale/region_001/revision_001/ocr_tiles_contact_sheet.png",
            "sha256": sha256_file(contact_sheet_path),
            "numbering": "one_based_sheet_index_mapped_to_candidate_id_in_records",
            "green_box": "candidate_bbox_inside_context_tile",
            "red_header": "input_candidate_was_abstained",
            "blue_header": "input_candidate_was_not_abstained",
        },
        "records": records,
        "notes": [
            "Tiles are geometric OCR inputs only; no transcription or meaning was assigned.",
            "Potential false positives are intentionally retained.",
            "Original and OCR-ready tile transforms map coordinates back to the source crop.",
        ],
    }
    manifest_path = staging / "ocr_tiles_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if OUTPUT_DIR.exists():
        raise FileExistsError(f"Immutable output appeared during build: {OUTPUT_DIR}")
    os.replace(staging, OUTPUT_DIR)

    print(
        json.dumps(
            {
                "output": str(OUTPUT_DIR),
                "candidate_count": len(records),
                "abstained_count": manifest["summary"]["abstained_count"],
                "contact_sheet_sha256": manifest["contact_sheet"]["sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
