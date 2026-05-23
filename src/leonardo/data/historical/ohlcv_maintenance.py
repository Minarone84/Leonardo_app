"""Inspection, validation, and narrow maintenance actions for OHLCV datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.historical.validator import HistoricalDatasetValidator
from leonardo.data.naming import MarketId, canonicalize


@dataclass(frozen=True)
class OhlcvDatasetSummary:
    """Read-only catalog summary for one persisted OHLCV dataset."""

    dataset_id: DatasetId
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    storage_segment: str
    partition_path: Path
    csv_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class OhlcvManifestSummary:
    """Selected sidecar fields useful for read-only maintenance display."""

    unique_id: str
    artifact_uid: str
    artifact_family: str
    storage_family: str
    market_exchange: str
    market_type: str
    market_symbol: str
    market_timeframe: str
    csv_relpath: str
    metadata_relpath: str
    row_count: int | None
    column_count: int | None
    columns: tuple[str, ...]
    first_ts_ms: int | None
    first_ts_utc: str
    first_ts_rome: str
    last_ts_ms: int | None
    last_ts_utc: str
    last_ts_rome: str
    timeline_status: str
    validation_status: str
    validation_notes: tuple[str, ...]
    fingerprint_size_bytes: int | None
    fingerprint_modified_at_ms: int | None


@dataclass(frozen=True)
class OhlcvInspectionReport:
    """Read-only CSV and sidecar inspection result for one OHLCV dataset."""

    dataset: OhlcvDatasetSummary
    csv_exists: bool
    metadata_exists: bool
    metadata_valid: bool
    metadata_status: str
    metadata_error: str
    local_state_source: str
    first_ts_ms: int | None
    last_ts_ms: int | None
    row_count: int
    issues: tuple[str, ...]
    manifest: OhlcvManifestSummary | None


@dataclass(frozen=True)
class OhlcvValidationIssue:
    """Structured validation issue for GUI display."""

    severity: str
    message: str


@dataclass(frozen=True)
class OhlcvValidationReport:
    """Read-only validation result for one OHLCV dataset."""

    dataset: OhlcvDatasetSummary
    status: str
    row_count: int
    issues: tuple[OhlcvValidationIssue, ...]


@dataclass(frozen=True)
class OhlcvMutationReport:
    """Structured result for one explicit OHLCV maintenance mutation."""

    dataset: OhlcvDatasetSummary
    action: str
    csv_path: Path
    metadata_path: Path
    message: str
    csv_deleted: bool = False
    metadata_deleted: bool = False
    metadata_rebuilt: bool = False
    cache_invalidated: bool = False
    row_count: int = 0


class HistoricalOhlcvMaintenanceService:
    """
    Provide OHLCV maintenance reports and narrow dataset deletion.

    The service owns historical OHLCV inspection, validation, exact dataset
    deletion, and explicit metadata rebuild. It does not repair data, download
    candles, delete derived artifacts, or import GUI code.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        dataset_service: HistoricalDatasetService,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._dataset_service = dataset_service
        self._paths = HistoricalPaths(root=self._historical_root)
        self._store = CsvOHLCVStore()

    def list_ohlcv_datasets(self) -> tuple[OhlcvDatasetSummary, ...]:
        """Return canonical OHLCV datasets known to the historical catalog."""
        return tuple(
            self._summary_for_dataset(dataset_id)
            for dataset_id in self._dataset_service.list_dataset_ids()
        )

    def inspect_ohlcv(self, dataset_id: DatasetId) -> OhlcvInspectionReport:
        """Inspect one OHLCV CSV and sidecar without mutating storage."""
        summary = self._summary_for_dataset(dataset_id)
        market = self._market_for_dataset(dataset_id)
        local_state = self._store.inspect(summary.csv_path, market=market, repair_metadata=False)
        manifest, metadata_error = self._load_manifest(summary.metadata_path)

        if not local_state.metadata_exists:
            metadata_status = "missing"
        elif manifest is None:
            metadata_status = "unreadable"
        elif local_state.metadata_valid:
            metadata_status = "valid"
        else:
            metadata_status = "mismatch_or_stale"

        return OhlcvInspectionReport(
            dataset=summary,
            csv_exists=local_state.csv_exists,
            metadata_exists=local_state.metadata_exists,
            metadata_valid=local_state.metadata_valid,
            metadata_status=metadata_status,
            metadata_error=metadata_error,
            local_state_source=local_state.source,
            first_ts_ms=local_state.first_ts_ms,
            last_ts_ms=local_state.last_ts_ms,
            row_count=local_state.row_count,
            issues=tuple(local_state.issues),
            manifest=None if manifest is None else self._manifest_summary(manifest),
        )

    def validate_ohlcv(self, dataset_id: DatasetId) -> OhlcvValidationReport:
        """Validate one OHLCV dataset without mutating storage."""
        summary = self._summary_for_dataset(dataset_id)
        report = HistoricalDatasetValidator(summary.timeframe).validate(summary.csv_path)
        return OhlcvValidationReport(
            dataset=summary,
            status=report.status,
            row_count=report.row_count,
            issues=tuple(
                OhlcvValidationIssue(severity=issue.severity, message=issue.message)
                for issue in report.issues
            ),
        )

    def delete_ohlcv(self, dataset_id: DatasetId) -> OhlcvMutationReport:
        """Delete one OHLCV CSV and its adjacent metadata sidecar."""
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)

        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")

        metadata_exists = summary.metadata_path.exists()
        summary.csv_path.unlink()
        metadata_deleted = False
        if metadata_exists:
            summary.metadata_path.unlink()
            metadata_deleted = True

        cache_invalidated = self._dataset_service.invalidate_dataset_cache(summary.dataset_id)
        return OhlcvMutationReport(
            dataset=summary,
            action="delete_ohlcv",
            csv_path=summary.csv_path,
            metadata_path=summary.metadata_path,
            message=(
                f"Deleted OHLCV dataset {summary.exchange} / {summary.market_type} / "
                f"{summary.symbol} / {summary.timeframe}."
            ),
            csv_deleted=True,
            metadata_deleted=metadata_deleted,
            cache_invalidated=bool(cache_invalidated),
        )

    def rebuild_ohlcv_metadata(self, dataset_id: DatasetId) -> OhlcvMutationReport:
        """Rewrite one OHLCV metadata sidecar from the existing CSV."""
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)

        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")

        market = self._market_for_dataset(summary.dataset_id)
        state = self._store.rebuild_metadata_sidecar(summary.csv_path, market=market)
        cache_invalidated = self._dataset_service.invalidate_dataset_cache(summary.dataset_id)
        return OhlcvMutationReport(
            dataset=summary,
            action="rebuild_ohlcv_metadata",
            csv_path=summary.csv_path,
            metadata_path=summary.metadata_path,
            message=(
                f"Rebuilt OHLCV metadata for {summary.exchange} / {summary.market_type} / "
                f"{summary.symbol} / {summary.timeframe}."
            ),
            metadata_rebuilt=True,
            cache_invalidated=bool(cache_invalidated),
            row_count=state.row_count,
        )

    def _summary_for_dataset(self, dataset_id: DatasetId) -> OhlcvDatasetSummary:
        market = self._market_for_dataset(dataset_id)
        partition_path = self._paths.partition_dir(market)
        csv_path = self._store.file_path(self._paths.ohlcv_dir(market))
        return OhlcvDatasetSummary(
            dataset_id=DatasetId(
                exchange=market.exchange,
                market_type=market.market_type,
                symbol=market.symbol,
                timeframe=market.timeframe,
            ),
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            storage_segment=partition_path.name,
            partition_path=partition_path,
            csv_path=csv_path,
            metadata_path=metadata_path_for_csv(csv_path),
        )

    def _validate_ohlcv_targets(self, summary: OhlcvDatasetSummary) -> None:
        if summary.csv_path.name != self._store.FILENAME:
            raise RuntimeError(f"Unexpected OHLCV filename: {summary.csv_path}")
        if summary.csv_path.parent.name != "ohlcv":
            raise RuntimeError(f"Unexpected OHLCV directory: {summary.csv_path}")
        if summary.metadata_path != metadata_path_for_csv(summary.csv_path):
            raise RuntimeError(f"Unexpected metadata path: {summary.metadata_path}")

        historical_root = self._historical_root.resolve()
        for path in (summary.csv_path, summary.metadata_path):
            resolved = path.resolve()
            try:
                resolved.relative_to(historical_root)
            except ValueError as exc:
                raise RuntimeError(f"OHLCV target is outside historical root: {path}") from exc

    def _market_for_dataset(self, dataset_id: DatasetId) -> MarketId:
        return canonicalize(
            dataset_id.exchange,
            dataset_id.market_type,
            dataset_id.symbol,
            dataset_id.timeframe,
        )

    def _load_manifest(self, metadata_path: Path) -> tuple[HistoricalCsvArtifactManifest | None, str]:
        if not metadata_path.exists():
            return None, ""
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                return HistoricalCsvArtifactManifest.from_dict(json.load(handle)), ""
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def _manifest_summary(self, manifest: HistoricalCsvArtifactManifest) -> OhlcvManifestSummary:
        fingerprint = manifest.fingerprint
        quality = manifest.quality
        return OhlcvManifestSummary(
            unique_id=manifest.identity.unique_id,
            artifact_uid=manifest.identity.artifact_uid,
            artifact_family=manifest.identity.artifact_family,
            storage_family=manifest.identity.storage_family,
            market_exchange=manifest.market.exchange,
            market_type=manifest.market.market_type,
            market_symbol=manifest.market.symbol,
            market_timeframe=manifest.market.timeframe,
            csv_relpath=manifest.files.csv_relpath,
            metadata_relpath=manifest.files.metadata_relpath,
            row_count=manifest.shape.row_count,
            column_count=manifest.shape.column_count,
            columns=tuple(manifest.shape.columns),
            first_ts_ms=manifest.time_range.first_ts_ms,
            first_ts_utc=manifest.time_range.first_ts_utc,
            first_ts_rome=manifest.time_range.first_ts_rome,
            last_ts_ms=manifest.time_range.last_ts_ms,
            last_ts_utc=manifest.time_range.last_ts_utc,
            last_ts_rome=manifest.time_range.last_ts_rome,
            timeline_status=quality.timeline_status,
            validation_status=quality.validation_status,
            validation_notes=tuple(quality.validation_notes),
            fingerprint_size_bytes=fingerprint.size_bytes,
            fingerprint_modified_at_ms=fingerprint.modified_at_ms,
        )
