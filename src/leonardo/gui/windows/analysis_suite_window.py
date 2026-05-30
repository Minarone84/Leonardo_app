from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
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
from leonardo.data.historical.analysis_suite_diagnostic_report import AnalysisSuiteDiagnosticReportService
from leonardo.data.historical.analysis_suite_feature_set_planner import AnalysisSuiteFeatureSetPlanner
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetDefinition,
    AnalysisSuiteTargetPlanner,
)
from leonardo.data.naming import canonicalize


_REPORT_ROLE = Qt.UserRole + 1
_CANDIDATE_ROLE = Qt.UserRole + 2


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


class _TargetPreviewService(Protocol):
    def preview_target(
        self,
        *,
        market: object,
        database_id: str,
        target_definition: object,
        preview_limit: int | None = None,
    ) -> object:
        ...


class _FeatureSetPreviewService(Protocol):
    def list_feature_candidates(
        self,
        *,
        market: object,
        database_id: str,
        target_definition: object | None = None,
        target_report: object | None = None,
    ) -> object:
        ...

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
        ...


class _DiagnosticReportService(Protocol):
    def build_report(
        self,
        *,
        readiness_report: object,
        target_report: object,
        feature_set_report: object,
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
        target_service: _TargetPreviewService | None = None,
        feature_set_service: _FeatureSetPreviewService | None = None,
        diagnostic_service: _DiagnosticReportService | None = None,
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
        self._target_service = target_service or AnalysisSuiteTargetPlanner(
            historical_root=self._historical_root,
        )
        self._feature_set_service = feature_set_service or AnalysisSuiteFeatureSetPlanner(
            historical_root=self._historical_root,
        )
        self._diagnostic_service = diagnostic_service or AnalysisSuiteDiagnosticReportService()
        self._open_data_manager_callback = open_data_manager_callback
        self._latest_catalog: object | None = None
        self._selected_report: object | None = None
        self._target_report: object | None = None
        self._target_report_key: tuple[object, ...] | None = None
        self._feature_candidates_report: object | None = None
        self._feature_candidates_key: tuple[object, ...] | None = None
        self._feature_set_report: object | None = None
        self._feature_set_report_key: tuple[object, ...] | None = None
        self._diagnostic_report: object | None = None

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
            self._clear_analysis_setup()
            self._summary_label.setText("Analysis Database readiness catalog could not be loaded.")
            self._details.setPlainText(f"Catalog refresh failed:\n{type(exc).__name__}: {exc}")
            self.statusBar().showMessage("Analysis Suite catalog refresh failed")
            return

        self._latest_catalog = catalog
        self._selected_report = None
        self._clear_preview()
        self._clear_analysis_setup()
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
        right_panel.addWidget(self._build_analysis_tabs(root_widget), 2)
        content.addLayout(right_panel, 2)

        return root_widget

    def _build_analysis_tabs(self, parent: QWidget) -> QTabWidget:
        tabs = QTabWidget(parent)
        tabs.setObjectName("analysisSuiteSetupTabs")
        tabs.addTab(self._build_preview_group(parent), "Data Preview")
        tabs.addTab(self._build_target_group(parent), "Target Preview")
        tabs.addTab(self._build_feature_group(parent), "Feature Set")
        tabs.addTab(self._build_diagnostic_group(parent), "Diagnostic Report")
        return tabs

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

    def _build_target_group(self, parent: QWidget) -> QGroupBox:
        target_group = QGroupBox("Target Preview", parent)
        layout = QVBoxLayout(target_group)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        layout.addLayout(controls)

        controls.addWidget(QLabel("Family", target_group))
        self._target_family = QComboBox(target_group)
        self._target_family.setObjectName("analysisSuiteTargetFamilyCombo")
        self._target_family.addItem("Future return regression", "future_return")
        self._target_family.addItem("Future direction classification", "future_direction")
        self._target_family.currentIndexChanged.connect(self._on_target_settings_changed)
        self._target_family.currentIndexChanged.connect(self._refresh_target_threshold_state)
        controls.addWidget(self._target_family)

        controls.addWidget(QLabel("Horizon", target_group))
        self._target_horizon = QSpinBox(target_group)
        self._target_horizon.setObjectName("analysisSuiteTargetHorizonSpin")
        self._target_horizon.setRange(1, 100000)
        self._target_horizon.setValue(1)
        self._target_horizon.valueChanged.connect(self._on_target_settings_changed)
        controls.addWidget(self._target_horizon)

        controls.addWidget(QLabel("Up", target_group))
        self._target_up_threshold = QDoubleSpinBox(target_group)
        self._target_up_threshold.setObjectName("analysisSuiteTargetUpThresholdSpin")
        self._target_up_threshold.setRange(0.0, 1.0)
        self._target_up_threshold.setDecimals(6)
        self._target_up_threshold.setSingleStep(0.001)
        self._target_up_threshold.setValue(0.01)
        self._target_up_threshold.valueChanged.connect(self._on_target_settings_changed)
        controls.addWidget(self._target_up_threshold)

        controls.addWidget(QLabel("Down", target_group))
        self._target_down_threshold = QDoubleSpinBox(target_group)
        self._target_down_threshold.setObjectName("analysisSuiteTargetDownThresholdSpin")
        self._target_down_threshold.setRange(0.0, 1.0)
        self._target_down_threshold.setDecimals(6)
        self._target_down_threshold.setSingleStep(0.001)
        self._target_down_threshold.setValue(0.01)
        self._target_down_threshold.valueChanged.connect(self._on_target_settings_changed)
        controls.addWidget(self._target_down_threshold)

        self._target_preview_button = QPushButton("Preview Target", target_group)
        self._target_preview_button.setObjectName("analysisSuiteTargetPreviewButton")
        self._target_preview_button.setEnabled(False)
        self._target_preview_button.clicked.connect(self._preview_target)
        controls.addWidget(self._target_preview_button)
        controls.addStretch(1)

        self._target_report_text = QPlainTextEdit(target_group)
        self._target_report_text.setObjectName("analysisSuiteTargetReportText")
        self._target_report_text.setReadOnly(True)
        self._target_report_text.setPlainText("Select a previewable Analysis Database.")
        layout.addWidget(self._target_report_text, 1)

        self._refresh_target_threshold_state()
        return target_group

    def _build_feature_group(self, parent: QWidget) -> QGroupBox:
        feature_group = QGroupBox("Feature Set", parent)
        layout = QVBoxLayout(feature_group)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        layout.addLayout(controls)

        self._feature_refresh_button = QPushButton("List Candidates", feature_group)
        self._feature_refresh_button.setObjectName("analysisSuiteFeatureRefreshButton")
        self._feature_refresh_button.setEnabled(False)
        self._feature_refresh_button.clicked.connect(self._list_feature_candidates)
        controls.addWidget(self._feature_refresh_button)

        self._feature_select_all_button = QPushButton("Select All Eligible", feature_group)
        self._feature_select_all_button.setObjectName("analysisSuiteFeatureSelectAllEligibleButton")
        self._feature_select_all_button.setEnabled(False)
        self._feature_select_all_button.clicked.connect(self._select_all_eligible_features)
        controls.addWidget(self._feature_select_all_button)

        self._feature_clear_button = QPushButton("Clear Selection", feature_group)
        self._feature_clear_button.setObjectName("analysisSuiteFeatureClearSelectionButton")
        self._feature_clear_button.setEnabled(False)
        self._feature_clear_button.clicked.connect(self._clear_feature_selection)
        controls.addWidget(self._feature_clear_button)

        self._feature_preview_button = QPushButton("Preview Feature Set", feature_group)
        self._feature_preview_button.setObjectName("analysisSuiteFeaturePreviewButton")
        self._feature_preview_button.setEnabled(False)
        self._feature_preview_button.clicked.connect(self._preview_feature_set)
        controls.addWidget(self._feature_preview_button)
        controls.addStretch(1)

        self._feature_table = QTableWidget(0, 6, feature_group)
        self._feature_table.setObjectName("analysisSuiteFeatureCandidateTable")
        self._feature_table.setHorizontalHeaderLabels(
            ["Select", "Column", "Status", "Group", "Reason", "Source"]
        )
        self._feature_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._feature_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._feature_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._feature_table.itemChanged.connect(self._on_feature_candidate_item_changed)
        layout.addWidget(self._feature_table, 2)

        self._feature_report_text = QPlainTextEdit(feature_group)
        self._feature_report_text.setObjectName("analysisSuiteFeatureReportText")
        self._feature_report_text.setReadOnly(True)
        self._feature_report_text.setPlainText("List candidates for a previewable Analysis Database.")
        layout.addWidget(self._feature_report_text, 1)

        return feature_group

    def _build_diagnostic_group(self, parent: QWidget) -> QGroupBox:
        diagnostic_group = QGroupBox("Diagnostic Report", parent)
        layout = QVBoxLayout(diagnostic_group)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        layout.addLayout(controls)

        self._diagnostic_button = QPushButton("Run Diagnostic", diagnostic_group)
        self._diagnostic_button.setObjectName("analysisSuiteDiagnosticButton")
        self._diagnostic_button.setEnabled(False)
        self._diagnostic_button.clicked.connect(self._run_diagnostic)
        controls.addWidget(self._diagnostic_button)
        controls.addStretch(1)

        self._diagnostic_report_text = QPlainTextEdit(diagnostic_group)
        self._diagnostic_report_text.setObjectName("analysisSuiteDiagnosticReportText")
        self._diagnostic_report_text.setReadOnly(True)
        self._diagnostic_report_text.setPlainText(
            "Preview a target and feature set before running diagnostics."
        )
        layout.addWidget(self._diagnostic_report_text, 1)

        return diagnostic_group

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
            self._clear_analysis_setup()
            return
        row = selected[0].row()
        item = self._table.item(row, 0)
        report = None if item is None else item.data(_REPORT_ROLE)
        if report is None:
            self._selected_report = None
            self._details.clear()
            self._clear_preview_table()
            self._refresh_preview_state()
            self._clear_analysis_setup()
            return
        self._selected_report = report
        self._show_report_details(report)
        self._clear_preview_table()
        self._refresh_preview_state()
        self._clear_analysis_setup()

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

    def _preview_target(self) -> None:
        context = self._selected_database_context()
        if context is None:
            self.statusBar().showMessage("Select an Analysis Database before target preview")
            return
        report, market, database_id = context
        if not bool(getattr(report, "can_preview", False)):
            self._target_report_text.setPlainText(
                "Target preview is not available for the selected Analysis Database.\n"
                + _list_section("Blockers", getattr(report, "blockers", ()))
            )
            self.statusBar().showMessage("Selected Analysis Database is not previewable")
            return

        definition = self._target_definition_from_controls()
        try:
            target_report = self._target_service.preview_target(
                market=market,
                database_id=database_id,
                target_definition=definition,
                preview_limit=None,
            )
        except Exception as exc:
            self._target_report = None
            self._target_report_key = None
            self._target_report_text.setPlainText(
                f"Target preview failed:\n{type(exc).__name__}: {exc}"
            )
            self._clear_feature_setup("Target preview failed. Refresh target before feature preview.")
            self._clear_diagnostic_setup()
            self.statusBar().showMessage("Analysis Suite target preview failed")
            self._refresh_analysis_setup_state()
            return

        self._target_report = target_report
        self._target_report_key = self._current_target_key()
        self._target_report_text.setPlainText(_target_report_summary(target_report))
        self._clear_feature_setup("Target preview changed. Refresh feature candidates.")
        self._clear_diagnostic_setup()
        self.statusBar().showMessage(
            f"Analysis Suite target preview: {_value_text(getattr(target_report, 'status', None))}"
        )
        self._refresh_analysis_setup_state()

    def _list_feature_candidates(self) -> None:
        context = self._selected_database_context()
        if context is None:
            self.statusBar().showMessage("Select an Analysis Database before listing features")
            return
        report, market, database_id = context
        if not bool(getattr(report, "can_preview", False)):
            self._feature_report_text.setPlainText(
                "Feature candidates are not available for the selected Analysis Database.\n"
                + _list_section("Blockers", getattr(report, "blockers", ()))
            )
            self.statusBar().showMessage("Selected Analysis Database is not previewable")
            return

        target_report = self._target_report if self._target_report_is_current() else None
        try:
            candidates_report = self._feature_set_service.list_feature_candidates(
                market=market,
                database_id=database_id,
                target_report=target_report,
            )
        except Exception as exc:
            self._feature_candidates_report = None
            self._feature_candidates_key = None
            self._feature_report_text.setPlainText(
                f"Feature candidate listing failed:\n{type(exc).__name__}: {exc}"
            )
            self._clear_feature_table()
            self._clear_diagnostic_setup()
            self.statusBar().showMessage("Analysis Suite feature candidate listing failed")
            self._refresh_analysis_setup_state()
            return

        self._feature_candidates_report = candidates_report
        self._feature_candidates_key = self._current_feature_candidates_key()
        self._feature_set_report = None
        self._feature_set_report_key = None
        self._populate_feature_candidates(
            tuple(getattr(candidates_report, "candidates", ()) or ())
        )
        self._feature_report_text.setPlainText(_feature_set_report_summary(candidates_report))
        self._clear_diagnostic_setup()
        self.statusBar().showMessage(
            "Analysis Suite feature candidates: "
            f"{_value_text(getattr(candidates_report, 'total_candidate_count', None))}"
        )
        self._refresh_analysis_setup_state()

    def _preview_feature_set(self) -> None:
        context = self._selected_database_context()
        if context is None:
            self.statusBar().showMessage("Select an Analysis Database before feature preview")
            return
        _report, market, database_id = context
        selected_columns = self._selected_feature_columns()
        target_report = self._target_report if self._target_report_is_current() else None
        try:
            feature_report = self._feature_set_service.validate_selected_features(
                market=market,
                database_id=database_id,
                selected_columns=selected_columns,
                target_report=target_report,
                name="Analysis Suite GUI feature set preview",
            )
        except Exception as exc:
            self._feature_set_report = None
            self._feature_set_report_key = None
            self._feature_report_text.setPlainText(
                f"Feature-set preview failed:\n{type(exc).__name__}: {exc}"
            )
            self._clear_diagnostic_setup()
            self.statusBar().showMessage("Analysis Suite feature-set preview failed")
            self._refresh_analysis_setup_state()
            return

        self._feature_set_report = feature_report
        self._feature_set_report_key = self._current_feature_set_key()
        self._feature_report_text.setPlainText(_feature_set_report_summary(feature_report))
        self._clear_diagnostic_setup()
        self.statusBar().showMessage(
            f"Analysis Suite feature-set preview: {_value_text(getattr(feature_report, 'status', None))}"
        )
        self._refresh_analysis_setup_state()

    def _run_diagnostic(self) -> None:
        readiness_report = self._selected_report
        target_report = self._target_report if self._target_report_is_current() else None
        feature_report = self._feature_set_report if self._feature_set_report_is_current() else None
        if readiness_report is None or target_report is None or feature_report is None:
            self._diagnostic_report_text.setPlainText(
                "Preview a current target and feature set before running diagnostics."
            )
            self._refresh_analysis_setup_state()
            return

        try:
            diagnostic_report = self._diagnostic_service.build_report(
                readiness_report=readiness_report,
                target_report=target_report,
                feature_set_report=feature_report,
            )
        except Exception as exc:
            self._diagnostic_report = None
            self._diagnostic_report_text.setPlainText(
                f"Diagnostic report failed:\n{type(exc).__name__}: {exc}"
            )
            self.statusBar().showMessage("Analysis Suite diagnostic report failed")
            self._refresh_analysis_setup_state()
            return

        self._diagnostic_report = diagnostic_report
        self._diagnostic_report_text.setPlainText(_diagnostic_report_summary(diagnostic_report))
        self.statusBar().showMessage(
            f"Analysis Suite diagnostic report: {_value_text(getattr(diagnostic_report, 'status', None))}"
        )
        self._refresh_analysis_setup_state()

    def _populate_feature_candidates(self, candidates: tuple[object, ...]) -> None:
        self._feature_table.blockSignals(True)
        self._feature_table.clearContents()
        self._feature_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            select_item = QTableWidgetItem("")
            select_item.setFlags(
                select_item.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
            )
            select_item.setCheckState(Qt.Checked if bool(getattr(candidate, "selected", False)) else Qt.Unchecked)
            select_item.setData(_CANDIDATE_ROLE, candidate)
            self._feature_table.setItem(row, 0, select_item)

            values = (
                getattr(candidate, "column_name", ""),
                getattr(candidate, "status", ""),
                getattr(candidate, "group", ""),
                _candidate_reason(candidate),
                _candidate_source(candidate),
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(_value_text(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(_candidate_reason(candidate))
                self._feature_table.setItem(row, column, item)
        self._feature_table.resizeColumnsToContents()
        self._feature_table.blockSignals(False)

    def _select_all_eligible_features(self) -> None:
        self._set_feature_selection(
            lambda candidate: str(getattr(candidate, "status", "")) == "eligible"
            and bool(getattr(candidate, "feature_eligible", False))
            and not tuple(getattr(candidate, "blockers", ()) or ())
        )

    def _clear_feature_selection(self) -> None:
        self._set_feature_selection(lambda _candidate: False)

    def _set_feature_selection(self, predicate: Callable[[object], bool]) -> None:
        self._feature_table.blockSignals(True)
        for row in range(self._feature_table.rowCount()):
            item = self._feature_table.item(row, 0)
            if item is None:
                continue
            candidate = item.data(_CANDIDATE_ROLE)
            item.setCheckState(Qt.Checked if predicate(candidate) else Qt.Unchecked)
        self._feature_table.blockSignals(False)
        self._on_feature_selection_changed()

    def _on_feature_candidate_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._on_feature_selection_changed()

    def _on_feature_selection_changed(self) -> None:
        if self._feature_candidates_report is not None:
            self._feature_set_report = None
            self._feature_set_report_key = None
            self._feature_report_text.setPlainText(
                "Feature selection changed. Preview the feature set before diagnostics."
            )
        self._clear_diagnostic_setup()
        self._refresh_analysis_setup_state()

    def _on_target_settings_changed(self) -> None:
        if getattr(self, "_target_report", None) is not None:
            self._target_report = None
            self._target_report_key = None
            self._target_report_text.setPlainText(
                "Target settings changed. Preview the target before diagnostics."
            )
        self._clear_feature_setup("Target settings changed. Refresh feature candidates.")
        self._clear_diagnostic_setup()
        self._refresh_analysis_setup_state()

    def _refresh_target_threshold_state(self) -> None:
        enabled = str(self._target_family.currentData() or "") == "future_direction"
        self._target_up_threshold.setEnabled(enabled)
        self._target_down_threshold.setEnabled(enabled)

    def _refresh_analysis_setup_state(self) -> None:
        report = self._selected_report
        can_preview = bool(getattr(report, "can_preview", False)) if report is not None else False
        self._target_preview_button.setEnabled(can_preview)
        self._feature_refresh_button.setEnabled(can_preview)
        has_candidates = self._feature_candidates_report is not None and self._feature_candidates_key == (
            self._current_feature_candidates_key()
        )
        self._feature_select_all_button.setEnabled(has_candidates)
        self._feature_clear_button.setEnabled(has_candidates)
        self._feature_preview_button.setEnabled(has_candidates and bool(self._selected_feature_columns()))
        self._diagnostic_button.setEnabled(
            self._target_report_is_current()
            and self._feature_set_report_is_current()
            and str(getattr(self._target_report, "status", "")) == "previewable"
            and str(getattr(self._feature_set_report, "status", "")) == "previewable"
        )

    def _clear_analysis_setup(self) -> None:
        self._clear_target_setup()
        self._clear_feature_setup()
        self._clear_diagnostic_setup()
        self._refresh_analysis_setup_state()

    def _clear_target_setup(self) -> None:
        self._target_report = None
        self._target_report_key = None
        self._target_report_text.setPlainText("Select a previewable Analysis Database.")

    def _clear_feature_setup(self, message: str = "List candidates for a previewable Analysis Database.") -> None:
        self._feature_candidates_report = None
        self._feature_candidates_key = None
        self._feature_set_report = None
        self._feature_set_report_key = None
        self._clear_feature_table()
        self._feature_report_text.setPlainText(message)

    def _clear_feature_table(self) -> None:
        self._feature_table.blockSignals(True)
        self._feature_table.clearContents()
        self._feature_table.setRowCount(0)
        self._feature_table.blockSignals(False)

    def _clear_diagnostic_setup(self) -> None:
        self._diagnostic_report = None
        self._diagnostic_report_text.setPlainText(
            "Preview a target and feature set before running diagnostics."
        )

    def _target_definition_from_controls(self) -> AnalysisSuiteTargetDefinition:
        horizon = int(self._target_horizon.value())
        family = str(self._target_family.currentData() or "")
        if family == "future_direction":
            return AnalysisSuiteTargetDefinition.future_direction(
                horizon_bars=horizon,
                up_threshold=float(self._target_up_threshold.value()),
                down_threshold=float(self._target_down_threshold.value()),
            )
        return AnalysisSuiteTargetDefinition.future_return(horizon_bars=horizon)

    def _selected_database_context(self) -> tuple[object, object, str] | None:
        report = self._selected_report
        if report is None:
            return None
        database_id = str(getattr(report, "database_id", ""))
        if not database_id:
            return None
        market = canonicalize(
            str(getattr(report, "exchange", "")),
            str(getattr(report, "market_type", "")),
            str(getattr(report, "symbol", "")),
            str(getattr(report, "timeframe", "")),
        )
        return report, market, database_id

    def _current_target_key(self) -> tuple[object, ...] | None:
        report = self._selected_report
        if report is None:
            return None
        return _database_key(report) + (
            str(self._target_family.currentData() or ""),
            int(self._target_horizon.value()),
            float(self._target_up_threshold.value()),
            float(self._target_down_threshold.value()),
        )

    def _current_feature_candidates_key(self) -> tuple[object, ...] | None:
        report = self._selected_report
        if report is None:
            return None
        return _database_key(report) + (self._target_report_key,)

    def _current_feature_set_key(self) -> tuple[object, ...] | None:
        candidates_key = self._current_feature_candidates_key()
        if candidates_key is None:
            return None
        return candidates_key + (self._selected_feature_columns(),)

    def _target_report_is_current(self) -> bool:
        return self._target_report is not None and self._target_report_key == self._current_target_key()

    def _feature_set_report_is_current(self) -> bool:
        return (
            self._feature_set_report is not None
            and self._feature_set_report_key == self._current_feature_set_key()
        )

    def _selected_feature_columns(self) -> tuple[str, ...]:
        selected: list[str] = []
        for row in range(self._feature_table.rowCount()):
            item = self._feature_table.item(row, 0)
            if item is None or item.checkState() != Qt.Checked:
                continue
            candidate = item.data(_CANDIDATE_ROLE)
            column = str(getattr(candidate, "column_name", ""))
            if column:
                selected.append(column)
        return tuple(selected)

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


def _target_report_summary(report: object) -> str:
    definition = getattr(report, "target_definition", None)
    lines = [
        f"Status: {_value_text(getattr(report, 'status', None))}",
        f"Target family: {_value_text(getattr(definition, 'target_family', None))}",
        f"Label type: {_value_text(getattr(definition, 'label_type', None))}",
        f"Output column: {_value_text(getattr(definition, 'output_column_name', None))}",
        f"Horizon bars: {_value_text(getattr(definition, 'horizon_bars', None))}",
        f"Rows: {_value_text(getattr(report, 'row_count', None))}",
        f"Available labels: {_value_text(getattr(report, 'available_label_count', None))}",
        f"Unavailable labels: {_value_text(getattr(report, 'unavailable_label_count', None))}",
        f"First available label ts: {_value_text(getattr(report, 'first_available_ts_ms', None))}",
        f"Last available label ts: {_value_text(getattr(report, 'last_available_ts_ms', None))}",
        _mapping_section("Regression stats", getattr(report, "regression_stats", {})),
        _mapping_section("Class distribution", getattr(report, "class_distribution", {})),
        _mapping_section("Leakage metadata", getattr(report, "leakage_summary", {})),
        _list_section("Warnings", getattr(report, "warnings", ())),
        _list_section("Blockers", getattr(report, "blockers", ())),
        _list_section("Errors", getattr(report, "errors", ())),
    ]
    return "\n".join(lines).strip()


def _feature_set_report_summary(report: object) -> str:
    lines = [
        f"Status: {_value_text(getattr(report, 'status', None))}",
        f"Total candidates: {_value_text(getattr(report, 'total_candidate_count', None))}",
        f"Eligible candidates: {_value_text(getattr(report, 'eligible_count', None))}",
        f"Blocked candidates: {_value_text(getattr(report, 'blocked_count', None))}",
        f"Warning candidates: {_value_text(getattr(report, 'warning_count', None))}",
        f"Selected features: {_value_text(getattr(report, 'selected_count', None))}",
        f"Accepted selected: {_value_text(getattr(report, 'accepted_selected_count', None))}",
        f"Rejected selected: {_value_text(getattr(report, 'rejected_selected_count', None))}",
        _candidate_list_section("Accepted features", getattr(report, "selected_features", ())),
        _candidate_list_section("Rejected features", getattr(report, "rejected_features", ())),
        _mapping_section("Group summary", getattr(report, "group_summary", {})),
        _mapping_section("Leakage summary", getattr(report, "leakage_summary", {})),
        _list_section("Warnings", getattr(report, "warnings", ())),
        _list_section("Blockers", getattr(report, "blockers", ())),
        _list_section("Errors", getattr(report, "errors", ())),
    ]
    return "\n".join(lines).strip()


def _diagnostic_report_summary(report: object) -> str:
    lines = [
        f"Status: {_value_text(getattr(report, 'status', None))}",
        f"Readiness: {_value_text(getattr(report, 'readiness_status', None))}",
        f"Strict ready: {_yes_no(getattr(report, 'strict_ready', False))}",
        f"Can preview: {_yes_no(getattr(report, 'can_preview', False))}",
        f"Rows: {_value_text(getattr(report, 'row_count', None))}",
        f"Columns: {_value_text(getattr(report, 'column_count', None))}",
        "",
        f"Target family: {_value_text(getattr(report, 'target_family', None))}",
        f"Target output: {_value_text(getattr(report, 'target_output_column', None))}",
        f"Horizon bars: {_value_text(getattr(report, 'horizon_bars', None))}",
        f"Available labels: {_value_text(getattr(report, 'available_label_count', None))}",
        f"Unavailable labels: {_value_text(getattr(report, 'unavailable_label_count', None))}",
        f"Label availability ratio: {_value_text(getattr(report, 'label_availability_ratio', None))}",
        _mapping_section("Regression stats", getattr(report, "regression_stats", {})),
        _mapping_section("Class distribution", getattr(report, "class_distribution", {})),
        "",
        f"Selected features: {_value_text(getattr(report, 'selected_feature_count', None))}",
        f"Accepted features: {_value_text(getattr(report, 'accepted_feature_count', None))}",
        f"Rejected features: {_value_text(getattr(report, 'rejected_feature_count', None))}",
        _list_section("Selected feature names", getattr(report, "selected_features", ())),
        _list_section("Rejected feature names", getattr(report, "rejected_features", ())),
        _mapping_section("Group summary", getattr(report, "group_summary", {})),
        "",
        f"Has leakage blockers: {_yes_no(getattr(report, 'has_leakage_blockers', False))}",
        _mapping_section("Leakage summary", getattr(report, "leakage_summary", {})),
        _feature_diagnostic_section(getattr(report, "feature_column_diagnostics", ())),
        _list_section("Warnings", getattr(report, "warnings", ())),
        _list_section("Blockers", getattr(report, "blockers", ())),
        _list_section("Errors", getattr(report, "errors", ())),
    ]
    return "\n".join(lines).strip()


def _mapping_section(label: str, values: object) -> str:
    if not isinstance(values, dict):
        values = dict(values or {}) if hasattr(values, "items") else {}
    if not values:
        return f"{label}: none"
    return f"{label}:\n" + "\n".join(
        f"- {key}: {_value_text(value)}"
        for key, value in sorted(values.items(), key=lambda item: str(item[0]))
    )


def _candidate_list_section(label: str, candidates: object) -> str:
    names = tuple(
        str(getattr(candidate, "column_name", ""))
        for candidate in candidates or ()
        if str(getattr(candidate, "column_name", ""))
    )
    return _list_section(label, names)


def _feature_diagnostic_section(diagnostics: object) -> str:
    items = tuple(diagnostics or ())
    if not items:
        return "Feature column diagnostics: none"
    lines = ["Feature column diagnostics:"]
    for diagnostic in items[:12]:
        lines.append(
            "- "
            f"{_value_text(getattr(diagnostic, 'column_name', None))}: "
            f"dtype={_value_text(getattr(diagnostic, 'dtype', None))}, "
            f"null_ratio={_value_text(getattr(diagnostic, 'null_ratio', None))}"
        )
    if len(items) > 12:
        lines.append(f"- ... {len(items) - 12} more")
    return "\n".join(lines)


def _list_section(label: str, values: object) -> str:
    items = tuple(str(item) for item in values or ())
    if not items:
        return f"{label}: none"
    return f"{label}:\n" + "\n".join(f"- {item}" for item in items)


def _candidate_reason(candidate: object) -> str:
    blockers = tuple(str(item) for item in getattr(candidate, "blockers", ()) or ())
    warnings = tuple(str(item) for item in getattr(candidate, "warnings", ()) or ())
    if blockers:
        return "; ".join(blockers)
    if warnings:
        return "; ".join(warnings)
    return ""


def _candidate_source(candidate: object) -> str:
    for attr in ("tool_title", "tool_key", "source_family", "source_id"):
        value = getattr(candidate, attr, None)
        if value:
            return str(value)
    return ""


def _database_key(report: object) -> tuple[str, str, str, str, str]:
    return (
        str(getattr(report, "exchange", "")),
        str(getattr(report, "market_type", "")),
        str(getattr(report, "symbol", "")),
        str(getattr(report, "timeframe", "")),
        str(getattr(report, "database_id", "")),
    )


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
