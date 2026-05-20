from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .models import *
from .inputs import *
from .params import *
from .behavior import *
from .capabilities import *
from .resolvers import *
from .resolvers import (
    _resolve_sma_output_names,
    _resolve_ema_output_names,
    _resolve_tema_output_names,
    _resolve_hma_output_names,
    _resolve_kama_output_names,
    _resolve_bb_output_names,
    _resolve_hck_output_names,
    _resolve_strategy_output_names,
    _resolve_peaks_troughs_output_names,
    _resolve_universal_trend_classifier_output_names,
    _resolve_sma_output_signals,
    _resolve_ema_output_signals,
    _resolve_tema_output_signals,
    _resolve_hma_output_signals,
    _resolve_kama_output_signals,
    _resolve_bb_output_signals,
    _resolve_hck_output_signals,
    _resolve_strategy_output_signals,
    _resolve_peaks_troughs_output_signals,
    _resolve_universal_trend_classifier_output_signals,
    _resolve_rsi_output_names,
    _resolve_arsi_output_names,
    _resolve_tdirsi_output_names,
    _resolve_smi_output_names,
    _resolve_mfi_output_names,
    _resolve_obv_output_names,
    _resolve_volume_output_names,
    _resolve_rsi_output_signals,
    _resolve_arsi_output_signals,
    _resolve_tdirsi_output_signals,
    _resolve_smi_output_signals,
    _resolve_mfi_output_signals,
    _resolve_obv_output_signals,
    _resolve_volume_output_signals,
    _resolve_derivative_output_names,
    _resolve_angle_output_names,
    _resolve_braids_output_names,
    _resolve_braid_instability_output_names,
    _resolve_delta_output_names,
    _resolve_trap_area_output_names,
    _resolve_percent_span_angle_output_names,
    _resolve_angle_momentum_output_names,
    _resolve_derivative_output_signals,
    _resolve_angle_output_signals,
    _resolve_braids_output_signals,
    _resolve_braid_instability_output_signals,
    _resolve_delta_output_signals,
    _resolve_trap_area_output_signals,
    _resolve_percent_span_angle_output_signals,
    _resolve_angle_momentum_output_signals,
)

