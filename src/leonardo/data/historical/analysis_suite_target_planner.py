from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol

import pandas as pd

from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
    AnalysisSuiteDatasetReadinessService,
    AnalysisSuiteDatasetReadinessStatus,
)
from leonardo.data.naming import MarketId


ANALYSIS_SUITE_TARGET_DEFINITION_SCHEMA_VERSION = 1
DEFAULT_TARGET_PREVIEW_LIMIT = 100
MAX_TARGET_PREVIEW_LIMIT = 500

AnalysisSuiteTargetFamily = Literal["future_return", "future_direction"]
AnalysisSuiteLabelType = Literal["regression", "classification"]
AnalysisSuiteUnavailablePolicy = Literal["mark_unavailable", "drop"]
AnalysisSuiteTargetPreviewStatus = Literal["previewable", "blocked", "error"]

JsonValue = Any


class _ReadinessService(Protocol):
    def readiness_for_database(
        self,
        *,
        market: MarketId,
        database_id: str,
    ) -> AnalysisSuiteDatasetReadinessReport:
        ...


@dataclass(frozen=True)
class AnalysisSuiteTargetDefinition:
    """
    JSON-safe definition for an in-memory Analysis Suite target preview.

    A target definition describes the future-dependent label rule used by the
    target planner. It is not persisted by AS5, and generated labels are not
    written back to Analysis Database manifests or dataframes.
    """

    name: str
    target_family: AnalysisSuiteTargetFamily | str
    label_type: AnalysisSuiteLabelType | str
    source_columns: tuple[str, ...]
    horizon_bars: int
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    thresholds: Mapping[str, JsonValue] = field(default_factory=dict)
    class_mapping: Mapping[str, str] = field(default_factory=dict)
    unavailable_policy: AnalysisSuiteUnavailablePolicy | str = "mark_unavailable"
    output_column_name: str = ""
    leakage_role: str = "target_only"
    future_derived: bool = True
    feature_eligible: bool = False
    database_id: str | None = None
    exchange: str | None = None
    market_type: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    schema_version: int = ANALYSIS_SUITE_TARGET_DEFINITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_columns", tuple(str(column) for column in self.source_columns))
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(
            self,
            "thresholds",
            {str(key): value for key, value in dict(self.thresholds).items()},
        )
        object.__setattr__(
            self,
            "class_mapping",
            {str(key): str(value) for key, value in dict(self.class_mapping).items()},
        )

    @classmethod
    def future_return(
        cls,
        *,
        name: str = "Future return",
        horizon_bars: int,
        return_mode: str = "simple",
        unavailable_policy: AnalysisSuiteUnavailablePolicy = "mark_unavailable",
        output_column_name: str | None = None,
    ) -> "AnalysisSuiteTargetDefinition":
        """
        Build a future-return regression target definition.

        The AS5 implementation supports simple returns only. The generated
        output column is target-only metadata and must not be selected as a
        feature by later Analysis Suite feature-set planners.
        """

        output = output_column_name or f"target_future_return_{horizon_bars}"
        return cls(
            name=name,
            target_family="future_return",
            label_type="regression",
            source_columns=("ts_ms", "close"),
            horizon_bars=horizon_bars,
            parameters={"return_mode": return_mode},
            thresholds={},
            class_mapping={},
            unavailable_policy=unavailable_policy,
            output_column_name=output,
        )

    @classmethod
    def future_direction(
        cls,
        *,
        name: str = "Future direction",
        horizon_bars: int,
        up_threshold: float,
        down_threshold: float | None = None,
        unavailable_policy: AnalysisSuiteUnavailablePolicy = "mark_unavailable",
        output_column_name: str | None = None,
    ) -> "AnalysisSuiteTargetDefinition":
        """
        Build a future-direction classification target definition.

        ``down_threshold`` may be omitted. The planner then uses
        ``up_threshold`` symmetrically and records that default in report
        warnings.
        """

        thresholds = {"up_threshold": float(up_threshold)}
        if down_threshold is not None:
            thresholds["down_threshold"] = float(down_threshold)
        output = output_column_name or f"target_future_direction_{horizon_bars}"
        return cls(
            name=name,
            target_family="future_direction",
            label_type="classification",
            source_columns=("ts_ms", "close"),
            horizon_bars=horizon_bars,
            parameters={},
            thresholds=thresholds,
            class_mapping={
                "up": "up",
                "down": "down",
                "flat": "flat",
                "unavailable": "unavailable",
            },
            unavailable_policy=unavailable_policy,
            output_column_name=output,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuiteTargetDefinition":
        """Create a target definition from a JSON-like mapping."""

        return cls(
            name=str(data.get("name", "")),
            target_family=str(data.get("target_family", "")),
            label_type=str(data.get("label_type", "")),
            source_columns=tuple(str(item) for item in data.get("source_columns", ()) or ()),  # type: ignore[arg-type]
            horizon_bars=int(data.get("horizon_bars", 0)),
            parameters=dict(data.get("parameters", {}) or {}),  # type: ignore[arg-type]
            thresholds=dict(data.get("thresholds", {}) or {}),  # type: ignore[arg-type]
            class_mapping=dict(data.get("class_mapping", {}) or {}),  # type: ignore[arg-type]
            unavailable_policy=str(data.get("unavailable_policy", "mark_unavailable")),
            output_column_name=str(data.get("output_column_name", "")),
            leakage_role=str(data.get("leakage_role", "target_only")),
            future_derived=bool(data.get("future_derived", True)),
            feature_eligible=bool(data.get("feature_eligible", False)),
            database_id=_optional_str(data.get("database_id")),
            exchange=_optional_str(data.get("exchange")),
            market_type=_optional_str(data.get("market_type")),
            symbol=_optional_str(data.get("symbol")),
            timeframe=_optional_str(data.get("timeframe")),
            schema_version=int(data.get("schema_version", ANALYSIS_SUITE_TARGET_DEFINITION_SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "name": self.name,
            "target_family": self.target_family,
            "label_type": self.label_type,
            "source_columns": list(self.source_columns),
            "horizon_bars": int(self.horizon_bars),
            "parameters": _json_safe_mapping(self.parameters),
            "thresholds": _json_safe_mapping(self.thresholds),
            "class_mapping": dict(self.class_mapping),
            "unavailable_policy": self.unavailable_policy,
            "output_column_name": self.output_column_name,
            "leakage_role": self.leakage_role,
            "future_derived": bool(self.future_derived),
            "feature_eligible": bool(self.feature_eligible),
            "database_id": self.database_id,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }


@dataclass(frozen=True)
class AnalysisSuiteTargetPreviewReport:
    """
    JSON-safe in-memory target/label preview report.

    The report is diagnostic. It contains target metadata, label sample rows,
    summary statistics, leakage metadata, and readiness diagnostics without
    persisting target definitions or labels.
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
    target_definition: AnalysisSuiteTargetDefinition
    status: AnalysisSuiteTargetPreviewStatus
    row_count: int | None
    available_label_count: int
    unavailable_label_count: int
    first_available_ts_ms: int | None
    last_available_ts_ms: int | None
    preview_limit: int
    sample_rows: tuple[dict[str, object], ...]
    regression_stats: dict[str, object]
    class_distribution: dict[str, int]
    leakage_summary: dict[str, object]
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
            "target_definition": self.target_definition.to_dict(),
            "status": self.status,
            "row_count": self.row_count,
            "available_label_count": int(self.available_label_count),
            "unavailable_label_count": int(self.unavailable_label_count),
            "first_available_ts_ms": self.first_available_ts_ms,
            "last_available_ts_ms": self.last_available_ts_ms,
            "preview_limit": int(self.preview_limit),
            "sample_rows": [dict(row) for row in self.sample_rows],
            "regression_stats": _json_safe_mapping(self.regression_stats),
            "class_distribution": dict(self.class_distribution),
            "leakage_summary": _json_safe_mapping(self.leakage_summary),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


class AnalysisSuiteTargetPlanner:
    """
    Build read-only target/label preview reports for Analysis Suite.

    The planner gates all work through AS1 readiness, reads only the required
    dataframe columns inside the data layer, computes labels in memory, and
    reports leakage metadata for later feature-set planners. It does not write
    target definitions, labels, manifests, dataframes, or artifacts.
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

    def preview_target(
        self,
        *,
        market: MarketId,
        database_id: str,
        target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object],
        preview_limit: int | None = None,
    ) -> AnalysisSuiteTargetPreviewReport:
        """
        Return an in-memory label preview for one Analysis Database target.

        The method requires AS1 ``can_preview`` and blocks without reading the
        dataframe when the selected database is not previewable. Labels are
        aligned to the source row timestamp; future rows are used only for the
        target value.
        """

        definition = _coerce_definition(target_definition)
        requested_limit, effective_limit, limit_warnings = _preview_limit_state(preview_limit)

        try:
            readiness = self._readiness_service.readiness_for_database(
                market=market,
                database_id=database_id,
            )
        except Exception as exc:
            return self._readiness_error_report(
                market=market,
                database_id=database_id,
                definition=definition,
                preview_limit=effective_limit,
                warnings=limit_warnings,
                exc=exc,
            )

        definition = _definition_for_database(definition, readiness=readiness)
        warnings = list(getattr(readiness, "warnings", ())) + list(limit_warnings)
        blockers = list(getattr(readiness, "blockers", ()))
        errors = list(getattr(readiness, "errors", ()))

        if requested_limit != effective_limit:
            warnings.append(f"preview_limit_effective: {effective_limit}")
        if not bool(getattr(readiness, "strict_ready", False)):
            warnings.append("dataset_not_strict_ready")

        validation_blockers = _definition_blockers(definition, warnings=warnings)
        if validation_blockers:
            return self._blocked_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers + validation_blockers,
                warnings=warnings,
                errors=errors,
            )

        if not bool(getattr(readiness, "can_preview", False)):
            return self._blocked_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers + ["dataset_not_previewable"],
                warnings=warnings,
                errors=errors,
            )

        dataframe_path = self._store.dataframe_path(
            market=market,
            database_id=database_id,
        )
        if not dataframe_path.exists():
            return self._blocked_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers + [f"dataframe_missing: {dataframe_path}"],
                warnings=warnings,
                errors=errors,
            )

        try:
            frame = _read_target_dataframe(dataframe_path)
            labels = _compute_labels(frame=frame, definition=definition, warnings=warnings)
        except _TargetPlannerBlocked as exc:
            return self._blocked_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers + list(exc.blockers),
                warnings=warnings,
                errors=errors,
            )
        except Exception as exc:
            return self._error_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers,
                warnings=warnings,
                errors=errors + [f"{type(exc).__name__}: {exc}"],
            )

        if labels.row_count <= definition.horizon_bars:
            return self._blocked_report(
                readiness=readiness,
                definition=definition,
                preview_limit=effective_limit,
                blockers=blockers + ["insufficient_rows_for_horizon"],
                warnings=warnings,
                errors=errors,
                row_count=labels.row_count,
            )

        return _report_from_readiness(
            readiness=readiness,
            definition=definition,
            status="previewable",
            row_count=labels.row_count,
            available_label_count=labels.available_label_count,
            unavailable_label_count=labels.unavailable_label_count,
            first_available_ts_ms=labels.first_available_ts_ms,
            last_available_ts_ms=labels.last_available_ts_ms,
            preview_limit=effective_limit,
            sample_rows=_sample_rows(
                labels.rows,
                limit=effective_limit,
                unavailable_policy=str(definition.unavailable_policy),
            ),
            regression_stats=labels.regression_stats,
            class_distribution=labels.class_distribution,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            errors=tuple(errors),
        )

    def preview_future_return(
        self,
        *,
        market: MarketId,
        database_id: str,
        horizon_bars: int,
        preview_limit: int | None = None,
        return_mode: str = "simple",
    ) -> AnalysisSuiteTargetPreviewReport:
        """Preview a future-return regression target."""

        return self.preview_target(
            market=market,
            database_id=database_id,
            target_definition=AnalysisSuiteTargetDefinition.future_return(
                horizon_bars=horizon_bars,
                return_mode=return_mode,
            ),
            preview_limit=preview_limit,
        )

    def preview_future_direction(
        self,
        *,
        market: MarketId,
        database_id: str,
        horizon_bars: int,
        up_threshold: float,
        down_threshold: float | None = None,
        preview_limit: int | None = None,
    ) -> AnalysisSuiteTargetPreviewReport:
        """Preview a thresholded future-direction classification target."""

        return self.preview_target(
            market=market,
            database_id=database_id,
            target_definition=AnalysisSuiteTargetDefinition.future_direction(
                horizon_bars=horizon_bars,
                up_threshold=up_threshold,
                down_threshold=down_threshold,
            ),
            preview_limit=preview_limit,
        )

    def _blocked_report(
        self,
        *,
        readiness: object,
        definition: AnalysisSuiteTargetDefinition,
        preview_limit: int,
        blockers: Iterable[str],
        warnings: Iterable[str],
        errors: Iterable[str],
        row_count: int | None = None,
    ) -> AnalysisSuiteTargetPreviewReport:
        return _report_from_readiness(
            readiness=readiness,
            definition=definition,
            status="blocked",
            row_count=row_count,
            available_label_count=0,
            unavailable_label_count=0,
            first_available_ts_ms=None,
            last_available_ts_ms=None,
            preview_limit=preview_limit,
            sample_rows=(),
            regression_stats={},
            class_distribution={},
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            errors=tuple(errors),
        )

    def _error_report(
        self,
        *,
        readiness: object,
        definition: AnalysisSuiteTargetDefinition,
        preview_limit: int,
        blockers: Iterable[str],
        warnings: Iterable[str],
        errors: Iterable[str],
    ) -> AnalysisSuiteTargetPreviewReport:
        return _report_from_readiness(
            readiness=readiness,
            definition=definition,
            status="error",
            row_count=None,
            available_label_count=0,
            unavailable_label_count=0,
            first_available_ts_ms=None,
            last_available_ts_ms=None,
            preview_limit=preview_limit,
            sample_rows=(),
            regression_stats={},
            class_distribution={},
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            errors=tuple(errors),
        )

    def _readiness_error_report(
        self,
        *,
        market: MarketId,
        database_id: str,
        definition: AnalysisSuiteTargetDefinition,
        preview_limit: int,
        warnings: Iterable[str],
        exc: Exception,
    ) -> AnalysisSuiteTargetPreviewReport:
        readiness = _SyntheticReadiness(
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
            warnings=tuple(warnings),
            blockers=("readiness_check_failed",),
            errors=(f"{type(exc).__name__}: {exc}",),
        )
        return _report_from_readiness(
            readiness=readiness,
            definition=definition,
            status="error",
            row_count=None,
            available_label_count=0,
            unavailable_label_count=0,
            first_available_ts_ms=None,
            last_available_ts_ms=None,
            preview_limit=preview_limit,
            sample_rows=(),
            regression_stats={},
            class_distribution={},
            warnings=readiness.warnings,
            blockers=readiness.blockers,
            errors=readiness.errors,
        )


