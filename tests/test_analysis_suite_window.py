from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTableWidget,
)

from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow
from leonardo.gui.windows.window_manager import WindowManager


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


class _NoopAwaitable:
    def __await__(self):
        if False:
            yield None
        return None


class _FakeState:
    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []
        self.closed: list[str] = []

    def window_open(self, name: str, type_: str, *, where: str = "gui") -> _NoopAwaitable:
        _ = where
        self.opened.append((name, type_))
        return _NoopAwaitable()

    def window_close(self, name: str, *, where: str = "gui") -> _NoopAwaitable:
        _ = where
        self.closed.append(name)
        return _NoopAwaitable()


class _FakeCore:
    def __init__(self) -> None:
        self.submitted: list[object] = []

    def submit(self, coro: object) -> None:
        self.submitted.append(coro)


class _FakeReadinessService:
    def __init__(self, *, items=(), fail: bool = False) -> None:
        self.items = tuple(items)
        self.fail = fail
        self.calls = 0

    def list_analysis_datasets(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("catalog unavailable")
        return SimpleNamespace(
            total_count=len(self.items),
            ready_count=sum(1 for item in self.items if item.readiness_status == "ready"),
            blocked_count=sum(
                1
                for item in self.items
                if item.readiness_status
                in {"missing_dataframe", "incomplete_topology", "corrupt_dataframe", "blocked"}
            ),
            draft_count=sum(1 for item in self.items if item.readiness_status == "draft"),
            stale_count=sum(1 for item in self.items if item.readiness_status == "stale_source"),
            error_count=sum(1 for item in self.items if item.readiness_status in {"corrupt_manifest", "error"}),
            items=self.items,
        )


class _FakePreviewService:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls: list[dict[str, object]] = []

    def preview_for_database(
        self,
        *,
        market: object,
        database_id: str,
        mode: str = "head",
        row_limit: int | None = None,
    ) -> object:
        self.calls.append(
            {
                "market": market,
                "database_id": database_id,
                "mode": mode,
                "row_limit": row_limit,
            }
        )
        return self.report


class _FakeTargetPlanner:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls: list[dict[str, object]] = []

    def preview_target(
        self,
        *,
        market: object,
        database_id: str,
        target_definition: object,
        preview_limit: int | None = None,
    ) -> object:
        self.calls.append(
            {
                "market": market,
                "database_id": database_id,
                "target_definition": target_definition,
                "preview_limit": preview_limit,
            }
        )
        setattr(self.report, "target_definition", target_definition)
        return self.report


class _FakeFeatureSetPlanner:
    def __init__(self, *, candidates: tuple[object, ...]) -> None:
        self.candidates = candidates
        self.list_calls: list[dict[str, object]] = []
        self.preview_calls: list[dict[str, object]] = []

    def list_feature_candidates(
        self,
        *,
        market: object,
        database_id: str,
        target_definition: object | None = None,
        target_report: object | None = None,
    ) -> object:
        self.list_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "target_definition": target_definition,
                "target_report": target_report,
            }
        )
        return _feature_report(
            candidates=self.candidates,
            selected_columns=(),
            target_report=target_report,
        )

    def validate_selected_features(
        self,
        *,
        market: object,
        database_id: str,
        selected_columns: object,
        target_definition: object | None = None,
        target_report: object | None = None,
        name: str = "Feature set preview",
    ) -> object:
        selected = tuple(str(column) for column in selected_columns)
        self.preview_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "selected_columns": selected,
                "target_definition": target_definition,
                "target_report": target_report,
                "name": name,
            }
        )
        return _feature_report(
            candidates=self.candidates,
            selected_columns=selected,
            target_report=target_report,
        )


class _FakeDiagnosticService:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls: list[dict[str, object]] = []

    def build_report(
        self,
        *,
        readiness_report: object,
        target_report: object,
        feature_set_report: object,
    ) -> object:
        self.calls.append(
            {
                "readiness_report": readiness_report,
                "target_report": target_report,
                "feature_set_report": feature_set_report,
            }
        )
        return self.report


class _FakePoiFamilyPlanner:
    def __init__(self, *, occurrence_report: object, family_report: object) -> None:
        self.occurrence_report = occurrence_report
        self.family_report = family_report
        self.occurrence_calls: list[dict[str, object]] = []
        self.family_calls: list[dict[str, object]] = []

    def preview_poi_occurrences(
        self,
        *,
        market: object,
        database_id: str,
        poi_definition: object,
        sample_limit: int | None = None,
        readiness_report: object | None = None,
        diagnostic_report: object | None = None,
    ) -> object:
        self.occurrence_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "poi_definition": poi_definition,
                "sample_limit": sample_limit,
                "readiness_report": readiness_report,
                "diagnostic_report": diagnostic_report,
            }
        )
        return self.occurrence_report

    def preview_family(
        self,
        *,
        market: object,
        database_id: str,
        family_definition: object,
        sample_limit: int | None = None,
        readiness_report: object | None = None,
        diagnostic_report: object | None = None,
    ) -> object:
        self.family_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "family_definition": family_definition,
                "sample_limit": sample_limit,
                "readiness_report": readiness_report,
                "diagnostic_report": diagnostic_report,
            }
        )
        return self.family_report


class _FakeGenomePathBuilder:
    def __init__(self, *, validation_report: object, path_report: object) -> None:
        self.validation_report = validation_report
        self.path_report = path_report
        self.validation_calls: list[dict[str, object]] = []
        self.path_calls: list[dict[str, object]] = []
        self.poi_family_path_calls: list[dict[str, object]] = []

    def validate_encoding_definition(
        self,
        *,
        market: object,
        database_id: str,
        encoding_definition: object,
        readiness_report: object | None = None,
        diagnostic_report: object | None = None,
        feature_set_report: object | None = None,
    ) -> object:
        self.validation_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "encoding_definition": encoding_definition,
                "readiness_report": readiness_report,
                "diagnostic_report": diagnostic_report,
                "feature_set_report": feature_set_report,
            }
        )
        return self.validation_report

    def preview_paths(
        self,
        *,
        market: object,
        database_id: str,
        encoding_definition: object,
        sample_limit: int | None = None,
        anchor_rows: object | None = None,
        readiness_report: object | None = None,
        diagnostic_report: object | None = None,
        feature_set_report: object | None = None,
    ) -> object:
        self.path_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "encoding_definition": encoding_definition,
                "sample_limit": sample_limit,
                "anchor_rows": anchor_rows,
                "readiness_report": readiness_report,
                "diagnostic_report": diagnostic_report,
                "feature_set_report": feature_set_report,
            }
        )
        return self.path_report

    def preview_paths_for_poi_family(
        self,
        *,
        market: object,
        database_id: str,
        encoding_definition: object,
        family_report: object,
        sample_limit: int | None = None,
        readiness_report: object | None = None,
        diagnostic_report: object | None = None,
        feature_set_report: object | None = None,
    ) -> object:
        self.poi_family_path_calls.append(
            {
                "market": market,
                "database_id": database_id,
                "encoding_definition": encoding_definition,
                "family_report": family_report,
                "sample_limit": sample_limit,
                "readiness_report": readiness_report,
                "diagnostic_report": diagnostic_report,
                "feature_set_report": feature_set_report,
            }
        )
        return self.path_report


