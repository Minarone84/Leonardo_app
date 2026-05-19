from __future__ import annotations

from typing import Any, Mapping

from .models import OutputSignalSpec

from leonardo.financial_tools.ft_naming import (
    PEAKS_TROUGHS_FRACTAL_LENGTHS,
    STRATEGY_EMA_SLOT_COUNT,
    STRATEGY_SMA_SLOT_COUNT,
    build_arsi_signal_name,
    build_bb_signal_names,
    build_ema_signal_name,
    build_hck_signal_names,
    build_hma_signal_name,
    build_kama_signal_name,
    build_mfi_signal_name,
    build_obv_signal_name,
    build_volume_signal_names,
    build_peaks_troughs_signal_name,
    build_peaks_troughs_signal_names,
    build_rsi_signal_name,
    build_sma_signal_name,
    build_smi_signal_names,
    build_strategy_bb_signal_names,
    build_strategy_ema_signal_name,
    build_strategy_hck_signal_names,
    build_strategy_signal_names,
    build_strategy_sma_signal_name,
    build_tdirsi_signal_names,
    build_tema_signal_name,
    build_universal_trend_classifier_signal_names,
    get_construct_signal_names,
)

def _resolve_sma_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_sma_signal_name(params["period"]),)


def _resolve_ema_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_ema_signal_name(params["period"]),)


def _resolve_tema_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_tema_signal_name(params["period"]),)


def _resolve_hma_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_hma_signal_name(params["period"]),)


def _resolve_kama_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_kama_signal_name(params["fast_period"], params["slow_period"]),)


def _resolve_bb_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_bb_signal_names()


def _resolve_hck_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_hck_signal_names()


def _resolve_strategy_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    del params
    return build_strategy_signal_names()


def _resolve_peaks_troughs_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    del params
    return build_peaks_troughs_signal_names()


def _resolve_universal_trend_classifier_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_universal_trend_classifier_signal_names(**dict(params))


