from __future__ import annotations

from copy import deepcopy

from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KIND,
    compare_source_ohlcv_snapshots,
)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": SOURCE_OHLCV_PROVENANCE_KIND,
        "captured_at_ms": 1_700_000_000_000,
        "captured_at_utc": "2023-11-14T22:13:20Z",
        "dataset": {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "30m",
        },
        "validation": {
            "status": "ok",
            "quality_validation_status": "ok",
            "csv_fingerprint": {
                "algorithm": "file_stat",
                "size_bytes": 123,
                "modified_at_ms": 1_700_000_000_000,
                "sha256": None,
                "sha256_status": "not_computed",
            },
        },
        "fingerprint": {
            "algorithm": "file_stat",
            "size_bytes": 123,
            "modified_at_ms": 1_700_000_000_000,
            "sha256": "abc",
            "sha256_status": "computed",
        },
        "source_correction": {
            "is_modified": False,
            "needs_source_recheck": False,
            "record_count": 0,
            "records": [],
        },
    }


def test_compare_source_ohlcv_snapshots_reports_current_for_matching_snapshots() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "current"
    assert report.matches is True
    assert report.reasons == ()
    assert report.actionable is False


def test_compare_source_ohlcv_snapshots_reports_unknown_when_recorded_snapshot_is_missing() -> None:
    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=None,
        current_snapshot=_snapshot(),
    )

    assert report.status == "unknown"
    assert report.matches is False
    assert "missing_recorded_source_ohlcv_snapshot" in report.reasons
    assert report.actionable is True


def test_compare_source_ohlcv_snapshots_detects_validation_status_change() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)
    current["validation"]["status"] = "modified"  # type: ignore[index]

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "source_drift"
    assert "source_validation_status_changed" in report.reasons


def test_compare_source_ohlcv_snapshots_detects_validation_fingerprint_change() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)
    current["validation"]["csv_fingerprint"]["size_bytes"] = 456  # type: ignore[index]

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "source_drift"
    assert "source_validation_fingerprint_changed" in report.reasons


def test_compare_source_ohlcv_snapshots_detects_csv_fingerprint_change() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)
    current["fingerprint"]["sha256"] = "def"  # type: ignore[index]

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "source_drift"
    assert "source_csv_fingerprint_changed" in report.reasons


def test_compare_source_ohlcv_snapshots_detects_source_correction_provenance_change() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)
    current["source_correction"]["record_count"] = 1  # type: ignore[index]
    current["source_correction"]["records"] = [  # type: ignore[index]
        {"ts_ms": 1000, "issue_code": "open_out_of_bounds"}
    ]

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "source_drift"
    assert "source_correction_record_count_changed" in report.reasons
    assert "source_correction_records_changed" in report.reasons


def test_compare_source_ohlcv_snapshots_ignores_capture_timestamp_difference() -> None:
    recorded = _snapshot()
    current = deepcopy(recorded)
    current["captured_at_ms"] = 1_700_000_060_000
    current["captured_at_utc"] = "2023-11-14T22:14:20Z"

    report = compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded,
        current_snapshot=current,
    )

    assert report.status == "current"
    assert report.matches is True
    assert report.reasons == ()
