from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = MODULE_ROOT / "runtime"
MODEL_CACHE = RUNTIME_ROOT / "models" / "doctr"
SOURCE = (
    MODULE_ROOT.parent
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_001.png"
)
OUTPUT = (
    MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)

DETECTOR_ARCHITECTURE = "db_resnet50"
RECOGNIZER_ARCHITECTURE = "parseq"
ABSTENTION_CONFIDENCE_FLOOR = 0.50


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return json_safe(value.tolist())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Path):
        return value.as_posix()
    return value


def normalized_polygon(geometry: Any) -> list[list[float]]:
    points = [[float(point[0]), float(point[1])] for point in geometry]
    if len(points) == 2:
        (x0, y0), (x1, y1) = points
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    if len(points) >= 4:
        return points
    raise ValueError(f"Unsupported word geometry: {geometry!r}")


def pixel_polygon(points: list[list[float]], width: int, height: int) -> list[list[int]]:
    return [
        [
            max(0, min(width - 1, round(point[0] * width))),
            max(0, min(height - 1, round(point[1] * height))),
        ]
        for point in points
    ]


def bbox(points: list[list[float | int]]) -> list[float | int]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def flatten_words(raw_export: dict[str, Any], width: int, height: int) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for page_index, page in enumerate(raw_export.get("pages", [])):
        for block_index, block in enumerate(page.get("blocks", [])):
            for line_index, line in enumerate(block.get("lines", [])):
                for word_index, word in enumerate(line.get("words", [])):
                    text_raw = str(word.get("value", ""))
                    confidence_value = word.get("confidence")
                    confidence_raw = (
                        float(confidence_value) if confidence_value is not None else None
                    )
                    objectness_value = word.get("objectness_score")
                    objectness_raw = (
                        float(objectness_value) if objectness_value is not None else None
                    )
                    polygon_normalized = normalized_polygon(word["geometry"])
                    polygon_pixels = pixel_polygon(polygon_normalized, width, height)

                    reasons: list[str] = []
                    if not text_raw.strip():
                        reasons.append("empty_raw_transcription")
                    if confidence_raw is None:
                        reasons.append("missing_raw_recognition_confidence")
                    elif confidence_raw < ABSTENTION_CONFIDENCE_FLOOR:
                        reasons.append("raw_recognition_confidence_below_floor")

                    words.append(
                        {
                            "id": f"word_{len(words) + 1:04d}",
                            "page_index": page_index,
                            "block_index": block_index,
                            "line_index": line_index,
                            "word_index": word_index,
                            "text_raw": text_raw,
                            "confidence_raw": confidence_raw,
                            "objectness_score_raw": objectness_raw,
                            "geometry_raw_normalized": json_safe(word.get("geometry")),
                            "polygon_normalized": polygon_normalized,
                            "bbox_normalized": bbox(polygon_normalized),
                            "polygon_pixels": polygon_pixels,
                            "bbox_pixels": bbox(polygon_pixels),
                            "crop_orientation_raw": json_safe(word.get("crop_orientation")),
                            "abstention": {
                                "abstained": bool(reasons),
                                "reasons": reasons,
                            },
                        }
                    )
    return words


