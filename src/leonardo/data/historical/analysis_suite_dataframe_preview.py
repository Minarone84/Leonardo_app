from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Protocol

from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
    AnalysisSuiteDatasetReadinessService,
    AnalysisSuiteDatasetReadinessStatus,
)
from leonardo.data.historical.artifact_metadata_naming import (
    format_ts_ms_rome,
    format_ts_ms_utc,
)
from leonardo.data.naming import MarketId


AnalysisSuiteDataframePreviewMode = Literal["head", "tail"]
AnalysisSuiteDataframePreviewStatus = Literal["previewable", "blocked", "error"]

DEFAULT_PREVIEW_ROW_LIMIT = 100
MAX_PREVIEW_ROW_LIMIT = 500


class _ReadinessService(Protocol):
    def readiness_for_database(
        self,
        *,
        market: MarketId,
        database_id: str,
    ) -> AnalysisSuiteDatasetReadinessReport:
        ...


@dataclass(frozen=True)
class AnalysisSuiteDataframePreviewReport:
    """
    JSON-safe bounded dataframe preview report for Analysis Suite consumers.

    The report contains display-ready preview rows and the readiness diagnostics
    that allowed or blocked preview. It is intentionally read-only and does not
    mutate Analysis Database manifests, dataframes, artifacts, or source OHLCV.
    """

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: AnalysisSuiteDatasetReadinessStatus | str
    strict_ready: bool
    can_preview: bool
    status: AnalysisSuiteDataframePreviewStatus
    mode: str
    requested_limit: int
    effective_limit: int
    max_limit: int
    total_row_count: int | None
    total_column_count: int | None
    returned_row_count: int
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    preview_first_ts_ms: int | None
    preview_last_ts_ms: int | None
    dataset_first_ts_ms: int | None
    dataset_last_ts_ms: int | None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "display_name": self.display_name,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "dataframe_path": self.dataframe_path,
            "manifest_path": self.manifest_path,
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "status": self.status,
            "mode": self.mode,
            "requested_limit": int(self.requested_limit),
            "effective_limit": int(self.effective_limit),
            "max_limit": int(self.max_limit),
            "total_row_count": self.total_row_count,
            "total_column_count": self.total_column_count,
            "returned_row_count": int(self.returned_row_count),
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "preview_first_ts_ms": self.preview_first_ts_ms,
            "preview_last_ts_ms": self.preview_last_ts_ms,
            "dataset_first_ts_ms": self.dataset_first_ts_ms,
            "dataset_last_ts_ms": self.dataset_last_ts_ms,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class _PreviewRows:
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    total_row_count: int | None
    preview_first_ts_ms: int | None
    preview_last_ts_ms: int | None


