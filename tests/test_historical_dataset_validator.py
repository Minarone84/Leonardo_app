from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.data.historical.validator import HistoricalDatasetValidator


HEADER = ("ts_ms", "open", "high", "low", "close", "volume")


def _write_csv(path: Path, rows: list[tuple[object, ...]], header: tuple[str, ...] = HEADER) -> Path:
    lines = [",".join(header)]
    lines.extend(",".join(str(value) for value in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _validate(path: Path, timeframe: str = "1m"):
    return HistoricalDatasetValidator(timeframe).validate(path)


def _messages(report) -> list[str]:
    return [issue.message for issue in report.issues]


def _only_issue(report):
    assert len(report.issues) == 1
    return report.issues[0]


def _issue_with_message(report, message: str):
    matches = [issue for issue in report.issues if issue.message == message]
    assert len(matches) == 1
    return matches[0]


def test_valid_minimal_ohlcv_accepts_extra_reordered_columns_and_equality_edges(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(
        path,
        rows=[
            ("x", 0, 1, 1, 1, 1, 0),
            ("x", 10, 2, 1, 2, 1, 60_000),
            ("x", 20, 5, 4, 5, 5, 120_000),
        ],
        header=("extra", "volume", "close", "low", "high", "open", "ts_ms"),
    )

    report = _validate(path)

    assert report.status == "ok"
    assert report.row_count == 3
    assert report.issues == []


@pytest.mark.parametrize("missing_column", HistoricalDatasetValidator.REQUIRED_COLUMNS)
def test_missing_required_columns_fail_by_name(tmp_path: Path, missing_column: str) -> None:
    header = tuple(column for column in HEADER if column != missing_column)
    row_values = {
        "ts_ms": 0,
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 1.5,
        "volume": 10,
    }
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[tuple(row_values[column] for column in header)], header=header)

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 0
    assert _messages(report) == [f"missing column: {missing_column}"]
    issue = _only_issue(report)
    assert issue.code == "missing_column"
    assert issue.column == missing_column
    assert issue.row_index is None
    assert issue.ts_ms is None
    assert issue.repairable is False


def test_empty_file_reports_missing_csv_header(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    path.write_text("", encoding="utf-8")

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 0
    assert _messages(report) == ["missing CSV header"]
    issue = _only_issue(report)
    assert issue.code == "missing_csv_header"
    assert issue.repairable is False


def test_header_only_csv_reports_empty_dataset(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[])

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 0
    assert _messages(report) == ["empty dataset"]
    issue = _only_issue(report)
    assert issue.code == "empty_dataset"
    assert issue.repairable is False


@pytest.mark.parametrize(
    ("row", "expected_column", "expected_ts_ms"),
    [
        (("0", "bad", "2", "1", "1.5", "10"), "open", 0),
        (("0", "", "2", "1", "1.5", "10"), "open", 0),
        (("not-a-timestamp", "1", "2", "1", "1.5", "10"), "ts_ms", None),
    ],
)
def test_numeric_parse_errors_are_reported_per_row(
    tmp_path: Path,
    row: tuple[str, ...],
    expected_column: str,
    expected_ts_ms: int | None,
) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[row])

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 1
    assert any(message.startswith("parse error at row 0:") for message in _messages(report))
    issue = _only_issue(report)
    assert issue.code == "parse_error"
    assert issue.row_index == 0
    assert issue.column == expected_column
    assert issue.ts_ms == expected_ts_ms


@pytest.mark.parametrize(
    "row",
    [
        ("0", "nan", "2", "1", "1.5", "10"),
        ("0", "1", "inf", "1", "1.5", "10"),
        ("0", "1", "2", "-inf", "1.5", "10"),
    ],
)
def test_non_finite_ohlcv_values_are_rejected(tmp_path: Path, row: tuple[str, ...]) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[row])

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 1
    assert "non-finite values at row 0" in _messages(report)
    issue = _only_issue(report)
    assert issue.code == "non_finite_values"
    assert issue.row_index == 0
    assert issue.ts_ms == 0
    assert issue.repairable is True


@pytest.mark.parametrize(
    ("row", "expected_message", "expected_code", "expected_column"),
    [
        (("0", "5", "4", "6", "5", "10"), "low > high at row 0", "low_greater_than_high", None),
        (("0", "0", "2", "1", "1.5", "10"), "open out of bounds at row 0", "open_out_of_bounds", "open"),
        (("0", "3", "2", "1", "1.5", "10"), "open out of bounds at row 0", "open_out_of_bounds", "open"),
        (("0", "1.5", "2", "1", "0", "10"), "close out of bounds at row 0", "close_out_of_bounds", "close"),
        (("0", "1.5", "2", "1", "3", "10"), "close out of bounds at row 0", "close_out_of_bounds", "close"),
    ],
)
def test_ohlc_envelope_failures_are_reported(
    tmp_path: Path,
    row: tuple[str, ...],
    expected_message: str,
    expected_code: str,
    expected_column: str | None,
) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[row])

    report = _validate(path)

    assert report.status == "error"
    assert report.row_count == 1
    assert expected_message in _messages(report)
    issue = _issue_with_message(report, expected_message)
    assert issue.code == expected_code
    assert issue.row_index == 0
    assert issue.ts_ms == 0
    assert issue.column == expected_column
    assert issue.repairable is True


