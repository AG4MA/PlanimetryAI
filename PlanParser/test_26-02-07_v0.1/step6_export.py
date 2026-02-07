"""
Step 6: Export to Knowledge Model JSON.

Assembles analyzed floor data into the output_model structure
and serializes to JSON.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
import logging

from output_model import KnowledgeModel, Floor, Room, Wall, Connection
from step5_semantic_analysis import AnalyzedRoom
from dcel import DCEL


def build_knowledge_model(
    source_file: str,
    floors_data: List[Dict],
    scale: Optional[str] = None,
    scale_factor: Optional[float] = None,
    orientation: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
) -> KnowledgeModel:
    """
    Build the KnowledgeModel from analyzed floor data.

    Args:
        source_file: Path to the original input file.
        floors_data: List of dicts with keys:
            "label": str, "rooms": List[AnalyzedRoom], "dcel": DCEL
        scale: Scale string (e.g., "1:100").
        scale_factor: Computed scale factor (px to m), or None.
        orientation: North orientation in degrees, or None.
        logger: Optional logger.

    Returns:
        KnowledgeModel instance.
    """
    # Parse scale
    if scale and scale_factor is None:
        scale_factor = _parse_scale(scale)

    model = KnowledgeModel(
        source_file=source_file,
        scale=scale,
        scale_factor=scale_factor,
        orientation_north=orientation,
    )

    for i, floor_data in enumerate(floors_data):
        label = floor_data["label"]
        analyzed_rooms: List[AnalyzedRoom] = floor_data["rooms"]
        dcel: DCEL = floor_data["dcel"]

        floor = Floor(
            id=f"floor_{i}",
            label=label,
        )

        for ar in analyzed_rooms:
            # Build walls
            walls = []
            for w in ar.walls:
                wall = Wall(
                    wall_type=w.get("wall_type", "unknown"),
                    start_point=tuple(w.get("start_point", (0, 0))),
                    end_point=tuple(w.get("end_point", (0, 0))),
                    length_px=w.get("length_px", 0.0),
                )
                if scale_factor is not None and wall.length_px > 0:
                    wall.length_m = wall.length_px * scale_factor
                walls.append(wall)

            # Build connections
            connections = []
            for c in ar.connections:
                conn = Connection(
                    to_room_id=str(c.get("to_room_id", "")),
                    connection_type=c.get("connection_type", "passage"),
                )
                if c.get("position"):
                    conn.position = tuple(c["position"])
                connections.append(conn)

            # Build room
            area_m2 = None
            if scale_factor is not None and ar.area_px > 0:
                area_m2 = ar.area_px * (scale_factor ** 2)

            room = Room(
                id=str(ar.face_id),
                label=ar.label,
                polygon=ar.polygon,
                area_px=ar.area_px,
                area_m2=area_m2,
                walls=walls,
                connections=connections,
            )
            floor.rooms.append(room)

        # Build topology (adjacency)
        dual = dcel.build_dual_graph()
        room_ids = {str(ar.face_id) for ar in analyzed_rooms}
        topology = {}
        for ar in analyzed_rooms:
            neighbors = dual.get(ar.face_id, [])
            topology[str(ar.face_id)] = [
                str(n) for n in neighbors if str(n) in room_ids
            ]
        floor.topology = topology

        model.floors.append(floor)

    if logger:
        total_rooms = sum(len(f.rooms) for f in model.floors)
        logger.info("  KnowledgeModel: %d floor(s), %d room(s) total",
                    len(model.floors), total_rooms)

    return model


def _parse_scale(scale: str) -> Optional[float]:
    """
    Parse a scale string like "1:100" into a conversion factor.

    Returns pixels-to-meters factor: 1 pixel = factor meters.
    Assumes rendering at 300 DPI and standard paper.
    """
    try:
        parts = scale.split(":")
        if len(parts) == 2:
            numerator = float(parts[0])
            denominator = float(parts[1])
            if denominator > 0:
                # At 1:100, 1 unit on paper = 100 units in reality
                # At 300 DPI, 1 inch = 300 pixels
                # 1 inch = 0.0254 m
                # So 1 pixel = 0.0254/300 m on paper
                # In reality: 1 pixel = (0.0254/300) * (denominator/numerator) m
                meters_per_pixel = (0.0254 / 300.0) * (denominator / numerator)
                return meters_per_pixel
    except (ValueError, ZeroDivisionError):
        pass
    return None


def export_json(
    model: KnowledgeModel,
    output_path: Path,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Serialize the KnowledgeModel to JSON and save."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    json_str = model.to_json(indent=2)
    output_path.write_text(json_str, encoding="utf-8")

    if logger:
        logger.info("  Exported: %s (%d bytes)", output_path.name, len(json_str))
