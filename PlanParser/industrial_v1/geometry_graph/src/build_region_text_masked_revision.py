from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import build_region_revision as base
import geometry_graph as graph


def write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def render_overlay(
    crop_path: Path,
    output_path: Path,
    segments: list[graph.Segment],
    payload: dict,
    revision_label: str,
) -> None:
    gray = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError(f"Cannot read crop image: {crop_path}")
    canvas = cv2.addWeighted(
        cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
        0.68,
        np.full((*gray.shape, 3), 255, dtype=np.uint8),
        0.32,
        0,
    )
    for segment in segments:
        cv2.line(
            canvas,
            (round(segment.start.x), round(segment.start.y)),
            (round(segment.end.x), round(segment.end.y)),
            (165, 165, 165),
            1,
            cv2.LINE_AA,
        )
    colors = {
        "crossing": (30, 190, 30),
        "endpoint_to_interior": (0, 155, 255),
        "endpoint_to_endpoint": (235, 80, 50),
        "mixed": (180, 45, 210),
    }
    for node in payload["nodes"]:
        x, y = (round(value) for value in node["coordinate_crop_px"])
        color = colors.get(node["geometric_class"], colors["mixed"])
        cv2.circle(canvas, (x, y), 6 if node["abstained"] else 4, color, 1 if node["abstained"] else -1, cv2.LINE_AA)
        if node["abstained"]:
            cv2.circle(canvas, (x, y), 2, color, -1, cv2.LINE_AA)

    enlarged = cv2.copyMakeBorder(canvas, 122, 30, 30, 30, cv2.BORDER_CONSTANT, value=(250, 250, 250))
    cv2.putText(
        enlarged,
        f"GEOMETRY GRAPH {revision_label} - OCR text separato; nessuna semantica edilizia",
        (30, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (30, 30, 30),
        1,
        cv2.LINE_AA,
    )
    entries = [
        ("crossing", colors["crossing"], False),
        ("endpoint-interior", colors["endpoint_to_interior"], False),
        ("endpoint-endpoint", colors["endpoint_to_endpoint"], False),
        ("astensione/mixed/near", colors["mixed"], True),
    ]
    x_cursor = 30
    for label, color, hollow in entries:
        cv2.circle(enlarged, (x_cursor + 6, 55), 5, color, 1 if hollow else -1, cv2.LINE_AA)
        cv2.putText(enlarged, label, (x_cursor + 17, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (45, 45, 45), 1, cv2.LINE_AA)
        x_cursor += 170
    summary = payload["summary"]
    cv2.putText(
        enlarged,
        (
            f"segmenti geometrici={summary['raw_segment_count']}  nodi={summary['node_count']}  "
            f"glyph esclusi={summary['text_contaminated_segments_removed_upstream']}  "
            f"nodi testo separati={summary['text_node_count']}"
        ),
        (30, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.47,
        (35, 35, 35),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        enlarged,
        "I nodi geometrici non sono muri/porte; i nodi testo restano nel ramo OCR per il futuro grafo testo-spazio-frontiera.",
        (30, 110),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.37,
        (60, 60, 60),
        1,
        cv2.LINE_AA,
    )
    success, encoded = cv2.imencode(".png", enlarged)
    if not success:
        raise RuntimeError("PNG encoding failed")
    write_bytes_exclusive(output_path, encoded.tobytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a geometry graph from OCR-masked linework.")
    parser.add_argument("--linework", type=Path, required=True)
    parser.add_argument("--crop", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--revision-label", default="r002")
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

    payload, segments, bbox = base.build_payload(
        linework_path=args.linework,
        crop_path=args.crop,
        regions_path=args.regions,
        region_id=args.region_id,
        near_tolerance_px=args.near_tolerance,
        endpoint_tolerance_px=args.endpoint_tolerance,
        parallel_angle_tolerance_deg=args.parallel_angle_tolerance,
    )
    upstream = json.loads(args.linework.read_text(encoding="utf-8"))
    if not upstream.get("scope", {}).get("text_and_linework_kept_as_separate_node_sets"):
        raise ValueError("Input linework does not certify text/linework separation")
    text_nodes = upstream.get("text_nodes", [])
    removed = upstream.get("text_contaminated_candidates", [])
    payload["schema_version"] = "1.1.0"
    payload["scope"]["text_geometry_separation_claimed"] = True
    payload["scope"]["ocr_exhaustiveness_claimed"] = False
    payload["summary"]["text_node_count"] = len(text_nodes)
    payload["summary"]["text_contaminated_segments_removed_upstream"] = len(removed)
    payload["text_node_branch"] = {
        "source_linework_path": str(args.linework).replace("\\", "/"),
        "source_linework_sha256": base.sha256_file(args.linework),
        "text_node_ids": [node["text_node_id"] for node in text_nodes],
        "future_relation_target": "text_node_to_space_to_frontier",
        "assignment_performed": False,
    }
    payload["upstream_text_contamination_audit"] = upstream.get("summary", {})

    base.write_json_exclusive(args.output_json, payload)
    render_overlay(args.crop, args.output_overlay, segments, payload, args.revision_label)
    manifest = {
        "schema_version": "planparser.industrial_v1.geometry_graph.artifact_manifest.v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "region_id": args.region_id,
        "crop_bbox_in_source_page_px": bbox,
        "source": {"path": str(args.crop).replace("\\", "/"), "sha256": base.sha256_file(args.crop)},
        "inputs": {
            "linework": {"path": str(args.linework).replace("\\", "/"), "sha256": base.sha256_file(args.linework)},
            "regions": {"path": str(args.regions).replace("\\", "/"), "sha256": base.sha256_file(args.regions)},
        },
        "outputs": {
            args.output_json.name: base.sha256_file(args.output_json),
            args.output_overlay.name: base.sha256_file(args.output_overlay),
        },
        "summary": payload["summary"],
        "limits": [
            "OCR text and geometric nodes remain separate",
            "OCR misses can leave glyph contamination",
            "no text-to-space assignment yet",
            "no building semantics",
        ],
    }
    base.write_json_exclusive(args.output_manifest, manifest)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
