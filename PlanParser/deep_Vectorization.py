# vectorize_system.py
# Raster technical drawing -> Vector primitives (line segments + quadratic Beziers)
# Pipeline:
# 1) Preprocess with UNet (noise removal, infill, binarization) [image-to-image BCE]
# 2) Patchify (64x64) + per-patch primitive estimation with ResNet encoder + Transformer decoder
#    (slots-based, DETR-like) -> primitives: {presence, type(line|bezier), control points, width}
# 3) Iterative refinement: snap primitives to cleaned raster using distance transform gradients
# 4) Merge: deduplicate primitives across patches, average by confidence
#
# Outputs:
#   out/clean.png
#   out/primitives_raw.json          (patch-level predictions in global coords)
#   out/primitives_refined.json      (refined + merged)
#   out/vector.svg                   (SVG preview in px units)
#
# If torch or weights are missing, script falls back to classical method (Canny+Hough).
#
# MIT License - 2025

import os, json, math, argparse, uuid, warnings
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
import cv2

# ---- Optional deep stack ------------------------------------------------
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.models as tvm
    TORCH_AVAILABLE = True
except Exception:
    torch, nn, F, tvm = None, None, None, None
    TORCH_AVAILABLE = False

# ------------------------- Utils -------------------------

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def imread_gray(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(path)
    return img

def normalize01(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32)
    mn, mx = x.min(), x.max()
    if mx > mn: x = (x - mn) / (mx - mn)
    else: x = np.zeros_like(x, dtype=np.float32)
    return x

def to_uint8(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return (x * 255).astype(np.uint8)

def sigmoid_np(x: np.ndarray) -> np.ndarray:
    return 1. / (1. + np.exp(-x))

def ifc_guid() -> str:
    return str(uuid.uuid4()).upper()

# ------------------------- Deep models -------------------------

if TORCH_AVAILABLE:
    class DoubleConv(nn.Module):
        def __init__(self, c_in, c_out):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(c_in, c_out, 3, padding=1),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
                nn.Conv2d(c_out, c_out, 3, padding=1),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
            )
        def forward(self, x): return self.net(x)

    class UNetSmall(nn.Module):
        """
        Very small UNet for binary segmentation (1->1), trained with BCE.
        """
        def __init__(self, in_ch=1, out_ch=1, base=32):
            super().__init__()
            self.d1 = DoubleConv(in_ch, base)
            self.p1 = nn.MaxPool2d(2)
            self.d2 = DoubleConv(base, base*2)
            self.p2 = nn.MaxPool2d(2)
            self.d3 = DoubleConv(base*2, base*4)
            self.u2 = nn.ConvTranspose2d(base*4, base*2, 2, stride=2)
            self.c2 = DoubleConv(base*4, base*2)
            self.u1 = nn.ConvTranspose2d(base*2, base, 2, stride=2)
            self.c1 = DoubleConv(base*2, base)
            self.out = nn.Conv2d(base, out_ch, 1)
        def forward(self, x):
            c1 = self.d1(x)
            c2 = self.d2(self.p1(c1))
            c3 = self.d3(self.p2(c2))
            u2 = self.u2(c3)
            x = self.c2(torch.cat([u2, c2], dim=1))
            u1 = self.u1(x)
            x = self.c1(torch.cat([u1, c1], dim=1))
            return self.out(x)

    class PositionalEncoding2D(nn.Module):
        def __init__(self, d_model: int):
            super().__init__()
            self.d_model = d_model
        def forward(self, H: int, W: int, device):
            pe = torch.zeros(1, self.d_model, H, W, device=device)
            # split channels
            d_model = self.d_model
            if d_model % 4 != 0:
                raise ValueError("d_model must be divisible by 4 for 2D PE")
            div = d_model // 4
            y_pos = torch.arange(H, device=device).unsqueeze(1)  # Hx1
            x_pos = torch.arange(W, device=device).unsqueeze(0)  # 1xW
            div_term = torch.exp(torch.arange(0, div, device=device)*(-math.log(10000.0)/div))
            pe[:, 0:div, :, :] = torch.sin(y_pos * div_term).unsqueeze(-1).permute(2,0,1)[:,None,:,:]
            pe[:, div:2*div, :, :] = torch.cos(y_pos * div_term).unsqueeze(-1).permute(2,0,1)[:,None,:,:]
            pe[:, 2*div:3*div, :, :] = torch.sin(x_pos * div_term).unsqueeze(-2).permute(2,0,1)[:,None,:,:]
            pe[:, 3*div:4*div, :, :] = torch.cos(x_pos * div_term).unsqueeze(-2).permute(2,0,1)[:,None,:,:]
            return pe

    class PrimitiveSlotsDETR(nn.Module):
        """
        ResNet encoder + Transformer decoder with learned queries (slots).
        Each slot predicts a primitive (presence, type, control points, width).
        """
        def __init__(self, num_slots=16, d_model=256, nhead=8, num_decoder_layers=3):
            super().__init__()
            # Encoder: ResNet18 backbone (adapt to 1-channel by channel-repeat)
            self.backbone = tvm.resnet18(weights=None)
            # modify first conv to accept 1 channel
            self.backbone.conv1 = nn.Conv2d(1, 64, kernel_size=7, stride=2, padding=3, bias=False)
            # take features from layer3 output
            self.encoder = nn.Sequential(
                self.backbone.conv1, self.backbone.bn1, self.backbone.relu, self.backbone.maxpool,
                self.backbone.layer1, self.backbone.layer2, self.backbone.layer3
            )
            self.proj = nn.Conv2d(256, d_model, 1)
            self.pos2d = PositionalEncoding2D(d_model)
            self.num_slots = num_slots
            self.query_embed = nn.Embedding(num_slots, d_model)
            decoder_layer = nn.TransformerDecoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
            self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=num_decoder_layers)
            # heads
            self.mlp_presence = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, 1))
            self.mlp_type = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, 2))  # line|bezier
            self.mlp_ctrl = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, 6))  # P0(xy), P1(xy), P2(xy) in [0,1]
            self.mlp_width = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Linear(d_model, 1)) # >0 via softplus

        def forward(self, x):  # x: Bx1x64x64
            B, _, H, W = x.shape
            f = self.encoder(x)             # Bx256xhxw  (for 64x64 -> h=w=8)
            f = self.proj(f)                # BxDxhxw
            pe = self.pos2d(f.shape[2], f.shape[3], f.device)
            f = f + pe                      # BxDxhxw
            mem = f.flatten(2).permute(0,2,1)    # Bx(hw)xD
            q = self.query_embed.weight.unsqueeze(0).repeat(B,1,1)  # BxSxD
            out = self.decoder(tgt=q, memory=mem)                   # BxSxD
            presence = self.mlp_presence(out)                       # BxSx1
            ptype = self.mlp_type(out)                              # BxSx2
            ctrl  = torch.sigmoid(self.mlp_ctrl(out))               # normalized [0,1]
            width = F.softplus(self.mlp_width(out)) + 0.1
            return presence.squeeze(-1), ptype, ctrl, width.squeeze(-1)

