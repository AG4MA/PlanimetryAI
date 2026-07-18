from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ROOT = Path(__file__).resolve().parents[1]
ATOMIC_ROOT = MODULE_ROOT.parent
INPUT_MANIFEST = (
    ATOMIC_ROOT
    / "ocr_tiles"
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
    / "ocr_tiles_manifest.json"
)
DOCTR_RUNTIME = ATOMIC_ROOT / "ocr_doctr" / "runtime"
DOCTR_MODEL_CACHE = DOCTR_RUNTIME / "models" / "doctr"
MODEL_WEIGHT = DOCTR_MODEL_CACHE / "models" / "parseq-56125471.pt"
OUTPUT = (
    MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)
PREFLIGHT_PATH = OUTPUT / "preflight_manifest.json"
RAW_PATH = OUTPUT / "ocr_tile_doctr_raw.json"
CONTACT_SHEET_PATH = OUTPUT / "ocr_tile_doctr_contact_sheet.png"
RUNTIME_MANIFEST_PATH = OUTPUT / "runtime_manifest.json"
ERROR_PATH = OUTPUT / "error.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite immutable artifact: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def runtime_tree_fingerprint(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\n")
        file_count += 1
        byte_count += stat.st_size
    return {
        "root": root.relative_to(ATOMIC_ROOT).as_posix(),
        "file_count": file_count,
        "byte_count": byte_count,
        "path_size_mtime_sha256": digest.hexdigest(),
    }


def validate_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 33:
        raise ValueError(f"Expected exactly 33 OCR tile records, got {None if not isinstance(records, list) else len(records)}")
    ids = [record.get("candidate_id") for record in records]
    expected_ids = [f"TC-{index:03d}" for index in range(1, 34)]
    if ids != expected_ids:
        raise ValueError(f"Candidate ID/order mismatch: {ids}")
    for record in records:
        if not isinstance(record.get("abstained"), bool):
            raise ValueError(f"Missing verbatim boolean abstention for {record.get('candidate_id')}")
        tile = record.get("ocr_ready_tile")
        if not isinstance(tile, dict):
            raise ValueError(f"Missing OCR-ready tile object for {record['candidate_id']}")
        tile_path = ATOMIC_ROOT / str(tile.get("path", ""))
        if not tile_path.is_file():
            raise FileNotFoundError(f"OCR-ready tile missing for {record['candidate_id']}: {tile_path}")
        actual_hash = sha256_file(tile_path)
        if actual_hash != tile.get("sha256"):
            raise ValueError(
                f"OCR-ready tile hash mismatch for {record['candidate_id']}: "
                f"manifest={tile.get('sha256')} actual={actual_hash}"
            )
    return records


def escape_visible(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def render_contact_sheet(records: list[dict[str, Any]], predictions: list[tuple[str, float]]) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    columns = 3
    rows = math.ceil(len(records) / columns)
    card_width = 560
    card_height = 260
    title_height = 62
    sheet = Image.new("RGB", (columns * card_width, title_height + rows * card_height), "#e9edf2")
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
        text_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16)
        small_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    except OSError:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    draw.text((16, 10), "docTR PARSeq recognition-only | 33 OCR-ready tiles | raw, unfiltered", fill="#111827", font=title_font)
    draw.text(
        (16, 38),
        "header red = original geometric abstention; green = originally non-abstained",
        fill="#374151",
        font=small_font,
    )

    for index, (record, prediction) in enumerate(zip(records, predictions, strict=True)):
        column = index % columns
        row = index // columns
        left = column * card_width + 6
        top = title_height + row * card_height + 6
        right = left + card_width - 12
        bottom = top + card_height - 12
        draw.rounded_rectangle((left, top, right, bottom), radius=8, fill="white", outline="#94a3b8", width=1)
        header_color = "#b91c1c" if record["abstained"] else "#047857"
        draw.rounded_rectangle((left, top, right, top + 58), radius=8, fill=header_color)
        draw.rectangle((left, top + 48, right, top + 58), fill=header_color)
        raw_text, confidence = prediction
        visible_prediction = escape_visible(raw_text)
        if len(visible_prediction) > 58:
            visible_prediction = visible_prediction[:55] + "..."
        draw.text(
            (left + 10, top + 6),
            f"{record['candidate_id']}  original_abstained={str(record['abstained']).lower()}",
            fill="white",
            font=text_font,
        )
        draw.text(
            (left + 10, top + 31),
            f"raw={visible_prediction!r}  conf={confidence:.6f}",
            fill="white",
            font=small_font,
        )

        tile_path = ATOMIC_ROOT / record["ocr_ready_tile"]["path"]
        tile = Image.open(tile_path).convert("RGB")
        preview = ImageOps.contain(tile, (card_width - 34, card_height - 84), Image.Resampling.LANCZOS)
        preview_left = left + (card_width - 12 - preview.width) // 2
        preview_top = top + 68 + (card_height - 78 - preview.height) // 2
        draw.rectangle(
            (preview_left - 1, preview_top - 1, preview_left + preview.width, preview_top + preview.height),
            outline="#cbd5e1",
            width=1,
        )
        sheet.paste(preview, (preview_left, preview_top))

    if CONTACT_SHEET_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite immutable artifact: {CONTACT_SHEET_PATH}")
    sheet.save(CONTACT_SHEET_PATH, format="PNG", optimize=False)


