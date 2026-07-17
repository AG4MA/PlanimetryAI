from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
ATOMIC_V2_DIR = SCRIPT_DIR.parent
DEFAULT_SOURCE = (
    ATOMIC_V2_DIR
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_001.png"
)
DEFAULT_OUTPUT = (
    SCRIPT_DIR
    / "artifacts"
    / "scheda_catastale"
    / "region_001"
    / "revision_001"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def png_write_new(path: Path, image: np.ndarray) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise RuntimeError(f"Could not write PNG: {path}")


def json_write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    path.write_text(serialized + "\n", encoding="utf-8", newline="\n")


def matrix_to_json(matrix: np.ndarray) -> list[list[float]]:
    rounded = np.round(matrix.astype(np.float64), 10)
    return [[float(value) for value in row] for row in rounded.tolist()]


def scale_matrix(scale: float) -> np.ndarray:
    return np.array(
        [[scale, 0.0, 0.0], [0.0, scale, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values, kind="stable")
    ordered_values = values[order]
    ordered_weights = weights[order]
    cutoff = float(ordered_weights.sum()) * 0.5
    index = int(np.searchsorted(np.cumsum(ordered_weights), cutoff, side="left"))
    return float(ordered_values[min(index, len(ordered_values) - 1)])


def measure_axis_skew(gray: np.ndarray) -> dict[str, Any]:
    height, width = gray.shape
    blurred = cv2.GaussianBlur(gray, (3, 3), 0.0)
    edges = cv2.Canny(blurred, 60, 180, apertureSize=3, L2gradient=True)
    min_line_length = max(50, int(round(min(height, width) * 0.12)))
    max_line_gap = max(6, int(round(min(height, width) * 0.015)))
    lines = cv2.HoughLinesP(
        edges,
        rho=1.0,
        theta=np.pi / 720.0,
        threshold=45,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )

    residuals: list[float] = []
    lengths: list[float] = []
    horizontal_count = 0
    vertical_count = 0
    if lines is not None:
        reshaped_lines = np.asarray(lines).reshape(-1, 4)
        for entry in reshaped_lines:
            x1, y1, x2, y2 = [float(value) for value in entry]
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dy, dx))
            residual = ((angle + 45.0) % 90.0) - 45.0
            if abs(residual) > 5.0:
                continue
            residuals.append(residual)
            lengths.append(length)
            normalized_angle = angle % 180.0
            if normalized_angle <= 45.0 or normalized_angle >= 135.0:
                horizontal_count += 1
            else:
                vertical_count += 1

    if not residuals:
        return {
            "algorithm": "canny_hough_axis_weighted_median",
            "canny_thresholds": [60, 180],
            "hough_theta_degrees": 0.25,
            "max_axis_residual_degrees": 5.0,
            "min_line_length_px": min_line_length,
            "max_line_gap_px": max_line_gap,
            "candidate_count": 0,
            "horizontal_candidate_count": 0,
            "vertical_candidate_count": 0,
            "estimated_skew_degrees": None,
            "weighted_mad_degrees": None,
            "measurable": False,
            "reason": "no_near_axis_line_candidates",
        }

    values = np.asarray(residuals, dtype=np.float64)
    weights = np.asarray(lengths, dtype=np.float64)
    estimate = weighted_median(values, weights)
    weighted_mad = weighted_median(np.abs(values - estimate), weights)
    total_length = float(weights.sum())
    minimum_total_length = float(min(height, width) * 1.2)
    measurable = (
        len(values) >= 6
        and total_length >= minimum_total_length
        and weighted_mad <= 0.75
    )
    if not measurable:
        reason = "insufficient_or_inconsistent_axis_support"
    elif abs(estimate) < 0.12:
        reason = "measurable_within_deadband"
    else:
        reason = "measurable_correction_available"

    return {
        "algorithm": "canny_hough_axis_weighted_median",
        "canny_thresholds": [60, 180],
        "hough_theta_degrees": 0.25,
        "max_axis_residual_degrees": 5.0,
        "min_line_length_px": min_line_length,
        "max_line_gap_px": max_line_gap,
        "candidate_count": int(len(values)),
        "horizontal_candidate_count": int(horizontal_count),
        "vertical_candidate_count": int(vertical_count),
        "candidate_total_length_px": round(total_length, 4),
        "minimum_total_length_px": round(minimum_total_length, 4),
        "estimated_skew_degrees": round(estimate, 6),
        "weighted_mad_degrees": round(weighted_mad, 6),
        "deadband_degrees": 0.12,
        "measurable": bool(measurable),
        "reason": reason,
    }


def linework_suppression(binary_black_on_white: np.ndarray, kernel_length: int) -> tuple[np.ndarray, np.ndarray]:
    ink = 255 - binary_black_on_white
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_length, 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_length))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vertical_kernel)
    line_mask = cv2.max(horizontal, vertical)
    line_mask = cv2.dilate(
        line_mask,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    cleaned_ink = cv2.bitwise_and(ink, cv2.bitwise_not(line_mask))
    cleaned = 255 - cleaned_ink
    return cleaned, line_mask


def make_contact_sheet(entries: list[tuple[str, np.ndarray]]) -> np.ndarray:
    columns = 3
    preview_width = 340
    preview_height = 346
    label_height = 42
    gap = 12
    rows = int(math.ceil(len(entries) / columns))
    sheet_width = columns * preview_width + (columns + 1) * gap
    sheet_height = rows * (preview_height + label_height) + (rows + 1) * gap
    sheet = np.full((sheet_height, sheet_width, 3), 245, dtype=np.uint8)

    for index, (label, image) in enumerate(entries):
        row = index // columns
        column = index % columns
        x0 = gap + column * preview_width
        y0 = gap + row * (preview_height + label_height)
        if image.ndim == 2:
            preview = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            preview = image.copy()
        source_height, source_width = preview.shape[:2]
        fit = min(preview_width / source_width, preview_height / source_height)
        resized_width = max(1, int(round(source_width * fit)))
        resized_height = max(1, int(round(source_height * fit)))
        interpolation = cv2.INTER_AREA if fit < 1.0 else cv2.INTER_LANCZOS4
        resized = cv2.resize(preview, (resized_width, resized_height), interpolation=interpolation)
        px = x0 + (preview_width - resized_width) // 2
        py = y0 + (preview_height - resized_height) // 2
        sheet[py : py + resized_height, px : px + resized_width] = resized
        cv2.rectangle(
            sheet,
            (x0, y0),
            (x0 + preview_width - 1, y0 + preview_height - 1),
            (180, 180, 180),
            1,
        )
        cv2.putText(
            sheet,
            label,
            (x0 + 4, y0 + preview_height + 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    return sheet


def build(source: Path, output_dir: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Source crop not found: {source}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output revision is not empty; refusing overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if normalized is None:
        raise RuntimeError(f"OpenCV could not decode source crop: {source}")
    height, width = normalized.shape[:2]
    gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)

    up2_color = cv2.resize(normalized, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LANCZOS4)
    up4_color = cv2.resize(normalized, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_LANCZOS4)
    up2_gray = cv2.cvtColor(up2_color, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(up2_gray)
    adaptive = cv2.adaptiveThreshold(
        clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        41,
        15,
    )
    otsu_input = cv2.GaussianBlur(clahe, (3, 3), 0.0)
    otsu_threshold, otsu = cv2.threshold(
        otsu_input,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    skew = measure_axis_skew(gray)
    estimated_skew = skew["estimated_skew_degrees"]
    deskew_applied = bool(
        skew["measurable"]
        and estimated_skew is not None
        and abs(float(estimated_skew)) >= float(skew["deadband_degrees"])
        and abs(float(estimated_skew)) <= 3.0
    )
    source_to_up2 = scale_matrix(2.0)
    if deskew_applied:
        center = ((up2_gray.shape[1] - 1) / 2.0, (up2_gray.shape[0] - 1) / 2.0)
        affine = cv2.getRotationMatrix2D(center, float(estimated_skew), 1.0)
        deskewed = cv2.warpAffine(
            clahe,
            affine,
            (up2_gray.shape[1], up2_gray.shape[0]),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )
        rotation_h = np.vstack([affine, [0.0, 0.0, 1.0]])
        deskew_matrix = rotation_h @ source_to_up2
    else:
        deskewed = clahe.copy()
        deskew_matrix = source_to_up2.copy()

    minimum_dimension_2x = min(otsu.shape)
    line_kernel_long = max(61, int(round(minimum_dimension_2x * 0.075)))
    line_kernel_extra_long = max(101, int(round(minimum_dimension_2x * 0.125)))
    if line_kernel_long % 2 == 0:
        line_kernel_long += 1
    if line_kernel_extra_long % 2 == 0:
        line_kernel_extra_long += 1
    suppressed_long, mask_long = linework_suppression(otsu, line_kernel_long)
    suppressed_extra_long, mask_extra_long = linework_suppression(otsu, line_kernel_extra_long)

    variants: list[dict[str, Any]] = []
    contact_entries: list[tuple[str, np.ndarray]] = []

    def add_variant(
        variant_id: str,
        filename: str,
        purpose: str,
        image: np.ndarray,
        color_space: str,
        chain: list[dict[str, Any]],
        source_to_variant: np.ndarray,
        extra: dict[str, Any] | None = None,
    ) -> None:
        path = output_dir / filename
        png_write_new(path, image)
        image_height, image_width = image.shape[:2]
        record: dict[str, Any] = {
            "id": variant_id,
            "filename": filename,
            "purpose": purpose,
            "sha256": sha256_file(path),
            "width_px": int(image_width),
            "height_px": int(image_height),
            "color_space": color_space,
            "transform_chain": chain,
            "coordinates": {
                "convention": "pixel_centers_xy_from_top_left",
                "source_to_variant_homogeneous_3x3": matrix_to_json(source_to_variant),
                "variant_to_source_homogeneous_3x3": matrix_to_json(
                    np.linalg.inv(source_to_variant)
                ),
            },
        }
        if extra:
            record.update(extra)
        variants.append(record)
        contact_entries.append((variant_id, image))

    identity = np.eye(3, dtype=np.float64)
    add_variant(
        "normalized_original",
        "01_normalized_original.png",
        "Stable PNG decode in source coordinates; no enhancement.",
        normalized,
        "BGR_sRGB",
        [{"operation": "decode_png", "mode": "BGR_8bit"}],
        identity,
    )
    add_variant(
        "normalized_2x",
        "02_normalized_2x.png",
        "Two-times color enlargement for OCR engines that benefit from larger glyphs.",
        up2_color,
        "BGR_sRGB",
        [
            {"operation": "decode_png", "mode": "BGR_8bit"},
            {"operation": "resize", "scale_x": 2.0, "scale_y": 2.0, "interpolation": "LANCZOS4"},
        ],
        scale_matrix(2.0),
    )
    add_variant(
        "normalized_4x",
        "03_normalized_4x.png",
        "Four-times color enlargement for small printed labels.",
        up4_color,
        "BGR_sRGB",
        [
            {"operation": "decode_png", "mode": "BGR_8bit"},
            {"operation": "resize", "scale_x": 4.0, "scale_y": 4.0, "interpolation": "LANCZOS4"},
        ],
        scale_matrix(4.0),
    )
    add_variant(
        "grayscale_clahe_2x",
        "04_grayscale_clahe_2x.png",
        "Local-contrast grayscale branch without binarization.",
        clahe,
        "GRAY_8bit",
        [
            {"operation": "decode_png", "mode": "BGR_8bit"},
            {"operation": "resize", "scale_x": 2.0, "scale_y": 2.0, "interpolation": "LANCZOS4"},
            {"operation": "convert_color", "from": "BGR", "to": "GRAY"},
            {"operation": "CLAHE", "clip_limit": 2.0, "tile_grid_size": [8, 8]},
        ],
        scale_matrix(2.0),
    )
    add_variant(
        "adaptive_threshold_2x",
        "05_adaptive_threshold_2x.png",
        "Locally adaptive binary branch for uneven paper/background intensity.",
        adaptive,
        "GRAY_BINARY_8bit",
        [
            {"operation": "inherit", "variant": "grayscale_clahe_2x"},
            {
                "operation": "adaptive_threshold",
                "method": "GAUSSIAN_C",
                "threshold_type": "BINARY",
                "block_size": 41,
                "c": 15,
            },
        ],
        scale_matrix(2.0),
    )
    add_variant(
        "otsu_threshold_2x",
        "06_otsu_threshold_2x.png",
        "Global binary branch after a conservative Gaussian prefilter.",
        otsu,
        "GRAY_BINARY_8bit",
        [
            {"operation": "inherit", "variant": "grayscale_clahe_2x"},
            {"operation": "gaussian_blur", "kernel_size": [3, 3], "sigma": 0.0},
            {
                "operation": "otsu_threshold",
                "threshold_type": "BINARY",
                "selected_threshold": round(float(otsu_threshold), 6),
            },
        ],
        scale_matrix(2.0),
    )
    add_variant(
        "deskew_clahe_2x",
        "07_deskew_clahe_2x.png",
        "CLAHE branch with deskew applied only when near-axis support is measurable and outside the deadband.",
        deskewed,
        "GRAY_8bit",
        [
            {"operation": "inherit", "variant": "grayscale_clahe_2x"},
            {
                "operation": "conditional_deskew",
                "applied": deskew_applied,
                "rotation_degrees": round(float(estimated_skew), 6) if deskew_applied else 0.0,
                "interpolation": "CUBIC" if deskew_applied else "NONE",
                "border_mode": "CONSTANT_WHITE" if deskew_applied else "NONE",
            },
        ],
        deskew_matrix,
        {"deskew_measurement": skew},
    )
    add_variant(
        "otsu_suppress_long_axis_lines_2x",
        "08_otsu_suppress_long_axis_lines_2x.png",
        "Conservative OCR branch removing only long horizontal/vertical binary runs.",
        suppressed_long,
        "GRAY_BINARY_8bit",
        [
            {"operation": "inherit", "variant": "otsu_threshold_2x"},
            {
                "operation": "axis_line_morphological_open_and_remove",
                "horizontal_kernel": [line_kernel_long, 1],
                "vertical_kernel": [1, line_kernel_long],
                "mask_dilation_kernel": [3, 3],
                "mask_dilation_iterations": 1,
            },
        ],
        scale_matrix(2.0),
        {
            "diagnostics": {
                "removed_mask_foreground_pixels": int(np.count_nonzero(mask_long)),
                "removed_mask_fraction": round(float(np.count_nonzero(mask_long)) / mask_long.size, 8),
            }
        },
    )
    add_variant(
        "otsu_suppress_extra_long_axis_lines_2x",
        "09_otsu_suppress_extra_long_axis_lines_2x.png",
        "More conservative OCR branch restricted to extra-long horizontal/vertical binary runs.",
        suppressed_extra_long,
        "GRAY_BINARY_8bit",
        [
            {"operation": "inherit", "variant": "otsu_threshold_2x"},
            {
                "operation": "axis_line_morphological_open_and_remove",
                "horizontal_kernel": [line_kernel_extra_long, 1],
                "vertical_kernel": [1, line_kernel_extra_long],
                "mask_dilation_kernel": [3, 3],
                "mask_dilation_iterations": 1,
            },
        ],
        scale_matrix(2.0),
        {
            "diagnostics": {
                "removed_mask_foreground_pixels": int(np.count_nonzero(mask_extra_long)),
                "removed_mask_fraction": round(float(np.count_nonzero(mask_extra_long)) / mask_extra_long.size, 8),
            }
        },
    )

    contact_sheet = make_contact_sheet(contact_entries)
    contact_sheet_path = output_dir / "preprocess_contact_sheet.png"
    png_write_new(contact_sheet_path, contact_sheet)

    try:
        source_relative = source.resolve().relative_to(ATOMIC_V2_DIR.resolve()).as_posix()
    except ValueError:
        source_relative = str(source.resolve())

    manifest = {
        "schema_version": "planparser.ocr_preprocess.manifest.v1",
        "deterministic": True,
        "accuracy_claim": None,
        "generator": "ocr_preprocess/build_preprocess.py",
        "source": {
            "path": source_relative,
            "sha256": sha256_file(source),
            "width_px": int(width),
            "height_px": int(height),
            "channels": int(normalized.shape[2]),
            "dtype": str(normalized.dtype),
        },
        "variant_count": len(variants),
        "variants": variants,
        "contact_sheet": {
            "filename": contact_sheet_path.name,
            "sha256": sha256_file(contact_sheet_path),
            "width_px": int(contact_sheet.shape[1]),
            "height_px": int(contact_sheet.shape[0]),
            "layout": {"columns": 3, "rows": 3},
        },
        "notes": [
            "These are deterministic OCR input candidates, not OCR recognition results.",
            "No OCR accuracy or floor-plan interpretation claim is made.",
            "Inverse coordinate matrices map variant pixel-center coordinates back to the source crop.",
        ],
    }
    manifest_path = output_dir / "preprocess_manifest.json"
    json_write_new(manifest_path, manifest)
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic OCR preprocessing variants.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = build(arguments.source.resolve(), arguments.output.resolve())
    print(result)
