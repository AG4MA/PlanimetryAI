import os
import re
import json
import glob
import math
from typing import List, Dict, Any, Tuple

import cv2
import numpy as np

SECTION_PATTERN = re.compile(r"base_rectangle_section_(\d+)\.png$")

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

# ----------------------------- Line Detection ---------------------------

def preprocess(img: np.ndarray) -> Dict[str, np.ndarray]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    # Adaptive threshold for thin lines
    th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 35, 7)
    # Morph open to remove noise
    kernel = np.ones((2, 2), np.uint8)
    opened = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel, iterations=1)
    edges = cv2.Canny(opened, 40, 120, apertureSize=3, L2gradient=True)
    return {
        'gray': gray,
        'th': th,
        'opened': opened,
        'edges': edges
    }


def extract_axis_lines(binary: np.ndarray) -> Dict[str, np.ndarray]:
    h, w = binary.shape
    # Horizontal lines
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 40), 1))
    h_lines = cv2.erode(binary, horiz_kernel, iterations=1)
    h_lines = cv2.dilate(h_lines, horiz_kernel, iterations=1)

    # Vertical lines
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 40)))
    v_lines = cv2.erode(binary, vert_kernel, iterations=1)
    v_lines = cv2.dilate(v_lines, vert_kernel, iterations=1)

    combined = cv2.bitwise_or(h_lines, v_lines)
    return {
        'horiz': h_lines,
        'vert': v_lines,
        'combined': combined
    }


def hough_segments(edge_img: np.ndarray, min_len: int = 25, max_gap: int = 4) -> List[Tuple[int, int, int, int]]:
    segs = cv2.HoughLinesP(edge_img, 1, np.pi / 180, threshold=35,
                           minLineLength=min_len, maxLineGap=max_gap)
    if segs is None:
        return []
    return [tuple(map(int, s[0])) for s in segs]


def classify_segment(x1, y1, x2, y2) -> str:
    dx = x2 - x1
    dy = y2 - y1
    angle = math.degrees(math.atan2(dy, dx))
    a = abs(angle)
    if a < 10 or a > 170:
        return 'horizontal'
    if 80 < a < 100:
        return 'vertical'
    return 'other'


def merge_close_segments(segments: List[Tuple[int, int, int, int]], dist_thresh=6, angle_thresh=8) -> List[Tuple[int, int, int, int]]:
    # Simple greedy merge by expanding bounding boxes for similar orientation
    if not segments:
        return []
    used = [False] * len(segments)
    merged = []

    def seg_angle(s):
        return math.degrees(math.atan2(s[3]-s[1], s[2]-s[0]))

    for i, s in enumerate(segments):
        if used[i]:
            continue
        x1, y1, x2, y2 = s
        ax = seg_angle(s)
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, t in enumerate(segments):
                if used[j]:
                    continue
                bx1, by1, bx2, by2 = t
                a2 = seg_angle(t)
                if abs((ax - a2 + 180) % 360 - 180) > angle_thresh:
                    continue
                # distance between segment endpoints / bounding boxes
                bb1 = min(x1, x2, bx1, bx2), min(y1, y2, by1, by2), max(x1, x2, bx1, bx2), max(y1, y2, by1, by2)
                # if bounding boxes overlap or are very close along orth axis
                if (bb1[2] - bb1[0]) * (bb1[3] - bb1[1]) < 1e7:  # cheap guard
                    # approximate distance by min of endpoint distances
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


