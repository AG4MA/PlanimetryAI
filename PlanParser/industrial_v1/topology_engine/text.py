"""Compatibility facade for topology text processing."""

from .domain.text_adapters import adapt_text_payload
from .domain.text_normalization import (
    first_config_value as _first_config_value,
    normalize_text,
)

__all__ = ["adapt_text_payload", "normalize_text"]
