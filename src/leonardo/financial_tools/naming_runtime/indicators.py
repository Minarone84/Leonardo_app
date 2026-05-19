from __future__ import annotations

from typing import Any, Sequence

from .tokens import _slugify_token

def build_indicator_signal_name(indicator_key: str, *parts: Any) -> str:
    """
    Build a canonical lowercase signal name for parameterized single-output
    indicators.

    Examples:
        build_indicator_signal_name("ema", 14) -> ema_14
        build_indicator_signal_name("kama", 2, 30) -> kama_2_30
    """
    base = _slugify_token(indicator_key)
    suffix_parts = [_slugify_token(part) for part in parts if part is not None and str(part) != ""]
    if not suffix_parts:
        return base
    return "_".join([base, *suffix_parts])


def build_sma_signal_name(period: Any) -> str:
    return build_indicator_signal_name("sma", period)


def build_ema_signal_name(period: Any) -> str:
    return build_indicator_signal_name("ema", period)


def build_tema_signal_name(period: Any) -> str:
    return build_indicator_signal_name("tema", period)


def build_hma_signal_name(period: Any) -> str:
    return build_indicator_signal_name("hma", period)


def build_kama_signal_name(fast_period: Any, slow_period: Any) -> str:
    return build_indicator_signal_name("kama", fast_period, slow_period)


def build_bb_signal_names() -> tuple[str, str, str]:
    """
    Canonical Bollinger Bands output names.
    """
    return (
        "bb_middle",
        "bb_upper_band",
        "bb_lower_band",
    )


def build_hck_signal_names() -> tuple[str, str, str]:
    """
    Canonical Hancock output names.

    Note:
    - fast_vwap and slow_vwap are analytical signals
    - vwap_color is currently an auxiliary/utility output
    """
    return (
        "fast_vwap",
        "slow_vwap",
        "vwap_color",
    )

STRATEGY_EMA_SLOT_COUNT: int = 6
STRATEGY_SMA_SLOT_COUNT: int = 6


def _validate_strategy_slot(slot: Any, *, family: str, max_slots: int) -> int:
    try:
        slot_int = int(slot)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Strategy {family} slot must be an integer.") from exc

    if slot_int < 1 or slot_int > max_slots:
        raise ValueError(f"Strategy {family} slot must be in the range 1..{max_slots}.")
    return slot_int


def build_strategy_ema_signal_name(slot: Any) -> str:
    """
    Canonical Strategy EMA slot output name.

    Examples:
    - st_ema_1
    - st_ema_6
    """
    slot_int = _validate_strategy_slot(slot, family="EMA", max_slots=STRATEGY_EMA_SLOT_COUNT)
    return f"st_ema_{slot_int}"


def build_strategy_sma_signal_name(slot: Any) -> str:
    """
    Canonical Strategy SMA slot output name.

    Examples:
    - st_sma_1
    - st_sma_6
    """
    slot_int = _validate_strategy_slot(slot, family="SMA", max_slots=STRATEGY_SMA_SLOT_COUNT)
    return f"st_sma_{slot_int}"


def build_strategy_bb_signal_names() -> tuple[str, str, str]:
    """
    Canonical Strategy Bollinger Bands output names.
    """
    return (
        "st_bb_middle",
        "st_bb_upper_band",
        "st_bb_lower_band",
    )


def build_strategy_hck_signal_names() -> tuple[str, str, str]:
    """
    Canonical Strategy Hancock-style output names.

    Note:
    - st_fast_vwap and st_slow_vwap are analytical signals
    - st_vwap_color is an auxiliary/utility output
    """
    return (
        "st_fast_vwap",
        "st_slow_vwap",
        "st_vwap_color",
    )


