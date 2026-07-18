from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping


def _legacy_room_aliases() -> dict[str, str]:
    return {
        "bagno": "bagno",
        "camera": "camera",
        "dis": "disimpegno",
        "disimpegno": "disimpegno",
        "soggiorno-pranzo": "soggiorno-pranzo",
        "soggiorno pranzo": "soggiorno-pranzo",
        "rip": "ripostiglio",
        "ripostiglio": "ripostiglio",
        "balcone": "balcone",
        "cucina": "cucina",
        "sala": "sala",
        "portico": "portico",
    }


@dataclass(frozen=True)
class TextAbstentionPolicy:
    """Keep OCR and semantic-role abstention as independent decisions.

    The legacy topology scripts used every text box when auditing geometry,
    irrespective of either kind of abstention.  Both defaults therefore stay
    ``True``.  Later policies can change either branch without conflating the
    two signals.
    """

    include_ocr_abstained_in_barrier_overlap: bool = True
    include_semantic_role_abstained_in_barrier_overlap: bool = True
    ocr_abstained_field: str = "ocr_abstained"
    semantic_role_abstained_field: str = "semantic_role_abstained"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TextAbstentionPolicy":
        allowed = {item.name for item in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown text-abstention policy fields: {sorted(unknown)}")
        return cls(**dict(value))


@dataclass(frozen=True)
class TopologyEngineConfig:
    """Typed parameters for the pure topology/barrier kernels.

    ``legacy_v1()`` reproduces the constants used by
    ``text_space_topology`` revision 002.  Pixel parameters are intentionally
    explicit; resolution-aware profiles can be introduced without silently
    changing this frozen baseline.
    """

    profile: str = "legacy_v1"

    room_aliases: Mapping[str, str] = field(default_factory=_legacy_room_aliases)
    object_terms: tuple[str, ...] = ("armadio", "arredo fisso")
    composite_enabled: bool = True
    composite_max_distance_px: float = 80.0
    composite_policy: str = "legacy_replacement"

    line_text_padding_px: int = 2
    line_text_overlap_exclusion_ratio: float = 0.25
    line_text_exclusion_length_ceiling_px: float = 180.0
    band_text_overlap_exclusion_ratio: float = 0.35
    band_text_exclusion_length_ceiling_px: float = 180.0

    solid_line_barrier_thickness_px: int = 3
    uncertain_line_barrier_thickness_px: int = 2
    include_crop_boundary: bool = True
    crop_boundary_thickness_px: int = 4

    closure_kernel_length_px: int = 31
    barrier_dilation_kernel_px: int = 3
    barrier_dilation_iterations: int = 1

    nearby_source_tolerance_px: float = 7.0
    boundary_near_kernel_px: int = 7
    boundary_source_stroke_px: int = 3

    compatibility_mode: str = "legacy_v1"
    nearest_free_max_radius_px: int = 60
    contour_epsilon_ratio: float = 0.003
    contour_min_epsilon_px: float = 1.0
    space_contract: str = "legacy_1_1"
    space_boundary_near_kernel_px: int = 5
    evidence_near_kernel_px: int = 7
    radial_source_tolerance_px: float = 7.0
    semantic_abstention_policy: str = "transcription_only"
    text_assignment_policy: str = "legacy_region1"
    include_boundary_evidence_edges: bool = True

    observed_boundary_abstention_below: float = 0.50
    synthetic_boundary_abstention_above: float = 0.30
    competition_boundary_abstention_above: float = 0.25
    legacy_support_abstention_below: float = 0.35
    legacy_competition_abstention_above: float = 0.35
    confidence_cap: float = 0.93
    confidence_base: float = 0.24
    confidence_observed_weight: float = 0.48
    confidence_synthetic_weight: float = 0.10
    confidence_non_abstained_bonus: float = 0.08
    confidence_large_area_bonus: float = 0.07
    confidence_large_area_min_px2: int = 500
    legacy_confidence_base: float = 0.30
    legacy_confidence_observed_weight: float = 0.45
    legacy_confidence_non_abstained_bonus: float = 0.10
    legacy_confidence_large_area_bonus: float = 0.08

    abstention_policy: TextAbstentionPolicy = field(default_factory=TextAbstentionPolicy)

    def __post_init__(self) -> None:
        if not self.profile:
            raise ValueError("profile must be non-empty")
        non_negative = {
            "line_text_padding_px": self.line_text_padding_px,
            "line_text_exclusion_length_ceiling_px": self.line_text_exclusion_length_ceiling_px,
            "band_text_exclusion_length_ceiling_px": self.band_text_exclusion_length_ceiling_px,
            "nearby_source_tolerance_px": self.nearby_source_tolerance_px,
            "composite_max_distance_px": self.composite_max_distance_px,
            "contour_epsilon_ratio": self.contour_epsilon_ratio,
            "contour_min_epsilon_px": self.contour_min_epsilon_px,
            "radial_source_tolerance_px": self.radial_source_tolerance_px,
            "confidence_base": self.confidence_base,
            "confidence_observed_weight": self.confidence_observed_weight,
            "confidence_synthetic_weight": self.confidence_synthetic_weight,
            "confidence_non_abstained_bonus": self.confidence_non_abstained_bonus,
            "confidence_large_area_bonus": self.confidence_large_area_bonus,
            "legacy_confidence_base": self.legacy_confidence_base,
            "legacy_confidence_observed_weight": self.legacy_confidence_observed_weight,
            "legacy_confidence_non_abstained_bonus": self.legacy_confidence_non_abstained_bonus,
            "legacy_confidence_large_area_bonus": self.legacy_confidence_large_area_bonus,
        }
        for name, value in non_negative.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        ratios = {
            "line_text_overlap_exclusion_ratio": self.line_text_overlap_exclusion_ratio,
            "band_text_overlap_exclusion_ratio": self.band_text_overlap_exclusion_ratio,
            "observed_boundary_abstention_below": self.observed_boundary_abstention_below,
            "synthetic_boundary_abstention_above": self.synthetic_boundary_abstention_above,
            "competition_boundary_abstention_above": self.competition_boundary_abstention_above,
            "legacy_support_abstention_below": self.legacy_support_abstention_below,
            "legacy_competition_abstention_above": self.legacy_competition_abstention_above,
            "confidence_cap": self.confidence_cap,
        }
        for name, value in ratios.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        positive_integers = {
            "solid_line_barrier_thickness_px": self.solid_line_barrier_thickness_px,
            "uncertain_line_barrier_thickness_px": self.uncertain_line_barrier_thickness_px,
            "crop_boundary_thickness_px": self.crop_boundary_thickness_px,
            "closure_kernel_length_px": self.closure_kernel_length_px,
            "barrier_dilation_kernel_px": self.barrier_dilation_kernel_px,
            "barrier_dilation_iterations": self.barrier_dilation_iterations,
            "boundary_near_kernel_px": self.boundary_near_kernel_px,
            "boundary_source_stroke_px": self.boundary_source_stroke_px,
            "nearest_free_max_radius_px": self.nearest_free_max_radius_px,
            "space_boundary_near_kernel_px": self.space_boundary_near_kernel_px,
            "evidence_near_kernel_px": self.evidence_near_kernel_px,
            "confidence_large_area_min_px2": self.confidence_large_area_min_px2,
        }
        for name, value in positive_integers.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "closure_kernel_length_px",
            "barrier_dilation_kernel_px",
            "boundary_near_kernel_px",
            "space_boundary_near_kernel_px",
            "evidence_near_kernel_px",
        ):
            if getattr(self, name) % 2 == 0:
                raise ValueError(f"{name} must be odd")
        if self.composite_policy not in {"legacy_replacement", "additive"}:
            raise ValueError("composite_policy must be legacy_replacement or additive")
        if self.compatibility_mode not in {"legacy_v1", "strict_v2"}:
            raise ValueError("compatibility_mode must be legacy_v1 or strict_v2")
        if self.space_contract not in {"legacy_1_0", "legacy_1_1"}:
            raise ValueError("space_contract must be legacy_1_0 or legacy_1_1")
        if self.semantic_abstention_policy not in {
            "transcription_only",
            "transcription_or_role",
            "role_only",
        }:
            raise ValueError("unsupported semantic_abstention_policy")
        if self.text_assignment_policy not in {"legacy_region1", "non_seed", "none"}:
            raise ValueError("unsupported text_assignment_policy")

    @classmethod
    def legacy_v1(cls) -> "TopologyEngineConfig":
        return cls()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TopologyEngineConfig":
        if not isinstance(value, Mapping):
            raise TypeError("TopologyEngineConfig input must be a mapping")
        allowed = {item.name for item in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown topology config fields: {sorted(unknown)}")
        payload = dict(value)
        if "room_aliases" in payload:
            aliases = payload["room_aliases"]
            if not isinstance(aliases, Mapping):
                raise TypeError("room_aliases must be a mapping")
            payload["room_aliases"] = dict(aliases)
        if "object_terms" in payload:
            terms = payload["object_terms"]
            if isinstance(terms, (str, bytes)) or not isinstance(terms, (list, tuple)):
                raise TypeError("object_terms must be an array")
            payload["object_terms"] = tuple(str(term) for term in terms)
        policy = payload.get("abstention_policy")
        if policy is not None and not isinstance(policy, TextAbstentionPolicy):
            if not isinstance(policy, Mapping):
                raise TypeError("abstention_policy must be a mapping")
            payload["abstention_policy"] = TextAbstentionPolicy.from_dict(policy)
        return cls(**payload)

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "TopologyEngineConfig":
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise TypeError("TopologyEngineConfig JSON must contain an object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


LEGACY_V1 = TopologyEngineConfig.legacy_v1()
