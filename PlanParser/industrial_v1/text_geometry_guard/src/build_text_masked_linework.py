from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    write_bytes_exclusive(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def encode_png(image) -> bytes:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("PNG encoding failed")
    return encoded.tobytes()


def expanded_bbox(box: list[int], padding: int, width: int, height: int) -> list[int]:
    x0, y0, x1, y1 = (int(value) for value in box)
    return [
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(width - 1, x1 + padding),
        min(height - 1, y1 + padding),
    ]


def overlap_audit(candidate: dict[str, Any], text_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    (x1, y1), (x2, y2) = candidate["points_px"]
    sample_count = max(abs(int(x2) - int(x1)), abs(int(y2) - int(y1))) + 1
    hit_count = 0
    node_hits: set[str] = set()
    for index in range(sample_count):
        t = 0.0 if sample_count == 1 else index / (sample_count - 1)
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        matched = False
        for node in text_nodes:
            left, top, right, bottom = node["mask_bbox_crop_px"]
            if left <= x <= right and top <= y <= bottom:
                node_hits.add(node["text_node_id"])
                matched = True
        hit_count += int(matched)
    return {
        "sample_count": sample_count,
        "samples_inside_text_mask": hit_count,
        "text_overlap_ratio": round(hit_count / max(1, sample_count), 6),
        "overlapping_text_node_ids": sorted(node_hits),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Separate OCR-supported glyph strokes from geometric linework candidates."
    )
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--linework", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--page-offset-x", type=int, required=True)
    parser.add_argument("--page-offset-y", type=int, required=True)
    parser.add_argument("--mask-padding", type=int, default=3)
    parser.add_argument("--exclude-overlap-ratio", type=float, default=0.50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite immutable revision: {args.output_dir}")

    image = cv2.imread(str(args.crop), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Cannot read crop: {args.crop}")
    height, width = image.shape[:2]
    linework = json.loads(args.linework.read_text(encoding="utf-8"))
    ocr = json.loads(args.ocr.read_text(encoding="utf-8"))
    crop_hash = sha256_file(args.crop)
    if linework.get("provenance", {}).get("source_sha256") != crop_hash:
        raise ValueError("Linework and crop hashes do not match")
    if ocr.get("source", {}).get("sha256") != crop_hash:
        raise ValueError("OCR and crop hashes do not match")

    text_nodes: list[dict[str, Any]] = []
    for index, word in enumerate(ocr.get("words", []), 1):
        box = [int(value) for value in word["bbox_pixels"]]
        mask_box = expanded_bbox(box, args.mask_padding, width, height)
        text_nodes.append(
            {
                "text_node_id": f"text_{index:04d}",
                "ocr_word_id": word["id"],
                "text_raw": word.get("text_raw", ""),
                "recognition_confidence_raw": word.get("confidence_raw"),
                "abstained": bool(word.get("abstention", {}).get("abstained", False)),
                "bbox_crop_px": box,
                "bbox_source_page_px": [
                    box[0] + args.page_offset_x,
                    box[1] + args.page_offset_y,
                    box[2] + args.page_offset_x,
                    box[3] + args.page_offset_y,
                ],
                "mask_bbox_crop_px": mask_box,
            }
        )

    retained: list[dict[str, Any]] = []
    contaminated: list[dict[str, Any]] = []
    for candidate in linework.get("candidates", []):
        audit = overlap_audit(candidate, text_nodes)
        annotated = {**candidate, "text_overlap_audit": audit}
        if audit["text_overlap_ratio"] >= args.exclude_overlap_ratio:
            annotated["exclusion_reason"] = "segment_supported_inside_ocr_text_mask"
            contaminated.append(annotated)
        else:
            retained.append(annotated)

    input_length = sum(float(item.get("length_px", 0.0)) for item in linework.get("candidates", []))
    excluded_length = sum(float(item.get("length_px", 0.0)) for item in contaminated)
    summary = {
        "input_candidate_count": len(linework.get("candidates", [])),
        "retained_geometric_candidate_count": len(retained),
        "text_contaminated_candidate_count": len(contaminated),
        "text_contaminated_candidate_ratio": round(
            len(contaminated) / max(1, len(linework.get("candidates", []))), 6
        ),
        "input_candidate_length_px": round(input_length, 3),
        "excluded_text_candidate_length_px": round(excluded_length, 3),
        "excluded_text_candidate_length_ratio": round(excluded_length / max(1.0, input_length), 6),
        "ocr_text_node_count": len(text_nodes),
    }
    payload = {
        "schema_version": "planparser.atomic_v2.linework.text_masked.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "region_id": args.region_id,
        "image": {"width_px": width, "height_px": height},
        "coordinate_systems": {
            "crop_px": {"origin": f"{args.region_id}_top_left", "x_axis": "right", "y_axis": "down"},
            "source_page_px": {"origin": "page_0001_top_left", "x_axis": "right", "y_axis": "down"},
            "crop_offset_in_source_page_px": [args.page_offset_x, args.page_offset_y],
        },
        "provenance": {
            "source_path": str(args.crop).replace("\\", "/"),
            "source_sha256": crop_hash,
            "source_linework": str(args.linework).replace("\\", "/"),
            "source_linework_sha256": sha256_file(args.linework),
            "source_ocr": str(args.ocr).replace("\\", "/"),
            "source_ocr_sha256": sha256_file(args.ocr),
            "detector": "axis-aligned-hough-linework-plus-ocr-text-guard",
            "detector_version": "2.0.0",
        },
        "parameters": {
            "text_mask_padding_px": args.mask_padding,
            "candidate_exclusion_minimum_text_overlap_ratio": args.exclude_overlap_ratio,
            "overlap_sampling_interval_px": 1,
        },
        "summary": summary,
        "text_nodes": text_nodes,
        "candidates": retained,
        "text_contaminated_candidates": contaminated,
        "scope": {
            "text_and_linework_kept_as_separate_node_sets": True,
            "text_transcription_is_raw_ocr_observation": True,
            "building_semantics_emitted": False,
            "ocr_exhaustiveness_claimed": False,
        },
        "excluded_inferences": [
            "walls",
            "rooms",
            "openings",
            "adjacency",
            "scale",
            "text_to_space_assignment",
        ],
    }

    masked = image.copy()
    for node in text_nodes:
        left, top, right, bottom = node["mask_bbox_crop_px"]
        cv2.rectangle(masked, (left, top), (right, bottom), (255, 255, 255), -1)

    overlay = image.copy()
    for candidate in retained:
        p1, p2 = (tuple(int(value) for value in point) for point in candidate["points_px"])
        color = (0, 0, 220) if candidate.get("status") == "solid" else (0, 150, 255)
        cv2.line(overlay, p1, p2, color, 2 if candidate.get("status") == "solid" else 1, cv2.LINE_AA)
    for candidate in contaminated:
        p1, p2 = (tuple(int(value) for value in point) for point in candidate["points_px"])
        cv2.line(overlay, p1, p2, (210, 0, 210), 3, cv2.LINE_AA)
    for node in text_nodes:
        left, top, right, bottom = node["mask_bbox_crop_px"]
        cv2.rectangle(overlay, (left, top), (right, bottom), (255, 90, 0), 1, cv2.LINE_AA)
        cv2.putText(
            overlay,
            node["text_node_id"].replace("text_", "T"),
            (left, max(50, top - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.32,
            (255, 90, 0),
            1,
            cv2.LINE_AA,
        )
    cv2.rectangle(overlay, (0, 0), (width - 1, 46), (255, 255, 255), -1)
    cv2.putText(
        overlay,
        (
            f"TEXT/LINEWORK GUARD retained={len(retained)}  "
            f"glyph-segments={len(contaminated)}  OCR-text-nodes={len(text_nodes)}"
        ),
        (7, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )

    args.output_dir.mkdir(parents=True, exist_ok=False)
    json_path = args.output_dir / "linework.json"
    overlay_path = args.output_dir / "linework_overlay.png"
    masked_path = args.output_dir / "text_masked_crop.png"
    manifest_path = args.output_dir / "artifact_manifest.json"
    write_json_exclusive(json_path, payload)
    write_bytes_exclusive(overlay_path, encode_png(overlay))
    write_bytes_exclusive(masked_path, encode_png(masked))
    manifest = {
        "schema_version": "planparser.atomic_v2.linework.artifact_manifest.v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "region_id": args.region_id,
        "source_sha256": crop_hash,
        "outputs": {
            json_path.name: sha256_file(json_path),
            overlay_path.name: sha256_file(overlay_path),
            masked_path.name: sha256_file(masked_path),
        },
        "summary": summary,
        "limits": [
            "OCR-supported text strokes removed from downstream linework",
            "OCR misses can leave residual glyph strokes",
            "text nodes preserved for future text-to-space graph",
        ],
    }
    write_json_exclusive(manifest_path, manifest)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
