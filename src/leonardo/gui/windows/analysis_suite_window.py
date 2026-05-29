from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.data.historical.analysis_suite_dataframe_preview import (
    DEFAULT_PREVIEW_ROW_LIMIT,
    MAX_PREVIEW_ROW_LIMIT,
    AnalysisSuiteDataframePreviewService,
)
from leonardo.data.historical.analysis_suite_dataset_readiness import AnalysisSuiteDatasetReadinessService
from leonardo.data.naming import canonicalize


_REPORT_ROLE = Qt.UserRole + 1


class _ReadinessCatalogService(Protocol):
    def list_analysis_datasets(self) -> object:
        ...


class _DataframePreviewService(Protocol):
    def preview_for_database(
        self,
        *,
        market: object,
        database_id: str,
        mode: str = "head",
        row_limit: int | None = None,
    ) -> object:
        ...


class AnalysisSuiteWindow(QMainWindow):
    """
    Read-only Analysis Suite dataset readiness catalog.

    The window consumes ``AnalysisSuiteDatasetReadinessService`` reports and
    displays Analysis Database readiness diagnostics for future analysis
    workflows. It does not build databases, calculate artifacts, execute
    recipes, repair OHLCV, or classify readiness in the GUI layer.
    """

    def __init__(
        self,
        *,
        ctx: AppContext,
        parent: Optional[QWidget] = None,
        readiness_service: _ReadinessCatalogService | None = None,
        preview_service: _DataframePreviewService | None = None,
        open_data_manager_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self._ctx = ctx
        self._historical_root = self._resolve_historical_root(ctx)
        self._readiness_service = readiness_service or AnalysisSuiteDatasetReadinessService(
            historical_root=self._historical_root,
        )
        self._preview_service = preview_service or AnalysisSuiteDataframePreviewService(
            historical_root=self._historical_root,
        )
        self._open_data_manager_callback = open_data_manager_callback
        self._latest_catalog: object | None = None
        self._selected_report: object | None = None

        self.setObjectName("analysisSuiteWindow")
        self.setWindowTitle("Leonardo - Analysis Suite")
        self.resize(1280, 760)

        self.setCentralWidget(self._build_central_widget())
        self.statusBar().showMessage("Analysis Suite catalog ready")
        self.refresh_catalog()

    def refresh_catalog(self) -> None:
        """
        Refresh the read-only Analysis Database readiness catalog.

        Service failures are shown in the details panel. A failed refresh does
        not mutate Data Manager state and does not prevent later retries.
        """

        try:
            catalog = self._readiness_service.list_analysis_datasets()
        except Exception as exc:
            self._latest_catalog = None
            self._clear_table()
            self._selected_report = None
            self._clear_preview()
            self._summary_label.setText("Analysis Database readiness catalog could not be loaded.")
            self._details.setPlainText(f"Catalog refresh failed:\n{type(exc).__name__}: {exc}")
            self.statusBar().showMessage("Analysis Suite catalog refresh failed")
            return

        self._latest_catalog = catalog
        self._selected_report = None
        self._clear_preview()
        items = tuple(getattr(catalog, "items", ()))
        self._populate_table(items)
        self._summary_label.setText(_catalog_summary(catalog))
        if items:
            self._table.selectRow(0)
            self._show_report_details(items[0])
        else:
            self._details.setPlainText("No Analysis Databases found.")
        self.statusBar().showMessage(f"Analysis Suite catalog refreshed: {len(items)} dataset(s)")

    def _build_central_widget(self) -> QWidget:
        root_widget = QWidget(self)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        root.addLayout(header)

        self._summary_label = QLabel("Analysis Database readiness catalog", root_widget)
        self._summary_label.setObjectName("analysisSuiteSummaryLabel")
        self._summary_label.setWordWrap(True)
        header.addWidget(self._summary_label, 1)

        self._refresh_button = QPushButton("Refresh Catalog", root_widget)
        self._refresh_button.setObjectName("analysisSuiteRefreshButton")
        self._refresh_button.clicked.connect(self.refresh_catalog)
        header.addWidget(self._refresh_button)

        self._open_data_manager_button = QPushButton("Open Data Manager", root_widget)
        self._open_data_manager_button.setObjectName("analysisSuiteOpenDataManagerButton")
        self._open_data_manager_button.setEnabled(self._open_data_manager_callback is not None)
        self._open_data_manager_button.setToolTip(
            "Open Data Manager for dataset preparation, update, build, and repair workflows."
        )
        self._open_data_manager_button.clicked.connect(self._open_data_manager)
        header.addWidget(self._open_data_manager_button)

        self._close_button = QPushButton("Close", root_widget)
        self._close_button.setObjectName("analysisSuiteCloseButton")
        self._close_button.clicked.connect(self.close)
        header.addWidget(self._close_button)

        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        catalog_group = QGroupBox("Analysis Database Readiness", root_widget)
        catalog_layout = QVBoxLayout(catalog_group)
        self._table = QTableWidget(0, 11, catalog_group)
        self._table.setObjectName("analysisSuiteCatalogTable")
        self._table.setHorizontalHeaderLabels(
            [
                "Display Name",
                "Status",
                "Strict",
                "Preview",
                "Market",
                "Rows",
                "Columns",
                "First ts",
                "Last ts",
                "Drift",
                "Topology",
            ]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        catalog_layout.addWidget(self._table, 1)
        content.addWidget(catalog_group, 3)

        details_group = QGroupBox("Readiness Details", root_widget)
        details_layout = QVBoxLayout(details_group)
        self._details = QPlainTextEdit(details_group)
        self._details.setObjectName("analysisSuiteDetailsText")
        self._details.setReadOnly(True)
        self._details.setPlaceholderText("Select an Analysis Database readiness row.")
        details_layout.addWidget(self._details, 1)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)
        right_panel.addWidget(details_group, 1)
        right_panel.addWidget(self._build_preview_group(root_widget), 1)
        content.addLayout(right_panel, 2)

        return root_widget

    def _build_preview_group(self, parent: QWidget) -> QGroupBox:
        preview_group = QGroupBox("Bounded Dataframe Preview", parent)
        layout = QVBoxLayout(preview_group)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        layout.addLayout(controls)

        controls.addWidget(QLabel("Mode", preview_group))
        self._preview_mode = QComboBox(preview_group)
        self._preview_mode.setObjectName("analysisSuitePreviewModeCombo")
        self._preview_mode.addItem("Head", "head")
        self._preview_mode.addItem("Tail", "tail")
        controls.addWidget(self._preview_mode)

        controls.addWidget(QLabel("Rows", preview_group))
        self._preview_row_limit = QSpinBox(preview_group)
        self._preview_row_limit.setObjectName("analysisSuitePreviewRowLimitSpin")
        self._preview_row_limit.setRange(1, MAX_PREVIEW_ROW_LIMIT)
        self._preview_row_limit.setValue(DEFAULT_PREVIEW_ROW_LIMIT)
        controls.addWidget(self._preview_row_limit)

        self._preview_button = QPushButton("Preview Dataframe", preview_group)
        self._preview_button.setObjectName("analysisSuitePreviewButton")
        self._preview_button.setEnabled(False)
        self._preview_button.clicked.connect(self._preview_dataframe)
        controls.addWidget(self._preview_button)
        controls.addStretch(1)

        self._preview_summary = QPlainTextEdit(preview_group)
        self._preview_summary.setObjectName("analysisSuitePreviewSummaryText")
        self._preview_summary.setReadOnly(True)
        self._preview_summary.setMaximumHeight(150)
        self._preview_summary.setPlainText("Select a previewable Analysis Database.")
        layout.addWidget(self._preview_summary)

        self._preview_table = QTableWidget(0, 0, preview_group)
        self._preview_table.setObjectName("analysisSuitePreviewTable")
        self._preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._preview_table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self._preview_table, 1)

        return preview_group

    def _open_data_manager(self) -> None:
        if self._open_data_manager_callback is None:
            self.statusBar().showMessage("Data Manager routing is not available")
            return
        self._open_data_manager_callback()
        self.statusBar().showMessage("Data Manager opened")

    def _populate_table(self, reports: tuple[object, ...]) -> None:
        self._clear_table()
        self._table.setRowCount(len(reports))
        for row, report in enumerate(reports):
            values = (
                getattr(report, "display_name", ""),
                getattr(report, "readiness_status", ""),
                _yes_no(getattr(report, "strict_ready", False)),
                _yes_no(getattr(report, "can_preview", False)),
                _market_label(report),
                _value_text(getattr(report, "row_count", None)),
                _value_text(getattr(report, "column_count", None)),
                _value_text(getattr(report, "first_ts_ms", None)),
                _value_text(getattr(report, "last_ts_ms", None)),
                getattr(report, "source_ohlcv_drift_status", ""),
                getattr(report, "geography_status", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or "-"))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(self._row_tooltip(report))
                if column == 0:
                    item.setData(_REPORT_ROLE, report)
                _style_status_item(item, str(getattr(report, "readiness_status", "")))
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()

    def _clear_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._table.blockSignals(False)

    def _on_table_selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            self._selected_report = None
            self._details.clear()
            self._clear_preview_table()
            self._refresh_preview_state()
            return
        row = selected[0].row()
        item = self._table.item(row, 0)
        report = None if item is None else item.data(_REPORT_ROLE)
        if report is None:
            self._selected_report = None
            self._details.clear()
            self._clear_preview_table()
            self._refresh_preview_state()
            return
        self._selected_report = report
        self._show_report_details(report)
        self._clear_preview_table()
        self._refresh_preview_state()

    def _show_report_details(self, report: object) -> None:
        self._details.setPlainText(_report_details(report))

    def _refresh_preview_state(self) -> None:
        report = self._selected_report
        can_preview = bool(getattr(report, "can_preview", False)) if report is not None else False
        self._preview_button.setEnabled(can_preview)
        if report is None:
            self._preview_summary.setPlainText("Select a previewable Analysis Database.")
            return
        if can_preview:
            self._preview_summary.setPlainText(
                "Preview available. "
                f"Readiness: {_value_text(getattr(report, 'readiness_status', None))}; "
                f"strict ready: {_yes_no(getattr(report, 'strict_ready', False))}."
            )
            return
        blockers = tuple(str(item) for item in getattr(report, "blockers", ()) or ())
        detail = "Preview is not available for the selected Analysis Database."
        if blockers:
            detail += "\n" + "\n".join(f"- {item}" for item in blockers)
        self._preview_summary.setPlainText(detail)

    def _preview_dataframe(self) -> None:
        report = self._selected_report
        if report is None:
            self.statusBar().showMessage("Select an Analysis Database before previewing")
            return
        if not bool(getattr(report, "can_preview", False)):
            self._refresh_preview_state()
            self.statusBar().showMessage("Selected Analysis Database is not previewable")
            return

        try:
            preview = self._preview_service.preview_for_database(
                market=canonicalize(
                    str(getattr(report, "exchange", "")),
                    str(getattr(report, "market_type", "")),
                    str(getattr(report, "symbol", "")),
                    str(getattr(report, "timeframe", "")),
                ),
                database_id=str(getattr(report, "database_id", "")),
                mode=str(self._preview_mode.currentData() or "head"),
                row_limit=int(self._preview_row_limit.value()),
            )
        except Exception as exc:
            self._clear_preview()
            self._preview_summary.setPlainText(
                f"Preview failed:\n{type(exc).__name__}: {exc}"
            )
            self.statusBar().showMessage("Analysis Suite dataframe preview failed")
            return

        self._show_preview_report(preview)
        self.statusBar().showMessage(
            f"Analysis Suite dataframe preview: {_value_text(getattr(preview, 'status', None))}"
        )

    def _show_preview_report(self, report: object) -> None:
        columns = tuple(str(column) for column in getattr(report, "columns", ()) or ())
        rows = tuple(dict(row) for row in getattr(report, "rows", ()) or ())
        self._preview_table.clear()
        self._preview_table.setColumnCount(len(columns))
        self._preview_table.setRowCount(len(rows))
        self._preview_table.setHorizontalHeaderLabels(columns)
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                item = QTableWidgetItem(_value_text(row.get(column)))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._preview_table.setItem(row_index, column_index, item)
        self._preview_table.resizeColumnsToContents()
        self._preview_summary.setPlainText(_preview_report_summary(report))

    def _clear_preview(self) -> None:
        self._clear_preview_table()
        self._preview_summary.setPlainText("Select a previewable Analysis Database.")
        self._preview_button.setEnabled(False)

    def _clear_preview_table(self) -> None:
        self._preview_table.clear()
        self._preview_table.setRowCount(0)
        self._preview_table.setColumnCount(0)

    @staticmethod
    def _resolve_historical_root(ctx: AppContext) -> Path:
        runtime = getattr(getattr(ctx, "config", None), "runtime", None)
        root = getattr(runtime, "data_dir", "data")
        return Path(root) / "historical"

    @staticmethod
    def _row_tooltip(report: object) -> str:
        status = getattr(report, "readiness_status", "")
        blockers = tuple(getattr(report, "blockers", ()))
        if blockers:
            return f"{status}: " + "; ".join(str(item) for item in blockers)
        return str(status or "readiness report")