def run() -> None:
    started_at = utc_now()
    total_start = time.perf_counter()
    OUTPUT.mkdir(parents=True, exist_ok=False)

    try:
        if not INPUT_MANIFEST.is_file():
            raise FileNotFoundError(f"Input tile manifest missing: {INPUT_MANIFEST}")
        if not MODEL_WEIGHT.is_file():
            raise FileNotFoundError(f"Local PARSeq weight missing: {MODEL_WEIGHT}")

        input_manifest_hash = sha256_file(INPUT_MANIFEST)
        model_hash_before = sha256_file(MODEL_WEIGHT)
        runtime_before = runtime_tree_fingerprint(DOCTR_RUNTIME)
        input_manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
        records = validate_inputs(input_manifest)

        preflight = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.preflight.v1",
            "status": "preflight_completed_before_model_load",
            "created_at_utc": utc_now(),
            "input": {
                "manifest_path": INPUT_MANIFEST.relative_to(ATOMIC_ROOT).as_posix(),
                "manifest_sha256": input_manifest_hash,
                "candidate_count": len(records),
                "candidate_ids": [record["candidate_id"] for record in records],
                "ocr_ready_tiles_verified_by_sha256": len(records),
                "original_abstained_count": sum(record["abstained"] for record in records),
                "original_non_abstained_count": sum(not record["abstained"] for record in records),
            },
            "planned_engine": {
                "name": "docTR",
                "architecture": "parseq",
                "mode": "recognition_only",
                "device": "cpu",
                "pretrained_weight_path": MODEL_WEIGHT.relative_to(ATOMIC_ROOT).as_posix(),
                "pretrained_weight_sha256": model_hash_before,
                "model_loading": "direct_local_state_dict; pretrained=False factory; no downloader call",
                "network_required": False,
            },
            "immutability": {
                "existing_runtime_access": "read_only",
                "runtime_tree_before": runtime_before,
                "new_output_namespace": OUTPUT.relative_to(ATOMIC_ROOT).as_posix(),
            },
        }
        write_json_once(PREFLIGHT_PATH, preflight)
        print(f"PREFLIGHT_WRITTEN {PREFLIGHT_PATH}", flush=True)

        os.environ["DOCTR_CACHE_DIR"] = str(DOCTR_MODEL_CACHE)
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.dont_write_bytecode = True

        import numpy as np
        import torch
        from doctr.models import parseq, recognition_predictor
        from PIL import Image

        torch.set_grad_enabled(False)
        torch.set_num_threads(min(8, max(1, os.cpu_count() or 1)))

        model_load_start = time.perf_counter()
        model = parseq(pretrained=False)
        state_dict = torch.load(MODEL_WEIGHT, map_location="cpu", weights_only=True)
        model.load_state_dict(state_dict, strict=True)
        model = model.eval().to(torch.device("cpu"))
        predictor = recognition_predictor(
            arch=model,
            pretrained=False,
            symmetric_pad=True,
            batch_size=16,
        ).eval().to(torch.device("cpu"))
        model_load_ms = (time.perf_counter() - model_load_start) * 1000
        print(f"MODEL_LOADED_MS {model_load_ms:.3f}", flush=True)

        image_load_start = time.perf_counter()
        crops: list[np.ndarray] = []
        actual_tile_details: list[dict[str, Any]] = []
        for record in records:
            tile_path = ATOMIC_ROOT / record["ocr_ready_tile"]["path"]
            with Image.open(tile_path) as source_image:
                image = source_image.convert("RGB")
                crops.append(np.asarray(image).copy())
                actual_tile_details.append(
                    {
                        "path": tile_path.relative_to(ATOMIC_ROOT).as_posix(),
                        "sha256": sha256_file(tile_path),
                        "width_px": image.width,
                        "height_px": image.height,
                        "mode_used": image.mode,
                    }
                )
        image_load_ms = (time.perf_counter() - image_load_start) * 1000

        inference_start = time.perf_counter()
        with torch.inference_mode():
            predictions = predictor(crops)
        inference_ms = (time.perf_counter() - inference_start) * 1000
        if len(predictions) != len(records):
            raise RuntimeError(
                f"Recognition-only output is not one-to-one: predictions={len(predictions)} inputs={len(records)}"
            )
        normalized_predictions: list[tuple[str, float]] = []
        for index, prediction in enumerate(predictions):
            if not isinstance(prediction, (tuple, list)) or len(prediction) != 2:
                raise TypeError(f"Invalid PARSeq prediction at index {index}: {prediction!r}")
            raw_text = str(prediction[0])
            confidence = float(prediction[1])
            normalized_predictions.append((raw_text, confidence))
        print(f"INFERENCE_COMPLETED_MS {inference_ms:.3f}", flush=True)

        result_records: list[dict[str, Any]] = []
        for input_record, tile_detail, prediction in zip(
            records,
            actual_tile_details,
            normalized_predictions,
            strict=True,
        ):
            raw_text, confidence = prediction
            result_records.append(
                {
                    "candidate_id": input_record["candidate_id"],
                    "sheet_index": input_record["sheet_index"],
                    "status": "completed",
                    "input_candidate_state": {
                        "abstained": input_record["abstained"],
                        "abstention_preservation": "verbatim_from_ocr_tiles_manifest",
                        "input_confidence_geometry": input_record["input_confidence_geometry"],
                        "input_candidate_record_sha256": input_record["input_candidate_record_sha256"],
                    },
                    "input_tile": tile_detail,
                    "raw_prediction": {
                        "text": raw_text,
                        "confidence": confidence,
                        "retained_unfiltered": True,
                    },
                    "derived_abstention_applied": False,
                    "text_correction_applied": False,
                    "semantic_assignment_applied": False,
                }
            )

        raw_payload = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.raw.v1",
            "status": "completed",
            "created_at_utc": utc_now(),
            "component": "ocr_tile_doctr",
            "revision": "revision_001",
            "input": {
                "manifest_path": INPUT_MANIFEST.relative_to(ATOMIC_ROOT).as_posix(),
                "manifest_sha256": input_manifest_hash,
                "tile_variant": "ocr_ready_4x",
                "count": len(records),
            },
            "engine": {
                "name": "docTR",
                "distribution": "python-doctr",
                "version": package_version("python-doctr"),
                "backend": "PyTorch",
                "torch_version": torch.__version__,
                "architecture": "parseq",
                "mode": "recognition_only",
                "device": "cpu",
                "model_weight_path": MODEL_WEIGHT.relative_to(ATOMIC_ROOT).as_posix(),
                "model_weight_sha256": model_hash_before,
                "split_wide_crops": True,
                "symmetric_pad": True,
                "batch_size": 16,
            },
            "policy": {
                "raw_predictions_retained_unfiltered": True,
                "original_abstention_state_preserved": True,
                "derived_abstention_applied": False,
                "text_correction_applied": False,
                "semantic_assignment_applied": False,
            },
            "counts": {
                "input_tiles": len(records),
                "predictions": len(result_records),
                "original_abstained": sum(record["abstained"] for record in records),
                "original_non_abstained": sum(not record["abstained"] for record in records),
                "empty_raw_predictions": sum(not record["raw_prediction"]["text"] for record in result_records),
            },
            "timings_ms": {
                "model_load": round(model_load_ms, 3),
                "image_load_and_hash": round(image_load_ms, 3),
                "recognition_batch": round(inference_ms, 3),
                "recognition_mean_per_input": round(inference_ms / len(records), 3),
            },
            "records": result_records,
            "limits": [
                "raw_model_confidence_is_not_calibrated_for_floorplans",
                "context_tiles_can_contain_non_text_graphics_or_more_than_one_text_fragment",
                "recognition_only_does_not_validate_geometric_candidate_quality",
                "no_ground_truth_accuracy_claim",
                "no_text_correction_filtering_or_semantic_interpretation",
            ],
        }
        write_json_once(RAW_PATH, raw_payload)

        contact_start = time.perf_counter()
        render_contact_sheet(records, normalized_predictions)
        contact_sheet_ms = (time.perf_counter() - contact_start) * 1000

        model_hash_after = sha256_file(MODEL_WEIGHT)
        runtime_after = runtime_tree_fingerprint(DOCTR_RUNTIME)
        if model_hash_before != model_hash_after:
            raise RuntimeError("Existing PARSeq model weight content changed during inference")
        if runtime_before != runtime_after:
            raise RuntimeError("Existing docTR runtime tree changed during recognition-only inference")

        total_before_manifest_ms = (time.perf_counter() - total_start) * 1000
        runtime_manifest = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.runtime.v1",
            "status": "completed",
            "started_at_utc": started_at,
            "completed_at_utc": utc_now(),
            "runtime": {
                "python": sys.version,
                "python_executable": Path(sys.executable).relative_to(ATOMIC_ROOT).as_posix(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "packages": {
                    "python-doctr": package_version("python-doctr"),
                    "torch": package_version("torch"),
                    "numpy": package_version("numpy"),
                    "Pillow": package_version("Pillow"),
                },
                "torch_cuda_available": torch.cuda.is_available(),
                "torch_num_threads": torch.get_num_threads(),
            },
            "immutability": {
                "existing_runtime_access": "read_only",
                "runtime_tree_before": runtime_before,
                "runtime_tree_after": runtime_after,
                "runtime_tree_unchanged": True,
                "model_weight_sha256_before": model_hash_before,
                "model_weight_sha256_after": model_hash_after,
                "model_weight_unchanged": True,
            },
            "outputs": {
                "preflight_manifest.json": sha256_file(PREFLIGHT_PATH),
                "ocr_tile_doctr_raw.json": sha256_file(RAW_PATH),
                "ocr_tile_doctr_contact_sheet.png": sha256_file(CONTACT_SHEET_PATH),
            },
            "counts": raw_payload["counts"],
            "timings_ms": {
                **raw_payload["timings_ms"],
                "contact_sheet_render": round(contact_sheet_ms, 3),
                "total_before_runtime_manifest_write": round(total_before_manifest_ms, 3),
            },
            "runner": {
                "path": Path(__file__).relative_to(ATOMIC_ROOT).as_posix(),
                "sha256": sha256_file(Path(__file__)),
            },
            "limits": raw_payload["limits"],
        }
        write_json_once(RUNTIME_MANIFEST_PATH, runtime_manifest)
        print(f"ARTIFACTS_COMPLETED {OUTPUT}", flush=True)
    except Exception as exc:
        error_payload = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.error.v1",
            "status": "failed",
            "started_at_utc": started_at,
            "failed_at_utc": utc_now(),
            "stage": "preflight_or_local_model_load_or_recognition_or_artifact_write",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "recognition_only_technically_valid": False,
            "existing_inputs_modified": False,
        }
        if not ERROR_PATH.exists():
            write_json_once(ERROR_PATH, error_payload)
        raise


if __name__ == "__main__":
    run()