@dataclass(frozen=True)
class _SyntheticReadiness:
    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: str
    strict_ready: bool
    can_preview: bool
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _LabelRows:
    row_count: int
    available_label_count: int
    unavailable_label_count: int
    first_available_ts_ms: int | None
    last_available_ts_ms: int | None
    rows: tuple[dict[str, object], ...]
    regression_stats: dict[str, object]
    class_distribution: dict[str, int]


class _TargetPlannerBlocked(Exception):
    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(str(item) for item in blockers)
        super().__init__("; ".join(self.blockers))


def _coerce_definition(
    definition: AnalysisSuiteTargetDefinition | Mapping[str, object],
) -> AnalysisSuiteTargetDefinition:
    if isinstance(definition, AnalysisSuiteTargetDefinition):
        return definition
    return AnalysisSuiteTargetDefinition.from_dict(definition)


def _definition_for_database(
    definition: AnalysisSuiteTargetDefinition,
    *,
    readiness: object,
) -> AnalysisSuiteTargetDefinition:
    return replace(
        definition,
        database_id=str(getattr(readiness, "database_id", "")),
        exchange=str(getattr(readiness, "exchange", "")),
        market_type=str(getattr(readiness, "market_type", "")),
        symbol=str(getattr(readiness, "symbol", "")),
        timeframe=str(getattr(readiness, "timeframe", "")),
    )


