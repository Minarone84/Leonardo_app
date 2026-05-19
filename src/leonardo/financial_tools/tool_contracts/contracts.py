from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from leonardo.financial_tools.execution_context import ToolExecutionEnvironment

ToolFamily = Literal["indicator", "oscillator", "construct"]
ValueType = Literal["int", "float", "bool", "str"]
OutputMode = Literal["overlay", "oscillator-pane", "non-visual"]
OutputStructure = Literal[
    "line-series",
    "multi-line-series",
    "levels",
    "bands",
    "state",
    "events",
    "analysis-only",
]
SignalType = Literal["signal", "utility"]
SignalValueType = Literal["numeric", "categorical", "boolean"]
ConstructInputBinding = Literal["unary_source", "fast_slow", "fast_mid_slow", "multi_source"]
ConstructSourceFamily = Literal["ohlc", "indicator", "oscillator", "construct"]
ConstructSourceCompatibility = Literal["mixed_numeric", "same_family", "same_oscillator_type"]
ConstructOutputCardinality = Literal["single", "matches_inputs", "one_or_more"]
ConstructOutputRole = Literal["plotted_line", "state_series", "analysis_only"]
OscillatorRangeMode = Literal["auto", "fixed_bounds"]
GuideLevelKind = Literal["overbought", "oversold", "center", "zero"]


@dataclass(frozen=True)
class DataInputContract:
    name: str
    dtype: ValueType
    required: bool = True
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class ParamContract:
    name: str
    dtype: ValueType
    required: bool = True
    default: Any = None
    label: str = ""
    description: str = ""
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class BehaviorContract:
    output_mode: OutputMode
    chart_renderable: bool = True
    supports_style: bool = True
    supports_pane_layout: bool = False
    supports_last_value: bool = True
    supported_environments: tuple[ToolExecutionEnvironment, ...] = ("historical",)
    default_environment: ToolExecutionEnvironment = "historical"


@dataclass(frozen=True)
class OutputSignalContract:
    signal_type: SignalType = "signal"
    renderable: bool = True
    analysis_usable: bool = True
    default_visible: bool = True
    label: str = ""
    description: str = ""
    semantic_role: str = "primary"
    value_type: SignalValueType = "numeric"
    can_drive_style_rules: bool = False


@dataclass(frozen=True)
class OutputContract:
    structure: OutputStructure
    naming_resolver: str
    signals: tuple[OutputSignalContract, ...] = ()
    dynamic_signals: bool = False
    accepts_empty_render_output: bool = False


@dataclass(frozen=True)
class ConstructIOContract:
    input_binding: ConstructInputBinding
    allowed_source_families: tuple[ConstructSourceFamily, ...]
    source_compatibility: ConstructSourceCompatibility = "mixed_numeric"
    output_cardinality: ConstructOutputCardinality = "single"
    output_role: ConstructOutputRole = "plotted_line"


@dataclass(frozen=True)
class OscillatorGuideLevelContract:
    kind: GuideLevelKind
    value: float
    visible: bool = True
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class OscillatorVisualContract:
    range_mode: OscillatorRangeMode = "auto"
    bounds: tuple[float, float] | None = None
    guide_levels: tuple[OscillatorGuideLevelContract, ...] = ()


@dataclass(frozen=True)
class ToolContract:
    family: ToolFamily
    key: str
    title: str
    aliases: tuple[str, ...] = ()
    data_inputs: tuple[DataInputContract, ...] = ()
    params: tuple[ParamContract, ...] = ()
    behavior: BehaviorContract | None = None
    output: OutputContract | None = None
    construct_io: ConstructIOContract | None = None
    oscillator_visual: OscillatorVisualContract | None = None
    description: str = ""
    form_variant: str = "default"
    contract_version: str = "1.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def default_params(self) -> dict[str, Any]:
        return {param.name: param.default for param in self.params}
