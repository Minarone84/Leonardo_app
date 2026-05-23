"""Inspection, validation, and narrow maintenance actions for OHLCV datasets."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import (
    format_ts_ms_rome,
    format_ts_ms_utc,
    metadata_path_for_csv,
)
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.downloader import DownloadRequest, HistoricalDownloader
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.historical.validator import HistoricalDatasetValidator
from leonardo.data.naming import MarketId, canonicalize


_VALIDATION_ROW_RE = re.compile(r"\brow\s+(\d+)\b")


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
    validation_status: str = "unknown"


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
    explicit_validation_status: str
    validated_at: str
    validation_validator: str
    validation_row_count: int | None
    validation_issue_count: int
    validation_warning_count: int
    validation_error_count: int
    validation_message: str
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
    """Validation result for one OHLCV dataset and sidecar update status."""

    dataset: OhlcvDatasetSummary
    status: str
    row_count: int
    issues: tuple[OhlcvValidationIssue, ...]
    metadata_updated: bool = False
    metadata_update_error: str = ""


@dataclass(frozen=True)
class OhlcvRepairRange:
    """One proposed read-only OHLCV repair range."""

    start_ts_ms: int
    end_ts_ms: int
    start_utc: str
    end_utc: str
    start_rome: str
    end_rome: str
    reason: str
    issue_count: int
    rows: tuple[int, ...]
    anchor_ts_ms: tuple[int, ...] = ()
    estimated_bars: int | None = None


@dataclass(frozen=True)
class OhlcvRepairPlan:
    """Read-only OHLCV repair proposal derived from validation output."""

    dataset: OhlcvDatasetSummary
    status: str
    actionable: bool
    message: str
    row_count: int
    ranges: tuple[OhlcvRepairRange, ...]
    issues: tuple[OhlcvValidationIssue, ...]
    warnings: tuple[str, ...]
    csv_fingerprint_size_bytes: int | None = None
    csv_fingerprint_modified_at_ms: int | None = None


@dataclass(frozen=True)
class OhlcvRepairExecutionRange:
    """Execution result for one planned OHLCV repair range."""

    start_ts_ms: int
    end_ts_ms: int
    start_utc: str
    end_utc: str
    total_rows_after: int
    job_id: str
    file_path: Path
    estimated_bars: int | None = None
    downloaded_bars: int | None = None
    downloaded_first_ts_ms: int | None = None
    downloaded_last_ts_ms: int | None = None


@dataclass(frozen=True)
class OhlcvRepairExecutionReport:
    """Structured result for explicit OHLCV repair execution."""

    dataset: OhlcvDatasetSummary
    action: str
    csv_path: Path
    metadata_path: Path
    message: str
    ranges_requested: int
    ranges_completed: int
    range_results: tuple[OhlcvRepairExecutionRange, ...]
    validation_status: str
    validation_row_count: int
    validation_issues: tuple[OhlcvValidationIssue, ...]
    final_row_count: int = 0
    metadata_updated: bool = False
    metadata_update_error: str = ""
    cache_invalidated: bool = False
    warnings: tuple[str, ...] = ()


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
    Provide OHLCV maintenance reports and narrow dataset actions.

    The service owns historical OHLCV inspection, validation, exact dataset
    deletion, explicit metadata rebuild, and read-only repair planning. It does
    not delete derived artifacts or import GUI code. Repair execution delegates
    range downloads to the existing historical downloader.
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
        """Validate one OHLCV dataset and persist explicit validation metadata."""
        summary = self._summary_for_dataset(dataset_id)
        report = HistoricalDatasetValidator(summary.timeframe).validate(summary.csv_path)
        metadata_updated = False
        metadata_update_error = ""
        try:
            metadata_updated = self._store.record_validation_result(
                summary.csv_path,
                market=self._market_for_dataset(dataset_id),
                status=report.status,
                row_count=report.row_count,
                issues=tuple((issue.severity, issue.message) for issue in report.issues),
                validator="HistoricalDatasetValidator",
            )
        except Exception as exc:
            metadata_update_error = f"{type(exc).__name__}: {exc}"
        return OhlcvValidationReport(
            dataset=summary,
            status=report.status,
            row_count=report.row_count,
            issues=tuple(
                OhlcvValidationIssue(severity=issue.severity, message=issue.message)
                for issue in report.issues
            ),
            metadata_updated=metadata_updated,
            metadata_update_error=metadata_update_error,
        )

    def plan_ohlcv_repair(self, dataset_id: DatasetId) -> OhlcvRepairPlan:
        """Build a read-only repair proposal from validation issues."""
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)
        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")

        validator = HistoricalDatasetValidator(summary.timeframe)
        report = validator.validate(summary.csv_path)
        row_timestamps = self._store.read_ts_ms_by_row(summary.csv_path)
        issues = tuple(
            OhlcvValidationIssue(severity=issue.severity, message=issue.message)
            for issue in report.issues
        )
        ranges, warnings = self._repair_ranges_from_validation(
            issues=issues,
            row_timestamps=row_timestamps,
            step_ms=validator.step_ms,
            timeframe=summary.timeframe,
        )

        if report.status == "ok":
            message = "No validation issues detected; no repair plan is needed."
        elif ranges:
            message = (
                f"{len(ranges)} proposed redownload range(s) were derived from "
                "timestamp-addressable validation issues."
            )
        else:
            message = "No timestamp-addressable repair range could be derived from the validation issues."

        fingerprint = self._store.file_fingerprint(summary.csv_path)
        return OhlcvRepairPlan(
            dataset=summary,
            status=report.status,
            actionable=bool(ranges),
            message=message,
            row_count=report.row_count,
            ranges=ranges,
            issues=issues,
            warnings=warnings,
            csv_fingerprint_size_bytes=fingerprint.size_bytes,
            csv_fingerprint_modified_at_ms=fingerprint.modified_at_ms,
        )

    async def execute_ohlcv_repair(
        self,
        ctx: Any,
        dataset_id: DatasetId,
        plan: OhlcvRepairPlan,
    ) -> OhlcvRepairExecutionReport:
        """Execute a reviewed OHLCV repair plan through the historical downloader."""
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)
        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")
        self._validate_repair_plan_for_dataset(plan, summary)

        downloader = HistoricalDownloader(root=self._historical_root)
        before_by_ts = {candle.ts_ms: candle for candle in self._store.read(summary.csv_path)}
        range_results: list[OhlcvRepairExecutionRange] = []
        for repair_range in plan.ranges:
            job_id = f"ohlcv_repair_{uuid.uuid4().hex[:12]}"
            result = await downloader.run_repair_range_with_job_id(
                ctx,
                DownloadRequest(
                    exchange=summary.exchange,
                    market_type=summary.market_type,
                    symbol=summary.symbol,
                    timeframe=summary.timeframe,
                    start_ms=int(repair_range.start_ts_ms),
                    end_ms=int(repair_range.end_ts_ms),
                ),
                job_id,
            )
            fetched_rows = getattr(result, "fetched_rows", None)
            range_results.append(
                OhlcvRepairExecutionRange(
                    start_ts_ms=int(repair_range.start_ts_ms),
                    end_ts_ms=int(repair_range.end_ts_ms),
                    start_utc=repair_range.start_utc,
                    end_utc=repair_range.end_utc,
                    estimated_bars=repair_range.estimated_bars,
                    downloaded_bars=None if fetched_rows is None else int(fetched_rows),
                    downloaded_first_ts_ms=getattr(result, "downloaded_first_ts_ms", None),
                    downloaded_last_ts_ms=getattr(result, "downloaded_last_ts_ms", None),
                    total_rows_after=int(result.total_rows),
                    job_id=job_id,
                    file_path=result.file_path,
                )
            )

        final_validation = self.validate_ohlcv(summary.dataset_id)
        cache_invalidated = self._dataset_service.invalidate_dataset_cache(summary.dataset_id)
        warnings = self._repair_execution_warnings(
            ranges=plan.ranges,
            range_results=tuple(range_results),
            before_by_ts=before_by_ts,
            final_candles=self._store.read(summary.csv_path),
        )
        return OhlcvRepairExecutionReport(
            dataset=summary,
            action="execute_ohlcv_repair",
            csv_path=summary.csv_path,
            metadata_path=summary.metadata_path,
            message=(
                f"Executed OHLCV repair for {summary.exchange} / {summary.market_type} / "
                f"{summary.symbol} / {summary.timeframe}."
            ),
            ranges_requested=len(plan.ranges),
            ranges_completed=len(range_results),
            range_results=tuple(range_results),
            validation_status=final_validation.status,
            validation_row_count=final_validation.row_count,
            final_row_count=final_validation.row_count,
            validation_issues=final_validation.issues,
            metadata_updated=final_validation.metadata_updated,
            metadata_update_error=final_validation.metadata_update_error,
            cache_invalidated=bool(cache_invalidated),
            warnings=warnings,
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
        metadata_path = metadata_path_for_csv(csv_path)
        summary = OhlcvDatasetSummary(
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
            metadata_path=metadata_path,
        )
        return replace(summary, validation_status=self._stored_validation_status(summary))

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

    def _validate_repair_plan_for_dataset(self, plan: OhlcvRepairPlan, summary: OhlcvDatasetSummary) -> None:
        if self._dataset_key(plan.dataset) != self._dataset_key(summary):
            raise ValueError("Repair plan dataset does not match the selected OHLCV dataset")
        if not plan.actionable or not plan.ranges:
            raise ValueError("Repair plan has no actionable ranges")
        current_fingerprint = self._store.file_fingerprint(summary.csv_path)
        if (
            plan.csv_fingerprint_size_bytes != current_fingerprint.size_bytes
            or plan.csv_fingerprint_modified_at_ms != current_fingerprint.modified_at_ms
        ):
            raise ValueError("Repair plan is stale because the OHLCV CSV changed after planning")
        for repair_range in plan.ranges:
            start_ts_ms = int(repair_range.start_ts_ms)
            end_ts_ms = int(repair_range.end_ts_ms)
            if start_ts_ms < 0:
                raise ValueError(f"Repair range start must be non-negative: {start_ts_ms}")
            if end_ts_ms < start_ts_ms:
                raise ValueError(
                    f"Repair range end must be greater than or equal to start: {start_ts_ms} > {end_ts_ms}"
                )

    def _repair_ranges_from_validation(
        self,
        *,
        issues: tuple[OhlcvValidationIssue, ...],
        row_timestamps: tuple[int | None, ...],
        step_ms: int | None,
        timeframe: str,
    ) -> tuple[tuple[OhlcvRepairRange, ...], tuple[str, ...]]:
        candidates: list[tuple[int, int, tuple[int, ...], tuple[int, ...], tuple[str, ...]]] = []
        warnings: list[str] = []
        variable_timeframe_warning_added = False

        for issue in issues:
            row_index = self._row_index_for_issue(issue)
            if row_index is None:
                warnings.append(f"Issue has no row timestamp anchor: {issue.message}")
                continue
            if row_index < 0 or row_index >= len(row_timestamps):
                warnings.append(f"Issue row is outside the CSV timestamp map: {issue.message}")
                continue

            ts_ms = row_timestamps[row_index]
            if ts_ms is None:
                warnings.append(f"Issue row has an unreadable ts_ms value: {issue.message}")
                continue

            if step_ms is None:
                start_ts_ms = ts_ms
                end_ts_ms = ts_ms
                if not variable_timeframe_warning_added:
                    warnings.append(
                        f"{timeframe} is variable-length; repair ranges are anchored to affected timestamps."
                    )
                    variable_timeframe_warning_added = True
            else:
                padding_ms = max(step_ms * 2, 60_000)
                start_ts_ms = max(0, ts_ms - padding_ms)
                end_ts_ms = ts_ms + padding_ms

            candidates.append(
                (
                    start_ts_ms,
                    end_ts_ms,
                    (row_index,),
                    (ts_ms,),
                    (f"{issue.severity}: {issue.message}",),
                )
            )

        return self._merge_repair_candidates(candidates, step_ms=step_ms), tuple(warnings)

    def _merge_repair_candidates(
        self,
        candidates: list[tuple[int, int, tuple[int, ...], tuple[int, ...], tuple[str, ...]]],
        *,
        step_ms: int | None,
    ) -> tuple[OhlcvRepairRange, ...]:
        if not candidates:
            return ()

        merged: list[tuple[int, int, tuple[int, ...], tuple[int, ...], tuple[str, ...]]] = []
        merge_gap_ms = 0 if step_ms is None else step_ms
        for start_ts_ms, end_ts_ms, rows, anchors, reasons in sorted(candidates, key=lambda item: item[0]):
            if not merged:
                merged.append((start_ts_ms, end_ts_ms, rows, anchors, reasons))
                continue

            prev_start, prev_end, prev_rows, prev_anchors, prev_reasons = merged[-1]
            if start_ts_ms <= prev_end + merge_gap_ms:
                merged[-1] = (
                    prev_start,
                    max(prev_end, end_ts_ms),
                    self._dedupe_ints(prev_rows + rows),
                    self._dedupe_ints(prev_anchors + anchors),
                    self._dedupe_strings(prev_reasons + reasons),
                )
                continue

            merged.append((start_ts_ms, end_ts_ms, rows, anchors, reasons))

        return tuple(
            OhlcvRepairRange(
                start_ts_ms=start_ts_ms,
                end_ts_ms=end_ts_ms,
                start_utc=format_ts_ms_utc(start_ts_ms),
                end_utc=format_ts_ms_utc(end_ts_ms),
                start_rome=format_ts_ms_rome(start_ts_ms),
                end_rome=format_ts_ms_rome(end_ts_ms),
                reason="; ".join(reasons),
                issue_count=len(reasons),
                rows=rows,
                anchor_ts_ms=anchors,
                estimated_bars=self._estimated_bars(start_ts_ms, end_ts_ms, step_ms),
            )
            for start_ts_ms, end_ts_ms, rows, anchors, reasons in merged
        )

    def _estimated_bars(self, start_ts_ms: int, end_ts_ms: int, step_ms: int | None) -> int | None:
        if step_ms is None or step_ms <= 0:
            return None
        return int((end_ts_ms - start_ts_ms) // step_ms) + 1

    def _repair_execution_warnings(
        self,
        *,
        ranges: tuple[OhlcvRepairRange, ...],
        range_results: tuple[OhlcvRepairExecutionRange, ...],
        before_by_ts: dict[int, Candle],
        final_candles: list[Candle],
    ) -> tuple[str, ...]:
        final_by_ts = {candle.ts_ms: candle for candle in final_candles}
        warnings: list[str] = []
        for index, repair_range in enumerate(ranges, start=1):
            result = range_results[index - 1] if index <= len(range_results) else None
            if result is not None and result.downloaded_bars == 0:
                warnings.append(
                    f"Range {index} fetched no exchange candles; existing rows in the repair range were not replaced."
                )

            for ts_ms in repair_range.anchor_ts_ms:
                final_candle = final_by_ts.get(ts_ms)
                if final_candle is None:
                    warnings.append(f"Range {index} no longer contains validation anchor ts_ms {ts_ms}.")
                    continue
                before_candle = before_by_ts.get(ts_ms)
                if before_candle is not None and final_candle == before_candle:
                    warnings.append(
                        f"Range {index} left validation anchor ts_ms {ts_ms} unchanged after repair."
                    )
        return tuple(dict.fromkeys(warnings))

    def _row_index_for_issue(self, issue: OhlcvValidationIssue) -> int | None:
        match = _VALIDATION_ROW_RE.search(issue.message)
        if match is None:
            return None
        return int(match.group(1))

    def _dataset_key(self, summary: OhlcvDatasetSummary) -> tuple[str, str, str, str]:
        return (summary.exchange, summary.market_type, summary.symbol, summary.timeframe)

    def _dedupe_ints(self, values: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(set(values)))

    def _dedupe_strings(self, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))

    def _stored_validation_status(self, summary: OhlcvDatasetSummary) -> str:
        manifest, _error = self._load_manifest(summary.metadata_path)
        if manifest is None:
            return "unknown"
        validation = manifest.validation
        if validation.status not in {"ok", "warning", "error"}:
            return "unknown"
        current = self._store.file_fingerprint(summary.csv_path)
        if validation.csv_fingerprint.size_bytes != current.size_bytes:
            return "unknown"
        if validation.csv_fingerprint.modified_at_ms != current.modified_at_ms:
            return "unknown"
        return validation.status

    def _manifest_summary(self, manifest: HistoricalCsvArtifactManifest) -> OhlcvManifestSummary:
        fingerprint = manifest.fingerprint
        quality = manifest.quality
        validation = manifest.validation
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
            explicit_validation_status=validation.status,
            validated_at=validation.validated_at,
            validation_validator=validation.validator,
            validation_row_count=validation.row_count,
            validation_issue_count=validation.issue_count,
            validation_warning_count=validation.warning_count,
            validation_error_count=validation.error_count,
            validation_message=validation.message,
            fingerprint_size_bytes=fingerprint.size_bytes,
            fingerprint_modified_at_ms=fingerprint.modified_at_ms,
        )
