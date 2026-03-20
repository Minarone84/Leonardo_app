from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Literal, Optional


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
    accepts_empty_render_output: bool = False


# ---------------------------------------------------------------------------
# Default behavior/output presets
# ---------------------------------------------------------------------------

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


def _default_behavior_for_kind(kind: ToolKind) -> ToolBehaviorSpec:
    if kind == "oscillator":
        return DEFAULT_OSCILLATOR_BEHAVIOR
    if kind == "construct":
        return DEFAULT_NON_VISUAL_CONSTRUCT_BEHAVIOR
    return DEFAULT_INDICATOR_BEHAVIOR


DEFAULT_LINE_OUTPUT = lambda names: ToolOutputSpec(
    structure="line-series",
    output_names=tuple(names),
    accepts_empty_render_output=False,
)

DEFAULT_MULTI_LINE_OUTPUT = lambda names: ToolOutputSpec(
    structure="multi-line-series",
    output_names=tuple(names),
    accepts_empty_render_output=False,
)

DEFAULT_ANALYSIS_ONLY_OUTPUT = ToolOutputSpec(
    structure="analysis-only",
    output_names=(),
    accepts_empty_render_output=True,
)


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
            accepts_empty_render_output=False,
        )
    )

    def __post_init__(self) -> None:
        if self.behavior is None:
            object.__setattr__(self, "behavior", _default_behavior_for_kind(self.kind))


# ---------------------------------------------------------------------------
# Canonical market-data inputs
# ---------------------------------------------------------------------------

OPEN_INPUT = DataInputSpec(
    name="open",
    dtype="float",
    label="Open",
    description="Open price series.",
)

HIGH_INPUT = DataInputSpec(
    name="high",
    dtype="float",
    label="High",
    description="High price series.",
)

LOW_INPUT = DataInputSpec(
    name="low",
    dtype="float",
    label="Low",
    description="Low price series.",
)

CLOSE_INPUT = DataInputSpec(
    name="close",
    dtype="float",
    label="Close",
    description="Close price series.",
)

VOLUME_INPUT = DataInputSpec(
    name="volume",
    dtype="float",
    label="Volume",
    description="Volume series. Compute layer may resolve 'Volume' or 'volume'.",
)


# ---------------------------------------------------------------------------
# Reusable parameter specs
# ---------------------------------------------------------------------------

PERIOD_PARAM = ParamSpec(
    name="period",
    dtype="int",
    required=True,
    default=14,
    label="Period",
    description="Primary lookback period.",
    minimum=1,
)

WINDOW_PARAM = ParamSpec(
    name="window",
    dtype="int",
    required=True,
    default=10,
    label="Window",
    description="Rolling window length.",
    minimum=1,
)

STD_PARAM = ParamSpec(
    name="std",
    dtype="float",
    required=True,
    default=2.0,
    label="Std Dev Multiplier",
    description="Standard deviation multiplier.",
    minimum=0.000001,
)

FAST_PERIOD_PARAM = ParamSpec(
    name="fast_period",
    dtype="int",
    required=True,
    default=2,
    label="Fast Period",
    description="Fast smoothing/adaptation period.",
    minimum=1,
)

SLOW_PERIOD_PARAM = ParamSpec(
    name="slow_period",
    dtype="int",
    required=True,
    default=30,
    label="Slow Period",
    description="Slow smoothing/adaptation period.",
    minimum=1,
)

FAST_VWAP_PARAM = ParamSpec(
    name="fast_vwap_l",
    dtype="int",
    required=True,
    default=13,
    label="Fast VWAP Length",
    description="Fast EW-VWAP length.",
    minimum=1,
)

SLOW_VWAP_PARAM = ParamSpec(
    name="slow_vwap_l",
    dtype="int",
    required=True,
    default=48,
    label="Slow VWAP Length",
    description="Slow EW-VWAP length.",
    minimum=1,
)

BOOST_BREAKOUTS_PARAM = ParamSpec(
    name="boost_breakouts",
    dtype="bool",
    required=False,
    default=True,
    label="Boost Breakouts",
    description="Boost fresh Donchian highs/lows in ARSI.",
)

BAND_LENGTH_PARAM = ParamSpec(
    name="band_length",
    dtype="int",
    required=True,
    default=34,
    label="Band Length",
    description="Lookback used for RSI bands.",
    minimum=1,
)