def approximate_thickness(img_gray: np.ndarray, seg: Tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = seg
    length = max(1, int(math.hypot(x2-x1, y2-y1)))
    n_samples = min(40, length)
    xs = np.linspace(x1, x2, n_samples).astype(int)
    ys = np.linspace(y1, y2, n_samples).astype(int)
    # Normal vector
    vx = x2 - x1
    vy = y2 - y1
    norm_len = math.hypot(vx, vy)
    if norm_len == 0:
        return 1.0
    nx = -vy / norm_len
    ny = vx / norm_len
    # sample perpendicular profile
    thickness_vals = []
    for xx, yy in zip(xs, ys):
        profile = []
        for d in range(-8, 9):
            px = int(round(xx + nx * d))
            py = int(round(yy + ny * d))
            if 0 <= px < img_gray.shape[1] and 0 <= py < img_gray.shape[0]:
                profile.append(img_gray[py, px])
        if profile:
            # estimate width by thresholding variation
            arr = np.array(profile)
            # simplistic contrast-based width: contiguous dark region length
            dark = arr < np.mean(arr) * 0.9
            if dark.any():
                idx = np.where(dark)[0]
                width_est = idx[-1] - idx[0] + 1
                thickness_vals.append(width_est)
    if not thickness_vals:
        return 1.0
    return float(np.median(thickness_vals))


def find_intersections(segments: List[Tuple[int,int,int,int]], tol=6) -> List[Tuple[int,int]]:
    pts = []
    for i, (x1,y1,x2,y2) in enumerate(segments):
        for j, (a1,b1,a2,b2) in enumerate(segments):
            if j <= i:
                continue
            # Solve intersection using parametric form with bounding box pruning
            den = (x1 - x2) * (b1 - b2) - (y1 - y2) * (a1 - a2)
            if den == 0:
                continue
            t = ((x1 - a1) * (b1 - b2) - (y1 - b1) * (a1 - a2)) / den
            u = ((x1 - a1) * (y1 - y2) - (y1 - b1) * (x1 - x2)) / den
            if 0 <= t <= 1 and 0 <= u <= 1:
                ix = int(round(x1 + t * (x2 - x1)))
                iy = int(round(y1 + t * (y2 - y1)))
                pts.append((ix, iy))
    # Deduplicate close points
    dedup = []
    for (x,y) in pts:
        if not any(abs(x - dx) <= tol and abs(y - dy) <= tol for (dx,dy) in dedup):
            dedup.append((x,y))
    return dedup

# ----------------------------- Section Processing ----------------------

def process_section(idx: int, path: str, out_dir: str) -> Dict[str, Any]:
    base_name = f"section_{idx:02d}"
    json_path = os.path.join(out_dir, base_name + '_lines.json')
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            return json.load(f)

    img = cv2.imread(path)
    if img is None:
        return {'error': 'cannot_read', 'path': path}

    prep = preprocess(img)
    axes = extract_axis_lines(prep['th'])
    hough = hough_segments(prep['edges'])

    # Combine axis-derived segments by contour bounding boxes
    axis_segments = []
    for key in ('horiz', 'vert'):
        mask = axes[key]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x,y,w,h = cv2.boundingRect(c)
            if w < 5 and h < 5:
                continue
            if key == 'horiz':
                axis_segments.append((x, y + h//2, x + w, y + h//2))
            else:
                axis_segments.append((x + w//2, y, x + w//2, y + h))

    all_segments = axis_segments + hough
    # Normalize orientation for duplicates (store sorted endpoints for vertical/horizontal)
    normalized = []
    for (x1,y1,x2,y2) in all_segments:
        if x1==x2 and y1==y2:
            continue
        normalized.append((x1,y1,x2,y2))

    merged = merge_close_segments(normalized)

    lines_data = []
    for seg in merged:
        x1,y1,x2,y2 = seg
        length = float(math.hypot(x2-x1, y2-y1))
        orient = classify_segment(x1,y1,x2,y2)
        thickness = approximate_thickness(prep['gray'], seg)
        lines_data.append({
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'length': length,
            'orientation': orient,
            'thickness_est': thickness
        })

    intersections = find_intersections([(l['x1'],l['y1'],l['x2'],l['y2']) for l in lines_data])

    result = {
        'section_index': idx,
        'image_path': path,
        'lines': lines_data,
        'intersections': [{'x':x,'y':y} for (x,y) in intersections],
        'counts': {
            'total_lines': len(lines_data),
            'intersections': len(intersections)
        }
    }

    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)

    # Optional debug visualization
    debug_img = img.copy()
    for l in lines_data:
        color = (0,255,0)
        if l['orientation'] == 'vertical':
            color = (255,0,0)
        elif l['orientation'] == 'other':
            color = (0,165,255)
        cv2.line(debug_img, (l['x1'], l['y1']), (l['x2'], l['y2']), color, 2)
    for (ix,iy) in intersections:
        cv2.circle(debug_img, (ix,iy), 4, (0,0,255), -1)
    cv2.imwrite(os.path.join(out_dir, base_name + '_debug.png'), debug_img)

    return result

# ----------------------------- Main Entrypoint -------------------------

def process_all_sections(sections_dir: str = '.', output_dir: str = 'sections_output') -> List[Dict[str, Any]]:
    ensure_dir(output_dir)
    sections = list_section_images(sections_dir)
    results = []
    for idx, path in sections:
        print(f"[INFO] Processing section {idx} -> {path}")
        res = process_section(idx, path, output_dir)
        print(f"[INFO] Lines: {res.get('counts', {}).get('total_lines')}  Intersections: {res.get('counts', {}).get('intersections')}")
        results.append(res)
    # Summary file
    summary_path = os.path.join(output_dir, 'summary.json')
    with open(summary_path, 'w') as f:
        json.dump({'sections': results}, f, indent=2)
    print(f"[DONE] Summary saved to {summary_path}")
    return results

if __name__ == '__main__':
    process_all_sections()
