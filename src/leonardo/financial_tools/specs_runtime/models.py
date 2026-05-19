from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Literal, Optional

from leonardo.financial_tools.execution_context import ToolExecutionEnvironment

ToolKind = Literal["indicator", "oscillator", "construct"]
ValueType = Literal["int", "float", "bool", "str"]

ToolOutputMode = Literal["overlay", "oscillator-pane", "non-visual"]
ToolOutputStructure = Literal[
    "line-series",
    "multi-line-series",
    "levels",
    "bands",
    "state",
    "events",
    "analysis-only",
]
OutputSignalType = Literal["signal", "utility"]

SignalSemanticRole = Literal[
    "primary",
    "center",
    "upper",
    "lower",
    "fast",
    "slow",
    "state",
]

SignalValueType = Literal["numeric", "categorical", "boolean"]

ConstructInputBindingType = Literal[
    "unary_source",
    "fast_slow",
    "fast_mid_slow",
    "multi_source",
]

ConstructSourceFamily = Literal[
    "ohlc",
    "indicator",
    "oscillator",
    "construct",
]

ConstructSourceCompatibility = Literal[
    "mixed_numeric",
    "same_family",
    "same_oscillator_type",
]

ConstructOutputCardinality = Literal[
    "single",
    "matches_inputs",
    "one_or_more",
]

ConstructOutputRole = Literal[
    "plotted_line",
    "state_series",
    "analysis_only",
]

StyleModuleKey = Literal[
    "line_style",
    "per_signal_line_style",
    "fill_between_signals",
    "conditional_line_color",
    "conditional_fill_color",
    "directional_line_width",
]

EditModuleKey = Literal[
    "single_period",
    "dual_period",
    "period_plus_float",
    "dual_length",
    "generic",
]

GuideLevelKind = Literal[
    "overbought",
    "oversold",
    "center",
    "zero",
]

OscillatorRangeMode = Literal[
    "auto",
    "fixed_bounds",
]