INDICATOR_SPECS: Dict[str, ToolSpec] = {
    "sma": ToolSpec(
        key="sma",
        title="SMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("sma_{period}",),
        description="Simple Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("sma_{period}",)),
        output_name_resolver=_resolve_sma_output_names,
        output_signal_resolver=_resolve_sma_output_signals,
        style_capabilities=SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=SINGLE_PERIOD_EDIT_CAPABILITIES,
    ),
    "ema": ToolSpec(
        key="ema",
        title="EMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("ema_{period}",),
        description="Exponential Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("ema_{period}",)),
        output_name_resolver=_resolve_ema_output_names,
        output_signal_resolver=_resolve_ema_output_signals,
        style_capabilities=SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=SINGLE_PERIOD_EDIT_CAPABILITIES,
    ),
    "tema": ToolSpec(
        key="tema",
        title="TEMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("tema_{period}",),
        description="Triple Exponential Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("tema_{period}",)),
        output_name_resolver=_resolve_tema_output_names,
        output_signal_resolver=_resolve_tema_output_signals,
        style_capabilities=SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=SINGLE_PERIOD_EDIT_CAPABILITIES,
    ),
    "hma": ToolSpec(
        key="hma",
        title="HMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM,),
        output_names=("hma_{period}",),
        description="Hull Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("hma_{period}",)),
        output_name_resolver=_resolve_hma_output_names,
        output_signal_resolver=_resolve_hma_output_signals,
        style_capabilities=SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=SINGLE_PERIOD_EDIT_CAPABILITIES,
    ),
    "kama": ToolSpec(
        key="kama",
        title="KAMA",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(FAST_PERIOD_PARAM, SLOW_PERIOD_PARAM),
        output_names=("kama_{fast_period}_{slow_period}",),
        description="Kaufman's Adaptive Moving Average.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("kama_{fast_period}_{slow_period}",)),
        output_name_resolver=_resolve_kama_output_names,
        output_signal_resolver=_resolve_kama_output_signals,
        style_capabilities=SINGLE_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=DUAL_PERIOD_EDIT_CAPABILITIES,
    ),
    "bb": ToolSpec(
        key="bb",
        title="Bollinger Bands",
        kind="indicator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, STD_PARAM),
        output_names=build_bb_signal_names(),
        description="Bollinger Bands on close.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(build_bb_signal_names()),
        output_name_resolver=_resolve_bb_output_names,
        output_signal_resolver=_resolve_bb_output_signals,
        style_capabilities=MULTI_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=PERIOD_PLUS_FLOAT_EDIT_CAPABILITIES,
    ),
    "hck": ToolSpec(
        key="hck",
        title="Hancock",
        kind="indicator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(FAST_VWAP_PARAM, SLOW_VWAP_PARAM),
        output_names=build_hck_signal_names(),
        description="Fast/slow EW-VWAP pair with directional color state.",
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(build_hck_signal_names()),
        output_name_resolver=_resolve_hck_output_names,
        output_signal_resolver=_resolve_hck_output_signals,
        style_capabilities=UTILITY_DRIVEN_MULTI_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=DUAL_LENGTH_EDIT_CAPABILITIES,
    ),
    "strategy": ToolSpec(
        key="strategy",
        title="Strategy",
        kind="indicator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(
            STRATEGY_EMA_1_PERIOD_PARAM,
            STRATEGY_EMA_2_PERIOD_PARAM,
            STRATEGY_EMA_3_PERIOD_PARAM,
            STRATEGY_EMA_4_PERIOD_PARAM,
            STRATEGY_EMA_5_PERIOD_PARAM,
            STRATEGY_EMA_6_PERIOD_PARAM,
            STRATEGY_SMA_1_PERIOD_PARAM,
            STRATEGY_SMA_2_PERIOD_PARAM,
            STRATEGY_SMA_3_PERIOD_PARAM,
            STRATEGY_SMA_4_PERIOD_PARAM,
            STRATEGY_SMA_5_PERIOD_PARAM,
            STRATEGY_SMA_6_PERIOD_PARAM,
            STRATEGY_BB_PERIOD_PARAM,
            STRATEGY_BB_STD_PARAM,
            STRATEGY_HCK_FAST_VWAP_PARAM,
            STRATEGY_HCK_SLOW_VWAP_PARAM,
        ),
        output_names=build_strategy_signal_names(),
        description=(
            "Composite price-overlay indicator bundling six EMAs, six SMAs, Bollinger Bands, "
            "and a Hancock pair."
        ),
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(build_strategy_signal_names()),
        output_name_resolver=_resolve_strategy_output_names,
        output_signal_resolver=_resolve_strategy_output_signals,
        style_capabilities=UTILITY_DRIVEN_MULTI_LINE_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=DEFAULT_GENERIC_EDIT_CAPABILITIES,
    ),
    "peaks_troughs": ToolSpec(
        key="peaks_troughs",
        title="Peaks & Troughs",
        kind="indicator",
        data_inputs=(HIGH_INPUT, LOW_INPUT),
        params=(),
        output_names=build_peaks_troughs_signal_names(),
        description=(
            "Confirmed fractal peak/trough detector across the fixed 3, 5, 7, 9, and 11-bar windows."
        ),
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=ToolOutputSpec(
            structure="events",
            output_names=build_peaks_troughs_signal_names(),
            signals=(),
            accepts_empty_render_output=False,
        ),
        output_name_resolver=_resolve_peaks_troughs_output_names,
        output_signal_resolver=_resolve_peaks_troughs_output_signals,
        style_capabilities=MULTI_SIGNAL_EVENT_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=DEFAULT_GENERIC_EDIT_CAPABILITIES,
    ),
    "universal_trend_classifier": ToolSpec(
        key="universal_trend_classifier",
        title="Universal Trend Classifier",
        kind="indicator",
        data_inputs=(OPEN_INPUT, HIGH_INPUT, LOW_INPUT, CLOSE_INPUT),
        params=UTC_PARAMS,
        output_names=build_universal_trend_classifier_signal_names(),
        description=(
            "Price-pane market-structure classifier emitting range bands, sparse "
            "start/end markers, and non-renderable boolean state outputs."
        ),
        behavior=DEFAULT_INDICATOR_BEHAVIOR,
        output=ToolOutputSpec(
            structure="multi-line-series",
            output_names=build_universal_trend_classifier_signal_names(),
            signals=_resolve_universal_trend_classifier_output_signals({}),
            accepts_empty_render_output=False,
        ),
        output_name_resolver=_resolve_universal_trend_classifier_output_names,
        output_signal_resolver=_resolve_universal_trend_classifier_output_signals,
        style_capabilities=MULTI_SIGNAL_EVENT_INDICATOR_STYLE_CAPABILITIES,
        edit_capabilities=DEFAULT_GENERIC_EDIT_CAPABILITIES,
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
        output_name_resolver=_resolve_rsi_output_names,
        output_signal_resolver=_resolve_rsi_output_signals,
        oscillator_visual=DEFAULT_BOUNDED_OSCILLATOR_VISUAL_SPEC,
    ),
    "arsi": ToolSpec(
        key="arsi",
        title="ARSI",
        kind="oscillator",
        data_inputs=(CLOSE_INPUT,),
        params=(PERIOD_PARAM, ARSI_METHOD_PARAM, ARSI_SIGNAL_PERIOD_PARAM, ARSI_SIGNAL_METHOD_PARAM),
        output_names=("arsi_{period}_{method}", "arsi_signal_{period}_{method}_{signal_period}_{signal_method}"),
        description="Ultimate RSI-style ARSI with configurable main and signal smoothing.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(
            ("arsi_{period}_{method}", "arsi_signal_{period}_{method}_{signal_period}_{signal_method}")
        ),
        output_name_resolver=_resolve_arsi_output_names,
        output_signal_resolver=_resolve_arsi_output_signals,
        oscillator_visual=ARSI_BOUNDED_OSCILLATOR_VISUAL_SPEC,
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
        output_names=(
            "tdirsi_fast_ma_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
            "tdirsi_slow_ma_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
            "tdirsi_up_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
            "tdirsi_dn_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
            "tdirsi_mid_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
        ),
        description="Traders Dynamic Index based on RSI.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(
            (
                "tdirsi_fast_ma_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
                "tdirsi_slow_ma_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
                "tdirsi_up_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
                "tdirsi_dn_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
                "tdirsi_mid_{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo}_{slow_smo}",
            )
        ),
        output_name_resolver=_resolve_tdirsi_output_names,
        output_signal_resolver=_resolve_tdirsi_output_signals,
        oscillator_visual=DEFAULT_BOUNDED_OSCILLATOR_VISUAL_SPEC,
    ),
    "smi": ToolSpec(
        key="smi",
        title="SMI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT),
        params=(K_LENGTH_PARAM, D_LENGTH_PARAM),
        output_names=("smi_{k_length}_{d_length}", "smi_signal_{k_length}_{d_length}"),
        description="Stochastic Momentum Index.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("smi_{k_length}_{d_length}", "smi_signal_{k_length}_{d_length}")),
        output_name_resolver=_resolve_smi_output_names,
        output_signal_resolver=_resolve_smi_output_signals,
        oscillator_visual=DEFAULT_ZERO_CENTERED_OSCILLATOR_VISUAL_SPEC,
    ),
    "mfi": ToolSpec(
        key="mfi",
        title="MFI",
        kind="oscillator",
        data_inputs=(HIGH_INPUT, LOW_INPUT, CLOSE_INPUT, VOLUME_INPUT),
        params=(PERIOD_PARAM,),
        output_names=("mfi_{period}",),
        description="Money Flow Index.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(("mfi_{period}",)),
        output_name_resolver=_resolve_mfi_output_names,
        output_signal_resolver=_resolve_mfi_output_signals,
        oscillator_visual=DEFAULT_BOUNDED_OSCILLATOR_VISUAL_SPEC,
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
        output_name_resolver=_resolve_obv_output_names,
        output_signal_resolver=_resolve_obv_output_signals,
        oscillator_visual=DEFAULT_UNBOUNDED_OSCILLATOR_VISUAL_SPEC,
    ),
    "volume": ToolSpec(
        key="volume",
        title="Volume",
        kind="oscillator",
        data_inputs=(VOLUME_INPUT,),
        params=(VOLUME_MEAN_PERIOD_PARAM,),
        output_names=("volume", "volume_mean_{period}"),
        description="Raw traded volume with configurable rolling mean.",
        behavior=DEFAULT_OSCILLATOR_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(("volume", "volume_mean_{period}")),
        output_name_resolver=_resolve_volume_output_names,
        output_signal_resolver=_resolve_volume_output_signals,
        oscillator_visual=DEFAULT_UNBOUNDED_OSCILLATOR_VISUAL_SPEC,
    ),
}


