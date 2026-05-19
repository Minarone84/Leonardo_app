from __future__ import annotations

from .models import ToolStyleCapabilities, ToolEditCapabilities

DEFAULT_GENERIC_STYLE_CAPABILITIES = ToolStyleCapabilities()
DEFAULT_GENERIC_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="generic")

SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES = ToolStyleCapabilities(
    supported_modules=(
        "line_style",
        "conditional_line_color",
        "directional_line_width",
    ),
    supports_condition_driven_style=True,
    supports_utility_style_drivers=False,
    supports_fill_between=False,
    supports_per_signal_styling=False,
)

MULTI_LINE_INDICATOR_STYLE_CAPABILITIES = ToolStyleCapabilities(
    supported_modules=(
        "line_style",
        "per_signal_line_style",
        "fill_between_signals",
        "conditional_line_color",
        "conditional_fill_color",
        "directional_line_width",
    ),
    supports_condition_driven_style=True,
    supports_utility_style_drivers=False,
    supports_fill_between=True,
    supports_per_signal_styling=True,
)

UTILITY_DRIVEN_MULTI_LINE_INDICATOR_STYLE_CAPABILITIES = ToolStyleCapabilities(
    supported_modules=(
        "line_style",
        "per_signal_line_style",
        "fill_between_signals",
        "conditional_line_color",
        "conditional_fill_color",
        "directional_line_width",
    ),
    supports_condition_driven_style=True,
    supports_utility_style_drivers=True,
    supports_fill_between=True,
    supports_per_signal_styling=True,
)

MULTI_SIGNAL_EVENT_INDICATOR_STYLE_CAPABILITIES = ToolStyleCapabilities(
    supported_modules=("per_signal_line_style",),
    supports_condition_driven_style=False,
    supports_utility_style_drivers=False,
    supports_fill_between=False,
    supports_per_signal_styling=True,
)

SINGLE_PERIOD_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="single_period")
DUAL_PERIOD_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="dual_period")
PERIOD_PLUS_FLOAT_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="period_plus_float")
DUAL_LENGTH_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="dual_length")