# ------------------------- Patchify / Blend -------------------------

def sliding_windows(img: np.ndarray, tile: int, stride: int) -> Tuple[List[Tuple[int,int,np.ndarray]], Tuple[int,int], Tuple[int,int], List[int], List[int]]:
    H, W = img.shape[:2]
    pad_h = (tile - H % tile) % tile
    pad_w = (tile - W % tile) % tile
    img_p = np.pad(img, ((0,pad_h),(0,pad_w)), mode='reflect')
    H2, W2 = img_p.shape
    ys = list(range(0, H2 - tile + 1, stride))
    xs = list(range(0, W2 - tile + 1, stride))
    patches = []
    for y in ys:
        for x in xs:
            patches.append((y, x, img_p[y:y+tile, x:x+tile].copy()))
    return patches, (pad_h, pad_w), (H2, W2), ys, xs

# ------------------------- Classical fallback -------------------------

def classical_preprocess(img_gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(img_gray, (3,3), 0)
    thr = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 35, 5)
    inv = 255 - thr
    kernel = np.ones((2,2), np.uint8)
    open_ = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel, 1)
    # fill small gaps
    close = cv2.morphologyEx(open_, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8), 1)
    return close

def classical_primitives(clean_bin: np.ndarray) -> Dict[str, Any]:
    edges = cv2.Canny(clean_bin, 40, 120, L2gradient=True)
    segs = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=40, minLineLength=20, maxLineGap=5)
    primitives = []
    if segs is not None:
        for (x1,y1,x2,y2) in segs[:,0,:]:
            primitives.append({
                "presence": 1.0, "type": "line",
                "P0": [float(x1), float(y1)], "P1": [float(x2), float(y2)], "P2": None,
                "width": 2.0, "conf": 0.6
            })
    return {"primitives": primitives}

# ------------------------- Refinement utilities -------------------------

