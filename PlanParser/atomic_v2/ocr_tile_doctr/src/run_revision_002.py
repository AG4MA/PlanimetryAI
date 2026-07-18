from __future__ import annotations

import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import run_revision_001 as base


OUTPUT = (
    base.MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_002"
)
PREFLIGHT_PATH = OUTPUT / "preflight_manifest.json"
RAW_PATH = OUTPUT / "ocr_tile_doctr_raw.json"
CONTACT_SHEET_PATH = OUTPUT / "ocr_tile_doctr_contact_sheet.png"
RUNTIME_MANIFEST_PATH = OUTPUT / "runtime_manifest.json"
ERROR_PATH = OUTPUT / "error.json"
PREDECESSOR_ERROR = (
    base.MODULE_ROOT
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
    / "error.json"
)


def run() -> None:
    started_at = base.utc_now()
    total_start = time.perf_counter()
    OUTPUT.mkdir(parents=True, exist_ok=False)

    try:
        if not base.INPUT_MANIFEST.is_file():
            raise FileNotFoundError(f"Input tile manifest missing: {base.INPUT_MANIFEST}")
        if not base.MODEL_WEIGHT.is_file():
            raise FileNotFoundError(f"Local PARSeq weight missing: {base.MODEL_WEIGHT}")
        if not PREDECESSOR_ERROR.is_file():
            raise FileNotFoundError(f"Expected immutable predecessor error missing: {PREDECESSOR_ERROR}")

        input_manifest_hash = base.sha256_file(base.INPUT_MANIFEST)
        model_hash_before = base.sha256_file(base.MODEL_WEIGHT)
        runtime_before = base.runtime_tree_fingerprint(base.DOCTR_RUNTIME)
        input_manifest = json.loads(base.INPUT_MANIFEST.read_text(encoding="utf-8"))
        records = base.validate_inputs(input_manifest)

        preflight = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.preflight.v2",
            "status": "preflight_completed_before_model_load",
            "created_at_utc": base.utc_now(),
            "revision": "revision_002",
            "predecessor": {
                "revision": "revision_001",
                "status": "failed_immutable",
                "error_path": PREDECESSOR_ERROR.relative_to(base.ATOMIC_ROOT).as_posix(),
                "error_sha256": base.sha256_file(PREDECESSOR_ERROR),
                "correction": "use_PARSeq.from_pretrained_with_local_path_for_legacy_key_compatibility",
            },
            "input": {
                "manifest_path": base.INPUT_MANIFEST.relative_to(base.ATOMIC_ROOT).as_posix(),
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
                "pretrained_weight_path": base.MODEL_WEIGHT.relative_to(base.ATOMIC_ROOT).as_posix(),
                "pretrained_weight_sha256": model_hash_before,
                "model_loading": "PARSeq.from_pretrained(local_path); built-in legacy-key compatibility; no downloader call",
                "network_required": False,
            },
            "immutability": {
                "existing_runtime_access": "read_only",
                "runtime_tree_before": runtime_before,
                "new_output_namespace": OUTPUT.relative_to(base.ATOMIC_ROOT).as_posix(),
            },
        }
        base.write_json_once(PREFLIGHT_PATH, preflight)
        print(f"PREFLIGHT_WRITTEN {PREFLIGHT_PATH}", flush=True)

        os.environ["DOCTR_CACHE_DIR"] = str(base.DOCTR_MODEL_CACHE)
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
        model.from_pretrained(str(base.MODEL_WEIGHT))
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
            tile_path = base.ATOMIC_ROOT / record["ocr_ready_tile"]["path"]
            with Image.open(tile_path) as source_image:
                image = source_image.convert("RGB")
                crops.append(np.asarray(image).copy())
                actual_tile_details.append(
                    {
                        "path": tile_path.relative_to(base.ATOMIC_ROOT).as_posix(),
                        "sha256": base.sha256_file(tile_path),
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
            normalized_predictions.append((str(prediction[0]), float(prediction[1])))
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
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.raw.v2",
            "status": "completed",
            "created_at_utc": base.utc_now(),
            "component": "ocr_tile_doctr",
            "revision": "revision_002",
            "predecessor_revision": "revision_001_failed_immutable",
            "input": {
                "manifest_path": base.INPUT_MANIFEST.relative_to(base.ATOMIC_ROOT).as_posix(),
                "manifest_sha256": input_manifest_hash,
                "tile_variant": "ocr_ready_4x",
                "count": len(records),
            },
            "engine": {
                "name": "docTR",
                "distribution": "python-doctr",
                "version": base.package_version("python-doctr"),
                "backend": "PyTorch",
                "torch_version": torch.__version__,
                "architecture": "parseq",
                "mode": "recognition_only",
                "device": "cpu",
                "model_weight_path": base.MODEL_WEIGHT.relative_to(base.ATOMIC_ROOT).as_posix(),
                "model_weight_sha256": model_hash_before,
                "model_local_legacy_compatibility_loader": True,
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
        base.write_json_once(RAW_PATH, raw_payload)

        contact_start = time.perf_counter()
        base.CONTACT_SHEET_PATH = CONTACT_SHEET_PATH
        base.render_contact_sheet(records, normalized_predictions)
        contact_sheet_ms = (time.perf_counter() - contact_start) * 1000

        model_hash_after = base.sha256_file(base.MODEL_WEIGHT)
        runtime_after = base.runtime_tree_fingerprint(base.DOCTR_RUNTIME)
        if model_hash_before != model_hash_after:
            raise RuntimeError("Existing PARSeq model weight content changed during inference")
        if runtime_before != runtime_after:
            raise RuntimeError("Existing docTR runtime tree changed during recognition-only inference")

        total_before_manifest_ms = (time.perf_counter() - total_start) * 1000
        runtime_manifest = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.runtime.v2",
            "status": "completed",
            "started_at_utc": started_at,
            "completed_at_utc": base.utc_now(),
            "runtime": {
                "python": sys.version,
                "python_executable": Path(sys.executable).relative_to(base.ATOMIC_ROOT).as_posix(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "packages": {
                    "python-doctr": base.package_version("python-doctr"),
                    "torch": base.package_version("torch"),
                    "numpy": base.package_version("numpy"),
                    "Pillow": base.package_version("Pillow"),
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
                "preflight_manifest.json": base.sha256_file(PREFLIGHT_PATH),
                "ocr_tile_doctr_raw.json": base.sha256_file(RAW_PATH),
                "ocr_tile_doctr_contact_sheet.png": base.sha256_file(CONTACT_SHEET_PATH),
            },
            "counts": raw_payload["counts"],
            "timings_ms": {
                **raw_payload["timings_ms"],
                "contact_sheet_render": round(contact_sheet_ms, 3),
                "total_before_runtime_manifest_write": round(total_before_manifest_ms, 3),
            },
            "runner": {
                "path": Path(__file__).relative_to(base.ATOMIC_ROOT).as_posix(),
                "sha256": base.sha256_file(Path(__file__)),
            },
            "limits": raw_payload["limits"],
        }
        base.write_json_once(RUNTIME_MANIFEST_PATH, runtime_manifest)
        print(f"ARTIFACTS_COMPLETED {OUTPUT}", flush=True)
    except Exception as exc:
        error_payload = {
            "schema_version": "planparser.atomic_v2.ocr_tile_doctr.error.v2",
            "status": "failed",
            "started_at_utc": started_at,
            "failed_at_utc": base.utc_now(),
            "stage": "preflight_or_local_compatible_model_load_or_recognition_or_artifact_write",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "existing_inputs_modified": False,
        }
        if not ERROR_PATH.exists():
            base.write_json_once(ERROR_PATH, error_payload)
        raise


if __name__ == "__main__":
    run()
