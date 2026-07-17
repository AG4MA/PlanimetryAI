"""Official Point 1 CLI: PDF/image to atomic decomposition JSON."""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

import cv2

from .decomposition import assert_valid_decomposition
from .decomposition.exporter import build_document, build_page_record, media_type


LEGACY_PIPELINE_DIR = Path(__file__).parent / "test_26-02-07_v0.1"
if str(LEGACY_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_PIPELINE_DIR))

from debug_utils import setup_logger  # noqa: E402
from step1_pdf_to_image import pdf_to_image  # noqa: E402
from step2_floor_detection import split_floors  # noqa: E402
from step4_line_text_extraction import extract_lines_and_text  # noqa: E402
from step5_semantic_analysis import SemanticAnalyzer  # noqa: E402


def source_page_count(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 1
    import fitz

    with fitz.open(str(path)) as document:
        return len(document)


def decompose_file(
    input_path: Path,
    *,
    output_path: Path,
    dpi: int = 300,
    debug_dir: Path | None = None,
) -> dict:
    """Run the current Point 1 stack and emit a validated draft document."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input does not exist: {input_path}")
    media_type(input_path)
    if dpi <= 0:
        raise ValueError("dpi must be positive")

    logger = setup_logger("decomposition", output_path.parent / "logs")
    page_records = []
    warnings: list[str] = []

    for page_index in range(source_page_count(input_path)):
        logger.info("[P1] Page %d: render and decompose", page_index)
        page_image = pdf_to_image(input_path, page=page_index, dpi=dpi, logger=logger)
        page_debug = Path(debug_dir) / f"page_{page_index}" if debug_dir else None
        floor_images = split_floors(
            page_image,
            debug_dir=page_debug / "floors" if page_debug else None,
            logger=logger,
        )

        floor_results = []
        for floor_index, floor in enumerate(floor_images):
            floor_debug = page_debug / f"floor_{floor_index}" if page_debug else None
            extraction = extract_lines_and_text(
                floor.image,
                debug_dir=floor_debug / "extraction" if floor_debug else None,
                logger=logger,
            )
            analyzer = SemanticAnalyzer(logger=logger)
            _, rooms = analyzer.analyze(
                extraction.segments,
                extraction.text_blocks,
                image_shape=floor.image.shape[:2],
                debug_dir=floor_debug / "semantic" if floor_debug else None,
                logger=logger,
            )
            floor_results.append({
                "floor": floor,
                "extraction": extraction,
                "rooms": rooms,
            })

        page_record, page_warnings = build_page_record(
            page_index=page_index,
            width_px=page_image.shape[1],
            height_px=page_image.shape[0],
            render_dpi=dpi if input_path.suffix.lower() == ".pdf" else None,
            floor_results=floor_results,
            cv_version=cv2.__version__,
        )
        page_records.append(page_record)
        warnings.extend(page_warnings)

    document = build_document(
        source_path=input_path,
        page_records=page_records,
        warnings=warnings,
        render_dpi=dpi,
        model_versions={
            "line_extraction": f"opencv-{cv2.__version__}",
            "semantic_analyzer": "heuristic-0.1.0",
            "ocr": "tesseract-if-available",
        },
    )
    assert_valid_decomposition(document)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return document


def _summary(document: dict) -> str:
    counts: dict[str, int] = {}
    for page in document["pages"]:
        for observation in page["observations"]:
            layer = observation["layer"]
            counts[layer] = counts.get(layer, 0) + 1
    rendered = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    return rendered or "no observations"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PlanParser Point 1: decompose a PDF/image into source-linked atoms"
    )
    parser.add_argument("input", type=Path, help="PDF or supported raster image")
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("decomposition.json"),
        help="Output JSON path (default: decomposition.json)",
    )
    parser.add_argument("--dpi", type=int, default=300, help="PDF render DPI")
    parser.add_argument(
        "--debug-dir", type=Path, default=None,
        help="Optional directory for intermediate debug artifacts",
    )
    args = parser.parse_args(argv)
    document = decompose_file(
        args.input,
        output_path=args.output,
        dpi=args.dpi,
        debug_dir=args.debug_dir,
    )
    print(f"Decomposition: {args.output}")
    print(f"Pages: {len(document['pages'])}; {_summary(document)}")
    print(f"Warnings: {len(document.get('warnings', []))}")
    print("Status: draft (Point 1; not a formal model and not a technical project)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
