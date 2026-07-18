from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


TILE_WIDTH = 420
TILE_HEIGHT = 365
VIEW_SIZE = 242
CONTEXT_SIZE = 220
GRID_COLUMNS = 4
GRID_ROWS = 3
SHEET_HEADER = 58


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exclusive_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def exclusive_png(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError(f"PNG encoding failed: {path}")
    exclusive_write(path, encoded.tobytes())


def color_for_class(geometric_class: str) -> tuple[int, int, int]:
    return {
        "crossing": (30, 190, 30),
        "endpoint_to_interior": (0, 155, 255),
        "endpoint_to_endpoint": (235, 80, 50),
        "mixed": (180, 45, 210),
    }.get(geometric_class, (180, 45, 210))


def relation_evidence(node: dict[str, Any], relation_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for relation_id in node["relation_ids"]:
        relation = relation_by_id[relation_id]
        evidence.append(
            {
                "relation_id": relation_id,
                "kind": relation["kind"],
                "geometric_class": relation["geometric_class"],
                "angle_degrees": relation["angle_degrees"],
                "separation_px": relation["separation_px"],
                "segment_ids": relation["segment_ids"],
                "confidence": relation["confidence"],
                "abstained": relation["abstained"],
            }
        )
    return evidence


def context_with_padding(
    source: np.ndarray, center_x: float, center_y: float
) -> tuple[np.ndarray, list[int], list[int], list[int]]:
    half = CONTEXT_SIZE // 2
    requested_x0 = int(round(center_x)) - half
    requested_y0 = int(round(center_y)) - half
    requested_x1 = requested_x0 + CONTEXT_SIZE
    requested_y1 = requested_y0 + CONTEXT_SIZE
    height, width = source.shape[:2]
    clipped_x0 = max(0, requested_x0)
    clipped_y0 = max(0, requested_y0)
    clipped_x1 = min(width, requested_x1)
    clipped_y1 = min(height, requested_y1)
    pad_left = clipped_x0 - requested_x0
    pad_top = clipped_y0 - requested_y0
    pad_right = requested_x1 - clipped_x1
    pad_bottom = requested_y1 - clipped_y1
    clipped = source[clipped_y0:clipped_y1, clipped_x0:clipped_x1]
    context = cv2.copyMakeBorder(
        clipped,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(250, 250, 250),
    )
    if context.shape[0] != CONTEXT_SIZE or context.shape[1] != CONTEXT_SIZE:
        raise RuntimeError("Context extraction did not produce the fixed reversible canvas")
    return (
        context,
        [requested_x0, requested_y0, CONTEXT_SIZE, CONTEXT_SIZE],
        [clipped_x0, clipped_y0, clipped_x1 - clipped_x0, clipped_y1 - clipped_y0],
        [pad_left, pad_top, pad_right, pad_bottom],
    )


def draw_related_segments(
    context: np.ndarray,
    raw_by_id: dict[str, dict[str, Any]],
    segment_ids: list[str],
    requested_bbox: list[int],
) -> None:
    x0, y0 = requested_bbox[:2]
    scale = VIEW_SIZE / CONTEXT_SIZE
    for segment_id in segment_ids:
        points = raw_by_id[segment_id]["points_px"]
        start = (
            round((float(points[0][0]) - x0) * scale),
            round((float(points[0][1]) - y0) * scale),
        )
        end = (
            round((float(points[1][0]) - x0) * scale),
            round((float(points[1][1]) - y0) * scale),
        )
        cv2.line(context, start, end, (10, 210, 235), 2, cv2.LINE_AA)


def fit_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    words = text.split(",")
    lines: list[str] = []
    current = ""
    for word in words:
        token = word if not current else f",{word}"
        if current and len(current) + len(token) > max_chars:
            lines.append(current)
            current = word
        else:
            current += token
    if current:
        lines.append(current)
    return lines


def create_tile(
    source: np.ndarray,
    node: dict[str, Any],
    evidence: list[dict[str, Any]],
    raw_by_id: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    center_x, center_y = node["coordinate_crop_px"]
    context, requested_bbox, clipped_bbox, padding = context_with_padding(source, center_x, center_y)
    context = cv2.resize(context, (VIEW_SIZE, VIEW_SIZE), interpolation=cv2.INTER_NEAREST)
    context = cv2.addWeighted(context, 0.78, np.full_like(context, 255), 0.22, 0)
    draw_related_segments(context, raw_by_id, node["segment_ids"], requested_bbox)

    center_in_view = (VIEW_SIZE // 2, VIEW_SIZE // 2)
    color = color_for_class(node["geometric_class"])
    if node["abstained"]:
        cv2.circle(context, center_in_view, 10, color, 2, cv2.LINE_AA)
        cv2.circle(context, center_in_view, 3, color, -1, cv2.LINE_AA)
    else:
        cv2.circle(context, center_in_view, 8, color, -1, cv2.LINE_AA)
    cv2.line(
        context,
        (center_in_view[0] - 14, center_in_view[1]),
        (center_in_view[0] + 14, center_in_view[1]),
        color,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        context,
        (center_in_view[0], center_in_view[1] - 14),
        (center_in_view[0], center_in_view[1] + 14),
        color,
        1,
        cv2.LINE_AA,
    )

    tile = np.full((TILE_HEIGHT, TILE_WIDTH, 3), 250, dtype=np.uint8)
    view_x = (TILE_WIDTH - VIEW_SIZE) // 2
    tile[6 : 6 + VIEW_SIZE, view_x : view_x + VIEW_SIZE] = context
    cv2.rectangle(tile, (view_x, 6), (view_x + VIEW_SIZE - 1, 6 + VIEW_SIZE - 1), (105, 105, 105), 1)

    evidence_kinds = "+".join(sorted({item["kind"].replace("_intersection", "") for item in evidence}))
    angles = ",".join(f"{item['angle_degrees']:.1f}" for item in evidence)
    lines = [
        f"{node['node_id']} | {node['geometric_class']}",
        f"evidence={evidence_kinds} | abstained={'yes' if node['abstained'] else 'no'}",
        f"angles_deg={angles} | crop=({center_x:.1f},{center_y:.1f})",
    ]
    segment_text = "segments=" + ",".join(node["segment_ids"])
    lines.extend(fit_text(segment_text, 53))
    y = 270
    for index, line in enumerate(lines):
        cv2.putText(
            tile,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43 if index else 0.49,
            color if index == 0 else (35, 35, 35),
            1,
            cv2.LINE_AA,
        )
        y += 19

    mapping = {
        "context_bbox_requested_crop_px": requested_bbox,
        "context_bbox_clipped_crop_px": clipped_bbox,
        "context_padding_px": {
            "left": padding[0],
            "top": padding[1],
            "right": padding[2],
            "bottom": padding[3],
        },
        "node_center_in_context_px": [CONTEXT_SIZE // 2, CONTEXT_SIZE // 2],
        "node_center_in_tile_px": [view_x + VIEW_SIZE // 2, 6 + VIEW_SIZE // 2],
        "tile_size_px": [TILE_WIDTH, TILE_HEIGHT],
        "context_original_size_px": [CONTEXT_SIZE, CONTEXT_SIZE],
        "context_rendered_size_px": [VIEW_SIZE, VIEW_SIZE],
    }
    return tile, mapping


def create_sheet(page_number: int, total_pages: int, tiles: list[tuple[str, np.ndarray]]) -> np.ndarray:
    sheet_height = SHEET_HEADER + GRID_ROWS * TILE_HEIGHT
    sheet_width = GRID_COLUMNS * TILE_WIDTH
    sheet = np.full((sheet_height, sheet_width, 3), 242, dtype=np.uint8)
    cv2.putText(
        sheet,
        f"GEOMETRY NODE REVIEW | page {page_number}/{total_pages} | raw geometry only",
        (18, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        (25, 25, 25),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        sheet,
        "yellow=source segments participating in node; hollow marker=near/mixed abstention",
        (18, 49),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        (55, 55, 55),
        1,
        cv2.LINE_AA,
    )
    for cell_index, (_, tile) in enumerate(tiles):
        row = cell_index // GRID_COLUMNS
        column = cell_index % GRID_COLUMNS
        x0 = column * TILE_WIDTH
        y0 = SHEET_HEADER + row * TILE_HEIGHT
        sheet[y0 : y0 + TILE_HEIGHT, x0 : x0 + TILE_WIDTH] = tile
        cv2.rectangle(sheet, (x0, y0), (x0 + TILE_WIDTH - 1, y0 + TILE_HEIGHT - 1), (180, 180, 180), 1)
    return sheet


def build(graph_path: Path, crop_path: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.rglob("*")):
        raise FileExistsError(f"Revision contains files; refusing overwrite: {output_dir}")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    source_gray = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
    if source_gray is None:
        raise RuntimeError(f"Cannot read source crop: {crop_path}")
    source = cv2.cvtColor(source_gray, cv2.COLOR_GRAY2BGR)
    relation_by_id = {item["relation_id"]: item for item in graph["junction_relations"]}
    raw_by_id = {item["id"]: item for item in graph["raw_segments_preserved"]}
    nodes = graph["nodes"]
    tiles_dir = output_dir / "tiles"
    sheets_dir = output_dir / "contact_sheets"
    rendered: list[tuple[str, np.ndarray]] = []
    manifest_nodes: list[dict[str, Any]] = []
    page_capacity = GRID_COLUMNS * GRID_ROWS
    total_pages = math.ceil(len(nodes) / page_capacity)

    for global_index, node in enumerate(nodes):
        evidence = relation_evidence(node, relation_by_id)
        tile, mapping = create_tile(source, node, evidence, raw_by_id)
        tile_name = f"{node['node_id']}.png"
        tile_path = tiles_dir / tile_name
        exclusive_png(tile_path, tile)
        page_index = global_index // page_capacity + 1
        cell_index = global_index % page_capacity
        row = cell_index // GRID_COLUMNS
        column = cell_index % GRID_COLUMNS
        sheet_name = f"contact_sheet_{page_index:03d}.png"
        manifest_nodes.append(
            {
                "node_id": node["node_id"],
                "node_coordinate_crop_px": node["coordinate_crop_px"],
                "node_coordinate_source_page_px": node["coordinate_source_page_px"],
                "geometric_class": node["geometric_class"],
                "observed_relation_kinds": node["observed_relation_kinds"],
                "abstained": node["abstained"],
                "confidence": node["confidence"],
                "segment_ids": node["segment_ids"],
                "relation_evidence": evidence,
                "tile_file": f"tiles/{tile_name}",
                "tile_sha256": sha256(tile_path),
                "sheet": {
                    "file": f"contact_sheets/{sheet_name}",
                    "page": page_index,
                    "row_zero_based": row,
                    "column_zero_based": column,
                    "cell_bbox_sheet_px": [
                        column * TILE_WIDTH,
                        SHEET_HEADER + row * TILE_HEIGHT,
                        TILE_WIDTH,
                        TILE_HEIGHT,
                    ],
                },
                "reversible_mapping": mapping,
            }
        )
        rendered.append((node["node_id"], tile))

    sheets: list[dict[str, Any]] = []
    for page_index in range(1, total_pages + 1):
        start = (page_index - 1) * page_capacity
        page_tiles = rendered[start : start + page_capacity]
        sheet = create_sheet(page_index, total_pages, page_tiles)
        sheet_name = f"contact_sheet_{page_index:03d}.png"
        sheet_path = sheets_dir / sheet_name
        exclusive_png(sheet_path, sheet)
        sheets.append(
            {
                "page": page_index,
                "file": f"contact_sheets/{sheet_name}",
                "sha256": sha256(sheet_path),
                "node_ids": [node_id for node_id, _ in page_tiles],
                "size_px": [int(sheet.shape[1]), int(sheet.shape[0])],
            }
        )

    manifest = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "purpose": "human_review_of_raw_geometric_nodes",
            "semantic_building_labels": False,
            "explicitly_not_inferred": ["wall", "door", "window", "room", "property_boundary"],
        },
        "provenance": {
            "geometry_graph_path": str(graph_path).replace("\\", "/"),
            "geometry_graph_sha256": sha256(graph_path),
            "crop_path": str(crop_path).replace("\\", "/"),
            "crop_sha256": sha256(crop_path),
            "crop_offset_in_source_page_px": graph["coordinate_systems"]["crop_offset_in_source_page_px"],
        },
        "render_parameters": {
            "context_size_crop_px": [CONTEXT_SIZE, CONTEXT_SIZE],
            "context_render_size_tile_px": [VIEW_SIZE, VIEW_SIZE],
            "tile_size_px": [TILE_WIDTH, TILE_HEIGHT],
            "sheet_grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS},
            "sheet_header_height_px": SHEET_HEADER,
            "interpolation": "nearest",
        },
        "summary": {
            "source_node_count": len(nodes),
            "tile_count": len(manifest_nodes),
            "contact_sheet_count": len(sheets),
            "mapped_once_count": len({item["node_id"] for item in manifest_nodes}),
            "abstained_node_count": sum(item["abstained"] for item in manifest_nodes),
        },
        "contact_sheets": sheets,
        "nodes": manifest_nodes,
    }
    manifest_path = output_dir / "review_tiles_manifest.json"
    exclusive_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render reversible review tiles for geometry nodes.")
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--crop", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build(args.graph, args.crop, args.output_dir)
    print(json.dumps(manifest["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