BAND_MULT_PARAM = ParamSpec(
    name="band_mult",
    dtype="float",
    required=False,
    default=1.6185,
    label="Band Multiplier",
    description="Band standard deviation multiplier.",
    minimum=0.000001,
)

FAST_LEN_PARAM = ParamSpec(
    name="fast_len",
    dtype="int",
    required=False,
    default=2,
    label="Fast Length",
    description="Fast smoothing length.",
    minimum=1,
)

SLOW_LEN_PARAM = ParamSpec(
    name="slow_len",
    dtype="int",
    required=False,
    default=7,
    label="Slow Length",
    description="Slow smoothing length.",
    minimum=1,
)

FAST_SMO_PARAM = ParamSpec(
    name="fast_smo",
    dtype="str",
    required=False,
    default="EMA",
    label="Fast Smoother",
    description="Fast smoothing mode.",
    choices=("EMA", "RMA", "SMA"),
)

SLOW_SMO_PARAM = ParamSpec(
    name="slow_smo",
    dtype="str",
    required=False,
    default="RMA",
    label="Slow Smoother",
    description="Slow smoothing mode.",
    choices=("EMA", "RMA", "SMA"),
)

K_LENGTH_PARAM = ParamSpec(
    name="k_length",
    dtype="int",
    required=True,
    default=14,
    label="K Length",
    description="Lookback for stochastic window.",
    minimum=1,
)

D_LENGTH_PARAM = ParamSpec(
    name="d_length",
    dtype="int",
    required=True,
    default=3,
    label="D Length",
    description="Smoothing length.",
    minimum=1,
)


# ---------------------------------------------------------------------------
# Indicator specs
# ---------------------------------------------------------------------------

INDICATOR_SPECS: Dict[str, ToolSpec] = {
    "sma": ToolSpec(
        key="sma",
        title="SMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("SMA_{period}",),
        description="Simple Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("SMA_{period}",)),
    ),
    "ema": ToolSpec(
        key="ema",
        title="EMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("EMA_{period}",),
        description="Exponential Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("EMA_{period}",)),
    ),
    "tema": ToolSpec(
        key="tema",
        title="TEMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("TEMA_{period}",),
        description="Triple Exponential Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("TEMA_{period}",)),
    ),
    "hma": ToolSpec(
        key="hma",
        title="HMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("HMA_{period}",),
        description="Hull Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("HMA_{period}",)),
    ),
    "kama": ToolSpec(
        key="kama",
        title="KAMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(FAST_PERIOD_PARAM, SLOW_PERIOD_PARAM),
        output_names=("KAMA_{fast_period}_{slow_period}",),
        description="Kaufman's Adaptive Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("KAMA_{fast_period}_{slow_period}",)),
    ),
    "bb": ToolSpec(
        key="bb",
        title="Bollinger Bands",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, STD_PARAM),
        output_names=("bb_middle", "bb_upper_band", "bb_lower_band"),
        description="Bollinger Bands on close.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("bb_middle", "bb_upper_band", "bb_lower_band")),
    ),
    "hck": ToolSpec(
        key="hck",
        title="Hancock",
        kind="indicator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(FAST_VWAP_PARAM, SLOW_VWAP_PARAM),
        output_names=("fast_vwap", "slow_vwap", "vwap_color"),
        description="Fast/slow EW-VWAP pair with directional color state.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("fast_vwap", "slow_vwap", "vwap_color")),
    ),
}


# ---------------------------------------------------------------------------
# Oscillator specs
# ---------------------------------------------------------------------------