def distance_transform_with_grad(bin_img: np.ndarray) -> Tuple[np.ndarray,np.ndarray,np.ndarray]:
    """
    bin_img: 255 on ink, 0 on background
    Returns: dist (float32), gradx, grady
    """
    inv = 255 - bin_img
    inv01 = (inv > 0).astype(np.uint8)
    dist = cv2.distanceTransform(inv01, cv2.DIST_L2, 3).astype(np.float32)
    # We want minima on ink -> invert sense by using gradient toward lower dist
    gradx = cv2.Sobel(dist, cv2.CV_32F, 1, 0, ksize=3)
    grady = cv2.Sobel(dist, cv2.CV_32F, 0, 1, ksize=3)
    return dist, gradx, grady

def bilinear_sample(mat: np.ndarray, x: float, y: float) -> float:
    H, W = mat.shape
    x = np.clip(x, 0, W-1); y = np.clip(y, 0, H-1)
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    x1, y1 = min(x0+1, W-1), min(y0+1, H-1)
    dx, dy = x - x0, y - y0
    v = (mat[y0, x0]*(1-dx)*(1-dy) + mat[y0, x1]*dx*(1-dy) +
         mat[y1, x0]*(1-dx)*dy     + mat[y1, x1]*dx*dy)
    return float(v)

def refine_control_points(ctrl_pts: List[Tuple[float,float]],
                          gradx: np.ndarray, grady: np.ndarray,
                          iters: int = 30, lr: float = 0.8) -> List[Tuple[float,float]]:
    """
    Gradient descent on distance field: p <- p - lr * grad(dist) at p
    """
    refined = []
    for (x, y) in ctrl_pts:
        px, py = float(x), float(y)
        for _ in range(iters):
            gx = bilinear_sample(gradx, px, py)
            gy = bilinear_sample(grady, px, py)
            px -= lr * gx
            py -= lr * gy
        refined.append((px, py))
    return refined

# ------------------------- Merging utilities -------------------------

def primitive_global_from_patch(pred: Dict[str,Any], y0: int, x0: int) -> Dict[str,Any]:
    typ = pred["type"]
    P0 = [pred["P0"][0] + x0, pred["P0"][1] + y0]
    if typ == "line":
        P1 = [pred["P1"][0] + x0, pred["P1"][1] + y0]
        return {**pred, "P0": P0, "P1": P1}
    else:
        P1 = [pred["P1"][0] + x0, pred["P1"][1] + y0]
        P2 = [pred["P2"][0] + x0, pred["P2"][1] + y0]
        return {**pred, "P0": P0, "P1": P1, "P2": P2}

def close(a: Tuple[float,float], b: Tuple[float,float], tol: float) -> bool:
    return (a[0]-b[0])**2 + (a[1]-b[1])**2 <= tol*tol

def merge_primitives(prims: List[Dict[str,Any]], tol: float = 3.0) -> List[Dict[str,Any]]:
    """
    Simple O(N^2) clustering with averaging by confidence. Handles line endpoint flipping.
    """
    used = [False]*len(prims)
    out = []
    for i, p in enumerate(prims):
        if used[i]: continue
        group = [i]
        used[i] = True
        for j, q in enumerate(prims):
            if used[j] or j == i: continue
            if p["type"] != q["type"]: continue
            if p["type"] == "line":
                A0, A1 = tuple(p["P0"]), tuple(p["P1"])
                B0, B1 = tuple(q["P0"]), tuple(q["P1"])
                if (close(A0,B0,tol) and close(A1,B1,tol)) or (close(A0,B1,tol) and close(A1,B0,tol)):
                    used[j] = True
                    group.append(j)
            else:
                if close(tuple(p["P0"]), tuple(q["P0"]), tol) and \
                   close(tuple(p["P1"]), tuple(q["P1"]), tol) and \
                   close(tuple(p["P2"]), tuple(q["P2"]), tol):
                    used[j] = True
                    group.append(j)
        # average group
        if len(group) == 1:
            out.append(prims[group[0]])
        else:
            # weighted average by conf
            gs = [prims[k] for k in group]
            ws = np.array([g.get("conf",1.0) for g in gs], dtype=np.float32)
            ws = ws / (ws.sum() + 1e-8)
            def wavg(points_key):
                pts = np.array([gs[k][points_key] for k in range(len(gs))], dtype=np.float32)
                return (ws[:,None] * pts).sum(axis=0).tolist()
            merged = {
                "presence": float(np.mean([g["presence"] for g in gs])),
                "type": gs[0]["type"],
                "width": float(np.mean([g["width"] for g in gs])),
                "conf": float(np.mean([g.get("conf",1.0) for g in gs]))
            }
            if gs[0]["type"] == "line":
                merged["P0"] = wavg("P0"); merged["P1"] = wavg("P1"); merged["P2"] = None
            else:
                merged["P0"] = wavg("P0"); merged["P1"] = wavg("P1"); merged["P2"] = wavg("P2")
            out.append(merged)
    return out

