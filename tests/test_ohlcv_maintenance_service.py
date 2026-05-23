from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.ohlcv_maintenance import HistoricalOhlcvMaintenanceService
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


class _InvalidateTrackingDatasetService:
    def __init__(self) -> None:
        self.invalidated: list[DatasetId] = []

    def list_dataset_ids(self) -> list[DatasetId]:
        return []

    def invalidate_dataset_cache(self, dataset_id: DatasetId) -> bool:
        self.invalidated.append(dataset_id)
        return True


def _service(tmp_path: Path) -> HistoricalOhlcvMaintenanceService:
    return HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=HistoricalDatasetService(tmp_path),
    )


def _candles() -> list[Candle]:
    return [
        Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(1_609_462_800_000, 1.5, 2.5, 1.0, 2.0, 11.0),
    ]


def _write_ohlcv(tmp_path: Path, *, timeframe: str = "1h") -> Path:
    market = canonicalize("bybit", "linear", "LINKUSDT", timeframe)
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    CsvOHLCVStore().write_atomic(csv_path, _candles(), market=market)
    return csv_path


def test_maintenance_service_lists_canonical_ohlcv_datasets(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, timeframe="1m")
    _write_ohlcv(tmp_path, timeframe="1M")

    datasets = _service(tmp_path).list_ohlcv_datasets()

    assert [(item.timeframe, item.storage_segment) for item in datasets] == [("1m", "1m"), ("1M", "1mo")]


def test_maintenance_service_inspects_valid_metadata_without_mutation(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path)
    metadata_path = metadata_path_for_csv(csv_path)

    report = _service(tmp_path).inspect_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.csv_exists is True
    assert report.metadata_exists is True
    assert report.metadata_status == "valid"
    assert report.metadata_valid is True
    assert report.row_count == 2
    assert report.manifest is not None
    assert report.manifest.market_timeframe == "1h"
    assert metadata_path.exists()


def test_maintenance_service_reports_missing_metadata_without_rebuild(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path)
    metadata_path = metadata_path_for_csv(csv_path)
    metadata_path.unlink()

    report = _service(tmp_path).inspect_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.metadata_exists is False
    assert report.metadata_status == "missing"
    assert report.metadata_valid is False
    assert report.row_count == 2
    assert not metadata_path.exists()


def test_maintenance_service_reports_unreadable_metadata_without_rebuild(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path)
    metadata_path = metadata_path_for_csv(csv_path)
    metadata_path.write_text("{not-json", encoding="utf-8")

    report = _service(tmp_path).inspect_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.metadata_exists is True
    assert report.metadata_status == "unreadable"
    assert report.metadata_error
    assert metadata_path.read_text(encoding="utf-8") == "{not-json"


def test_maintenance_service_validates_ohlcv_bounds(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n"
        "60000,10,5,1,2,100\n",
        encoding="utf-8",
    )

    report = _service(tmp_path).validate_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    assert report.status == "error"
    assert report.row_count == 1
    assert report.metadata_updated is True
    assert any(issue.message == "open out of bounds at row 0" for issue in report.issues)
    payload = json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    assert payload["validation"]["status"] == "error"
    assert payload["validation"]["validator"] == "HistoricalDatasetValidator"
    assert payload["validation"]["row_count"] == 1
    assert payload["validation"]["issue_count"] == 1
    assert payload["validation"]["error_count"] == 1
    assert "open out of bounds" in payload["validation"]["message"]


