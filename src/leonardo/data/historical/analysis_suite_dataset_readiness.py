from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from leonardo.data.historical.analysis_database_contracts import (
    ANALYSIS_DATABASE_DATASET_TYPE,
    ANALYSIS_DATABASE_MANIFEST_FILENAME,
    AnalysisDatabaseManifest,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_dataset_geography import (
    AnalysisDatasetGeographyPolicy,
)
from leonardo.data.historical.paths import storage_segment_to_timeframe
from leonardo.data.naming import MarketId, canonicalize


AnalysisSuiteDatasetReadinessStatus = Literal[
    "ready",
    "draft",
    "missing_dataframe",
    "stale_source",
    "incomplete_topology",
    "corrupt_manifest",
    "corrupt_dataframe",
    "blocked",
    "error",
]


@dataclass(frozen=True)
class AnalysisSuiteDatasetReadinessReport:
    """
    Read-only Analysis Suite readiness report for one Analysis Database.

    The report is intentionally diagnostic. It does not repair source OHLCV,
    calculate artifacts, edit manifests, or create dataframe content. Analysis
    Suite callers can use it to decide whether a materialized Analysis Database
    is eligible for preview or future analysis workflows.
    """

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    manifest_status: str
    materialization_status: str
    dataframe_status: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: AnalysisSuiteDatasetReadinessStatus
    strict_ready: bool
    can_preview: bool
    row_count: int | None
    column_count: int | None
    first_ts_ms: int | None
    last_ts_ms: int | None
    source_ohlcv_drift_status: str
    geography_status: str
    missing_topology: tuple[str, ...]
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
            "manifest_status": self.manifest_status,
            "materialization_status": self.materialization_status,
            "dataframe_status": self.dataframe_status,
            "dataframe_path": self.dataframe_path,
            "manifest_path": self.manifest_path,
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "row_count": self.row_count,
            "column_count": self.column_count,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "source_ohlcv_drift_status": self.source_ohlcv_drift_status,
            "geography_status": self.geography_status,
            "missing_topology": list(self.missing_topology),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class AnalysisSuiteDatasetCatalogReport:
    """JSON-safe catalog report for Analysis Suite dataset readiness."""

    total_count: int
    ready_count: int
    blocked_count: int
    draft_count: int
    stale_count: int
    error_count: int
    items: tuple[AnalysisSuiteDatasetReadinessReport, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "total_count": int(self.total_count),
            "ready_count": int(self.ready_count),
            "blocked_count": int(self.blocked_count),
            "draft_count": int(self.draft_count),
            "stale_count": int(self.stale_count),
            "error_count": int(self.error_count),
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


class AnalysisSuiteDatasetReadinessService:
    """
    Build read-only readiness diagnostics for Analysis Suite dataset candidates.

    The service consumes Analysis Database manifests and dataframe metadata
    through existing data-layer contracts. It reports readiness for future
    Analysis Suite consumers without changing Data Manager state, source OHLCV,
    recipes, artifacts, or Analysis Database files.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
        geography_policy: AnalysisDatasetGeographyPolicy | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(
            historical_root=self._historical_root
        )
        self._geography_policy = geography_policy or AnalysisDatasetGeographyPolicy()

    def list_analysis_datasets(
        self,
        *,
        market: MarketId | None = None,
    ) -> AnalysisSuiteDatasetCatalogReport:
        """
        List Analysis Database readiness reports for a market or all markets.

        The scan includes unreadable manifest files as blocked diagnostics.
        This differs from Data Manager listing behavior, which may omit corrupt
        manifests to keep preparation widgets usable.
        """

        items = tuple(
            self._readiness_for_manifest_path(path)
            for path in self._manifest_paths(market=market)
        )
        return AnalysisSuiteDatasetCatalogReport(
            total_count=len(items),
            ready_count=sum(1 for item in items if item.readiness_status == "ready"),
            blocked_count=sum(
                1
                for item in items
                if item.readiness_status
                in {
                    "missing_dataframe",
                    "incomplete_topology",
                    "corrupt_dataframe",
                    "blocked",
                }
            ),
            draft_count=sum(1 for item in items if item.readiness_status == "draft"),
            stale_count=sum(
                1 for item in items if item.readiness_status == "stale_source"
            ),
            error_count=sum(
                1
                for item in items
                if item.readiness_status in {"corrupt_manifest", "error"}
            ),
            items=items,
        )

    def readiness_for_database(
        self,
        *,
        market: MarketId,
        database_id: str,
    ) -> AnalysisSuiteDatasetReadinessReport:
        """
        Build a readiness report for one Analysis Database identity.
        """

        return self._readiness_for_manifest_path(
            self._store.manifest_path(market=market, database_id=database_id)
        )

    def build_readiness_report(
        self,
        manifest: AnalysisDatabaseManifest,
        *,
        manifest_path: Path | None = None,
    ) -> AnalysisSuiteDatasetReadinessReport:
        """
        Build a readiness report from a loaded Analysis Database manifest.

        This method supports callers that already have a validated manifest.
        It still performs read-only dataframe, source-drift, and geography
        diagnostics through the same policy used by catalog scans.
        """

        path = manifest_path or self._store.manifest_path(
            market=manifest.market,
            database_id=manifest.database_id,
        )
        return self._build_report_from_manifest(manifest=manifest, manifest_path=path)

    def _readiness_for_manifest_path(
        self,
        path: Path,
    ) -> AnalysisSuiteDatasetReadinessReport:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            manifest = AnalysisDatabaseManifest.from_dict(dict(raw))
        except Exception as exc:
            return self._corrupt_manifest_report(path=path, exc=exc)
        return self._build_report_from_manifest(manifest=manifest, manifest_path=path)

    def _build_report_from_manifest(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        manifest_path: Path,
    ) -> AnalysisSuiteDatasetReadinessReport:
        dataframe_path = self._store.dataframe_path(
            market=manifest.market,
            database_id=manifest.database_id,
        )
        warnings: list[str] = []
        blockers: list[str] = []
        errors: list[str] = []
        materialization = manifest.materialization
        materialization_status = "present" if materialization is not None else "missing"
        source_drift_status = "not_checked"
        geography_status = "unknown"
        missing_topology: tuple[str, ...] = ()

        if manifest.status == "draft" or materialization is None:
            blockers.append("database_not_materialized")
            geography_status, missing_topology = self._geography_state(
                manifest=manifest,
                warnings=warnings,
                blockers=blockers,
                errors=errors,
            )
            return self._report(
                manifest=manifest,
                manifest_path=manifest_path,
                dataframe_path=dataframe_path,
                readiness_status="draft",
                materialization_status=materialization_status,
                dataframe_status="not_materialized",
                can_preview=False,
                row_count=None,
                column_count=None,
                first_ts_ms=None,
                last_ts_ms=None,
                source_drift_status=source_drift_status,
                geography_status=geography_status,
                missing_topology=missing_topology,
                warnings=warnings,
                blockers=blockers,
                errors=errors,
            )

        dataframe = _inspect_dataframe(
            path=dataframe_path,
            expected_row_count=materialization.row_count,
            expected_column_count=materialization.column_count,
            expected_first_ts_ms=materialization.first_ts_ms,
            expected_last_ts_ms=materialization.last_ts_ms,
            expected_sha256=materialization.dataframe_sha256,
        )
        warnings.extend(dataframe.warnings)
        blockers.extend(dataframe.blockers)
        errors.extend(dataframe.errors)

        source_drift_status = self._source_drift_state(
            manifest=manifest,
            warnings=warnings,
            blockers=blockers,
            errors=errors,
        )
        geography_status, missing_topology = self._geography_state(
            manifest=manifest,
            warnings=warnings,
            blockers=blockers,
            errors=errors,
        )

        readiness_status = _readiness_status(
            dataframe_status=dataframe.status,
            source_drift_status=source_drift_status,
            geography_status=geography_status,
            missing_topology=missing_topology,
            errors=errors,
        )
        can_preview = dataframe.status == "available"
        return self._report(
            manifest=manifest,
            manifest_path=manifest_path,
            dataframe_path=dataframe_path,
            readiness_status=readiness_status,
            materialization_status=materialization_status,
            dataframe_status=dataframe.status,
            can_preview=can_preview,
            row_count=dataframe.row_count,
            column_count=dataframe.column_count,
            first_ts_ms=dataframe.first_ts_ms,
            last_ts_ms=dataframe.last_ts_ms,
            source_drift_status=source_drift_status,
            geography_status=geography_status,
            missing_topology=missing_topology,
            warnings=warnings,
            blockers=blockers,
            errors=errors,
        )

    def _source_drift_state(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        warnings: list[str],
        blockers: list[str],
        errors: list[str],
    ) -> str:
        try:
            report = self._store.materialization_source_ohlcv_drift_report(
                market=manifest.market,
                database_id=manifest.database_id,
            )
        except Exception as exc:
            errors.append(f"source_ohlcv_drift_check_failed: {type(exc).__name__}: {exc}")
            blockers.append("source_ohlcv_drift_check_failed")
            return "error"

        if report.status == "current":
            return "current"
        reason_text = ", ".join(report.reasons) if report.reasons else report.status
        if report.status == "source_drift":
            blockers.append(f"source_ohlcv_drift: {reason_text}")
        elif report.status == "unknown":
            blockers.append(f"source_ohlcv_drift_unknown: {reason_text}")
        else:
            blockers.append(f"source_ohlcv_drift_blocked: {reason_text}")
        warnings.extend(str(reason) for reason in report.reasons)
        return report.status

    def _geography_state(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        warnings: list[str],
        blockers: list[str],
        errors: list[str],
    ) -> tuple[str, tuple[str, ...]]:
        try:
            report = self._geography_policy.evaluate_manifest(manifest)
        except Exception as exc:
            errors.append(f"geography_check_failed: {type(exc).__name__}: {exc}")
            blockers.append("geography_check_failed")
            return "error", ()

        warnings.extend(
            f"{warning.code}: {warning.message}" for warning in report.warnings
        )
        blockers.extend(
            f"{blocker.code}: {blocker.message}" for blocker in report.blockers
        )
        if report.blockers:
            return "blocked", tuple(report.missing_keys)
        if report.missing_keys:
            blockers.append(
                "missing_topology: " + ", ".join(str(key) for key in report.missing_keys)
            )
            return "incomplete", tuple(report.missing_keys)
        return "complete", ()

    def _report(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        manifest_path: Path,
        dataframe_path: Path,
        readiness_status: AnalysisSuiteDatasetReadinessStatus,
        materialization_status: str,
        dataframe_status: str,
        can_preview: bool,
        row_count: int | None,
        column_count: int | None,
        first_ts_ms: int | None,
        last_ts_ms: int | None,
        source_drift_status: str,
        geography_status: str,
        missing_topology: Iterable[str],
        warnings: Iterable[str],
        blockers: Iterable[str],
        errors: Iterable[str],
    ) -> AnalysisSuiteDatasetReadinessReport:
        return AnalysisSuiteDatasetReadinessReport(
            database_id=manifest.database_id,
            display_name=manifest.display_name,
            exchange=manifest.market.exchange,
            market_type=manifest.market.market_type,
            symbol=manifest.market.symbol,
            timeframe=manifest.market.timeframe,
            manifest_status=manifest.status,
            materialization_status=materialization_status,
            dataframe_status=dataframe_status,
            dataframe_path=str(dataframe_path),
            manifest_path=str(manifest_path),
            readiness_status=readiness_status,
            strict_ready=readiness_status == "ready",
            can_preview=bool(can_preview),
            row_count=row_count,
            column_count=column_count,
            first_ts_ms=first_ts_ms,
            last_ts_ms=last_ts_ms,
            source_ohlcv_drift_status=source_drift_status,
            geography_status=geography_status,
            missing_topology=tuple(str(item) for item in missing_topology),
            warnings=tuple(str(item) for item in warnings),
            blockers=tuple(str(item) for item in blockers),
            errors=tuple(str(item) for item in errors),
        )

    def _corrupt_manifest_report(
        self,
        *,
        path: Path,
        exc: Exception,
    ) -> AnalysisSuiteDatasetReadinessReport:
        market = _market_from_manifest_path(self._historical_root, path)
        database_id = path.parent.name if path.parent.name else ""
        return AnalysisSuiteDatasetReadinessReport(
            database_id=database_id,
            display_name=database_id,
            exchange="" if market is None else market.exchange,
            market_type="" if market is None else market.market_type,
            symbol="" if market is None else market.symbol,
            timeframe="" if market is None else market.timeframe,
            manifest_status="unreadable",
            materialization_status="unknown",
            dataframe_status="unknown",
            dataframe_path=(
                None
                if market is None or not database_id
                else str(
                    self._store.dataframe_path(
                        market=market,
                        database_id=database_id,
                    )
                )
            ),
            manifest_path=str(path),
            readiness_status="corrupt_manifest",
            strict_ready=False,
            can_preview=False,
            row_count=None,
            column_count=None,
            first_ts_ms=None,
            last_ts_ms=None,
            source_ohlcv_drift_status="not_checked",
            geography_status="unknown",
            missing_topology=(),
            warnings=(),
            blockers=("manifest_unreadable",),
            errors=(f"{type(exc).__name__}: {exc}",),
        )

    def _manifest_paths(self, *, market: MarketId | None) -> tuple[Path, ...]:
        if market is not None:
            base = self._store.analysis_databases_dir(market=market, ensure=False)
            if not base.exists():
                return ()
            return tuple(sorted(base.glob(f"*/{ANALYSIS_DATABASE_MANIFEST_FILENAME}")))
        if not self._historical_root.exists():
            return ()
        pattern = (
            f"*/*/*/*/{ANALYSIS_DATABASE_DATASET_TYPE}/*/"
            f"{ANALYSIS_DATABASE_MANIFEST_FILENAME}"
        )
        return tuple(sorted(self._historical_root.glob(pattern)))


@dataclass(frozen=True)
class _DataframeInspection:
    status: str
    row_count: int | None = None
    column_count: int | None = None
    first_ts_ms: int | None = None
    last_ts_ms: int | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _inspect_dataframe(
    *,
    path: Path,
    expected_row_count: int | None,
    expected_column_count: int | None,
    expected_first_ts_ms: int | None,
    expected_last_ts_ms: int | None,
    expected_sha256: str | None,
) -> _DataframeInspection:
    if not path.exists():
        return _DataframeInspection(
            status="missing",
            blockers=(f"dataframe_missing: {path}",),
        )

    warnings: list[str] = []
    blockers: list[str] = []
    errors: list[str] = []
    actual_hash = _sha256_file(path)
    if expected_sha256:
        if actual_hash != expected_sha256:
            blockers.append("dataframe_hash_mismatch")
    else:
        warnings.append("dataframe_hash_missing_from_materialization")

    try:
        row_count, column_count, first_ts_ms, last_ts_ms = _read_dataframe_metadata(path)
    except Exception as exc:
        return _DataframeInspection(
            status="corrupt",
            blockers=tuple(blockers) + ("dataframe_unreadable",),
            errors=tuple(errors) + (f"{type(exc).__name__}: {exc}",),
        )

    if expected_row_count is not None and row_count != expected_row_count:
        blockers.append("dataframe_row_count_mismatch")
    if expected_column_count is not None and column_count != expected_column_count:
        blockers.append("dataframe_column_count_mismatch")
    if expected_first_ts_ms is not None and first_ts_ms != expected_first_ts_ms:
        blockers.append("dataframe_first_ts_ms_mismatch")
    if expected_last_ts_ms is not None and last_ts_ms != expected_last_ts_ms:
        blockers.append("dataframe_last_ts_ms_mismatch")

    if blockers:
        return _DataframeInspection(
            status="corrupt",
            row_count=row_count,
            column_count=column_count,
            first_ts_ms=first_ts_ms,
            last_ts_ms=last_ts_ms,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            errors=tuple(errors),
        )
    return _DataframeInspection(
        status="available",
        row_count=row_count,
        column_count=column_count,
        first_ts_ms=first_ts_ms,
        last_ts_ms=last_ts_ms,
        warnings=tuple(warnings),
    )


def _read_dataframe_metadata(path: Path) -> tuple[int, int, int | None, int | None]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("Analysis Database dataframe is empty.") from exc
        if "ts_ms" not in header:
            raise ValueError("Analysis Database dataframe is missing ts_ms.")
        ts_index = header.index("ts_ms")
        row_count = 0
        first_ts_ms: int | None = None
        last_ts_ms: int | None = None
        for row_index, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"Analysis Database dataframe row {row_index} has {len(row)} "
                    f"field(s), expected {len(header)}."
                )
            ts_ms = int(row[ts_index])
            if first_ts_ms is None:
                first_ts_ms = ts_ms
            last_ts_ms = ts_ms
            row_count += 1
    return row_count, len(header), first_ts_ms, last_ts_ms


def _readiness_status(
    *,
    dataframe_status: str,
    source_drift_status: str,
    geography_status: str,
    missing_topology: tuple[str, ...],
    errors: Iterable[str],
) -> AnalysisSuiteDatasetReadinessStatus:
    if dataframe_status == "missing":
        return "missing_dataframe"
    if dataframe_status != "available":
        return "corrupt_dataframe"
    if source_drift_status == "source_drift":
        return "stale_source"
    if source_drift_status in {"blocked", "unknown", "error"}:
        return "blocked"
    if geography_status in {"blocked", "error"}:
        return "blocked"
    if missing_topology or geography_status == "incomplete":
        return "incomplete_topology"
    if tuple(errors):
        return "error"
    return "ready"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _market_from_manifest_path(root: Path, path: Path) -> MarketId | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
        parts = rel.parts
        if len(parts) < 7:
            return None
        return canonicalize(
            parts[0],
            parts[1],
            parts[2],
            storage_segment_to_timeframe(parts[3]),
        )
    except Exception:
        return None


__all__ = [
    "AnalysisSuiteDatasetCatalogReport",
    "AnalysisSuiteDatasetReadinessReport",
    "AnalysisSuiteDatasetReadinessService",
    "AnalysisSuiteDatasetReadinessStatus",
]
