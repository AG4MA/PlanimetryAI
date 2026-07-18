from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
PLANPARSER_ROOT = HERE.parents[2]
ATOMIC_ROOT = PLANPARSER_ROOT / "atomic_v2"
SOURCE = (
    ATOMIC_ROOT
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_002.png"
)
OUTPUT = (
    PLANPARSER_ROOT
    / "industrial_v1"
    / "text_nodes"
    / "artifacts"
    / "scheda_catastale"
    / "region_002"
    / "revision_001"
)

OCR_HEAVY = ATOMIC_ROOT / "ocr_heavy"
PADDLE_PYTHON = OCR_HEAVY / "runtime" / "venv" / "Scripts" / "python.exe"
PADDLE_MODEL_ROOT = (
    OCR_HEAVY
    / "runtime"
    / "revision_004"
    / "attempt_001_model_bundle"
)
PADDLE_DETECTOR = PADDLE_MODEL_ROOT / "PP-OCRv5_server_det"
PADDLE_RECOGNIZER = PADDLE_MODEL_ROOT / "latin_PP-OCRv5_mobile_rec"

OCR_DOCTR = ATOMIC_ROOT / "ocr_doctr"
DOCTR_PYTHON = OCR_DOCTR / "runtime" / ".venv" / "Scripts" / "python.exe"
DOCTR_CACHE = OCR_DOCTR / "runtime" / "models" / "doctr"

ENGINE_CONFIDENCE_FLOOR = 0.80
RAW_ABSTENTION_FLOOR = 0.50
PAIR_INTERSECTION_OVER_SMALLER = 0.35
PAIR_CENTER_DISTANCE_BY_HEIGHT = 1.50


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return jsonable(value.tolist())
    if hasattr(value, "item"):
        return value.item()
    return value


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    with path.open("xb") as stream:
        stream.write(data)


def write_bytes_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def bbox_center(box: list[float]) -> list[float]:
    return [round((box[0] + box[2]) / 2.0, 3), round((box[1] + box[3]) / 2.0, 3)]


def union_bbox(boxes: list[list[float]]) -> list[float]:
    return [
        round(min(box[0] for box in boxes), 3),
        round(min(box[1] for box in boxes), 3),
        round(max(box[2] for box in boxes), 3),
        round(max(box[3] for box in boxes), 3),
    ]


def bbox_metrics(a: list[float], b: list[float]) -> dict[str, float]:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    smaller = min(area_a, area_b)
    union = area_a + area_b - intersection
    center_distance = math.dist(bbox_center(a), bbox_center(b))
    height = max(1.0, ay2 - ay1, by2 - by1)
    return {
        "intersection_over_smaller": round(intersection / smaller, 6)
        if smaller
        else 0.0,
        "intersection_over_union": round(intersection / union, 6) if union else 0.0,
        "center_distance_px": round(center_distance, 6),
        "center_distance_by_height": round(center_distance / height, 6),
    }