def _definition_blockers(
    definition: AnalysisSuiteTargetDefinition,
    *,
    warnings: list[str],
) -> list[str]:
    blockers: list[str] = []
    if definition.schema_version != ANALYSIS_SUITE_TARGET_DEFINITION_SCHEMA_VERSION:
        blockers.append("unsupported_target_definition_schema")
    if definition.target_family not in {"future_return", "future_direction"}:
        blockers.append(f"unsupported_target_family: {definition.target_family}")
    if definition.unavailable_policy not in {"mark_unavailable", "drop"}:
        blockers.append(f"unsupported_unavailable_policy: {definition.unavailable_policy}")
    if _int_or_none(definition.horizon_bars) is None or int(definition.horizon_bars) <= 0:
        blockers.append("horizon_bars_must_be_positive")
    if definition.leakage_role != "target_only":
        blockers.append("target_definition_leakage_role_must_be_target_only")
    if not bool(definition.future_derived):
        blockers.append("target_definition_must_be_future_derived")
    if bool(definition.feature_eligible):
        blockers.append("target_definition_must_not_be_feature_eligible")

    if definition.target_family == "future_return":
        if definition.label_type != "regression":
            blockers.append("future_return_requires_regression_label_type")
        if str(definition.parameters.get("return_mode", "simple")) != "simple":
            blockers.append("unsupported_return_mode")
    if definition.target_family == "future_direction":
        if definition.label_type != "classification":
            blockers.append("future_direction_requires_classification_label_type")
        up_threshold = _float_or_none(definition.thresholds.get("up_threshold"))
        if up_threshold is None:
            blockers.append("future_direction_requires_up_threshold")
        elif up_threshold < 0:
            blockers.append("up_threshold_must_be_non_negative")
        down_threshold = _float_or_none(definition.thresholds.get("down_threshold"))
        if "down_threshold" not in definition.thresholds and up_threshold is not None:
            warnings.append("down_threshold_defaulted_to_up_threshold")
        elif down_threshold is None:
            blockers.append("down_threshold_must_be_numeric")
        elif down_threshold < 0:
            blockers.append("down_threshold_must_be_non_negative")
    return blockers


