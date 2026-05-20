from __future__ import annotations

from .models import ParamSpec

PERIOD_PARAM = ParamSpec(
    name="period",
    dtype="int",
    required=True,
    default=14,
    label="Period",
    description="Primary lookback period.",
    minimum=1,
)

VOLUME_MEAN_PERIOD_PARAM = ParamSpec(
    name="period",
    dtype="int",
    required=True,
    default=20,
    label="Mean Period",
    description="Rolling mean period for the Volume average line.",
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

UTC_SOURCE_PARAM = ParamSpec(
    name="source",
    dtype="str",
    required=True,
    default="close",
    label="Source",
    description="OHLC source column used by the Universal Trend Classifier.",
    choices=("open", "high", "low", "close"),
)

UTC_FRACTAL_WINDOW_PARAM = ParamSpec(
    name="fractal_window",
    dtype="int",
    required=True,
    default=5,
    label="Fractal Window",
    description="Compatibility alias for trend_fractal_window.",
    minimum=3,
    choices=(3, 5, 7, 9, 11),
)

UTC_TREND_FRACTAL_WINDOW_PARAM = ParamSpec(
    name="trend_fractal_window",
    dtype="int",
    required=True,
    default=5,
    label="Up/Down Trend Fractal",
    description="Peaks & Troughs fractal length consumed by UTC directional trend detection.",
    minimum=3,
    choices=(3, 5, 7, 9, 11),
)

UTC_RANGE_FRACTAL_WINDOW_PARAM = ParamSpec(
    name="range_fractal_window",
    dtype="int",
    required=True,
    default=3,
    label="Range Trend Fractal",
    description="Peaks & Troughs fractal length consumed by UTC horizontal range discovery.",
    minimum=3,
    choices=(3, 5, 7, 9, 11),
)

UTC_HR_BREAK_MODE_PARAM = ParamSpec(
    name="hr_break_mode",
    dtype="str",
    required=True,
    default="close",
    label="Range Break Mode",
    description="Horizontal-range invalidation mode after a range is active.",
    choices=("close", "wick", "hybrid"),
)

UTC_PEAK_COLUMN_PARAM = ParamSpec(
    name="peak_column",
    dtype="str",
    required=False,
    default=None,
    label="Peak Column",
    description="Legacy trend peak column override. Leave empty to use peak_fractal_{trend_fractal_window}.",
)

UTC_TROUGH_COLUMN_PARAM = ParamSpec(
    name="trough_column",
    dtype="str",
    required=False,
    default=None,
    label="Trough Column",
    description="Legacy trend trough column override. Leave empty to use trough_fractal_{trend_fractal_window}.",
)

UTC_MIN_HR_BAND_PERC_PARAM = ParamSpec(
    name="min_hr_band_perc",
    dtype="float",
    required=True,
    default=0.005,
    label="Min HR Band %",
    description="Minimum horizontal-range band size as a fraction of source price.",
    minimum=0.0,
)

UTC_HR_TREND_LENGTH_PARAM = ParamSpec(
    name="hr_trend_length",
    dtype="int",
    required=True,
    default=20,
    label="HR Trend Length",
    description="Lookback window used to evaluate horizontal-range/trend structure.",
    minimum=3,
)

UTC_HR_TREND_ATR_MULT_PARAM = ParamSpec(
    name="hr_trend_atr_mult",
    dtype="float",
    required=True,
    default=1.0,
    label="HR ATR Mult",
    description="ATR multiplier used for horizontal-range band tolerance.",
    minimum=0.0,
)

UTC_HR_TREND_ATR_LEN_PARAM = ParamSpec(
    name="hr_trend_atr_len",
    dtype="int",
    required=True,
    default=500,
    label="HR ATR Length",
    description="Rolling ATR averaging length used by the classifier.",
    minimum=1,
)

UTC_HR_TREND_TOL_MULT_PARAM = ParamSpec(
    name="hr_trend_tol_mult",
    dtype="float",
    required=True,
    default=0.3,
    label="HR Trend Tolerance Mult",
    description="ATR multiplier reserved for incremental/realtime trend-extension tolerance; historical directional trend detection remains strict.",
    minimum=0.0,
)

UTC_HR_TREND_MAX_GAP_PARAM = ParamSpec(
    name="hr_trend_max_gap",
    dtype="int",
    required=True,
    default=20,
    label="HR Trend Max Gap",
    description="Maximum allowed gap between qualifying swings for horizontal-range continuity.",
    minimum=1,
)

UTC_HR_MIN_INSIDE_RATIO_PARAM = ParamSpec(
    name="hr_min_inside_ratio",
    dtype="float",
    required=True,
    default=0.8,
    label="HR Min Inside Ratio",
    description="Minimum ratio of bars inside the candidate horizontal-range band.",
    minimum=0.000001,
    maximum=1.0,
)

UTC_MIN_RANGE_SWINGS_PARAM = ParamSpec(
    name="min_range_swings",
    dtype="int",
    required=True,
    default=4,
    label="Min Range Swings",
    description="Minimum alternating swings required to confirm a horizontal range.",
    minimum=4,
)

UTC_PARAMS = (
    UTC_SOURCE_PARAM,
    UTC_FRACTAL_WINDOW_PARAM,
    UTC_TREND_FRACTAL_WINDOW_PARAM,
    UTC_PEAK_COLUMN_PARAM,
    UTC_TROUGH_COLUMN_PARAM,
    UTC_MIN_HR_BAND_PERC_PARAM,
    UTC_HR_TREND_LENGTH_PARAM,
    UTC_HR_TREND_ATR_MULT_PARAM,
    UTC_HR_TREND_ATR_LEN_PARAM,
    UTC_HR_TREND_TOL_MULT_PARAM,
    UTC_HR_TREND_MAX_GAP_PARAM,
    UTC_HR_MIN_INSIDE_RATIO_PARAM,
    UTC_MIN_RANGE_SWINGS_PARAM,
    UTC_RANGE_FRACTAL_WINDOW_PARAM,
    UTC_HR_BREAK_MODE_PARAM,
)

BOOST_BREAKOUTS_PARAM = ParamSpec(
    name="boost_breakouts",
    dtype="bool",
    required=False,
    default=True,
    label="Boost Breakouts",
    description="Boost fresh Donchian highs/lows in ARSI.",
)

ARSI_METHOD_PARAM = ParamSpec(
    name="method",
    dtype="str",
    required=True,
    default="RMA",
    label="Method",
    description="Smoothing method used for the primary ARSI numerator and denominator.",
    choices=("EMA", "SMA", "RMA", "TMA"),
)

ARSI_SIGNAL_PERIOD_PARAM = ParamSpec(
    name="signal_period",
    dtype="int",
    required=True,
    default=14,
    label="Signal Period",
    description="Moving-average period for the ARSI signal line.",
    minimum=1,
)

ARSI_SIGNAL_METHOD_PARAM = ParamSpec(
    name="signal_method",
    dtype="str",
    required=True,
    default="EMA",
    label="Signal Method",
    description="Smoothing method used for the ARSI signal line.",
    choices=("EMA", "SMA", "RMA", "TMA"),
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

SOURCE_COLUMNS_PARAM = ParamSpec(
    name="source_columns",
    dtype="str",
    required=True,
    default="close",
    label="Source Columns",
    description="Comma-separated source column names, for example: close, volume, feature_1",
)

SOURCE_PARAM = ParamSpec(
    name="source",
    dtype="str",
    required=True,
    default="close",
    label="Source",
    description="Single source column name, for example: close or ema_14_close",
)

DERIVATIVE_ORDER_PARAM = ParamSpec(
    name="order",
    dtype="int",
    required=False,
    default=1,
    label="Derivative Order",
    description="Derivative order. Supported values in this phase: 1 or 2.",
    minimum=1,
    maximum=2,
)

ANGLE_UNIT_PARAM = ParamSpec(
    name="unit",
    dtype="str",
    required=False,
    default="deg",
    label="Unit",
    description="Output angular unit for the unary angle construct.",
    choices=("deg", "rad"),
)

FAST_SOURCE_PARAM = ParamSpec(
    name="fast",
    dtype="str",
    required=True,
    default="",
    label="Fast Source",
    description="Fast source column name.",
)

MID_SOURCE_PARAM = ParamSpec(
    name="mid",
    dtype="str",
    required=False,
    default="",
    label="Mid Source",
    description="Optional mid source column name.",
)

SLOW_SOURCE_PARAM = ParamSpec(
    name="slow",
    dtype="str",
    required=True,
    default="",
    label="Slow Source",
    description="Slow source column name.",
)

TIE_POLICY_PARAM = ParamSpec(
    name="tie_policy",
    dtype="str",
    required=False,
    default="carry",
    label="Tie Policy",
    description="How braid-state ties are handled for the ambient braid state output.",
    choices=("carry", "drop"),
)

ZERO_EPS_PARAM = ParamSpec(
    name="zero_eps",
    dtype="float",
    required=False,
    default=0.0,
    label="Zero Epsilon",
    description="Near-zero threshold used for trap-area segment boundaries.",
    minimum=0.0,
)

PERCENT_SPAN_ANGLE_UNIT_PARAM = ParamSpec(
    name="unit",
    dtype="str",
    required=False,
    default="deg",
    label="Unit",
    description="Output unit for percent-span-angle values.",
    choices=("deg", "rad"),
)

BRAID_INSTABILITY_N_PARAM = ParamSpec(
    name="n",
    dtype="int",
    required=False,
    default=5,
    label="Instability Window",
    description="Rolling window used to compute braid instability.",
    minimum=1,
)

DELTA_MODE_PARAM = ParamSpec(
    name="mode",
    dtype="str",
    required=False,
    default="abs",
    label="Delta Mode",
    description="Delta output mode. 'abs' emits raw signed separation. 'pct' emits signed percent-relative separation versus the slow source.",
    choices=("abs", "pct"),
)

DELTA_EPS_PARAM = ParamSpec(
    name="eps",
    dtype="float",
    required=False,
    default=1e-12,
    label="Delta Epsilon",
    description="Strictly positive denominator stabilization value used only when delta mode is 'pct'.",
    minimum=0.0,
)

ANGLE_MTM_N_PARAM = ParamSpec(
    name="n",
    dtype="int",
    required=False,
    default=3,
    label="Momentum Window",
    description="Lookback window used to compute angle momentum.",
    minimum=1,
)

MULTIPLIER_PARAM = ParamSpec(
    name="multiplier",
    dtype="float",
    required=False,
    default=1.0,
    label="Multiplier",
    description="Final multiplier applied to the estimated movement floor.",
    minimum=0.000001,
)

FLOOR_QUANTILE_PARAM = ParamSpec(
    name="floor_quantile",
    dtype="float",
    required=False,
    default=0.05,
    label="Floor Quantile",
    description="Low quantile used to estimate the minimum meaningful movement floor.",
    minimum=0.0,
    maximum=1.0,
)

GLOBAL_MIN_STEP_PARAM = ParamSpec(
    name="global_min_step",
    dtype="float",
    required=False,
    default=1e-12,
    label="Global Min Step",
    description="Strictly-positive global fallback step for degenerate or flat series.",
    minimum=0.0,
)

QUANTILE_METHOD_PARAM = ParamSpec(
    name="quantile_method",
    dtype="str",
    required=False,
    default="nearest",
    label="Quantile Method",
    description="Quantile interpolation/method mode used by the variation estimator.",
    choices=("nearest", "lower", "higher", "midpoint", "linear"),
)

N_BINS_PARAM = ParamSpec(
    name="n_bins",
    dtype="int",
    required=False,
    default=15,
    label="Number of Bins",
    description="Number of signed bins per side.",
    minimum=1,
)

BOUNDARY_EPS_PARAM = ParamSpec(
    name="boundary_eps",
    dtype="float",
    required=False,
    default=1e-12,
    label="Boundary Epsilon",
    description="Absolute tolerance used only for scalar threshold comparisons.",
    minimum=0.0,
)

STRATEGY_EMA_1_PERIOD_PARAM = ParamSpec(
    name="ema_1_period",
    dtype="int",
    required=True,
    default=9,
    label="EMA 1 Period",
    description="Lookback period for Strategy EMA slot 1.",
    minimum=1,
)

STRATEGY_EMA_2_PERIOD_PARAM = ParamSpec(
    name="ema_2_period",
    dtype="int",
    required=True,
    default=20,
    label="EMA 2 Period",
    description="Lookback period for Strategy EMA slot 2.",
    minimum=1,
)

STRATEGY_EMA_3_PERIOD_PARAM = ParamSpec(
    name="ema_3_period",
    dtype="int",
    required=True,
    default=50,
    label="EMA 3 Period",
    description="Lookback period for Strategy EMA slot 3.",
    minimum=1,
)

STRATEGY_EMA_4_PERIOD_PARAM = ParamSpec(
    name="ema_4_period",
    dtype="int",
    required=True,
    default=100,
    label="EMA 4 Period",
    description="Lookback period for Strategy EMA slot 4.",
    minimum=1,
)

STRATEGY_EMA_5_PERIOD_PARAM = ParamSpec(
    name="ema_5_period",
    dtype="int",
    required=True,
    default=200,
    label="EMA 5 Period",
    description="Lookback period for Strategy EMA slot 5.",
    minimum=1,
)

STRATEGY_EMA_6_PERIOD_PARAM = ParamSpec(
    name="ema_6_period",
    dtype="int",
    required=True,
    default=400,
    label="EMA 6 Period",
    description="Lookback period for Strategy EMA slot 6.",
    minimum=1,
)

STRATEGY_SMA_1_PERIOD_PARAM = ParamSpec(
    name="sma_1_period",
    dtype="int",
    required=True,
    default=9,
    label="SMA 1 Period",
    description="Lookback period for Strategy SMA slot 1.",
    minimum=1,
)

STRATEGY_SMA_2_PERIOD_PARAM = ParamSpec(
    name="sma_2_period",
    dtype="int",
    required=True,
    default=20,
    label="SMA 2 Period",
    description="Lookback period for Strategy SMA slot 2.",
    minimum=1,
)

STRATEGY_SMA_3_PERIOD_PARAM = ParamSpec(
    name="sma_3_period",
    dtype="int",
    required=True,
    default=50,
    label="SMA 3 Period",
    description="Lookback period for Strategy SMA slot 3.",
    minimum=1,
)

STRATEGY_SMA_4_PERIOD_PARAM = ParamSpec(
    name="sma_4_period",
    dtype="int",
    required=True,
    default=100,
    label="SMA 4 Period",
    description="Lookback period for Strategy SMA slot 4.",
    minimum=1,
)

STRATEGY_SMA_5_PERIOD_PARAM = ParamSpec(
    name="sma_5_period",
    dtype="int",
    required=True,
    default=200,
    label="SMA 5 Period",
    description="Lookback period for Strategy SMA slot 5.",
    minimum=1,
)

STRATEGY_SMA_6_PERIOD_PARAM = ParamSpec(
    name="sma_6_period",
    dtype="int",
    required=True,
    default=400,
    label="SMA 6 Period",
    description="Lookback period for Strategy SMA slot 6.",
    minimum=1,
)

STRATEGY_BB_PERIOD_PARAM = ParamSpec(
    name="bb_period",
    dtype="int",
    required=True,
    default=20,
    label="BB Period",
    description="Bollinger Bands lookback period inside Strategy.",
    minimum=1,
)

STRATEGY_BB_STD_PARAM = ParamSpec(
    name="bb_std",
    dtype="float",
    required=True,
    default=2.0,
    label="BB Std Dev Multiplier",
    description="Bollinger Bands standard deviation multiplier inside Strategy.",
    minimum=0.000001,
)

STRATEGY_HCK_FAST_VWAP_PARAM = ParamSpec(
    name="hck_fast_vwap_l",
    dtype="int",
    required=True,
    default=13,
    label="HCK Fast VWAP Length",
    description="Fast EW-VWAP length for the Strategy Hancock pair.",
    minimum=1,
)

STRATEGY_HCK_SLOW_VWAP_PARAM = ParamSpec(
    name="hck_slow_vwap_l",
    dtype="int",
    required=True,
    default=48,
    label="HCK Slow VWAP Length",
    description="Slow EW-VWAP length for the Strategy Hancock pair.",
    minimum=1,
)
