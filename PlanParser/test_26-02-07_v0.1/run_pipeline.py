"""
PlanParser Pipeline v0.1 - Orchestrator

Runs all 6 steps sequentially:
  Step 1: PDF -> Image
  Step 2: Floor Detection & Splitting
  Step 3: Scale & Orientation (STUB)
  Step 4: Line & Text Extraction
  Step 5: Semantic Analysis
  Step 6: Export to JSON

Usage:
    python run_pipeline.py <input_pdf_or_image> [--output <dir>] [--scale <1:100>] [--page <0>] [--dpi <300>]
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional
import logging

# Ensure this package is importable
sys.path.insert(0, str(Path(__file__).parent))

from __init__ import configure_tesseract, OUTPUT_DIR, DATA_DIR
from debug_utils import setup_logger, save_debug_image, draw_segments_on_image, draw_text_blocks_on_image
from step1_pdf_to_image import pdf_to_image
from step2_floor_detection import split_floors
from step3_scale_orientation import extract_scale, extract_orientation
from step4_line_text_extraction import extract_lines_and_text
from step5_semantic_analysis import SemanticAnalyzer
from step6_export import build_knowledge_model, export_json


def run_pipeline(
    input_path: Path,
    output_dir: Optional[Path] = None,
    scale: Optional[str] = None,
    page: int = 0,
    dpi: int = 300,
) -> dict:
    """
    Execute the full 6-step pipeline.

    Args:
        input_path: Path to PDF or image file.
        output_dir: Output directory for results and debug images.
        scale: Optional scale string (e.g., "1:100").
        page: PDF page index (0-based).
        dpi: Rendering DPI for PDFs.

    Returns:
        The KnowledgeModel as a dict.
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger("pipeline", output_dir / "logs")

    logger.info("=" * 60)
    logger.info("PLANIMETRY PIPELINE v0.1 - test_26-02-07")
    logger.info("=" * 60)
    logger.info("Input: %s", input_path)
    logger.info("Output: %s", output_dir)
    if scale:
        logger.info("Scale: %s", scale)

    t0 = time.perf_counter()

    # ==========================================
    # STEP 1: PDF -> Image
    # ==========================================
    logger.info("[STEP 1] PDF to Image")
    full_image = pdf_to_image(input_path, page=page, dpi=dpi, logger=logger)
    save_debug_image(full_image, output_dir / "step1_full_image.png", logger)

    # ==========================================
    # STEP 2: Floor Detection & Splitting
    # ==========================================
    logger.info("[STEP 2] Floor Detection & Splitting")
    floor_images = split_floors(
        full_image,
        debug_dir=output_dir / "step2_floors",
        logger=logger,
    )
    logger.info("  Detected %d floor(s)", len(floor_images))
    for i, fi in enumerate(floor_images):
        logger.info("    Floor %d: '%s' (confidence=%.2f)", i, fi.label, fi.confidence)

    # ==========================================
    # STEP 3: Scale & Orientation (STUB)
    # ==========================================
    logger.info("[STEP 3] Scale & Orientation (STUB)")
    detected_scale = extract_scale(full_image, logger=logger)
    detected_orientation = extract_orientation(full_image, logger=logger)
    effective_scale = scale or detected_scale

    # ==========================================
    # STEP 4 + 5: Per-floor processing
    # ==========================================
    floors_data = []

    for i, floor_img in enumerate(floor_images):
        floor_name = floor_img.label.replace(" ", "_")
        floor_debug_dir = output_dir / f"floor_{i}_{floor_name}"
        floor_debug_dir.mkdir(parents=True, exist_ok=True)

        # STEP 4: Line & Text Extraction
        logger.info("[STEP 4] Lines & Text for floor %d: '%s'", i, floor_img.label)
        extraction = extract_lines_and_text(
            floor_img.image,
            debug_dir=floor_debug_dir / "step4_extraction",
            logger=logger,
        )

        # Save debug visualizations
        save_debug_image(
            draw_segments_on_image(floor_img.image, extraction.segments),
            floor_debug_dir / "step4_segments.png",
            logger,
        )
        save_debug_image(
            draw_text_blocks_on_image(floor_img.image, extraction.text_blocks),
            floor_debug_dir / "step4_text_blocks.png",
            logger,
        )
        logger.info("  %d segments, %d text blocks",
                    len(extraction.segments), len(extraction.text_blocks))

        # STEP 5: Semantic Analysis
        logger.info("[STEP 5] Semantic Analysis for floor %d", i)
        analyzer = SemanticAnalyzer(logger=logger)
        dcel, rooms = analyzer.analyze(
            extraction.segments,
            extraction.text_blocks,
            image_shape=floor_img.image.shape[:2],
            debug_dir=floor_debug_dir / "step5_analysis",
            logger=logger,
        )
        logger.info("  %d rooms identified", len(rooms))

        floors_data.append({
            "label": floor_img.label,
            "confidence": floor_img.confidence,
            "source_rect": floor_img.source_rect,
            "rooms": rooms,
            "dcel": dcel,
        })

    # ==========================================
    # STEP 6: Export
    # ==========================================
    logger.info("[STEP 6] Export Knowledge Model")
    model = build_knowledge_model(
        source_file=str(input_path),
        floors_data=floors_data,
        scale=effective_scale,
        orientation=detected_orientation,
        render_dpi=dpi,
        logger=logger,
    )
    export_json(model, output_dir / "knowledge_model.json", logger=logger)

    elapsed = time.perf_counter() - t0
    logger.info("-" * 60)
    logger.info("Pipeline completed in %.1fs", elapsed)
    logger.info("Output: %s", output_dir / "knowledge_model.json")
    logger.info("=" * 60)

    return model.to_dict()


def main():
    """CLI entry point."""
    configure_tesseract()

    parser = argparse.ArgumentParser(
        description="PlanParser Pipeline v0.1 - Floor plan to Knowledge Model",
    )
    parser.add_argument("input", help="Path to PDF or image file")
    parser.add_argument("--output", "-o", help="Output directory", default=None)
    parser.add_argument("--scale", "-s", help="Scale (e.g., 1:100)", default=None)
    parser.add_argument("--page", "-p", type=int, default=0, help="PDF page index")
    parser.add_argument("--dpi", type=int, default=300, help="Rendering DPI")

    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    result = run_pipeline(
        input_path=Path(args.input),
        output_dir=out,
        scale=args.scale,
        page=args.page,
        dpi=args.dpi,
    )

    # Print summary
    print("\n--- RESULT SUMMARY ---")
    meta = result.get("meta", {})
    print(f"Source: {meta.get('source_file', '?')}")
    print(f"Scale: {meta.get('scale', 'not set')}")

    for floor in result.get("floors", []):
        print(f"\nFloor: {floor.get('label', '?')}")
        rooms = floor.get("rooms", [])
        print(f"  Rooms: {len(rooms)}")
        for room in rooms:
            label = room.get("label", "unlabeled")
            area = room.get("area_px", 0)
            n_walls = len(room.get("walls", []))
            print(f"    - {label}: area_px={area:.0f}, walls={n_walls}")


if __name__ == "__main__":
    main()
