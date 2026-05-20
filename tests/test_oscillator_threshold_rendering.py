from __future__ import annotations

import pytest

from leonardo.gui.chart.model import Series, SeriesStyle
from leonardo.gui.chart.rendering.oscillator_policy_painter import OscillatorPolicyPainterMixin
from leonardo.gui.chart.rendering.oscillator_surface_painter import OscillatorSurfacePaintMixin


class _ThresholdRenderer(OscillatorSurfacePaintMixin, OscillatorPolicyPainterMixin):
    pass


def _series() -> Series:
    return Series(
        key="rsi|rsi",
        title="RSI",
        values=[],
        style=SeriesStyle(color="#123456", line_width=2),
    )


def _renderer(series: Series) -> _ThresholdRenderer:
    renderer = object.__new__(_ThresholdRenderer)
    renderer._series_list = [series]
    renderer._visual_policy = {
        "threshold_line_color": {
            "target_signal": "__primary__",
            "lower_value": 30,
            "upper_value": 70,
            "oversold_color": "#22C55E",
            "neutral_color": "#94A3B8",
            "overbought_color": "#EF4444",
        }
    }
    return renderer


def _pen_color(renderer: _ThresholdRenderer, series: Series, value: float) -> str:
    return renderer._pen_for_series_value(series, value).color().name().upper()


def test_threshold_policy_neutral_values_use_series_style_color() -> None:
    series = _series()
    renderer = _renderer(series)

    assert _pen_color(renderer, series, 50) == "#123456"
    assert _pen_color(renderer, series, 70) == "#EF4444"
    assert _pen_color(renderer, series, 30) == "#22C55E"


@pytest.mark.parametrize(
    ("v1", "v2", "threshold", "expected_colors"),
    [
        (69.0, 71.0, 70.0, ["#123456", "#EF4444"]),
        (71.0, 69.0, 70.0, ["#EF4444", "#123456"]),
        (31.0, 29.0, 30.0, ["#123456", "#22C55E"]),
        (29.0, 31.0, 30.0, ["#22C55E", "#123456"]),
    ],
)
def test_threshold_aware_segments_split_at_crossing(
    v1: float,
    v2: float,
    threshold: float,
    expected_colors: list[str],
) -> None:
    series = _series()
    renderer = _renderer(series)
    y_to_px = lambda value: 100.0 - value
    captured: list[tuple[float, float, str]] = []

    def capture_line_path(_p: object, path, pen) -> None:
        start = path.elementAt(0)
        end = path.elementAt(1)
        captured.append((float(start.x), float(end.x), pen.color().name().upper()))

    renderer._draw_line_path = capture_line_path
    renderer._draw_threshold_aware_line_segment(
        object(),
        series=series,
        x1=0.0,
        y1=y_to_px(v1),
        v1=v1,
        x2=10.0,
        y2=y_to_px(v2),
        v2=v2,
        y_to_px=y_to_px,
    )

    assert captured == [
        (pytest.approx(0.0), pytest.approx(5.0), expected_colors[0]),
        (pytest.approx(5.0), pytest.approx(10.0), expected_colors[1]),
    ]
    segments = renderer._threshold_line_segment_points(
        series=series,
        x1=0.0,
        y1=y_to_px(v1),
        v1=v1,
        x2=10.0,
        y2=y_to_px(v2),
        v2=v2,
        y_to_px=y_to_px,
    )
    assert segments[0][1][1] == pytest.approx(y_to_px(threshold))
    assert segments[1][0][1] == pytest.approx(y_to_px(threshold))