def _preview_limit_state(limit: int | None) -> tuple[int, int, tuple[str, ...]]:
    if limit is None:
        return DEFAULT_TARGET_PREVIEW_LIMIT, DEFAULT_TARGET_PREVIEW_LIMIT, ()
    requested = int(limit)
    if requested <= 0:
        return requested, DEFAULT_TARGET_PREVIEW_LIMIT, ("preview_limit_defaulted",)
    if requested > MAX_TARGET_PREVIEW_LIMIT:
        return requested, MAX_TARGET_PREVIEW_LIMIT, ("preview_limit_clamped_to_max",)
    return requested, requested, ()


def _read_target_dataframe(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0)
    columns = tuple(str(column) for column in header.columns)
    missing = [column for column in ("ts_ms", "close") if column not in columns]
    if missing:
        raise _TargetPlannerBlocked(
            f"missing_required_target_column: {column}" for column in missing
        )
    return pd.read_csv(path, usecols=["ts_ms", "close"])


def _compute_labels(
    *,
    frame: pd.DataFrame,
    definition: AnalysisSuiteTargetDefinition,
    warnings: list[str],
) -> _LabelRows:
    row_count = int(len(frame))
    horizon = int(definition.horizon_bars)
    ts_ms = pd.to_numeric(frame["ts_ms"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    future_close = close.shift(-horizon)
    label_end_ts_ms = ts_ms.shift(-horizon)
    future_return = (future_close - close) / close
    valid = (
        ts_ms.notna()
        & label_end_ts_ms.notna()
        & close.notna()
        & future_close.notna()
        & (close != 0)
        & future_return.notna()
    )
    valid = valid & future_return.map(_is_finite)

    invalid_denominator_count = int(((close == 0) & future_close.notna()).sum())
    if invalid_denominator_count:
        warnings.append(f"invalid_close_denominator_count: {invalid_denominator_count}")

    rows: list[dict[str, object]] = []
    if definition.target_family == "future_direction":
        labels = _direction_labels(
            future_return=future_return,
            valid=valid,
            definition=definition,
        )
    else:
        labels = pd.Series([None] * row_count)

    output_column = definition.output_column_name
    for index in range(row_count):
        available = bool(valid.iloc[index])
        label_value: object
        if definition.target_family == "future_direction":
            label_value = labels.iloc[index] if available else "unavailable"
        else:
            label_value = _json_safe_number(future_return.iloc[index]) if available else None
        rows.append(
            {
                "ts_ms": _json_safe_int(ts_ms.iloc[index]),
                "label_ts_ms": _json_safe_int(ts_ms.iloc[index]),
                "label_end_ts_ms": _json_safe_int(label_end_ts_ms.iloc[index]),
                "label_available": available,
                output_column: label_value,
                "close_t": _json_safe_number(close.iloc[index]),
                "close_t_plus_horizon": _json_safe_number(future_close.iloc[index]),
                "future_return": _json_safe_number(future_return.iloc[index]) if available else None,
            }
        )

    available_count = int(valid.sum())
    unavailable_count = row_count - available_count
    available_ts = tuple(
        _json_safe_int(ts_ms.iloc[index])
        for index in range(row_count)
        if bool(valid.iloc[index])
    )
    available_returns = tuple(
        float(future_return.iloc[index])
        for index in range(row_count)
        if bool(valid.iloc[index])
    )
    return _LabelRows(
        row_count=row_count,
        available_label_count=available_count,
        unavailable_label_count=unavailable_count,
        first_available_ts_ms=next((item for item in available_ts if item is not None), None),
        last_available_ts_ms=next((item for item in reversed(available_ts) if item is not None), None),
        rows=tuple(rows),
        regression_stats=(
            _regression_stats(available_returns)
            if definition.target_family == "future_return"
            else {}
        ),
        class_distribution=(
            _class_distribution(labels=labels, valid=valid)
            if definition.target_family == "future_direction"
            else {}
        ),
    )


def _direction_labels(
    *,
    future_return: pd.Series,
    valid: pd.Series,
    definition: AnalysisSuiteTargetDefinition,
) -> pd.Series:
    up_threshold = float(definition.thresholds.get("up_threshold", 0.0))
    down_threshold = float(definition.thresholds.get("down_threshold", up_threshold))
    values: list[str] = []
    for index in range(len(future_return)):
        if not bool(valid.iloc[index]):
            values.append("unavailable")
            continue
        value = float(future_return.iloc[index])
        if value >= up_threshold:
            values.append(str(definition.class_mapping.get("up", "up")))
        elif value <= -down_threshold:
            values.append(str(definition.class_mapping.get("down", "down")))
        else:
            values.append(str(definition.class_mapping.get("flat", "flat")))
    return pd.Series(values)


def _sample_rows(
    rows: Iterable[dict[str, object]],
    *,
    limit: int,
    unavailable_policy: str,
) -> tuple[dict[str, object], ...]:
    out: list[dict[str, object]] = []
    for row in rows:
        if unavailable_policy == "drop" and not bool(row.get("label_available", False)):
            continue
        out.append(dict(row))
        if len(out) >= limit:
            break
    return tuple(out)


def _regression_stats(values: tuple[float, ...]) -> dict[str, object]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": _json_safe_number(min(values)),
        "max": _json_safe_number(max(values)),
        "mean": _json_safe_number(sum(values) / len(values)),
    }


def _class_distribution(*, labels: pd.Series, valid: pd.Series) -> dict[str, int]:
    distribution = {"up": 0, "down": 0, "flat": 0, "unavailable": 0}
    for index in range(len(labels)):
        label = str(labels.iloc[index])
        if not bool(valid.iloc[index]):
            distribution["unavailable"] += 1
        elif label in distribution:
            distribution[label] += 1
        else:
            distribution[label] = distribution.get(label, 0) + 1
    return distribution


def _report_from_readiness(
    *,
    readiness: object,
    definition: AnalysisSuiteTargetDefinition,
    status: AnalysisSuiteTargetPreviewStatus,
    row_count: int | None,
    available_label_count: int,
    unavailable_label_count: int,
    first_available_ts_ms: int | None,
    last_available_ts_ms: int | None,
    preview_limit: int,
    sample_rows: Iterable[dict[str, object]],
    regression_stats: Mapping[str, object],
    class_distribution: Mapping[str, int],
    warnings: Iterable[str],
    blockers: Iterable[str],
    errors: Iterable[str],
) -> AnalysisSuiteTargetPreviewReport:
    rows_tuple = tuple(dict(row) for row in sample_rows)
    return AnalysisSuiteTargetPreviewReport(
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
        target_definition=definition,
        status=status,
        row_count=row_count,
        available_label_count=available_label_count,
        unavailable_label_count=unavailable_label_count,
        first_available_ts_ms=first_available_ts_ms,
        last_available_ts_ms=last_available_ts_ms,
        preview_limit=preview_limit,
        sample_rows=rows_tuple,
        regression_stats=dict(regression_stats),
        class_distribution=dict(class_distribution),
        leakage_summary=_leakage_summary(definition),
        warnings=tuple(str(item) for item in warnings),
        blockers=tuple(str(item) for item in blockers),
        errors=tuple(str(item) for item in errors),
    )


def _leakage_summary(definition: AnalysisSuiteTargetDefinition) -> dict[str, object]:
    return {
        "leakage_role": definition.leakage_role,
        "future_derived": bool(definition.future_derived),
        "feature_eligible": bool(definition.feature_eligible),
        "source_columns": list(definition.source_columns),
        "horizon_bars": int(definition.horizon_bars),
        "output_column_name": definition.output_column_name,
        "future_rows_used": f"t+1 through t+{definition.horizon_bars}",
        "feature_selection_policy": "exclude_target_outputs",
    }


def _json_safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe_value(value) for key, value in values.items()}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return _json_safe_number(value)
    return str(value)


def _json_safe_number(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _json_safe_int(value: object) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _is_finite(value: object) -> bool:
    numeric = _float_or_none(value)
    return numeric is not None
