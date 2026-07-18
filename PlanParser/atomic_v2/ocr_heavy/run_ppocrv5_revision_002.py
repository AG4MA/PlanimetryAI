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


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
INPUT_IMAGE = (
    PROJECT_ROOT
    / "atomic_v2"
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
    / "revision_002"
)
ENGINES = ("paddle", "paddle_static", "paddle_dynamic")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def readable_directory(path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not state["exists"]:
        state["readable"] = False
        state["error"] = "directory does not exist"
        return state
    try:
        entries = sorted(item.name for item in path.iterdir())
        state["readable"] = True
        state["entries"] = entries
    except Exception as exc:  # Preserve the exact filesystem failure in evidence.
        state["readable"] = False
        state["error_type"] = type(exc).__name__
        state["error"] = str(exc)
    return state


def set_isolated_environment() -> dict[str, str]:
    cache_root = OUTPUT_DIR / "runtime_cache"
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


def result_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "json"):
        payload = result.json
        if isinstance(payload, dict) and "res" in payload:
            payload = payload["res"]
        if isinstance(payload, dict):
            return jsonable(payload)
    if isinstance(result, dict):
        return jsonable(result)
    try:
        return jsonable(dict(result))
    except Exception:
        return {"repr": repr(result)}


def extract_items(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    texts = list(raw_result.get("rec_texts") or [])
    scores = list(raw_result.get("rec_scores") or [])
    polygons = list(raw_result.get("rec_polys") or raw_result.get("dt_polys") or [])
    items: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        polygon = polygons[index] if index < len(polygons) else []
        score = scores[index] if index < len(scores) else None
        points = [[float(point[0]), float(point[1])] for point in polygon]
        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        else:
            bbox = None
        items.append(
            {
                "index": index,
                "text": str(text),
                "confidence": None if score is None else float(score),
                "polygon": points,
                "bbox_xyxy": bbox,
            }
        )
    return items


def draw_overlay(items: list[dict[str, Any]], output_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(INPUT_IMAGE).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    for item in items:
        points = [(round(x), round(y)) for x, y in item["polygon"]]
        if len(points) >= 3:
            draw.polygon(points, fill=(255, 215, 0, 45), outline=(220, 25, 35, 255), width=2)
        bbox = item["bbox_xyxy"]
        if bbox is None:
            continue
        confidence = item["confidence"]
        label = item["text"]
        if confidence is not None:
            label = f"{label}  {confidence:.3f}"
        left, top = round(bbox[0]), round(bbox[1])
        label_box = draw.textbbox((left, max(0, top - 14)), label, font=font)
        draw.rectangle(label_box, fill=(255, 255, 255, 225))
        draw.text(
            (left, max(0, top - 14)),
            label,
            fill=(10, 30, 190, 255),
            font=font,
        )
    image.save(output_path)


def collect_failures() -> list[dict[str, Any]]:
    failures = []
    for engine in ENGINES:
        path = OUTPUT_DIR / f"attempt_{engine}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("status") == "error":
            failures.append(payload)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=ENGINES)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    environment = set_isolated_environment()
    start = time.perf_counter()
    started_at = utc_now()
    attempt_path = OUTPUT_DIR / f"attempt_{args.engine}.json"
    manifest_path = OUTPUT_DIR / "runtime_manifest.json"
    init_seconds: float | None = None
    inference_seconds: float | None = None
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "running",
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
        "models": {
            "detection": readable_directory(DETECTION_MODEL),
            "recognition": readable_directory(RECOGNITION_MODEL),
        },
        "timings_seconds": {},
    }
    write_json(manifest_path, manifest)

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
            text_detection_model_dir=str(DETECTION_MODEL),
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

        raw_pages = [result_payload(result) for result in results]
        items: list[dict[str, Any]] = []
        for page in raw_pages:
            items.extend(extract_items(page))
        raw_output = {
            "schema_version": "1.0",
            "engine": args.engine,
            "input_image": str(INPUT_IMAGE),
            "model": {
                "detection": str(DETECTION_MODEL),
                "recognition": str(RECOGNITION_MODEL),
            },
            "items": items,
            "paddle_raw": raw_pages,
        }
        raw_path = OUTPUT_DIR / "ppocrv5_raw.json"
        overlay_path = OUTPUT_DIR / "ppocrv5_overlay.png"
        write_json(raw_path, raw_output)
        draw_overlay(items, overlay_path)
        total_seconds = time.perf_counter() - start
        attempt = {
            "status": "success",
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
        write_json(attempt_path, attempt)
        manifest.update(attempt)
        manifest["models"] = {
            "detection": readable_directory(DETECTION_MODEL),
            "recognition": readable_directory(RECOGNITION_MODEL),
        }
        write_json(manifest_path, manifest)
        print(json.dumps(attempt, ensure_ascii=False))
        return 0
    except BaseException as exc:
        total_seconds = time.perf_counter() - start
        error = {
            "status": "error",
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
        write_json(attempt_path, error)
        manifest.update(error)
        manifest["models"] = {
            "detection": readable_directory(DETECTION_MODEL),
            "recognition": readable_directory(RECOGNITION_MODEL),
        }
        write_json(manifest_path, manifest)
        write_json(
            OUTPUT_DIR / "errors.json",
            {"schema_version": "1.0", "failures": collect_failures()},
        )
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
