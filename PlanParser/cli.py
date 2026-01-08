"""
PlanParser CLI
==============
Command-line interface for parsing planimetry files.
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import OutputConfig, PlanParserConfig
from .parser import PlanParser


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="PlanParser - Parse planimetry PDFs to extract floor plans and rooms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m PlanParser parse --pdf data/scheda_catastale.pdf
  python -m PlanParser parse --pdf data/plan.pdf --anchor down --output results/
  python -m PlanParser parse --image debug_image/section.png
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Parse command
    parse_cmd = subparsers.add_parser("parse", help="Parse a planimetry file")

    input_group = parse_cmd.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--pdf", type=str, help="Path to PDF file")
    input_group.add_argument("--image", type=str, help="Path to image file")

    parse_cmd.add_argument(
        "--page", type=int, default=0,
        help="PDF page number (0-indexed, default: 0)"
    )
    parse_cmd.add_argument(
        "--anchor", choices=["up", "down"], default="up",
        help="Floor split line position relative to label (default: up)"
    )
    parse_cmd.add_argument(
        "--zoom", type=float, default=2.0,
        help="PDF rendering zoom factor (default: 2.0)"
    )
    parse_cmd.add_argument(
        "--output", "-o", type=str, default="./planimetry_output",
        help="Output directory (default: ./planimetry_output)"
    )
    parse_cmd.add_argument(
        "--debug-dir", type=str, default="./debug_image",
        help="Debug images directory (default: ./debug_image)"
    )
    parse_cmd.add_argument(
        "--json", action="store_true",
        help="Output result as JSON"
    )
    parse_cmd.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    parse_cmd.add_argument(
        "--no-debug-images", action="store_true",
        help="Don't save intermediate debug images"
    )
    parse_cmd.add_argument(
        "--tesseract-path", type=str,
        help="Path to Tesseract executable (if not in PATH)"
    )

    # Info command
    info_cmd = subparsers.add_parser("info", help="Show PDF information")
    info_cmd.add_argument("pdf", type=str, help="Path to PDF file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "parse":
        run_parse(args)
    elif args.command == "info":
        run_info(args)


def run_parse(args):
    """Execute parse command."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Build configuration
    config = PlanParserConfig(
        pdf_zoom=args.zoom,
        output=OutputConfig(
            debug_dir=Path(args.debug_dir),
            output_dir=Path(args.output),
            save_intermediate=not args.no_debug_images,
            log_level="DEBUG" if args.verbose else "INFO"
        )
    )

    if args.tesseract_path:
        config.ocr.tesseract_path = args.tesseract_path

    # Create parser
    plan_parser = PlanParser(config)

    # Parse
    if args.pdf:
        logger.info(f"Parsing PDF: {args.pdf}")
        result = plan_parser.parse(args.pdf, page_num=args.page, floor_anchor=args.anchor)
    else:
        logger.info(f"Parsing image: {args.image}")
        result = plan_parser.parse_image(args.image, floor_anchor=args.anchor)

    # Output results
    if args.json:
        print(result.to_json())
    else:
        print("\n" + "=" * 60)
        print("PARSING RESULT")
        print("=" * 60)

        if result.success:
            print("✅ SUCCESS")
            print(f"Source: {result.source_file}")
            print(f"Floors detected: {len(result.floors)}")

            for floor in result.floors:
                print(f"\n📍 {floor.floor_label} (confidence: {floor.confidence:.0%})")
                print(f"   Rooms: {len(floor.rooms)}")
                for room in floor.rooms:
                    print(f"   - {room['label']}: bbox={room['bbox']}, conf={room.get('confidence', 0):.0%}")

            if result.debug_images:
                print(f"\n🖼️  Debug images saved to: {args.debug_dir}")
        else:
            print("❌ FAILED")
            for error in result.errors:
                print(f"   Error: {error}")

        print("=" * 60)

    # Save JSON result
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(result.to_json())

    logger.info(f"Result saved to: {json_path}")

    sys.exit(0 if result.success else 1)


def run_info(args):
    """Show PDF information."""
    from .pdf_reader import extract_text_from_pdf, get_pdf_metadata, get_pdf_page_count

    pdf_path = Path(args.pdf)

    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    print(f"\nPDF Info: {pdf_path}")
    print("-" * 40)

    # Page count
    pages = get_pdf_page_count(pdf_path)
    print(f"Pages: {pages}")

    # Metadata
    meta = get_pdf_metadata(pdf_path)
    if meta:
        print(f"Page size: {meta.get('page_width', 'N/A')} x {meta.get('page_height', 'N/A')}")
        if meta.get('title'):
            print(f"Title: {meta['title']}")
        if meta.get('author'):
            print(f"Author: {meta['author']}")

    # Embedded text
    text = extract_text_from_pdf(pdf_path)
    if text:
        print(f"Embedded text: {len(text)} characters")
        preview = text[:200].replace('\n', ' ')
        print(f"Preview: {preview}...")
    else:
        print("Embedded text: None (will require OCR)")


if __name__ == "__main__":
    main()