def _resolve_sma_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_sma_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="SMA",
            description="Primary SMA line.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_ema_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_ema_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="EMA",
            description="Primary EMA line.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_tema_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_tema_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="TEMA",
            description="Primary TEMA line.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_hma_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_hma_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="HMA",
            description="Primary HMA line.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_kama_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_kama_signal_name(params["fast_period"], params["slow_period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="KAMA",
            description="Primary KAMA line.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_bb_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    middle, upper, lower = build_bb_signal_names()
    return (
        OutputSignalSpec(
            name=middle,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Middle",
            description="Bollinger middle band.",
            semantic_role="center",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=upper,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Upper Band",
            description="Bollinger upper band.",
            semantic_role="upper",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=lower,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Lower Band",
            description="Bollinger lower band.",
            semantic_role="lower",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_hck_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    fast_vwap, slow_vwap, vwap_color = build_hck_signal_names()
    return (
        OutputSignalSpec(
            name=fast_vwap,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Fast VWAP",
            description="Fast EW-VWAP line.",
            semantic_role="fast",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=slow_vwap,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Slow VWAP",
            description="Slow EW-VWAP line.",
            semantic_role="slow",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=vwap_color,
            signal_type="utility",
            renderable=False,
            analysis_usable=False,
            default_visible=False,
            label="VWAP Color State",
            description="Auxiliary directional color state. Not a canonical plotted line.",
            semantic_role="state",
            value_type="categorical",
            can_drive_style_rules=True,
        ),
    )


def _resolve_strategy_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    del params

    signals: list[OutputSignalSpec] = []

    for slot in range(1, STRATEGY_EMA_SLOT_COUNT + 1):
        signal_name = build_strategy_ema_signal_name(slot)
        signals.append(
            OutputSignalSpec(
                name=signal_name,
                signal_type="signal",
                renderable=True,
                analysis_usable=True,
                label=f"EMA {slot}",
                description=f"Strategy EMA slot {slot}.",
                semantic_role="ema",
                value_type="numeric",
                can_drive_style_rules=True,
            )
        )

    for slot in range(1, STRATEGY_SMA_SLOT_COUNT + 1):
        signal_name = build_strategy_sma_signal_name(slot)
        signals.append(
            OutputSignalSpec(
                name=signal_name,
                signal_type="signal",
                renderable=True,
                analysis_usable=True,
                label=f"SMA {slot}",
                description=f"Strategy SMA slot {slot}.",
                semantic_role="sma",
                value_type="numeric",
                can_drive_style_rules=True,
            )
        )

    bb_middle, bb_upper_band, bb_lower_band = build_strategy_bb_signal_names()
    signals.extend((
        OutputSignalSpec(
            name=bb_middle,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Middle",
            description="Strategy Bollinger middle band.",
            semantic_role="center",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=bb_upper_band,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Upper Band",
            description="Strategy Bollinger upper band.",
            semantic_role="upper",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=bb_lower_band,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="BB Lower Band",
            description="Strategy Bollinger lower band.",
            semantic_role="lower",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    ))

    st_fast_vwap, st_slow_vwap, st_vwap_color = build_strategy_hck_signal_names()
    signals.extend((
        OutputSignalSpec(
            name=st_fast_vwap,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Fast VWAP",
            description="Strategy fast EW-VWAP line.",
            semantic_role="fast",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=st_slow_vwap,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Slow VWAP",
            description="Strategy slow EW-VWAP line.",
            semantic_role="slow",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=st_vwap_color,
            signal_type="utility",
            renderable=False,
            analysis_usable=False,
            default_visible=False,
            label="VWAP Color State",
            description="Strategy auxiliary directional color state. Not a canonical plotted line.",
            semantic_role="state",
            value_type="categorical",
            can_drive_style_rules=True,
        ),
    ))

    return tuple(signals)


def _resolve_peaks_troughs_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    del params

    signals: list[OutputSignalSpec] = []
    for fractal_length in PEAKS_TROUGHS_FRACTAL_LENGTHS:
        peak_name = build_peaks_troughs_signal_name("peak", fractal_length)
        trough_name = build_peaks_troughs_signal_name("trough", fractal_length)
        default_visible = fractal_length == 3

        signals.append(
            OutputSignalSpec(
                name=peak_name,
                signal_type="signal",
                renderable=True,
                analysis_usable=True,
                default_visible=default_visible,
                label=f"Peak {fractal_length}",
                description=(
                    f"Confirmed {fractal_length}-bar peak fractal event using the bar high as the marker price."
                ),
                semantic_role="peak",
                value_type="numeric",
                can_drive_style_rules=True,
            )
        )
        signals.append(
            OutputSignalSpec(
                name=trough_name,
                signal_type="signal",
                renderable=True,
                analysis_usable=True,
                default_visible=default_visible,
                label=f"Trough {fractal_length}",
                description=(
                    f"Confirmed {fractal_length}-bar trough fractal event using the bar low as the marker price."
                ),
                semantic_role="trough",
                value_type="numeric",
                can_drive_style_rules=True,
            )
        )

    return tuple(signals)


def _utc_state_signal(name: str, role: str, label: str, description: str) -> OutputSignalSpec:
    return OutputSignalSpec(
        name=name,
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


def _utc_render_signal(name: str, role: str, label: str, description: str) -> OutputSignalSpec:
    return OutputSignalSpec(
        name=name,
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


def _utc_analysis_numeric_signal(name: str, role: str, label: str, description: str) -> OutputSignalSpec:
    return OutputSignalSpec(
        name=name,
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


def _resolve_universal_trend_classifier_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    del params
    return (
        _utc_state_signal("horizontal_range", "horizontal_range", "Horizontal Range", "True while a horizontal range is active."),
        _utc_state_signal("hr_start", "hr_start", "HR Start", "Sparse boolean horizontal-range start event."),
        _utc_state_signal("hr_end", "hr_end", "HR End", "Sparse boolean horizontal-range end event."),
        _utc_render_signal("hor_upper", "range_upper", "HR Upper", "Upper horizontal-range band."),
        _utc_render_signal("hor_lower", "range_lower", "HR Lower", "Lower horizontal-range band."),
        _utc_state_signal("uptrend", "uptrend", "Uptrend", "True while an uptrend interval is active."),
        _utc_state_signal("uptrend_start", "uptrend_start", "Uptrend Start", "Sparse boolean uptrend start event."),
        _utc_state_signal("uptrend_end", "uptrend_end", "Uptrend End", "Sparse boolean uptrend end event."),
        _utc_state_signal("downtrend", "downtrend", "Downtrend", "True while a downtrend interval is active."),
        _utc_state_signal("downtrend_start", "downtrend_start", "Downtrend Start", "Sparse boolean downtrend start event."),
        _utc_state_signal("downtrend_end", "downtrend_end", "Downtrend End", "Sparse boolean downtrend end event."),
        _utc_state_signal("hr_uptrend", "hr_uptrend", "HR + Uptrend", "Composite horizontal-range/uptrend flag."),
        _utc_state_signal("hr_downtrend", "hr_downtrend", "HR + Downtrend", "Composite horizontal-range/downtrend flag."),
        _utc_render_signal("hr_start_marker", "range_start_marker", "HR Start Marker", "Sparse price marker at horizontal-range start."),
        _utc_render_signal("hr_end_marker", "range_end_marker", "HR End Marker", "Sparse price marker at horizontal-range end."),
        _utc_render_signal("uptrend_start_marker", "uptrend_start_marker", "Uptrend Start Marker", "Sparse price marker at uptrend start."),
        _utc_render_signal("uptrend_end_marker", "uptrend_end_marker", "Uptrend End Marker", "Sparse price marker at uptrend end."),
        _utc_render_signal("downtrend_start_marker", "downtrend_start_marker", "Downtrend Start Marker", "Sparse price marker at downtrend start."),
        _utc_render_signal("downtrend_end_marker", "downtrend_end_marker", "Downtrend End Marker", "Sparse price marker at downtrend end."),
        _utc_state_signal("hr_breakout_attempt", "hr_breakout_attempt", "HR Breakout Attempt", "Sparse boolean event when an active horizontal range is first broken."),
        _utc_state_signal("hr_pending_breakout", "hr_pending_breakout", "HR Pending Breakout", "True while UTC is waiting for reclaim or breakout confirmation."),
        _utc_state_signal("hr_breakout_confirmed", "hr_breakout_confirmed", "HR Breakout Confirmed", "Sparse boolean event when a pending breakout survives the reclaim window."),
        _utc_state_signal("hr_false_breakout", "hr_false_breakout", "HR False Breakout", "Sparse boolean event when a pending breakout reclaims the same range in time."),
        _utc_state_signal("hr_reclaim", "hr_reclaim", "HR Reclaim", "Sparse boolean event when price/source re-enters the pending range."),
        _utc_analysis_numeric_signal("hr_break_direction", "hr_break_direction", "HR Break Direction", "Breakout direction: 1 upside, -1 downside, 0 ambiguous."),
        _utc_analysis_numeric_signal("hr_break_extreme", "hr_break_extreme", "HR Break Extreme", "Breakout high/low extreme tracked during the pending breakout lifecycle."),
        _utc_analysis_numeric_signal("hr_reclaim_marker", "hr_reclaim_marker", "HR Reclaim Marker", "Sparse source-price marker at the reclaim bar."),
    )


# ---------------------------------------------------------------------------
# Oscillator output resolvers
# ---------------------------------------------------------------------------

def _resolve_rsi_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_rsi_signal_name(params["period"]),)


def _resolve_arsi_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_arsi_signal_name(params["period"]),)


def _resolve_tdirsi_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_tdirsi_signal_names(
        params["period"],
        params["band_length"],
        params["fast_len"],
        params["slow_len"],
        params["fast_smo"],
        params["slow_smo"],
    )


def _resolve_smi_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_smi_signal_names(
        params["k_length"],
        params["d_length"],
    )


def _resolve_mfi_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_mfi_signal_name(params["period"]),)


def _resolve_obv_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return (build_obv_signal_name(),)


def _resolve_volume_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return build_volume_signal_names(params["period"])


def _resolve_rsi_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_rsi_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="RSI",
            description="Primary RSI line.",
        ),
    )


def _resolve_arsi_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_arsi_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="ARSI",
            description="Primary augmented RSI line.",
        ),
    )


