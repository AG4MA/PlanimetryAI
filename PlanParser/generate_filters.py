import os
import cv2
import numpy as np
from typing import Callable, Dict, Tuple

# Default input
DEFAULT_IMAGE = "base_rectangle_section_1.png"
OUTPUT_DIR = "filters_test"
DESC_FILE = "filters_explained.txt"


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def load_image(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input image not found: {path}")
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError(f"Cannot read image: {path}")
    return img

# ---------------- Skeletonization (morphological) ------------------

def morphological_skeleton(binary: np.ndarray) -> np.ndarray:
    skel = np.zeros(binary.shape, np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    temp = np.zeros(binary.shape, np.uint8)
    eroded = np.zeros(binary.shape, np.uint8)
    done = False
    bw = binary.copy()
    while not done:
        eroded = cv2.erode(bw, element)
        temp = cv2.dilate(eroded, element)
        temp = cv2.subtract(bw, temp)
        skel = cv2.bitwise_or(skel, temp)
        bw = eroded.copy()
        if cv2.countNonZero(bw) == 0:
            done = True
    return skel

# ---------------- Filter Generators ------------------

def to_gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def clahe_gray(img):
    g = to_gray(img)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(g)


def gaussian_blur(img):
    return cv2.GaussianBlur(to_gray(img), (5, 5), 0)


def median_blur(img):
    return cv2.medianBlur(to_gray(img), 5)


def bilateral(img):
    return cv2.bilateralFilter(to_gray(img), d=9, sigmaColor=75, sigmaSpace=75)


def otsu(img):
    g = to_gray(img)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


def otsu_inv(img):
    g = to_gray(img)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return th


def adaptive_mean(img):
    g = to_gray(img)
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 7)


def adaptive_gauss(img):
    g = to_gray(img)
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)


def canny_soft(img):
    g = to_gray(img)
    return cv2.Canny(g, 40, 120)


def canny_strong(img):
    g = to_gray(img)
    return cv2.Canny(g, 80, 200)


def sobel_x(img):
    g = to_gray(img)
    return cv2.Sobel(g, cv2.CV_16S, 1, 0, ksize=3).clip(-255,255).astype(np.int16)


def sobel_y(img):
    g = to_gray(img)
    return cv2.Sobel(g, cv2.CV_16S, 0, 1, ksize=3).clip(-255,255).astype(np.int16)


def laplacian(img):
    g = to_gray(img)
    return cv2.Laplacian(g, cv2.CV_16S, ksize=3)


def scharr_x(img):
    g = to_gray(img)
    return cv2.Scharr(g, cv2.CV_16S, 1, 0)


def scharr_y(img):
    g = to_gray(img)
    return cv2.Scharr(g, cv2.CV_16S, 0, 1)


def morphology_open(img):
    g = to_gray(img)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    return cv2.morphologyEx(g, cv2.MORPH_OPEN, k, iterations=1)


def morphology_close(img):
    g = to_gray(img)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5,5))
    return cv2.morphologyEx(g, cv2.MORPH_CLOSE, k, iterations=1)


def morphology_gradient(img):
    g = to_gray(img)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    return cv2.morphologyEx(g, cv2.MORPH_GRADIENT, k)


def erode_small(img):
    g = to_gray(img)
    k = np.ones((3,3), np.uint8)
    return cv2.erode(g, k, iterations=1)


def dilate_small(img):
    g = to_gray(img)
    k = np.ones((3,3), np.uint8)
    return cv2.dilate(g, k, iterations=1)