def _ctx(tmp_path: Path, state: _FakeState | None = None):
    return SimpleNamespace(
        config=SimpleNamespace(runtime=SimpleNamespace(data_dir=str(tmp_path))),
        state=state or _FakeState(),
    )


def _report(
    *,
    database_id: str,
    display_name: str,
    readiness_status: str,
    strict_ready: bool,
    can_preview: bool,
    source_ohlcv_drift_status: str = "current",
    geography_status: str = "complete",
    missing_topology=(),
    blockers=(),
    warnings=(),
    errors=(),
):
    return SimpleNamespace(
        database_id=database_id,
        display_name=display_name,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        manifest_status="materialized" if readiness_status == "ready" else readiness_status,
        materialization_status="present" if readiness_status != "draft" else "missing",
        dataframe_status="available" if can_preview else "missing",
        dataframe_path=f"C:/data/{database_id}/dataframe.csv",
        manifest_path=f"C:/data/{database_id}/manifest.json",
        readiness_status=readiness_status,
        strict_ready=strict_ready,
        can_preview=can_preview,
        row_count=100 if can_preview else None,
        column_count=12 if can_preview else None,
        first_ts_ms=1000 if can_preview else None,
        last_ts_ms=2000 if can_preview else None,
        source_ohlcv_drift_status=source_ohlcv_drift_status,
        geography_status=geography_status,
        missing_topology=tuple(missing_topology),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _preview_report(
    *,
    database_id: str = "adb_ready",
    status: str = "previewable",
    mode: str = "head",
    strict_ready: bool = True,
    can_preview: bool = True,
    blockers=(),
    warnings=(),
    errors=(),
):
    return SimpleNamespace(
        database_id=database_id,
        display_name=database_id,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        dataframe_path=f"C:/data/{database_id}/dataframe.csv",
        manifest_path=f"C:/data/{database_id}/manifest.json",
        readiness_status="ready" if strict_ready else "incomplete_topology",
        strict_ready=strict_ready,
        can_preview=can_preview,
        status=status,
        mode=mode,
        requested_limit=25,
        effective_limit=25,
        max_limit=500,
        total_row_count=100,
        total_column_count=3,
        returned_row_count=2,
        columns=("ts_ms", "ts_utc", "value"),
        rows=(
            {"ts_ms": 1000, "ts_utc": "1970-01-01 00:00:01 UTC", "value": "1.0"},
            {"ts_ms": 2000, "ts_utc": "1970-01-01 00:00:02 UTC", "value": None},
        )
        if status == "previewable"
        else (),
        preview_first_ts_ms=1000 if status == "previewable" else None,
        preview_last_ts_ms=2000 if status == "previewable" else None,
        dataset_first_ts_ms=1000,
        dataset_last_ts_ms=5000,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        errors=tuple(errors),
    )


def _target_preview_report(*, status: str = "previewable") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        target_definition=SimpleNamespace(
            target_family="future_return",
            label_type="regression",
            output_column_name="target_future_return_2",
            horizon_bars=2,
        ),
        row_count=12,
        available_label_count=10,
        unavailable_label_count=2,
        first_available_ts_ms=1000,
        last_available_ts_ms=10000,
        regression_stats={"count": 10, "mean": 0.12},
        class_distribution={},
        leakage_summary={
            "leakage_role": "target_only",
            "future_derived": True,
            "feature_eligible": False,
        },
        warnings=("target_warning",),
        blockers=(),
        errors=(),
    )


def _candidate(
    column_name: str,
    *,
    status: str = "eligible",
    group: str = "base_ohlc",
    feature_eligible: bool = True,
    blockers=(),
    warnings=(),
) -> SimpleNamespace:
    return SimpleNamespace(
        column_name=column_name,
        display_name=column_name,
        status=status,
        group=group,
        selected=False,
        selectable=True,
        analysis_usable=True,
        renderable=True,
        feature_eligible=feature_eligible,
        leakage_role="feature",
        future_derived=False,
        source_family="analysis_database",
        source_id=None,
        tool_key=None,
        tool_title=None,
        source_column_name=column_name,
        dtype="float64",
        nullable=False,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        metadata={},
    )


def _feature_report(
    *,
    candidates: tuple[object, ...],
    selected_columns: tuple[str, ...],
    target_report: object | None = None,
) -> SimpleNamespace:
    selected = tuple(
        candidate
        for candidate in candidates
        if getattr(candidate, "column_name", "") in selected_columns
        and getattr(candidate, "status", "") == "eligible"
    )
    rejected = tuple(
        candidate
        for candidate in candidates
        if getattr(candidate, "column_name", "") in selected_columns
        and getattr(candidate, "status", "") != "eligible"
    )
    return SimpleNamespace(
        status="blocked" if rejected else "previewable",
        total_candidate_count=len(candidates),
        eligible_count=sum(1 for candidate in candidates if getattr(candidate, "status", "") == "eligible"),
        blocked_count=sum(1 for candidate in candidates if getattr(candidate, "status", "") == "blocked"),
        warning_count=sum(1 for candidate in candidates if getattr(candidate, "status", "") == "warning"),
        selected_count=len(selected_columns),
        accepted_selected_count=len(selected),
        rejected_selected_count=len(rejected),
        candidates=candidates,
        selected_features=selected,
        rejected_features=rejected,
        group_summary={"base_ohlc": len(selected)},
        leakage_summary={
            "target_output_column": getattr(
                getattr(target_report, "target_definition", None),
                "output_column_name",
                None,
            )
        },
        warnings=("feature_warning",),
        blockers=tuple(
            f"selected_feature_rejected: {getattr(candidate, 'column_name', '')}"
            for candidate in rejected
        ),
        errors=(),
    )


def _diagnostic_report(*, status: str = "ready") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        readiness_status="ready",
        strict_ready=True,
        can_preview=True,
        row_count=12,
        column_count=6,
        target_family="future_return",
        target_output_column="target_future_return_2",
        horizon_bars=2,
        available_label_count=10,
        unavailable_label_count=2,
        label_availability_ratio=0.83,
        regression_stats={"count": 10, "mean": 0.12},
        class_distribution={},
        selected_feature_count=1,
        accepted_feature_count=1,
        rejected_feature_count=0,
        selected_features=("close",),
        rejected_features=(),
        group_summary={"base_ohlc": 1},
        has_leakage_blockers=False,
        leakage_summary={"has_leakage_blockers": False},
        feature_column_diagnostics=(
            SimpleNamespace(column_name="close", dtype="float64", null_ratio=0.0),
        ),
        warnings=(),
        blockers=(),
        errors=(),
    )


def _poi_occurrence(
    *,
    row_index: int = 4,
    ts_ms: int = 4000,
    poi_key: str = "poi_preview",
    source_column: str = "peak_marker",
    source_value: object = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        row_index=row_index,
        ts_ms=ts_ms,
        anchor_ts_ms=ts_ms,
        event_ts_ms=ts_ms,
        knowable_at_ts_ms=ts_ms,
        poi_key=poi_key,
        poi_type="gui_preview",
        source_column=source_column,
        source_value=source_value,
        metadata={"event_kind": "sparse_event"},
    )


