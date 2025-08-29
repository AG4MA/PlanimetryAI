# parse_sections_to_ifc_json.py
# Unico script: sezioni PNG -> JSON IFC-like (IfcSpace/IfcWall/IfcDoor)

import os, re, glob, json, math, argparse, uuid
from typing import List, Dict, Any, Tuple, Optional

import cv2
import numpy as np
from PIL import Image

# ---- opzionale OCR (se installato) ----
try:
    import pytesseract
    HAS_TESS = True
except Exception:
    HAS_TESS = False

# ---- shapely per poligonalizzazione ----
from shapely.geometry import LineString, MultiLineString, Polygon, Point
from shapely.ops import polygonize, unary_union

# ----------------------------- Config ----------------------------------

SECTION_PATTERN = re.compile(r"base_rectangle_section_(\d+)\.png$", re.IGNORECASE)

LABEL_MAP = [
    (re.compile(r"^camera$"), "camera"),
    (re.compile(r"^bagno$"), "bagno"),
    (re.compile(r"^dis\.?$"), "disimpegno"),
    (re.compile(r"^rip\.?$"), "ripostiglio"),
    (re.compile(r"^soggiorno[- ]?pranzo$"), "soggiorno-pranzo"),
    (re.compile(r"^vano\s*scala$"), "vano scala"),
    (re.compile(r"^balcone$"), "balcone"),
    (re.compile(r"^armadio$"), "armadio"),
    (re.compile(r"^arredo\s*fisso$"), "arredo fisso"),
]
IGNORE_TOKENS = {"stessa", "uiu", "stessa uiu"}

def ifc_guid() -> str:
    return str(uuid.uuid4()).upper()

# ----------------------------- Utility ---------------------------------

def list_section_images(directory: str = '.') -> List[Tuple[int, str]]:
    imgs = []
    for path in glob.glob(os.path.join(directory, 'base_rectangle_section_*.png')):
        m = SECTION_PATTERN.search(os.path.basename(path))
        if m:
            idx = int(m.group(1))
            imgs.append((idx, path))
    return sorted(imgs, key=lambda x: x[0])

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

# ----------------------------- Preprocess + Lines -----------------------

def preprocess(img_bgr: np.ndarray) -> Dict[str, np.ndarray]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    th = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 35, 7
    )
    kernel = np.ones((2, 2), np.uint8)
    opened = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel, iterations=1)
    edges = cv2.Canny(opened, 40, 120, apertureSize=3, L2gradient=True)
    return {'gray': gray, 'th': th, 'opened': opened, 'edges': edges}

def extract_axis_lines(binary: np.ndarray) -> Dict[str, np.ndarray]:
    h, w = binary.shape
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 40), 1))
    vert_kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 40)))
    h_lines = cv2.dilate(cv2.erode(binary, horiz_kernel, 1), horiz_kernel, 1)
    v_lines = cv2.dilate(cv2.erode(binary, vert_kernel, 1),  vert_kernel,  1)
    return {'horiz': h_lines, 'vert': v_lines, 'combined': cv2.bitwise_or(h_lines, v_lines)}

def hough_segments(edge_img: np.ndarray, min_len: int = 25, max_gap: int = 4) -> List[Tuple[int, int, int, int]]:
    segs = cv2.HoughLinesP(edge_img, 1, np.pi / 180, threshold=35,
                           minLineLength=min_len, maxLineGap=max_gap)
    if segs is None:
        return []
    return [tuple(map(int, s[0])) for s in segs]

def classify_segment(x1, y1, x2, y2) -> str:
    dx, dy = x2 - x1, y2 - y1
    angle = abs(math.degrees(math.atan2(dy, dx)))
    if angle < 10 or angle > 170: return 'horizontal'
    if 80 < angle < 100:          return 'vertical'
    return 'other'

