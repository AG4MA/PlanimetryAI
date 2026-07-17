from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

import geometry_graph as graph


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def build_payload(
    *,
    linework_path: Path,
    crop_path: Path,
    regions_path: Path,
    region_id: str,
    near_tolerance_px: float,
    endpoint_tolerance_px: float,
    parallel_angle_tolerance_deg: float,
) -> tuple[dict[str, Any], list[graph.Segment], list[int]]:
    linework_payload, segments = graph._load_segments(linework_path)
    regions_payload = json.loads(regions_path.read_text(encoding="utf-8"))
    selected = next(item for item in regions_payload["regions"] if item["id"] == region_id)
    bbox = [int(value) for value in selected["bbox_px"]]
    offset = (float(bbox[0]), float(bbox[1]))

    image = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Cannot read crop image: {crop_path}")
    height, width = image.shape
    if [width, height] != bbox[2:4]:
        raise ValueError(
            f"Crop dimensions {width}x{height} do not match {region_id} bbox {bbox[2]}x{bbox[3]}"
        )

    crop_hash = sha256_file(crop_path)
    upstream_crop_hash = linework_payload.get("provenance", {}).get("source_sha256")
    if upstream_crop_hash != crop_hash:
        raise ValueError("Linework provenance does not point to the exact source crop bytes")

    result = graph.analyze_segments(
        segments,
        near_tolerance_px=near_tolerance_px,
        endpoint_tolerance_px=endpoint_tolerance_px,
        parallel_angle_tolerance_deg=parallel_angle_tolerance_deg,
    )
    graph._add_source_coordinates(result, offset)
    counts = {
        "raw_segment_count": len(segments),
        "node_count": len(result["nodes"]),
        "exact_intersection_count": sum(
            item["kind"] == "exact_intersection" for item in result["junction_relations"]
        ),
        "near_junction_count": sum(
            item["kind"] == "near_junction" for item in result["junction_relations"]
        ),
        "collinear_overlap_count": len(result["overlap_relations"]),
        "parallel_pair_count": len(result["parallel_relations"]),
        "abstained_node_count": sum(item["abstained"] for item in result["nodes"]),
    }
    payload = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "region_id": region_id,
        "coordinate_systems": {
            "crop_px": {
                "origin": f"{region_id}_top_left",
                "x_axis": "right",
                "y_axis": "down",
            },
            "source_page_px": {
                "origin": "page_0001_top_left",
                "x_axis": "right",
                "y_axis": "down",
            },
            "crop_bbox_in_source_page_px": bbox,
            "crop_offset_in_source_page_px": [offset[0], offset[1]],
        },
        "provenance": {
            "source_crop": str(crop_path).replace("\\", "/"),
            "source_crop_sha256": crop_hash,
            "source_linework": str(linework_path).replace("\\", "/"),
            "source_linework_sha256": sha256_file(linework_path),
            "source_regions": str(regions_path).replace("\\", "/"),
            "source_regions_sha256": sha256_file(regions_path),
            "upstream_detector": linework_payload.get("provenance", {}),
            "engine": "nonsemantic-segment-relation-graph",
            "engine_version": "1.0.0",
        },
        "parameters": {
            "near_junction_tolerance_px": near_tolerance_px,
            "endpoint_classification_tolerance_px": endpoint_tolerance_px,
            "parallel_angle_tolerance_degrees": parallel_angle_tolerance_deg,
            "node_cluster_radius_px": 3.0,
        },
        "scope": {
            "observed_only": True,
            "semantic_labels_emitted": False,
            "text_geometry_separation_claimed": False,
            "explicitly_not_inferred": [
                "wall",
                "door",
                "window",
                "room",
                "property_boundary",
                "building_membership",
                "glyph_or_building_line",
            ],
        },
        "summary": counts,
        "raw_segments_preserved": [segment.raw for segment in segments],
        **result,
    }
    return payload, segments, bbox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build geometry graph for an explicit split region.")
    parser.add_argument("--linework", type=Path, required=True)
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-overlay", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--near-tolerance", type=float, default=8.0)
    parser.add_argument("--endpoint-tolerance", type=float, default=2.0)
    parser.add_argument("--parallel-angle-tolerance", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (args.output_json, args.output_overlay, args.output_manifest):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite immutable artifact: {path}")

    payload, segments, bbox = build_payload(
        linework_path=args.linework,
        crop_path=args.crop,
        regions_path=args.regions,
        region_id=args.region_id,
        near_tolerance_px=args.near_tolerance,
        endpoint_tolerance_px=args.endpoint_tolerance,
        parallel_angle_tolerance_deg=args.parallel_angle_tolerance,
    )
    write_json_exclusive(args.output_json, payload)
    graph.render_overlay(args.crop, args.output_overlay, segments, payload)
    manifest = {
        "schema_version": "planparser.industrial_v1.geometry_graph.artifact_manifest.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "region_id": args.region_id,
        "crop_bbox_in_source_page_px": bbox,
        "source": {
            "path": str(args.crop).replace("\\", "/"),
            "sha256": sha256_file(args.crop),
        },
        "inputs": {
            "linework": {
                "path": str(args.linework).replace("\\", "/"),
                "sha256": sha256_file(args.linework),
            },
            "regions": {
                "path": str(args.regions).replace("\\", "/"),
                "sha256": sha256_file(args.regions),
            },
        },
        "outputs": {
            args.output_json.name: sha256_file(args.output_json),
            args.output_overlay.name: sha256_file(args.output_overlay),
        },
        "summary": payload["summary"],
        "limits": [
            "no_building_semantics",
            "raw_revision_does_not_separate_text_glyphs_from_linework",
        ],
    }
    write_json_exclusive(args.output_manifest, manifest)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
