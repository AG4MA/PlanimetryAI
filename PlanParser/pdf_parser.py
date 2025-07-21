import fitz  # PyMuPDF
from typing import Tuple, List


def detect_plan_frame(pdf_path: str, page_number: int = 0) -> Tuple[float, float, float, float]:
    doc = fitz.open(pdf_path)
    page = doc[page_number]

    all_boxes: List[Tuple[float, float, float, float]] = []

    # 1. Blocchi testuali
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, *_ = block
        all_boxes.append((x0, y0, x1, y1))

    # 2. Disegni vettoriali
    for d in page.get_drawings():
        for path in d["items"]:
            if path[0] != "l":  # 'l' = line
                continue
            for segment in path[1]:
                x0, y0 = segment[0]
                x1, y1 = segment[1]
                all_boxes.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    # 3. Calcolo bounding box complessiva
    if not all_boxes:
        raise ValueError("Nessun contenuto grafico rilevato.")

    x_min = min(b[0] for b in all_boxes)
    y_min = min(b[1] for b in all_boxes)
    x_max = max(b[2] for b in all_boxes)
    y_max = max(b[3] for b in all_boxes)

    return (x_min, y_min, x_max, y_max)
