"""Build a versioned visual progress review from immutable atomic_v2 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail((width, height), Image.Resampling.LANCZOS)
    return copy


def _card(title: str, lines: list[str], size=(1100, 1050)) -> Image.Image:
    card = Image.new("RGB", size, "#FAFAFA")
    draw = ImageDraw.Draw(card)
    draw.rectangle((2, 2, size[0] - 3, size[1] - 3), outline="#777777", width=3)
    draw.text((40, 40), title, fill="#B00020", font=_font(32, True))
    y = 110
    for line in lines:
        draw.text((40, y), line, fill="#222222", font=_font(25))
        y += 44
    return card


def _two_crops(first: Image.Image, second: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (1100, 1050), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 15), "REGIONE 001 (identificatore, non nome piano)", fill="#222222", font=_font(24, True))
    a = _fit(first, 1020, 450)
    canvas.paste(a, ((1100 - a.width) // 2, 55))
    draw.text((20, 540), "REGIONE 002 (identificatore, non nome piano)", fill="#222222", font=_font(24, True))
    b = _fit(second, 1020, 430)
    canvas.paste(b, ((1100 - b.width) // 2, 590))
    return canvas


def _page(original: Image.Image, output: Image.Image, title: str, subtitle: str, limitations: list[str], left_label="ORIGINAL / INPUT", right_label="OUTPUT CANDIDATO - NON APPROVATO") -> Image.Image:
    width, height = 2400, 1600
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    margin, gap, header, footer = 60, 36, 175, 250
    panel_w = (width - 2 * margin - gap) // 2
    panel_h = height - header - footer
    draw.text((margin, 24), title, fill="#B00020", font=_font(37, True))
    draw.text((margin, 76), subtitle, fill="#333333", font=_font(23))
    draw.text((margin, 128), left_label, fill="#111111", font=_font(24, True))
    draw.text((margin + panel_w + gap, 128), right_label, fill="#111111", font=_font(24, True))
    for x, image in ((margin, original), (margin + panel_w + gap, output)):
        fitted = _fit(image, panel_w, panel_h)
        px = x + (panel_w - fitted.width) // 2
        py = header + (panel_h - fitted.height) // 2
        canvas.paste(fitted, (px, py))
        draw.rectangle((x, header, x + panel_w, header + panel_h), outline="#777777", width=2)
    y = height - footer + 24
    draw.text((margin, y), "LIMITI VISIBILI / STATO:", fill="#B00020", font=_font(22, True))
    y += 36
    for text in limitations:
        draw.text((margin, y), "- " + text, fill="#222222", font=_font(20))
        y += 31
    return canvas


def build(root: Path, output_dir: Path) -> Path:
    page_source = Image.open(root / "ingest/artifacts/scheda_catastale/pages/page_0001.png")
    region_dir = root / "region_split/artifacts/scheda_catastale/page_0001/revision_002"
    region_overlay = Image.open(region_dir / "regions_overlay.png")
    crop1 = Image.open(region_dir / "region_001.png")
    crop2 = Image.open(region_dir / "region_002.png")
    linework = Image.open(root / "linework/artifacts/scheda_catastale/region_001/revision_001/linework_overlay.png")
    bands = Image.open(root / "wall_bands/artifacts/scheda_catastale/region_001/revision_001/wall_bands_overlay.png")
    network1 = Image.open(root / "wall_network/artifacts/scheda_catastale/region_001/revision_001/wall_network_overlay.png")
    network2 = Image.open(root / "wall_network/artifacts/scheda_catastale/region_001/revision_002/wall_network_overlay.png")
    seeds = Image.open(root / "room_seeds/artifacts/scheda_catastale/region_001/revision_001/room_seeds_overlay.png")
    ocr_json = json.loads((root / "ocr/artifacts/scheda_catastale/region_001/revision_001/ocr.json").read_text(encoding="utf-8"))
    pdf_json = json.loads((root / "pdf_text/artifacts/scheda_catastale/region_001/revision_001/pdf_text.json").read_text(encoding="utf-8"))
    pdf_overlay = Image.open(root / "pdf_text/artifacts/scheda_catastale/region_001/revision_001/pdf_text_overlay.png")

    pages = [
        _page(page_source, region_overlay, "1. SPLIT DELLA PAGINA SORGENTE", "Riquadri automatici numerati; nessun nome piano inferito", ["due corpi planimetrici isolati; intestazione esclusa", "confidence euristica 0.956 e 0.939; output candidato non approvato"]),
        _page(page_source, _two_crops(crop1, crop2), "2. CROP DELLE DUE REGIONI", "Pixel reali ritagliati dalla pagina, senza OCR o semantica", ["piccole diciture aderenti ai bordi possono restare o essere tagliate", "gli identificatori regione non descrivono il contenuto"]),
        _page(crop1, linework, "3. LINEWORK H/V CANDIDATO", "Segmenti numerati: rosso solido, arancio incerto/astensione", ["111 segmenti: 74 solidi, 37 incerti", "testo, arredo e scala generano ancora falsi candidati; non sono pareti"]),
        _page(crop1, bands, "4. BANDE DA DOPPI BORDI", "Proposte geometriche numerate; nessuna classe interno/esterno", ["40 bande: 30 solide, 10 incerte", "gradini e arredi con doppio bordo coerente possono essere promossi"]),
        _page(network1, network2, "5. RETE GEOMETRICA - CONFRONTO REVISIONI", "Sinistra revision_001; destra revision_002 conservativa", ["revision_002 conserva 40/40 candidati: 10 primary, 20 secondary, 10 abstention", "alcuni arredi restano primary; alcune divisioni sottili sono secondary"], left_label="OUTPUT REVISION_001 - NON APPROVATO", right_label="OUTPUT REVISION_002 - NON APPROVATO"),
        _page(crop1, seeds, "6. SEMI DI SPAZIO BIANCO", "Flood-fill/morfologia: verde candidato, magenta escluso/astensione", ["7 candidati, 23 piccoli esclusi, 3 background esterni conservati", "disimpegno e area centrale possono fondersi; scala deforma un poligono", "semi geometrici: non dichiarano stanze"]),
        _page(crop1, _card("OCR RASTER: ASTENSIONE", ["status: ABSTAINED", "elementi: 0", "trascrizione: non disponibile", "confidence: non disponibile", "motivo:", *ocr_json["region"]["reasons"], "", "Nessun testo inventato."]), "7. OCR RASTER", "Astensione esplicita quando il motore non è disponibile", ["pytesseract presente ma eseguibile Tesseract non trovato", "nessun overlay OCR generato; nessun risultato implicito"]),
        _page(crop1, pdf_overlay, "8. TESTO PDF-NATIVE", "Ricerca oggetti testuali nativi nella regione del PDF", ["0 span nativi intersecanti; astensione esplicita", "il PDF contiene raster/linework senza testo nativo utile nella regione", "nessuna trascrizione o correzione inventata"]),
    ]
    output_dir.mkdir(parents=True, exist_ok=False)
    for index, page in enumerate(pages, 1):
        page.save(output_dir / f"atomic_progress_review_page_{index:02d}.png")
    pdf = output_dir / "atomic_progress_review.pdf"
    pages[0].save(pdf, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Build atomic progress visual review revision 001")
    parser.add_argument("atomic_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(build(args.atomic_root, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