OSCILLATOR_SPECS: Dict[str, ToolSpec] = {
    "rsi": ToolSpec(
        key="rsi",
        title="RSI",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("rsi_{period}",),
        description="Wilder RSI.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("rsi_{period}",)),
    ),
    "arsi": ToolSpec(
        key="arsi",
        title="ARSI",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, BOOST_BREAKOUTS_PARAM),
        output_names=("arsi_{period}",),
        description="Augmented RSI with optional breakout boosting.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("arsi_{period}",)),
    ),
    "tdirsi": ToolSpec(
        key="tdirsi",
        title="TDI RSI",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT,),
        params=(
            PERIOD_PARAM,
            BAND_LENGTH_PARAM,
            BAND_MULT_PARAM,
            FAST_LEN_PARAM,
            SLOW_LEN_PARAM,
            FAST_SMO_PARAM,
            SLOW_SMO_PARAM,
        ),
        output_names=("fast_ma", "slow_ma", "up", "dn", "mid"),
        description="Traders Dynamic Index based on RSI.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("fast_ma", "slow_ma", "up", "dn", "mid")),
    ),
    "smi": ToolSpec(
        key="smi",
        title="SMI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT),
        params=(K_LENGTH_PARAM, D_LENGTH_PARAM),
        output_names=("SMI", "SMIsignal"),
        description="Stochastic Momentum Index.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("SMI", "SMIsignal")),
    ),
    "mfi": ToolSpec(
        key="mfi",
        title="MFI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(PERIOD_PARAM,),
        output_names=("mfi",),
        description="Money Flow Index.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("mfi",)),
    ),
    "obv": ToolSpec(
        key="obv",
        title="OBV",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT, VOLUME_INPUT),
        params=(),
        output_names=("obv",),
        description="On-Balance Volume.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("obv",)),
    ),
}


# ---------------------------------------------------------------------------
# Construct specs
# ---------------------------------------------------------------------------

CONSTRUCT_SPECS: Dict[str, ToolSpec] = {
    "dummy_overlay": ToolSpec(
        key="dummy_overlay",
        title="Dummy Overlay Construct",
        kind="construct",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("dummy_overlay",),
        description="Dummy construct that renders an EMA-like line on the price pane.",
        behavior=ToolBehaviorSpec(
            output_mode="overlay",
            chart_renderable=True,
            supports_style=True,
            supports_pane_layout=False,
            supports_last_value=True,
        ),
        output=DEFAULT_LINE_OUTPUT(("dummy_overlay",)),
    ),
    "dummy_oscillator": ToolSpec(
        key="dummy_oscillator",
        title="Dummy Oscillator Construct",
        kind="construct",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("dummy_oscillator",),
        description="Dummy construct that renders an RSI-like line in its own lower pane.",
        behavior=ToolBehaviorSpec(
            output_mode="oscillator-pane",
            chart_renderable=True,
            supports_style=True,
            supports_pane_layout=True,
            supports_last_value=True,
        ),
        output=DEFAULT_LINE_OUTPUT(("dummy_oscillator",)),
    ),
    "dummy_non_visual": ToolSpec(
        key="dummy_non_visual",
        title="Dummy Non-Visual Construct",
        kind="construct",
        data_inputs=(CLOSE_INPUT,),
        params=(WINDOW_PARAM,),
        output_names=(),
        description="Dummy construct that computes analysis-only metadata and does not render on the chart.",
        behavior=DEFAULT_NON_VISUAL_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_ANALYSIS_ONLY_OUTPUT,
    ),
}


# ---------------------------------------------------------------------------
# Unified helpers
# ---------------------------------------------------------------------------

ALL_TOOL_SPECS: Dict[str, ToolSpec] = {
    **INDICATOR_SPECS,
    **OSCILLATOR_SPECS,
    **CONSTRUCT_SPECS,
}


def get_indicator_specs() -> Dict[str, ToolSpec]:
    return dict(INDICATOR_SPECS)


def get_oscillator_specs() -> Dict[str, ToolSpec]:
    return dict(OSCILLATOR_SPECS)


def get_construct_specs() -> Dict[str, ToolSpec]:
    return dict(CONSTRUCT_SPECS)


def get_tool_spec(key: str) -> ToolSpec:
    k = str(key).strip().lower()
    if k not in ALL_TOOL_SPECS:
        raise KeyError(f"Unknown tool spec: {key}")
    return ALL_TOOL_SPECS[k]


def tool_titles_by_kind(kind: ToolKind) -> Dict[str, str]:
    return {
        key: spec.title
        for key, spec in ALL_TOOL_SPECS.items()
        if spec.kind == kind
    }


def build_default_params(spec: ToolSpec) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    for param in spec.params:
        defaults[param.name] = param.default
    return defaults


def format_output_names(spec: ToolSpec, params: Mapping[str, Any]) -> tuple[str, ...]:
    """
    Render output names using the provided params.

    Example:
        spec.output_names = ("SMA_{period}",)
        params = {"period": 20}
        -> ("SMA_20",)
    """
    rendered: list[str] = []
    format_values = dict(params)
    for name in spec.output_names:
        rendered.append(str(name).format(**format_values))
    return tuple(rendered)