def test_maintenance_service_plans_timestamp_anchored_repair_without_metadata_mutation(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    CsvOHLCVStore().write_atomic(
        csv_path,
        [
            Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
            Candle(120_000, 10.0, 5.0, 1.0, 2.0, 11.0),
        ],
        market=market,
    )
    metadata_path = metadata_path_for_csv(csv_path)
    before_metadata = metadata_path.read_text(encoding="utf-8")

    plan = _service(tmp_path).plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    assert plan.status == "error"
    assert plan.actionable is True
    assert plan.row_count == 2
    assert len(plan.ranges) == 1
    repair_range = plan.ranges[0]
    assert repair_range.start_ts_ms == 0
    assert repair_range.end_ts_ms == 240_000
    assert repair_range.estimated_bars == 5
    assert repair_range.rows == (1,)
    assert repair_range.issue_count == 1
    assert "open out of bounds at row 1" in repair_range.reason
    assert plan.csv_fingerprint_size_bytes is not None
    assert plan.csv_fingerprint_modified_at_ms is not None
    assert metadata_path.read_text(encoding="utf-8") == before_metadata


def test_maintenance_service_repair_plan_keeps_unanchored_issues_read_only(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("ts_ms,open\n60000,1\n", encoding="utf-8")

    plan = _service(tmp_path).plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    assert plan.status == "error"
    assert plan.actionable is False
    assert plan.ranges == ()
    assert any("missing column: high" in issue.message for issue in plan.issues)
    assert any("no row timestamp anchor" in warning for warning in plan.warnings)
    assert not metadata_path_for_csv(csv_path).exists()


def test_maintenance_service_executes_repair_plan_through_downloader_and_stamps_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    CsvOHLCVStore().write_atomic(
        csv_path,
        [
            Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
            Candle(120_000, 10.0, 5.0, 1.0, 2.0, 11.0),
        ],
        market=market,
    )
    dataset_service = _InvalidateTrackingDatasetService()
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=dataset_service,  # type: ignore[arg-type]
    )
    plan = service.plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1m"))
    requests: list[tuple[int | None, int | None]] = []

    class _FakeDownloader:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "historical"

        async def run_with_job_id(self, _ctx, req, job_id: str):
            requests.append((req.start_ms, req.end_ms))
            CsvOHLCVStore().write_atomic(
                csv_path,
                [
                    Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
                    Candle(120_000, 2.0, 5.0, 1.0, 2.5, 11.0),
                ],
                market=market,
            )
            return SimpleNamespace(total_rows=2, file_path=csv_path, job_id=job_id)

    monkeypatch.setattr("leonardo.data.historical.ohlcv_maintenance.HistoricalDownloader", _FakeDownloader)

    report = asyncio.run(
        service.execute_ohlcv_repair(
            object(),
            DatasetId("bybit", "linear", "LINKUSDT", "1m"),
            plan,
        )
    )

    assert requests == [(plan.ranges[0].start_ts_ms, plan.ranges[0].end_ts_ms)]
    assert report.action == "execute_ohlcv_repair"
    assert report.ranges_requested == 1
    assert report.ranges_completed == 1
    assert report.final_row_count == 2
    assert report.validation_status == "ok"
    assert report.metadata_updated is True
    assert report.cache_invalidated is True
    assert report.range_results[0].estimated_bars == plan.ranges[0].estimated_bars
    assert report.range_results[0].downloaded_bars is None
    assert dataset_service.invalidated[-1] == DatasetId("bybit", "linear", "LINKUSDT", "1m")
    payload = json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    assert payload["validation"]["status"] == "ok"


def test_maintenance_service_execute_repair_stamps_failed_post_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    CsvOHLCVStore().write_atomic(
        csv_path,
        [
            Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
            Candle(120_000, 10.0, 5.0, 1.0, 2.0, 11.0),
        ],
        market=market,
    )
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )
    plan = service.plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    class _FakeDownloader:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "historical"

        async def run_with_job_id(self, _ctx, _req, job_id: str):
            CsvOHLCVStore().write_atomic(
                csv_path,
                [
                    Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
                    Candle(120_000, 10.0, 5.0, 1.0, 2.0, 11.0),
                ],
                market=market,
            )
            return SimpleNamespace(total_rows=2, file_path=csv_path, job_id=job_id)

    monkeypatch.setattr("leonardo.data.historical.ohlcv_maintenance.HistoricalDownloader", _FakeDownloader)

    report = asyncio.run(
        service.execute_ohlcv_repair(
            object(),
            DatasetId("bybit", "linear", "LINKUSDT", "1m"),
            plan,
        )
    )

    assert report.validation_status == "error"
    assert report.metadata_updated is True
    assert any(issue.message == "open out of bounds at row 1" for issue in report.validation_issues)
    payload = json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    assert payload["validation"]["status"] == "error"