def _poi_occurrence_report(*, status: str = "ready") -> SimpleNamespace:
    occurrence = _poi_occurrence()
    return SimpleNamespace(
        status=status,
        row_count=20,
        occurrence_count=3,
        first_occurrence_ts_ms=4000,
        last_occurrence_ts_ms=12000,
        requested_sample_limit=100,
        sample_limit=100,
        sample_occurrences=(occurrence,),
        warnings=("poi_warning",),
        blockers=(),
        errors=(),
    )


def _poi_family_report(*, status: str = "ready") -> SimpleNamespace:
    occurrence = _poi_occurrence()
    return SimpleNamespace(
        status=status,
        row_count=20,
        occurrence_count=3,
        matched_count=2,
        unmatched_count=1,
        first_occurrence_ts_ms=4000,
        last_occurrence_ts_ms=12000,
        requested_sample_limit=100,
        sample_limit=100,
        sample_memberships=(
            SimpleNamespace(
                occurrence=occurrence,
                matched=True,
                condition_results=(
                    {
                        "column": "rsi_14",
                        "operator": "gte",
                        "value": 50,
                        "actual_value": 61,
                        "matched": True,
                    },
                ),
                blockers=(),
                warnings=(),
            ),
        ),
        warnings=("family_warning",),
        blockers=(),
        errors=(),
    )


def _genome_validation_report(*, status: str = "ready") -> dict[str, object]:
    return {
        "status": status,
        "warnings": ("genome_warning",),
        "blockers": (),
        "errors": (),
    }


def _genome_path_report(*, status: str = "ready") -> SimpleNamespace:
    snapshot = SimpleNamespace(
        row_index=4,
        ts_ms=4000,
        components={"close_value": 101.5},
        component_metadata={},
        blockers=(),
        warnings=(),
    )
    path = SimpleNamespace(
        anchor_row_index=4,
        anchor_ts_ms=4000,
        anchor_kind="row",
        snapshots=(snapshot,),
        blockers=(),
        warnings=(),
    )
    return SimpleNamespace(
        status=status,
        row_count=20,
        path_count=7,
        requested_sample_limit=100,
        sample_limit=100,
        sample_paths=(path,),
        warnings=("path_warning",),
        blockers=(),
        errors=(),
    )


def test_analysis_suite_window_constructs_and_populates_readiness_rows(tmp_path: Path) -> None:
    _qapp()
    service = _FakeReadinessService(
        items=(
            _report(
                database_id="adb_ready",
                display_name="ReadyDB",
                readiness_status="ready",
                strict_ready=True,
                can_preview=True,
            ),
            _report(
                database_id="adb_incomplete",
                display_name="IncompleteDB",
                readiness_status="incomplete_topology",
                strict_ready=False,
                can_preview=True,
                geography_status="incomplete",
                missing_topology=("volume_artifact", "utc"),
                blockers=("missing_topology: volume_artifact, utc",),
            ),
            _report(
                database_id="adb_draft",
                display_name="DraftDB",
                readiness_status="draft",
                strict_ready=False,
                can_preview=False,
                source_ohlcv_drift_status="not_checked",
                geography_status="incomplete",
                missing_topology=("braids",),
                blockers=("database_not_materialized",),
            ),
            _report(
                database_id="adb_stale",
                display_name="StaleDB",
                readiness_status="stale_source",
                strict_ready=False,
                can_preview=True,
                source_ohlcv_drift_status="source_drift",
                blockers=("source_ohlcv_drift: row_count_changed",),
            ),
            _report(
                database_id="adb_corrupt",
                display_name="CorruptDB",
                readiness_status="corrupt_manifest",
                strict_ready=False,
                can_preview=False,
                source_ohlcv_drift_status="not_checked",
                geography_status="unknown",
                blockers=("manifest_unreadable",),
                errors=("JSONDecodeError: bad manifest",),
            ),
        )
    )

    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=service,
    )

    table = window.findChild(QTableWidget, "analysisSuiteCatalogTable")
    details = window.findChild(QPlainTextEdit, "analysisSuiteDetailsText")
    assert table is not None
    assert details is not None
    assert table.rowCount() == 5
    assert table.item(0, 0).text() == "ReadyDB"
    assert table.item(0, 1).text() == "ready"
    assert table.item(1, 1).text() == "incomplete_topology"
    assert [table.item(row, 1).text() for row in range(table.rowCount())] == [
        "ready",
        "incomplete_topology",
        "draft",
        "stale_source",
        "corrupt_manifest",
    ]

    table.selectRow(1)
    assert "Database ID: adb_incomplete" in details.toPlainText()
    assert "Missing topology:" in details.toPlainText()
    assert "- volume_artifact" in details.toPlainText()
    assert "missing_topology: volume_artifact, utc" in details.toPlainText()
    assert service.calls == 1


def test_analysis_suite_window_preview_controls_exist(tmp_path: Path) -> None:
    _qapp()
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
        preview_service=_FakePreviewService(_preview_report()),
    )

    mode = window.findChild(QComboBox, "analysisSuitePreviewModeCombo")
    row_limit = window.findChild(QSpinBox, "analysisSuitePreviewRowLimitSpin")
    button = window.findChild(QPushButton, "analysisSuitePreviewButton")
    table = window.findChild(QTableWidget, "analysisSuitePreviewTable")
    summary = window.findChild(QPlainTextEdit, "analysisSuitePreviewSummaryText")

    assert mode is not None
    assert [mode.itemText(index) for index in range(mode.count())] == ["Head", "Tail"]
    assert row_limit is not None
    assert row_limit.value() == 100
    assert row_limit.maximum() >= 500
    assert button is not None
    assert button.text() == "Preview Dataframe"
    assert button.isEnabled() is False
    assert table is not None
    assert table.isSortingEnabled() is False
    assert summary is not None
    assert summary.isReadOnly() is True


def test_analysis_suite_window_target_feature_diagnostic_controls_exist(tmp_path: Path) -> None:
    _qapp()
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
        target_service=_FakeTargetPlanner(_target_preview_report()),
        feature_set_service=_FakeFeatureSetPlanner(candidates=()),
        diagnostic_service=_FakeDiagnosticService(_diagnostic_report()),
    )

    tabs = window.findChild(QTabWidget, "analysisSuiteSetupTabs")
    family = window.findChild(QComboBox, "analysisSuiteTargetFamilyCombo")
    horizon = window.findChild(QSpinBox, "analysisSuiteTargetHorizonSpin")
    up_threshold = window.findChild(QDoubleSpinBox, "analysisSuiteTargetUpThresholdSpin")
    down_threshold = window.findChild(QDoubleSpinBox, "analysisSuiteTargetDownThresholdSpin")
    target_button = window.findChild(QPushButton, "analysisSuiteTargetPreviewButton")
    feature_table = window.findChild(QTableWidget, "analysisSuiteFeatureCandidateTable")
    feature_button = window.findChild(QPushButton, "analysisSuiteFeaturePreviewButton")
    diagnostic_button = window.findChild(QPushButton, "analysisSuiteDiagnosticButton")

    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Data Preview",
        "Target Preview",
        "Feature Set",
        "Diagnostic Report",
        "POI / Family Preview",
        "Genome Path Preview",
    ]
    assert family is not None
    assert [family.itemText(index) for index in range(family.count())] == [
        "Future return regression",
        "Future direction classification",
    ]
    assert horizon is not None
    assert horizon.minimum() == 1
    assert up_threshold is not None
    assert down_threshold is not None
    assert target_button is not None
    assert target_button.isEnabled() is False
    assert feature_table is not None
    assert feature_table.columnCount() == 6
    assert feature_button is not None
    assert feature_button.isEnabled() is False
    assert diagnostic_button is not None
    assert diagnostic_button.isEnabled() is False


