# twin_misure.py
# PlanTwin_Misure: lavora su clean.png già presente in --out-dir
import os, json, argparse, math, cv2
from typing import Dict, Any, List, Tuple, Optional
from shapely.geometry import Polygon
from twin_core import core_run, save_json, vector_geometry, extract_indizi_scala

def resolve_scale_m_per_px(scale_hint: Optional[float], fallback_m_per_px: Optional[float])->Optional[float]:
    if fallback_m_per_px and fallback_m_per_px>0: return float(fallback_m_per_px)
    return None

def length_px(seg: Dict[str,Any])->float:
    x0,y0=seg["P0"]; x1,y1=seg["P1"]
    return float(math.hypot(x1-x0,y1-y0))

def compute_measurements(segments: List[Dict[str,Any]], m_per_px: Optional[float])->Dict[str,Any]:
    meas=[{"px":length_px(s)} for s in segments]
    if m_per_px:
        for m,s in zip(meas,segments): m["m"]=m["px"]*m_per_px
    return {"scale_m_per_px":m_per_px, "segments":meas}

def run_misure(image:str, out_dir:str, fallback_m_per_px:Optional[float])->Dict[str,Any]:
    clean_path=os.path.join(out_dir,"clean.png")
    if os.path.exists(clean_path):
        gray=cv2.imread(clean_path, cv2.IMREAD_GRAYSCALE)
        vg=vector_geometry(gray)
        ind=extract_indizi_scala(gray)
        res={"vg":vg,"ind":ind}
    else:
        res=core_run(image,out_dir)
    mppx=resolve_scale_m_per_px(res["ind"]["scale_hint"], fallback_m_per_px)
    return compute_measurements(res["vg"]["segments"], mppx)

if __name__=="__main__":
    ap=argparse.ArgumentParser(description="PlanTwin_Misure")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--m-per-px", type=float, default=None,
                    help="Fattore metri-per-pixel (es. 0.002 = 2mm/px)")
    args=ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    out=run_misure(args.image,args.out_dir,args.m_per_px)
    save_json(os.path.join(args.out_dir,"misure.json"),out)
    print("[PlanTwin/misure] done.")