def build_strategy_signal_names() -> tuple[str, ...]:
    """
    Canonical Strategy composite output names.

    Output order is stable and slot-based so chart-local style identity does not
    drift when internal Strategy periods are edited.
    """
    names: list[str] = []

    for slot in range(1, STRATEGY_EMA_SLOT_COUNT + 1):
        names.append(build_strategy_ema_signal_name(slot))

    for slot in range(1, STRATEGY_SMA_SLOT_COUNT + 1):
        names.append(build_strategy_sma_signal_name(slot))

    names.extend(build_strategy_bb_signal_names())
    names.extend(build_strategy_hck_signal_names())
    return tuple(names)

PEAKS_TROUGHS_FRACTAL_LENGTHS: tuple[int, ...] = (3, 5, 7, 9, 11)


def build_peaks_troughs_signal_name(kind: Any, fractal_length: Any) -> str:
    """
    Canonical Peaks & Troughs event output name.

    Examples:
    - peak_fractal_3
    - trough_fractal_5
    """
    kind_token = _slugify_token(kind)
    if kind_token not in {"peak", "trough"}:
        raise ValueError("Peaks & Troughs signal kind must be 'peak' or 'trough'.")

    return f"{kind_token}_fractal_{_slugify_token(fractal_length)}"


def build_peaks_troughs_signal_names(
    fractal_lengths: Sequence[Any] = PEAKS_TROUGHS_FRACTAL_LENGTHS,
) -> tuple[str, ...]:
    """
    Canonical Peaks & Troughs output names for the fixed supported fractals.
    """
    names: list[str] = []
    for fractal_length in fractal_lengths:
        names.append(build_peaks_troughs_signal_name("peak", fractal_length))
        names.append(build_peaks_troughs_signal_name("trough", fractal_length))
    return tuple(names)


UNIVERSAL_TREND_CLASSIFIER_SIGNAL_NAMES: tuple[str, ...] = (
    "horizontal_range",
    "hr_start",
    "hr_end",
    "hor_upper",
    "hor_lower",
    "uptrend",
    "uptrend_start",
    "uptrend_end",
    "downtrend",
    "downtrend_start",
    "downtrend_end",
    "hr_uptrend",
    "hr_downtrend",
    "hr_start_marker",
    "hr_end_marker",
    "uptrend_start_marker",
    "uptrend_end_marker",
    "downtrend_start_marker",
    "downtrend_end_marker",
    "hr_breakout_attempt",
    "hr_pending_breakout",
    "hr_breakout_confirmed",
    "hr_false_breakout",
    "hr_reclaim",
    "hr_break_direction",
    "hr_break_extreme",
    "hr_reclaim_marker",
)


def build_universal_trend_classifier_signal_names(**params: Any) -> tuple[str, ...]:
    """Canonical Universal Trend Classifier output names in runtime-emitted order."""
    del params
    return UNIVERSAL_TREND_CLASSIFIER_SIGNAL_NAMES


def get_indicator_signal_names(indicator_key: str, **params: Any) -> tuple[str, ...]:
    """
    Return canonical output signal names for a registered indicator family.
    """
    key = _slugify_token(indicator_key)

    if key == "sma":
        return (build_sma_signal_name(params["period"]),)

    if key == "ema":
        return (build_ema_signal_name(params["period"]),)

    if key == "tema":
        return (build_tema_signal_name(params["period"]),)

    if key == "hma":
        return (build_hma_signal_name(params["period"]),)

    if key == "kama":
        return (build_kama_signal_name(params["fast_period"], params["slow_period"]),)

    if key == "bb":
        return build_bb_signal_names()

    if key == "hck":
        return build_hck_signal_names()

    if key == "strategy":
        return build_strategy_signal_names()

    if key == "peaks_troughs":
        return build_peaks_troughs_signal_names()

    if key == "universal_trend_classifier":
        return build_universal_trend_classifier_signal_names(**params)

    raise KeyError(f"Unsupported indicator key for canonical signal naming: {indicator_key}")


# ----------------------------------------------------------------------
# Oscillator signal naming helpers
