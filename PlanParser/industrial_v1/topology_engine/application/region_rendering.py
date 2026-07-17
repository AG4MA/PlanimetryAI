from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..rendering import (
    build_region_contact_sheet,
    draw_barriers,
    draw_text_nodes,
    draw_topology,
    encode_png,
    pil_from_bgr,
)
from .contracts import JobContractError
from .region_analysis import RegionComputation


@dataclass
class RegionRendering:
    contact_sheet: Image.Image
    artifacts: dict[str, bytes]


def _encode_mask(mask: np.ndarray) -> bytes:
    return encode_png(Image.fromarray(mask.astype(np.uint8), mode="L"))


def _encode_labels(labels: np.ndarray) -> bytes:
    maximum = int(labels.max(initial=0))
    if maximum > 65535:
        raise JobContractError("Space-label raster exceeds uint16 capacity")
    return encode_png(Image.fromarray(labels.astype(np.uint16), mode="I;16"))


def render_region(
    source_bgr: np.ndarray, computation: RegionComputation
) -> RegionRendering:
    """Render review evidence separately from the computation kernel."""

    source = pil_from_bgr(source_bgr)
    text_overlay = draw_text_nodes(source, computation.text_nodes)
    barrier_overlay = draw_barriers(
        source,
        computation.barriers.observed_geometry,
        computation.barriers.synthetic_closures,
        crop_boundary=computation.barriers.crop_boundary,
    )
    topology_overlay = draw_topology(
        source, computation.labels, computation.text_nodes, computation.spaces
    )
    contact_sheet = build_region_contact_sheet(
        region_id=computation.region_id,
        source=source,
        text_overlay=text_overlay,
        barrier_overlay=barrier_overlay,
        topology_overlay=topology_overlay,
        nodes=computation.text_nodes,
        spaces=computation.spaces,
        edges=computation.edges,
        profile_id=computation.config.profile,
    )
    artifacts = {
        "text_nodes_overlay.png": encode_png(text_overlay),
        "barrier_overlay.png": encode_png(barrier_overlay),
        "topology_overlay.png": encode_png(topology_overlay),
        "text_space_topology_contact_sheet.png": encode_png(contact_sheet),
        "observed_geometry_mask.png": _encode_mask(
            computation.barriers.observed_geometry
        ),
        "crop_boundary_mask.png": _encode_mask(computation.barriers.crop_boundary),
        "raw_observed_mask.png": _encode_mask(computation.barriers.raw_observed),
        "synthetic_closures_mask.png": _encode_mask(
            computation.barriers.synthetic_closures
        ),
        "effective_barrier_mask.png": _encode_mask(
            computation.barriers.effective_barrier
        ),
        "space_labels_u16.png": _encode_labels(computation.labels),
    }
    return RegionRendering(contact_sheet=contact_sheet, artifacts=artifacts)


__all__ = ["RegionRendering", "render_region"]