CONSTRUCT_SPECS: Dict[str, ToolSpec] = {
    "dynamic_binning": ToolSpec(
        key="dynamic_binning",
        title="Dynamic Binning",
        kind="construct",
        data_inputs=(),
        params=(
            SOURCE_COLUMNS_PARAM,
            WINDOW_PARAM,
            MULTIPLIER_PARAM,
            FLOOR_QUANTILE_PARAM,
            GLOBAL_MIN_STEP_PARAM,
            QUANTILE_METHOD_PARAM,
            N_BINS_PARAM,
            BOUNDARY_EPS_PARAM,
        ),
        output_names=(),
        description="Non-visual construct that estimates per-series movement floors and fits deterministic signed bins.",
        behavior=DEFAULT_NON_VISUAL_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_ANALYSIS_ONLY_OUTPUT,
    ),
    "derivative": ToolSpec(
        key="derivative",
        title="Derivatives",
        kind="construct",
        data_inputs=(),
        params=(DERIVATIVE_ORDER_PARAM,),
        output_names=(),
        description="Unary construct computing first or second derivative.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(()),
        form_variant="construct_unary_source",
        output_name_resolver=_resolve_derivative_output_names,
        output_signal_resolver=_resolve_derivative_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="unary_source",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="single",
            output_role="plotted_line",
        ),
    ),
    "angle": ToolSpec(
        key="angle",
        title="Angles",
        kind="construct",
        data_inputs=(),
        params=(ANGLE_UNIT_PARAM,),
        output_names=(),
        description="Unary construct computing the canonical angle of the selected source.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(()),
        form_variant="construct_unary_source",
        output_name_resolver=_resolve_angle_output_names,
        output_signal_resolver=_resolve_angle_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="unary_source",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="single",
            output_role="plotted_line",
        ),
    ),
    "braids": ToolSpec(
        key="braids",
        title="Braids",
        kind="construct",
        data_inputs=(),
        params=(FAST_SOURCE_PARAM, MID_SOURCE_PARAM, SLOW_SOURCE_PARAM, TIE_POLICY_PARAM),
        output_names=(),
        description="Braid structural construct emitting ambient state, width, and compression for fast, mid, and slow sources.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(()),
        form_variant="construct_fms",
        output_name_resolver=_resolve_braids_output_names,
        output_signal_resolver=_resolve_braids_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="fast_mid_slow",
            allowed_source_families=("indicator", "oscillator", "construct"),
            source_compatibility="same_family",
            output_cardinality="one_or_more",
            output_role="state_series",
        ),
    ),
    "braid_instability": ToolSpec(
        key="braid_instability",
        title="Braid Instability",
        kind="construct",
        data_inputs=(),
        params=(FAST_SOURCE_PARAM, MID_SOURCE_PARAM, SLOW_SOURCE_PARAM, BRAID_INSTABILITY_N_PARAM),
        output_names=(),
        description="Temporal braid-stability construct measuring rolling raw braid-state churn.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_LINE_OUTPUT(()),
        form_variant="construct_fms",
        output_name_resolver=_resolve_braid_instability_output_names,
        output_signal_resolver=_resolve_braid_instability_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="fast_mid_slow",
            allowed_source_families=("indicator", "oscillator", "construct"),
            source_compatibility="same_family",
            output_cardinality="single",
            output_role="plotted_line",
        ),
    ),
    "delta": ToolSpec(
        key="delta",
        title="Delta",
        kind="construct",
        data_inputs=(),
        params=(FAST_SOURCE_PARAM, SLOW_SOURCE_PARAM, DELTA_MODE_PARAM, DELTA_EPS_PARAM),
        output_names=(),
        description="Directional relational construct computing fast-minus-slow in raw or percent-relative mode.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(()),
        form_variant="construct_fs",
        output_name_resolver=_resolve_delta_output_names,
        output_signal_resolver=_resolve_delta_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="fast_slow",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="one_or_more",
            output_role="plotted_line",
        ),
    ),
    "trap_area": ToolSpec(
        key="trap_area",
        title="Trap Area",
        kind="construct",
        data_inputs=(),
        params=(FAST_SOURCE_PARAM, MID_SOURCE_PARAM, SLOW_SOURCE_PARAM, ZERO_EPS_PARAM),
        output_names=(),
        description="Cumulative trapezoidal area between ordered faster/slower signal pairs.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(()),
        form_variant="construct_fms",
        output_name_resolver=_resolve_trap_area_output_names,
        output_signal_resolver=_resolve_trap_area_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="fast_mid_slow",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="one_or_more",
            output_role="plotted_line",
        ),
    ),
    "percent_span_angle": ToolSpec(
        key="percent_span_angle",
        title="Percent Span Angle",
        kind="construct",
        data_inputs=(),
        params=(SOURCE_COLUMNS_PARAM, WINDOW_PARAM, PERCENT_SPAN_ANGLE_UNIT_PARAM),
        output_names=(),
        description="Windowed percent-span angle on selected source columns.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(()),
        form_variant="construct_multi_source",
        output_name_resolver=_resolve_percent_span_angle_output_names,
        output_signal_resolver=_resolve_percent_span_angle_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="multi_source",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="matches_inputs",
            output_role="plotted_line",
        ),
    ),
    "angle_momentum": ToolSpec(
        key="angle_momentum",
        title="Angle Momentum",
        kind="construct",
        data_inputs=(),
        params=(SOURCE_COLUMNS_PARAM, ANGLE_MTM_N_PARAM),
        output_names=(),
        description="Signed average angle change per bar on selected angle-like source columns.",
        behavior=DEFAULT_OSCILLATOR_CONSTRUCT_BEHAVIOR,
        output=DEFAULT_MULTI_LINE_OUTPUT(()),
        form_variant="construct_multi_source",
        output_name_resolver=_resolve_angle_momentum_output_names,
        output_signal_resolver=_resolve_angle_momentum_output_signals,
        construct_io=ConstructIOSpec(
            input_binding="multi_source",
            allowed_source_families=("ohlc", "indicator", "oscillator", "construct"),
            source_compatibility="mixed_numeric",
            output_cardinality="matches_inputs",
            output_role="plotted_line",
        ),
    ),
}