def merge_close_segments(segments: List[Tuple[int,int,int,int]], dist_thresh=6, angle_thresh=8) -> List[Tuple[int,int,int,int]]:
    if not segments: return []
    used = [False] * len(segments)
    merged: List[Tuple[int,int,int,int]] = []

    def seg_angle(s):
        return math.degrees(math.atan2(s[3]-s[1], s[2]-s[0]))

    for i, s in enumerate(segments):
        if used[i]: continue
        x1, y1, x2, y2 = s
        ax = seg_angle(s)
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, t in enumerate(segments):
                if used[j] or j == i: continue
                bx1, by1, bx2, by2 = t
                a2 = seg_angle(t)
                # angolo simile
                if abs((ax - a2 + 180) % 360 - 180) > angle_thresh: continue
                # distanza tra bounding boxes (greedy)
                d_candidates = [
                    math.hypot(x1-bx1, y1-by1), math.hypot(x1-bx2, y1-by2),
                    math.hypot(x2-bx1, y2-by1), math.hypot(x2-bx2, y2-by2)
                ]
                if min(d_candidates) <= dist_thresh:
                    x1 = min(x1, x2, bx1, bx2)
                    y1 = min(y1, y2, by1, by2)
                    x2 = max(x1, x2, bx1, bx2)
                    y2 = max(y1, y2, by1, by2)
                    used[j] = True
                    changed = True
        merged.append((x1, y1, x2, y2))
    return merged

# ----------------------------- Polygonize (rooms) -----------------------

def polygonize_from_lines(lines: List[Tuple[int,int,int,int]], min_area: float = 1200) -> List[Polygon]:
    if not lines: return []
    mls = MultiLineString([LineString([(x1,y1),(x2,y2)]) for (x1,y1,x2,y2) in lines])
    polys = list(polygonize(mls))
    polys = [p for p in polys if p.is_valid and p.area >= min_area]
    # rimuovi poligono “contenitore” se ingloba molti altri
    if len(polys) >= 2:
        inner = [p for p in polys if sum([p.contains(q) for q in polys if q!=p]) == 0]
        if inner: polys = inner
    return sorted(polys, key=lambda p: -p.area)

# ----------------------------- OCR labels -------------------------------

def normalize_label(txt: str) -> Optional[str]:
    t = txt.strip().lower()
    if not t: return None
    if t in IGNORE_TOKENS: return None
    for rx, lab in LABEL_MAP:
        if rx.match(t): return lab
    return t

def ocr_textboxes(img_bgr: np.ndarray, lang: str = "ita", tesseract_cmd: Optional[str] = None):
    if not HAS_TESS: return []
    if tesseract_cmd: pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
    data = pytesseract.image_to_data(thr, lang=lang, output_type=pytesseract.Output.DICT)
    out = []
    for i in range(len(data["text"])):
        txt = data["text"][i].strip()
        if not txt: continue
        x,y,w,h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        out.append({"text": txt, "bbox": (x,y,x+w,y+h)})
    return out

def assign_room_labels(rooms: List[Polygon], textboxes: List[Dict[str,Any]]) -> List[Optional[str]]:
    labels = [None]*len(rooms)
    for tb in textboxes:
        x1,y1,x2,y2 = tb["bbox"]
        cx,cy = (x1+x2)/2, (y1+y2)/2
        p = Point(cx,cy)
        best_i, best_d = None, 1e18
        for i,poly in enumerate(rooms):
            if poly.contains(p):
                best_i = i; best_d = 0; break
            d = poly.exterior.distance(p)
            if d < best_d: best_i, best_d = i, d
        if best_i is not None:
            lab = normalize_label(tb["text"])
            if lab: labels[best_i] = lab
    return labels

# ----------------------------- Doors (MVP) ------------------------------

def detect_doors(edges: np.ndarray, rooms: List[Polygon]) -> List[Dict[str,Any]]:
    doors = []
    # Greedy: se due stanze sono adiacenti, cerca un "gap" lungo la bisettrice che colleghi i centroidi
    for i,a in enumerate(rooms):
        for j,b in enumerate(rooms):
            if j <= i: continue
            ca, cb = a.centroid, b.centroid
            xs = np.linspace(int(ca.x), int(cb.x), 120).astype(int)
            ys = np.linspace(int(ca.y), int(cb.y), 120).astype(int)
            zeros = 0
            for x,y in zip(xs,ys):
                x = max(0, min(edges.shape[1]-1, x))
                y = max(0, min(edges.shape[0]-1, y))
                if edges[y,x] == 0: zeros += 1
            if zeros > 80:  # soglia empirica
                doors.append({"between": (i,j), "conf": 0.3})
    return doors

