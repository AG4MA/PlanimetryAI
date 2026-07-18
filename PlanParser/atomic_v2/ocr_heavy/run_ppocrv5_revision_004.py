from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
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
ORIGINAL_MODEL_ROOT = HERE / "runtime" / "models" / "official_models"
ORIGINAL_DETECTION_MODEL = ORIGINAL_MODEL_ROOT / "PP-OCRv5_server_det"
ORIGINAL_RECOGNITION_MODEL = ORIGINAL_MODEL_ROOT / "latin_PP-OCRv5_mobile_rec"
ORIGINAL_HF_REF = (
    HERE
    / "runtime"
    / "models"
    / "huggingface"
    / "hub"
    / "models--PaddlePaddle--latin_PP-OCRv5_mobile_rec"
    / "refs"
    / "main"
)

RUNTIME_REVISION = HERE / "runtime" / "revision_004"
MODEL_BUNDLE = RUNTIME_REVISION / "attempt_001_model_bundle"
DETECTION_MODEL = MODEL_BUNDLE / "PP-OCRv5_server_det"
RECOGNITION_MODEL = MODEL_BUNDLE / "latin_PP-OCRv5_mobile_rec"
OUTPUT_DIR = (
    HERE
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_004"
)

RECOGNITION_REPO = "PaddlePaddle/latin_PP-OCRv5_mobile_rec"
RECOGNITION_COMMIT = "ab2cd5cc5fa6309be2e5acdfe66eca2c2c127d57"
MODEL_FILES = (
    ".gitattributes",
    "README.md",
    "config.json",
    "inference.json",
    "inference.pdiparams",
    "inference.yml",
)
RUNTIME_MODEL_FILES = (
    "config.json",
    "inference.json",
    "inference.pdiparams",
    "inference.yml",
)
ENGINES = ("paddle", "paddle_static")

support.INPUT_IMAGE = INPUT_IMAGE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    return support.jsonable(value)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(jsonable(payload), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_probe(path: Path, include_hash: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path)}
    try:
        stat = path.stat()
        result.update(
            {
                "stat_success": True,
                "is_file": path.is_file(),
                "is_directory": path.is_dir(),
                "size_bytes": stat.st_size,
                "mode": oct(stat.st_mode),
            }
        )
    except BaseException as exc:
        result.update(
            {
                "stat_success": False,
                "stat_error_type": type(exc).__name__,
                "stat_error": str(exc),
            }
        )
    try:
        with path.open("rb") as stream:
            prefix = stream.read(64)
        result["read_success"] = True
        result["prefix_hex"] = prefix.hex()
        if include_hash:
            result["sha256"] = sha256_file(path)
    except BaseException as exc:
        result.update(
            {
                "read_success": False,
                "read_error_type": type(exc).__name__,
                "read_error": str(exc),
            }
        )
    return result


def directory_probe(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path)}
    try:
        stat = path.stat()
        result.update(
            {
                "stat_success": True,
                "is_file": path.is_file(),
                "is_directory": path.is_dir(),
                "mode": oct(stat.st_mode),
            }
        )
    except BaseException as exc:
        result.update(
            {
                "stat_success": False,
                "stat_error_type": type(exc).__name__,
                "stat_error": str(exc),
            }
        )
    try:
        result["entries"] = sorted(item.name for item in path.iterdir())
        result["enumerate_success"] = True
    except BaseException as exc:
        result.update(
            {
                "enumerate_success": False,
                "enumerate_error_type": type(exc).__name__,
                "enumerate_error": str(exc),
            }
        )
    return result


