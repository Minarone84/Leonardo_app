from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.financial_tools.ft_specs import (
    OutputSignalSpec,
    ToolBehaviorSpec,
    ToolOutputSpec,
    ToolSpec,
)
from leonardo.gui.historical_chart.projection import HistoricalChartProjectionMixin
from leonardo.gui.historical_chart.session import AppliedStudyProjection, ChartDataSession, StoredStudyLine


class ProjectionHarness(HistoricalChartProjectionMixin):
    def __init__(self, timeline: list[int], *, resident_base: int = 0, resident_size: int | None = None) -> None:
        self._session = ChartDataSession()
        self._session.set_timeline(timeline)
        self._session.resident_base_index = resident_base
        self._session.resident_size = len(timeline) if resident_size is None else resident_size

    def _coerce_timeline_values(self, raw) -> list[int]:
        if raw is None:
            return []
        if isinstance(raw, pd.DataFrame):
            if "ts_ms" not in raw.columns:
                return []
            raw = raw["ts_ms"]
        elif isinstance(raw, dict):
            raw = raw.get("ts_ms", [])
        if isinstance(raw, pd.Series):
            raw = raw.tolist()
        elif isinstance(raw, pd.Index):
            raw = raw.tolist()
        elif hasattr(raw, "tolist") and not isinstance(raw, (str, bytes)):
            raw = raw.tolist()
        try:
            return [int(value) for value in list(raw)]
        except (TypeError, ValueError):
            return []


def test_explicit_result_time_wins_over_equal_length_position() -> None:
    harness = ProjectionHarness([1000, 2000, 3000, 4000])
    result = SimpleNamespace(time=pd.Series([3000, 1000, 4000, 2000]))

    aligned = harness._align_line_to_canonical_timeline(
        line_values=pd.Series([30.0, 10.0, 40.0, 20.0]),
        result=result,
    )

    assert list(aligned.index) == [1000, 2000, 3000, 4000]
    assert aligned.tolist() == [10.0, 20.0, 30.0, 40.0]


def test_explicit_timeline_partial_overlap_preserves_gaps_and_resident_projection() -> None:
    harness = ProjectionHarness([1000, 2000, 3000, 4000, 5000], resident_base=1, resident_size=3)
    result = SimpleNamespace(time=pd.Series([1000, 3000, 5000]))

    aligned = harness._align_line_to_canonical_timeline(
        line_values=pd.Series([10.0, 30.0, 50.0]),
        result=result,
    )
    study = AppliedStudyProjection(
        projection_key="study",
        tool_type="indicator",
        tool_key="fake",
        tool_title="Fake",
        display_name="Fake",
        params={},
        behavior={},
        output={},
        full_lines=[
            StoredStudyLine(
                key="line",
                title="Line",
                values=aligned,
                renderable=True,
                analysis_usable=True,
            )
        ],
    )

    projected = harness._build_projected_series_list(study=study)

    assert len(projected) == 1
    assert pd.isna(projected[0].values[0])
    assert projected[0].values[1] == 30.0
    assert pd.isna(projected[0].values[2])


def test_duplicate_explicit_timeline_keys_are_rejected() -> None:
    harness = ProjectionHarness([1000, 2000, 3000])
    result = SimpleNamespace(time=pd.Series([1000, 2000, 2000]))

    with pytest.raises(ValueError, match="duplicate timeline values"):
        harness._align_line_to_canonical_timeline(
            line_values=pd.Series([1.0, 2.0, 3.0]),
            result=result,
        )


def test_legacy_full_dataset_positional_fallback_when_no_timeline_metadata() -> None:
    harness = ProjectionHarness([1000, 2000, 3000])
    result = SimpleNamespace()

    aligned = harness._align_line_to_canonical_timeline(
        line_values=pd.Series([1.0, 2.0, 3.0]),
        result=result,
    )

    assert list(aligned.index) == [1000, 2000, 3000]
    assert aligned.tolist() == [1.0, 2.0, 3.0]


def test_mismatched_length_without_timeline_fails() -> None:
    harness = ProjectionHarness([1000, 2000, 3000])
    result = SimpleNamespace()

    with pytest.raises(ValueError, match="cannot be aligned"):
        harness._align_line_to_canonical_timeline(
            line_values=pd.Series([1.0, 2.0]),
            result=result,
        )


def test_non_renderable_analysis_usable_output_is_retained_but_not_projected() -> None:
    harness = ProjectionHarness([1000, 2000, 3000])
    spec = ToolSpec(
        key="fake_tool",
        title="Fake Tool",
        kind="indicator",
        data_inputs=(),
        params=(),
        output_names=("render_line", "analysis_line"),
        behavior=ToolBehaviorSpec(output_mode="overlay", chart_renderable=True),
        output=ToolOutputSpec(
            structure="line-series",
            output_names=("render_line", "analysis_line"),
            signals=(
                OutputSignalSpec(name="render_line", renderable=True, analysis_usable=True),
                OutputSignalSpec(name="analysis_line", renderable=False, analysis_usable=True),
            ),
        ),
    )
    result = SimpleNamespace(
        lines=[
            SimpleNamespace(key="render_line", title="Render", values=pd.Series([1.0, 2.0, 3.0])),
            SimpleNamespace(key="analysis_line", title="Analysis", values=pd.Series([10.0, 20.0, 30.0])),
        ],
        time=pd.Series([1000, 2000, 3000]),
        params={},
        title="Fake Tool",
    )

    study = harness._store_applied_study_projection(
        projection_key="fake_tool|default",
        result=result,
        spec=spec,
        tool_type="indicator",
        tool_key="fake_tool",
        tool_title="Fake Tool",
        effective_params={},
    )

    assert [line.key for line in study.full_lines] == ["render_line"]
    assert [line.key for line in study.full_analysis_source_lines] == ["analysis_line"]
    assert len(study.projected_series_list) == 1
    assert all("analysis_line" not in series.key for series in study.projected_series_list)
