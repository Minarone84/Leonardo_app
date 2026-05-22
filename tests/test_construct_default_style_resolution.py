from __future__ import annotations

from leonardo.gui.chart.study_style_defaults import (
    build_default_series_style,
    get_signal_style_defaults,
    get_study_style_defaults,
)


EXPECTED_CONSTRUCT_DEFAULTS = {
    "derivative": "#FF9F1C",
    "angle": "#00E5FF",
    "braids": "#B967FF",
    "braid_instability": "#FF3DCE",
    "delta": "#FFF200",
    "trap_area": "#FF6B35",
    "percent_span_angle": "#39FF14",
    "angle_momentum": "#4DA3FF",
}


def test_construct_defaults_resolve_to_high_contrast_color_and_width() -> None:
    for study_key, expected_color in EXPECTED_CONSTRUCT_DEFAULTS.items():
        defaults = get_signal_style_defaults(
            study_key=study_key,
            signal_name=f"{study_key}_runtime_output",
        )
        style = build_default_series_style(
            study_key=study_key,
            signal_name=f"{study_key}_runtime_output",
        )

        assert defaults is not None
        assert defaults.color == expected_color
        assert defaults.line_width == 1
        assert style.color == expected_color
        assert style.line_width == 1


def test_dynamic_binning_has_no_chart_style_default() -> None:
    defaults = get_study_style_defaults("dynamic_binning")
    signal_defaults = get_signal_style_defaults(
        study_key="dynamic_binning",
        signal_name="dynamic_binning_runtime_output",
    )
    style = build_default_series_style(
        study_key="dynamic_binning",
        signal_name="dynamic_binning_runtime_output",
    )

    assert defaults.signal_defaults == {}
    assert signal_defaults is None
    assert style.color is None