def _catalog_summary(catalog: object) -> str:
    return (
        f"Datasets: {getattr(catalog, 'total_count', 0)} | "
        f"Ready: {getattr(catalog, 'ready_count', 0)} | "
        f"Blocked: {getattr(catalog, 'blocked_count', 0)} | "
        f"Draft: {getattr(catalog, 'draft_count', 0)} | "
        f"Stale: {getattr(catalog, 'stale_count', 0)} | "
        f"Errors: {getattr(catalog, 'error_count', 0)}"
    )


def _report_details(report: object) -> str:
    lines = [
        f"Database ID: {_value_text(getattr(report, 'database_id', None))}",
        f"Display name: {_value_text(getattr(report, 'display_name', None))}",
        f"Market: {_market_label(report)}",
        f"Manifest path: {_value_text(getattr(report, 'manifest_path', None))}",
        f"Dataframe path: {_value_text(getattr(report, 'dataframe_path', None))}",
        "",
        f"Readiness status: {_value_text(getattr(report, 'readiness_status', None))}",
        f"Strict ready: {_yes_no(getattr(report, 'strict_ready', False))}",
        f"Can preview: {_yes_no(getattr(report, 'can_preview', False))}",
        f"Manifest status: {_value_text(getattr(report, 'manifest_status', None))}",
        f"Materialization status: {_value_text(getattr(report, 'materialization_status', None))}",
        f"Dataframe status: {_value_text(getattr(report, 'dataframe_status', None))}",
        "",
        f"Rows: {_value_text(getattr(report, 'row_count', None))}",
        f"Columns: {_value_text(getattr(report, 'column_count', None))}",
        f"First timestamp: {_value_text(getattr(report, 'first_ts_ms', None))}",
        f"Last timestamp: {_value_text(getattr(report, 'last_ts_ms', None))}",
        "",
        f"Source OHLCV drift status: {_value_text(getattr(report, 'source_ohlcv_drift_status', None))}",
        f"Geography/topology status: {_value_text(getattr(report, 'geography_status', None))}",
        _list_section("Missing topology", getattr(report, "missing_topology", ())),
        _list_section("Blockers", getattr(report, "blockers", ())),
        _list_section("Warnings", getattr(report, "warnings", ())),
        _list_section("Errors", getattr(report, "errors", ())),
    ]
    return "\n".join(lines).strip()


