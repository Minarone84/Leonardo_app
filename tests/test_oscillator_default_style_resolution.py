from __future__ import annotations

from leonardo.gui.chart.study_style_defaults import build_default_series_style
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_OSCILLATOR,
    STUDY_FAMILY_OSCILLATOR,
    StudyComputationConfig,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_oscillator_policy import (
    HistoricalChartPanelOscillatorPolicyMixin,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_style import (
    HistoricalChartPanelStyleMixin,
)


def test_dynamic_oscillator_signal_names_resolve_chart_defaults() -> None:
    cases = [
        ("rsi", "rsi_14", "#A855F7", "solid", "line"),
        ("arsi", "arsi_14_rma", "#8B5CF6", "solid", "line"),
        ("arsi", "arsi_signal_14_rma_14_ema", "#FF5D00", "solid", "line"),
        ("mfi", "mfi_14", "#14B8A6", "solid", "line"),
        ("smi", "smi_14_3", "#06B6D4", "solid", "line"),
        ("smi", "smi_signal_14_3", "#F59E0B", "solid", "line"),
        ("tdi", "tdirsi_fast_ma_14_34_2_7_ema_rma", "#22C55E", "solid", "line"),
        ("tdi", "tdirsi_slow_ma_14_34_2_7_ema_rma", "#EF4444", "solid", "line"),
        ("tdi", "tdirsi_up_14_34_2_7_ema_rma", "#A855F7", "dashed", "line"),
        ("tdi", "tdirsi_dn_14_34_2_7_ema_rma", "#A855F7", "dashed", "line"),
        ("tdi", "tdirsi_mid_14_34_2_7_ema_rma", "#F59E0B", "solid", "line"),
        ("tdirsi", "tdirsi_fast_ma_14_34_2_7_ema_rma", "#22C55E", "solid", "line"),
        ("volume", "volume_mean_20", "#06B6D4", "solid", "line"),
    ]

    for study_key, signal_name, color, line_style, render_mode in cases:
        style = build_default_series_style(
            study_key=study_key,
            signal_name=signal_name,
        )
        assert style.color == color
        assert style.line_style == line_style
        assert style.render_mode == render_mode


def test_panel_signal_style_resolution_uses_dynamic_defaults() -> None:
    mixin = object.__new__(HistoricalChartPanelStyleMixin)

    signal_style = mixin._default_signal_style_for_line_key(
        defaults_study_key="tdi",
        line_key="tdirsi_up_14_34_2_7_ema_rma",
        show_label=True,
        show_value=True,
    )

    assert signal_style is not None
    assert signal_style.color == "#A855F7"
    assert signal_style.line_style == "dashed"


def test_tdirsi_fill_policy_targets_dynamic_runtime_band_signals() -> None:
    mixin = object.__new__(HistoricalChartPanelOscillatorPolicyMixin)
    study = ChartStudyInstance(
        instance_id="tdi-study",
        dataset_id="demo",
        pane_target=PANE_TARGET_OSCILLATOR,
        display_name="TDI RSI",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_OSCILLATOR,
            tool_key="tdirsi",
            params={
                "period": 14,
                "band_length": 34,
                "fast_len": 2,
                "slow_len": 7,
                "fast_smo": "ema",
                "slow_smo": "rma",
            },
        ),
        runtime=ChartStudyRuntimeState(
            render_keys=[
                "tdirsi|demo|tdirsi_fast_ma_14_34_2_7_ema_rma",
                "tdirsi|demo|tdirsi_slow_ma_14_34_2_7_ema_rma",
                "tdirsi|demo|tdirsi_up_14_34_2_7_ema_rma",
                "tdirsi|demo|tdirsi_dn_14_34_2_7_ema_rma",
                "tdirsi|demo|tdirsi_mid_14_34_2_7_ema_rma",
            ],
        ),
    )

    policy = mixin._default_oscillator_visual_policy_for_study(study)

    assert policy is not None
    fills = policy.get("fills")
    assert fills == [
        {
            "series_a": "tdirsi_up_14_34_2_7_ema_rma",
            "series_b": "tdirsi_dn_14_34_2_7_ema_rma",
            "color": "#60A5FA",
            "opacity": 0.10,
            "visible": True,
        }
    ]