def model_cache_manifest() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not MODEL_CACHE.exists():
        return entries
    for path in sorted(item for item in MODEL_CACHE.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(MODULE_ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_overlay(source: Path, words: list[dict[str, Any]], target: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(source).convert("RGBA")
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.load_default()

    for word in words:
        abstained = bool(word["abstention"]["abstained"])
        color = (255, 123, 0, 255) if abstained else (0, 160, 80, 255)
        fill = (255, 123, 0, 42) if abstained else (0, 160, 80, 35)
        polygon = [tuple(point) for point in word["polygon_pixels"]]
        draw.polygon(polygon, fill=fill)
        draw.line(polygon + [polygon[0]], fill=color, width=2)

        confidence = word["confidence_raw"]
        confidence_label = "n/a" if confidence is None else f"{confidence:.3f}"
        label = f"{word['id']} {word['text_raw']} [{confidence_label}]"
        anchor_x, anchor_y = polygon[0]
        label_box = draw.textbbox((anchor_x, max(0, anchor_y - 12)), label, font=font)
        draw.rectangle(label_box, fill=(255, 255, 255, 220))
        draw.text(
            (anchor_x, max(0, anchor_y - 12)),
            label,
            fill=color,
            font=font,
        )

    Image.alpha_composite(image, layer).convert("RGB").save(target, format="PNG")


def run() -> None:
    started_at = utc_now()
    total_start = time.perf_counter()
    if OUTPUT.exists():
        existing_names = {path.name for path in OUTPUT.iterdir()}
        if not existing_names.issubset({"error.json"}):
            raise FileExistsError(
                f"Output revision already contains non-error artifacts: {sorted(existing_names)}"
            )
    else:
        OUTPUT.mkdir(parents=True, exist_ok=False)

    try:
        os.environ["DOCTR_CACHE_DIR"] = str(MODEL_CACHE)
        os.environ["TORCH_HOME"] = str(RUNTIME_ROOT / "models")
        os.environ["XDG_CACHE_HOME"] = str(RUNTIME_ROOT / "xdg_cache")
        os.environ["HF_HOME"] = str(RUNTIME_ROOT / "models" / "huggingface")

        if not SOURCE.is_file():
            raise FileNotFoundError(f"Source image not found: {SOURCE}")

        from PIL import Image
        import doctr
        import torch
        import torchvision
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor

        torch.set_grad_enabled(False)
        source_image = Image.open(SOURCE)
        width, height = source_image.size

        model_load_start = time.perf_counter()
        predictor = ocr_predictor(
            det_arch=DETECTOR_ARCHITECTURE,
            reco_arch=RECOGNIZER_ARCHITECTURE,
            pretrained=True,
            assume_straight_pages=False,
            preserve_aspect_ratio=True,
            symmetric_pad=True,
            export_as_straight_boxes=False,
            detect_orientation=False,
            straighten_pages=False,
            detect_language=False,
        )
        predictor = predictor.to(torch.device("cpu"))
        model_load_ms = (time.perf_counter() - model_load_start) * 1000

        document_load_start = time.perf_counter()
        document = DocumentFile.from_images(str(SOURCE))
        document_load_ms = (time.perf_counter() - document_load_start) * 1000

        inference_start = time.perf_counter()
        with torch.inference_mode():
            result = predictor(document)
        inference_ms = (time.perf_counter() - inference_start) * 1000

        raw_export = json_safe(result.export())
        words = flatten_words(raw_export, width, height)
        abstained_count = sum(bool(word["abstention"]["abstained"]) for word in words)

        raw_payload = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.raw.v1",
            "status": "completed",
            "created_at_utc": utc_now(),
            "source": {
                "path": SOURCE.relative_to(MODULE_ROOT.parent).as_posix(),
                "bytes": SOURCE.stat().st_size,
                "sha256": sha256_file(SOURCE),
                "width_pixels": width,
                "height_pixels": height,
                "mode": source_image.mode,
            },
            "engine": {
                "name": "docTR",
                "distribution": "python-doctr",
                "version": doctr.__version__,
                "backend": "PyTorch",
                "device": "cpu",
                "detector": {
                    "architecture": DETECTOR_ARCHITECTURE,
                    "pretrained": True,
                },
                "recognizer": {
                    "architecture": RECOGNIZER_ARCHITECTURE,
                    "pretrained": True,
                },
                "options": {
                    "assume_straight_pages": False,
                    "preserve_aspect_ratio": True,
                    "symmetric_pad": True,
                    "export_as_straight_boxes": False,
                    "detect_orientation": False,
                    "straighten_pages": False,
                    "detect_language": False,
                },
            },
            "abstention_policy": {
                "type": "raw_recognition_confidence_floor",
                "threshold": ABSTENTION_CONFIDENCE_FLOOR,
                "effect": "annotation_only_raw_word_is_retained",
            },
            "counts": {
                "words_total": len(words),
                "words_not_abstained": len(words) - abstained_count,
                "words_abstained": abstained_count,
            },
            "timings_ms": {
                "model_load": round(model_load_ms, 3),
                "document_load": round(document_load_ms, 3),
                "inference": round(inference_ms, 3),
            },
            "words": words,
            "document_export_raw": raw_export,
        }

        write_json(OUTPUT / "ocr_raw.json", raw_payload)
        render_overlay(SOURCE, words, OUTPUT / "ocr_overlay.png")

        total_ms = (time.perf_counter() - total_start) * 1000
        manifest = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.runtime.v1",
            "status": "completed",
            "started_at_utc": started_at,
            "completed_at_utc": utc_now(),
            "runtime": {
                "python": sys.version,
                "python_executable": Path(sys.executable).relative_to(MODULE_ROOT).as_posix(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "packages": {
                    "python-doctr": package_version("python-doctr"),
                    "torch": torch.__version__,
                    "torchvision": torchvision.__version__,
                    "numpy": package_version("numpy"),
                    "Pillow": package_version("Pillow"),
                    "opencv-python": package_version("opencv-python"),
                },
                "torch_cuda_available": torch.cuda.is_available(),
                "torch_num_threads": torch.get_num_threads(),
            },
            "models": {
                "detector": DETECTOR_ARCHITECTURE,
                "recognizer": RECOGNIZER_ARCHITECTURE,
                "pretrained": True,
                "cache_root": MODEL_CACHE.relative_to(MODULE_ROOT).as_posix(),
                "cached_files": model_cache_manifest(),
            },
            "source_sha256": sha256_file(SOURCE),
            "outputs": {
                "ocr_raw.json": sha256_file(OUTPUT / "ocr_raw.json"),
                "ocr_overlay.png": sha256_file(OUTPUT / "ocr_overlay.png"),
            },
            "timings_ms": {
                "model_load": round(model_load_ms, 3),
                "document_load": round(document_load_ms, 3),
                "inference": round(inference_ms, 3),
                "total_before_manifest_write": round(total_ms, 3),
            },
        }
        write_json(OUTPUT / "runtime_manifest.json", manifest)
    except Exception as exc:
        error_payload = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.error.v1",
            "status": "failed",
            "started_at_utc": started_at,
            "failed_at_utc": utc_now(),
            "stage": "model_load_or_inference_or_artifact_write",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "source": str(SOURCE),
            "detector": DETECTOR_ARCHITECTURE,
            "recognizer": RECOGNIZER_ARCHITECTURE,
        }
        error_target = OUTPUT / "error.json"
        attempt_index = 2
        while error_target.exists():
            error_target = OUTPUT / f"error_attempt_{attempt_index:03d}.json"
            attempt_index += 1
        write_json(error_target, error_payload)
        raise


if __name__ == "__main__":
    run()