def quantize_kmeans(img, k=4):
    data = img.reshape((-1,3)).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(data, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    centers = centers.astype(np.uint8)
    reduced = centers[labels.flatten()].reshape(img.shape)
    return reduced


def distance_transform(img):
    b = otsu_inv(img)
    dist = cv2.distanceTransform(b, cv2.DIST_L2, 5)
    # Normalize for visualization
    dist_norm = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return dist_norm


def skeleton(img):
    b = otsu_inv(img)
    return morphological_skeleton(b)


def horizontal_lines(img):
    b = otsu_inv(img)
    h, w = b.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w//30), 1))
    temp = cv2.erode(b, kernel, iterations=1)
    temp = cv2.dilate(temp, kernel, iterations=1)
    return temp


def vertical_lines(img):
    b = otsu_inv(img)
    h, w = b.shape
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h//30)))
    temp = cv2.erode(b, kernel, iterations=1)
    temp = cv2.dilate(temp, kernel, iterations=1)
    return temp


def edge_preserve(img):
    return cv2.edgePreservingFilter(img, flags=1, sigma_s=60, sigma_r=0.4)


def color_channels(img):
    b,g,r = cv2.split(img)
    return {"channel_b": b, "channel_g": g, "channel_r": r}

FILTERS: Dict[str, Callable] = {
    "gray": to_gray,
    "clahe_gray": clahe_gray,
    "gaussian_blur": gaussian_blur,
    "median_blur": median_blur,
    "bilateral": bilateral,
    "otsu": otsu,
    "otsu_inv": otsu_inv,
    "adaptive_mean": adaptive_mean,
    "adaptive_gauss": adaptive_gauss,
    "canny_soft": canny_soft,
    "canny_strong": canny_strong,
    "sobel_x": sobel_x,
    "sobel_y": sobel_y,
    "laplacian": laplacian,
    "scharr_x": scharr_x,
    "scharr_y": scharr_y,
    "morph_open": morphology_open,
    "morph_close": morphology_close,
    "morph_gradient": morphology_gradient,
    "erode_small": erode_small,
    "dilate_small": dilate_small,
    "quantize_k4": lambda img: quantize_kmeans(img, 4),
    "distance_transform": distance_transform,
    "skeleton": skeleton,
    "horizontal_lines": horizontal_lines,
    "vertical_lines": vertical_lines,
    "edge_preserve": edge_preserve,
}

FILTER_DESCRIPTIONS = {
    "gray": "Conversione in scala di grigi; base per quasi tutte le operazioni successive.",
    "clahe_gray": "Equalizzazione adattiva del contrasto locale (CLAHE) per migliorare testo e linee deboli.",
    "gaussian_blur": "Riduzione rumore gaussiana; utile prima di edge detection.",
    "median_blur": "Filtro mediano; efficace contro salt-and-pepper noise preservando i bordi.",
    "bilateral": "Filtro bilaterale che riduce il rumore mantenendo i bordi netti (utile per testo).",
    "otsu": "Binarizzazione globale automatica (Otsu) foreground scuro su fondo chiaro.",
    "otsu_inv": "Binarizzazione Otsu inversa (foreground chiaro su sfondo scuro) per segmentazioni alternative.",
    "adaptive_mean": "Binarizzazione adattiva a media locale; utile con illuminazione non uniforme.",
    "adaptive_gauss": "Binarizzazione adattiva gaussiana; spesso più stabile su planimetrie.",
    "canny_soft": "Edge detection Canny con soglie basse (più sensibile, più rumore).",
    "canny_strong": "Edge detection Canny con soglie più alte (più preciso, meno falsi).",
    "sobel_x": "Derivata orizzontale (Sobel) per evidenziare bordi verticali.",
    "sobel_y": "Derivata verticale (Sobel) per evidenziare bordi orizzontali.",
    "laplacian": "Seconda derivata isotropa; evidenzia rapidi cambi di intensità (tutti i bordi).",
    "scharr_x": "Filtro Scharr orizzontale (derivata precisa) per linee verticali.",
    "scharr_y": "Filtro Scharr verticale per linee orizzontali.",
    "morph_open": "Morph opening: rimuove piccoli rumori (erosione + dilatazione).",
    "morph_close": "Morph closing: chiude piccoli gap nelle linee (dilatazione + erosione).",
    "morph_gradient": "Differenza tra dilatazione ed erosione (outline delle forme).",
    "erode_small": "Erosione leggera: assottiglia le linee e rimuove punti isolati.",
    "dilate_small": "Dilatazione leggera: ispessisce le linee e connette piccoli gap.",
    "quantize_k4": "Riduzione colori via K-means (k=4); semplifica la scena per clustering di regioni.",
    "distance_transform": "Trasformata di distanza sul binario (utile per segmentazione, watershed).",
    "skeleton": "Scheletrizzazione morfologica: riduce le linee al loro asse centrale.",
    "horizontal_lines": "Estrazione linee orizzontali mediante morfologia (isolamento muri/quote).",
    "vertical_lines": "Estrazione linee verticali mediante morfologia (isolamento muri verticali).",
    "edge_preserve": "Filtro edge-preserving: smoothing non lineare che mantiene i bordi (prep per threshold).",
}

CHANNEL_DESCRIPTION = "Canali B,G,R separati per analizzare differenze cromatiche localizzate."


def save_image(path: str, img):
    if img.dtype == np.int16:
        # normalize to 0-255 for visualization
        disp = np.clip((img.astype(np.float32) + 255) / 2, 0, 255).astype(np.uint8)
        cv2.imwrite(path, disp)
    else:
        cv2.imwrite(path, img)


def main(image_path: str = DEFAULT_IMAGE):
    ensure_dir(OUTPUT_DIR)
    img = load_image(image_path)

    descriptions_out = []

    # Save original
    save_image(os.path.join(OUTPUT_DIR, "00_original.png"), img)
    descriptions_out.append("00_original.png : Immagine originale di riferimento.")

    # Apply each single-output filter
    order = sorted(FILTERS.keys())
    for idx, name in enumerate(order, start=1):
        try:
            out = FILTERS[name](img)
            filename = f"{idx:02d}_{name}.png"
            save_image(os.path.join(OUTPUT_DIR, filename), out)
            descriptions_out.append(f"{filename} : {FILTER_DESCRIPTIONS.get(name, '')}")
        except Exception as e:
            descriptions_out.append(f"ERROR {name}: {e}")

    # Channels
    chans = color_channels(img)
    for key, cimg in chans.items():
        fname = f"ch_{key}.png"
        save_image(os.path.join(OUTPUT_DIR, fname), cimg)
        descriptions_out.append(f"{fname} : {CHANNEL_DESCRIPTION}")

    # Compose overlay of edges on original
    try:
        edges = canny_strong(img)
        edges_col = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        overlay = img.copy()
        overlay[edges > 0] = (0, 0, 255)
        save_image(os.path.join(OUTPUT_DIR, "overlay_edges.png"), overlay)
        descriptions_out.append("overlay_edges.png : Sovrapposizione bordi (Canny forte) sull'originale per verifica linee.")
    except Exception:
        pass

    # Write description file
    with open(os.path.join(OUTPUT_DIR, DESC_FILE), 'w', encoding='utf-8') as f:
        f.write("GUIDA FILTRI / COMPUTER VISION\n")
        f.write("Immagine di input: " + image_path + "\n\n")
        for line in descriptions_out:
            f.write(line + "\n")

    print(f"[DONE] Generated {len(descriptions_out)} filter outputs in {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
