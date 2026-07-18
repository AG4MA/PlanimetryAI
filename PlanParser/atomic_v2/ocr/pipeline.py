"""Tesseract-backed raw OCR with explicit abstention and provenance."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path
from statistics import fmean
from typing import Any


class OcrError(RuntimeError):
    """Raised when an OCR input or destination is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_reference(path: Path) -> tuple[str, str]:
    project_root = Path(__file__).resolve().parents[3]
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root).as_posix(), "project_relative"
    except ValueError:
        return resolved.as_posix(), "absolute"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    path.write_bytes(data)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _find_tesseract() -> Path | None:
    from_path = shutil.which("tesseract")
    if from_path:
        return Path(from_path).resolve()

    candidates = (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
    )
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _load_parent_region(source: Path) -> dict[str, Any] | None:
    metadata_path = source.parent / "regions.json"
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for region in metadata.get("regions", []):
        if region.get("id") == source.stem:
            return {
                "bbox_px": region.get("bbox_px"),
                "id": region.get("id"),
                "metadata_path": _project_reference(metadata_path)[0],
                "metadata_sha256": _sha256(metadata_path),
            }
    return None


def _base_report(
    source: Path,
    *,
    width: int,
    height: int,
    mode: str,
    parent_region: dict[str, Any] | None,
    confidence_threshold: float,
) -> dict[str, Any]:
    source_reference, reference_kind = _project_reference(source)
    parent_bbox = parent_region.get("bbox_px") if parent_region else None
    return {
        "elements": [],
        "engine_records": [],
        "output": {
            "overlay_file": None,
            "overlay_generated": False,
        },
        "provenance": {
            "binding": "pytesseract",
            "binding_version": _package_version("pytesseract"),
            "confidence_threshold": confidence_threshold,
            "engine": "tesseract",
            "parent_region": parent_region,
            "semantic_assignment": False,
            "text_correction": False,
        },
        "region": {
            "abstained": False,
            "bbox_px_local": [0, 0, width, height],
            "bbox_px_parent": parent_bbox,
            "confidence": None,
            "id": source.stem,
            "reasons": [],
            "transcription_raw": None,
        },
        "schema": "planparser.atomic_v2.raw_ocr",
        "schema_version": "1.0.0",
        "source": {
            "byte_size": source.stat().st_size,
            "dimensions_px": [width, height],
            "mode": mode,
            "path": source_reference,
            "reference_kind": reference_kind,
            "sha256": _sha256(source),
        },
        "status": "pending",
    }


def _engine_unavailable(report: dict[str, Any], report_path: Path) -> Path:
    reason = "ocr_engine_unavailable: pytesseract is installed but the Tesseract executable was not found"
    report["provenance"]["engine_available"] = False
    report["provenance"]["engine_executable"] = None
    report["region"]["abstained"] = True
    report["region"]["reasons"] = [reason]
    report["status"] = "abstained"
    _write_json(report_path, report)
    return report_path


def _available_languages(pytesseract: Any) -> tuple[list[str], str]:
    languages = sorted(str(item) for item in pytesseract.get_languages(config=""))
    if "ita" in languages and "eng" in languages:
        selected = "ita+eng"
    elif "ita" in languages:
        selected = "ita"
    elif "eng" in languages:
        selected = "eng"
    elif languages:
        selected = languages[0]
    else:
        raise OcrError("Tesseract is available but exposes no language data")
    return languages, selected


def _confidence(raw: Any) -> tuple[str, float | None]:
    raw_text = str(raw)
    try:
        numeric = float(raw_text)
    except (TypeError, ValueError):
        return raw_text, None
    if numeric < 0:
        return raw_text, None
    return raw_text, round(numeric / 100.0, 6)


