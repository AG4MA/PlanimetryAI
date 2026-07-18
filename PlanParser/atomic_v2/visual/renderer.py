"""Render review sheets without altering source images or decomposition data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "source_region": "#00AEEF",
    "text": "#19A54A",
    "geometry": "#E53935",
    "architectural_candidate": "#FF8C00",
    "symbol": "#8E44AD",
    "measurement": "#795548",
    "relationship": "#1565C0",
    "abstained": "#D000D0",
}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail((width, height), Image.Resampling.LANCZOS)
    return copy


def _sheet(left: Image.Image, right: Image.Image, title: str, subtitle: str, notes: Iterable[str]) -> Image.Image:
    page_w, page_h = 2400, 1600
    margin, header, footer, gap = 70, 170, 250, 40
    panel_w = (page_w - 2 * margin - gap) // 2
    panel_h = page_h - header - footer
    canvas = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 30), title, fill="#B00020", font=_font(38, True))
    draw.text((margin, 82), subtitle, fill="#333333", font=_font(24))
    draw.text((margin, 128), "ORIGINALE", fill="#111111", font=_font(24, True))
    draw.text((margin + panel_w + gap, 128), "OVERLAY / DIAGNOSTICA", fill="#111111", font=_font(24, True))
    for x, img in ((margin, left), (margin + panel_w + gap, right)):
        fitted = _fit(img, panel_w, panel_h)
        y = header + (panel_h - fitted.height) // 2
        canvas.paste(fitted, (x + (panel_w - fitted.width) // 2, y))
        draw.rectangle((x, header, x + panel_w, header + panel_h), outline="#777777", width=2)
    y = page_h - footer + 24
    for note in notes:
        draw.text((margin, y), note, fill="#222222", font=_font(21))
        y += 32
    return canvas


def _legend_notes(missing: Iterable[str] = ()) -> list[str]:
    keys = [
        "Legenda: azzurro=regioni | verde=OCR | rosso=pareti/geometria | arancio=stanze/aperture",
        "viola=simboli | blu=relazioni | magenta=astensione. Etichette: classe, confidenza.",
    ]
    missing = list(missing)
    if missing:
        keys.append("DATI MANCANTI (non inferiti): " + "; ".join(missing))
    return keys


def render_legacy_baseline(base_path: Path, selected_path: Path, graph_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = Image.open(base_path).convert("RGB")
    selected = Image.open(selected_path).convert("RGB")
    graph = Image.open(graph_path).convert("RGB")
    missing = ["poligoni stanza", "assi parete", "aperture", "confidenze", "astensioni"]
    common = _legend_notes(missing)
    page1 = _sheet(
        base,
        selected,
        "BASELINE LEGACY NON APPROVATA",
        "Section 1 - OCR/candidati selezionati; nessuna validazione geometrica implicita",
        common,
    )
    page2 = _sheet(
        base,
        graph,
        "BASELINE LEGACY NON APPROVATA",
        "Section 1 - grafo legacy; le linee blu non attestano adiacenze fisiche",
        common + ["ATTENZIONE: relazioni legacy mostrate come diagnostica, non come risultato approvato."],
    )
    page1.save(output_dir / "baseline_review_page_1.png")
    page2.save(output_dir / "baseline_review_page_2.png")
    pdf_path = output_dir / "baseline_review.pdf"
    page1.save(pdf_path, "PDF", resolution=150.0, save_all=True, append_images=[page2])
    return pdf_path


def _draw_observation(draw: ImageDraw.ImageDraw, obs: dict, scale_x: float, scale_y: float) -> tuple[float, float] | None:
    geometry = obs.get("geometry") or {}
    layer = obs.get("layer", "geometry")
    confidence = obs.get("confidence") or {}
    abstained = bool(confidence.get("abstained", False))
    color = COLORS["abstained"] if abstained else COLORS.get(layer, "#333333")
    width = 7 if abstained else 4
    points = [(float(x) * scale_x, float(y) * scale_y) for x, y in geometry.get("points", [])]
    bbox = geometry.get("bbox")
    center = None
    if bbox:
        x, y, w, h = map(float, bbox)
        rect = (x * scale_x, y * scale_y, (x + w) * scale_x, (y + h) * scale_y)
        draw.rectangle(rect, outline=color, width=width)
        center = ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
    elif points:
        kind = geometry.get("type")
        if kind == "point":
            x, y = points[0]
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=color, width=width)
        else:
            path = points + ([points[0]] if kind == "polygon" else [])
            draw.line(path, fill=color, width=width, joint="curve")
        center = points[0]
    if center:
        score = confidence.get("score")
        score_text = "?" if score is None else f"{float(score):.2f}"
        label = f"{obs.get('class_id', 'classe?')} c={score_text}" + (" ASTENUTO" if abstained else "")
        draw.text((center[0] + 5, center[1] + 5), label, fill=color, font=_font(18, True), stroke_width=2, stroke_fill="white")
    return center


def render_contract_review(image_path: Path, decomposition_path: Path, output_dir: Path, page_index: int = 0) -> Path:
    document = json.loads(decomposition_path.read_text(encoding="utf-8"))
    pages = document.get("pages") or []
    if page_index >= len(pages):
        raise ValueError(f"page_index {page_index} non presente nel contratto")
    page = pages[page_index]
    original = Image.open(image_path).convert("RGB")
    overlay = original.copy()
    draw = ImageDraw.Draw(overlay)
    source_w = float(page.get("width_px") or original.width)
    source_h = float(page.get("height_px") or original.height)
    sx, sy = original.width / source_w, original.height / source_h
    centers = {}
    layers = set()
    for obs in page.get("observations") or []:
        layers.add(obs.get("layer"))
        centers[obs.get("id")] = _draw_observation(draw, obs, sx, sy)
    for rel in page.get("relationships") or []:
        a, b = centers.get(rel.get("from_id")), centers.get(rel.get("to_id"))
        if a and b:
            draw.line((a, b), fill=COLORS["relationship"], width=3)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            draw.text(mid, f"{rel.get('type', '?')} c={float(rel.get('confidence', 0)):.2f}", fill=COLORS["relationship"], font=_font(17, True), stroke_width=2, stroke_fill="white")
    expected = {"source_region", "text", "geometry", "architectural_candidate"}
    missing = [f"layer {name}" for name in sorted(expected - layers)]
    if not page.get("relationships"):
        missing.append("relazioni")
    sheet = _sheet(original, overlay, "REVISIONE DECOMPOSIZIONE ATOMICA", f"Pagina contratto {page_index}", _legend_notes(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"contract_review_page_{page_index}.png"
    pdf_path = output_dir / f"contract_review_page_{page_index}.pdf"
    sheet.save(png_path)
    sheet.save(pdf_path, "PDF", resolution=150.0)
    return pdf_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Renderer isolato per revisione visiva PlanParser atomic_v2")
    sub = parser.add_subparsers(dest="mode", required=True)
    legacy = sub.add_parser("legacy-baseline")
    legacy.add_argument("--base", type=Path, required=True)
    legacy.add_argument("--selected", type=Path, required=True)
    legacy.add_argument("--graph", type=Path, required=True)
    legacy.add_argument("--output-dir", type=Path, required=True)
    contract = sub.add_parser("contract")
    contract.add_argument("--image", type=Path, required=True)
    contract.add_argument("--decomposition", type=Path, required=True)
    contract.add_argument("--output-dir", type=Path, required=True)
    contract.add_argument("--page-index", type=int, default=0)
    args = parser.parse_args()
    if args.mode == "legacy-baseline":
        result = render_legacy_baseline(args.base, args.selected, args.graph, args.output_dir)
    else:
        result = render_contract_review(args.image, args.decomposition, args.output_dir, args.page_index)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