CONSTRUCT_SPEC_ALIASES: Dict[str, str] = {
    "dynamic_binning_analysis": "dynamic_binning",
    "derivative_analysis": "derivative",
    "angle_analysis": "angle",
    "percent_angle": "percent_span_angle",
    "percent_angle_analysis": "percent_span_angle",
    "percent_span_angle_analysis": "percent_span_angle",
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


def get_oscillator_visual_spec(key: str) -> Optional[OscillatorVisualSpec]:
    spec = get_tool_spec(key)
    if spec.kind != "oscillator":
        return None
    return spec.oscillator_visual


def get_construct_specs() -> Dict[str, ToolSpec]:
    return dict(CONSTRUCT_SPECS)


def get_tool_spec(key: str) -> ToolSpec:
    k = str(key).strip().lower()
    k = CONSTRUCT_SPEC_ALIASES.get(k, k)
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

    Resolution priority:
    1. canonical resolver from ft_naming.py
    2. legacy template formatting fallback
    """
    if spec.output_name_resolver is not None:
        return tuple(spec.output_name_resolver(dict(params)))

    rendered: list[str] = []
    format_values = dict(params)
    for name in spec.output_names:
        rendered.append(str(name).format(**format_values))
    return tuple(rendered)


def format_output_signals(spec: ToolSpec, params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    """
    Render output signal metadata using the provided params.

    Resolution priority:
    1. canonical resolver from ft_naming.py
    2. legacy template formatting fallback
    """
    if spec.output_signal_resolver is not None:
        return tuple(spec.output_signal_resolver(dict(params)))

    rendered: list[OutputSignalSpec] = []
    format_values = dict(params)

    for signal in spec.output.signals:
        rendered.append(
            OutputSignalSpec(
                name=str(signal.name).format(**format_values),
                signal_type=signal.signal_type,
                renderable=signal.renderable,
                analysis_usable=signal.analysis_usable,
                default_visible=signal.default_visible,
                label=signal.label,
                description=signal.description,
                semantic_role=signal.semantic_role,
                value_type=signal.value_type,
                can_drive_style_rules=signal.can_drive_style_rules,
            )
        )

    return tuple(rendered)
