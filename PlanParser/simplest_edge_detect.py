
import os
import sys
import json
import cv2
import numpy as np

def load_image(path: str):
    if not os.path.exists(path):
        print(f"[ERR] Missing file: {path}")
        return None
    img = cv2.imread(path)
    if img is None:
        print(f"[ERR] Cannot read: {path}")
    else:
        print(f"[OK] Loaded {path} shape={img.shape}")
    return img

def preprocess_for_edges(img: np.ndarray):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    # Auto Canny thresholds
    v = np.median(blur)
    lower = int(max(0, 0.66 * v))
    upper = int(min(255, 1.33 * v))
    edges = cv2.Canny(blur, lower, upper)
    # Light dilation to close tiny gaps
    kernel = np.ones((3,3), np.uint8)
    edges_dil = cv2.dilate(edges, kernel, iterations=1)
    return edges_dil

def extract_contours(edges: np.ndarray, min_area=50):
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    kept = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x,y,w,h = cv2.boundingRect(c)
        kept.append({
            "bbox": [int(x), int(y), int(w), int(h)],
            "area": float(area),
            "perimeter": float(cv2.arcLength(c, True))
        })
    return kept, contours

def draw_overlays(img: np.ndarray, contours, out_path: str):
    overlay = img.copy()
    cv2.drawContours(overlay, contours, -1, (0,0,255), 1)
    cv2.imwrite(out_path, overlay)
    print(f"[OK] Saved overlay: {out_path}")

def process_section(section_path: str, prefix: str):
    img = load_image(section_path)
    if img is None:
        return None
    edges = preprocess_for_edges(img)
    edges_path = f"{prefix}_edges.png"
    cv2.imwrite(edges_path, edges)
    print(f"[OK] Saved edges: {edges_path}")
    kept_meta, contours = extract_contours(edges)
    overlay_path = f"{prefix}_edges_overlay.png"
    draw_overlays(img, contours, overlay_path)
    meta_path = f"{prefix}_contours.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"contours": kept_meta}, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved metadata: {meta_path}")
    return kept_meta

def main():
    """
    Monolithic script:
    - Takes base_rectangle_section_1.png and base_rectangle_section_2.png (default names)
    - Produces edge maps, overlays, and contour metadata JSON.
    Usage:
        python monolithic_edge_segmentation.py [section1 path] [section2 path]
    """
    # Defaults (produced by define_floor / previous pipeline)
    default_1 = "base_rectangle_section_1.png"
    default_2 = "base_rectangle_section_2.png"

    section1 = sys.argv[1] if len(sys.argv) > 1 else default_1
    section2 = sys.argv[2] if len(sys.argv) > 2 else default_2

    print(f"[INFO] Processing sections:\n  1: {section1}\n  2: {section2}")

    meta1 = process_section(section1, "section1")
    meta2 = process_section(section2, "section2")

    summary = {
        "section1_file": section1,
        "section2_file": section2,
        "section1_contours": len(meta1) if meta1 else 0,
        "section2_contours": len(meta2) if meta2 else 0
    }
    with open("sections_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[OK] Summary: {summary}")

if __name__== "__main__":
    main()