# ------------------------- SVG export -------------------------

def export_svg(path: str, width: int, height: int, primitives: List[Dict[str,Any]]):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n')
        f.write('<rect x="0" y="0" width="100%" height="100%" fill="white"/>\n')
        for pr in primitives:
            sw = max(1.0, pr.get("width", 2.0))
            if pr["type"] == "line":
                x0,y0 = pr["P0"]; x1,y1 = pr["P1"]
                f.write(f'<path d="M {x0:.2f} {y0:.2f} L {x1:.2f} {y1:.2f}" stroke="black" fill="none" stroke-width="{sw:.2f}" stroke-linecap="round"/>\n')
            else:
                x0,y0 = pr["P0"]; x1,y1 = pr["P1"]; x2,y2 = pr["P2"]
                f.write(f'<path d="M {x0:.2f} {y0:.2f} Q {x1:.2f} {y1:.2f} {x2:.2f} {y2:.2f}" stroke="black" fill="none" stroke-width="{sw:.2f}" stroke-linecap="round"/>\n')
        f.write('</svg>\n')

# ------------------------- Deep inference helpers -------------------------

def deep_preprocess(img_gray: np.ndarray, weights_path: str, device: str) -> np.ndarray:
    H, W = img_gray.shape
    net = UNetSmall(1,1,base=32).to(device)
    ckpt = torch.load(weights_path, map_location=device)
    net.load_state_dict(ckpt)
    net.eval()
    with torch.no_grad():
        x = torch.from_numpy(img_gray[None,None].astype(np.float32)/255.0).to(device)
        y = net(x)
        y = torch.sigmoid(y)
        out = (y[0,0].cpu().numpy() > 0.5).astype(np.uint8)*255
    return out

def deep_patch_primitives(clean_bin: np.ndarray, weights_path: str, tile=64, stride=64,
                          num_slots=16, device='cpu', presence_thresh=0.3) -> Dict[str,Any]:
    H, W = clean_bin.shape
    model = PrimitiveSlotsDETR(num_slots=num_slots).to(device)
    ckpt = torch.load(weights_path, map_location=device)
    model.load_state_dict(ckpt)
    model.eval()

    patches, pads, full, ys, xs = sliding_windows(clean_bin, tile, stride)
    prims_global = []
    with torch.no_grad():
        for (y0,x0,patch) in patches:
            # normalize to [0,1]
            p = (patch.astype(np.float32)/255.0)[None,None,:,:]
            t = torch.from_numpy(p).to(device)
            presence, ptype_logits, ctrl, width = model(t)
            presence = torch.sigmoid(presence)[0].cpu().numpy()     # S
            ptype = torch.softmax(ptype_logits[0], dim=-1).cpu().numpy()  # Sx2
            ctrl = ctrl[0].cpu().numpy()                           # Sx6 (norm)
            width = width[0].cpu().numpy()                         # S
            for s in range(presence.shape[0]):
                if presence[s] < presence_thresh: continue
                typ_idx = int(np.argmax(ptype[s]))
                typ = "line" if typ_idx == 0 else "bezier"
                # ctrl coords -> pixels within patch
                P0 = [float(ctrl[s,0]*tile), float(ctrl[s,1]*tile)]
                P1 = [float(ctrl[s,2]*tile), float(ctrl[s,3]*tile)]
                P2 = [float(ctrl[s,4]*tile), float(ctrl[s,5]*tile)]
                width_px = float(width[s])
                conf = float(presence[s])
                pred = {
                    "presence": conf, "type": typ,
                    "P0": P0, "P1": P1, "P2": None if typ=="line" else P2,
                    "width": max(1.0, width_px), "conf": conf
                }
                pred_g = primitive_global_from_patch(pred, y0, x0)
                prims_global.append(pred_g)
    return {"primitives": prims_global}

# ------------------------- Main vectorization -------------------------

