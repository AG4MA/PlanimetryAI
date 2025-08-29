import os
import cv2
import math
import numpy as np
from collections import defaultdict

FILTERS_DIR = "C://projects//extra//PlanimetryAI//PlanParser//filters_test"
OUTPUT_TXT = os.path.join(FILTERS_DIR, "filters_line_stats.txt")

def auto_canny(image, sigma=0.33):
    v = np.median(image)
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v))
    return cv2.Canny(image, lower, upper, L2gradient=True)

def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return img

def hough_count(edges):
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=25,
        maxLineGap=5
    )
    if lines is None:
        return []
    return [tuple(l[0]) for l in lines]

def merge_similar(lines, angle_tol_deg=3, dist_tol=10):
    # Represent each line as (rho, theta); cluster by angle then position
    normed = []
    for (x1, y1, x2, y2) in lines:
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0 and dy == 0:
            continue
        theta = math.degrees(math.atan2(dy, dx))
        # Normalize angle to [0,180)
        if theta < 0:
            theta += 180
        # Compute rho from normal form
        # Convert to radians for formula
        tr = math.radians(theta)
        # For stability pick one endpoint
        rho = x1 * math.cos(tr) + y1 * math.sin(tr)
        normed.append((rho, theta, (x1, y1, x2, y2)))

    clusters = []
    used = [False] * len(normed)
    for i, (rho_i, th_i, l_i) in enumerate(normed):
        if used[i]:
            continue
        group = [l_i]
        used[i] = True
        for j, (rho_j, th_j, l_j) in enumerate(normed[i+1:], start=i+1):
            if used[j]:
                continue
            if abs(th_i - th_j) <= angle_tol_deg and abs(rho_i - rho_j) <= dist_tol:
                group.append(l_j)
                used[j] = True
        clusters.append(group)
    # One representative per cluster
    merged = [g[0] for g in clusters]
    return merged

def contour_count(binary):
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    usable = 0
    for c in cnts:
        if cv2.arcLength(c, True) > 40:  # ignore tiny noise
            usable += 1
    return usable

def evaluate_image(path):
    gray = load_gray(path)
    if gray is None:
        return None

    # Normalize contrast slightly
    norm = cv2.equalizeHist(gray)

    # Try both direct Canny and after slight blur
    blur = cv2.GaussianBlur(norm, (3, 3), 0)
    edges = auto_canny(blur)

    # Hough line segments
    raw_lines = hough_count(edges)
    merged_lines = merge_similar(raw_lines)

    # Binary (Otsu) for contour heuristic
    _, otsu = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inv = 255 - otsu  # walls often dark; invert
    conts = contour_count(inv)

    return {
        "raw_line_segments": len(raw_lines),
        "merged_line_groups": len(merged_lines),
        "contours": conts
    }

def main():
    if not os.path.isdir(FILTERS_DIR):
        print(f"Directory not found: {FILTERS_DIR}")
        return

    results = []
    for fname in sorted(os.listdir(FILTERS_DIR)):
        if not fname.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')):
            continue
        fpath = os.path.join(FILTERS_DIR, fname)
        stats = evaluate_image(fpath)
        if stats is None:
            continue
        results.append((fname, stats))

    # Sort primarily by merged groups (proxy for structural lines)
    results.sort(key=lambda x: (x[1]['merged_line_groups'], x[1]['raw_line_segments']), reverse=True)

    lines_out = []
    header = "FilterName | RawLineSegments | MergedLineGroups | ContourCount"
    sep = "-" * len(header)
    lines_out.append(header)
    lines_out.append(sep)
    for name, s in results:
        lines_out.append(f"{name} | {s['raw_line_segments']} | {s['merged_line_groups']} | {s['contours']}")

    report = "\n".join(lines_out)
    print(report)

    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(report + "\n")
        f.write("\nNotes:\n")
        f.write("RawLineSegments = direct HoughLinesP detections after edge extraction.\n")
        f.write("MergedLineGroups = approximate distinct structural lines after clustering.\n")
        f.write("ContourCount = count of larger external contours (inverted binarization).\n")
        f.write("Higher MergedLineGroups usually indicates better structural line preservation.\n")

if __name__ == "__main__":
    main()