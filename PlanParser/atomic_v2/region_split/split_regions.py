"""Isolated heuristic splitter for architectural drawing regions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_regions(image) -> list[dict]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, round(width * 0.014)), 1)),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, round(height * 0.010)))),
    )
    structural = cv2.bitwise_or(horizontal, vertical)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(15, round(width * 0.010)), max(9, round(height * 0.004))),
    )
    joined = cv2.dilate(structural, kernel, iterations=1)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    candidates = []
    for component_id in range(1, count):
        x, y, w, h, area = map(int, stats[component_id])
        width_ratio, height_ratio = w / width, h / height
        if y < height * 0.15:
            continue
        if not (0.20 <= width_ratio <= 0.65 and 0.14 <= height_ratio <= 0.42):
            continue
        component_mask = labels[y:y + h, x:x + w] == component_id
        original_ink = ink[y:y + h, x:x + w] > 0
        ink_pixels = int((component_mask & original_ink).sum())
        ink_ratio = ink_pixels / max(w * h, 1)
        if ink_ratio < 0.012:
            continue
        score = area * (0.6 + min(ink_ratio / 0.08, 1.0) * 0.4)
        candidates.append((score, x, y, w, h, ink_ratio))

    chosen = sorted(candidates, reverse=True)[:2]
    chosen.sort(key=lambda item: item[2])
    regions = []
    pad = max(8, round(min(width, height) * 0.003))
    for index, (_, x, y, w, h, ink_ratio) in enumerate(chosen, 1):
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        size_quality = min(1.0, (w / width) / 0.35) * min(1.0, (h / height) / 0.20)
        density_quality = min(1.0, ink_ratio / 0.045)
        confidence = round(min(0.98, 0.55 + 0.25 * size_quality + 0.20 * density_quality), 3)
        regions.append({
            "id": f"region_{index:03d}",
            "bbox_px": [x0, y0, x1 - x0, y1 - y0],
            "confidence": confidence,
            "reasons": [
                "connected horizontal/vertical linework component below the cadastral header",
                "component dimensions are consistent with a plan drawing rather than a text line",
                f"measured ink ratio={ink_ratio:.4f}",
            ],
            "abstained": False,
        })
    return regions


def split(source: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    output_dir.mkdir(parents=True, exist_ok=True)
    regions = detect_regions(image)
    abstained = len(regions) != 2
    if abstained:
        regions = [{
            "id": "region_detection_abstention",
            "bbox_px": [0, 0, image.shape[1], image.shape[0]],
            "confidence": 0.0,
            "reasons": [f"expected exactly 2 drawing regions; detected {len(regions)}"],
            "abstained": True,
        }]

    overlay = image.copy()
    for region in regions:
        x, y, w, h = region["bbox_px"]
        color = (255, 0, 255) if region["abstained"] else (0, 80, 255)
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, 8)
        cv2.putText(
            overlay,
            f"{region['id']}  confidence={region['confidence']:.3f}",
            (x + 10, max(45, y - 15)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3,
            cv2.LINE_AA,
        )
        if not region["abstained"]:
            cv2.imwrite(str(output_dir / f"{region['id']}.png"), image[y:y + h, x:x + w])
    cv2.imwrite(str(output_dir / "regions_overlay.png"), overlay)
    payload = {
        "schema_version": "1.0.0",
        "source": {
            "path": str(source).replace("\\", "/"),
            "sha256": _sha256(source),
            "width_px": image.shape[1],
            "height_px": image.shape[0],
        },
        "method": {
            "name": "connected-linework-region-split",
            "version": "1.0.0",
            "automatic": True,
            "ocr_used": False,
        },
        "regions": regions,
        "abstained": abstained,
    }
    json_path = output_dir / "regions.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect isolated plan-drawing regions")
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    result = split(args.source, args.output_dir)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
