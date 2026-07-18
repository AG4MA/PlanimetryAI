from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import ENGINE_VERSION


COLORS: tuple[tuple[int, int, int], ...] = (
    (37, 99, 235),
    (22, 163, 74),
    (234, 88, 12),
    (147, 51, 234),
    (8, 145, 178),
    (190, 24, 93),
    (101, 163, 13),
    (202, 138, 4),
)

ROLE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "space_name_seed": (22, 163, 74, 255),
    "contained_object_label": (37, 99, 235, 255),
    "external_context_label": (147, 51, 234, 255),
    "border_context_unresolved": (220, 38, 38, 255),
    "unresolved_text": (245, 158, 11, 255),
}


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def pil_from_bgr(image: np.ndarray) -> Image.Image:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a three-channel BGR image")
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def encode_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def encode_pdf(images: Sequence[Image.Image]) -> bytes:
    if not images:
        raise ValueError("At least one image is required to encode a PDF")
    converted = [image.convert("RGB") for image in images]
    buffer = BytesIO()
    converted[0].save(
        buffer,
        format="PDF",
        resolution=150.0,
        save_all=True,
        append_images=converted[1:],
    )
    return buffer.getvalue()


def draw_text_nodes(source: Image.Image, nodes: Sequence[dict[str, Any]]) -> Image.Image:
    output = source.convert("RGB").copy()
    draw = ImageDraw.Draw(output, "RGBA")
    for node in nodes:
        x1, y1, x2, y2 = map(float, node["bbox_crop_px_xyxy"])
        color = ROLE_COLORS.get(node.get("role_hypothesis", ""), (107, 114, 128, 255))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        cx, cy = map(float, node["center_crop_px"])
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
        label = str(node.get("id", "text"))
        if label.startswith("text_node_"):
            label = "T" + label.removeprefix("text_node_")
        label = label[:24]
        label_width = max(36, len(label) * 7)
        top = max(0.0, y1 - 16)
        draw.rectangle((x1, top, x1 + label_width, max(top + 14, y1 - 1)), fill=(255, 255, 255, 230))
        draw.text((x1 + 2, top), label, fill=color, font=load_font(10, True))
        if node.get("semantic_role_abstained"):
            draw.line((x1, y1, x2, y2), fill=(220, 38, 38, 230), width=2)
    return output


def draw_barriers(
    source: Image.Image,
    observed: np.ndarray,
    synthetic_closures: np.ndarray,
    *,
    crop_boundary: np.ndarray | None = None,
) -> Image.Image:
    base = np.asarray(source.convert("RGB"), dtype=np.uint8)
    if observed.shape != base.shape[:2] or synthetic_closures.shape != base.shape[:2]:
        raise ValueError("Barrier layers must match the source raster size")
    overlay = base.copy()
    overlay[observed > 0] = np.asarray([37, 99, 235], dtype=np.uint8)
    overlay[synthetic_closures > 0] = np.asarray([217, 70, 239], dtype=np.uint8)
    if crop_boundary is not None:
        if crop_boundary.shape != base.shape[:2]:
            raise ValueError("Crop-boundary layer must match the source raster size")
        overlay[crop_boundary > 0] = np.asarray([75, 85, 99], dtype=np.uint8)
    blended = cv2.addWeighted(base, 0.56, overlay, 0.44, 0)
    return Image.fromarray(blended)


def _space_label(space: dict[str, Any], fallback: int) -> int:
    value = space.get("space_label_index")
    if value is not None:
        return int(value)
    identifier = str(space.get("id", ""))
    try:
        return int(identifier.rsplit("_", 1)[-1])
    except ValueError:
        return fallback