# ----------------------------- Section Processing ----------------------

def process_section(idx: int, path: str, out_dir: str, min_room_area_px: int = 1200,
                    do_ocr: bool = True, tess_cmd: Optional[str] = None) -> Dict[str, Any]:
    img = cv2.imread(path)
    if img is None:
        return {'error': 'cannot_read', 'path': path, 'section_index': idx}

    prep = preprocess(img)
    axes = extract_axis_lines(prep['th'])
    hough = hough_segments(prep['edges'])

    # segmenti derivati dagli assi (contorni → segmenti centrali)
    axis_segments: List[Tuple[int,int,int,int]] = []
    for key in ('horiz','vert'):
        mask = axes[key]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x,y,w,h = cv2.boundingRect(c)
            if w < 5 and h < 5: continue
            if key == 'horiz':
                axis_segments.append((x, y + h//2, x + w, y + h//2))
            else:
                axis_segments.append((x + w//2, y, x + w//2, y + h))

    all_segments = axis_segments + hough
    merged = merge_close_segments(all_segments)

    # Poligoni (stanze)
    polys = polygonize_from_lines(merged, min_area=min_room_area_px)

    # OCR
    textboxes = ocr_textboxes(img) if (do_ocr and HAS_TESS) else []
    labels = assign_room_labels(polys, textboxes) if textboxes else [None]*len(polys)

    # Doors euristiche
    doors = detect_doors(prep['edges'], polys)

    # Debug overlay
    dbg = img.copy()
    for x1,y1,x2,y2 in merged:
        color = (0,255,0)
        ang = classify_segment(x1,y1,x2,y2)
        if ang == 'vertical': color = (255,0,0)
        elif ang == 'other': color = (0,165,255)
        cv2.line(dbg, (x1,y1), (x2,y2), color, 1)
    for k,p in enumerate(polys):
        cx,cy = int(p.centroid.x), int(p.centroid.y)
        name = labels[k] or f"room_{k+1}"
        cv2.putText(dbg, name, (cx-20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,0,200), 1, cv2.LINE_AA)
    for d in doors:
        i,j = d["between"]
        pa, pb = polys[i].centroid, polys[j].centroid
        cv2.circle(dbg, (int((pa.x+pb.x)/2), int((pa.y+pb.y)/2)), 5, (0,0,255), -1)

    ensure_dir(out_dir)
    cv2.imwrite(os.path.join(out_dir, f"section_{idx:02d}_debug.png"), dbg)

    return {
        "section_index": idx,
        "image_path": path,
        "segments": [{"x1":x1,"y1":y1,"x2":x2,"y2":y2} for (x1,y1,x2,y2) in merged],
        "rooms": [list(p.exterior.coords) for p in polys],
        "room_labels": labels,
        "doors": [{"between": d["between"], "conf": d["conf"]} for d in doors],
    }

# ----------------------------- IFC-like JSON ---------------------------

def to_ifcish(level_name: str,
              level_height_m: float,
              sections: List[Dict[str,Any]],
              units: str = "px",
              scale_px_per_m: Optional[float] = None) -> Dict[str,Any]:

    spaces = []
    walls  = []
    doors  = []

    # Raccogli entità da tutte le sezioni
    for sec in sections:
        idx = sec["section_index"]
        # Stanze
        for k, coords in enumerate(sec["rooms"]):
            name = sec["room_labels"][k] or f"section{idx}_room{k+1}"
            spaces.append({
                "type": "IfcSpace",
                "GlobalId": ifc_guid(),
                "Name": name,
                "SectionIndex": idx,
                "Representation": {"Outline": {"type": "PolyLoop", "coordinates": coords}},
                "Properties": {}
            })
        # Muri (assi) come linee 2D
        for seg in sec["segments"]:
            walls.append({
                "type": "IfcWall",
                "GlobalId": ifc_guid(),
                "SectionIndex": idx,
                "Axis": [[seg["x1"], seg["y1"]], [seg["x2"], seg["y2"]]]
            })
        # Porte
        for d in sec["doors"]:
            i,j = d["between"]
            # sicurezza su indices
            if i < len(sec["rooms"]) and j < len(sec["rooms"]):
                doors.append({
                    "type": "IfcDoor",
                    "GlobalId": ifc_guid(),
                    "SectionIndex": idx,
                    "ConnectsSpacesHint": [ # usiamo i nomi, più robusto per ora
                        sec["room_labels"][i] or f"section{idx}_room{i+1}",
                        sec["room_labels"][j] or f"section{idx}_room{j+1}"
                    ],
                    "Confidence": d.get("conf", 0.0)
                })

    plan = {
        "type": "IfcProject",
        "GlobalId": ifc_guid(),
        "UnitsInContext": {"LengthUnit": units, "ScalePxPerM": scale_px_per_m},
        "Buildings": [{
            "type": "IfcBuilding",
            "GlobalId": ifc_guid(),
            "BuildingStoreys": [{
                "type": "IfcBuildingStorey",
                "GlobalId": ifc_guid(),
                "Name": level_name,
                "Elevation": 0.0,
                "Height": level_height_m,
                "Spaces": spaces,
                "Elements": {"Walls": walls, "Doors": doors, "Windows": []}
            }]
        }]
    }
    return plan

# ----------------------------- Main ------------------------------------

def process_all_sections(sections_dir: str,
                         output_dir: str,
                         min_room_area_px: int = 1200,
                         do_ocr: bool = True,
                         tess_cmd: Optional[str] = None) -> List[Dict[str,Any]]:
    ensure_dir(output_dir)
    items = list_section_images(sections_dir)
    results = []
    for idx, path in items:
        print(f"[INFO] Processing section {idx} -> {path}")
        res = process_section(idx, path, output_dir, min_room_area_px, do_ocr, tess_cmd)
        n_rooms = len(res.get("rooms", []))
        print(f"       rooms={n_rooms}  segments={len(res.get('segments', []))}  doors={len(res.get('doors', []))}")
        results.append(res)
    with open(os.path.join(output_dir, "sections_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"sections": results}, f, ensure_ascii=False, indent=2)
    return results

def main():
    ap = argparse.ArgumentParser(description="Parse base_rectangle_section_*.png → IFC-like JSON")
    ap.add_argument("--input-dir", default=".", help="Cartella con i PNG delle sezioni")
    ap.add_argument("--output", default="plan_ifc.json", help="Percorso file JSON finale")
    ap.add_argument("--out-dir", default="sections_output", help="Cartella per debug/summary")
    ap.add_argument("--level-name", default="Piano", help="Nome livello (IfcBuildingStorey.Name)")
    ap.add_argument("--height", type=float, default=3.0, help="Altezza livello in metri (metadati)")
    ap.add_argument("--no-ocr", action="store_true", help="Disabilita OCR anche se disponibile")
    ap.add_argument("--tesseract", default=None, help="Percorso a tesseract.exe se necessario (Windows)")
    ap.add_argument("--min-room-area", type=int, default=1200, help="Area minima in px^2 per accettare una stanza")
    args = ap.parse_args()

    sections = process_all_sections(
        sections_dir=args.input_dir,
        output_dir=args.out_dir,
        min_room_area_px=args.min_room_area,
        do_ocr=(not args.no_ocr),
        tess_cmd=args.tesseract
    )
    if not sections:
        print("[WARN] Nessuna sezione trovata.")
        return

    plan = to_ifcish(
        level_name=args.level_name,
        level_height_m=args.height,
        sections=sections,
        units="px",
        scale_px_per_m=None
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"[DONE] IFC-like JSON salvato in: {args.output}")

if __name__ == "__main__":
    main()
