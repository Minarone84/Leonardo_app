from __future__ import annotations

from .models import (
    ToolKind,
    ToolBehaviorSpec,
    ToolStyleCapabilities,
    ToolEditCapabilities,
    ToolOutputSpec,
    OutputSignalSpec,
    OscillatorGuideLevelSpec,
    OscillatorVisualSpec,
)

DEFAULT_INDICATOR_BEHAVIOR = ToolBehaviorSpec(
    output_mode="overlay",
    chart_renderable=True,
    supports_style=True,
    supports_pane_layout=False,
    supports_last_value=True,
)

DEFAULT_OSCILLATOR_BEHAVIOR = ToolBehaviorSpec(
    output_mode="oscillator-pane",
    chart_renderable=True,
    supports_style=True,
    supports_pane_layout=True,
    supports_last_value=True,
)

DEFAULT_NON_VISUAL_CONSTRUCT_BEHAVIOR = ToolBehaviorSpec(
    output_mode="non-visual",
    chart_renderable=False,
    supports_style=False,
    supports_pane_layout=False,
    supports_last_value=False,
)

DEFAULT_OVERLAY_CONSTRUCT_BEHAVIOR = ToolBehaviorSpec(
    output_mode="overlay",
    chart_renderable=True,
    supports_style=True,
    supports_pane_layout=False,
    supports_last_value=True,
)

DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR = ToolBehaviorSpec(
    output_mode="oscillator-pane",
    chart_renderable=True,
    supports_style=True,
    supports_pane_layout=True,
    supports_last_value=True,
)

DEFAULT_GENERIC_STYLE_CAPABILITIES = ToolStyleCapabilities()
DEFAULT_GENERIC_EDIT_CAPABILITIES = ToolEditCapabilities(preferred_module="generic")


def _default_behavior_for_kind(kind: ToolKind) -> ToolBehaviorSpec:
    if kind == "oscillator":
        return DEFAULT_OSCILLATOR_BEHAVIOR
    if kind == "construct":
        return DEFAULT_NON_VISUAL_CONSTRUCT_BEHAVIOR
    return DEFAULT_INDICATOR_BEHAVIOR


def _default_signal_specs(names: tuple[str, ...]) -> tuple[OutputSignalSpec, ...]:
    return tuple(OutputSignalSpec(name=name) for name in names)


def DEFAULT_LINE_OUTPUT(
    names: tuple[str, ...],
    *,
    signals: tuple[OutputSignalSpec, ...] | None = None,
) -> ToolOutputSpec:
    return ToolOutputSpec(
        structure="line-series",
        output_names=tuple(names),
        signals=signals if signals is not None else _default_signal_specs(tuple(names)),
        accepts_empty_render_output=False,
    )


def DEFAULT_MULTI_LINE_OUTPUT(
    names: tuple[str, ...],
    *,
    signals: tuple[OutputSignalSpec, ...] | None = None,
) -> ToolOutputSpec:
    return ToolOutputSpec(
        structure="multi-line-series",
        output_names=tuple(names),
        signals=signals if signals is not None else _default_signal_specs(tuple(names)),
        accepts_empty_render_output=False,
    )


DEFAULT_ANALYSIS_ONLY_OUTPUT = ToolOutputSpec(
    structure="analysis-only",
    output_names=(),
    signals=(),
    accepts_empty_render_output=True,
)

DEFAULT_BOUNDED_OSCILLATOR_VISUAL_SPEC = OscillatorVisualSpec(
    range_mode="fixed_bounds",
    bounds=(0.0, 100.0),
    guide_levels=(
        OscillatorGuideLevelSpec(
            kind="overbought",
            value=70.0,
            visible=True,
            label="Overbought",
            description="Default overbought guide level for bounded RSI-like oscillators.",
        ),
        OscillatorGuideLevelSpec(
            kind="center",
            value=50.0,
            visible=True,
            label="Center",
            description="Default center guide level for bounded RSI-like oscillators.",
        ),
        OscillatorGuideLevelSpec(
            kind="oversold",
            value=30.0,
            visible=True,
            label="Oversold",
            description="Default oversold guide level for bounded RSI-like oscillators.",
        ),
    ),
)

ARSI_BOUNDED_OSCILLATOR_VISUAL_SPEC = OscillatorVisualSpec(
    range_mode="fixed_bounds",
    bounds=(0.0, 100.0),
    guide_levels=(
        OscillatorGuideLevelSpec(
            kind="overbought",
            value=80.0,
            visible=True,
            label="Overbought",
            description="Default overbought guide level for ARSI.",
        ),
        OscillatorGuideLevelSpec(
            kind="center",
            value=50.0,
            visible=True,
            label="Center",
            description="Default center guide level for ARSI.",
        ),
        OscillatorGuideLevelSpec(
            kind="oversold",
            value=20.0,
            visible=True,
            label="Oversold",
            description="Default oversold guide level for ARSI.",
        ),
    ),
)

DEFAULT_ZERO_CENTERED_OSCILLATOR_VISUAL_SPEC = OscillatorVisualSpec(
    range_mode="auto",
    bounds=None,
    guide_levels=(
        OscillatorGuideLevelSpec(
            kind="zero",
            value=0.0,
            visible=True,
            label="Zero",
            description="Default zero guide level for centered oscillators.",
        ),
    ),
)

DEFAULT_UNBOUNDED_OSCILLATOR_VISUAL_SPEC = OscillatorVisualSpec(
    range_mode="auto",
    bounds=None,
    guide_levels=(),
)