class AnalysisSuiteDataframePreviewService:
    """
    Build bounded, read-only dataframe previews for Analysis Suite.

    Preview eligibility is delegated to ``AnalysisSuiteDatasetReadinessService``.
    The service resolves Analysis Database paths through data-layer ownership,
    reads at most the requested bounded preview rows into memory, and returns a
    JSON-safe report for GUI or other Analysis Suite consumers.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
        readiness_service: _ReadinessService | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(
            historical_root=self._historical_root
        )
        self._readiness_service = readiness_service or AnalysisSuiteDatasetReadinessService(
            historical_root=self._historical_root,
            store=self._store,
        )

    def preview_dataframe(
        self,
        *,
        market: MarketId,
        database_id: str,
        mode: str = "head",
        row_limit: int | None = None,
    ) -> AnalysisSuiteDataframePreviewReport:
        """
        Return a bounded read-only preview for one Analysis Database dataframe.

        The method does not accept arbitrary dataframe paths. It resolves the
        selected database through AS1 readiness and Analysis Database store
        pathing, then reads only a bounded head or tail preview from
        ``dataframe.csv`` when AS1 reports ``can_preview``.
        """

        requested_limit, effective_limit, limit_warnings = _row_limit_state(row_limit)
        mode_text = str(mode or "").strip().lower()

        try:
            readiness = self._readiness_service.readiness_for_database(
                market=market,
                database_id=database_id,
            )
        except Exception as exc:
            return self._readiness_error_report(
                market=market,
                database_id=database_id,
                mode=mode_text or str(mode),
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                warnings=limit_warnings,
                exc=exc,
            )

        if mode_text not in {"head", "tail"}:
            return self._blocked_report(
                readiness=readiness,
                mode=mode_text or str(mode),
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                warnings=limit_warnings,
                blockers=("unsupported_preview_mode",),
            )

        if not bool(getattr(readiness, "can_preview", False)):
            return self._blocked_report(
                readiness=readiness,
                mode=mode_text,
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                warnings=limit_warnings,
                blockers=("dataset_not_previewable",),
            )

        dataframe_path = self._dataframe_path(market=market, database_id=database_id)
        if not dataframe_path.exists():
            return self._blocked_report(
                readiness=readiness,
                mode=mode_text,
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                warnings=limit_warnings,
                blockers=(f"dataframe_missing: {dataframe_path}",),
            )

        try:
            if mode_text == "head":
                preview = _read_head_preview(
                    dataframe_path,
                    row_limit=effective_limit,
                    total_row_count=_int_or_none(getattr(readiness, "row_count", None)),
                )
            else:
                preview = _read_tail_preview(
                    dataframe_path,
                    row_limit=effective_limit,
                )
        except Exception as exc:
            return self._error_report(
                readiness=readiness,
                mode=mode_text,
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                warnings=limit_warnings,
                errors=(f"{type(exc).__name__}: {exc}",),
            )

        return self._previewable_report(
            readiness=readiness,
            preview=preview,
            mode=mode_text,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
            warnings=limit_warnings,
        )

    def preview_for_database(
        self,
        *,
        market: MarketId,
        database_id: str,
        mode: str = "head",
        row_limit: int | None = None,
    ) -> AnalysisSuiteDataframePreviewReport:
        """Alias for ``preview_dataframe`` using Analysis Database identity."""

        return self.preview_dataframe(
            market=market,
            database_id=database_id,
            mode=mode,
            row_limit=row_limit,
        )

    def _dataframe_path(self, *, market: MarketId, database_id: str) -> Path:
        return self._store.dataframe_path(market=market, database_id=database_id)

    def _previewable_report(
        self,
        *,
        readiness: object,
        preview: _PreviewRows,
        mode: str,
        requested_limit: int,
        effective_limit: int,
        warnings: Iterable[str],
    ) -> AnalysisSuiteDataframePreviewReport:
        return _report_from_readiness(
            readiness=readiness,
            status="previewable",
            mode=mode,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
            columns=preview.columns,
            rows=preview.rows,
            total_row_count=(
                preview.total_row_count
                if preview.total_row_count is not None
                else _int_or_none(getattr(readiness, "row_count", None))
            ),
            total_column_count=_int_or_none(getattr(readiness, "column_count", None)),
            preview_first_ts_ms=preview.preview_first_ts_ms,
            preview_last_ts_ms=preview.preview_last_ts_ms,
            warnings=tuple(getattr(readiness, "warnings", ())) + tuple(warnings),
            blockers=tuple(getattr(readiness, "blockers", ())),
            errors=tuple(getattr(readiness, "errors", ())),
        )

    def _blocked_report(
        self,
        *,
        readiness: object,
        mode: str,
        requested_limit: int,
        effective_limit: int,
        warnings: Iterable[str],
        blockers: Iterable[str],
    ) -> AnalysisSuiteDataframePreviewReport:
        return _report_from_readiness(
            readiness=readiness,
            status="blocked",
            mode=mode,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
            columns=(),
            rows=(),
            total_row_count=_int_or_none(getattr(readiness, "row_count", None)),
            total_column_count=_int_or_none(getattr(readiness, "column_count", None)),
            preview_first_ts_ms=None,
            preview_last_ts_ms=None,
            warnings=tuple(getattr(readiness, "warnings", ())) + tuple(warnings),
            blockers=tuple(getattr(readiness, "blockers", ())) + tuple(blockers),
            errors=tuple(getattr(readiness, "errors", ())),
        )

    def _error_report(
        self,
        *,
        readiness: object,
        mode: str,
        requested_limit: int,
        effective_limit: int,
        warnings: Iterable[str],
        errors: Iterable[str],
    ) -> AnalysisSuiteDataframePreviewReport:
        return _report_from_readiness(
            readiness=readiness,
            status="error",
            mode=mode,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
            columns=(),
            rows=(),
            total_row_count=_int_or_none(getattr(readiness, "row_count", None)),
            total_column_count=_int_or_none(getattr(readiness, "column_count", None)),
            preview_first_ts_ms=None,
            preview_last_ts_ms=None,
            warnings=tuple(getattr(readiness, "warnings", ())) + tuple(warnings),
            blockers=tuple(getattr(readiness, "blockers", ())),
            errors=tuple(getattr(readiness, "errors", ())) + tuple(errors),
        )

    def _readiness_error_report(
        self,
        *,
        market: MarketId,
        database_id: str,
        mode: str,
        requested_limit: int,
        effective_limit: int,
        warnings: Iterable[str],
        exc: Exception,
    ) -> AnalysisSuiteDataframePreviewReport:
        return AnalysisSuiteDataframePreviewReport(
            database_id=str(database_id),
            display_name=str(database_id),
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            dataframe_path=str(self._store.dataframe_path(market=market, database_id=database_id)),
            manifest_path=str(self._store.manifest_path(market=market, database_id=database_id)),
            readiness_status="error",
            strict_ready=False,
            can_preview=False,
            status="error",
            mode=mode,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
            max_limit=MAX_PREVIEW_ROW_LIMIT,
            total_row_count=None,
            total_column_count=None,
            returned_row_count=0,
            columns=(),
            rows=(),
            preview_first_ts_ms=None,
            preview_last_ts_ms=None,
            dataset_first_ts_ms=None,
            dataset_last_ts_ms=None,
            warnings=tuple(warnings),
            blockers=("readiness_check_failed",),
            errors=(f"{type(exc).__name__}: {exc}",),
        )


def _report_from_readiness(
    *,
    readiness: object,
    status: AnalysisSuiteDataframePreviewStatus,
    mode: str,
    requested_limit: int,
    effective_limit: int,
    columns: Iterable[str],
    rows: Iterable[dict[str, object]],
    total_row_count: int | None,
    total_column_count: int | None,
    preview_first_ts_ms: int | None,
    preview_last_ts_ms: int | None,
    warnings: Iterable[str],
    blockers: Iterable[str],
    errors: Iterable[str],
) -> AnalysisSuiteDataframePreviewReport:
    rows_tuple = tuple(dict(row) for row in rows)
    return AnalysisSuiteDataframePreviewReport(
        database_id=str(getattr(readiness, "database_id", "")),
        display_name=str(getattr(readiness, "display_name", "")),
        exchange=str(getattr(readiness, "exchange", "")),
        market_type=str(getattr(readiness, "market_type", "")),
        symbol=str(getattr(readiness, "symbol", "")),
        timeframe=str(getattr(readiness, "timeframe", "")),
        dataframe_path=_optional_str(getattr(readiness, "dataframe_path", None)),
        manifest_path=_optional_str(getattr(readiness, "manifest_path", None)),
        readiness_status=str(getattr(readiness, "readiness_status", "error")),
        strict_ready=bool(getattr(readiness, "strict_ready", False)),
        can_preview=bool(getattr(readiness, "can_preview", False)),
        status=status,
        mode=mode,
        requested_limit=requested_limit,
        effective_limit=effective_limit,
        max_limit=MAX_PREVIEW_ROW_LIMIT,
        total_row_count=total_row_count,
        total_column_count=total_column_count,
        returned_row_count=len(rows_tuple),
        columns=tuple(str(column) for column in columns),
        rows=rows_tuple,
        preview_first_ts_ms=preview_first_ts_ms,
        preview_last_ts_ms=preview_last_ts_ms,
        dataset_first_ts_ms=_int_or_none(getattr(readiness, "first_ts_ms", None)),
        dataset_last_ts_ms=_int_or_none(getattr(readiness, "last_ts_ms", None)),
        warnings=tuple(str(item) for item in warnings),
        blockers=tuple(str(item) for item in blockers),
        errors=tuple(str(item) for item in errors),
    )


def _row_limit_state(row_limit: int | None) -> tuple[int, int, tuple[str, ...]]:
    if row_limit is None:
        return DEFAULT_PREVIEW_ROW_LIMIT, DEFAULT_PREVIEW_ROW_LIMIT, ()
    requested = int(row_limit)
    if requested <= 0:
        return requested, DEFAULT_PREVIEW_ROW_LIMIT, ("row_limit_defaulted",)
    if requested > MAX_PREVIEW_ROW_LIMIT:
        return requested, MAX_PREVIEW_ROW_LIMIT, ("row_limit_clamped_to_max",)
    return requested, requested, ()


def _read_head_preview(
    path: Path,
    *,
    row_limit: int,
    total_row_count: int | None,
) -> _PreviewRows:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _fieldnames(reader)
        rows: list[dict[str, object]] = []
        for raw in reader:
            if len(rows) >= row_limit:
                break
            rows.append(_display_row(raw, columns))
    return _preview_rows(
        source_columns=columns,
        rows=rows,
        total_row_count=total_row_count,
    )


def _read_tail_preview(path: Path, *, row_limit: int) -> _PreviewRows:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _fieldnames(reader)
        row_buffer: deque[dict[str, object]] = deque(maxlen=row_limit)
        total_row_count = 0
        for raw in reader:
            row_buffer.append(_display_row(raw, columns))
            total_row_count += 1
    return _preview_rows(
        source_columns=columns,
        rows=tuple(row_buffer),
        total_row_count=total_row_count,
    )


def _fieldnames(reader: csv.DictReader[str]) -> tuple[str, ...]:
    if reader.fieldnames is None:
        raise ValueError("Analysis Database dataframe has no header row.")
    return tuple(str(column) for column in reader.fieldnames)


def _display_row(
    raw: dict[str, str | None],
    columns: tuple[str, ...],
) -> dict[str, object]:
    row: dict[str, object] = {}
    for column in columns:
        value = raw.get(column)
        if column == "ts_ms":
            ts_ms = _int_or_none(value)
            row[column] = ts_ms if ts_ms is not None else _json_safe_cell(value)
            row["ts_utc"] = format_ts_ms_utc(ts_ms)
            row["ts_rome"] = format_ts_ms_rome(ts_ms)
            continue
        row[column] = _json_safe_cell(value)
    return row


def _preview_rows(
    *,
    source_columns: tuple[str, ...],
    rows: Iterable[dict[str, object]],
    total_row_count: int | None,
) -> _PreviewRows:
    rows_tuple = tuple(dict(row) for row in rows)
    return _PreviewRows(
        columns=_display_columns(source_columns),
        rows=rows_tuple,
        total_row_count=total_row_count,
        preview_first_ts_ms=_first_ts_ms(rows_tuple),
        preview_last_ts_ms=_last_ts_ms(rows_tuple),
    )


def _display_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for column in columns:
        out.append(column)
        if column == "ts_ms":
            out.extend(("ts_utc", "ts_rome"))
    return tuple(out)


def _first_ts_ms(rows: tuple[dict[str, object], ...]) -> int | None:
    for row in rows:
        value = _int_or_none(row.get("ts_ms"))
        if value is not None:
            return value
    return None


def _last_ts_ms(rows: tuple[dict[str, object], ...]) -> int | None:
    for row in reversed(rows):
        value = _int_or_none(row.get("ts_ms"))
        if value is not None:
            return value
    return None


def _json_safe_cell(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() in {"nan", "none", "null"}:
            return None
        return text
    return value


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return int(float(value))
    except Exception:
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
