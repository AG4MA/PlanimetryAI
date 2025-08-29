# twin_core.py
# PlanTwin: core condiviso (Preprocess + VectorGeometry + IndiziScala)
import os, json, argparse, re
from typing import List, Tuple, Dict, Any, Optional
import numpy as np, cv2

# --- OCR opzionale (per indizi scala/quote/nord) ---
try:
    import pytesseract
    HAS_TESS = True
except Exception:
    HAS_TESS = False

def ensure_dir(p:str): os.makedirs(p, exist_ok=True)

def imread_gray(path:str)->np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: raise FileNotFoundError(path)
    return img

def preprocess(img_gray: np.ndarray) -> Dict[str,np.ndarray]:
    blur = cv2.GaussianBlur(img_gray,(3,3),0)
    thr = cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY,35,5)
    ink = 255 - thr  # ink=white on black bg? we keep ink=255
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2,2),np.uint8),1)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8),1)
    return {"clean": ink}

def vector_geometry(clean_bin: np.ndarray) -> Dict[str,Any]:
    # Segmenti = Hough; Curve: none (placeholder). Refinement minimale con subpixel endpoints.
    edges = cv2.Canny(clean_bin,40,120,L2gradient=True)
    segs = cv2.HoughLinesP(edges,1,np.pi/180,threshold=40,minLineLength=25,maxLineGap=5)
    segments = []
    if segs is not None:
        for x1,y1,x2,y2 in segs[:,0,:]:
            segments.append({"type":"line","P0":[float(x1),float(y1)],"P1":[float(x2),float(y2)],"width":2.0,"conf":0.6})
    return {"segments":segments, "edges":edges}

def ocr_texts(img_gray: np.ndarray)->List[str]:
    if not HAS_TESS: return []
    data = pytesseract.image_to_data(img_gray, lang="ita+eng", output_type=pytesseract.Output.DICT)
    out=[]
    for t in data["text"]:
        t=(t or "").strip()
        if t: out.append(t)
    return out

SCALE_RX = re.compile(r'(\d+(?:[.,]\d+)?)\s*(m|cm|mm|:|\/)?\s*(\d+)?', re.IGNORECASE)
def parse_scale_tokens(tokens: List[str])->Optional[float]:
    """
    Ritorna fattore metri-per-pixel SE possibile (placeholder: None).
    Qui estraiamo solo indicatori come '1:100' o quote '3.50 m' come indizio (senza calcolare m/px).
    """
    # Nota: il calcolo m/px richiede o DPI o una distanza in px corrispondente a una quota.
    # Qui ci limitiamo a rilevare la presenza di scala/quote.
    for tk in tokens:
        m=SCALE_RX.search(tk.replace(',','.'))
        if not m: continue
        a, unit, b = m.group(1), m.group(2), m.group(3)
        if unit in (":","/") and b:
            # esempio "1:100" -> ritorna rapporto (solo come indizio)
            try:
                ratio = float(b)
                if ratio>0: return -ratio  # convenzione: negativo = rapporto 1:ratio (non m/px)
            except: pass
        if unit in ("m","cm","mm"):
            # è presente una quota metrica; senza distanza in px non possiamo m/px -> usiamo sentinel
            return 0.0  # 0.0 = quote presenti ma non m/px
    return None

def extract_indizi_scala(img_gray: np.ndarray)->Dict[str,Any]:
    texts = ocr_texts(img_gray)
    hint = parse_scale_tokens(texts)
    return {"texts":texts, "scale_hint":hint}

def save_json(path:str, obj:Any):
    with open(path,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)

def core_run(image:str, out_dir:str)->Dict[str,Any]:
    ensure_dir(out_dir)
    gray = imread_gray(image)
    pre = preprocess(gray)
    vg  = vector_geometry(pre["clean"])
    ind = extract_indizi_scala(gray)
    cv2.imwrite(os.path.join(out_dir,"clean.png"), pre["clean"])
    return {"width": gray.shape[1], "height": gray.shape[0], "pre":pre, "vg":vg, "ind":ind}

if __name__=="__main__":
    ap = argparse.ArgumentParser(description="PlanTwin core (preprocess + vector geometry + indizi scala)")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out-dir", default="out_core")
    args = ap.parse_args()
    res = core_run(args.image, args.out_dir)
    save_json(os.path.join(args.out_dir,"core_summary.json"),
              {"size":[res["width"],res["height"]],
               "segments":res["vg"]["segments"][:200], # truncate preview
               "scale_hint":res["ind"]["scale_hint"]})
    print("[PlanTwin/core] done.")
