"""Inspection, validation, and narrow maintenance actions for OHLCV datasets."""

from __future__ import annotations

import json
import re
import time
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
from leonardo.data.historical.validator import HistoricalDatasetValidator, ValidationIssue
from leonardo.data.naming import MarketId, canonicalize


_VALIDATION_ROW_RE = re.compile(r"\brow\s+(\d+)\b")
_SOURCE_CORRECTION_ELIGIBLE_CODES = {
    "open_out_of_bounds",
    "close_out_of_bounds",
    "low_greater_than_high",
}
_SOURCE_CORRECTION_RELATIVE_TOLERANCE = 0.0001
_SOURCE_CORRECTION_ABSOLUTE_TOLERANCE = 1e-12


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
    code: str | None = None
    row_index: int | None = None
    ts_ms: int | None = None
    column: str | None = None
    repairable: bool | None = None


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
    repair_outcome: str
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
    source_invalid: bool = False
    source_invalid_anchors: tuple[int, ...] = ()


@dataclass(frozen=True)
class OhlcvSourceCorrectionValues:
    """OHLCV values used by a read-only source-correction proposal."""

    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OhlcvSourceCorrectionContext:
    """Neighbor-candle context used to justify a source-correction item."""

    previous_close: float | None = None
    current_open: float | None = None
    next_open: float | None = None
    current_close: float | None = None
    absolute_difference: float | None = None
    tolerance: float | None = None
    context_match: bool | None = None
    previous_contiguous: bool | None = None
    next_contiguous: bool | None = None


@dataclass(frozen=True)
class OhlcvSourceCorrectionItem:
    """One read-only source-correction proposal or non-actionable finding."""

    ts_ms: int | None
    row_index: int | None
    issue_code: str
    issue_message: str
    action: str
    actionable: bool
    confidence: str
    method: str
    original: OhlcvSourceCorrectionValues | None
    proposed: OhlcvSourceCorrectionValues | None
    context: OhlcvSourceCorrectionContext
    reason: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OhlcvSourceCorrectionPlan:
    """Read-only source-correction plan for source-invalid OHLCV candles."""

    dataset: OhlcvDatasetSummary
    status: str
    actionable: bool
    item_count: int
    actionable_count: int
    row_count: int
    items: tuple[OhlcvSourceCorrectionItem, ...]
    message: str
    warnings: tuple[str, ...] = ()
    csv_fingerprint_size_bytes: int | None = None
    csv_fingerprint_modified_at_ms: int | None = None
    generated_at_ms: int | None = None
    relative_tolerance: float = _SOURCE_CORRECTION_RELATIVE_TOLERANCE
    absolute_tolerance: float = _SOURCE_CORRECTION_ABSOLUTE_TOLERANCE


