from __future__ import annotations

from leonardo.financial_tools.tool_contracts.contracts import (
    BehaviorContract,
    DataInputContract,
    OutputContract,
    OutputSignalContract,
    ParamContract,
    ToolContract,
)

OPEN = DataInputContract("open", "float", label="Open")
CLOSE = DataInputContract("close", "float", label="Close")
HIGH = DataInputContract("high", "float", label="High")
LOW = DataInputContract("low", "float", label="Low")
VOLUME = DataInputContract("volume", "float", label="Volume")

PERIOD = ParamContract("period", "int", default=14, minimum=1, label="Period")
STD = ParamContract("std", "float", default=2.0, minimum=0.000001, label="Std Dev Multiplier")
FAST_PERIOD = ParamContract("fast_period", "int", default=2, minimum=1, label="Fast Period")
SLOW_PERIOD = ParamContract("slow_period", "int", default=30, minimum=1, label="Slow Period")
FAST_VWAP = ParamContract("fast_vwap_l", "int", default=13, minimum=1, label="Fast VWAP Length")
SLOW_VWAP = ParamContract("slow_vwap_l", "int", default=48, minimum=1, label="Slow VWAP Length")

UTC_PARAMS = (
    ParamContract(
        "source",
        "str",
        default="close",
        label="Source",
        choices=("open", "high", "low", "close"),
    ),
    ParamContract(
        "fractal_window",
        "int",
        default=5,
        minimum=3,
        choices=(3, 5, 7, 9, 11),
        label="Fractal Window",
        description="Compatibility alias for trend_fractal_window.",
    ),
    ParamContract(
        "trend_fractal_window",
        "int",
        default=5,
        minimum=3,
        choices=(3, 5, 7, 9, 11),
        label="Up/Down Trend Fractal",
        description="Peaks & Troughs fractal length consumed by UTC directional trend detection.",
    ),
    ParamContract(
        "peak_column",
        "str",
        required=False,
        default=None,
        label="Peak Column",
        description="Legacy trend peak column override; defaults from trend_fractal_window.",
    ),
    ParamContract(
        "trough_column",
        "str",
        required=False,
        default=None,
        label="Trough Column",
        description="Legacy trend trough column override; defaults from trend_fractal_window.",
    ),
    ParamContract("min_hr_band_perc", "float", default=0.005, minimum=0.0, label="Min HR Band %"),
    ParamContract("hr_trend_length", "int", default=20, minimum=3, label="HR Trend Length"),
    ParamContract("hr_trend_atr_mult", "float", default=1.0, minimum=0.0, label="HR ATR Mult"),
    ParamContract("hr_trend_atr_len", "int", default=500, minimum=1, label="HR ATR Length"),
    ParamContract(
        "hr_trend_tol_mult",
        "float",
        default=0.3,
        minimum=0.0,
        label="HR Trend Tolerance Mult",
        description="Reserved for incremental/realtime trend-extension tolerance; historical directional trend detection remains strict.",
    ),
    ParamContract("hr_trend_max_gap", "int", default=20, minimum=1, label="HR Trend Max Gap", description="Maximum allowed gap between qualifying swings for horizontal-range continuity."),
    ParamContract(
        "hr_min_inside_ratio",
        "float",
        default=0.8,
        minimum=0.000001,
        maximum=1.0,
        label="HR Min Inside Ratio",
    ),
    ParamContract("min_range_swings", "int", default=4, minimum=4, label="Min Range Swings"),
    ParamContract(
        "range_fractal_window",
        "int",
        default=3,
        minimum=3,
        choices=(3, 5, 7, 9, 11),
        label="Range Trend Fractal",
        description="Peaks & Troughs fractal length consumed by UTC horizontal range discovery.",
    ),
    ParamContract(
        "hr_break_mode",
        "str",
        default="close",
        choices=("close", "wick", "hybrid"),
        label="Range Break Mode",
        description="Horizontal-range invalidation mode after a range is active.",
    ),
)


def _utc_state(role: str, label: str, description: str = "") -> OutputSignalContract:
    return OutputSignalContract(
        signal_type="utility",
        renderable=False,
        analysis_usable=True,
        default_visible=False,
        label=label,
        description=description,
        semantic_role=role,
        value_type="boolean",
        can_drive_style_rules=True,
    )


def _utc_line(role: str, label: str, description: str = "") -> OutputSignalContract:
    return OutputSignalContract(
        signal_type="signal",
        renderable=True,
        analysis_usable=True,
        default_visible=True,
        label=label,
        description=description,
        semantic_role=role,
        value_type="numeric",
        can_drive_style_rules=True,
    )


def _utc_marker(role: str, label: str, description: str = "") -> OutputSignalContract:
    return OutputSignalContract(
        signal_type="signal",
        renderable=True,
        analysis_usable=True,
        default_visible=True,
        label=label,
        description=description,
        semantic_role=role,
        value_type="numeric",
        can_drive_style_rules=True,
    )


