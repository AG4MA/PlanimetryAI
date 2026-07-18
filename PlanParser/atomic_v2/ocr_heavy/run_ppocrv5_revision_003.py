from __future__ import annotations

import argparse
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

import run_ppocrv5_revision_002 as support


HERE = Path(__file__).resolve().parent
INPUT_IMAGE = (
    HERE.parent
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_001.png"
)
RUNTIME_ROOT = HERE / "runtime"
DETECTION_MODEL = RUNTIME_ROOT / "models" / "official_models" / "PP-OCRv5_server_det"
RECOGNITION_MODEL = (
    RUNTIME_ROOT / "models" / "official_models" / "latin_PP-OCRv5_mobile_rec"
)
OUTPUT_DIR = (
    HERE
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_003"
)
ENGINE_ATTEMPTS = {
    "paddle": 1,
    "paddle_static": 2,
    "paddle_dynamic": 3,
}

# Reuse only serialization/visualization helpers. Redirect every helper global to
# revision_003 before it can write; revision_002 remains read-only history.
support.INPUT_IMAGE = INPUT_IMAGE
support.RUNTIME_ROOT = RUNTIME_ROOT
support.DETECTION_MODEL = DETECTION_MODEL
support.RECOGNITION_MODEL = RECOGNITION_MODEL
support.OUTPUT_DIR = OUTPUT_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable attempt artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(support.jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rewrite_running_manifest(path: Path, payload: dict[str, Any]) -> None:
    # This path belongs solely to the current attempt. It is written as RUNNING,
    # then finalized once; later invocations refuse because the attempt file exists.
    path.write_text(
        json.dumps(support.jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def set_environment(attempt_slug: str) -> dict[str, str]:
    cache_root = OUTPUT_DIR / "runtime_cache" / attempt_slug
    values = {
        "PADDLE_PDX_CACHE_HOME": str(cache_root / "paddlex"),
        "PADDLE_HOME": str(cache_root / "paddle"),
        "HF_HOME": str(RUNTIME_ROOT / "models" / "huggingface"),
        "FLAGS_use_mkldnn": "0",
        "FLAGS_enable_onednn": "0",
        "FLAGS_use_onednn": "0",
        "DNNL_VERBOSE": "0",
        "MKLDNN_VERBOSE": "0",
        "OMP_NUM_THREADS": "2",
    }
    for key, value in values.items():
        os.environ[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=tuple(ENGINE_ATTEMPTS))
    args = parser.parse_args()

    attempt_number = ENGINE_ATTEMPTS[args.engine]
    attempt_slug = f"attempt_{attempt_number:03d}_{args.engine}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    attempt_path = OUTPUT_DIR / f"{attempt_slug}.json"
    manifest_path = OUTPUT_DIR / f"runtime_manifest_{attempt_number:03d}_{args.engine}.json"
    if attempt_path.exists() or manifest_path.exists():
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "immutable attempt already exists",
                    "attempt": str(attempt_path),
                    "manifest": str(manifest_path),
                }
            ),
            file=sys.stderr,
        )
        return 2

    environment = set_environment(attempt_slug)
    start = time.perf_counter()
    started_at = utc_now()
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "running",
        "attempt": attempt_number,
        "engine": args.engine,
        "started_at": started_at,
        "input_image": str(INPUT_IMAGE),
        "output_directory": str(OUTPUT_DIR),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "packages": {
                "paddlepaddle": package_version("paddlepaddle"),
                "paddleocr": package_version("paddleocr"),
                "paddlex": package_version("paddlex"),
            },
        },
        "environment": environment,
        "enable_mkldnn": False,
        "model_names": {
            "detection": "PP-OCRv5_server_det",
            "recognition": "latin_PP-OCRv5_mobile_rec",
        },
        "models": {
            "detection": support.readable_directory(DETECTION_MODEL),
            "recognition": support.readable_directory(RECOGNITION_MODEL),
        },
        "timings_seconds": {},
    }
    write_json_new(manifest_path, manifest)

    init_seconds: float | None = None
    inference_seconds: float | None = None
    try:
        if not INPUT_IMAGE.is_file():
            raise FileNotFoundError(f"input image missing: {INPUT_IMAGE}")
        if not DETECTION_MODEL.is_dir():
            raise FileNotFoundError(f"detection model missing: {DETECTION_MODEL}")
        if not RECOGNITION_MODEL.is_dir():
            raise FileNotFoundError(f"recognition model missing: {RECOGNITION_MODEL}")

        init_start = time.perf_counter()
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_detection_model_dir=str(DETECTION_MODEL),
            text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
            text_recognition_model_dir=str(RECOGNITION_MODEL),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
            engine=args.engine,
            enable_hpi=False,
            enable_mkldnn=False,
            cpu_threads=2,
        )
        init_seconds = time.perf_counter() - init_start

        inference_start = time.perf_counter()
        results = ocr.predict(str(INPUT_IMAGE))
        inference_seconds = time.perf_counter() - inference_start
        if not results:
            raise RuntimeError("PP-OCRv5 returned no result object")

        raw_pages = [support.result_payload(result) for result in results]
        items: list[dict[str, Any]] = []
        for page in raw_pages:
            items.extend(support.extract_items(page))
        raw_path = OUTPUT_DIR / f"ppocrv5_raw_{attempt_number:03d}_{args.engine}.json"
        overlay_path = OUTPUT_DIR / f"ppocrv5_overlay_{attempt_number:03d}_{args.engine}.png"
        write_json_new(
            raw_path,
            {
                "schema_version": "1.0",
                "attempt": attempt_number,
                "engine": args.engine,
                "input_image": str(INPUT_IMAGE),
                "items": items,
                "paddle_raw": raw_pages,
            },
        )
        if overlay_path.exists():
            raise FileExistsError(f"immutable overlay already exists: {overlay_path}")
        support.draw_overlay(items, overlay_path)
        total_seconds = time.perf_counter() - start
        attempt = {
            "status": "success",
            "attempt": attempt_number,
            "engine": args.engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "text_count": len(items),
            "timings_seconds": {
                "initialization": init_seconds,
                "inference": inference_seconds,
                "total": total_seconds,
            },
            "outputs": {
                "raw_json": str(raw_path),
                "overlay_png": str(overlay_path),
                "runtime_manifest": str(manifest_path),
            },
        }
        write_json_new(attempt_path, attempt)
        manifest.update(attempt)
        rewrite_running_manifest(manifest_path, manifest)
        print(json.dumps(attempt, ensure_ascii=False))
        return 0
    except BaseException as exc:
        total_seconds = time.perf_counter() - start
        error = {
            "status": "error",
            "attempt": attempt_number,
            "engine": args.engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "timings_seconds": {
                "initialization": init_seconds,
                "inference": inference_seconds,
                "total": total_seconds,
            },
        }
        write_json_new(attempt_path, error)
        manifest.update(error)
        manifest["models"] = {
            "detection": support.readable_directory(DETECTION_MODEL),
            "recognition": support.readable_directory(RECOGNITION_MODEL),
        }
        rewrite_running_manifest(manifest_path, manifest)
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