@dataclass(frozen=True)
class OhlcvSourceCorrectionExecutionItem:
    """Execution result for one planned source-correction item."""

    ts_ms: int | None
    row_index: int | None
    action: str
    status: str
    issue_code: str
    original: OhlcvSourceCorrectionValues | None
    corrected: OhlcvSourceCorrectionValues | None
    message: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OhlcvSourceCorrectionExecutionReport:
    """Structured result for explicit OHLCV source-correction execution."""

    dataset: OhlcvDatasetSummary
    status: str
    validation_status: str
    action_count: int
    applied_count: int
    skipped_count: int
    failed_count: int
    final_row_count: int
    metadata_updated: bool
    validation_metadata_updated: bool
    cache_invalidated: bool
    csv_path: Path
    metadata_path: Path
    source_csv_fingerprint_size_bytes: int | None
    source_csv_fingerprint_modified_at_ms: int | None
    corrected_csv_fingerprint_size_bytes: int | None
    corrected_csv_fingerprint_modified_at_ms: int | None
    items: tuple[OhlcvSourceCorrectionExecutionItem, ...]
    message: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


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
        recorded_status = self._validation_status_for_metadata(summary, report.status)
        metadata_updated = False
        metadata_update_error = ""
        try:
            metadata_updated = self._store.record_validation_result(
                summary.csv_path,
                market=self._market_for_dataset(dataset_id),
                status=recorded_status,
                row_count=report.row_count,
                issues=tuple((issue.severity, issue.message) for issue in report.issues),
                validator="HistoricalDatasetValidator",
                message_override=self._validation_message_override(recorded_status, report.status),
            )
        except Exception as exc:
            metadata_update_error = f"{type(exc).__name__}: {exc}"
        return OhlcvValidationReport(
            dataset=summary,
            status=recorded_status,
            row_count=report.row_count,
            issues=tuple(
                self._ohlcv_validation_issue(issue)
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
            self._ohlcv_validation_issue(issue)
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

    def plan_ohlcv_source_correction(self, dataset_id: DatasetId) -> OhlcvSourceCorrectionPlan:
        """Build a read-only source-correction plan from current validation issues."""
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)
        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")

        validator = HistoricalDatasetValidator(summary.timeframe)
        report = validator.validate(summary.csv_path)
        row_timestamps = self._store.read_ts_ms_by_row(summary.csv_path)
        issues = tuple(
            self._ohlcv_validation_issue(issue)
            for issue in report.issues
        )
        error_issues = tuple(issue for issue in issues if issue.severity == "error")
        if not error_issues:
            fingerprint = self._store.file_fingerprint(summary.csv_path)
            return OhlcvSourceCorrectionPlan(
                dataset=summary,
                status=report.status,
                actionable=False,
                item_count=0,
                actionable_count=0,
                row_count=report.row_count,
                items=(),
                message="No validation errors detected; no source correction plan is needed.",
                csv_fingerprint_size_bytes=fingerprint.size_bytes,
                csv_fingerprint_modified_at_ms=fingerprint.modified_at_ms,
                generated_at_ms=int(time.time() * 1000),
            )

        eligible_issues = tuple(
            issue
            for issue in error_issues
            if (issue.code or "") in _SOURCE_CORRECTION_ELIGIBLE_CODES
        )
        candles: list[Candle] = []
        read_error = ""
        if eligible_issues:
            try:
                candles = self._store.read(summary.csv_path)
            except Exception as exc:
                read_error = f"{type(exc).__name__}: {exc}"

        items = self._source_correction_items_from_issues(
            issues=error_issues,
            row_timestamps=row_timestamps,
            candles=candles,
            step_ms=validator.step_ms,
            read_error=read_error,
        )
        actionable_count = sum(1 for item in items if item.actionable)
        if actionable_count:
            message = f"{actionable_count} actionable source-correction item(s) were planned."
        elif items:
            message = "Validation errors were found, but no automatic source correction is currently actionable."
        else:
            message = "No source correction items could be derived from the current validation report."

        fingerprint = self._store.file_fingerprint(summary.csv_path)
        return OhlcvSourceCorrectionPlan(
            dataset=summary,
            status=report.status,
            actionable=actionable_count > 0,
            item_count=len(items),
            actionable_count=actionable_count,
            row_count=report.row_count,
            items=items,
            message=message,
            warnings=() if not read_error else (f"Could not read OHLCV rows for context: {read_error}",),
            csv_fingerprint_size_bytes=fingerprint.size_bytes,
            csv_fingerprint_modified_at_ms=fingerprint.modified_at_ms,
            generated_at_ms=int(time.time() * 1000),
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
        final_candles = self._store.read(summary.csv_path)
        repair_outcome, source_invalid_anchors, warnings = self._repair_execution_classification(
            ranges=plan.ranges,
            range_results=tuple(range_results),
            before_by_ts=before_by_ts,
            final_candles=final_candles,
            final_validation_status=final_validation.status,
            final_issue_messages_by_ts=self._validation_issue_messages_by_ts(
                final_validation.issues,
                self._store.read_ts_ms_by_row(summary.csv_path),
            ),
        )
        return OhlcvRepairExecutionReport(
            dataset=summary,
            action="execute_ohlcv_repair",
            repair_outcome=repair_outcome,
            csv_path=summary.csv_path,
            metadata_path=summary.metadata_path,
            message=self._repair_execution_message(summary, repair_outcome),
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
            source_invalid=repair_outcome == "source_invalid",
            source_invalid_anchors=source_invalid_anchors,
        )

    def execute_ohlcv_source_correction(
        self,
        dataset_id: DatasetId,
        plan: OhlcvSourceCorrectionPlan,
    ) -> OhlcvSourceCorrectionExecutionReport:
        """
        Apply a reviewed source-correction plan to one OHLCV dataset.

        Execution is intentionally limited to a single dataset and to
        correction actions already present in the supplied plan. The current CSV
        fingerprint and target row values must still match the plan before any
        write occurs. Successful corrections are persisted through the CSV
        store, followed by source-correction provenance, raw validation, modified
        validation stamping, and dataset-cache invalidation.
        """
        summary = self._summary_for_dataset(dataset_id)
        self._validate_ohlcv_targets(summary)
        if not summary.csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {summary.csv_path}")
        self._validate_source_correction_plan_for_dataset(plan, summary)

        market = self._market_for_dataset(summary.dataset_id)
        source_fingerprint = self._store.file_fingerprint(summary.csv_path)
        existing_source_records = self._store.source_correction_records(summary.csv_path, market=market)
        source_candles = self._store.read(summary.csv_path)
        row_timestamps = self._store.read_ts_ms_by_row(summary.csv_path)
        self._validate_source_correction_candles(source_candles)

        pending_candles = list(source_candles)
        execution_items: list[OhlcvSourceCorrectionExecutionItem] = []
        record_bases: list[dict[str, object]] = []

        for item in sorted(plan.items, key=self._source_correction_item_execution_key):
            if not item.actionable:
                raise ValueError(f"Source correction plan contains a non-actionable item: {item.issue_message}")
            if item.action not in {"adjust_ohlc_envelope", "drop_initial_invalid_bar"}:
                raise ValueError(f"Unsupported source correction action: {item.action}")

            if item.action == "adjust_ohlc_envelope":
                corrected_candles, execution_item, record_base = self._execute_envelope_source_correction_item(
                    item=item,
                    candles=pending_candles,
                    row_timestamps=row_timestamps,
                )
            else:
                corrected_candles, execution_item, record_base = self._execute_initial_drop_source_correction_item(
                    item=item,
                    candles=pending_candles,
                    row_timestamps=row_timestamps,
                )
            pending_candles = corrected_candles
            execution_items.append(execution_item)
            record_bases.append(record_base)

        self._validate_source_correction_candles(pending_candles)
        self._store.write_atomic(summary.csv_path, pending_candles, market=market)
        corrected_fingerprint = self._store.file_fingerprint(summary.csv_path)
        source_records = tuple(
            self._final_source_correction_record(
                record,
                source=summary.exchange,
                source_fingerprint=source_fingerprint,
                corrected_fingerprint=corrected_fingerprint,
            )
            for record in record_bases
        )
        metadata_updated = self._store.record_source_corrections(
            summary.csv_path,
            market=market,
            records=source_records,
            existing_records=existing_source_records,
        )

        final_raw_validation = HistoricalDatasetValidator(summary.timeframe).validate(summary.csv_path)
        final_status = "modified" if final_raw_validation.status in {"ok", "warning"} else "error"
        validation_metadata_updated = self._store.record_validation_result(
            summary.csv_path,
            market=market,
            status=final_status,
            row_count=final_raw_validation.row_count,
            issues=tuple((issue.severity, issue.message) for issue in final_raw_validation.issues),
            validator="HistoricalDatasetValidator",
            message_override=self._source_correction_validation_message(
                final_status,
                final_raw_validation.status,
                final_raw_validation.issues,
            ),
        )
        cache_invalidated = self._dataset_service.invalidate_dataset_cache(summary.dataset_id)
        final_issues = tuple(self._ohlcv_validation_issue(issue) for issue in final_raw_validation.issues)
        errors = tuple(
            f"{issue.severity}: {issue.message}"
            for issue in final_issues
            if issue.severity == "error"
        )
        status = "ok" if final_status == "modified" else "error"
        message = (
            f"Applied {len(execution_items)} source correction item(s); dataset is valid with modified provenance."
            if final_status == "modified"
            else "Source correction applied, but final validation still has hard errors."
        )
        return OhlcvSourceCorrectionExecutionReport(
            dataset=summary,
            status=status,
            validation_status=final_status,
            action_count=len(plan.items),
            applied_count=len(execution_items),
            skipped_count=0,
            failed_count=0 if status == "ok" else len(errors),
            final_row_count=final_raw_validation.row_count,
            metadata_updated=bool(metadata_updated),
            validation_metadata_updated=bool(validation_metadata_updated),
            cache_invalidated=bool(cache_invalidated),
            csv_path=summary.csv_path,
            metadata_path=summary.metadata_path,
            source_csv_fingerprint_size_bytes=source_fingerprint.size_bytes,
            source_csv_fingerprint_modified_at_ms=source_fingerprint.modified_at_ms,
            corrected_csv_fingerprint_size_bytes=corrected_fingerprint.size_bytes,
            corrected_csv_fingerprint_modified_at_ms=corrected_fingerprint.modified_at_ms,
            items=tuple(execution_items),
            message=message,
            warnings=tuple(
                f"{issue.severity}: {issue.message}"
                for issue in final_issues
                if issue.severity == "warning"
            ),
            errors=errors,
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

    def _validate_source_correction_plan_for_dataset(
        self,
        plan: OhlcvSourceCorrectionPlan,
        summary: OhlcvDatasetSummary,
    ) -> None:
        if self._dataset_key(plan.dataset) != self._dataset_key(summary):
            raise ValueError("Source correction plan dataset does not match the selected OHLCV dataset")
        if not plan.actionable or not plan.items:
            raise ValueError("Source correction plan has no actionable items")
        if not any(item.actionable for item in plan.items):
            raise ValueError("Source correction plan contains no actionable correction items")
        if any(not item.actionable for item in plan.items):
            raise ValueError("Source correction execution requires a fully actionable reviewed plan")
        if any(item.action not in {"adjust_ohlc_envelope", "drop_initial_invalid_bar"} for item in plan.items):
            raise ValueError("Source correction plan contains unsupported action types")

        current_fingerprint = self._store.file_fingerprint(summary.csv_path)
        if (
            plan.csv_fingerprint_size_bytes != current_fingerprint.size_bytes
            or plan.csv_fingerprint_modified_at_ms != current_fingerprint.modified_at_ms
        ):
            raise ValueError(
                "Source correction plan is stale. Re-run Analyze Checked and Plan Source Correction."
            )

    def _execute_envelope_source_correction_item(
        self,
        *,
        item: OhlcvSourceCorrectionItem,
        candles: list[Candle],
        row_timestamps: tuple[int | None, ...],
    ) -> tuple[list[Candle], OhlcvSourceCorrectionExecutionItem, dict[str, object]]:
        if item.ts_ms is None:
            raise ValueError("Source correction item has no target timestamp")
        if item.original is None or item.proposed is None:
            raise ValueError("Envelope source correction requires original and proposed OHLCV values")
        self._validate_source_correction_row_index(item, row_timestamps)
        index = self._single_candle_index_by_ts(candles, int(item.ts_ms))
        current = candles[index]
        if not self._source_values_equal(self._source_values(current), item.original):
            raise ValueError(f"Current OHLCV row no longer matches source correction plan at ts_ms {item.ts_ms}")
        proposed_candle = self._candle_from_source_values(int(item.ts_ms), item.proposed)
        self._validate_corrected_candle(proposed_candle)
        corrected = list(candles)
        corrected[index] = proposed_candle
        execution_item = OhlcvSourceCorrectionExecutionItem(
            ts_ms=item.ts_ms,
            row_index=item.row_index,
            action=item.action,
            status="applied",
            issue_code=item.issue_code,
            original=item.original,
            corrected=item.proposed,
            message=f"Applied source correction at ts_ms {item.ts_ms}.",
            warnings=(),
        )
        return corrected, execution_item, self._source_correction_record_base(item=item, corrected=item.proposed)

    def _execute_initial_drop_source_correction_item(
        self,
        *,
        item: OhlcvSourceCorrectionItem,
        candles: list[Candle],
        row_timestamps: tuple[int | None, ...],
    ) -> tuple[list[Candle], OhlcvSourceCorrectionExecutionItem, dict[str, object]]:
        if item.ts_ms is None:
            raise ValueError("Initial source correction drop has no target timestamp")
        if item.row_index != 0:
            raise ValueError("Initial source correction drop requires row_index 0")
        if not candles or candles[0].ts_ms != int(item.ts_ms):
            raise ValueError("Initial source correction drop target is no longer the first OHLCV row")
        self._validate_source_correction_row_index(item, row_timestamps)
        current = candles[0]
        if item.original is None or not self._source_values_equal(self._source_values(current), item.original):
            raise ValueError(f"Current first OHLCV row no longer matches source correction plan at ts_ms {item.ts_ms}")
        corrected = list(candles[1:])
        execution_item = OhlcvSourceCorrectionExecutionItem(
            ts_ms=item.ts_ms,
            row_index=item.row_index,
            action=item.action,
            status="applied",
            issue_code=item.issue_code,
            original=item.original,
            corrected=None,
            message=f"Dropped initial source-invalid OHLCV row at ts_ms {item.ts_ms}.",
            warnings=(
                "Dataset start timestamp changed.",
                "Dataset row count decreased.",
            ),
        )
        return corrected, execution_item, self._source_correction_record_base(item=item, corrected=None)

    def _validate_source_correction_row_index(
        self,
        item: OhlcvSourceCorrectionItem,
        row_timestamps: tuple[int | None, ...],
    ) -> None:
        if item.row_index is None:
            return
        if item.row_index < 0 or item.row_index >= len(row_timestamps):
            raise ValueError(f"Source correction row_index is outside current CSV rows: {item.row_index}")
        if row_timestamps[item.row_index] != item.ts_ms:
            raise ValueError(
                "Source correction plan row/timestamp target no longer matches the current CSV"
            )

    def _single_candle_index_by_ts(self, candles: list[Candle], ts_ms: int) -> int:
        matches = [index for index, candle in enumerate(candles) if int(candle.ts_ms) == int(ts_ms)]
        if not matches:
            raise ValueError(f"Source correction target ts_ms not found: {ts_ms}")
        if len(matches) > 1:
            raise ValueError(f"Source correction target ts_ms is duplicated: {ts_ms}")
        return matches[0]

    def _validate_corrected_candle(self, candle: Candle) -> None:
        if candle.volume < 0:
            raise ValueError(f"Source correction would create negative volume at ts_ms {candle.ts_ms}")
        if not (candle.low <= candle.high):
            raise ValueError(f"Source correction would leave low greater than high at ts_ms {candle.ts_ms}")
        if not (candle.low <= candle.open <= candle.high):
            raise ValueError(f"Source correction would leave open out of bounds at ts_ms {candle.ts_ms}")
        if not (candle.low <= candle.close <= candle.high):
            raise ValueError(f"Source correction would leave close out of bounds at ts_ms {candle.ts_ms}")

    def _validate_source_correction_candles(self, candles: list[Candle]) -> None:
        ts_values = [int(candle.ts_ms) for candle in candles]
        if len(ts_values) != len(set(ts_values)):
            raise ValueError("Source correction would leave duplicate ts_ms values")
        if any(left >= right for left, right in zip(ts_values, ts_values[1:])):
            raise ValueError("Source correction would break strict timestamp ordering")

    def _source_correction_record_base(
        self,
        *,
        item: OhlcvSourceCorrectionItem,
        corrected: OhlcvSourceCorrectionValues | None,
    ) -> dict[str, object]:
        return {
            "ts_ms": item.ts_ms,
            "row_index": item.row_index,
            "issue_code": item.issue_code,
            "issue_message": item.issue_message,
            "action": item.action,
            "method": item.method,
            "confidence": item.confidence,
            "needs_source_recheck": True,
            "original": None if item.original is None else self._source_values_dict(item.original),
            "corrected": None if corrected is None else self._source_values_dict(corrected),
            "context": self._source_context_dict(item.context),
        }

    def _final_source_correction_record(
        self,
        record: dict[str, object],
        *,
        source: str,
        source_fingerprint: Any,
        corrected_fingerprint: Any,
    ) -> dict[str, object]:
        corrected_at_ms = int(time.time() * 1000)
        out = dict(record)
        out.update(
            {
                "source": str(source),
                "corrected_at_ms": corrected_at_ms,
                "corrected_at": format_ts_ms_utc(corrected_at_ms),
                "source_csv_fingerprint": self._fingerprint_dict(source_fingerprint),
                "corrected_csv_fingerprint": self._fingerprint_dict(corrected_fingerprint),
            }
        )
        return out

    def _source_correction_validation_message(
        self,
        status: str,
        raw_status: str,
        issues: tuple[ValidationIssue, ...] | list[ValidationIssue],
    ) -> str:
        if status == "modified":
            if raw_status == "warning" and issues:
                return (
                    "Dataset is valid after documented source correction; "
                    f"warnings remain: {issues[0].severity}: {issues[0].message}"
                )
            return "Dataset is valid after documented source correction."
        if issues:
            return f"{len(tuple(issues))} validation issues detected after source correction; first: {issues[0].severity}: {issues[0].message}"
        return "Source correction completed, but validation did not produce a modified status."

    def _validation_status_for_metadata(self, summary: OhlcvDatasetSummary, raw_status: str) -> str:
        if raw_status in {"ok", "warning"} and self._store.has_current_source_corrections(
            summary.csv_path,
            market=self._market_for_dataset(summary.dataset_id),
        ):
            return "modified"
        return raw_status

    def _validation_message_override(self, recorded_status: str, raw_status: str) -> str | None:
        if recorded_status == "modified":
            if raw_status == "warning":
                return "Dataset is valid after documented source correction; validation warnings remain."
            return "Dataset is valid after documented source correction."
        return None

    @staticmethod
    def _source_correction_item_execution_key(item: OhlcvSourceCorrectionItem) -> tuple[int, int]:
        ts_ms = 9_223_372_036_854_775_807 if item.ts_ms is None else int(item.ts_ms)
        row_index = 9_223_372_036_854_775_807 if item.row_index is None else int(item.row_index)
        return ts_ms, row_index

    @staticmethod
    def _candle_from_source_values(ts_ms: int, values: OhlcvSourceCorrectionValues) -> Candle:
        return Candle(
            ts_ms=int(ts_ms),
            open=float(values.open),
            high=float(values.high),
            low=float(values.low),
            close=float(values.close),
            volume=float(values.volume),
        )

    @staticmethod
    def _source_values_equal(left: OhlcvSourceCorrectionValues, right: OhlcvSourceCorrectionValues) -> bool:
        return (
            left.open == right.open
            and left.high == right.high
            and left.low == right.low
            and left.close == right.close
            and left.volume == right.volume
        )

    @staticmethod
    def _source_values_dict(values: OhlcvSourceCorrectionValues) -> dict[str, object]:
        return {
            "open": values.open,
            "high": values.high,
            "low": values.low,
            "close": values.close,
            "volume": values.volume,
        }

    @staticmethod
    def _source_context_dict(context: OhlcvSourceCorrectionContext) -> dict[str, object]:
        return {
            "previous_close": context.previous_close,
            "current_open": context.current_open,
            "next_open": context.next_open,
            "current_close": context.current_close,
            "absolute_difference": context.absolute_difference,
            "tolerance": context.tolerance,
            "context_match": context.context_match,
            "previous_contiguous": context.previous_contiguous,
            "next_contiguous": context.next_contiguous,
        }

    @staticmethod
    def _fingerprint_dict(fingerprint: Any) -> dict[str, object]:
        return {
            "size_bytes": getattr(fingerprint, "size_bytes", None),
            "modified_at_ms": getattr(fingerprint, "modified_at_ms", None),
        }

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
            ts_ms = self._ts_ms_for_issue(issue, row_timestamps)
            if ts_ms is None:
                if row_index is None:
                    warnings.append(f"Issue has no row timestamp anchor: {issue.message}")
                    continue
                if row_index < 0 or row_index >= len(row_timestamps):
                    warnings.append(f"Issue row is outside the CSV timestamp map: {issue.message}")
                    continue
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
                    () if row_index is None else (row_index,),
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

    def _repair_execution_classification(
        self,
        *,
        ranges: tuple[OhlcvRepairRange, ...],
        range_results: tuple[OhlcvRepairExecutionRange, ...],
        before_by_ts: dict[int, Candle],
        final_candles: list[Candle],
        final_validation_status: str,
        final_issue_messages_by_ts: dict[int, tuple[str, ...]],
    ) -> tuple[str, tuple[int, ...], tuple[str, ...]]:
        final_by_ts = {candle.ts_ms: candle for candle in final_candles}
        warnings: list[str] = []
        no_replacement_rows = False
        coverage_missing_anchor = False
        incomplete_ranges = len(range_results) < len(ranges)
        source_invalid_anchors: list[int] = []
        for index, repair_range in enumerate(ranges, start=1):
            result = range_results[index - 1] if index <= len(range_results) else None
            if result is None:
                warnings.append(f"Range {index} did not return a repair result.")
                continue

            if result is not None and result.downloaded_bars == 0:
                no_replacement_rows = True
                warnings.append(
                    f"Range {index} fetched no exchange candles; existing rows in the repair range were not replaced."
                )
                continue

            for ts_ms in repair_range.anchor_ts_ms:
                coverage_includes_anchor = self._downloaded_coverage_includes(result, ts_ms)
                if not coverage_includes_anchor:
                    coverage_missing_anchor = True
                    warnings.append(
                        f"Range {index} downloaded coverage did not include validation anchor ts_ms {ts_ms}; "
                        "repair could not prove replacement of the bad candle."
                    )

                final_candle = final_by_ts.get(ts_ms)
                if final_candle is None:
                    warnings.append(f"Range {index} no longer contains validation anchor ts_ms {ts_ms}.")
                    continue
                before_candle = before_by_ts.get(ts_ms)
                if before_candle is not None and final_candle == before_candle:
                    warnings.append(
                        f"Range {index} left validation anchor ts_ms {ts_ms} unchanged after repair."
                    )

                issue_messages = final_issue_messages_by_ts.get(ts_ms, ())
                if final_validation_status == "error" and coverage_includes_anchor and issue_messages:
                    source_invalid_anchors.append(ts_ms)
                    warnings.append(
                        f"Source-invalid candle detected at ts_ms {ts_ms}: {'; '.join(issue_messages)}. "
                        "The repair range was redownloaded from the exchange, but the replacement candle still "
                        "violates OHLC validation. No local correction was applied. Dataset remains invalid."
                    )

        if final_validation_status == "ok":
            repair_outcome = "repaired_ok"
        elif incomplete_ranges:
            repair_outcome = "repair_failed"
        elif no_replacement_rows:
            repair_outcome = "no_replacement_rows"
        elif coverage_missing_anchor:
            repair_outcome = "coverage_missing_anchor"
        elif source_invalid_anchors:
            repair_outcome = "source_invalid"
        elif final_validation_status == "warning":
            repair_outcome = "repaired_warning"
        else:
            repair_outcome = "validation_failed"

        return (
            repair_outcome,
            tuple(sorted(set(source_invalid_anchors))),
            tuple(dict.fromkeys(warnings)),
        )

    def _validation_issue_messages_by_ts(
        self,
        issues: tuple[OhlcvValidationIssue, ...],
        row_timestamps: tuple[int | None, ...],
    ) -> dict[int, tuple[str, ...]]:
        messages_by_ts: dict[int, list[str]] = {}
        for issue in issues:
            ts_ms = self._ts_ms_for_issue(issue, row_timestamps)
            if ts_ms is None:
                continue
            messages_by_ts.setdefault(ts_ms, []).append(f"{issue.severity}: {issue.message}")
        return {ts_ms: tuple(messages) for ts_ms, messages in messages_by_ts.items()}

    @staticmethod
    def _downloaded_coverage_includes(result: OhlcvRepairExecutionRange | None, ts_ms: int) -> bool:
        if result is None:
            return False
        if result.downloaded_first_ts_ms is None or result.downloaded_last_ts_ms is None:
            return False
        return int(result.downloaded_first_ts_ms) <= int(ts_ms) <= int(result.downloaded_last_ts_ms)

    def _repair_execution_message(self, summary: OhlcvDatasetSummary, repair_outcome: str) -> str:
        dataset = f"{summary.exchange} / {summary.market_type} / {summary.symbol} / {summary.timeframe}"
        if repair_outcome == "repaired_ok":
            return f"Repair completed and post-repair validation passed for {dataset}."
        if repair_outcome == "source_invalid":
            return (
                "Repair executed, but validation still failed because the exchange data still contains "
                f"invalid candle(s) for {dataset}."
            )
        if repair_outcome == "coverage_missing_anchor":
            return (
                "Repair executed, but downloaded coverage did not include one or more validation anchor "
                f"candles for {dataset}."
            )
        if repair_outcome == "no_replacement_rows":
            return f"Repair executed, but no replacement candles were fetched for {dataset}."
        if repair_outcome == "repair_failed":
            return f"Repair did not complete all planned ranges for {dataset}."
        if repair_outcome == "repaired_warning":
            return f"Repair executed; post-repair validation completed with warnings for {dataset}."
        return f"Repair executed, but post-repair validation still failed for {dataset}."

    def _source_correction_items_from_issues(
        self,
        *,
        issues: tuple[OhlcvValidationIssue, ...],
        row_timestamps: tuple[int | None, ...],
        candles: list[Candle],
        step_ms: int | None,
        read_error: str,
    ) -> tuple[OhlcvSourceCorrectionItem, ...]:
        candles_by_ts = {candle.ts_ms: candle for candle in candles}
        position_by_ts = {candle.ts_ms: index for index, candle in enumerate(candles)}
        issue_timestamps = {
            ts_ms
            for issue in issues
            for ts_ms in (self._ts_ms_for_issue(issue, row_timestamps),)
            if ts_ms is not None
        }
        planned_values_by_ts: dict[int, OhlcvSourceCorrectionValues] = {}
        sorted_issues = sorted(
            issues,
            key=lambda issue: self._source_correction_issue_sort_key(issue, row_timestamps),
        )
        items: list[OhlcvSourceCorrectionItem] = []

        for issue in sorted_issues:
            row_index = self._row_index_for_issue(issue)
            ts_ms = self._ts_ms_for_issue(issue, row_timestamps)
            code = issue.code or "unknown"
            if code not in _SOURCE_CORRECTION_ELIGIBLE_CODES:
                items.append(
                    self._unsupported_source_correction_item(
                        issue=issue,
                        row_index=row_index,
                        ts_ms=ts_ms,
                        reason=(
                            f"Validation issue code {code!r} is not eligible for source-correction planning."
                        ),
                    )
                )
                continue

            if read_error:
                items.append(
                    self._unsupported_source_correction_item(
                        issue=issue,
                        row_index=row_index,
                        ts_ms=ts_ms,
                        reason=f"OHLCV rows could not be read for source-correction context: {read_error}",
                    )
                )
                continue

            if ts_ms is None or ts_ms not in candles_by_ts:
                items.append(
                    self._unsupported_source_correction_item(
                        issue=issue,
                        row_index=row_index,
                        ts_ms=ts_ms,
                        reason="The validation issue has no readable candle timestamp for source correction.",
                    )
                )
                continue

            candle = candles_by_ts[ts_ms]
            position = position_by_ts[ts_ms]
            if code == "open_out_of_bounds":
                item = self._plan_open_source_correction(
                    issue=issue,
                    candle=candle,
                    position=position,
                    row_index=row_index,
                    candles=candles,
                    step_ms=step_ms,
                    invalid_timestamps=issue_timestamps,
                    planned_values_by_ts=planned_values_by_ts,
                )
            elif code == "close_out_of_bounds":
                item = self._plan_close_source_correction(
                    issue=issue,
                    candle=candle,
                    position=position,
                    row_index=row_index,
                    candles=candles,
                    step_ms=step_ms,
                    invalid_timestamps=issue_timestamps,
                    planned_values_by_ts=planned_values_by_ts,
                )
            else:
                item = self._plan_envelope_source_correction(
                    issue=issue,
                    candle=candle,
                    position=position,
                    row_index=row_index,
                    candles=candles,
                    step_ms=step_ms,
                    invalid_timestamps=issue_timestamps,
                    planned_values_by_ts=planned_values_by_ts,
                )

            if item.actionable and item.proposed is not None:
                planned_values_by_ts[candle.ts_ms] = item.proposed
            items.append(item)

        return tuple(items)

    def _plan_open_source_correction(
        self,
        *,
        issue: OhlcvValidationIssue,
        candle: Candle,
        position: int,
        row_index: int | None,
        candles: list[Candle],
        step_ms: int | None,
        invalid_timestamps: set[int],
        planned_values_by_ts: dict[int, OhlcvSourceCorrectionValues],
    ) -> OhlcvSourceCorrectionItem:
        original = self._source_values(candle)
        if position == 0:
            next_candle = candles[position + 1] if position + 1 < len(candles) else None
            safe_drop = next_candle is None or next_candle.ts_ms > candle.ts_ms
            return OhlcvSourceCorrectionItem(
                ts_ms=candle.ts_ms,
                row_index=row_index,
                issue_code=issue.code or "open_out_of_bounds",
                issue_message=issue.message,
                action="drop_initial_invalid_bar",
                actionable=safe_drop,
                confidence="medium" if safe_drop else "none",
                method="initial_bar_drop",
                original=original,
                proposed=None,
                context=OhlcvSourceCorrectionContext(current_open=candle.open),
                reason=(
                    "First row is source-invalid and no previous close exists. "
                    "Proposed action: drop the initial invalid bar."
                ),
                warnings=(
                    "This will change dataset start timestamp and row count.",
                    "Execution requires explicit confirmation in a future source-correction patch.",
                ),
            )

        previous = candles[position - 1]
        previous_contiguous = self._source_context_is_contiguous(previous.ts_ms, candle.ts_ms, step_ms)
        if not previous_contiguous:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    previous_close=previous.close,
                    current_open=candle.open,
                    previous_contiguous=False,
                ),
                reason="Previous candle is not contiguous with the invalid open candle.",
            )
        if previous.ts_ms in invalid_timestamps and previous.ts_ms not in planned_values_by_ts:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    previous_close=previous.close,
                    current_open=candle.open,
                    previous_contiguous=True,
                ),
                reason="Previous candle is also invalid and has not already been planned for correction.",
            )

        previous_values = planned_values_by_ts.get(previous.ts_ms, self._source_values(previous))
        match, difference, tolerance = self._source_context_matches(previous_values.close, candle.open)
        context = OhlcvSourceCorrectionContext(
            previous_close=previous_values.close,
            current_open=candle.open,
            absolute_difference=difference,
            tolerance=tolerance,
            context_match=match,
            previous_contiguous=True,
        )
        if not match:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=context,
                reason="Previous close does not approximately match the current open.",
            )

        proposed = self._expanded_envelope_values(original)
        return OhlcvSourceCorrectionItem(
            ts_ms=candle.ts_ms,
            row_index=row_index,
            issue_code=issue.code or "open_out_of_bounds",
            issue_message=issue.message,
            action="adjust_ohlc_envelope",
            actionable=True,
            confidence="high",
            method="previous_close_context",
            original=original,
            proposed=proposed,
            context=context,
            reason=(
                "Open is outside the OHLC envelope, and previous close matches current open. "
                "Preserve open and expand the envelope to include it."
            ),
        )

    def _plan_close_source_correction(
        self,
        *,
        issue: OhlcvValidationIssue,
        candle: Candle,
        position: int,
        row_index: int | None,
        candles: list[Candle],
        step_ms: int | None,
        invalid_timestamps: set[int],
        planned_values_by_ts: dict[int, OhlcvSourceCorrectionValues],
    ) -> OhlcvSourceCorrectionItem:
        original = self._source_values(candle)
        if position + 1 >= len(candles):
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(current_close=candle.close),
                reason="No next candle exists to validate the current close.",
            )

        next_candle = candles[position + 1]
        next_contiguous = self._source_context_is_contiguous(candle.ts_ms, next_candle.ts_ms, step_ms)
        if not next_contiguous:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    current_close=candle.close,
                    next_open=next_candle.open,
                    next_contiguous=False,
                ),
                reason="Next candle is not contiguous with the invalid close candle.",
            )
        if next_candle.ts_ms in invalid_timestamps and next_candle.ts_ms not in planned_values_by_ts:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    current_close=candle.close,
                    next_open=next_candle.open,
                    next_contiguous=True,
                ),
                reason="Next candle is also invalid and has not already been planned for correction.",
            )

        next_values = planned_values_by_ts.get(next_candle.ts_ms, self._source_values(next_candle))
        match, difference, tolerance = self._source_context_matches(next_values.open, candle.close)
        context = OhlcvSourceCorrectionContext(
            current_close=candle.close,
            next_open=next_values.open,
            absolute_difference=difference,
            tolerance=tolerance,
            context_match=match,
            next_contiguous=True,
        )
        if not match:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=context,
                reason="Next open does not approximately match the current close.",
            )

        proposed = self._expanded_envelope_values(original)
        return OhlcvSourceCorrectionItem(
            ts_ms=candle.ts_ms,
            row_index=row_index,
            issue_code=issue.code or "close_out_of_bounds",
            issue_message=issue.message,
            action="adjust_ohlc_envelope",
            actionable=True,
            confidence="high",
            method="next_open_context",
            original=original,
            proposed=proposed,
            context=context,
            reason=(
                "Close is outside the OHLC envelope, and next open matches current close. "
                "Preserve close and expand the envelope to include it."
            ),
        )

    def _plan_envelope_source_correction(
        self,
        *,
        issue: OhlcvValidationIssue,
        candle: Candle,
        position: int,
        row_index: int | None,
        candles: list[Candle],
        step_ms: int | None,
        invalid_timestamps: set[int],
        planned_values_by_ts: dict[int, OhlcvSourceCorrectionValues],
    ) -> OhlcvSourceCorrectionItem:
        original = self._source_values(candle)
        if position == 0 or position + 1 >= len(candles):
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    current_open=candle.open,
                    current_close=candle.close,
                ),
                reason="Both previous close and next open context are required for low/high envelope correction.",
            )

        previous = candles[position - 1]
        next_candle = candles[position + 1]
        previous_contiguous = self._source_context_is_contiguous(previous.ts_ms, candle.ts_ms, step_ms)
        next_contiguous = self._source_context_is_contiguous(candle.ts_ms, next_candle.ts_ms, step_ms)
        if not previous_contiguous or not next_contiguous:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    previous_close=previous.close,
                    current_open=candle.open,
                    current_close=candle.close,
                    next_open=next_candle.open,
                    previous_contiguous=previous_contiguous,
                    next_contiguous=next_contiguous,
                ),
                reason="Neighbor candle context is not contiguous with the invalid envelope candle.",
            )
        if (
            previous.ts_ms in invalid_timestamps and previous.ts_ms not in planned_values_by_ts
        ) or (
            next_candle.ts_ms in invalid_timestamps and next_candle.ts_ms not in planned_values_by_ts
        ):
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=OhlcvSourceCorrectionContext(
                    previous_close=previous.close,
                    current_open=candle.open,
                    current_close=candle.close,
                    next_open=next_candle.open,
                    previous_contiguous=True,
                    next_contiguous=True,
                ),
                reason="Neighbor candle context includes invalid candles that are not already planned corrections.",
            )

        previous_values = planned_values_by_ts.get(previous.ts_ms, self._source_values(previous))
        next_values = planned_values_by_ts.get(next_candle.ts_ms, self._source_values(next_candle))
        open_match, open_difference, open_tolerance = self._source_context_matches(
            previous_values.close,
            candle.open,
        )
        close_match, close_difference, close_tolerance = self._source_context_matches(
            next_values.open,
            candle.close,
        )
        context = OhlcvSourceCorrectionContext(
            previous_close=previous_values.close,
            current_open=candle.open,
            current_close=candle.close,
            next_open=next_values.open,
            absolute_difference=max(open_difference, close_difference),
            tolerance=max(open_tolerance, close_tolerance),
            context_match=open_match and close_match,
            previous_contiguous=True,
            next_contiguous=True,
        )
        if not context.context_match:
            return self._ambiguous_source_correction_item(
                issue=issue,
                row_index=row_index,
                candle=candle,
                original=original,
                context=context,
                reason="Previous close and next open do not both support the current open/close values.",
            )

        return OhlcvSourceCorrectionItem(
            ts_ms=candle.ts_ms,
            row_index=row_index,
            issue_code=issue.code or "low_greater_than_high",
            issue_message=issue.message,
            action="adjust_ohlc_envelope",
            actionable=True,
            confidence="high",
            method="envelope_context",
            original=original,
            proposed=self._expanded_envelope_values(original),
            context=context,
            reason=(
                "Low/high envelope is invalid, and neighbor context supports the current open and close. "
                "Expand the envelope to include open, high, low, and close."
            ),
        )

    def _unsupported_source_correction_item(
        self,
        *,
        issue: OhlcvValidationIssue,
        row_index: int | None,
        ts_ms: int | None,
        reason: str,
    ) -> OhlcvSourceCorrectionItem:
        return OhlcvSourceCorrectionItem(
            ts_ms=ts_ms,
            row_index=row_index,
            issue_code=issue.code or "unknown",
            issue_message=issue.message,
            action="unsupported_no_action",
            actionable=False,
            confidence="none",
            method="unsupported",
            original=None,
            proposed=None,
            context=OhlcvSourceCorrectionContext(),
            reason=reason,
        )

    def _ambiguous_source_correction_item(
        self,
        *,
        issue: OhlcvValidationIssue,
        row_index: int | None,
        candle: Candle,
        original: OhlcvSourceCorrectionValues,
        context: OhlcvSourceCorrectionContext,
        reason: str,
    ) -> OhlcvSourceCorrectionItem:
        return OhlcvSourceCorrectionItem(
            ts_ms=candle.ts_ms,
            row_index=row_index,
            issue_code=issue.code or "unknown",
            issue_message=issue.message,
            action="ambiguous_no_action",
            actionable=False,
            confidence="none",
            method="ambiguous",
            original=original,
            proposed=None,
            context=context,
            reason=reason,
        )

    def _source_correction_issue_sort_key(
        self,
        issue: OhlcvValidationIssue,
        row_timestamps: tuple[int | None, ...],
    ) -> tuple[int, int, int]:
        row_index = self._row_index_for_issue(issue)
        ts_ms = self._ts_ms_for_issue(issue, row_timestamps)
        return (
            1 if ts_ms is None else 0,
            9_223_372_036_854_775_807 if ts_ms is None else int(ts_ms),
            9_223_372_036_854_775_807 if row_index is None else int(row_index),
        )

    @staticmethod
    def _source_values(candle: Candle) -> OhlcvSourceCorrectionValues:
        return OhlcvSourceCorrectionValues(
            open=float(candle.open),
            high=float(candle.high),
            low=float(candle.low),
            close=float(candle.close),
            volume=float(candle.volume),
        )

    @staticmethod
    def _expanded_envelope_values(values: OhlcvSourceCorrectionValues) -> OhlcvSourceCorrectionValues:
        return OhlcvSourceCorrectionValues(
            open=values.open,
            high=max(values.high, values.open, values.low, values.close),
            low=min(values.low, values.open, values.high, values.close),
            close=values.close,
            volume=values.volume,
        )

    @staticmethod
    def _source_context_is_contiguous(left_ts_ms: int, right_ts_ms: int, step_ms: int | None) -> bool:
        if step_ms is None:
            return True
        return int(right_ts_ms) - int(left_ts_ms) == int(step_ms)

    @staticmethod
    def _source_context_matches(left: float, right: float) -> tuple[bool, float, float]:
        difference = abs(float(left) - float(right))
        tolerance = max(
            _SOURCE_CORRECTION_ABSOLUTE_TOLERANCE,
            abs(float(right)) * _SOURCE_CORRECTION_RELATIVE_TOLERANCE,
        )
        return difference <= tolerance, difference, tolerance

    def _row_index_for_issue(self, issue: OhlcvValidationIssue) -> int | None:
        if issue.row_index is not None:
            return int(issue.row_index)
        match = _VALIDATION_ROW_RE.search(issue.message)
        if match is None:
            return None
        return int(match.group(1))

    def _ts_ms_for_issue(
        self,
        issue: OhlcvValidationIssue,
        row_timestamps: tuple[int | None, ...],
    ) -> int | None:
        if issue.ts_ms is not None:
            return int(issue.ts_ms)

        row_index = self._row_index_for_issue(issue)
        if row_index is None or row_index < 0 or row_index >= len(row_timestamps):
            return None
        ts_ms = row_timestamps[row_index]
        if ts_ms is None:
            return None
        return int(ts_ms)

    @staticmethod
    def _ohlcv_validation_issue(issue: ValidationIssue) -> OhlcvValidationIssue:
        return OhlcvValidationIssue(
            severity=issue.severity,
            message=issue.message,
            code=issue.code,
            row_index=issue.row_index,
            ts_ms=issue.ts_ms,
            column=issue.column,
            repairable=issue.repairable,
        )

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
        if validation.status not in {"ok", "modified", "warning", "error"}:
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