def vectorize_raster(image_path: str,
                     out_dir: str,
                     denoise_weights: Optional[str],
                     primitive_weights: Optional[str],
                     patch_size: int = 64,
                     stride: int = 64,
                     num_slots: int = 16,
                     refine_iters: int = 30,
                     refine_lr: float = 0.8,
                     device: str = 'cpu'):

    ensure_dir(out_dir)
    img_gray = imread_gray(image_path)
    H, W = img_gray.shape

    use_deep = TORCH_AVAILABLE and (denoise_weights is not None) and (primitive_weights is not None)
    if not TORCH_AVAILABLE and (denoise_weights or primitive_weights):
        warnings.warn("PyTorch non disponibile: userò il fallback classico.")

    # 1) Preprocess
    if use_deep:
        print("[1/4] Preprocess (UNet)...")
        clean_bin = deep_preprocess(img_gray, denoise_weights, device)
    else:
        print("[1/4] Preprocess (classical)...")
        clean_bin = classical_preprocess(img_gray)

    cv2.imwrite(os.path.join(out_dir, "clean.png"), clean_bin)

    # 2) Patch primitive estimation
    if use_deep:
        print("[2/4] Patch primitives (ResNet+Transformer)...")
        est = deep_patch_primitives(clean_bin, primitive_weights, tile=patch_size,
                                    stride=stride, num_slots=num_slots, device=device)
    else:
        print("[2/4] Patch primitives (fallback Hough)...")
        est = classical_primitives(clean_bin)

    raw_path = os.path.join(out_dir, "primitives_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(est, f, indent=2)

    # 3) Refinement (snap to distance transform)
    print("[3/4] Refinement on distance field...")
    dist, gx, gy = distance_transform_with_grad(clean_bin)
    refined = []
    for pr in est["primitives"]:
        if pr["type"] == "line":
            ctrl = [(pr["P0"][0], pr["P0"][1]), (pr["P1"][0], pr["P1"][1])]
        else:
            ctrl = [(pr["P0"][0], pr["P0"][1]), (pr["P1"][0], pr["P1"][1]), (pr["P2"][0], pr["P2"][1])]
        new_ctrl = refine_control_points(ctrl, gx, gy, iters=refine_iters, lr=refine_lr)
        pr_ref = dict(pr)
        pr_ref["P0"] = [float(new_ctrl[0][0]), float(new_ctrl[0][1])]
        pr_ref["P1"] = [float(new_ctrl[1][0]), float(new_ctrl[1][1])]
        if pr["type"] == "bezier":
            pr_ref["P2"] = [float(new_ctrl[2][0]), float(new_ctrl[2][1])]
        refined.append(pr_ref)

    # 4) Merge overlapping across patches
    print("[4/4] Merge / deduplicate...")
    merged = merge_primitives(refined, tol=3.0)

    out_json = {"width": W, "height": H, "primitives": merged}
    with open(os.path.join(out_dir, "primitives_refined.json"), "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2)

    export_svg(os.path.join(out_dir, "vector.svg"), W, H, merged)

    print(f"[DONE] primitives: raw={len(est['primitives'])}  merged={len(merged)}")
    print(f"       outputs in {out_dir}: clean.png, primitives_raw.json, primitives_refined.json, vector.svg")

# ------------------------- CLI -------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Vectorize raster technical drawings into line segments + quadratic Beziers.")
    ap.add_argument("--image", required=True, help="Input raster image (png/jpg)")
    ap.add_argument("--out-dir", default="out_vec", help="Output directory")
    ap.add_argument("--denoise-weights", default=None, help="Path to UNet weights (.pth) for preprocessing")
    ap.add_argument("--primitive-weights", default=None, help="Path to primitive detector weights (.pth)")
    ap.add_argument("--patch-size", type=int, default=64)
    ap.add_argument("--stride", type=int, default=64, help="Use < patch-size for overlap blending")
    ap.add_argument("--num-slots", type=int, default=16, help="Max primitives per patch")
    ap.add_argument("--refine-iters", type=int, default=30)
    ap.add_argument("--refine-lr", type=float, default=0.8)
    ap.add_argument("--device", default="cuda" if TORCH_AVAILABLE and torch.cuda.is_available() else "cpu")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    vectorize_raster(
        image_path=args.image,
        out_dir=args.out_dir,
        denoise_weights=args.denoise_weights,
        primitive_weights=args.primitive_weights,
        patch_size=args.patch_size,
        stride=args.stride,
        num_slots=args.num_slots,
        refine_iters=args.refine_iters,
        refine_lr=args.refine_lr,
        device=args.device
    )
