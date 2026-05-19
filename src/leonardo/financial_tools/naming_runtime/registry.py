from __future__ import annotations

from typing import Any

from .constructs_core import _normalize_construct_key
from .indicators import get_indicator_signal_names
from .oscillators import get_oscillator_signal_names
from .constructs import get_construct_signal_names


def get_tool_signal_names(family: str, tool_key: str, **params: Any) -> tuple[str, ...]:
    """Resolve canonical output signal names for one tool family."""
    family_key = str(family).strip().lower()
    if family_key == "indicator":
        return get_indicator_signal_names(tool_key, **params)
    if family_key == "oscillator":
        return get_oscillator_signal_names(tool_key, **params)
    if family_key == "construct":
        return get_construct_signal_names(_normalize_construct_key(tool_key), **params)
    raise KeyError(f"Unsupported tool family for signal naming: {family}")