def test_analysis_suite_window_poi_family_controls_exist(tmp_path: Path) -> None:
    _qapp()
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
        poi_family_service=_FakePoiFamilyPlanner(
            occurrence_report=_poi_occurrence_report(),
            family_report=_poi_family_report(),
        ),
    )

    poi_key = window.findChild(QLineEdit, "analysisSuitePoiKeyEdit")
    source = window.findChild(QComboBox, "analysisSuitePoiSourceColumnCombo")
    event_kind = window.findChild(QComboBox, "analysisSuitePoiEventKindCombo")
    event_value = window.findChild(QLineEdit, "analysisSuitePoiEventValueEdit")
    previous_value = window.findChild(QLineEdit, "analysisSuitePoiPreviousValueEdit")
    poi_button = window.findChild(QPushButton, "analysisSuitePoiPreviewButton")
    condition_table = window.findChild(QTableWidget, "analysisSuitePoiConditionTable")
    add_condition = window.findChild(QPushButton, "analysisSuitePoiAddConditionButton")
    family_button = window.findChild(QPushButton, "analysisSuitePoiFamilyPreviewButton")
    poi_report = window.findChild(QPlainTextEdit, "analysisSuitePoiReportText")
    family_report = window.findChild(QPlainTextEdit, "analysisSuitePoiFamilyReportText")

    assert poi_key is not None
    assert poi_key.text() == "poi_preview"
    assert source is not None
    assert source.isEditable() is True
    assert event_kind is not None
    assert [event_kind.itemData(index) for index in range(event_kind.count())] == [
        "sparse_event",
        "boolean_true",
        "value_equals",
        "transition",
    ]
    assert event_value is not None
    assert event_value.isEnabled() is False
    assert previous_value is not None
    assert previous_value.isEnabled() is False
    assert poi_button is not None
    assert poi_button.isEnabled() is False
    assert condition_table is not None
    assert condition_table.columnCount() == 8
    assert add_condition is not None
    assert family_button is not None
    assert family_button.isEnabled() is False
    assert poi_report is not None
    assert poi_report.isReadOnly() is True
    assert family_report is not None
    assert family_report.isReadOnly() is True


def test_analysis_suite_window_genome_path_controls_exist(tmp_path: Path) -> None:
    _qapp()
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
        genome_path_service=_FakeGenomePathBuilder(
            validation_report=_genome_validation_report(),
            path_report=_genome_path_report(),
        ),
    )

    encoding_key = window.findChild(QLineEdit, "analysisSuiteGenomeEncodingKeyEdit")
    display_name = window.findChild(QLineEdit, "analysisSuiteGenomeEncodingDisplayNameEdit")
    path_length = window.findChild(QSpinBox, "analysisSuiteGenomePathLengthSpin")
    anchor_mode = window.findChild(QComboBox, "analysisSuiteGenomeAnchorModeCombo")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    remove_component = window.findChild(
        QPushButton,
        "analysisSuiteGenomeRemoveComponentButton",
    )
    validate_button = window.findChild(QPushButton, "analysisSuiteGenomeValidateButton")
    row_preview_button = window.findChild(
        QPushButton,
        "analysisSuiteGenomeRowPreviewButton",
    )
    poi_preview_button = window.findChild(
        QPushButton,
        "analysisSuiteGenomePoiFamilyPreviewButton",
    )
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")

    assert encoding_key is not None
    assert encoding_key.text() == "genome_preview"
    assert display_name is not None
    assert display_name.text() == "Genome preview"
    assert path_length is not None
    assert path_length.minimum() == 1
    assert anchor_mode is not None
    assert [anchor_mode.itemData(index) for index in range(anchor_mode.count())] == [
        "row",
        "poi_occurrence",
    ]
    assert component_table is not None
    assert component_table.columnCount() == 8
    assert add_component is not None
    assert remove_component is not None
    assert validate_button is not None
    assert validate_button.isEnabled() is False
    assert row_preview_button is not None
    assert row_preview_button.isEnabled() is False
    assert poi_preview_button is not None
    assert poi_preview_button.isEnabled() is False
    assert report_text is not None
    assert report_text.isReadOnly() is True


def test_analysis_suite_window_target_preview_calls_as5_service(tmp_path: Path) -> None:
    _qapp()
    target_service = _FakeTargetPlanner(_target_preview_report())
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        target_service=target_service,
        feature_set_service=_FakeFeatureSetPlanner(candidates=()),
        diagnostic_service=_FakeDiagnosticService(_diagnostic_report()),
    )

    family = window.findChild(QComboBox, "analysisSuiteTargetFamilyCombo")
    horizon = window.findChild(QSpinBox, "analysisSuiteTargetHorizonSpin")
    button = window.findChild(QPushButton, "analysisSuiteTargetPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteTargetReportText")
    assert family is not None
    assert horizon is not None
    assert button is not None
    assert report_text is not None

    family.setCurrentIndex(1)
    horizon.setValue(2)
    button.click()

    assert len(target_service.calls) == 1
    call = target_service.calls[0]
    assert call["database_id"] == "adb_ready"
    definition = call["target_definition"]
    assert getattr(definition, "target_family") == "future_direction"
    assert getattr(definition, "label_type") == "classification"
    assert getattr(definition, "horizon_bars") == 2
    assert getattr(definition, "future_derived") is True
    assert getattr(definition, "feature_eligible") is False

    text = report_text.toPlainText()
    assert "Status: previewable" in text
    assert "Available labels: 10" in text
    assert "Leakage metadata:" in text
    assert "target_warning" in text


def test_analysis_suite_window_preview_button_follows_can_preview(tmp_path: Path) -> None:
    _qapp()
    service = _FakeReadinessService(
        items=(
            _report(
                database_id="adb_ready",
                display_name="ReadyDB",
                readiness_status="ready",
                strict_ready=True,
                can_preview=True,
            ),
            _report(
                database_id="adb_draft",
                display_name="DraftDB",
                readiness_status="draft",
                strict_ready=False,
                can_preview=False,
                blockers=("database_not_materialized",),
            ),
        )
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=service,
        preview_service=_FakePreviewService(_preview_report()),
    )

    table = window.findChild(QTableWidget, "analysisSuiteCatalogTable")
    button = window.findChild(QPushButton, "analysisSuitePreviewButton")
    summary = window.findChild(QPlainTextEdit, "analysisSuitePreviewSummaryText")
    assert table is not None
    assert button is not None
    assert summary is not None

    assert button.isEnabled() is True
    table.selectRow(1)
    assert button.isEnabled() is False
    assert "database_not_materialized" in summary.toPlainText()
    table.selectRow(0)
    assert button.isEnabled() is True


