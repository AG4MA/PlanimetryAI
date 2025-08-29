# twin_significato.py
# PlanTwin_Significato: lavora su clean.png già presente in --out-dir
import os, json, argparse
from typing import List, Dict, Any, Tuple
import cv2
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import polygonize
from twin_core import core_run, save_json

def build_topology(segments: List[Dict[str,Any]], min_area_px: float=1200)->Dict[str,Any]:
    lines=[LineString([tuple(s["P0"]), tuple(s["P1"])]) for s in segments if s.get("type")=="line"]
    if not lines: return {"rooms":[], "graph":{"nodes":[], "edges":[]}}
    mls = MultiLineString(lines)
    polys = [p for p in polygonize(mls) if p.is_valid and p.area>=min_area_px]
    nodes=[]; edges=[]; node_map={}
    def nid(xy):
        k=(round(xy[0],1), round(xy[1],1))
        if k not in node_map:
            node_map[k]=len(nodes)
            nodes.append({"id":node_map[k],"p":[float(k[0]),float(k[1])]})
        return node_map[k]
    for s in segments:
        if s.get("type")!="line": continue
        i=nid(tuple(s["P0"])); j=nid(tuple(s["P1"]))
        edges.append({"u":i,"v":j})
    return {"rooms":[list(p.exterior.coords) for p in polys], "graph":{"nodes":nodes,"edges":edges}}

def basic_semantics(rooms: List[List[Tuple[float,float]]])->List[Dict[str,Any]]:
    return [{"name":f"room_{k+1}","outline":coords} for k,coords in enumerate(rooms)]

def run_significato(image:str, out_dir:str)->Dict[str,Any]:
    # se esiste già clean.png usalo, altrimenti rigenera
    clean_path=os.path.join(out_dir,"clean.png")
    if os.path.exists(clean_path):
        gray=cv2.imread(clean_path, cv2.IMREAD_GRAYSCALE)
        pre={"clean":gray}
        from twin_core import vector_geometry, extract_indizi_scala
        vg=vector_geometry(pre["clean"])
        ind=extract_indizi_scala(gray)
        res={"width":gray.shape[1],"height":gray.shape[0],"vg":vg,"ind":ind}
    else:
        res=core_run(image,out_dir)
    topo=build_topology(res["vg"]["segments"])
    spaces=basic_semantics(topo["rooms"])
    model={
        "type":"IfcProject_like",
        "size":[res["width"],res["height"]],
        "Spaces":spaces,
        "Graph":topo["graph"],
        "Hints":{"scale_hint":res["ind"]["scale_hint"]}
    }
    return model

if __name__=="__main__":
    ap=argparse.ArgumentParser(description="PlanTwin_Significato")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out-dir", required=True)
    args=ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    model=run_significato(args.image,args.out_dir)
    save_json(os.path.join(args.out_dir,"significato.json"),model)
    print("[PlanTwin/significato] done.")