def test_maintenance_service_execute_repair_rejects_mismatched_plan(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, timeframe="1h")
    service = _service(tmp_path)
    plan = service.plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1h"))
    mismatched_plan = plan.__class__(
        dataset=plan.dataset.__class__(
            dataset_id=DatasetId("bybit", "linear", "LINKUSDT", "1m"),
            exchange=plan.dataset.exchange,
            market_type=plan.dataset.market_type,
            symbol=plan.dataset.symbol,
            timeframe="1m",
            storage_segment="1m",
            partition_path=plan.dataset.partition_path,
            csv_path=plan.dataset.csv_path,
            metadata_path=plan.dataset.metadata_path,
            validation_status=plan.dataset.validation_status,
        ),
        status=plan.status,
        actionable=True,
        message=plan.message,
        row_count=plan.row_count,
        ranges=(),
        issues=plan.issues,
        warnings=plan.warnings,
        csv_fingerprint_size_bytes=plan.csv_fingerprint_size_bytes,
        csv_fingerprint_modified_at_ms=plan.csv_fingerprint_modified_at_ms,
    )

    try:
        asyncio.run(
            service.execute_ohlcv_repair(
                object(),
                DatasetId("bybit", "linear", "LINKUSDT", "1h"),
                mismatched_plan,  # type: ignore[arg-type]
            )
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("execute_ohlcv_repair should reject a plan for a different dataset")


def test_maintenance_service_execute_repair_rejects_stale_plan(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    CsvOHLCVStore().write_atomic(
        csv_path,
        [
            Candle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
            Candle(120_000, 10.0, 5.0, 1.0, 2.0, 11.0),
        ],
        market=market,
    )
    service = _service(tmp_path)
    plan = service.plan_ohlcv_repair(DatasetId("bybit", "linear", "LINKUSDT", "1m"))
    with csv_path.open("a", encoding="utf-8") as handle:
        handle.write("180000,2,3,1,2.5,12\n")

    try:
        asyncio.run(
            service.execute_ohlcv_repair(
                object(),
                DatasetId("bybit", "linear", "LINKUSDT", "1m"),
                plan,
            )
        )
    except ValueError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("execute_ohlcv_repair should reject a stale repair plan")


def test_maintenance_service_persists_ok_validation_and_lists_cached_status(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1h")
    service = _service(tmp_path)

    report = service.validate_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.status == "ok"
    assert report.metadata_updated is True
    payload = json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    assert payload["validation"]["status"] == "ok"
    assert payload["validation"]["validator"] == "HistoricalDatasetValidator"
    assert payload["validation"]["row_count"] == 2
    assert payload["validation"]["issue_count"] == 0
    assert payload["validation"]["csv_fingerprint"]["size_bytes"] is not None
    assert service.list_ohlcv_datasets()[0].validation_status == "ok"


def test_maintenance_service_validation_rebuilds_mismatched_metadata_identity(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1m")
    metadata_path = metadata_path_for_csv(csv_path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["market"]["timeframe"] = "1M"
    payload["identity"]["artifact_uid"] = "ohlcv:bybit:linear:LINKUSDT:1M:ohlcv__candles"
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    service = _service(tmp_path)

    report = service.validate_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    assert report.metadata_updated is True
    updated = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert updated["market"]["timeframe"] == "1m"
    assert updated["validation"]["status"] == "warning"


def test_maintenance_service_treats_stale_validation_metadata_as_unknown(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1h")
    service = _service(tmp_path)
    service.validate_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    with csv_path.open("a", encoding="utf-8") as handle:
        handle.write("1609466400000,2,3,1,2.5,12\n")

    assert service.list_ohlcv_datasets()[0].validation_status == "unknown"


def test_maintenance_service_deletes_only_selected_ohlcv_csv_and_metadata(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1m")
    metadata_path = metadata_path_for_csv(csv_path)
    market = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    unrelated_path = paths.partition_dir(market) / "indicators" / "keep.csv"
    unrelated_path.parent.mkdir(parents=True)
    unrelated_path.write_text("value\n1\n", encoding="utf-8")
    dataset_service = _InvalidateTrackingDatasetService()
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=dataset_service,  # type: ignore[arg-type]
    )

    report = service.delete_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    assert report.csv_deleted is True
    assert report.metadata_deleted is True
    assert report.cache_invalidated is True
    assert not csv_path.exists()
    assert not metadata_path.exists()
    assert unrelated_path.exists()
    assert dataset_service.invalidated == [DatasetId("bybit", "linear", "LINKUSDT", "1m")]


def test_maintenance_service_delete_tolerates_missing_metadata(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1h")
    metadata_path = metadata_path_for_csv(csv_path)
    metadata_path.unlink()
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    report = service.delete_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.csv_deleted is True
    assert report.metadata_deleted is False
    assert not csv_path.exists()
    assert not metadata_path.exists()


def test_maintenance_service_delete_requires_existing_csv(tmp_path: Path) -> None:
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    try:
        service.delete_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1m"))
    except FileNotFoundError as exc:
        assert "OHLCV CSV not found" in str(exc)
    else:
        raise AssertionError("delete_ohlcv should fail when candles.csv is missing")


def test_maintenance_service_delete_uses_collision_safe_timeframe_path(tmp_path: Path) -> None:
    minute_csv = _write_ohlcv(tmp_path, timeframe="1m")
    month_csv = _write_ohlcv(tmp_path, timeframe="1M")
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    report = service.delete_ohlcv(DatasetId("bybit", "linear", "LINKUSDT", "1M"))

    assert report.dataset.timeframe == "1M"
    assert report.dataset.storage_segment == "1mo"
    assert minute_csv.exists()
    assert not month_csv.exists()
    assert metadata_path_for_csv(minute_csv).exists()
    assert not metadata_path_for_csv(month_csv).exists()


def test_maintenance_service_rebuilds_corrupt_metadata_without_touching_csv(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1h")
    before_csv = csv_path.read_text(encoding="utf-8")
    metadata_path = metadata_path_for_csv(csv_path)
    metadata_path.write_text("{bad json", encoding="utf-8")
    dataset_service = _InvalidateTrackingDatasetService()
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=dataset_service,  # type: ignore[arg-type]
    )

    report = service.rebuild_ohlcv_metadata(DatasetId("bybit", "linear", "LINKUSDT", "1h"))

    assert report.action == "rebuild_ohlcv_metadata"
    assert report.metadata_rebuilt is True
    assert report.row_count == 2
    assert report.cache_invalidated is True
    assert csv_path.read_text(encoding="utf-8") == before_csv
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["market"]["timeframe"] == "1h"
    assert payload["shape"]["row_count"] == 2
    assert dataset_service.invalidated == [DatasetId("bybit", "linear", "LINKUSDT", "1h")]


def test_maintenance_service_rebuilds_wrong_but_parseable_metadata_identity(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1m")
    metadata_path = metadata_path_for_csv(csv_path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["market"]["timeframe"] = "1M"
    payload["identity"]["artifact_uid"] = "ohlcv:bybit:linear:LINKUSDT:1M:ohlcv__candles"
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    service.rebuild_ohlcv_metadata(DatasetId("bybit", "linear", "LINKUSDT", "1m"))

    rebuilt = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert rebuilt["market"]["timeframe"] == "1m"
    assert rebuilt["identity"]["artifact_uid"] == "ohlcv:bybit:linear:LINKUSDT:1m:ohlcv__candles"


def test_maintenance_service_rebuild_preserves_canonical_month_timeframe(tmp_path: Path) -> None:
    csv_path = _write_ohlcv(tmp_path, timeframe="1M")
    metadata_path = metadata_path_for_csv(csv_path)
    metadata_path.unlink()
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    report = service.rebuild_ohlcv_metadata(DatasetId("bybit", "linear", "LINKUSDT", "1M"))

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert report.dataset.storage_segment == "1mo"
    assert payload["market"]["timeframe"] == "1M"
    assert payload["identity"]["artifact_uid"] == "ohlcv:bybit:linear:LINKUSDT:1M:ohlcv__candles"


def test_maintenance_service_rebuild_requires_existing_csv(tmp_path: Path) -> None:
    service = HistoricalOhlcvMaintenanceService(
        historical_root=tmp_path / "historical",
        dataset_service=_InvalidateTrackingDatasetService(),  # type: ignore[arg-type]
    )

    try:
        service.rebuild_ohlcv_metadata(DatasetId("bybit", "linear", "LINKUSDT", "1m"))
    except FileNotFoundError as exc:
        assert "OHLCV CSV not found" in str(exc)
    else:
        raise AssertionError("rebuild_ohlcv_metadata should fail when candles.csv is missing")
