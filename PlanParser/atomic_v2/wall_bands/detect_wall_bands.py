"""Propose non-semantic wall bands from paired linework evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _axis(candidate: dict):
    (x1, y1), (x2, y2) = candidate["points_px"]
    if candidate["orientation"] == "horizontal":
        return y1, min(x1, x2), max(x1, x2)
    return x1, min(y1, y2), max(y1, y2)


def _paired_bands(lines: list[dict]) -> list[dict]:
    proposals = []
    for i, first in enumerate(lines):
        if first["length_px"] < 45:
            continue
        c1, a1, b1 = _axis(first)
        for second in lines[i + 1:]:
            if second["orientation"] != first["orientation"] or second["length_px"] < 45:
                continue
            c2, a2, b2 = _axis(second)
            separation = abs(c2 - c1)
            if not 4 <= separation <= 22:
                continue
            start, end = max(a1, a2), min(b1, b2)
            overlap = end - start
            if overlap < 40:
                continue
            overlap_ratio = overlap / max(1, min(b1 - a1, b2 - a2))
            if overlap_ratio < 0.72:
                continue
            if first["orientation"] == "horizontal":
                polygon = [[start, min(c1, c2)], [end, min(c1, c2)], [end, max(c1, c2)], [start, max(c1, c2)]]
                bbox = [start, min(c1, c2), overlap, separation]
            else:
                polygon = [[min(c1, c2), start], [max(c1, c2), start], [max(c1, c2), end], [min(c1, c2), end]]
                bbox = [min(c1, c2), start, separation, overlap]
            confidence = round(min(0.97, 0.42 + 0.24 * overlap_ratio + 0.17 * min(overlap / 140, 1) + 0.14 * min(first["confidence"], second["confidence"])), 3)
            proposals.append({
                "orientation": first["orientation"],
                "polygon_px": polygon,
                "bbox_px": bbox,
                "source_edge_ids": [first["id"], second["id"]],
                "observed_thickness_px": separation,
                "length_px": overlap,
                "confidence": confidence,
                "evidence_type": "parallel_edge_pair",
                "reasons": [
                    f"two parallel source edges overlap by {overlap}px",
                    f"overlap ratio={overlap_ratio:.3f}",
                    f"observed separation={separation}px",
                ],
                "abstained": confidence < 0.78 or first["abstained"] or second["abstained"],
            })
    return proposals


def _perimeter_bands(lines: list[dict], width: int, height: int) -> list[dict]:
    proposals = []
    margin = max(24, round(min(width, height) * 0.045))
    for line in lines:
        if line["abstained"] or line["length_px"] < min(width, height) * 0.48:
            continue
        coordinate, start, end = _axis(line)
        near_border = coordinate <= margin or coordinate >= ((height if line["orientation"] == "horizontal" else width) - margin)
        if not near_border:
            continue
        thickness = max(2.0, float(line.get("observed_thickness_px", 1.0)))
        half = thickness / 2
        if line["orientation"] == "horizontal":
            polygon = [[start, coordinate - half], [end, coordinate - half], [end, coordinate + half], [start, coordinate + half]]
            bbox = [start, round(coordinate - half, 2), end - start, thickness]
        else:
            polygon = [[coordinate - half, start], [coordinate + half, start], [coordinate + half, end], [coordinate - half, end]]
            bbox = [round(coordinate - half, 2), start, thickness, end - start]
        confidence = round(min(0.90, 0.58 + 0.18 * min(line["length_px"] / 300, 1) + 0.12 * line["confidence"]), 3)
        proposals.append({
            "orientation": line["orientation"],
            "polygon_px": polygon,
            "bbox_px": bbox,
            "source_edge_ids": [line["id"]],
            "observed_thickness_px": thickness,
            "length_px": line["length_px"],
            "confidence": confidence,
            "evidence_type": "robust_perimeter_edge",
            "reasons": ["long continuous source edge near crop perimeter", "single-edge exception restricted to robust perimeter evidence"],
            "abstained": confidence < 0.78,
        })
    return proposals


def _deduplicate(proposals: list[dict]) -> list[dict]:
    kept = []
    for proposal in sorted(proposals, key=lambda p: (-p["confidence"], -p["length_px"])):
        x, y, w, h = proposal["bbox_px"]
        duplicate = False
        for prior in kept:
            px, py, pw, ph = prior["bbox_px"]
            ix, iy = max(x, px), max(y, py)
            iw, ih = max(0, min(x + w, px + pw) - ix), max(0, min(y + h, py + ph) - iy)
            intersection = iw * ih
            if intersection and intersection / max(1, min(w * h, pw * ph)) > 0.75:
                duplicate = True
                break
        if not duplicate:
            kept.append(proposal)
    kept.sort(key=lambda p: (p["abstained"], p["bbox_px"][1], p["bbox_px"][0]))
    for index, proposal in enumerate(kept, 1):
        proposal["id"] = f"band_{index:03d}"
        proposal["status"] = "uncertain" if proposal["abstained"] else "solid"
    return kept


def run(source: Path, linework_path: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    linework = json.loads(linework_path.read_text(encoding="utf-8"))
    candidates = linework.get("candidates", [])
    height, width = image.shape[:2]
    bands = _deduplicate(_paired_bands(candidates) + _perimeter_bands(candidates, width, height))
    output_dir.mkdir(parents=True, exist_ok=False)
    overlay = image.copy()
    for band in bands:
        points = [(round(x), round(y)) for x, y in band["polygon_px"]]
        color = (200, 0, 200) if band["abstained"] else (0, 0, 230)
        cv2.polylines(overlay, [__import__("numpy").array(points, dtype="int32")], True, color, 2, cv2.LINE_AA)
        x, y, _, _ = band["bbox_px"]
        cv2.putText(overlay, band["id"], (round(x), max(48, round(y) - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
    solid = sum(not band["abstained"] for band in bands)
    uncertain = len(bands) - solid
    cv2.rectangle(overlay, (0, 0), (width - 1, 42), (255, 255, 255), -1)
    cv2.putText(overlay, f"WALL-BAND PROPOSALS solid={solid} uncertain={uncertain}", (8, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.imwrite(str(output_dir / "wall_bands_overlay.png"), overlay)
    payload = {
        "schema_version": "1.0.0",
        "provenance": {
            "source_crop": str(source).replace("\\", "/"),
            "source_crop_sha256": _sha256(source),
            "source_linework": str(linework_path).replace("\\", "/"),
            "source_linework_sha256": _sha256(linework_path),
            "detector": "parallel-edge-wall-band-proposer",
            "detector_version": "1.0.0",
        },
        "summary": {"candidate_count": len(bands), "solid_count": solid, "uncertain_count": uncertain},
        "candidates": bands,
        "excluded_inferences": ["internal_or_external", "rooms", "openings", "adjacency", "scale"],
    }
    result = output_dir / "wall_bands.json"
    result.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose wall bands from linework evidence")
    parser.add_argument("source", type=Path)
    parser.add_argument("linework", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(run(args.source, args.linework, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
