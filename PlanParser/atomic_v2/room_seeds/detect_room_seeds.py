"""Detect non-semantic enclosed white-space seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


PARAMETERS = {
    "ink_threshold": 205,
    "horizontal_close_px": 25,
    "vertical_close_px": 25,
    "barrier_dilation_px": 3,
    "minimum_candidate_area_px2": 1800,
    "minimum_reported_area_px2": 12,
    "polygon_epsilon_ratio": 0.006,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _polygon(mask: np.ndarray) -> list[list[int]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    epsilon = PARAMETERS["polygon_epsilon_ratio"] * cv2.arcLength(contour, True)
    simplified = cv2.approxPolyDP(contour, epsilon, True)
    return [[int(point[0][0]), int(point[0][1])] for point in simplified]


def detect(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, PARAMETERS["ink_threshold"], 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (PARAMETERS["horizontal_close_px"], 1)),
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, PARAMETERS["vertical_close_px"])),
    )
    barriers = cv2.bitwise_or(horizontal, vertical)
    barriers = cv2.dilate(
        barriers,
        cv2.getStructuringElement(cv2.MORPH_RECT, (PARAMETERS["barrier_dilation_px"], PARAMETERS["barrier_dilation_px"])),
    )
    free = cv2.bitwise_not(barriers)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(free, 8)
    height, width = gray.shape
    records = []
    for label in range(1, count):
        x, y, w, h, area = map(int, stats[label])
        if area < PARAMETERS["minimum_reported_area_px2"]:
            continue
        touches_boundary = x == 0 or y == 0 or x + w >= width or y + h >= height
        component_mask = np.uint8(labels == label) * 255
        polygon = _polygon(component_mask)
        bbox_area = max(w * h, 1)
        fill_ratio = area / bbox_area
        if touches_boundary:
            status = "external_background"
            abstained = True
            confidence = 0.0
            reasons = ["white-space component touches crop boundary", "retained as excluded external background"]
        elif area < PARAMETERS["minimum_candidate_area_px2"]:
            status = "small_excluded"
            abstained = True
            confidence = round(min(0.49, area / PARAMETERS["minimum_candidate_area_px2"] * 0.49), 3)
            reasons = [
                f"area {area}px2 is below explicit candidate minimum {PARAMETERS['minimum_candidate_area_px2']}px2",
                "retained as excluded/abstained component",
            ]
        else:
            status = "candidate"
            abstained = False
            size_quality = min(1.0, area / 15000)
            confidence = round(min(0.95, 0.52 + 0.25 * size_quality + 0.18 * min(fill_ratio / 0.65, 1.0)), 3)
            reasons = [
                "enclosed white-space component does not touch crop boundary",
                f"area={area}px2 exceeds explicit minimum",
                f"component fill ratio={fill_ratio:.3f}",
                "no semantic room interpretation assigned",
            ]
        records.append({
            "id": "",
            "status": status,
            "bbox_px": [x, y, w, h],
            "polygon_px": polygon,
            "area_px2": area,
            "confidence": confidence,
            "reasons": reasons,
            "abstained": abstained,
        })
    order = {"candidate": 0, "small_excluded": 1, "external_background": 2}
    records.sort(key=lambda item: (order[item["status"]], item["bbox_px"][1], item["bbox_px"][0]))
    for index, record in enumerate(records, 1):
        record["id"] = f"seed_{index:03d}"
    return records


def run(source: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    records = detect(image)
    output_dir.mkdir(parents=True, exist_ok=False)
    overlay = image.copy()
    colors = {"candidate": (0, 170, 0), "small_excluded": (200, 0, 200), "external_background": (140, 140, 140)}
    for record in records:
        if record["status"] == "external_background":
            continue
        polygon = np.array(record["polygon_px"], dtype=np.int32)
        if len(polygon) >= 3:
            layer = overlay.copy()
            cv2.fillPoly(layer, [polygon], colors[record["status"]])
            cv2.addWeighted(layer, 0.20, overlay, 0.80, 0, overlay)
            cv2.polylines(overlay, [polygon], True, colors[record["status"]], 2, cv2.LINE_AA)
        x, y, _, _ = record["bbox_px"]
        cv2.putText(overlay, record["id"], (x, max(48, y - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, colors[record["status"]], 1, cv2.LINE_AA)
    summary = {status: sum(record["status"] == status for record in records) for status in colors}
    cv2.rectangle(overlay, (0, 0), (image.shape[1] - 1, 44), (255, 255, 255), -1)
    cv2.putText(overlay, f"WHITE-SPACE SEEDS candidate={summary['candidate']} small/abstained={summary['small_excluded']} background={summary['external_background']}", (7, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.imwrite(str(output_dir / "room_seeds_overlay.png"), overlay)
    payload = {
        "schema_version": "1.0.0",
        "provenance": {
            "source_crop": str(source).replace("\\", "/"),
            "source_crop_sha256": _sha256(source),
            "detector": "morphological-white-space-flood-fill",
            "detector_version": "1.0.0",
        },
        "parameters": PARAMETERS,
        "summary": {"reported_component_count": len(records), **summary},
        "seeds": records,
        "excluded_inferences": ["rooms", "room_names", "walls", "openings", "adjacency", "scale"],
    }
    result = output_dir / "room_seeds.json"
    result.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect non-semantic enclosed white-space seeds")
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(run(args.source, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