def icacls_probe(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["icacls", str(path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
        )
        return {
            "path": str(path),
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except BaseException as exc:
        return {
            "path": str(path),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def model_hashes(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in MODEL_FILES:
        result[name] = file_probe(path / name, include_hash=True)
    return result


def collect_diagnosis() -> dict[str, Any]:
    ref: dict[str, Any] = file_probe(ORIGINAL_HF_REF, include_hash=True)
    if ref.get("read_success"):
        try:
            ref["commit"] = ORIGINAL_HF_REF.read_text(encoding="utf-8").strip()
        except BaseException as exc:
            ref["text_error_type"] = type(exc).__name__
            ref["text_error"] = str(exc)
    return {
        "schema_version": "1.0",
        "status": "diagnosed",
        "created_at": utc_now(),
        "constraint": "read-only diagnosis; no ACL, attribute, content, name, or path mutation on existing models",
        "process": {
            "user": os.environ.get("USERNAME"),
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "original_recognition_directory": directory_probe(
            ORIGINAL_RECOGNITION_MODEL
        ),
        "original_recognition_inference_yml": file_probe(
            ORIGINAL_RECOGNITION_MODEL / "inference.yml", include_hash=True
        ),
        "original_recognition_directory_acl": icacls_probe(
            ORIGINAL_RECOGNITION_MODEL
        ),
        "original_recognition_inference_yml_acl": icacls_probe(
            ORIGINAL_RECOGNITION_MODEL / "inference.yml"
        ),
        "original_recognition_expected_file_probes": model_hashes(
            ORIGINAL_RECOGNITION_MODEL
        ),
        "original_detection_directory": directory_probe(ORIGINAL_DETECTION_MODEL),
        "original_detection_directory_acl": icacls_probe(ORIGINAL_DETECTION_MODEL),
        "original_detection_hashes": model_hashes(ORIGINAL_DETECTION_MODEL),
        "accessible_huggingface_ref": ref,
        "diagnosis": {
            "scope": "whole recognition model directory, not only inference.yml",
            "reason": "directory enumeration, ACL query, stat/read of inference.yml, and every expected file are denied to this process",
            "workaround": "do not change ACL; build a new inherited-ACL bundle and fetch the exact official recognition commit",
        },
    }


def copy_file_exclusive(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, target.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def prepare_model_bundle() -> dict[str, Any]:
    started_at = utc_now()
    start = time.perf_counter()
    if RUNTIME_REVISION.exists():
        raise FileExistsError(f"immutable runtime revision already exists: {RUNTIME_REVISION}")
    MODEL_BUNDLE.mkdir(parents=True, exist_ok=False)
    DETECTION_MODEL.mkdir(exist_ok=False)
    RECOGNITION_MODEL.mkdir(exist_ok=False)

    copied_detection: dict[str, Any] = {}
    for name in MODEL_FILES:
        source = ORIGINAL_DETECTION_MODEL / name
        if not source.is_file():
            if name in RUNTIME_MODEL_FILES:
                raise FileNotFoundError(f"required detector model file missing: {source}")
            continue
        target = DETECTION_MODEL / name
        copy_file_exclusive(source, target)
        copied_detection[name] = {
            "source_sha256": sha256_file(source),
            "target_sha256": sha256_file(target),
            "size_bytes": target.stat().st_size,
        }
        if copied_detection[name]["source_sha256"] != copied_detection[name]["target_sha256"]:
            raise RuntimeError(f"detector copy hash mismatch: {name}")

    os.environ["HF_HOME"] = str(RUNTIME_REVISION / "huggingface_cache")
    os.environ["HF_HUB_CACHE"] = str(RUNTIME_REVISION / "huggingface_cache" / "hub")
    from huggingface_hub import snapshot_download

    resolved_path = snapshot_download(
        repo_id=RECOGNITION_REPO,
        revision=RECOGNITION_COMMIT,
        local_dir=str(RECOGNITION_MODEL),
        allow_patterns=list(MODEL_FILES),
        max_workers=1,
    )

    for name in RUNTIME_MODEL_FILES:
        path = RECOGNITION_MODEL / name
        if not path.is_file():
            raise FileNotFoundError(f"downloaded recognition file missing: {path}")
        with path.open("rb") as stream:
            stream.read(64)

    result = {
        "schema_version": "1.0",
        "status": "success",
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": time.perf_counter() - start,
        "source": {
            "repository": RECOGNITION_REPO,
            "commit": RECOGNITION_COMMIT,
            "network_usage": "official model files downloaded only; input image was never transmitted",
        },
        "resolved_download_path": resolved_path,
        "bundle": str(MODEL_BUNDLE),
        "copied_detection": copied_detection,
        "detection_hashes": model_hashes(DETECTION_MODEL),
        "recognition_hashes": model_hashes(RECOGNITION_MODEL),
        "bundle_acl": icacls_probe(MODEL_BUNDLE),
        "recognition_directory_acl": icacls_probe(RECOGNITION_MODEL),
        "recognition_inference_yml_probe": file_probe(
            RECOGNITION_MODEL / "inference.yml", include_hash=True
        ),
    }
    return result


def set_worker_environment(engine: str) -> dict[str, str]:
    cache_root = OUTPUT_DIR / "runtime_cache" / engine
    values = {
        "PADDLE_PDX_CACHE_HOME": str(cache_root / "paddlex"),
        "PADDLE_HOME": str(cache_root / "paddle"),
        "HF_HOME": str(RUNTIME_REVISION / "huggingface_cache"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "1",
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


def worker(engine: str) -> int:
    attempt_number = ENGINES.index(engine) + 1
    slug = f"{attempt_number:03d}_{engine}"
    result_path = OUTPUT_DIR / f"worker_result_{slug}.json"
    if result_path.exists():
        raise FileExistsError(f"immutable worker result already exists: {result_path}")
    environment = set_worker_environment(engine)
    started_at = utc_now()
    start = time.perf_counter()
    initialization_seconds: float | None = None
    inference_seconds: float | None = None
    try:
        if not INPUT_IMAGE.is_file():
            raise FileNotFoundError(f"input image missing: {INPUT_IMAGE}")
        for model_dir in (DETECTION_MODEL, RECOGNITION_MODEL):
            for name in RUNTIME_MODEL_FILES:
                path = model_dir / name
                if not path.is_file():
                    raise FileNotFoundError(f"runtime model file missing: {path}")
                with path.open("rb") as stream:
                    stream.read(64)

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
            engine=engine,
            enable_hpi=False,
            enable_mkldnn=False,
            cpu_threads=2,
        )
        initialization_seconds = time.perf_counter() - init_start

        inference_start = time.perf_counter()
        results = ocr.predict(str(INPUT_IMAGE))
        inference_seconds = time.perf_counter() - inference_start
        if not results:
            raise RuntimeError("PP-OCRv5 returned no result object")

        raw_pages = [support.result_payload(result) for result in results]
        items: list[dict[str, Any]] = []
        for page in raw_pages:
            items.extend(support.extract_items(page))

        raw_path = OUTPUT_DIR / f"ppocrv5_raw_{slug}.json"
        overlay_path = OUTPUT_DIR / f"ppocrv5_overlay_{slug}.png"
        write_json_new(
            raw_path,
            {
                "schema_version": "1.0",
                "attempt": attempt_number,
                "engine": engine,
                "input_image": str(INPUT_IMAGE),
                "items": items,
                "paddle_raw": raw_pages,
            },
        )
        if overlay_path.exists():
            raise FileExistsError(f"immutable overlay already exists: {overlay_path}")
        support.draw_overlay(items, overlay_path)
        payload = {
            "schema_version": "1.0",
            "status": "success",
            "attempt": attempt_number,
            "engine": engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "text_count": len(items),
            "enable_mkldnn": False,
            "environment": environment,
            "timings_seconds": {
                "initialization": initialization_seconds,
                "inference": inference_seconds,
                "total": time.perf_counter() - start,
            },
            "outputs": {
                "raw_json": str(raw_path),
                "overlay_png": str(overlay_path),
            },
        }
        write_json_new(result_path, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except BaseException as exc:
        payload = {
            "schema_version": "1.0",
            "status": "error",
            "attempt": attempt_number,
            "engine": engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "enable_mkldnn": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "timings_seconds": {
                "initialization": initialization_seconds,
                "inference": inference_seconds,
                "total": time.perf_counter() - start,
            },
        }
        write_json_new(result_path, payload)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1


def run_worker_subprocess(engine: str) -> dict[str, Any]:
    attempt_number = ENGINES.index(engine) + 1
    slug = f"{attempt_number:03d}_{engine}"
    attempt_path = OUTPUT_DIR / f"attempt_{slug}.json"
    worker_path = OUTPUT_DIR / f"worker_result_{slug}.json"
    if attempt_path.exists() or worker_path.exists():
        raise FileExistsError(f"immutable engine attempt already exists: {slug}")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", engine]
    started_at = utc_now()
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=1800,
            check=False,
        )
        worker_payload = None
        if worker_path.is_file():
            worker_payload = json.loads(worker_path.read_text(encoding="utf-8"))
        payload = {
            "schema_version": "1.0",
            "status": (
                "success"
                if completed.returncode == 0
                and worker_payload
                and worker_payload.get("status") == "success"
                else "error"
            ),
            "attempt": attempt_number,
            "engine": engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "elapsed_seconds": time.perf_counter() - start,
            "enable_mkldnn": False,
            "process_return_code": completed.returncode,
            "worker_result": worker_payload,
            "stdout_tail": completed.stdout[-20000:],
            "stderr_tail": completed.stderr[-20000:],
        }
    except BaseException as exc:
        payload = {
            "schema_version": "1.0",
            "status": "error",
            "attempt": attempt_number,
            "engine": engine,
            "started_at": started_at,
            "finished_at": utc_now(),
            "elapsed_seconds": time.perf_counter() - start,
            "enable_mkldnn": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    write_json_new(attempt_path, payload)
    return payload


def run_all() -> int:
    if OUTPUT_DIR.exists() or RUNTIME_REVISION.exists():
        raise FileExistsError(
            "revision_004 is immutable and already exists; use a new revision"
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    diagnosis = collect_diagnosis()
    write_json_new(OUTPUT_DIR / "filesystem_diagnosis_001.json", diagnosis)

    try:
        model_replica = prepare_model_bundle()
    except BaseException as exc:
        model_replica = {
            "schema_version": "1.0",
            "status": "error",
            "started_at": utc_now(),
            "finished_at": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "partial_runtime_revision": directory_probe(RUNTIME_REVISION),
            "partial_recognition_model": directory_probe(RECOGNITION_MODEL),
        }
        write_json_new(OUTPUT_DIR / "model_replica_001.json", model_replica)
        write_json_new(
            OUTPUT_DIR / "run_summary_001.json",
            {
                "schema_version": "1.0",
                "status": "blocked_model_replica",
                "model_replica": model_replica,
            },
        )
        return 1

    write_json_new(OUTPUT_DIR / "model_replica_001.json", model_replica)
    attempts: list[dict[str, Any]] = []
    for engine in ENGINES:
        attempt = run_worker_subprocess(engine)
        attempts.append(attempt)
        if attempt.get("status") == "success":
            break

    successful = next(
        (attempt for attempt in attempts if attempt.get("status") == "success"), None
    )
    summary = {
        "schema_version": "1.0",
        "status": "success" if successful else "all_inference_attempts_failed",
        "created_at": utc_now(),
        "input_image": str(INPUT_IMAGE),
        "input_transmitted": False,
        "enable_mkldnn": False,
        "packages": {
            "paddlepaddle": package_version("paddlepaddle"),
            "paddleocr": package_version("paddleocr"),
            "paddlex": package_version("paddlex"),
            "huggingface_hub": package_version("huggingface_hub"),
        },
        "models": {
            "detection": str(DETECTION_MODEL),
            "recognition": str(RECOGNITION_MODEL),
            "recognition_repository": RECOGNITION_REPO,
            "recognition_commit": RECOGNITION_COMMIT,
        },
        "attempts": attempts,
        "successful_attempt": successful,
    }
    write_json_new(OUTPUT_DIR / "run_summary_001.json", summary)
    return 0 if successful else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-all", action="store_true")
    parser.add_argument("--worker", choices=ENGINES)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.run_all:
        return run_all()
    parser.error("choose --run-all or --worker")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
