"""
PlanParser CLI
==============
Command-line interface for parsing planimetry files.
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import OutputConfig, PlanParserConfig, ScaleConfig, SourceType
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
        description="PlanParser - Parse planimetry files to extract floor plans, rooms, and geometry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m PlanParser parse data/scheda_catastale.pdf
  python -m PlanParser parse plan.dwg --source-type dwg
  python -m PlanParser parse photo.jpg --noscale
  python -m PlanParser parse data/plan.pdf --scale 100 --output results/
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Parse command
    parse_cmd = subparsers.add_parser("parse", help="Parse a planimetry file")

    # Input file (positional, required)
    parse_cmd.add_argument(
        "input_file", type=str,
        help="Path to planimetry file (PDF, image, DWG, DXF)"
    )
    
    # Source type (optional - auto-detected from extension)
    parse_cmd.add_argument(
        "--source-type", "-t",
        choices=["pdf", "image", "dwg", "dxf"],
        help="Input file type (auto-detected if not specified)"
    )
    
    # Scale options
    scale_group = parse_cmd.add_mutually_exclusive_group()
    scale_group.add_argument(
        "--scale", "-s", type=float,
        help="Scale ratio (e.g., 100 for 1:100). If not provided, auto-detection is attempted."
    )
    scale_group.add_argument(
        "--noscale", action="store_true",
        help="Skip scale detection and use default (1:100). For testing purposes."
    )

    # Compass/orientation options
    compass_group = parse_cmd.add_mutually_exclusive_group()
    compass_group.add_argument(
        "--compass", "-c", type=float,
        help="North angle in degrees (0=up, 90=right, 180=down, 270=left). If not provided, auto-detection is attempted."
    )
    compass_group.add_argument(
        "--nocompass", action="store_true",
        help="Skip compass detection and use default (0° = north is up). For testing purposes."
    )

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

    # Extract-lines command (for debugging/development)
    lines_cmd = subparsers.add_parser("extract-lines", help="Extract line segments from image (debug)")
    lines_cmd.add_argument("input_file", type=str, help="Path to image or PDF file")
    lines_cmd.add_argument("--output", "-o", type=str, default="./debug_image/lines_debug.png",
                          help="Output visualization path")
    lines_cmd.add_argument("--min-length", type=int, default=30, help="Minimum line length in pixels")
    lines_cmd.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "parse":
        run_parse(args)
    elif args.command == "info":
        run_info(args)
    elif args.command == "extract-lines":
        run_extract_lines(args)


def run_extract_lines(args):
    """Execute extract-lines command for debugging line extraction."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    from pathlib import Path
    import cv2
    from .extraction import LineExtractor, LineExtractionConfig
    from .pdf_reader import render_pdf_page
    
    input_path = Path(args.input_file)
    output_path = Path(args.output)
    
    if not input_path.exists():
        print(f"❌ File not found: {input_path}")
        sys.exit(1)
    
    # Load image (from PDF or direct)
    if input_path.suffix.lower() == ".pdf":
        print(f"📄 Rendering PDF: {input_path}")
        image = render_pdf_page(input_path, page_num=0, zoom=2.0)
        if image is None:
            print("❌ Failed to render PDF")
            sys.exit(1)
    else:
        print(f"🖼️  Loading image: {input_path}")
        image = cv2.imread(str(input_path))
        if image is None:
            print(f"❌ Failed to load image: {input_path}")
            sys.exit(1)
    
    print(f"   Image size: {image.shape[1]}x{image.shape[0]} px")
    
    # Configure and extract
    config = LineExtractionConfig(
        min_line_length=args.min_length
    )
    
    extractor = LineExtractor(config)
    
    print("🔍 Extracting lines...")
    result = extractor.extract(image)
    
    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Visualize
    extractor.visualize(image, result, output_path)
    
    # Print results
    print("\n" + "=" * 50)
    print("LINE EXTRACTION RESULT")
    print("=" * 50)
    print(f"Total lines: {result.total_count}")
    print(f"  Horizontal: {len(result.horizontal_lines)} (green)")
    print(f"  Vertical:   {len(result.vertical_lines)} (blue)")
    print(f"  Diagonal:   {len(result.diagonal_lines)} (red)")
    print(f"\n📊 Visualization saved to: {output_path}")
    
    if args.verbose:
        print("\n--- Line Details ---")
        for i, line in enumerate(result.lines[:20]):  # First 20
            print(f"  {i+1}: ({line.x1},{line.y1})->({line.x2},{line.y2}) "
                  f"len={line.length:.1f} angle={line.angle_degrees:.1f}° [{line.orientation.value}]")
        if len(result.lines) > 20:
            print(f"  ... and {len(result.lines) - 20} more")


