from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QPlainTextEdit, QSpinBox, QTableWidget

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