def test_negative_volume_fails(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[(0, 1, 2, 1, 1.5, -0.1)])

    report = _validate(path)

    assert report.status == "error"
    assert "negative volume at row 0" in _messages(report)
    issue = _only_issue(report)
    assert issue.code == "negative_volume"
    assert issue.row_index == 0
    assert issue.ts_ms == 0
    assert issue.column == "volume"
    assert issue.repairable is True


def test_zero_volume_passes(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[(0, 1, 2, 1, 1.5, 0)])

    report = _validate(path)

    assert report.status == "ok"
    assert report.issues == []


@pytest.mark.parametrize(
    "rows",
    [
        [(0, 1, 2, 1, 1.5, 10), (0, 1, 2, 1, 1.5, 10)],
        [(60_000, 1, 2, 1, 1.5, 10), (0, 1, 2, 1, 1.5, 10)],
    ],
)
def test_duplicate_or_decreasing_timestamps_fail_as_non_increasing(tmp_path: Path, rows: list[tuple[int, ...]]) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=rows)

    report = _validate(path)

    assert report.status == "error"
    assert "non-increasing timestamp at row 1" in _messages(report)
    issue = _issue_with_message(report, "non-increasing timestamp at row 1")
    assert issue.code == "non_increasing_timestamp"
    assert issue.row_index == 1
    assert issue.column == "ts_ms"
    assert issue.repairable is True


def test_sorted_increasing_timestamps_pass(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(
        path,
        rows=[
            (0, 1, 2, 1, 1.5, 10),
            (60_000, 1, 2, 1, 1.5, 10),
            (120_000, 1, 2, 1, 1.5, 10),
        ],
    )

    report = _validate(path)

    assert report.status == "ok"
    assert report.issues == []


def test_fixed_timeframe_gap_is_warning_with_count_only(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[(0, 1, 2, 1, 1.5, 10), (120_000, 1, 2, 1, 1.5, 10)])

    report = _validate(path, timeframe="1m")

    assert report.status == "warning"
    assert _messages(report) == ["1 timeframe gaps detected"]
    issue = _only_issue(report)
    assert issue.severity == "warning"
    assert issue.code == "gap_count"
    assert issue.row_index is None
    assert issue.ts_ms is None


def test_month_timeframe_skips_exact_continuity_but_keeps_validation_warning(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(
        path,
        rows=[
            (1_609_459_200_000, 1, 2, 1, 1.5, 10),
            (1_612_137_600_000, 1, 2, 1, 1.5, 10),
            (1_614_556_800_000, 1, 2, 1, 1.5, 10),
        ],
    )

    report = _validate(path, timeframe="1M")

    assert report.status == "warning"
    assert _messages(report) == [
        "exact timeframe continuity check skipped for variable-length timeframe: 1M"
    ]
    issue = _only_issue(report)
    assert issue.severity == "warning"
    assert issue.code == "variable_timeframe_continuity_skipped"
    assert issue.repairable is False


def test_row_numbers_are_zero_based_data_rows_excluding_header(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[(0, 1, 2, 1, 1.5, 10), (60_000, 0, 2, 1, 1.5, 10)])

    report = _validate(path)

    assert report.status == "error"
    assert "open out of bounds at row 1" in _messages(report)
    issue = _only_issue(report)
    assert issue.code == "open_out_of_bounds"
    assert issue.row_index == 1
    assert issue.ts_ms == 60_000
    assert issue.column == "open"


@pytest.mark.parametrize(
    "row",
    [
        (0, -2, -1, -3, -2, 10),
        (0, 0, 0, 0, 0, 10),
    ],
)
def test_zero_and_negative_prices_are_currently_allowed_when_envelope_passes(
    tmp_path: Path,
    row: tuple[int, ...],
) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[row])

    report = _validate(path)

    assert report.status == "ok"
    assert report.issues == []


def test_timestamp_scale_is_not_directly_validated_for_single_row(tmp_path: Path) -> None:
    path = tmp_path / "candles.csv"
    _write_csv(path, rows=[(60, 1, 2, 1, 1.5, 10)])

    report = _validate(path)

    assert report.status == "ok"
    assert report.issues == []
