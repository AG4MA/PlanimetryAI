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

import run_doctr as base


MODULE_ROOT = Path(__file__).resolve().parent
OUTPUT = (
    MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_002"
)
PREFLIGHT_MANIFEST = OUTPUT / "preflight_manifest.json"
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


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite immutable artifact: {path}")
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cache_snapshot() -> list[dict[str, Any]]:
    if not base.MODEL_CACHE.is_dir():
        raise FileNotFoundError(f"Model cache not found: {base.MODEL_CACHE}")
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in base.MODEL_CACHE.rglob("*") if item.is_file()):
        stat = path.stat()
        entries.append(
            {
                "path": path.relative_to(MODULE_ROOT).as_posix(),
                "bytes": stat.st_size,
                "modified_time_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )
    return entries


def count_structure(raw_export: dict[str, Any]) -> tuple[int, int]:
    blocks = 0
    lines = 0
    for page in raw_export.get("pages", []):
        page_blocks = page.get("blocks", [])
        blocks += len(page_blocks)
        lines += sum(len(block.get("lines", [])) for block in page_blocks)
    return blocks, lines


def run() -> None:
    started_at = utc_now()
    total_start = time.perf_counter()
    OUTPUT.mkdir(parents=True, exist_ok=False)

    if not base.SOURCE.is_file():
        raise FileNotFoundError(f"Source image not found: {base.SOURCE}")

    source_stat = base.SOURCE.stat()
    source_hash = sha256_file(base.SOURCE)
    cache_before = cache_snapshot()
    expected_weight_names = {
        "db_resnet50-79bd7d70.pt",
        "parseq-56125471.pt",
        "mobilenet_v3_small_crop_orientation-f0847a18.pt",
        "mobilenet_v3_small_page_orientation-8e60325c.pt",
    }
    cached_names = {Path(item["path"]).name for item in cache_before}
    missing_weights = sorted(expected_weight_names - cached_names)
    if missing_weights:
        raise FileNotFoundError(f"Required cached model weights missing: {missing_weights}")

    preflight = {
        "schema_version": "planparser.atomic_v2.ocr_doctr.preflight.v1",
        "status": "preflight_completed_before_inference",
        "created_at_utc": utc_now(),
        "source": {
            "path": base.SOURCE.relative_to(MODULE_ROOT.parent).as_posix(),
            "bytes": source_stat.st_size,
            "modified_time_ns": source_stat.st_mtime_ns,
            "sha256": source_hash,
        },
        "planned_runtime": {
            "python": sys.version,
            "python_executable": Path(sys.executable).relative_to(MODULE_ROOT).as_posix(),
            "device": "cpu",
            "detector": DETECTOR_ARCHITECTURE,
            "recognizer": RECOGNIZER_ARCHITECTURE,
            "network_required": False,
        },
        "model_cache_before_inference": cache_before,
        "cache_policy": "reuse_existing_files_without_writes; verify byte/hash/mtime snapshot after inference",
    }
    write_json_once(PREFLIGHT_MANIFEST, preflight)
    print(f"PREFLIGHT_WRITTEN {PREFLIGHT_MANIFEST}", flush=True)

    try:
        os.environ["DOCTR_CACHE_DIR"] = str(base.MODEL_CACHE)
        os.environ["TORCH_HOME"] = str(base.RUNTIME_ROOT / "models")
        os.environ["XDG_CACHE_HOME"] = str(base.RUNTIME_ROOT / "xdg_cache")
        os.environ["HF_HOME"] = str(base.RUNTIME_ROOT / "models" / "huggingface")

        from PIL import Image
        import doctr
        import torch
        import torchvision
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor

        torch.set_grad_enabled(False)
        source_image = Image.open(base.SOURCE)
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
        ).to(torch.device("cpu"))
        model_load_ms = (time.perf_counter() - model_load_start) * 1000
        print(f"MODEL_LOADED_MS {model_load_ms:.3f}", flush=True)

        document_load_start = time.perf_counter()
        document = DocumentFile.from_images(str(base.SOURCE))
        document_load_ms = (time.perf_counter() - document_load_start) * 1000

        inference_start = time.perf_counter()
        with torch.inference_mode():
            result = predictor(document)
        inference_ms = (time.perf_counter() - inference_start) * 1000
        print(f"INFERENCE_COMPLETED_MS {inference_ms:.3f}", flush=True)

        raw_export = json_safe(result.export())
        words = base.flatten_words(raw_export, width, height)
        abstained_count = sum(bool(word["abstention"]["abstained"]) for word in words)
        block_count, line_count = count_structure(raw_export)

        raw_payload = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.raw.v2",
            "status": "completed",
            "created_at_utc": utc_now(),
            "source": {
                "path": base.SOURCE.relative_to(MODULE_ROOT.parent).as_posix(),
                "bytes": source_stat.st_size,
                "sha256": source_hash,
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
                "pages": len(raw_export.get("pages", [])),
                "blocks": block_count,
                "lines": line_count,
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
            "limits": [
                "single_crop_single_pass_only",
                "no_ground_truth_accuracy_claim",
                "raw_confidence_not_calibrated_for_floorplans",
                "no_text_correction_or_semantic_interpretation",
                "text_not_detected_by_the_detector_is_absent_from_this_output",
            ],
        }

        write_json_once(OUTPUT / "ocr_raw.json", raw_payload)
        base.render_overlay(base.SOURCE, words, OUTPUT / "ocr_overlay.png")

        cache_after = cache_snapshot()
        cache_unchanged = cache_before == cache_after
        if not cache_unchanged:
            raise RuntimeError("Model cache snapshot changed during revision_002 inference")

        total_ms = (time.perf_counter() - total_start) * 1000
        manifest = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.runtime.v2",
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
                "cache_root": base.MODEL_CACHE.relative_to(MODULE_ROOT).as_posix(),
                "cache_reused_without_content_or_mtime_change": cache_unchanged,
                "cached_files": cache_after,
            },
            "source_sha256": source_hash,
            "outputs": {
                "preflight_manifest.json": sha256_file(PREFLIGHT_MANIFEST),
                "ocr_raw.json": sha256_file(OUTPUT / "ocr_raw.json"),
                "ocr_overlay.png": sha256_file(OUTPUT / "ocr_overlay.png"),
            },
            "counts": raw_payload["counts"],
            "timings_ms": {
                "model_load": round(model_load_ms, 3),
                "document_load": round(document_load_ms, 3),
                "inference": round(inference_ms, 3),
                "total_before_manifest_write": round(total_ms, 3),
            },
            "limits": raw_payload["limits"],
        }
        write_json_once(OUTPUT / "runtime_manifest.json", manifest)
        print(f"ARTIFACTS_COMPLETED {OUTPUT}", flush=True)
    except Exception as exc:
        error_payload = {
            "schema_version": "planparser.atomic_v2.ocr_doctr.error.v2",
            "status": "failed",
            "started_at_utc": started_at,
            "failed_at_utc": utc_now(),
            "stage": "model_load_or_inference_or_artifact_write",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "source_sha256": source_hash,
            "detector": DETECTOR_ARCHITECTURE,
            "recognizer": RECOGNIZER_ARCHITECTURE,
        }
        write_json_once(OUTPUT / "error.json", error_payload)
        raise


if __name__ == "__main__":
    run()