@dataclass(frozen=True)
class DataInputSpec:
    """
    Canonical market-data input required by a tool.

    Notes:
    - These names are UI / spec-layer canonical names.
    - Compute modules remain responsible for resolving storage-level variations
      such as 'Volume' vs 'volume'.
    """
    name: str
    dtype: ValueType
    required: bool = True
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class ParamSpec:
    """
    Configurable parameter required or accepted by a tool.
    """
    name: str
    dtype: ValueType
    required: bool = True
    default: Any = None
    label: str = ""
    description: str = ""
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: tuple[Any, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolBehaviorSpec:
    """
    Declares how a tool behaves once applied to a chart session.

    This metadata is intentionally separate from `kind`:

    - `kind` answers what the tool is
    - `behavior` answers how it behaves in the chart/runtime layer

    This allows constructs to be:
    - overlay-like
    - oscillator-pane-like
    - non-visual

    without forcing rendering behavior to be guessed from family name alone.
    """
    output_mode: ToolOutputMode
    chart_renderable: bool = True
    supports_style: bool = True
    supports_pane_layout: bool = False
    supports_last_value: bool = True
    supported_environments: tuple[ToolExecutionEnvironment, ...] = ("historical",)
    default_environment: ToolExecutionEnvironment = "historical"


@dataclass(frozen=True)
class ToolStyleCapabilities:
    """
    Declarative style-module capability contract for a tool.

    Important:
    - This is capability metadata, not UI layout metadata.
    - It tells the GUI which reusable style modules may be exposed for the tool.
    - It must remain renderer-agnostic and must not contain actual style values
      such as default colors, widths, or opacities.
    """
    supported_modules: tuple[StyleModuleKey, ...] = ()
    supports_condition_driven_style: bool = False
    supports_utility_style_drivers: bool = False
    supports_fill_between: bool = False
    supports_per_signal_styling: bool = False


@dataclass(frozen=True)
class ToolEditCapabilities:
    """
    Declarative edit-module capability contract for a tool.

    Purpose:
    - allows the GUI to map a tool to a reusable edit form module family
    - keeps param-shape knowledge centralized in specs rather than hardcoded in UI
    """
    preferred_module: EditModuleKey | str = "generic"


@dataclass(frozen=True)
class OutputSignalSpec:
    """
    Identity card for one output column emitted by a tool.

    Notes:
    - `name` is the canonical output column name or legacy template.
    - `signal_type` separates meaningful analytical outputs from auxiliary data.
    - `renderable` indicates whether this output should be treated as a chart line.
    - `analysis_usable` indicates whether this output should be offered as a future source.
    - `semantic_role` gives module logic a stable, tool-local meaning for the signal.
    - `value_type` allows style modules to distinguish numeric plotted series from
      categorical / state-like utility outputs.
    - `can_drive_style_rules` allows a signal to be used as a condition driver for
      style modules even when the signal is not itself renderable.
    """
    name: str
    signal_type: OutputSignalType = "signal"
    renderable: bool = True
    analysis_usable: bool = True
    default_visible: bool = True
    label: str = ""
    description: str = ""
    semantic_role: SignalSemanticRole | str = "primary"
    value_type: SignalValueType = "numeric"
    can_drive_style_rules: bool = False


@dataclass(frozen=True)
class ToolOutputSpec:
    """
    Declares the expected output shape of a tool.

    This is intentionally descriptive rather than renderer-specific.
    It helps the controller/panel pipeline understand whether a tool is
    expected to produce renderable series or can validly produce
    analysis-only/non-visual results.
    """
    structure: ToolOutputStructure
    output_names: tuple[str, ...] = ()
    signals: tuple[OutputSignalSpec, ...] = ()
    accepts_empty_render_output: bool = False


@dataclass(frozen=True)
class ConstructIOSpec:
    """
    Declarative construct input/output type contract.

    Purpose:
    - formalize accepted binding shape for chart-facing constructs
    - declare which upstream source families are admissible
    - express whether sources may be mixed or must remain semantically aligned
    - describe the expected output cardinality and high-level output role

    Important:
    - this is spec metadata only
    - it does not define computation logic
    - it does not define styling, pane policy, or renderer behavior
    """
    input_binding: ConstructInputBindingType
    allowed_source_families: tuple[ConstructSourceFamily, ...]
    source_compatibility: ConstructSourceCompatibility = "mixed_numeric"
    output_cardinality: ConstructOutputCardinality = "single"
    output_role: ConstructOutputRole = "plotted_line"


@dataclass(frozen=True)
class OscillatorGuideLevelSpec:
    """
    Declarative semantic guide-level metadata for oscillator panes.

    Important:
    - This is spec metadata, not renderer instructions.
    - It expresses semantic default guide levels that the chart-local panel
      layer may translate into pane visual policy.
    - It must not contain concrete styling such as colors, line widths,
      or dash patterns.
    """
    kind: GuideLevelKind
    value: float
    visible: bool = True
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class OscillatorVisualSpec:
    """
    Declarative oscillator visual-semantics metadata.

    Purpose:
    - centralize bounded-vs-auto oscillator identity in the spec layer
    - declare default numeric bounds when the oscillator family is bounded
    - declare semantic default guide levels such as overbought/oversold,
      centerline, or zero line

    Important:
    - This remains metadata only.
    - The panel/workspace/render layers remain responsible for translating
      this spec into chart-local pane policy and actual drawing behavior.
    """
    range_mode: OscillatorRangeMode = "auto"
    bounds: tuple[float, float] | None = None
    guide_levels: tuple[OscillatorGuideLevelSpec, ...] = ()


# ---------------------------------------------------------------------------
# Default behavior/output presets
# ---------------------------------------------------------------------------

def _default_behavior_for_kind(kind: ToolKind) -> ToolBehaviorSpec:
    if kind == "oscillator":
        return ToolBehaviorSpec(
            output_mode="oscillator-pane",
            chart_renderable=True,
            supports_style=True,
            supports_pane_layout=True,
            supports_last_value=True,
        )
    if kind == "construct":
        return ToolBehaviorSpec(
            output_mode="non-visual",
            chart_renderable=False,
            supports_style=False,
            supports_pane_layout=False,
            supports_last_value=False,
        )
    return ToolBehaviorSpec(
        output_mode="overlay",
        chart_renderable=True,
        supports_style=True,
        supports_pane_layout=False,
        supports_last_value=True,
    )


def _default_style_capabilities_factory() -> ToolStyleCapabilities:
    return ToolStyleCapabilities()


def _default_edit_capabilities_factory() -> ToolEditCapabilities:
    return ToolEditCapabilities(preferred_module="generic")

@dataclass(frozen=True)
class ToolSpec:
    """
    Unified metadata contract for indicators, oscillators, and constructs.

    This spec is intentionally UI-friendly and persistence-friendly:
    - drives dropdown population
    - drives dynamic config forms
    - defines canonical required market-data inputs
    - defines configurable parameters
    - exposes output metadata for storage/display workflows
    - declares chart/runtime behavior explicitly

    `form_variant` is a UI-only hint used by the FinancialToolsManagerWindow
    to switch between the generic param form and specialized construct forms.

    `style_capabilities` and `edit_capabilities` are capability-only metadata
    used by the future chart UI module architecture. They do NOT define actual
    colors, widths, opacities, widget layouts, or any renderer-specific values.

    Important construct-layer policy
    --------------------------------
    Construct specs in this module must mirror two upstream sources of truth:

    1. runtime truth from `constructs.py`
    2. canonical naming truth from `ft_naming.py`

    This means the spec layer must not preserve stale construct families or old
    emitted-name assumptions once runtime/naming ground truth has moved on.
    """
    key: str
    title: str
    kind: ToolKind
    data_inputs: tuple[DataInputSpec, ...]
    params: tuple[ParamSpec, ...]
    output_names: tuple[str, ...]
    description: str = ""
    behavior: Optional[ToolBehaviorSpec] = None
    output: ToolOutputSpec = field(
        default_factory=lambda: ToolOutputSpec(
            structure="line-series",
            output_names=(),
            signals=(),
            accepts_empty_render_output=False,
        )
    )
    form_variant: str = "default"
    output_name_resolver: Optional[Callable[[Mapping[str, Any]], tuple[str, ...]]] = None
    output_signal_resolver: Optional[Callable[[Mapping[str, Any]], tuple[OutputSignalSpec, ...]]] = None
    style_capabilities: ToolStyleCapabilities = field(default_factory=_default_style_capabilities_factory)
    edit_capabilities: ToolEditCapabilities = field(default_factory=_default_edit_capabilities_factory)
    oscillator_visual: Optional[OscillatorVisualSpec] = None
    construct_io: Optional[ConstructIOSpec] = None

    def __post_init__(self) -> None:
        if self.behavior is None:
            object.__setattr__(self, "behavior", _default_behavior_for_kind(self.kind))