def _resolve_tdirsi_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    fast_ma, slow_ma, up, dn, mid = build_tdirsi_signal_names(
        params["period"],
        params["band_length"],
        params["fast_len"],
        params["slow_len"],
        params["fast_smo"],
        params["slow_smo"],
    )
    return (
        OutputSignalSpec(
            name=fast_ma,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Fast MA",
            description="Fast smoothed RSI line.",
        ),
        OutputSignalSpec(
            name=slow_ma,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Slow MA",
            description="Slow smoothed RSI line.",
        ),
        OutputSignalSpec(
            name=up,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Upper Band",
            description="Upper RSI volatility band.",
        ),
        OutputSignalSpec(
            name=dn,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Lower Band",
            description="Lower RSI volatility band.",
        ),
        OutputSignalSpec(
            name=mid,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Mid Band",
            description="Mid RSI volatility band.",
        ),
    )


def _resolve_smi_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    smi_name, smi_signal_name = build_smi_signal_names(
        params["k_length"],
        params["d_length"],
    )
    return (
        OutputSignalSpec(
            name=smi_name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="SMI",
            description="Primary stochastic momentum index line.",
        ),
        OutputSignalSpec(
            name=smi_signal_name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="SMI Signal",
            description="SMI signal line.",
        ),
    )