def test_analysis_suite_window_preview_calls_service_and_renders_table(tmp_path: Path) -> None:
    _qapp()
    preview_service = _FakePreviewService(
        _preview_report(
            strict_ready=False,
            warnings=("non_strict_preview",),
            blockers=("missing_topology: utc",),
        )
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="incomplete_topology",
                    strict_ready=False,
                    can_preview=True,
                ),
            )
        ),
        preview_service=preview_service,
    )

    mode = window.findChild(QComboBox, "analysisSuitePreviewModeCombo")
    row_limit = window.findChild(QSpinBox, "analysisSuitePreviewRowLimitSpin")
    button = window.findChild(QPushButton, "analysisSuitePreviewButton")
    preview_table = window.findChild(QTableWidget, "analysisSuitePreviewTable")
    summary = window.findChild(QPlainTextEdit, "analysisSuitePreviewSummaryText")
    assert mode is not None
    assert row_limit is not None
    assert button is not None
    assert preview_table is not None
    assert summary is not None

    mode.setCurrentIndex(1)
    row_limit.setValue(25)
    button.click()

    assert len(preview_service.calls) == 1
    call = preview_service.calls[0]
    market = call["market"]
    assert getattr(market, "exchange") == "bybit"
    assert getattr(market, "market_type") == "linear"
    assert getattr(market, "symbol") == "BTCUSDT"
    assert getattr(market, "timeframe") == "30m"
    assert call["database_id"] == "adb_ready"
    assert call["mode"] == "tail"
    assert call["row_limit"] == 25

    assert preview_table.rowCount() == 2
    assert preview_table.columnCount() == 3
    assert preview_table.horizontalHeaderItem(0).text() == "ts_ms"
    assert preview_table.item(0, 0).text() == "1000"
    assert preview_table.item(1, 2).text() == "-"
    assert preview_table.editTriggers() == QTableWidget.NoEditTriggers

    summary_text = summary.toPlainText()
    assert "Status: previewable" in summary_text
    assert "Requested limit: 25" in summary_text
    assert "Effective limit: 25" in summary_text
    assert "Returned rows: 2" in summary_text
    assert "Strict ready: No" in summary_text
    assert "non_strict_preview" in summary_text
    assert "missing_topology: utc" in summary_text


def test_analysis_suite_window_displays_blocked_preview_report(tmp_path: Path) -> None:
    _qapp()
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        preview_service=_FakePreviewService(
            _preview_report(
                status="blocked",
                blockers=("dataset_not_previewable",),
                errors=("preview refused",),
            )
        ),
    )

    button = window.findChild(QPushButton, "analysisSuitePreviewButton")
    preview_table = window.findChild(QTableWidget, "analysisSuitePreviewTable")
    summary = window.findChild(QPlainTextEdit, "analysisSuitePreviewSummaryText")
    assert button is not None
    assert preview_table is not None
    assert summary is not None

    button.click()

    assert preview_table.rowCount() == 0
    assert "Status: blocked" in summary.toPlainText()
    assert "dataset_not_previewable" in summary.toPlainText()
    assert "preview refused" in summary.toPlainText()


def test_analysis_suite_window_feature_candidate_selection_calls_as6_service(tmp_path: Path) -> None:
    _qapp()
    feature_service = _FakeFeatureSetPlanner(
        candidates=(
            _candidate("close"),
            _candidate("rsi_14", group="oscillators"),
            _candidate(
                "target_future_return_2",
                status="blocked",
                group="target",
                feature_eligible=False,
                blockers=("target_only",),
            ),
        )
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        target_service=_FakeTargetPlanner(_target_preview_report()),
        feature_set_service=feature_service,
        diagnostic_service=_FakeDiagnosticService(_diagnostic_report()),
    )

    list_button = window.findChild(QPushButton, "analysisSuiteFeatureRefreshButton")
    select_all = window.findChild(QPushButton, "analysisSuiteFeatureSelectAllEligibleButton")
    preview_button = window.findChild(QPushButton, "analysisSuiteFeaturePreviewButton")
    table = window.findChild(QTableWidget, "analysisSuiteFeatureCandidateTable")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteFeatureReportText")
    assert list_button is not None
    assert select_all is not None
    assert preview_button is not None
    assert table is not None
    assert report_text is not None

    list_button.click()

    assert len(feature_service.list_calls) == 1
    assert table.rowCount() == 3
    assert table.item(0, 1).text() == "close"
    assert table.item(2, 2).text() == "blocked"
    assert "target_only" in table.item(2, 4).text()

    select_all.click()

    assert table.item(0, 0).checkState() == Qt.Checked
    assert table.item(1, 0).checkState() == Qt.Checked
    assert table.item(2, 0).checkState() == Qt.Unchecked
    assert preview_button.isEnabled() is True

    preview_button.click()

    assert len(feature_service.preview_calls) == 1
    assert feature_service.preview_calls[0]["selected_columns"] == ("close", "rsi_14")
    text = report_text.toPlainText()
    assert "Status: previewable" in text
    assert "Accepted features:" in text
    assert "close" in text
    assert "rsi_14" in text


def test_analysis_suite_window_poi_preview_calls_as8_service(tmp_path: Path) -> None:
    _qapp()
    feature_service = _FakeFeatureSetPlanner(
        candidates=(
            _candidate("peak_marker", group="events"),
            _candidate("rsi_14", group="oscillators"),
        )
    )
    poi_service = _FakePoiFamilyPlanner(
        occurrence_report=_poi_occurrence_report(),
        family_report=_poi_family_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        feature_set_service=feature_service,
        poi_family_service=poi_service,
    )

    list_button = window.findChild(QPushButton, "analysisSuiteFeatureRefreshButton")
    source = window.findChild(QComboBox, "analysisSuitePoiSourceColumnCombo")
    event_kind = window.findChild(QComboBox, "analysisSuitePoiEventKindCombo")
    button = window.findChild(QPushButton, "analysisSuitePoiPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuitePoiReportText")
    assert list_button is not None
    assert source is not None
    assert event_kind is not None
    assert button is not None
    assert report_text is not None

    list_button.click()
    assert [source.itemText(index) for index in range(source.count())] == [
        "peak_marker",
        "rsi_14",
    ]
    source.setCurrentText("peak_marker")
    event_kind.setCurrentIndex(0)
    button.click()

    assert len(poi_service.occurrence_calls) == 1
    call = poi_service.occurrence_calls[0]
    assert call["database_id"] == "adb_ready"
    assert call["readiness_report"] is not None
    definition = call["poi_definition"]
    assert getattr(definition, "poi_key") == "poi_preview"
    assert getattr(definition, "poi_type") == "gui_preview"
    assert getattr(definition, "source_column") == "peak_marker"
    assert getattr(definition, "event_kind") == "sparse_event"

    text = report_text.toPlainText()
    assert "Status: ready" in text
    assert "Occurrence count: 3" in text
    assert "peak_marker" in text
    assert "poi_warning" in text


