from __future__ import annotations

from leonardo.gui.chart.model import Series, SeriesStyle
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_OSCILLATOR,
    STUDY_FAMILY_OSCILLATOR,
    StudyComputationConfig,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_style import (
    HistoricalChartPanelStyleMixin,
)


class _Model:
    def __init__(self, series_by_key: dict[str, Series]) -> None:
        self._series_by_key = dict(series_by_key)

    def oscillator(self, key: str) -> Series | None:
        return self._series_by_key.get(key)


class _Workspace:
    def __init__(self, series_by_key: dict[str, Series]) -> None:
        self.model = _Model(series_by_key)


class _Registry:
    def __init__(self) -> None:
        self.added: ChartStudyInstance | None = None

    def add(self, study: ChartStudyInstance) -> ChartStudyInstance:
        self.added = study
        return study


def _build_volume_study(*, volume_key: str, mean_key: str) -> ChartStudyInstance:
    return ChartStudyInstance(
        instance_id="volume-study",
        dataset_id="demo",
        pane_target=PANE_TARGET_OSCILLATOR,
        display_name="Volume",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_OSCILLATOR,
            tool_key="volume",
            params={"period": 20},
        ),
        runtime=ChartStudyRuntimeState(render_keys=[volume_key, mean_key]),
    )


def _build_style_mixin(series_by_key: dict[str, Series]) -> HistoricalChartPanelStyleMixin:
    mixin = object.__new__(HistoricalChartPanelStyleMixin)
    mixin._workspace = _Workspace(series_by_key)
    mixin._study_registry = _Registry()
    mixin._study_is_renderable = lambda study: True
    return mixin


def test_volume_mean_final_panel_style_stays_line_when_workspace_style_is_stale() -> None:
    study_id = "volume-study"
    volume_key = f"volume__default__period-20|{study_id}|volume"
    mean_key = f"volume__default__period-20|{study_id}|volume_mean_20"
    study = _build_volume_study(volume_key=volume_key, mean_key=mean_key)

    incoming_series = [
        Series(key=volume_key, title="Volume", values=[100.0, 200.0], style=SeriesStyle()),
        Series(key=mean_key, title="Volume Mean", values=[None, 150.0], style=SeriesStyle()),
    ]
    stale_workspace_series = {
        volume_key: Series(
            key=volume_key,
            title="Volume",
            values=[100.0, 200.0],
            style=SeriesStyle(color="#22C55E", render_mode="histogram"),
        ),
        mean_key: Series(
            key=mean_key,
            title="Volume Mean",
            values=[None, 150.0],
            style=SeriesStyle(color="#06B6D4", render_mode="histogram"),
        ),
    }
    mixin = _build_style_mixin(stale_workspace_series)

    seeded = mixin._seed_study_style_from_series_and_defaults(
        study=study,
        series_list=incoming_series,
    )
    seeded_mean_style = seeded.style.signal_styles["volume_mean_20"]
    assert seeded_mean_style.color == "#06B6D4"
    assert seeded_mean_style.render_mode == "line"

    styled_series, fills = mixin._resolved_render_state_for_study(
        study=seeded,
        series_list=incoming_series,
    )
    assert fills is None

    line_keys = [series.key.rsplit("|", 1)[-1] for series in styled_series]
    assert line_keys == ["volume", "volume_mean_20"]

    styles_by_line = {
        series.key.rsplit("|", 1)[-1]: series.style
        for series in styled_series
    }
    assert styles_by_line["volume"].render_mode == "histogram"
    assert styles_by_line["volume_mean_20"].color == "#06B6D4"
    assert styles_by_line["volume_mean_20"].render_mode == "line"
