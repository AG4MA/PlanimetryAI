from __future__ import annotations

import importlib.util
import json
import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw


COMPONENT_DIR = Path(__file__).resolve().parent
BASE_BUILDER = COMPONENT_DIR / "build_revision_001.py"
ARTIFACT_PARENT = (
    COMPONENT_DIR / "artifacts/scheda_catastale/page_0001"
)
TARGET = ARTIFACT_PARENT / "revision_002"


def load_base_builder():
    spec = importlib.util.spec_from_file_location("compass_observation_r001", BASE_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load base builder: {BASE_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_overlay(module, stage: Path) -> None:
    overlay_path = stage / "compass_observation_overlay.png"
    page = Image.open(module.PAGE).convert("RGB")
    overlay = Image.open(overlay_path).convert("RGB")
    draw = ImageDraw.Draw(overlay)

    panel_x = page.width
    draw.rectangle((panel_x + 30, 78, overlay.width - 30, 126), fill="#f8fafc")
    draw.text(
        (panel_x + 42, 88),
        "revision_002  |  atomic sheet-level observation",
        fill="#475569",
        font=module.font(20),
    )

    payload = json.loads((stage / "compass_observation.json").read_text(encoding="utf-8"))
    bbox = payload["observations"][0]["bbox_page_px"]
    old_label_box = (
        bbox["x"] - 10,
        bbox["y"] - 54,
        page.width,
        bbox["y"] - 10,
    )
    overlay.paste(page.crop(old_label_box), old_label_box)
    label_right = bbox["x"] - 20
    label_left = max(20, label_right - 590)
    draw.rectangle(
        (label_left, bbox["y"] - 54, label_right, bbox["y"] - 10),
        fill="#e11d48",
    )
    draw.text(
        (label_left + 10, bbox["y"] - 48),
        "CO-001  sheet-level directional compass glyph candidate",
        fill="white",
        font=module.font(24, True),
    )
    draw.line(
        (label_right, bbox["y"] - 32, bbox["x"] - 10, bbox["y"] - 10),
        fill="#e11d48",
        width=5,
    )
    overlay.save(overlay_path, optimize=True)


def update_staged_metadata(module, stage: Path) -> None:
    json_path = stage / "compass_observation.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["revision"] = "revision_002"
    payload["publication"] = {
        "mode": "staged_directory_then_atomic_rename",
        "target_was_absent": True,
        "prior_revision_modified": False,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = stage / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["revision"] = "revision_002"
    manifest["publication"] = {
        "mode": "staged_directory_then_atomic_rename",
        "target": TARGET.name,
    }
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = module.sha256(stage / artifact["path"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(f"Refusing to overwrite immutable artifact revision: {TARGET}")
    ARTIFACT_PARENT.mkdir(parents=True, exist_ok=True)
    stage = ARTIFACT_PARENT / f".revision_002.staging_{uuid.uuid4().hex}"
    if stage.exists():
        raise FileExistsError(f"Unexpected staging collision: {stage}")

    module = load_base_builder()
    module.OUTPUT = stage
    module.main()
    patch_overlay(module, stage)
    update_staged_metadata(module, stage)

    required = {
        "compass_observation.json",
        "compass_observation_overlay.png",
        "artifact_manifest.json",
    }
    present = {item.name for item in stage.iterdir() if item.is_file()}
    if present != required:
        raise RuntimeError(f"Staged artifact set mismatch: expected={required}, present={present}")
    os.replace(stage, TARGET)
    print(
        json.dumps(
            {
                "published": str(TARGET),
                "publication_mode": "atomic_directory_rename",
                "artifacts": sorted(required),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
