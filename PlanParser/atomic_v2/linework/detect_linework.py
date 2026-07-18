"""Detect axis-aligned linework candidates without semantic interpretation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _merge(raw: list[tuple[str, int, int, int]], coordinate_tolerance: int = 4, gap: int = 7):
    merged = []
    for orientation in ("horizontal", "vertical"):
        lines = sorted((line for line in raw if line[0] == orientation), key=lambda v: (v[1], v[2], v[3]))
        groups: list[list[int]] = []
        for _, coordinate, start, end in lines:
            target = None
            for group in groups:
                if abs(coordinate - group[0]) <= coordinate_tolerance and start <= group[2] + gap and end >= group[1] - gap:
                    target = group
                    break
            if target is None:
                groups.append([coordinate, start, end, 1])
            else:
                count = target[3] + 1
                target[0] = round((target[0] * target[3] + coordinate) / count)
                target[1] = min(target[1], start)
                target[2] = max(target[2], end)
                target[3] = count
        merged.extend((orientation, coordinate, start, end, votes) for coordinate, start, end, votes in groups)
    return merged


def _observed_thickness(ink: np.ndarray, orientation: str, coordinate: int, start: int, end: int) -> float:
    height, width = ink.shape
    samples = []
    for along in np.linspace(start, end, num=min(11, max(3, (end - start) // 15 + 1))):
        along = int(round(along))
        run = 0
        for offset in range(-8, 9):
            x, y = (along, coordinate + offset) if orientation == "horizontal" else (coordinate + offset, along)
            if 0 <= x < width and 0 <= y < height and ink[y, x]:
                run += 1
        if run:
            samples.append(run)
    return round(float(np.median(samples)), 2) if samples else 0.0


def _occupancy(ink: np.ndarray, orientation: str, coordinate: int, start: int, end: int) -> float:
    height, width = ink.shape
    hits = 0
    total = max(end - start + 1, 1)
    for along in range(start, end + 1):
        found = False
        for offset in range(-2, 3):
            x, y = (along, coordinate + offset) if orientation == "horizontal" else (coordinate + offset, along)
            if 0 <= x < width and 0 <= y < height and ink[y, x]:
                found = True
                break
        hits += int(found)
    return hits / total


def detect(image: np.ndarray) -> list[dict]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink_u8 = cv2.threshold(gray, 205, 255, cv2.THRESH_BINARY_INV)[1]
    lines = cv2.HoughLinesP(ink_u8, 1, np.pi / 180, threshold=28, minLineLength=20, maxLineGap=5)
    raw = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            dx, dy = abs(int(x2) - int(x1)), abs(int(y2) - int(y1))
            if dy <= 2 and dx >= 20:
                raw.append(("horizontal", round((int(y1) + int(y2)) / 2), min(int(x1), int(x2)), max(int(x1), int(x2))))
            elif dx <= 2 and dy >= 20:
                raw.append(("vertical", round((int(x1) + int(x2)) / 2), min(int(y1), int(y2)), max(int(y1), int(y2))))
    ink = ink_u8 > 0
    candidates = []
    for orientation, coordinate, start, end, votes in _merge(raw):
        length = end - start
        if length < 20:
            continue
        occupancy = _occupancy(ink, orientation, coordinate, start, end)
        thickness = _observed_thickness(ink, orientation, coordinate, start, end)
        length_quality = min(1.0, length / 100.0)
        confidence = round(min(0.97, 0.30 + 0.40 * occupancy + 0.20 * length_quality + 0.07 * min(votes / 3, 1)), 3)
        status = "solid" if length >= 45 and occupancy >= 0.78 and confidence >= 0.75 else "uncertain"
        if orientation == "horizontal":
            points = [[start, coordinate], [end, coordinate]]
        else:
            points = [[coordinate, start], [coordinate, end]]
        candidates.append({
            "orientation": orientation,
            "points_px": points,
            "length_px": round(math.dist(points[0], points[1]), 2),
            "observed_thickness_px": thickness,
            "confidence": confidence,
            "status": status,
            "reasons": [
                f"axis-aligned Hough support merged from {votes} detection(s)",
                f"observed line occupancy={occupancy:.3f}",
                "semantic type intentionally not inferred",
            ],
            "abstained": status == "uncertain",
        })
    candidates.sort(key=lambda c: (c["status"] != "solid", c["orientation"], c["points_px"][0][1], c["points_px"][0][0]))
    for index, candidate in enumerate(candidates, 1):
        candidate["id"] = f"line_{index:03d}"
    return candidates


def run(source: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    candidates = detect(image)
    output_dir.mkdir(parents=True, exist_ok=False)
    overlay = image.copy()
    for candidate in candidates:
        p1, p2 = map(tuple, candidate["points_px"])
        color = (0, 0, 230) if candidate["status"] == "solid" else (0, 165, 255)
        cv2.line(overlay, p1, p2, color, 2 if candidate["status"] == "solid" else 1, cv2.LINE_AA)
        cv2.putText(overlay, candidate["id"], p1, cv2.FONT_HERSHEY_SIMPLEX, 0.34, color, 1, cv2.LINE_AA)
    solid = sum(c["status"] == "solid" for c in candidates)
    uncertain = len(candidates) - solid
    cv2.rectangle(overlay, (0, 0), (image.shape[1] - 1, 42), (255, 255, 255), -1)
    cv2.putText(overlay, f"LINEWORK CANDIDATES  solid={solid}  uncertain/abstained={uncertain}", (8, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.imwrite(str(output_dir / "linework_overlay.png"), overlay)
    provenance = {
        "source_path": str(source).replace("\\", "/"),
        "source_sha256": _sha256(source),
        "detector": "axis-aligned-hough-linework",
        "detector_version": "1.0.0",
        "semantic_inference": False,
    }
    payload = {
        "schema_version": "1.0.0",
        "image": {"width_px": image.shape[1], "height_px": image.shape[0]},
        "provenance": provenance,
        "summary": {"candidate_count": len(candidates), "solid_count": solid, "uncertain_count": uncertain},
        "candidates": candidates,
        "excluded_inferences": ["walls", "rooms", "openings", "adjacency", "scale"],
    }
    path = output_dir / "linework.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect horizontal/vertical linework candidates")
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(run(args.source, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