def test_analysis_suite_window_family_preview_calls_as8_service(tmp_path: Path) -> None:
    _qapp()
    poi_service = _FakePoiFamilyPlanner(
        occurrence_report=_poi_occurrence_report(),
        family_report=_poi_family_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        poi_family_service=poi_service,
    )

    source = window.findChild(QComboBox, "analysisSuitePoiSourceColumnCombo")
    event_kind = window.findChild(QComboBox, "analysisSuitePoiEventKindCombo")
    event_value = window.findChild(QLineEdit, "analysisSuitePoiEventValueEdit")
    add_condition = window.findChild(QPushButton, "analysisSuitePoiAddConditionButton")
    condition_table = window.findChild(QTableWidget, "analysisSuitePoiConditionTable")
    button = window.findChild(QPushButton, "analysisSuitePoiFamilyPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuitePoiFamilyReportText")
    assert source is not None
    assert event_kind is not None
    assert event_value is not None
    assert add_condition is not None
    assert condition_table is not None
    assert button is not None
    assert report_text is not None

    source.setEditText("peak_marker")
    event_kind.setCurrentIndex(2)
    event_value.setText("1")
    add_condition.click()
    condition_table.item(0, 1).setText("rsi_14")
    condition_table.item(0, 2).setText("gte")
    condition_table.item(0, 3).setText("50")
    condition_table.item(0, 5).setText("1")
    condition_table.item(0, 7).setText("rsi confirmation")
    button.click()

    assert len(poi_service.family_calls) == 1
    call = poi_service.family_calls[0]
    assert call["database_id"] == "adb_ready"
    definition = call["family_definition"]
    assert getattr(definition, "family_key") == "poi_family_preview"
    assert getattr(definition.poi_definition, "source_column") == "peak_marker"
    assert getattr(definition.poi_definition, "event_kind") == "value_equals"
    assert getattr(definition.poi_definition, "event_value") == 1
    assert len(definition.conditions) == 1
    condition = definition.conditions[0]
    assert condition.column == "rsi_14"
    assert condition.operator == "gte"
    assert condition.value == 50
    assert condition.lookback_bars == 1
    assert condition.required is True
    assert condition.label == "rsi confirmation"

    text = report_text.toPlainText()
    assert "Status: ready" in text
    assert "Matched count: 2" in text
    assert "Unmatched count: 1" in text
    assert "rsi_14" in text
    assert "family_warning" in text


def test_analysis_suite_window_genome_validation_calls_as9_service(tmp_path: Path) -> None:
    _qapp()
    feature_service = _FakeFeatureSetPlanner(candidates=(_candidate("close"),))
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        feature_set_service=feature_service,
        genome_path_service=genome_service,
    )

    list_button = window.findChild(QPushButton, "analysisSuiteFeatureRefreshButton")
    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    validate_button = window.findChild(QPushButton, "analysisSuiteGenomeValidateButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")
    assert list_button is not None
    assert add_component is not None
    assert component_table is not None
    assert validate_button is not None
    assert report_text is not None

    list_button.click()
    add_component.click()
    assert component_table.item(0, 2).text() == "close"
    component_table.item(0, 1).setText("close_variation")
    component_table.item(0, 3).setText("variation_direction")
    component_table.item(0, 5).setText("2")
    validate_button.click()

    assert len(genome_service.validation_calls) == 1
    call = genome_service.validation_calls[0]
    assert call["database_id"] == "adb_ready"
    assert call["readiness_report"] is not None
    definition = call["encoding_definition"]
    assert getattr(definition, "encoding_key") == "genome_preview"
    assert getattr(definition, "path_length_bars") == 12
    assert getattr(definition, "anchor") == "row"
    assert len(definition.components) == 1
    component = definition.components[0]
    assert component.component_key == "close_variation"
    assert component.source_column == "close"
    assert component.encoding == "variation_direction"
    assert component.lookback_bars == 2

    text = report_text.toPlainText()
    assert "Status: ready" in text
    assert "genome_warning" in text


def test_analysis_suite_window_genome_row_preview_calls_as9_service(tmp_path: Path) -> None:
    _qapp()
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        genome_path_service=genome_service,
    )

    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    preview_button = window.findChild(QPushButton, "analysisSuiteGenomeRowPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")
    assert add_component is not None
    assert component_table is not None
    assert preview_button is not None
    assert report_text is not None

    add_component.click()
    component_table.item(0, 1).setText("close_value")
    component_table.item(0, 2).setText("close")
    preview_button.click()

    assert len(genome_service.path_calls) == 1
    call = genome_service.path_calls[0]
    assert call["database_id"] == "adb_ready"
    assert call["anchor_rows"] is None
    definition = call["encoding_definition"]
    assert getattr(definition, "anchor") == "row"
    assert definition.components[0].source_column == "close"

    text = report_text.toPlainText()
    assert "Status: ready" in text
    assert "Path count: 7" in text
    assert "close_value=101.5" in text
    assert "path_warning" in text


def test_analysis_suite_window_genome_static_bin_config_is_passed_to_as9(
    tmp_path: Path,
) -> None:
    _qapp()
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        genome_path_service=genome_service,
    )

    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    validate_button = window.findChild(QPushButton, "analysisSuiteGenomeValidateButton")
    assert add_component is not None
    assert component_table is not None
    assert validate_button is not None

    add_component.click()
    component_table.item(0, 1).setText("rsi_bin")
    component_table.item(0, 2).setText("rsi_14")
    component_table.item(0, 3).setText("static_bin")
    component_table.item(0, 4).setText("low:-inf:30;middle:30:70;high:70:inf")
    validate_button.click()

    component = genome_service.validation_calls[0]["encoding_definition"].components[0]
    assert [rule.label for rule in component.bins] == ["low", "middle", "high"]
    assert component.bins[0].lower is None
    assert component.bins[0].upper == 30.0
    assert component.bins[2].lower == 70.0
    assert component.bins[2].upper is None


def test_analysis_suite_window_genome_poi_family_preview_uses_current_as8_report(
    tmp_path: Path,
) -> None:
    _qapp()
    poi_service = _FakePoiFamilyPlanner(
        occurrence_report=_poi_occurrence_report(),
        family_report=_poi_family_report(),
    )
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        poi_family_service=poi_service,
        genome_path_service=genome_service,
    )

    poi_source = window.findChild(QComboBox, "analysisSuitePoiSourceColumnCombo")
    family_button = window.findChild(QPushButton, "analysisSuitePoiFamilyPreviewButton")
    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    genome_button = window.findChild(QPushButton, "analysisSuiteGenomePoiFamilyPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")
    assert poi_source is not None
    assert family_button is not None
    assert add_component is not None
    assert component_table is not None
    assert genome_button is not None
    assert report_text is not None

    poi_source.setEditText("peak_marker")
    family_button.click()
    add_component.click()
    component_table.item(0, 1).setText("rsi_value")
    component_table.item(0, 2).setText("rsi_14")
    genome_button.click()

    assert len(poi_service.family_calls) == 1
    assert len(genome_service.poi_family_path_calls) == 1
    call = genome_service.poi_family_path_calls[0]
    assert call["database_id"] == "adb_ready"
    assert call["family_report"] is poi_service.family_report
    assert call["encoding_definition"].anchor == "poi_occurrence"
    assert "Path count: 7" in report_text.toPlainText()


def test_analysis_suite_window_genome_poi_family_preview_requires_as8_report(
    tmp_path: Path,
) -> None:
    _qapp()
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        genome_path_service=genome_service,
    )

    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    genome_button = window.findChild(QPushButton, "analysisSuiteGenomePoiFamilyPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")
    assert add_component is not None
    assert component_table is not None
    assert genome_button is not None
    assert report_text is not None

    add_component.click()
    component_table.item(0, 1).setText("close_value")
    component_table.item(0, 2).setText("close")
    genome_button.click()

    assert genome_service.poi_family_path_calls == []
    assert "Preview a current POI family" in report_text.toPlainText()