def draw_topology(
    source: Image.Image,
    labels: np.ndarray,
    nodes: Sequence[dict[str, Any]],
    spaces: Sequence[dict[str, Any]],
) -> Image.Image:
    base = np.asarray(source.convert("RGB"), dtype=np.uint8)
    if labels.shape != base.shape[:2]:
        raise ValueError("Topology labels must match the source raster size")
    overlay = base.copy()
    for index, space in enumerate(spaces, 1):
        label = _space_label(space, index)
        overlay[labels == label] = np.asarray(COLORS[(index - 1) % len(COLORS)], dtype=np.uint8)
    blended = cv2.addWeighted(base, 0.62, overlay, 0.38, 0)
    output = Image.fromarray(blended)
    draw = ImageDraw.Draw(output, "RGBA")
    node_by_id = {str(node["id"]): node for node in nodes}
    for index, space in enumerate(spaces, 1):
        node = node_by_id.get(str(space.get("name_text_node_id")))
        if node is None:
            continue
        seed = node.get("expansion_seed_crop_px")
        if not seed:
            continue
        color = (*COLORS[(index - 1) % len(COLORS)], 255)
        for ray in space.get("radial_boundary_observations", []):
            hit = ray.get("hit_crop_px")
            if hit:
                draw.line((tuple(seed), tuple(hit)), fill=(*color[:3], 150), width=1)
                hx, hy = hit
                draw.ellipse((hx - 3, hy - 3, hx + 3, hy + 3), fill=color)
        sx, sy = seed
        draw.ellipse((sx - 7, sy - 7, sx + 7, sy + 7), fill=color, outline=(255, 255, 255, 255), width=2)
        label = f"{space.get('id', 'space')} {space.get('name_hypothesis') or 'senza nome'}"
        label_width = min(max(100, len(label) * 6), 300)
        draw.rectangle((sx + 8, sy - 9, sx + 8 + label_width, sy + 8), fill=(255, 255, 255, 225))
        draw.text((sx + 10, sy - 8), label, fill=color, font=load_font(9, True))
    return output


def panel(image: Image.Image, title: str, subtitle: str) -> Image.Image:
    header = 74
    output = Image.new("RGB", (image.width, image.height + header), "white")
    output.paste(image.convert("RGB"), (0, header))
    draw = ImageDraw.Draw(output)
    draw.rectangle((0, 0, output.width - 1, output.height - 1), outline="#9ca3af", width=2)
    draw.text((11, 8), title, fill="#111827", font=load_font(20, True))
    draw.text((11, 40), subtitle, fill="#4b5563", font=load_font(13))
    return output


