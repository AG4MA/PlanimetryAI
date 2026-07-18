"""Group every wall-band proposal into a non-semantic geometric network."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expanded_intersects(a: list[float], b: list[float], tolerance: float = 9) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + tolerance < bx or bx + bw + tolerance < ax
        or ay + ah + tolerance < by or by + bh + tolerance < ay
    )


def _components(bands: list[dict]) -> tuple[list[list[int]], dict[int, set[int]]]:
    graph = {i: set() for i in range(len(bands))}
    for i, first in enumerate(bands):
        for j in range(i + 1, len(bands)):
            second = bands[j]
            if _expanded_intersects(first["bbox_px"], second["bbox_px"]):
                graph[i].add(j)
                graph[j].add(i)
    components = []
    unseen = set(graph)
    while unseen:
        seed = min(unseen)
        stack, component = [seed], []
        unseen.remove(seed)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in graph[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return components, graph


def _component_record(component_id: str, indices: list[int], bands: list[dict]) -> dict:
    selected = [bands[i] for i in indices]
    xs = [b["bbox_px"][0] for b in selected]
    ys = [b["bbox_px"][1] for b in selected]
    x2s = [b["bbox_px"][0] + b["bbox_px"][2] for b in selected]
    y2s = [b["bbox_px"][1] + b["bbox_px"][3] for b in selected]
    orientations = sorted(set(b["orientation"] for b in selected))
    thicknesses = [float(b["observed_thickness_px"]) for b in selected]
    return {
        "id": component_id,
        "source_band_ids": [b["id"] for b in selected],
        "bbox_px": [min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)],
        "total_length_px": round(sum(float(b["length_px"]) for b in selected), 2),
        "member_count": len(selected),
        "orientations": orientations,
        "observed_thickness_median_px": round(statistics.median(thicknesses), 2),
        "observed_thickness_range_px": [min(thicknesses), max(thicknesses)],
    }


def build(bands: list[dict], width: int, height: int):
    components, graph = _components(bands)
    records = [_component_record(f"component_{i + 1:03d}", nodes, bands) for i, nodes in enumerate(components)]
    thickness_bins = Counter(round(float(b["observed_thickness_px"]) / 2) * 2 for b in bands if not b["abstained"])
    thickness_clusters = [
        {"center_px": center, "member_count": count}
        for center, count in sorted(thickness_bins.items(), key=lambda item: (-item[1], item[0]))
    ]
    for record, nodes in zip(records, components):
        span_x = record["bbox_px"][2] / width
        span_y = record["bbox_px"][3] / height
        has_both_axes = len(record["orientations"]) == 2
        primary_evidence = (
            record["member_count"] >= 3
            and has_both_axes
            and record["total_length_px"] >= 240
            and (span_x >= 0.16 or span_y >= 0.16)
        )
        record["network_evidence"] = {
            "spatial_span_ratio": [round(span_x, 3), round(span_y, 3)],
            "has_horizontal_and_vertical": has_both_axes,
            "connection_count": sum(len(graph[node]) for node in nodes) // 2,
        }
        record["primary_component"] = primary_evidence
        record["reasons"] = [
            f"connected component contains {record['member_count']} band(s)",
            f"total observed band length={record['total_length_px']}px",
            f"spatial span ratios x={span_x:.3f}, y={span_y:.3f}",
            "classification uses geometry only; semantic role not inferred",
        ]

    component_for_index = {}
    for record, nodes in zip(records, components):
        for node in nodes:
            component_for_index[node] = record
    members = []
    for index, band in enumerate(bands):
        component = component_for_index[index]
        if band["abstained"]:
            tier = "abstention"
            reasons = list(band["reasons"]) + ["source wall-band proposal was abstained"]
        elif component["primary_component"]:
            tier = "primary"
            reasons = list(component["reasons"]) + ["member retained in a spatially connected primary component"]
        else:
            tier = "secondary"
            reasons = list(component["reasons"]) + ["insufficient connected extent for primary tier"]
        members.append({
            "source_band_id": band["id"],
            "component_id": component["id"],
            "tier": tier,
            "polygon_px": band["polygon_px"],
            "bbox_px": band["bbox_px"],
            "observed_thickness_px": band["observed_thickness_px"],
            "length_px": band["length_px"],
            "confidence": band["confidence"],
            "reasons": reasons,
            "abstained": tier == "abstention",
        })
    return records, members, thickness_clusters


def run(source: Path, linework_path: Path, bands_path: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    linework = json.loads(linework_path.read_text(encoding="utf-8"))
    bands_payload = json.loads(bands_path.read_text(encoding="utf-8"))
    bands = bands_payload.get("candidates", [])
    height, width = image.shape[:2]
    components, members, clusters = build(bands, width, height)
    output_dir.mkdir(parents=True, exist_ok=False)
    overlay = image.copy()
    colors = {"primary": (0, 0, 230), "secondary": (220, 110, 0), "abstention": (200, 0, 200)}
    for member in members:
        points = np.array([(round(x), round(y)) for x, y in member["polygon_px"]], dtype=np.int32)
        cv2.polylines(overlay, [points], True, colors[member["tier"]], 2, cv2.LINE_AA)
    for component in components:
        x, y, _, _ = component["bbox_px"]
        cv2.putText(overlay, component["id"], (round(x), max(51, round(y) - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
    counts = Counter(member["tier"] for member in members)
    cv2.rectangle(overlay, (0, 0), (width - 1, 44), (255, 255, 255), -1)
    cv2.putText(overlay, f"GEOMETRIC NETWORK primary={counts['primary']} secondary={counts['secondary']} abstention={counts['abstention']}", (7, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.imwrite(str(output_dir / "wall_network_overlay.png"), overlay)
    payload = {
        "schema_version": "1.0.0",
        "provenance": {
            "source_crop": str(source).replace("\\", "/"),
            "source_crop_sha256": _sha256(source),
            "source_linework": str(linework_path).replace("\\", "/"),
            "source_linework_sha256": _sha256(linework_path),
            "source_wall_bands": str(bands_path).replace("\\", "/"),
            "source_wall_bands_sha256": _sha256(bands_path),
            "builder": "geometric-band-network",
            "builder_version": "1.0.0",
        },
        "summary": {
            "source_band_count": len(bands),
            "retained_member_count": len(members),
            "component_count": len(components),
            "primary_count": counts["primary"],
            "secondary_count": counts["secondary"],
            "abstention_count": counts["abstention"],
        },
        "observed_thickness_clusters": clusters,
        "components": components,
        "members": members,
        "excluded_inferences": ["walls", "rooms", "openings", "adjacency", "scale", "internal_or_external"],
    }
    result = output_dir / "wall_network.json"
    result.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-semantic network from wall-band proposals")
    parser.add_argument("source", type=Path)
    parser.add_argument("linework", type=Path)
    parser.add_argument("wall_bands", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(run(args.source, args.linework, args.wall_bands, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