def _run_engine(
    source: Path,
    output_dir: Path,
    report: dict[str, Any],
    executable: Path,
    confidence_threshold: float,
) -> Path:
    import pytesseract
    from PIL import Image, ImageDraw, ImageFont
    from pytesseract import Output

    pytesseract.pytesseract.tesseract_cmd = str(executable)
    engine_version = str(pytesseract.get_tesseract_version()).splitlines()[0]
    available_languages, language = _available_languages(pytesseract)
    config = "--psm 11"

    with Image.open(source) as opened:
        image = opened.convert("RGB")
        transcription_raw = pytesseract.image_to_string(image, lang=language, config=config)
        data = pytesseract.image_to_data(image, lang=language, config=config, output_type=Output.DICT)

    keys = sorted(data)
    record_count = len(data.get("level", []))
    records: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    parent_bbox = report["region"]["bbox_px_parent"]

    for index in range(record_count):
        record = {key: data[key][index] for key in keys}
        records.append(record)
        if int(record.get("level", 0)) != 5:
            continue

        left = int(record["left"])
        top = int(record["top"])
        width = int(record["width"])
        height = int(record["height"])
        raw_confidence, normalized_confidence = _confidence(record.get("conf"))
        transcription = str(record.get("text", ""))
        reasons: list[str] = ["raw_word_record_emitted_by_tesseract"]
        abstained = False
        if not transcription.strip():
            abstained = True
            reasons.append("empty_raw_transcription")
        if normalized_confidence is None:
            abstained = True
            reasons.append("engine_confidence_unavailable")
        elif normalized_confidence < confidence_threshold:
            abstained = True
            reasons.append("confidence_below_acceptance_threshold")

        bbox_parent = None
        if isinstance(parent_bbox, list) and len(parent_bbox) == 4:
            bbox_parent = [parent_bbox[0] + left, parent_bbox[1] + top, width, height]

        elements.append(
            {
                "abstained": abstained,
                "bbox_px_local": [left, top, width, height],
                "bbox_px_parent": bbox_parent,
                "confidence": normalized_confidence,
                "confidence_raw": raw_confidence,
                "id": f"ocr_{len(elements) + 1:04d}",
                "reasons": reasons,
                "transcription_raw": transcription,
            }
        )

    usable_confidences = [
        item["confidence"]
        for item in elements
        if item["confidence"] is not None and not item["abstained"]
    ]
    report["elements"] = elements
    report["engine_records"] = records
    report["provenance"].update(
        {
            "available_languages": available_languages,
            "engine_available": True,
            "engine_executable": executable.as_posix(),
            "engine_version": engine_version,
            "language": language,
            "page_segmentation_mode": 11,
        }
    )
    report["region"]["transcription_raw"] = transcription_raw
    report["region"]["confidence"] = (
        round(fmean(usable_confidences), 6) if usable_confidences else None
    )
    report["region"]["abstained"] = not bool(usable_confidences)
    report["region"]["reasons"] = (
        ["no_non_abstained_ocr_elements"]
        if report["region"]["abstained"]
        else ["contains_raw_ocr_elements"]
    )
    report["status"] = "abstained" if report["region"]["abstained"] else "completed"

    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()
    for element in elements:
        x, y, width, height = element["bbox_px_local"]
        color = (220, 40, 40) if element["abstained"] else (0, 150, 40)
        draw.rectangle((x, y, x + width, y + height), outline=color, width=2)
        confidence_label = (
            "conf=null"
            if element["confidence"] is None
            else f"conf={element['confidence']:.2f}"
        )
        label = f"{element['id']} {confidence_label}"
        label_box = draw.textbbox((x, y), label, font=font, stroke_width=0)
        label_height = label_box[3] - label_box[1]
        label_y = max(0, y - label_height - 3)
        draw.rectangle(
            (x, label_y, x + (label_box[2] - label_box[0]) + 4, label_y + label_height + 3),
            fill=(255, 255, 255),
        )
        draw.text((x + 2, label_y + 1), label, fill=color, font=font)

    overlay_path = output_dir / "ocr_overlay.png"
    overlay.save(overlay_path, format="PNG", compress_level=9, optimize=False)
    report["output"] = {
        "overlay_file": "ocr_overlay.png",
        "overlay_generated": True,
        "overlay_sha256": _sha256(overlay_path),
    }
    report_path = output_dir / "ocr.json"
    _write_json(report_path, report)
    return report_path


def run_raw_ocr(
    source: Path | str,
    output_dir: Path | str,
    *,
    confidence_threshold: float = 0.60,
) -> Path:
    """Run raw OCR, or emit a complete abstention report if Tesseract is absent."""

    source_path = Path(source).resolve()
    destination = Path(output_dir).resolve()
    if not source_path.is_file():
        raise OcrError(f"source region does not exist: {source_path}")
    if source_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise OcrError("source region must be PNG or JPEG")
    if destination.exists():
        raise OcrError(f"output directory already exists; refusing to overwrite: {destination}")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")

    try:
        from PIL import Image
    except ImportError as exc:
        raise OcrError("Pillow is required to inspect the source region") from exc

    try:
        with Image.open(source_path) as image:
            image.verify()
        with Image.open(source_path) as image:
            width, height = image.size
            mode = image.mode
    except Exception as exc:
        raise OcrError(f"cannot decode source region: {exc}") from exc

    destination.mkdir(parents=True, exist_ok=False)
    report_path = destination / "ocr.json"
    report = _base_report(
        source_path,
        width=width,
        height=height,
        mode=mode,
        parent_region=_load_parent_region(source_path),
        confidence_threshold=confidence_threshold,
    )

    executable = _find_tesseract()
    if executable is None:
        return _engine_unavailable(report, report_path)
    return _run_engine(source_path, destination, report, executable, confidence_threshold)