def test_analysis_suite_window_clears_poi_family_state_when_inputs_change(tmp_path: Path) -> None:
    _qapp()
    poi_service = _FakePoiFamilyPlanner(
        occurrence_report=_poi_occurrence_report(),
        family_report=_poi_family_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
                _report(
                    database_id="adb_other",
                    display_name="OtherDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        poi_family_service=poi_service,
    )

    catalog = window.findChild(QTableWidget, "analysisSuiteCatalogTable")
    source = window.findChild(QComboBox, "analysisSuitePoiSourceColumnCombo")
    poi_button = window.findChild(QPushButton, "analysisSuitePoiPreviewButton")
    family_button = window.findChild(QPushButton, "analysisSuitePoiFamilyPreviewButton")
    add_condition = window.findChild(QPushButton, "analysisSuitePoiAddConditionButton")
    condition_table = window.findChild(QTableWidget, "analysisSuitePoiConditionTable")
    poi_text = window.findChild(QPlainTextEdit, "analysisSuitePoiReportText")
    family_text = window.findChild(QPlainTextEdit, "analysisSuitePoiFamilyReportText")
    assert catalog is not None
    assert source is not None
    assert poi_button is not None
    assert family_button is not None
    assert add_condition is not None
    assert condition_table is not None
    assert poi_text is not None
    assert family_text is not None

    source.setEditText("peak_marker")
    poi_button.click()
    family_button.click()
    assert "Occurrence count: 3" in poi_text.toPlainText()
    assert "Matched count: 2" in family_text.toPlainText()

    source.setEditText("other_marker")
    assert "POI definition changed" in poi_text.toPlainText()
    assert "POI definition changed" in family_text.toPlainText()

    poi_button.click()
    family_button.click()
    add_condition.click()
    condition_table.item(0, 1).setText("rsi_14")
    assert "Family definition changed" in family_text.toPlainText()

    catalog.selectRow(1)
    assert "Select a previewable Analysis Database" in poi_text.toPlainText()
    assert "Preview POI occurrences before family membership" in family_text.toPlainText()


def test_analysis_suite_window_clears_genome_state_when_inputs_change(tmp_path: Path) -> None:
    _qapp()
    genome_service = _FakeGenomePathBuilder(
        validation_report=_genome_validation_report(),
        path_report=_genome_path_report(),
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
                _report(
                    database_id="adb_other",
                    display_name="OtherDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        genome_path_service=genome_service,
    )

    catalog = window.findChild(QTableWidget, "analysisSuiteCatalogTable")
    add_component = window.findChild(QPushButton, "analysisSuiteGenomeAddComponentButton")
    component_table = window.findChild(QTableWidget, "analysisSuiteGenomeComponentTable")
    preview_button = window.findChild(QPushButton, "analysisSuiteGenomeRowPreviewButton")
    report_text = window.findChild(QPlainTextEdit, "analysisSuiteGenomePathReportText")
    assert catalog is not None
    assert add_component is not None
    assert component_table is not None
    assert preview_button is not None
    assert report_text is not None

    add_component.click()
    component_table.item(0, 1).setText("close_value")
    component_table.item(0, 2).setText("close")
    preview_button.click()
    assert "Path count: 7" in report_text.toPlainText()

    component_table.item(0, 2).setText("rsi_14")
    assert "Genome encoding changed" in report_text.toPlainText()

    preview_button.click()
    assert "Path count: 7" in report_text.toPlainText()

    catalog.selectRow(1)
    assert "Add at least one genome component" in report_text.toPlainText()


def test_analysis_suite_window_diagnostic_requires_current_target_and_feature_reports(tmp_path: Path) -> None:
    _qapp()
    target_service = _FakeTargetPlanner(_target_preview_report())
    feature_service = _FakeFeatureSetPlanner(candidates=(_candidate("close"),))
    diagnostic_service = _FakeDiagnosticService(_diagnostic_report(status="ready"))
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        target_service=target_service,
        feature_set_service=feature_service,
        diagnostic_service=diagnostic_service,
    )

    target_button = window.findChild(QPushButton, "analysisSuiteTargetPreviewButton")
    list_button = window.findChild(QPushButton, "analysisSuiteFeatureRefreshButton")
    select_all = window.findChild(QPushButton, "analysisSuiteFeatureSelectAllEligibleButton")
    feature_button = window.findChild(QPushButton, "analysisSuiteFeaturePreviewButton")
    diagnostic_button = window.findChild(QPushButton, "analysisSuiteDiagnosticButton")
    diagnostic_text = window.findChild(QPlainTextEdit, "analysisSuiteDiagnosticReportText")
    assert target_button is not None
    assert list_button is not None
    assert select_all is not None
    assert feature_button is not None
    assert diagnostic_button is not None
    assert diagnostic_text is not None

    assert diagnostic_button.isEnabled() is False
    target_button.click()
    list_button.click()
    select_all.click()
    feature_button.click()

    assert diagnostic_button.isEnabled() is True
    diagnostic_button.click()

    assert len(diagnostic_service.calls) == 1
    assert diagnostic_service.calls[0]["target_report"] is target_service.report
    assert diagnostic_service.calls[0]["feature_set_report"] is not None
    text = diagnostic_text.toPlainText()
    assert "Status: ready" in text
    assert "Available labels: 10" in text
    assert "Feature column diagnostics:" in text


def test_analysis_suite_window_refresh_clears_stale_preview(tmp_path: Path) -> None:
    _qapp()
    readiness = _FakeReadinessService(
        items=(
            _report(
                database_id="adb_ready",
                display_name="ReadyDB",
                readiness_status="ready",
                strict_ready=True,
                can_preview=True,
            ),
        )
    )
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=readiness,
        preview_service=_FakePreviewService(_preview_report()),
    )
    button = window.findChild(QPushButton, "analysisSuitePreviewButton")
    preview_table = window.findChild(QTableWidget, "analysisSuitePreviewTable")
    summary = window.findChild(QPlainTextEdit, "analysisSuitePreviewSummaryText")
    assert button is not None
    assert preview_table is not None
    assert summary is not None

    button.click()
    assert preview_table.rowCount() == 2

    readiness.items = ()
    window.refresh_catalog()

    assert preview_table.rowCount() == 0
    assert button.isEnabled() is False
    assert "Select a previewable Analysis Database" in summary.toPlainText()


