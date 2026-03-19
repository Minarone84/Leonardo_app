from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Literal


ToolKind = Literal["indicator", "oscillator", "construct"]
ValueType = Literal["int", "float", "bool", "str"]


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
class ToolSpec:
    """
    Unified metadata contract for indicators, oscillators, and constructs.

    This spec is intentionally UI-friendly and persistence-friendly:
    - drives dropdown population
    - drives dynamic config forms
    - defines canonical required market-data inputs
    - defines configurable parameters
    - exposes output column names for storage/display workflows
    """
    key: str
    title: str
    kind: ToolKind
    data_inputs: tuple[DataInputSpec, ...]
    params: tuple[ParamSpec, ...]
    output_names: tuple[str, ...]
    description: str = ""


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
    ),
    "ema": ToolSpec(
        key="ema",
        title="EMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("EMA_{period}",),
        description="Exponential Moving Average.",
    ),
    "tema": ToolSpec(
        key="tema",
        title="TEMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("TEMA_{period}",),
        description="Triple Exponential Moving Average.",
    ),
    "hma": ToolSpec(
        key="hma",
        title="HMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("HMA_{period}",),
        description="Hull Moving Average.",
    ),
    "kama": ToolSpec(
        key="kama",
        title="KAMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(FAST_PERIOD_PARAM, SLOW_PERIOD_PARAM),
        output_names=("KAMA_{fast_period}_{slow_period}",),
        description="Kaufman's Adaptive Moving Average.",
    ),
    "bb": ToolSpec(
        key="bb",
        title="Bollinger Bands",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, STD_PARAM),
        output_names=("bb_middle", "bb_upper_band", "bb_lower_band"),
        description="Bollinger Bands on close.",
    ),
    "hck": ToolSpec(
        key="hck",
        title="Hancock",
        kind="indicator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(FAST_VWAP_PARAM, SLOW_VWAP_PARAM),
        output_names=("fast_vwap", "slow_vwap", "vwap_color"),
        description="Fast/slow EW-VWAP pair with directional color state.",
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
    ),
    "arsi": ToolSpec(
        key="arsi",
        title="ARSI",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, BOOST_BREAKOUTS_PARAM),
        output_names=("arsi_{period}",),
        description="Augmented RSI with optional breakout boosting.",
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
    ),
    "smi": ToolSpec(
        key="smi",
        title="SMI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT),
        params=(K_LENGTH_PARAM, D_LENGTH_PARAM),
        output_names=("SMI", "SMIsignal"),
        description="Stochastic Momentum Index.",
    ),
    "mfi": ToolSpec(
        key="mfi",
        title="MFI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(PERIOD_PARAM,),
        output_names=("mfi",),
        description="Money Flow Index.",
    ),
    "obv": ToolSpec(
        key="obv",
        title="OBV",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT, VOLUME_INPUT),
        params=(),
        output_names=("obv",),
        description="On-Balance Volume.",
    ),
}


# ---------------------------------------------------------------------------
# Construct placeholder specs
# ---------------------------------------------------------------------------

CONSTRUCT_SPECS: Dict[str, ToolSpec] = {
    "placeholder": ToolSpec(
        key="placeholder",
        title="Construct (placeholder)",
        kind="construct",
        data_inputs=(),
        params=(),
        output_names=(),
        description="Placeholder entry until construct tools are implemented.",
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