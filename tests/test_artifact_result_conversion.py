from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from leonardo.data.historical.artifact_result_conversion import result_to_save_dataframe


@dataclass(frozen=True)
class _Line:
    key: str
    values: pd.Series


@dataclass(frozen=True)
class _Result:
    index: pd.Index
    lines: tuple[_Line, ...] = ()
    time: pd.Series | None = None
    timeframe: pd.Series | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def test_result_to_save_dataframe_preserves_boolean_output() -> None:
    index = pd.RangeIndex(3)
    result = _Result(
        index=index,
        time=pd.Series([1000, 2000, 3000], index=index),
        timeframe=pd.Series(["1h", "1h", "1h"], index=index),
        lines=(
            _Line(
                key="state",
                values=pd.Series([True, False, True], index=index, dtype="bool"),
            ),
        ),
    )

    out = result_to_save_dataframe(result)

    assert list(out.columns) == ["time", "timeframe", "state"]
    assert pd.api.types.is_bool_dtype(out["state"])
    assert out["state"].tolist() == [True, False, True]


def test_result_to_save_dataframe_preserves_numeric_gaps() -> None:
    index = pd.RangeIndex(3)
    result = _Result(
        index=index,
        time=pd.Series([1000, 2000, 3000], index=index),
        lines=(
            _Line(
                key="value",
                values=pd.Series([1.5, float("nan"), 3.25], index=index),
            ),
        ),
    )

    out = result_to_save_dataframe(result, default_timeframe="1h")

    assert list(out.columns) == ["time", "value", "timeframe"]
    assert str(out["value"].dtype) == "float32"
    assert out["value"].iloc[0] == 1.5
    assert pd.isna(out["value"].iloc[1])
    assert out["value"].iloc[2] == 3.25
    assert out["timeframe"].tolist() == ["1h", "1h", "1h"]


def test_result_to_save_dataframe_preserves_multi_line_order() -> None:
    index = pd.RangeIndex(2)
    result = _Result(
        index=index,
        time=pd.Series([1000, 2000], index=index),
        timeframe=pd.Series(["1h", "1h"], index=index),
        lines=(
            _Line(key="first", values=pd.Series([1, 2], index=index)),
            _Line(key="second", values=pd.Series([3, 4], index=index)),
        ),
    )

    out = result_to_save_dataframe(result)

    assert list(out.columns) == ["time", "timeframe", "first", "second"]
    assert out["first"].tolist() == [1.0, 2.0]
    assert out["second"].tolist() == [3.0, 4.0]


def test_result_to_save_dataframe_preserves_labeled_rows() -> None:
    result = _Result(
        index=pd.RangeIndex(0),
        metadata={
            "labeled_rows": [
                {"ts_ms": 1000, "label": "alpha", "score": 1.0},
                {"ts_ms": 2000, "label": "beta", "score": 2.0},
            ],
        },
    )

    out = result_to_save_dataframe(result)

    assert list(out.columns) == ["ts_ms", "label", "score"]
    assert out.to_dict("records") == [
        {"ts_ms": 1000, "label": "alpha", "score": 1.0},
        {"ts_ms": 2000, "label": "beta", "score": 2.0},
    ]


def test_result_to_save_dataframe_uses_range_time_fallback() -> None:
    index = pd.RangeIndex(2)
    result = _Result(
        index=index,
        lines=(
            _Line(key="value", values=pd.Series([10, 20], index=index)),
        ),
    )

    out = result_to_save_dataframe(result, default_timeframe="30m")

    assert out["time"].tolist() == [0, 1]
    assert out["timeframe"].tolist() == ["30m", "30m"]


def test_result_to_save_dataframe_does_not_filter_utility_outputs() -> None:
    index = pd.RangeIndex(2)
    result = _Result(
        index=index,
        time=pd.Series([1000, 2000], index=index),
        lines=(
            _Line(key="renderable_value", values=pd.Series([1.0, 2.0], index=index)),
            _Line(key="utility_state", values=pd.Series(["bull", "bear"], index=index)),
        ),
    )

    out = result_to_save_dataframe(result)

    assert "renderable_value" in out.columns
    assert "utility_state" in out.columns
    assert out["utility_state"].tolist() == ["bull", "bear"]


def test_chart_and_data_save_paths_use_shared_conversion_helper() -> None:
    root = Path(__file__).resolve().parents[1]

    chart_projection = (
        root / "src" / "leonardo" / "gui" / "historical_chart" / "projection.py"
    ).read_text(encoding="utf-8")
    calculation_service = (
        root / "src" / "leonardo" / "data" / "historical" / "artifact_calculation_service.py"
    ).read_text(encoding="utf-8")
    import_line = "from leonardo.data.historical.artifact_result_conversion import result_to_save_dataframe"

    assert import_line in chart_projection
    assert import_line in calculation_service
    assert "result_to_save_dataframe(result" in chart_projection
    assert "result_to_save_dataframe(result" in calculation_service