def _utc_analysis_numeric(role: str, label: str, description: str = "") -> OutputSignalContract:
    return OutputSignalContract(
        signal_type="utility",
        renderable=False,
        analysis_usable=True,
        default_visible=False,
        label=label,
        description=description,
        semantic_role=role,
        value_type="numeric",
        can_drive_style_rules=True,
    )


UTC_OUTPUT_SIGNALS = (
    _utc_state("horizontal_range", "Horizontal Range", "True while a horizontal range is active."),
    _utc_state("hr_start", "HR Start", "Sparse boolean horizontal-range start event."),
    _utc_state("hr_end", "HR End", "Sparse boolean horizontal-range end event."),
    _utc_line("range_upper", "HR Upper", "Upper horizontal-range band."),
    _utc_line("range_lower", "HR Lower", "Lower horizontal-range band."),
    _utc_state("uptrend", "Uptrend", "True while an uptrend interval is active."),
    _utc_state("uptrend_start", "Uptrend Start", "Sparse boolean uptrend start event."),
    _utc_state("uptrend_end", "Uptrend End", "Sparse boolean uptrend end event."),
    _utc_state("downtrend", "Downtrend", "True while a downtrend interval is active."),
    _utc_state("downtrend_start", "Downtrend Start", "Sparse boolean downtrend start event."),
    _utc_state("downtrend_end", "Downtrend End", "Sparse boolean downtrend end event."),
    _utc_state("hr_uptrend", "HR + Uptrend", "Composite horizontal-range/uptrend flag."),
    _utc_state("hr_downtrend", "HR + Downtrend", "Composite horizontal-range/downtrend flag."),
    _utc_marker("range_start_marker", "HR Start Marker", "Sparse price marker at horizontal-range start."),
    _utc_marker("range_end_marker", "HR End Marker", "Sparse price marker at horizontal-range end."),
    _utc_marker("uptrend_start_marker", "Uptrend Start Marker", "Sparse price marker at uptrend start."),
    _utc_marker("uptrend_end_marker", "Uptrend End Marker", "Sparse price marker at uptrend end."),
    _utc_marker("downtrend_start_marker", "Downtrend Start Marker", "Sparse price marker at downtrend start."),
    _utc_marker("downtrend_end_marker", "Downtrend End Marker", "Sparse price marker at downtrend end."),
    _utc_state("hr_breakout_attempt", "HR Breakout Attempt", "Sparse boolean event when an active horizontal range is first broken."),
    _utc_state("hr_pending_breakout", "HR Pending Breakout", "True while UTC is waiting for reclaim or breakout confirmation."),
    _utc_state("hr_breakout_confirmed", "HR Breakout Confirmed", "Sparse boolean event when a pending breakout survives the reclaim window."),
    _utc_state("hr_false_breakout", "HR False Breakout", "Sparse boolean event when a pending breakout reclaims the same range in time."),
    _utc_state("hr_reclaim", "HR Reclaim", "Sparse boolean event when price/source re-enters the pending range."),
    _utc_analysis_numeric("hr_break_direction", "HR Break Direction", "Breakout direction: 1 upside, -1 downside, 0 ambiguous."),
    _utc_analysis_numeric("hr_break_extreme", "HR Break Extreme", "Breakout high/low extreme tracked during the pending breakout lifecycle."),
    _utc_analysis_numeric("hr_reclaim_marker", "HR Reclaim Marker", "Sparse source-price marker at the reclaim bar."),
)

OVERLAY = BehaviorContract("overlay", chart_renderable=True, supports_style=True)


def line(resolver: str, *, role: str = "primary") -> OutputContract:
    return OutputContract(
        structure="line-series",
        naming_resolver=resolver,
        signals=(OutputSignalContract(semantic_role=role, can_drive_style_rules=True),),
    )


def multi(resolver: str, signals: tuple[OutputSignalContract, ...]) -> OutputContract:
    return OutputContract(
        structure="multi-line-series",
        naming_resolver=resolver,
        signals=signals,
    )


