"""Conservative revision of geometric-network member tiers."""

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


def _intersects(a, b, tolerance=9):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + tolerance < bx or bx + bw + tolerance < ax or ay + ah + tolerance < by or by + bh + tolerance < ay)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def run(source: Path, bands_path: Path, revision1_path: Path, output_dir: Path) -> Path:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read source image: {source}")
    bands_payload = json.loads(bands_path.read_text(encoding="utf-8"))
    previous = json.loads(revision1_path.read_text(encoding="utf-8"))
    bands = bands_payload["candidates"]
    previous_by_id = {member["source_band_id"]: member for member in previous["members"]}
    solid = [band for band in bands if not band["abstained"]]
    lengths = [float(band["length_px"]) for band in solid]
    thicknesses = [float(band["observed_thickness_px"]) for band in solid]
    long_threshold = round(_percentile(lengths, 0.60), 2)
    very_long_threshold = round(_percentile(lengths, 0.85), 2)
    thickness_threshold = round(statistics.median(thicknesses), 2)
    degree = {}
    for i, band in enumerate(bands):
        degree[band["id"]] = sum(i != j and _intersects(band["bbox_px"], other["bbox_px"]) for j, other in enumerate(bands))

    members = []
    for band in bands:
        prior = previous_by_id[band["id"]]
        length = float(band["length_px"])
        thickness = float(band["observed_thickness_px"])
        local_degree = degree[band["id"]]
        if band["abstained"]:
            tier = "abstention"
            decision = "source proposal abstained; retained unchanged"
        else:
            thick_supported = thickness >= thickness_threshold
            long_supported = length >= long_threshold
            very_long_supported = length >= very_long_threshold
            locally_supported = local_degree >= 2
            primary = prior["tier"] == "primary" and (
                very_long_supported
                or (long_supported and thick_supported)
                or (length >= _percentile(lengths, 0.40) and thick_supported and locally_supported)
            )
            tier = "primary" if primary else "secondary"
            decision = (
                "retained as primary by observed length/thickness/local-support distribution"
                if primary else
                "conservatively declassified: insufficient combined length, thickness and local support"
            )
        members.append({
            **prior,
            "tier": tier,
            "abstained": tier == "abstention",
            "local_connection_degree": local_degree,
            "previous_tier": prior["tier"],
            "reasons": list(prior["reasons"]) + [
                decision,
                f"observed thresholds: long>={long_threshold}px, very_long>={very_long_threshold}px, thickness>={thickness_threshold}px",
                f"member observations: length={length}px, thickness={thickness}px, local_degree={local_degree}",
            ],
        })

    counts = Counter(member["tier"] for member in members)
    output_dir.mkdir(parents=True, exist_ok=False)
    overlay = image.copy()
    colors = {"primary": (0, 0, 230), "secondary": (220, 110, 0), "abstention": (200, 0, 200)}
    for member in members:
        points = np.array([(round(x), round(y)) for x, y in member["polygon_px"]], dtype=np.int32)
        cv2.polylines(overlay, [points], True, colors[member["tier"]], 2, cv2.LINE_AA)
        x, y, _, _ = member["bbox_px"]
        cv2.putText(overlay, member["source_band_id"], (round(x), max(48, round(y) - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.32, colors[member["tier"]], 1, cv2.LINE_AA)
    cv2.rectangle(overlay, (0, 0), (image.shape[1] - 1, 44), (255, 255, 255), -1)
    cv2.putText(overlay, f"NETWORK REVISION 002  primary={counts['primary']} secondary={counts['secondary']} abstention={counts['abstention']}", (7, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.51, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.imwrite(str(output_dir / "wall_network_overlay.png"), overlay)
    payload = {
        "schema_version": "1.0.0",
        "revision": "002",
        "provenance": {
            "source_crop": str(source).replace("\\", "/"),
            "source_crop_sha256": _sha256(source),
            "source_wall_bands": str(bands_path).replace("\\", "/"),
            "source_wall_bands_sha256": _sha256(bands_path),
            "source_network_revision_001": str(revision1_path).replace("\\", "/"),
            "source_network_revision_001_sha256": _sha256(revision1_path),
            "builder": "geometric-band-network-conservative-tiering",
            "builder_version": "2.0.0",
        },
        "observed_thresholds": {
            "long_length_px_p60": long_threshold,
            "very_long_length_px_p85": very_long_threshold,
            "thickness_px_median": thickness_threshold,
            "minimum_local_connection_degree": 2,
        },
        "summary": {
            "source_band_count": len(bands),
            "retained_member_count": len(members),
            "primary_count": counts["primary"],
            "secondary_count": counts["secondary"],
            "abstention_count": counts["abstention"],
            "declassified_from_primary_count": sum(m["previous_tier"] == "primary" and m["tier"] == "secondary" for m in members),
        },
        "components": previous["components"],
        "observed_thickness_clusters": previous["observed_thickness_clusters"],
        "members": members,
        "excluded_inferences": previous["excluded_inferences"],
    }
    result = output_dir / "wall_network.json"
    result.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Conservative geometric network tiering revision 002")
    parser.add_argument("source", type=Path)
    parser.add_argument("wall_bands", type=Path)
    parser.add_argument("revision_001", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(run(args.source, args.wall_bands, args.revision_001, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