def run_parse(args):
    """Execute parse command."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    input_path = Path(args.input_file)
    
    # Validate input file exists
    if not input_path.exists():
        print(f"❌ Error: File not found: {input_path}")
        sys.exit(1)
    
    # Determine source type
    if args.source_type:
        source_type = SourceType(args.source_type)
    else:
        try:
            source_type = SourceType.from_extension(input_path)
            logger.info(f"Auto-detected source type: {source_type.value}")
        except ValueError as e:
            print(f"❌ Error: {e}")
            print("Use --source-type to specify the file type manually.")
            sys.exit(1)
    
    # Build scale configuration
    scale_config = ScaleConfig()
    use_default_scale = False
    use_default_compass = False
    
    if args.scale:
        # User provided explicit scale
        scale_config.scale_ratio = args.scale
        scale_config.scale_detected = False  # Not auto-detected
        logger.info(f"Using user-provided scale: 1:{int(args.scale)}")
    elif args.noscale:
        # Use default scale without detection
        use_default_scale = True
        logger.info(f"Using default scale: 1:{int(scale_config.default_scale_ratio)} (--noscale)")
    else:
        # Will attempt auto-detection during parsing
        logger.info("Scale will be auto-detected from planimetry")
    
    # Handle compass/orientation options
    if args.compass is not None:
        # User provided explicit north angle
        scale_config.north_angle_degrees = args.compass % 360  # Normalize to 0-360
        scale_config.orientation_detected = False
        logger.info(f"Using user-provided compass: {scale_config.north_angle_degrees}°")
    elif args.nocompass:
        # Use default orientation without detection
        use_default_compass = True
        logger.info(f"Using default compass: {scale_config.default_north_angle}° (--nocompass)")
    else:
        # Will attempt auto-detection during parsing
        logger.info("Compass will be auto-detected from planimetry")

    # Build configuration
    config = PlanParserConfig(
        source_type=source_type,
        scale=scale_config,
        use_default_scale=use_default_scale,
        use_default_compass=use_default_compass,
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

    # Parse based on source type
    logger.info(f"Parsing {source_type.value.upper()}: {input_path}")
    
    if source_type == SourceType.PDF:
        result = plan_parser.parse(input_path, page_num=args.page, floor_anchor=args.anchor)
    elif source_type == SourceType.IMAGE:
        result = plan_parser.parse_image(input_path, floor_anchor=args.anchor)
    elif source_type in (SourceType.DWG, SourceType.DXF):
        # TODO: Implement DWG/DXF parsing
        print(f"⚠️  {source_type.value.upper()} parsing not yet implemented")
        print("Supported formats: PDF, IMAGE (png, jpg, tiff, bmp)")
        sys.exit(1)
    else:
        print(f"❌ Unsupported source type: {source_type}")
        sys.exit(1)

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
            print(f"Source type: {source_type.value}")
            
            # Scale info
            if result.metadata.get("scale"):
                scale_info = result.metadata["scale"]
                print(f"Scale: 1:{int(scale_info.get('ratio', 100))} ", end="")
                print("(detected)" if scale_info.get("detected") else "(default/user)")
            
            # Orientation info
            if result.metadata.get("orientation"):
                orient_info = result.metadata["orientation"]
                angle = orient_info.get("north_angle_degrees", 0)
                print(f"Orientation: {angle}° ", end="")
                print("(detected)" if orient_info.get("detected") else "(default/user)")
            
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