def _resolve_mfi_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_mfi_signal_name(params["period"])
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="MFI",
            description="Primary money flow index line.",
        ),
    )


def _resolve_obv_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = build_obv_signal_name()
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="OBV",
            description="Primary on-balance volume line.",
        ),
    )


def _resolve_volume_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    volume_name, mean_name = build_volume_signal_names(params["period"])
    return (
        OutputSignalSpec(
            name=volume_name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Volume",
            description="Raw traded volume from the canonical OHLCV dataset.",
            semantic_role="primary",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=mean_name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Volume Mean",
            description="Rolling mean of traded volume.",
            semantic_role="mean",
            value_type="numeric",
            can_drive_style_rules=True,
        ),
    )


def _resolve_derivative_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("derivative", **params)


def _resolve_angle_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("angle", **params)


def _resolve_braids_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("braids", **params)


def _resolve_braid_instability_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("braid_instability", **params)


def _resolve_delta_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("delta", **params)


def _resolve_trap_area_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("trap_area", **params)


def _resolve_percent_span_angle_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("percent_span_angle", **params)


def _resolve_angle_momentum_output_names(params: Mapping[str, Any]) -> tuple[str, ...]:
    return get_construct_signal_names("angle_momentum", **params)


def _resolve_derivative_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("derivative", **params)
    return tuple(
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Derivative",
            description="Derivative of the selected source.",
        )
        for name in names
    )


def _resolve_angle_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = get_construct_signal_names("angle", **params)[0]
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Angle",
            description="Unary angular transform of the selected source.",
        ),
    )


def _resolve_braids_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("braids", **params)
    if len(names) != 3:
        raise ValueError("braids is expected to emit exactly three canonical outputs")

    ambient_name, width_name, compression_name = names
    return (
        OutputSignalSpec(
            name=ambient_name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            default_visible=True,
            label="Braid Ambient State",
            description="Categorical braid ordering state series.",
            semantic_role="state",
            value_type="categorical",
            can_drive_style_rules=True,
        ),
        OutputSignalSpec(
            name=width_name,
            signal_type="signal",
            renderable=False,
            analysis_usable=True,
            default_visible=False,
            label="Braid Width",
            description="Total braid envelope spread. Retained for analysis/chaining, not chart rendering.",
            semantic_role="analysis",
            value_type="numeric",
        ),
        OutputSignalSpec(
            name=compression_name,
            signal_type="signal",
            renderable=False,
            analysis_usable=True,
            default_visible=False,
            label="Braid Compression",
            description="Minimum pairwise braid separation. Retained for analysis/chaining, not chart rendering.",
            semantic_role="analysis",
            value_type="numeric",
        ),
    )


def _resolve_braid_instability_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    name = get_construct_signal_names("braid_instability", **params)[0]
    return (
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Braid Instability",
            description="Rolling instability score of raw braid state changes.",
        ),
    )


def _resolve_delta_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("delta", **params)
    mode = str(params.get("mode", "abs")).strip().lower()
    label = "Delta %" if mode == "pct" else "Delta"
    description = (
        "Signed percent-relative separation of fast versus slow."
        if mode == "pct"
        else "Signed raw separation of fast versus slow."
    )
    return tuple(
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label=label,
            description=description,
        )
        for name in names
    )


def _resolve_trap_area_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("trap_area", **params)
    return tuple(
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Trap Area",
            description="Trap-area series for one configured faster/slower pair.",
        )
        for name in names
    )


def _resolve_percent_span_angle_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("percent_span_angle", **params)
    return tuple(
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Percent Span Angle",
            description="Windowed percent-span angular orientation series.",
        )
        for name in names
    )


def _resolve_angle_momentum_output_signals(params: Mapping[str, Any]) -> tuple[OutputSignalSpec, ...]:
    names = get_construct_signal_names("angle_momentum", **params)
    return tuple(
        OutputSignalSpec(
            name=name,
            signal_type="signal",
            renderable=True,
            analysis_usable=True,
            label="Angle Momentum",
            description="Average signed angle change per bar over the configured lag window.",
        )
        for name in names
    )


