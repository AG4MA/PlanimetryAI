"""Create the additive OCR visual review pack for atomic_v2 revision 001."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont


PAGE_SIZE = (3200, 2200)
BG = "#F5F7FA"
INK = "#18212B"
MUTED = "#54606C"
ACCENT = "#A40020"
BLUE = "#1558D6"
GREEN = "#078A32"
ORANGE = "#D96A00"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        "arialbd.ttf" if bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def text_width(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), value, font=face)
    return box[2] - box[0]


def wrapped_lines(
    draw: ImageDraw.ImageDraw,
    value: str,
    face: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if text_width(draw, candidate, face) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    face: ImageFont.ImageFont,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    line_height = face.getbbox("Ag")[3] - face.getbbox("Ag")[1]
    for line in wrapped_lines(draw, value, face, max_width):
        draw.text((x, y), line, fill=fill, font=face)
        y += line_height + line_gap
    return y


def base_page(title: str, subtitle: str, page_number: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    canvas = Image.new("RGB", PAGE_SIZE, BG)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, PAGE_SIZE[0], 145), fill="#FFFFFF")
    draw.rectangle((0, 145, PAGE_SIZE[0], 154), fill=ACCENT)
    draw.text((70, 30), title, fill=INK, font=font(46, True))
    draw.text((70, 91), subtitle, fill=MUTED, font=font(26))
    draw.text((PAGE_SIZE[0] - 250, 52), f"PAG. {page_number}", fill=ACCENT, font=font(28, True))
    return canvas, draw


def paste_panel(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    note: str = "",
    title_color: str = INK,
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill="#FFFFFF", outline="#AAB3BD", width=3)
    draw.text((x0 + 25, y0 + 18), title, fill=title_color, font=font(31, True))
    if note:
        draw.text((x0 + 25, y0 + 62), note, fill=MUTED, font=font(20))
    image_top = y0 + (100 if note else 72)
    fitted = fit(image, (x1 - x0 - 50, y1 - image_top - 25))
    px = x0 + (x1 - x0 - fitted.width) // 2
    py = image_top + (y1 - image_top - fitted.height) // 2
    canvas.paste(fitted, (px, py))


def comparison_page(
    original: Image.Image,
    ppocr: Image.Image,
    doctr: Image.Image,
    guard: Image.Image,
) -> Image.Image:
    canvas, draw = base_page(
        "OCR: CONFRONTO VISIVO",
        "Stesso crop, quattro viste. Risultati candidati: nessuna approvazione implicita.",
        1,
    )
    margin, gap = 55, 35
    panel_w = (PAGE_SIZE[0] - 2 * margin - gap) // 2
    panel_h = 855
    y_a, y_b = 195, 1085
    paste_panel(canvas, draw, original, (margin, y_a, margin + panel_w, y_a + panel_h), "ORIGINALE")
    paste_panel(
        canvas,
        draw,
        ppocr,
        (margin + panel_w + gap, y_a, PAGE_SIZE[0] - margin, y_a + panel_h),
        "PP-OCRv5",
        "rosso = box OCR; etichetta blu = testo/confidenza",
        BLUE,
    )
    paste_panel(
        canvas,
        draw,
        doctr,
        (margin, y_b, margin + panel_w, y_b + panel_h),
        "docTR",
        "word_#### + testo/confidenza",
        GREEN,
    )
    paste_panel(
        canvas,
        draw,
        guard,
        (margin + panel_w + gap, y_b, PAGE_SIZE[0] - margin, y_b + panel_h),
        "GEOMETRY GUARD",
        "verde = supporto; arancio = astensione; mapping word -> TC",
        ORANGE,
    )
    draw.text(
        (70, 2055),
        "Per correggere: cita word_#### o TC-###; indica testo corretto, box errato, parola unita/divisa o testo mancante.",
        fill=ACCENT,
        font=font(27, True),
    )
    return canvas


def candidate_map_page(original: Image.Image, candidates: Image.Image) -> Image.Image:
    canvas, draw = base_page(
        "MAPPA DEI CANDIDATI TESTO",
        "Gli ID TC sono riferimenti stabili per la revisione visiva; non sono trascrizioni.",
        2,
    )
    paste_panel(canvas, draw, original, (55, 195, 1575, 1820), "ORIGINALE")
    paste_panel(
        canvas,
        draw,
        candidates,
        (1625, 195, 3145, 1820),
        "TEXT CANDIDATES",
        "verde = doppio supporto; arancio = astensione geometrica",
    )
    y = 1860
    draw.text((70, y), "COME SEGNALARE", fill=ACCENT, font=font(29, True))
    y += 48
    instructions = [
        "TC-005 corretto / testo corretto: bagno",
        "TC-010 box troppo largo / include arredo",
        "Testo mancante: descrivi la posizione e cita il TC piu vicino.",
    ]
    for item in instructions:
        draw.text((95, y), "• " + item, fill=INK, font=font(25))
        y += 42
    return canvas


def contact_sheet_page(contact_sheet: Image.Image) -> Image.Image:
    canvas, draw = base_page(
        "TILES OCR PER ID TC",
        "Ingrandimenti locali preparati per confrontare testo e geometria senza perdere il riferimento al crop.",
        3,
    )
    fitted = fit(contact_sheet, (PAGE_SIZE[0] - 120, 1820))
    px = (PAGE_SIZE[0] - fitted.width) // 2
    py = 180 + (1820 - fitted.height) // 2
    draw.rounded_rectangle((45, 175, PAGE_SIZE[0] - 45, 2015), radius=18, fill="#FFFFFF", outline="#AAB3BD", width=3)
    canvas.paste(fitted, (px, py))
    draw.text((70, 2050), "BLU = candidato geometrico", fill=BLUE, font=font(25, True))
    draw.text((710, 2050), "ROSSO = astensione", fill="#C52020", font=font(25, True))
    draw.text(
        (1320, 2050),
        "Segnala sempre TC-###; candidate non significa OCR corretto.",
        fill=ACCENT,
        font=font(25, True),
    )
    return canvas


def word_review_page(doctr: Image.Image, guard: Image.Image) -> Image.Image:
    canvas, draw = base_page(
        "REVISIONE PER WORD ID",
        "docTR propone testo e box; il guard verifica solo la compatibilita geometrica con i TC.",
        4,
    )
    paste_panel(
        canvas,
        draw,
        doctr,
        (55, 195, 1575, 1860),
        "docTR — PAROLE OCR",
        "cita word_#### per confermare o correggere",
        GREEN,
    )
    paste_panel(
        canvas,
        draw,
        guard,
        (1625, 195, 3145, 1860),
        "GUARD — word_#### -> TC-###",
        "verde supportato; arancio richiede decisione umana",
        ORANGE,
    )
    y = 1900
    draw.text((70, y), "ESEMPI DI FEEDBACK:", fill=ACCENT, font=font(28, True))
    y += 46
    draw.text(
        (90, y),
        "word_0006 e word_0007 vanno uniti  |  word_0013 e falso  |  TC-010 contiene due parole separate",
        fill=INK,
        font=font(25),
    )
    y += 42
    draw.text(
        (90, y),
        "Il verde non certifica ortografia o significato: certifica soltanto supporto geometrico.",
        fill=MUTED,
        font=font(24),
    )
    return canvas


def build(atomic_root: Path, output_dir: Path) -> Path:
    inputs = {
        "original": atomic_root / "region_split/artifacts/scheda_catastale/page_0001/revision_002/region_001.png",
        "text_candidates": atomic_root / "ocr_text_candidates/artifacts/scheda_catastale/region_001/revision_001/text_candidates_overlay.png",
        "contact_sheet": atomic_root / "ocr_tiles/artifacts/scheda_catastale/region_001/revision_001/ocr_tiles_contact_sheet.png",
        "doctr": atomic_root / "ocr_doctr/artifacts/scheda_catastale/region_001/revision_002/ocr_overlay.png",
        "ppocr": atomic_root / "ocr_heavy/artifacts/scheda_catastale/region_001/revision_004/ppocrv5_overlay_001_paddle.png",
        "guard": atomic_root / "ocr_geometry_guard/artifacts/scheda_catastale/region_001/revision_001/ocr_geometry_guard_overlay.png",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing immutable input artifacts: " + ", ".join(missing))
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing review directory: {output_dir}")

    images = {name: Image.open(path).convert("RGB") for name, path in inputs.items()}
    pages = [
        comparison_page(images["original"], images["ppocr"], images["doctr"], images["guard"]),
        candidate_map_page(images["original"], images["text_candidates"]),
        contact_sheet_page(images["contact_sheet"]),
        word_review_page(images["doctr"], images["guard"]),
    ]

    output_dir.mkdir(parents=True, exist_ok=False)
    comparison = output_dir / "ocr_comparison.png"
    pages[0].save(comparison, optimize=True)
    for index, page in enumerate(pages, 1):
        page.save(output_dir / f"ocr_review_page_{index:02d}.png", optimize=True)

    pdf = output_dir / "ocr_review.pdf"
    pages[0].save(pdf, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])

    document = fitz.open(pdf)
    for index, page in enumerate(document, 1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
        pixmap.save(output_dir / f"ocr_review_pdf_render_page_{index:02d}.png")
    document.close()

    manifest = {
        "revision": "revision_001",
        "status": "visual_review_candidate",
        "page_count": len(pages),
        "inputs_read_only": {name: str(path) for name, path in inputs.items()},
        "outputs": {
            "comparison": comparison.name,
            "pdf": pdf.name,
            "page_pngs": [f"ocr_review_page_{index:02d}.png" for index in range(1, len(pages) + 1)],
            "pdf_renders": [f"ocr_review_pdf_render_page_{index:02d}.png" for index in range(1, len(pages) + 1)],
        },
        "excluded": ["ocr_ensemble"],
    }
    (output_dir / "ocr_review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OCR visual review pack revision 001")
    parser.add_argument("atomic_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(build(args.atomic_root.resolve(), args.output_dir.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