def build_region_contact_sheet(
    *,
    region_id: str,
    source: Image.Image,
    text_overlay: Image.Image,
    barrier_overlay: Image.Image,
    topology_overlay: Image.Image,
    nodes: Sequence[dict[str, Any]],
    spaces: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    profile_id: str,
) -> Image.Image:
    panels = (
        panel(source, "1. SORGENTE", "raster originale: testo e geometria ancora sovrapposti"),
        panel(text_overlay, "2. NODI TESTUALI", "il testo è una rete semantica separata dalle linee"),
        panel(barrier_overlay, "3. LAYER DI BARRIERA", "blu=osservato; magenta=chiusura temporanea; grigio=limite crop"),
        panel(topology_overlay, "4. ESPANSIONE TOPOLOGICA", "i nomi si espandono verso evidenze geometriche tracciabili"),
    )
    gap = 18
    header = 142
    footer = 318
    cell_width = source.width
    cell_height = source.height + 74
    canvas = Image.new(
        "RGB",
        (cell_width * 2 + gap, header + cell_height * 2 + gap + footer),
        "#f3f4f6",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), f"PLANPARSER — MOTORE TOPOLOGICO CANONICO {ENGINE_VERSION}", fill="#111827", font=load_font(27, True))
    draw.text((18, 48), f"{region_id} · profilo {profile_id}", fill="#1d4ed8", font=load_font(17, True))
    draw.text(
        (18, 78),
        "Compute, rendering e pubblicazione sono separati; ogni relazione conserva la propria evidenza.",
        fill="#374151",
        font=load_font(15),
    )
    draw.text(
        (18, 108),
        f"nodi testo={len(nodes)}  semi spazio={sum(n.get('role_hypothesis') == 'space_name_seed' for n in nodes)}  "
        f"spazi={len(spaces)}  archi={len(edges)}",
        fill="#374151",
        font=load_font(15),
    )
    positions = (
        (0, header),
        (cell_width + gap, header),
        (0, header + cell_height + gap),
        (cell_width + gap, header + cell_height + gap),
    )
    for item, position in zip(panels, positions):
        canvas.paste(item, position)

    footer_y = header + cell_height * 2 + gap
    draw.rectangle((0, footer_y, canvas.width - 1, canvas.height - 1), fill="white", outline="#9ca3af", width=2)
    draw.text((18, footer_y + 14), "CONTRATTO DEL RISULTATO", fill="#111827", font=load_font(19, True))
    draw.text(
        (18, footer_y + 46),
        "Testo → nomina uno spazio candidato → lo spazio è collegato alle linee/bande che sostengono il confine.",
        fill="#374151",
        font=load_font(14),
    )
    draw.text(
        (18, footer_y + 73),
        "Osservato, chiusura temporanea, competizione fra semi e irrisolto restano cause distinte.",
        fill="#374151",
        font=load_font(14),
    )
    draw.text((18, footer_y + 108), "SPAZI", fill="#111827", font=load_font(15, True))
    for index, space in enumerate(spaces):
        column = index // 4
        row = index % 4
        composition = space.get("boundary_composition", {})
        summary = (
            f"{space.get('id')} {space.get('name_hypothesis') or '—'}  "
            f"O={float(composition.get('observed_geometry_ratio', 0.0)):.2f} "
            f"G={float(composition.get('synthetic_gap_closure_ratio', 0.0)):.2f} "
            f"C={float(composition.get('seed_competition_ratio', 0.0)):.2f}  "
            f"{'ASTENUTO' if space.get('abstained') else 'CANDIDATO'}"
        )
        draw.text(
            (18 + column * (canvas.width // 2), footer_y + 137 + row * 24),
            summary,
            fill="#991b1b" if space.get("abstained") else "#166534",
            font=load_font(12),
        )
    bounded = sum(edge.get("relation") == "bounded_by_candidate_evidence" for edge in edges)
    adjacency = sum(edge.get("relation") == "candidate_topological_adjacency" for edge in edges)
    draw.text(
        (18, footer_y + 245),
        f"Relazioni di confine={bounded}; adiacenze candidate={adjacency}. Dati completi, config e hash sono nel JSON/manifest.",
        fill="#111827",
        font=load_font(13, True),
    )
    draw.text(
        (18, footer_y + 278),
        "NON DICHIARATO: muro, porta, finestra, stanza validata, proprietà, scala metrica o nord.",
        fill="#991b1b",
        font=load_font(13, True),
    )
    return canvas


def _fit_width(image: Image.Image, width: int) -> Image.Image:
    if image.width == width:
        return image.convert("RGB")
    height = max(1, round(image.height * width / image.width))
    return image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)


def compose_batch_review(
    *,
    document_id: str,
    page_id: str,
    region_sheets: Iterable[tuple[str, Image.Image, dict[str, Any]]],
    equivalence_ok: bool,
    graph_summary: dict[str, Any],
    width: int = 1800,
) -> Image.Image:
    prepared: list[tuple[str, Image.Image, dict[str, Any]]] = [
        (region_id, _fit_width(sheet, width), summary)
        for region_id, sheet, summary in region_sheets
    ]
    header = 220
    gap = 24
    total_height = header + sum(sheet.height for _, sheet, _ in prepared) + gap * max(0, len(prepared) - 1)
    canvas = Image.new("RGB", (width, total_height), "#e5e7eb")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width - 1, header - 1), fill="#111827")
    draw.text((28, 20), "PLANPARSER — CONSOLIDAMENTO ENTERPRISE", fill="white", font=load_font(32, True))
    draw.text((28, 66), f"{document_id} / {page_id} · engine {ENGINE_VERSION}", fill="#bfdbfe", font=load_font(18, True))
    status = "EQUIVALENZA BASELINE: OK" if equivalence_ok else "EQUIVALENZA BASELINE: DIFFERENZE"
    draw.text((28, 103), status, fill="#86efac" if equivalence_ok else "#fca5a5", font=load_font(20, True))
    draw.text(
        (28, 139),
        f"grafo chiuso: nodi={graph_summary.get('node_count', 0)}  archi={graph_summary.get('edge_count', 0)}  "
        f"duplicati={graph_summary.get('duplicate_id_count', 0)}  pendenti={graph_summary.get('dangling_edge_count', 0)}",
        fill="#e5e7eb",
        font=load_font(16),
    )
    draw.text(
        (28, 172),
        "Artefatti precedenti congelati · nuovi output pubblicati in modo additivo e verificati tramite SHA-256",
        fill="#d1d5db",
        font=load_font(14),
    )
    y = header
    for _, sheet, _ in prepared:
        canvas.paste(sheet, (0, y))
        y += sheet.height + gap
    return canvas