def _preview_report_summary(report: object) -> str:
    return "\n".join(
        [
            f"Status: {_value_text(getattr(report, 'status', None))}",
            f"Mode: {_value_text(getattr(report, 'mode', None))}",
            f"Requested limit: {_value_text(getattr(report, 'requested_limit', None))}",
            f"Effective limit: {_value_text(getattr(report, 'effective_limit', None))}",
            f"Returned rows: {_value_text(getattr(report, 'returned_row_count', None))}",
            f"Total rows: {_value_text(getattr(report, 'total_row_count', None))}",
            f"Total columns: {_value_text(getattr(report, 'total_column_count', None))}",
            f"Preview first ts: {_value_text(getattr(report, 'preview_first_ts_ms', None))}",
            f"Preview last ts: {_value_text(getattr(report, 'preview_last_ts_ms', None))}",
            f"Dataset first ts: {_value_text(getattr(report, 'dataset_first_ts_ms', None))}",
            f"Dataset last ts: {_value_text(getattr(report, 'dataset_last_ts_ms', None))}",
            f"Readiness status: {_value_text(getattr(report, 'readiness_status', None))}",
            f"Strict ready: {_yes_no(getattr(report, 'strict_ready', False))}",
            _list_section("Warnings", getattr(report, "warnings", ())),
            _list_section("Blockers", getattr(report, "blockers", ())),
            _list_section("Errors", getattr(report, "errors", ())),
        ]
    ).strip()


def _list_section(label: str, values: object) -> str:
    items = tuple(str(item) for item in values or ())
    if not items:
        return f"{label}: none"
    return f"{label}:\n" + "\n".join(f"- {item}" for item in items)


def _market_label(report: object) -> str:
    parts = (
        getattr(report, "exchange", ""),
        getattr(report, "market_type", ""),
        getattr(report, "symbol", ""),
        getattr(report, "timeframe", ""),
    )
    text = " / ".join(str(part) for part in parts if str(part or "").strip())
    return text or "-"


def _value_text(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _yes_no(value: object) -> str:
    return "Yes" if bool(value) else "No"


def _style_status_item(item: QTableWidgetItem, status: str) -> None:
    if status == "ready":
        item.setBackground(QBrush(QColor("#dff0d8")))
    elif status in {"blocked", "error", "corrupt_manifest", "corrupt_dataframe"}:
        item.setBackground(QBrush(QColor("#f2dede")))
    elif status in {"draft", "missing_dataframe", "stale_source", "incomplete_topology"}:
        item.setBackground(QBrush(QColor("#fcf8e3")))