def cache_files(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        for candidate in (
            Path("C:/Windows/Fonts") / name,
            Path("/usr/share/fonts/truetype/dejavu") / name,
        ):
            if candidate.is_file():
                return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def render_engine_overlay(
    source: Path, records: list[dict[str, Any]], engine: str
) -> bytes:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    font = load_font(12)
    for record in records:
        box = record["bbox_pixels"]
        abstained = record["abstention"]["abstained"]
        color = (224, 112, 0, 255) if abstained else (0, 150, 78, 255)
        fill = (255, 170, 0, 35) if abstained else (0, 190, 90, 32)
        draw.rectangle(tuple(box), outline=color, fill=fill, width=2)
        confidence = record["confidence_raw"]
        label = f"{record['source_ref']} {record['text_raw']} {confidence:.3f}"
        x, y = int(box[0]), max(0, int(box[1]) - 15)
        label_box = draw.textbbox((x, y), label, font=font)
        draw.rectangle(label_box, fill=(255, 255, 255, 225))
        draw.text((x, y), label, fill=color, font=font)
    header = f"{engine} raw detections | green=retained orange=raw-abstained"
    header_box = draw.textbbox((8, 8), header, font=font)
    draw.rectangle(header_box, fill=(255, 255, 255, 230))
    draw.text((8, 8), header, fill=(20, 20, 20), font=font)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def run_paddle_worker() -> None:
    started_at = utc_now()
    start = time.perf_counter()
    os.environ.update(
        {
            "PADDLE_PDX_CACHE_HOME": str(OUTPUT / "runtime_cache" / "paddle" / "paddlex"),
            "PADDLE_HOME": str(OUTPUT / "runtime_cache" / "paddle" / "paddle"),
            "HF_HOME": str(OCR_HEAVY / "runtime" / "revision_004" / "huggingface_cache"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "1",
            "FLAGS_use_mkldnn": "0",
            "FLAGS_enable_onednn": "0",
            "FLAGS_use_onednn": "0",
            "OMP_NUM_THREADS": "2",
        }
    )
    sys.path.insert(0, str(OCR_HEAVY))
    import run_ppocrv5_revision_002 as support
    from paddleocr import PaddleOCR

    support.INPUT_IMAGE = SOURCE
    init_start = time.perf_counter()
    predictor = PaddleOCR(
        text_detection_model_name="PP-OCRv5_server_det",
        text_detection_model_dir=str(PADDLE_DETECTOR),
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=str(PADDLE_RECOGNIZER),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        engine="paddle",
        enable_hpi=False,
        enable_mkldnn=False,
        cpu_threads=2,
    )
    init_seconds = time.perf_counter() - init_start
    inference_start = time.perf_counter()
    results = predictor.predict(str(SOURCE))
    inference_seconds = time.perf_counter() - inference_start
    raw_pages = [support.result_payload(result) for result in results]
    extracted: list[dict[str, Any]] = []
    for page in raw_pages:
        extracted.extend(support.extract_items(page))
    records: list[dict[str, Any]] = []
    for index, item in enumerate(extracted, start=1):
        box = [float(value) for value in item["bbox_xyxy"]]
        confidence = float(item["confidence"])
        reasons: list[str] = []
        if not item["text"].strip():
            reasons.append("empty_raw_transcription")
        if confidence < RAW_ABSTENTION_FLOOR:
            reasons.append("raw_recognition_confidence_below_floor")
        records.append(
            {
                "source_ref": f"paddle:item_{index:04d}",
                "text_raw": item["text"],
                "confidence_raw": confidence,
                "polygon_pixels": item["polygon"],
                "bbox_pixels": box,
                "center_pixels": bbox_center(box),
                "abstention": {"abstained": bool(reasons), "reasons": reasons},
            }
        )
    payload = {
        "schema_version": "planparser.industrial_v1.ocr_raw.v1",
        "created_at_utc": utc_now(),
        "status": "completed",
        "scope": {"document": "scheda_catastale", "region": "region_002"},
        "source": {"path": SOURCE.as_posix(), "sha256": sha256_file(SOURCE)},
        "engine": {
            "name": "PaddleOCR",
            "pipeline": "PP-OCRv5",
            "distribution_version": package_version("paddleocr"),
            "detector": "PP-OCRv5_server_det",
            "recognizer": "latin_PP-OCRv5_mobile_rec",
            "device": "cpu",
            "network_used": False,
        },
        "counts": {
            "raw_items": len(records),
            "raw_abstained": sum(record["abstention"]["abstained"] for record in records),
        },
        "timings_seconds": {
            "model_initialization": round(init_seconds, 6),
            "inference": round(inference_seconds, 6),
            "total": round(time.perf_counter() - start, 6),
        },
        "records": records,
        "engine_export_raw": raw_pages,
        "limits": [
            "raw confidence is not calibrated for floorplans",
            "no dictionary, correction, or semantic assignment applied",
            "missed text is absent from this engine output",
        ],
        "worker": {"started_at_utc": started_at, "python": sys.version, "platform": platform.platform()},
    }
    write_json_exclusive(OUTPUT / "paddle_raw.json", payload)
    write_bytes_exclusive(
        OUTPUT / "paddle_overlay.png", render_engine_overlay(SOURCE, records, "PP-OCRv5")
    )


def run_doctr_worker() -> None:
    started_at = utc_now()
    start = time.perf_counter()
    os.environ.update(
        {
            "DOCTR_CACHE_DIR": str(DOCTR_CACHE),
            "TORCH_HOME": str(OCR_DOCTR / "runtime" / "models"),
            "XDG_CACHE_HOME": str(OCR_DOCTR / "runtime" / "xdg_cache"),
            "HF_HOME": str(OCR_DOCTR / "runtime" / "models" / "huggingface"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    sys.path.insert(0, str(OCR_DOCTR))
    import run_doctr as support
    import doctr
    import torch
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor

    support.SOURCE = SOURCE
    support.ABSTENTION_CONFIDENCE_FLOOR = RAW_ABSTENTION_FLOOR
    cache_before = cache_files(DOCTR_CACHE)
    torch.set_grad_enabled(False)
    init_start = time.perf_counter()
    predictor = ocr_predictor(
        det_arch="db_resnet50",
        reco_arch="parseq",
        pretrained=True,
        assume_straight_pages=False,
        preserve_aspect_ratio=True,
        symmetric_pad=True,
        export_as_straight_boxes=False,
        detect_orientation=False,
        straighten_pages=False,
        detect_language=False,
    ).to(torch.device("cpu"))
    init_seconds = time.perf_counter() - init_start
    with Image.open(SOURCE) as opened:
        width, height = opened.size
    document = DocumentFile.from_images(str(SOURCE))
    inference_start = time.perf_counter()
    with torch.inference_mode():
        result = predictor(document)
    inference_seconds = time.perf_counter() - inference_start
    raw_export = support.json_safe(result.export())
    support_words = support.flatten_words(raw_export, width, height)
    records = [
        {
            "source_ref": f"doctr:{word['id']}",
            "text_raw": word["text_raw"],
            "confidence_raw": word["confidence_raw"],
            "objectness_score_raw": word["objectness_score_raw"],
            "polygon_pixels": word["polygon_pixels"],
            "bbox_pixels": [float(value) for value in word["bbox_pixels"]],
            "center_pixels": bbox_center([float(value) for value in word["bbox_pixels"]]),
            "page_index": word["page_index"],
            "block_index": word["block_index"],
            "line_index": word["line_index"],
            "word_index": word["word_index"],
            "abstention": word["abstention"],
        }
        for word in support_words
    ]
    cache_after = cache_files(DOCTR_CACHE)
    if cache_before != cache_after:
        raise RuntimeError("docTR model cache changed during offline inference")
    payload = {
        "schema_version": "planparser.industrial_v1.ocr_raw.v1",
        "created_at_utc": utc_now(),
        "status": "completed",
        "scope": {"document": "scheda_catastale", "region": "region_002"},
        "source": {"path": SOURCE.as_posix(), "sha256": sha256_file(SOURCE)},
        "engine": {
            "name": "docTR",
            "distribution_version": doctr.__version__,
            "detector": "db_resnet50",
            "recognizer": "parseq",
            "device": "cpu",
            "network_used": False,
            "cache_unchanged": True,
        },
        "counts": {
            "raw_items": len(records),
            "raw_abstained": sum(record["abstention"]["abstained"] for record in records),
        },
        "timings_seconds": {
            "model_initialization": round(init_seconds, 6),
            "inference": round(inference_seconds, 6),
            "total": round(time.perf_counter() - start, 6),
        },
        "records": records,
        "engine_export_raw": raw_export,
        "model_cache": cache_after,
        "limits": [
            "raw confidence is not calibrated for floorplans",
            "no dictionary, correction, or semantic assignment applied",
            "missed text is absent from this engine output",
        ],
        "worker": {"started_at_utc": started_at, "python": sys.version, "platform": platform.platform()},
    }
    write_json_exclusive(OUTPUT / "doctr_raw.json", payload)
    write_bytes_exclusive(
        OUTPUT / "doctr_overlay.png", render_engine_overlay(SOURCE, records, "docTR")
    )


def candidate_role(text: str, consensus: bool) -> dict[str, Any]:
    normalized = normalize_text(text).strip(" .")
    if not consensus:
        return {
            "classification": "unresolved",
            "abstained": True,
            "evidence": ["role inference disabled without exact two-engine consensus"],
        }
    room_labels = {
        "bagno",
        "camera",
        "cucina",
        "sala",
        "soggiorno",
        "ingresso",
        "studio",
        "ripostiglio",
        "lavanderia",
    }
    if normalized in room_labels:
        return {
            "classification": "room_label_candidate",
            "abstained": False,
            "evidence": ["exact two-engine transcription consensus", "exact lexical class match"],
            "not_a_final_semantic_assignment": True,
        }
    if normalized in {"vano scala", "scala", "scale"}:
        return {
            "classification": "vertical_circulation_label_candidate",
            "abstained": False,
            "evidence": ["exact two-engine transcription consensus", "exact lexical class match"],
            "not_a_final_semantic_assignment": True,
        }
    if normalized in {"portico", "balcone", "terrazzo", "cortile"}:
        return {
            "classification": "exterior_or_semi_exterior_space_label_candidate",
            "abstained": False,
            "evidence": ["exact two-engine transcription consensus", "exact lexical class match"],
            "not_a_final_semantic_assignment": True,
        }
    if normalized in {"altra uiu", "altra u.i.u", "altra u.i.u."}:
        return {
            "classification": "adjacent_unit_context_candidate",
            "abstained": False,
            "evidence": ["exact two-engine transcription consensus", "exact lexical class match"],
            "not_a_final_semantic_assignment": True,
        }
    if normalized in {"dis", "disimpegno"}:
        return {
            "classification": "distribution_space_label_candidate",
            "abstained": True,
            "evidence": ["abbreviation or context-dependent label; semantic decision deferred"],
        }
    return {
        "classification": "unresolved",
        "abstained": True,
        "evidence": ["no exact conservative lexical role mapping"],
    }


def build_text_nodes(
    paddle: list[dict[str, Any]], doctr: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unmatched_doctr = set(range(len(doctr)))
    nodes: list[dict[str, Any]] = []
    assignment_audit: list[dict[str, Any]] = []
    for pp_index, pp in enumerate(paddle):
        pp_box = pp["bbox_pixels"]
        candidates: list[tuple[int, dict[str, float]]] = []
        for dt_index in sorted(unmatched_doctr):
            metrics = bbox_metrics(pp_box, doctr[dt_index]["bbox_pixels"])
            if (
                metrics["intersection_over_smaller"] >= PAIR_INTERSECTION_OVER_SMALLER
                or metrics["center_distance_by_height"] <= PAIR_CENTER_DISTANCE_BY_HEIGHT
                and metrics["intersection_over_union"] > 0
            ):
                candidates.append((dt_index, metrics))
        candidates.sort(key=lambda item: (doctr[item[0]]["center_pixels"][0], item[0]))
        selected_indices = [index for index, _ in candidates]
        for index in selected_indices:
            unmatched_doctr.remove(index)
        dt_group = [doctr[index] for index in selected_indices]
        pp_text = pp["text_raw"]
        dt_text = " ".join(item["text_raw"] for item in dt_group) if dt_group else None
        normalized_pp = normalize_text(pp_text)
        normalized_dt = normalize_text(dt_text or "")
        exact = bool(dt_group) and normalized_pp == normalized_dt
        all_confident = (
            pp["confidence_raw"] >= ENGINE_CONFIDENCE_FLOOR
            and bool(dt_group)
            and all(item["confidence_raw"] >= ENGINE_CONFIDENCE_FLOOR for item in dt_group)
        )
        consensus = exact and all_confident and not pp["abstention"]["abstained"] and all(
            not item["abstention"]["abstained"] for item in dt_group
        )
        if consensus:
            classification = "consensus"
            reasons = ["exact normalized transcription", "spatially overlapping engine observations"]
        elif dt_group:
            classification = "conflict_or_ambiguous"
            reasons = ["two engines aligned spatially but exact conservative consensus not met"]
        else:
            classification = "single_engine"
            reasons = ["no spatially aligned docTR observation"]
        boxes = [pp_box] + [item["bbox_pixels"] for item in dt_group]
        box = union_bbox(boxes)
        raw_alternatives = [
            {
                "engine": "paddle",
                "source_refs": [pp["source_ref"]],
                "text_raw": pp_text,
                "confidence_raw": pp["confidence_raw"],
            }
        ]
        if dt_group:
            raw_alternatives.append(
                {
                    "engine": "doctr",
                    "source_refs": [item["source_ref"] for item in dt_group],
                    "text_raw": dt_text,
                    "confidence_raw": [item["confidence_raw"] for item in dt_group],
                }
            )
        node = {
            "node_id": f"text_node_{len(nodes) + 1:04d}",
            "node_type": "text_observation",
            "geometry_separation": {
                "stored_as_geometry_primitive": False,
                "line_or_wall_membership_assigned": False,
                "future_relation_target": "spatial_context_or_space_node",
            },
            "bbox_pixels": box,
            "center_pixels": bbox_center(box),
            "raw_alternatives": raw_alternatives,
            "decision": {
                "classification": classification,
                "consensus_text": pp_text if consensus else None,
                "abstained": not consensus,
                "reasons": reasons,
                "normalized_exact": exact,
                "fuzzy_similarity": round(SequenceMatcher(None, normalized_pp, normalized_dt).ratio(), 6)
                if dt_group
                else None,
            },
            "candidate_role": candidate_role(pp_text, consensus),
            "relations": [],
        }
        nodes.append(node)
        assignment_audit.append(
            {
                "paddle_ref": pp["source_ref"],
                "doctr_refs": [item["source_ref"] for item in dt_group],
                "pair_metrics": [metrics for _, metrics in candidates],
                "node_id": node["node_id"],
            }
        )
    for dt_index in sorted(unmatched_doctr):
        item = doctr[dt_index]
        box = item["bbox_pixels"]
        nodes.append(
            {
                "node_id": f"text_node_{len(nodes) + 1:04d}",
                "node_type": "text_observation",
                "geometry_separation": {
                    "stored_as_geometry_primitive": False,
                    "line_or_wall_membership_assigned": False,
                    "future_relation_target": "spatial_context_or_space_node",
                },
                "bbox_pixels": box,
                "center_pixels": bbox_center(box),
                "raw_alternatives": [
                    {
                        "engine": "doctr",
                        "source_refs": [item["source_ref"]],
                        "text_raw": item["text_raw"],
                        "confidence_raw": item["confidence_raw"],
                    }
                ],
                "decision": {
                    "classification": "single_engine",
                    "consensus_text": None,
                    "abstained": True,
                    "reasons": ["no spatially aligned PaddleOCR observation"],
                    "normalized_exact": False,
                    "fuzzy_similarity": None,
                },
                "candidate_role": candidate_role(item["text_raw"], False),
                "relations": [],
            }
        )
    return nodes, assignment_audit


def render_nodes(source: Path, nodes: list[dict[str, Any]], counts: dict[str, int]) -> bytes:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    panel_width = 460
    canvas = Image.new("RGB", (image.width + panel_width, max(image.height, 729)), "white")
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(12)
    title = load_font(22, bold=True)
    medium = load_font(14, bold=True)
    colors = {
        "consensus": (0, 155, 78, 255),
        "conflict_or_ambiguous": (232, 145, 0, 255),
        "single_engine": (105, 105, 105, 255),
    }
    for node in nodes:
        classification = node["decision"]["classification"]
        color = colors[classification]
        box = node["bbox_pixels"]
        draw.rectangle(tuple(box), outline=color, fill=(*color[:3], 28), width=3)
        text = node["decision"]["consensus_text"]
        if text is None:
            text = " <> ".join(
                str(alt["text_raw"]) for alt in node["raw_alternatives"]
            )
        label = f"{node['node_id']} {text}"
        x, y = int(box[0]), max(0, int(box[1]) - 15)
        label_box = draw.textbbox((x, y), label, font=font)
        draw.rectangle(label_box, fill=(255, 255, 255, 230))
        draw.text((x, y), label, fill=color, font=font)
    px = image.width
    draw.rectangle((px, 0, canvas.width, canvas.height), fill=(250, 250, 250, 255))
    draw.line((px, 0, px, canvas.height), fill=(20, 20, 20, 255), width=2)
    x, y = px + 20, 20
    draw.text((x, y), "TEXT NODES — region_002", fill=(20, 20, 20), font=title)
    y += 40
    draw.text((x, y), "Independent from line/wall geometry", fill=(50, 50, 50), font=medium)
    y += 34
    for classification, label in (
        ("consensus", "Exact two-engine consensus"),
        ("conflict_or_ambiguous", "Aligned but ambiguous: abstained"),
        ("single_engine", "Single engine: abstained"),
    ):
        color = colors[classification]
        draw.rectangle((x, y + 2, x + 20, y + 17), fill=color)
        draw.text((x + 30, y), label, fill=(35, 35, 35), font=font)
        y += 25
    y += 12
    draw.text((x, y), "Counts", fill=(20, 20, 20), font=medium)
    y += 27
    for key in ("total", "consensus", "conflict_or_ambiguous", "single_engine", "role_candidates", "role_abstained"):
        draw.text((x, y), f"{key}: {counts[key]}", fill=(45, 45, 45), font=font)
        y += 21
    y += 12
    draw.text((x, y), "Nodes", fill=(20, 20, 20), font=medium)
    y += 25
    for node in nodes:
        text = node["decision"]["consensus_text"]
        if text is None:
            text = " / ".join(str(alt["text_raw"]) for alt in node["raw_alternatives"])
        role = node["candidate_role"]["classification"]
        line = f"{node['node_id']}: {text} [{role}]"
        if len(line) > 57:
            line = line[:56] + "…"
        draw.text((x, y), line, fill=colors[node["decision"]["classification"]], font=font)
        y += 20
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def run_subprocess(engine: str, executable: Path) -> dict[str, Any]:
    start = time.perf_counter()
    command = [str(executable), str(Path(__file__).resolve()), "--worker", engine]
    completed = subprocess.run(
        command,
        cwd=str(PLANPARSER_ROOT.parent),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=1800,
        check=False,
    )
    return {
        "engine": engine,
        "command": command,
        "return_code": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - start, 6),
        "stdout_tail": completed.stdout[-10000:],
        "stderr_tail": completed.stderr[-10000:],
    }


def orchestrate() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"immutable output revision exists: {OUTPUT}")
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    required = [PADDLE_PYTHON, DOCTR_PYTHON, PADDLE_DETECTOR, PADDLE_RECOGNIZER, DOCTR_CACHE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing local runtime inputs: {missing}")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    with Image.open(SOURCE) as opened:
        width, height = opened.size
    preflight = {
        "schema_version": "planparser.industrial_v1.text_nodes.preflight.v1",
        "created_at_utc": utc_now(),
        "source": {
            "path": SOURCE.as_posix(),
            "sha256": sha256_file(SOURCE),
            "width_px": width,
            "height_px": height,
        },
        "architecture": {
            "text_is_a_separate_node_type": True,
            "text_is_not_merged_into_lines_or_walls": True,
            "node_fields": [
                "bbox_pixels",
                "center_pixels",
                "raw_alternatives",
                "decision/confidence/abstention",
                "candidate_role",
                "relations",
            ],
        },
        "offline_engines": {
            "paddle": {
                "python": PADDLE_PYTHON.as_posix(),
                "detector": PADDLE_DETECTOR.as_posix(),
                "recognizer": PADDLE_RECOGNIZER.as_posix(),
            },
            "doctr": {"python": DOCTR_PYTHON.as_posix(), "cache": DOCTR_CACHE.as_posix()},
        },
        "network_required": False,
    }
    write_json_exclusive(OUTPUT / "preflight_manifest.json", preflight)
    attempts: list[dict[str, Any]] = []
    for engine, executable in (("paddle", PADDLE_PYTHON), ("doctr", DOCTR_PYTHON)):
        try:
            attempt = run_subprocess(engine, executable)
        except Exception as exc:
            attempt = {
                "engine": engine,
                "return_code": None,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        attempts.append(attempt)
        if attempt.get("return_code") != 0:
            write_json_exclusive(OUTPUT / f"{engine}_error.json", attempt)
    paddle_path = OUTPUT / "paddle_raw.json"
    doctr_path = OUTPUT / "doctr_raw.json"
    if not paddle_path.is_file() or not doctr_path.is_file():
        write_json_exclusive(
            OUTPUT / "run_manifest.json",
            {
                "schema_version": "planparser.industrial_v1.text_nodes.run.v1",
                "status": "partial_engine_failure",
                "created_at_utc": utc_now(),
                "attempts": attempts,
                "ensemble_produced": False,
                "reason": "both independent raw engines are required for conservative ensemble",
            },
        )
        raise RuntimeError("one or more OCR engines failed; raw evidence preserved")
    paddle_payload = json.loads(paddle_path.read_text(encoding="utf-8"))
    doctr_payload = json.loads(doctr_path.read_text(encoding="utf-8"))
    if paddle_payload["source"]["sha256"] != doctr_payload["source"]["sha256"]:
        raise RuntimeError("engine source hashes differ")
    nodes, assignment_audit = build_text_nodes(
        paddle_payload["records"], doctr_payload["records"]
    )
    classifications = [node["decision"]["classification"] for node in nodes]
    counts = {
        "total": len(nodes),
        "consensus": classifications.count("consensus"),
        "conflict_or_ambiguous": classifications.count("conflict_or_ambiguous"),
        "single_engine": classifications.count("single_engine"),
        "role_candidates": sum(not node["candidate_role"]["abstained"] for node in nodes),
        "role_abstained": sum(node["candidate_role"]["abstained"] for node in nodes),
    }
    ensemble = {
        "schema_version": "planparser.industrial_v1.text_nodes.v1",
        "created_at_utc": utc_now(),
        "status": "completed_conservative_two_engine_alignment",
        "scope": {
            "document": "scheda_catastale",
            "region": "region_002",
            "coordinate_space": "region_002_crop_pixels",
            "width_px": width,
            "height_px": height,
        },
        "architecture": {
            "node_type": "text_observation",
            "separate_from_geometry_graph": True,
            "line_or_wall_membership_assigned": False,
            "intended_next_relation": "text_node_to_surrounding_space",
        },
        "inputs": {
            "paddle_raw": {"path": paddle_path.as_posix(), "sha256": sha256_file(paddle_path)},
            "doctr_raw": {"path": doctr_path.as_posix(), "sha256": sha256_file(doctr_path)},
            "source_sha256": paddle_payload["source"]["sha256"],
        },
        "policy": {
            "spatial_alignment_precedes_text_comparison": True,
            "normalization": "Unicode NFKC + casefold + whitespace collapse; no spelling correction",
            "consensus_requires": [
                "spatial overlap",
                "exact normalized transcription",
                "all raw confidences >= 0.80",
                "no raw engine abstention",
            ],
            "all_non_consensus_nodes_abstain": True,
            "candidate_roles_are_not_final_semantics": True,
        },
        "counts": counts,
        "text_nodes": nodes,
        "alignment_assignment_audit": assignment_audit,
        "limits": [
            "consensus is engine agreement, not ground truth",
            "no geometry or room containment relation is asserted in this revision",
            "candidate roles are conservative lexical candidates and may abstain",
            "no human review or correction was used",
        ],
    }
    ensemble_bytes = (json.dumps(ensemble, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    overlay_bytes = render_nodes(SOURCE, nodes, counts)
    write_bytes_exclusive(OUTPUT / "text_nodes.json", ensemble_bytes)
    write_bytes_exclusive(OUTPUT / "text_nodes_overlay.png", overlay_bytes)
    output_names = [
        "preflight_manifest.json",
        "paddle_raw.json",
        "paddle_overlay.png",
        "doctr_raw.json",
        "doctr_overlay.png",
        "text_nodes.json",
        "text_nodes_overlay.png",
    ]
    manifest = {
        "schema_version": "planparser.industrial_v1.text_nodes.run.v1",
        "status": "completed",
        "created_at_utc": utc_now(),
        "attempts": attempts,
        "counts": counts,
        "outputs": {
            name: {"bytes": (OUTPUT / name).stat().st_size, "sha256": sha256_file(OUTPUT / name)}
            for name in output_names
        },
        "generator": {
            "path": Path(__file__).resolve().as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "write_policy": {"exclusive_create": True, "existing_artifacts_modified": False},
    }
    write_json_exclusive(OUTPUT / "run_manifest.json", manifest)
    print(json.dumps(counts, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("paddle", "doctr"))
    args = parser.parse_args()
    if args.worker == "paddle":
        run_paddle_worker()
    elif args.worker == "doctr":
        run_doctr_worker()
    else:
        orchestrate()


if __name__ == "__main__":
    main()
