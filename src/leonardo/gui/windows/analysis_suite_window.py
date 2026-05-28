from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.data.historical.analysis_suite_dataset_readiness import AnalysisSuiteDatasetReadinessService


_REPORT_ROLE = Qt.UserRole + 1


class _ReadinessCatalogService(Protocol):
    def list_analysis_datasets(self) -> object:
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
        open_data_manager_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self._ctx = ctx
        self._historical_root = self._resolve_historical_root(ctx)
        self._readiness_service = readiness_service or AnalysisSuiteDatasetReadinessService(
            historical_root=self._historical_root,
        )
        self._open_data_manager_callback = open_data_manager_callback
        self._latest_catalog: object | None = None

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
            self._summary_label.setText("Analysis Database readiness catalog could not be loaded.")
            self._details.setPlainText(f"Catalog refresh failed:\n{type(exc).__name__}: {exc}")
            self.statusBar().showMessage("Analysis Suite catalog refresh failed")
            return

        self._latest_catalog = catalog
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
        content.addWidget(details_group, 2)

        return root_widget

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
            self._details.clear()
            return
        row = selected[0].row()
        item = self._table.item(row, 0)
        report = None if item is None else item.data(_REPORT_ROLE)
        if report is None:
            self._details.clear()
            return
        self._show_report_details(report)

    def _show_report_details(self, report: object) -> None:
        self._details.setPlainText(_report_details(report))

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