def test_analysis_suite_window_clears_analysis_state_when_database_or_settings_change(tmp_path: Path) -> None:
    _qapp()
    target_service = _FakeTargetPlanner(_target_preview_report())
    feature_service = _FakeFeatureSetPlanner(candidates=(_candidate("close"),))
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(
            items=(
                _report(
                    database_id="adb_ready",
                    display_name="ReadyDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
                _report(
                    database_id="adb_other",
                    display_name="OtherDB",
                    readiness_status="ready",
                    strict_ready=True,
                    can_preview=True,
                ),
            )
        ),
        target_service=target_service,
        feature_set_service=feature_service,
        diagnostic_service=_FakeDiagnosticService(_diagnostic_report()),
    )

    target_button = window.findChild(QPushButton, "analysisSuiteTargetPreviewButton")
    list_button = window.findChild(QPushButton, "analysisSuiteFeatureRefreshButton")
    select_all = window.findChild(QPushButton, "analysisSuiteFeatureSelectAllEligibleButton")
    feature_button = window.findChild(QPushButton, "analysisSuiteFeaturePreviewButton")
    diagnostic_button = window.findChild(QPushButton, "analysisSuiteDiagnosticButton")
    diagnostic_text = window.findChild(QPlainTextEdit, "analysisSuiteDiagnosticReportText")
    feature_text = window.findChild(QPlainTextEdit, "analysisSuiteFeatureReportText")
    feature_table = window.findChild(QTableWidget, "analysisSuiteFeatureCandidateTable")
    horizon = window.findChild(QSpinBox, "analysisSuiteTargetHorizonSpin")
    catalog = window.findChild(QTableWidget, "analysisSuiteCatalogTable")
    assert target_button is not None
    assert list_button is not None
    assert select_all is not None
    assert feature_button is not None
    assert diagnostic_button is not None
    assert diagnostic_text is not None
    assert feature_text is not None
    assert feature_table is not None
    assert horizon is not None
    assert catalog is not None

    target_button.click()
    list_button.click()
    select_all.click()
    feature_button.click()
    assert diagnostic_button.isEnabled() is True

    horizon.setValue(3)

    assert diagnostic_button.isEnabled() is False
    assert feature_table.rowCount() == 0
    assert "Target settings changed" in feature_text.toPlainText()
    assert "Preview a target and feature set" in diagnostic_text.toPlainText()

    target_button.click()
    list_button.click()
    select_all.click()
    feature_button.click()
    assert diagnostic_button.isEnabled() is True

    catalog.selectRow(1)

    assert diagnostic_button.isEnabled() is False
    assert feature_table.rowCount() == 0
    assert "Preview a target and feature set" in diagnostic_text.toPlainText()


def test_analysis_suite_window_handles_empty_and_service_failure(tmp_path: Path) -> None:
    _qapp()
    empty = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
    )
    empty_table = empty.findChild(QTableWidget, "analysisSuiteCatalogTable")
    empty_details = empty.findChild(QPlainTextEdit, "analysisSuiteDetailsText")
    assert empty_table is not None
    assert empty_details is not None
    assert empty_table.rowCount() == 0
    assert "No Analysis Databases found" in empty_details.toPlainText()

    failing = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(fail=True),
    )
    failing_details = failing.findChild(QPlainTextEdit, "analysisSuiteDetailsText")
    assert failing_details is not None
    assert "Catalog refresh failed" in failing_details.toPlainText()
    assert "catalog unavailable" in failing_details.toPlainText()


def test_analysis_suite_window_allowed_actions_are_read_only(tmp_path: Path) -> None:
    _qapp()
    opened: list[str] = []
    window = AnalysisSuiteWindow(
        ctx=_ctx(tmp_path),  # type: ignore[arg-type]
        readiness_service=_FakeReadinessService(),
        open_data_manager_callback=lambda: opened.append("data_manager"),
    )
    buttons = {button.text() for button in window.findChildren(QPushButton)}

    assert "Refresh Catalog" in buttons
    assert "Open Data Manager" in buttons
    assert "Close" in buttons
    forbidden = {
        "Build Database",
        "Rebuild Database",
        "Extend Database",
        "Edit Components",
        "Calculate Artifacts",
        "Execute Recipes",
        "Repair OHLCV",
        "Create Analysis Project",
        "Create Analysis Run",
        "Train Model",
        "Generate Signal",
        "Category Builder",
        "White-Box Discovery",
        "Backtest",
    }
    assert buttons.isdisjoint(forbidden)

    open_button = window.findChild(QPushButton, "analysisSuiteOpenDataManagerButton")
    assert open_button is not None
    open_button.click()
    assert opened == ["data_manager"]


def test_main_window_analysis_menu_contains_data_manager_and_analysis_suite_actions() -> None:
    source = Path("src/leonardo/gui/main_window.py").read_text(encoding="utf-8")

    assert 'menu2 = mb.addMenu("Analysis")' in source
    assert 'QAction("Data Manager", self)' in source
    assert 'QAction("Analysis Suite", self)' in source
    assert "menu2.addAction(self._act_open_data_manager)" in source
    assert "menu2.addAction(self._act_open_analysis_suite)" in source
    assert "self._act_open_analysis_suite.setEnabled(True)" in source
    assert "def _open_analysis_suite(self) -> None:" in source
    assert "wm.open_analysis_suite(parent=self)" in source


def test_window_manager_opens_reuses_and_tracks_analysis_suite_window(tmp_path: Path) -> None:
    _qapp()
    state = _FakeState()
    core = _FakeCore()
    manager = WindowManager(
        ctx=_ctx(tmp_path, state),  # type: ignore[arg-type]
        core_bridge=core,  # type: ignore[arg-type]
    )

    first = manager.open_analysis_suite()
    second = manager.open_analysis_suite()

    assert isinstance(first, AnalysisSuiteWindow)
    assert first is second
    assert manager.get_analysis_suite() is first
    assert ("analysis_suite", "AnalysisSuiteWindow") in state.opened
    assert len([item for item in state.opened if item[0] == "analysis_suite"]) == 1

    manager.close_analysis_suite()
    _qapp().processEvents()
    assert "analysis_suite" in state.closed


def test_analysis_suite_window_static_boundaries() -> None:
    source = Path("src/leonardo/gui/windows/analysis_suite_window.py").read_text(encoding="utf-8")
    window_manager_source = Path("src/leonardo/gui/windows/window_manager.py").read_text(encoding="utf-8")

    forbidden = (
        "pandas",
        "pd.read_csv",
        "csv.",
        "load_dataframe",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "ArtifactRecoveryRegenerator",
        "DataManagerUpdateService",
        "DataManagerSelectedUpdateService",
        "DataManagerConstructBatchExecutionService",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "Category Builder",
        "White-Box Discovery",
        "Rule Discovery",
        "Train Model",
        "Generate Signal",
        "materialize_database",
        "rebuild_database",
        "replace_database_features",
        "save_manifest",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv(",
    )
    for pattern in forbidden:
        assert pattern not in source

    assert ".open(\"w" not in source
    assert ".open('w" not in source
    assert "AnalysisSuiteWindow" in window_manager_source


def test_no_analysis_project_run_or_report_store_added() -> None:
    matches = list(Path("src").rglob("*analysis_project*"))
    matches.extend(Path("src").rglob("*analysis_run*"))
    matches.extend(Path("src").rglob("*analysis_report*"))
    assert matches == []


def test_main_window_runtime_action_is_distinct_from_data_manager() -> None:
    _qapp()
    source = Path("src/leonardo/gui/main_window.py").read_text(encoding="utf-8")
    assert "_act_open_analysis_suite" in source
    assert "_act_open_data_manager" in source
    assert "_open_analysis_suite" in source
    assert "_open_data_manager" in source
    assert "Historical" in source
    assert "Analysis Suite" in source
    assert "AnalysisSuiteWindow" not in source
    assert QAction is not None
