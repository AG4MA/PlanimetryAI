from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(r"C:\projects\PlanimetryAI\PlanParser\atomic_v2")
REVISION = (
    ROOT
    / "ocr_tiles"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)
INPUT = (
    ROOT
    / "ocr_text_candidates"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
    / "text_candidates.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((REVISION / "ocr_tiles_manifest.json").read_text("utf-8"))
    source = json.loads(INPUT.read_text("utf-8"))
    input_by_id = {item["id"]: item for item in source["candidates"]}
    errors: list[str] = []

    output_ids = {record["candidate_id"] for record in manifest["records"]}
    if output_ids != set(input_by_id):
        errors.append("candidate_id_set_differs")

    for record in manifest["records"]:
        candidate_id = record["candidate_id"]
        if record["abstained"] != bool(input_by_id[candidate_id]["abstained"]):
            errors.append(f"{candidate_id}:abstained_state_differs")
        for key in ("original_tile", "ocr_ready_tile"):
            tile = record[key]
            tile_path = REVISION / tile["path_in_revision"]
            if not tile_path.is_file():
                errors.append(f"{candidate_id}:{key}:missing")
                continue
            if sha256(tile_path) != tile["sha256"]:
                errors.append(f"{candidate_id}:{key}:hash_differs")
            with Image.open(tile_path) as image:
                if image.size != (tile["width_px"], tile["height_px"]):
                    errors.append(f"{candidate_id}:{key}:dimensions_differ")

        window = record["crop_window_original_px"]
        bbox = record["candidate_bbox_original_px"]
        relative = record["candidate_bbox_tile_px"]
        expected_x = bbox["x"] - window["x"]
        expected_y = bbox["y"] - window["y"]
        if abs(relative["x"] - expected_x) > 1e-6:
            errors.append(f"{candidate_id}:relative_x_differs")
        if abs(relative["y"] - expected_y) > 1e-6:
            errors.append(f"{candidate_id}:relative_y_differs")

    sheet = REVISION / "ocr_tiles_contact_sheet.png"
    if sha256(sheet) != manifest["contact_sheet"]["sha256"]:
        errors.append("contact_sheet_hash_differs")

    result = {
        "record_count": len(manifest["records"]),
        "file_count": sum(1 for item in REVISION.rglob("*") if item.is_file()),
        "abstained_count": sum(1 for item in manifest["records"] if item["abstained"]),
        "contact_sheet_hash_ok": "contact_sheet_hash_differs" not in errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