INDICATOR_CONTRACTS: dict[str, ToolContract] = {
    "sma": ToolContract(
        family="indicator",
        key="sma",
        title="SMA",
        data_inputs=(CLOSE,),
        params=(PERIOD,),
        behavior=OVERLAY,
        output=line("indicator:sma"),
        description="Simple Moving Average.",
    ),
    "ema": ToolContract(
        family="indicator",
        key="ema",
        title="EMA",
        data_inputs=(CLOSE,),
        params=(PERIOD,),
        behavior=OVERLAY,
        output=line("indicator:ema"),
        description="Exponential Moving Average.",
    ),
    "tema": ToolContract(
        family="indicator",
        key="tema",
        title="TEMA",
        data_inputs=(CLOSE,),
        params=(PERIOD,),
        behavior=OVERLAY,
        output=line("indicator:tema"),
        description="Triple Exponential Moving Average.",
    ),
    "hma": ToolContract(
        family="indicator",
        key="hma",
        title="HMA",
        data_inputs=(CLOSE,),
        params=(PERIOD,),
        behavior=OVERLAY,
        output=line("indicator:hma"),
        description="Hull Moving Average.",
    ),
    "kama": ToolContract(
        family="indicator",
        key="kama",
        title="KAMA",
        data_inputs=(CLOSE,),
        params=(FAST_PERIOD, SLOW_PERIOD),
        behavior=OVERLAY,
        output=line("indicator:kama"),
        description="Kaufman's Adaptive Moving Average.",
    ),
    "bb": ToolContract(
        family="indicator",
        key="bb",
        title="Bollinger Bands",
        data_inputs=(CLOSE,),
        params=(PERIOD, STD),
        behavior=OVERLAY,
        output=multi(
            "indicator:bb",
            (
                OutputSignalContract(semantic_role="center", can_drive_style_rules=True),
                OutputSignalContract(semantic_role="upper", can_drive_style_rules=True),
                OutputSignalContract(semantic_role="lower", can_drive_style_rules=True),
            ),
        ),
        description="Bollinger Bands on close.",
    ),
    "hck": ToolContract(
        family="indicator",
        key="hck",
        title="Hancock",
        data_inputs=(HIGH, LOW, CLOSE, VOLUME),
        params=(FAST_VWAP, SLOW_VWAP),
        behavior=OVERLAY,
        output=multi(
            "indicator:hck",
            (
                OutputSignalContract(semantic_role="fast", can_drive_style_rules=True),
                OutputSignalContract(semantic_role="slow", can_drive_style_rules=True),
                OutputSignalContract(
                    signal_type="utility",
                    renderable=False,
                    analysis_usable=False,
                    default_visible=False,
                    semantic_role="state",
                    value_type="categorical",
                    can_drive_style_rules=True,
                ),
            ),
        ),
        description="Fast/slow EW-VWAP pair with directional color state.",
    ),
    "strategy": ToolContract(
        family="indicator",
        key="strategy",
        title="Strategy",
        data_inputs=(HIGH, LOW, CLOSE, VOLUME),
        params=(
            ParamContract("ema_1_period", "int", default=9, minimum=1),
            ParamContract("ema_2_period", "int", default=20, minimum=1),
            ParamContract("ema_3_period", "int", default=50, minimum=1),
            ParamContract("ema_4_period", "int", default=100, minimum=1),
            ParamContract("ema_5_period", "int", default=200, minimum=1),
            ParamContract("ema_6_period", "int", default=400, minimum=1),
            ParamContract("sma_1_period", "int", default=9, minimum=1),
            ParamContract("sma_2_period", "int", default=20, minimum=1),
            ParamContract("sma_3_period", "int", default=50, minimum=1),
            ParamContract("sma_4_period", "int", default=100, minimum=1),
            ParamContract("sma_5_period", "int", default=200, minimum=1),
            ParamContract("sma_6_period", "int", default=400, minimum=1),
            ParamContract("bb_period", "int", default=20, minimum=1),
            ParamContract("bb_std", "float", default=2.0, minimum=0.000001),
            ParamContract("hck_fast_vwap_l", "int", default=13, minimum=1),
            ParamContract("hck_slow_vwap_l", "int", default=48, minimum=1),
        ),
        behavior=OVERLAY,
        output=OutputContract(
            structure="multi-line-series",
            naming_resolver="indicator:strategy",
            dynamic_signals=True,
        ),
        description="Composite price-overlay indicator.",
    ),
    "peaks_troughs": ToolContract(
        family="indicator",
        key="peaks_troughs",
        title="Peaks & Troughs",
        data_inputs=(HIGH, LOW),
        params=(),
        behavior=OVERLAY,
        output=OutputContract(
            structure="events",
            naming_resolver="indicator:peaks_troughs",
            dynamic_signals=True,
        ),
        description="Confirmed fractal peak/trough detector.",
    ),
    "universal_trend_classifier": ToolContract(
        family="indicator",
        key="universal_trend_classifier",
        title="Universal Trend Classifier",
        aliases=("utc",),
        data_inputs=(OPEN, HIGH, LOW, CLOSE),
        params=UTC_PARAMS,
        behavior=OVERLAY,
        output=multi("indicator:universal_trend_classifier", UTC_OUTPUT_SIGNALS),
        description=(
            "Price-pane market-structure classifier emitting range bands, sparse "
            "start/end markers, and non-renderable boolean state outputs."
        ),
    ),
}
