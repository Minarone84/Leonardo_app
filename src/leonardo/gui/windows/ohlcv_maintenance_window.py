"""Qt window for historical OHLCV dataset inspection and maintenance actions."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.core_bridge import CoreBridge


class OHLCVMaintenanceWindow(QMainWindow):
    """
    Inspector and explicit maintenance workflow for persisted OHLCV datasets.

    The window owns presentation and user interaction only. Dataset catalog
    inspection, validation, deletion, and metadata rebuild are requested through
    CoreBridge so persistence contracts remain in the data layer.
    """

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bridge = core_bridge
        self._datasets: tuple[object, ...] = ()
        self._selected_dataset: object | None = None
        self._last_repair_plan: object | None = None
        self._pending: dict[str, Future[object]] = {}
        self._select_first_after_refresh = True
        self._validation_status_by_key: dict[tuple[str, str, str, str], str] = {}
        self._validation_running = False
        self._validation_batch_targets: tuple[object, ...] = ()
        self._validation_batch_queue: list[object] = []
        self._validation_batch_current: object | None = None
        self._validation_batch_total = 0
        self._validation_batch_done = 0
        self._validation_batch_cancel_requested = False
        self._validation_progress: QProgressDialog | None = None

        self.setWindowTitle("OHLCV Maintenance")
        self.resize(1160, 720)
        self.setMinimumSize(940, 560)
        self.statusBar().showMessage("Ready")

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Historical OHLCV Maintenance", self)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._refresh_button = QPushButton("Refresh Datasets", self)
        self._validate_button = QPushButton("Analyze / Validate Selected", self)
        self._repair_plan_button = QPushButton("Plan Repair", self)
        self._execute_repair_button = QPushButton("Execute Repair...", self)
        self._rebuild_metadata_button = QPushButton("Rebuild Metadata...", self)
        self._delete_button = QPushButton("Delete Selected", self)
        self._validate_button.setEnabled(False)
        self._repair_plan_button.setEnabled(False)
        self._execute_repair_button.setEnabled(False)
        self._rebuild_metadata_button.setEnabled(False)
        self._delete_button.setEnabled(False)
        toolbar.addWidget(self._refresh_button)
        toolbar.addWidget(self._validate_button)
        toolbar.addWidget(self._repair_plan_button)
        toolbar.addWidget(self._execute_repair_button)
        toolbar.addWidget(self._rebuild_metadata_button)
        toolbar.addWidget(self._delete_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 5)

        dataset_group = QGroupBox("OHLCV Datasets", splitter)
        dataset_layout = QVBoxLayout(dataset_group)
        selection_toolbar = QHBoxLayout()
        selection_toolbar.setSpacing(8)
        self._select_all_button = QPushButton("Select All", dataset_group)
        self._deselect_all_button = QPushButton("Deselect All", dataset_group)
        self._select_all_button.setEnabled(False)
        self._deselect_all_button.setEnabled(False)
        selection_toolbar.addWidget(self._select_all_button)
        selection_toolbar.addWidget(self._deselect_all_button)
        selection_toolbar.addStretch(1)
        dataset_layout.addLayout(selection_toolbar)
        self._dataset_table = QTableWidget(0, 7, dataset_group)
        self._dataset_table.setHorizontalHeaderLabels(
            ["Select", "Exchange", "Market", "Symbol", "Timeframe", "Storage", "Validation"]
        )
        self._dataset_table.horizontalHeader().setStretchLastSection(True)
        self._dataset_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._dataset_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._dataset_table.setSelectionMode(QTableWidget.SingleSelection)
        self._dataset_table.verticalHeader().setVisible(False)
        dataset_layout.addWidget(self._dataset_table, 1)
        splitter.addWidget(dataset_group)

        details_group = QGroupBox("Dataset Details", splitter)
        details_layout = QVBoxLayout(details_group)
        self._details = QPlainTextEdit(details_group)
        self._details.setReadOnly(True)
        self._details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._details.setPlainText("Select a dataset to inspect CSV and metadata state.")
        details_layout.addWidget(self._details, 1)
        splitter.addWidget(details_group)
        splitter.setSizes([420, 700])

        validation_group = QGroupBox("Validation Report", self)
        validation_layout = QVBoxLayout(validation_group)
        self._validation = QPlainTextEdit(validation_group)
        self._validation.setReadOnly(True)
        self._validation.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._validation.setMinimumHeight(160)
        self._validation.setPlainText(
            "Check one or more datasets, then run Analyze / Validate Selected."
        )
        validation_layout.addWidget(self._validation, 1)
        layout.addWidget(validation_group, 2)

        self._watch = QTimer(self)
        self._watch.setInterval(150)
        self._watch.timeout.connect(self._poll_pending)

        self._refresh_button.clicked.connect(self.refresh_datasets)
        self._validate_button.clicked.connect(self.validate_selected)
        self._repair_plan_button.clicked.connect(self.plan_repair_selected)
        self._execute_repair_button.clicked.connect(self.execute_repair_selected)
        self._rebuild_metadata_button.clicked.connect(self.rebuild_metadata_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._select_all_button.clicked.connect(self.select_all_datasets)
        self._deselect_all_button.clicked.connect(self.deselect_all_datasets)
        self._dataset_table.itemSelectionChanged.connect(self._on_selection_changed)

        self.refresh_datasets()

    def refresh_datasets(self) -> None:
        """Request the current read-only OHLCV dataset catalog."""
        self._request_dataset_list(select_first=True)

    def _request_dataset_list(self, *, select_first: bool) -> None:
        """Request the dataset catalog and control post-refresh selection."""
        self._select_first_after_refresh = bool(select_first)
        self._last_repair_plan = None
        self._refresh_button.setEnabled(False)
        self._set_dataset_selection_buttons_enabled(False)
        self._set_execute_repair_enabled(False)
        self._start_future("list", self._bridge.list_historical_ohlcv_datasets())
        self.statusBar().showMessage("Loading OHLCV dataset list...")

    def validate_selected(self) -> None:
        """Request validation for checked datasets or the current row."""
        targets = self._checked_datasets()
        if not targets and self._selected_dataset is not None:
            targets = (self._selected_dataset,)
        if not targets:
            self.statusBar().showMessage("Select an OHLCV dataset before validating")
            return
        self._last_repair_plan = None
        self._set_execute_repair_enabled(False)
        self._start_validation_batch(targets)

    def select_all_datasets(self) -> None:
        """Check every dataset row in the maintenance table."""
        self._set_all_dataset_checks(Qt.CheckState.Checked)

    def deselect_all_datasets(self) -> None:
        """Clear every dataset row checkbox in the maintenance table."""
        self._set_all_dataset_checks(Qt.CheckState.Unchecked)

    def plan_repair_selected(self) -> None:
        """Request a read-only repair plan for the current OHLCV dataset."""
        summary = self._selected_dataset
        if summary is None:
            self.statusBar().showMessage("Select an OHLCV dataset before planning repair")
            return

        self._last_repair_plan = None
        self._set_execute_repair_enabled(False)
        self._set_selected_actions_enabled(False)
        self._validation.setPlainText("Planning repair ranges for the selected OHLCV dataset...")
        self._start_future(
            "repair_plan",
            self._bridge.plan_historical_ohlcv_repair(**self._identity_kwargs(summary)),
        )
        self.statusBar().showMessage("Planning OHLCV repair ranges...")

    def execute_repair_selected(self) -> None:
        """Confirm and execute the last reviewed OHLCV repair plan."""
        summary = self._selected_dataset
        plan = self._last_repair_plan
        if summary is None or plan is None:
            self.statusBar().showMessage("Plan repair before executing repair")
            return
        if not bool(getattr(plan, "actionable", False)):
            self.statusBar().showMessage("Repair plan has no actionable ranges")
            return
        if not self._confirm_execute_repair(plan):
            self.statusBar().showMessage("Repair execution cancelled")
            return

        self._set_selected_actions_enabled(False)
        self._set_execute_repair_enabled(False)
        self._validation.setPlainText("Executing OHLCV repair plan...")
        self._start_future(
            "execute_repair",
            self._bridge.execute_historical_ohlcv_repair(
                **self._identity_kwargs(summary),
                plan=plan,
            ),
        )
        self.statusBar().showMessage("Executing OHLCV repair plan...")

    def rebuild_metadata_selected(self) -> None:
        """Confirm and request metadata rebuild for the selected OHLCV dataset."""
        summary = self._selected_dataset
        if summary is None:
            self.statusBar().showMessage("Select an OHLCV dataset before rebuilding metadata")
            return
        if not self._confirm_rebuild_metadata(summary):
            self.statusBar().showMessage("Metadata rebuild cancelled")
            return

        self._set_selected_actions_enabled(False)
        self._details.setPlainText("Rebuilding selected OHLCV metadata...")
        self._start_future(
            "rebuild_metadata",
            self._bridge.rebuild_historical_ohlcv_metadata(**self._identity_kwargs(summary)),
        )
        self.statusBar().showMessage("Rebuilding selected OHLCV metadata...")

    def delete_selected(self) -> None:
        """Confirm and request deletion of the currently selected OHLCV dataset."""
        summary = self._selected_dataset
        if summary is None:
            self.statusBar().showMessage("Select an OHLCV dataset before deleting")
            return
        if not self._confirm_delete(summary):
            self.statusBar().showMessage("Delete cancelled")
            return

        self._set_selected_actions_enabled(False)
        self._details.setPlainText("Deleting selected OHLCV dataset...")
        self._start_future("delete", self._bridge.delete_historical_ohlcv_dataset(**self._identity_kwargs(summary)))
        self.statusBar().showMessage("Deleting selected OHLCV dataset...")

    def _on_selection_changed(self) -> None:
        summary = self._current_dataset()
        self._selected_dataset = summary
        self._last_repair_plan = None
        self._set_selected_actions_enabled(summary is not None)
        if not self._validation_running:
            self._validation.setPlainText(
                "Check one or more datasets, then run Analyze / Validate Selected."
            )
        if summary is None:
            self._details.setPlainText("Select a dataset to inspect CSV and metadata state.")
            return
        self._details.setPlainText("Inspecting selected dataset...")
        self._start_future("inspect", self._bridge.inspect_historical_ohlcv_dataset(**self._identity_kwargs(summary)))
        self.statusBar().showMessage("Inspecting selected OHLCV dataset...")

    def _start_future(self, name: str, future: Future[object]) -> None:
        self._pending[name] = future
        if not self._watch.isActive():
            self._watch.start()

    def _poll_pending(self) -> None:
        for name, future in list(self._pending.items()):
            if not future.done():
                continue
            self._pending.pop(name, None)
            try:
                result = future.result()
            except Exception as exc:
                self._handle_future_error(name, exc)
                continue

            if name == "list":
                self._render_dataset_list(result)
            elif name == "inspect":
                self._details.setPlainText(self._format_inspection(result))
                self.statusBar().showMessage("Dataset inspection complete")
            elif name == "validate_batch":
                self._handle_validation_batch_result(result)
            elif name == "repair_plan":
                if (
                    self._selected_dataset is not None
                    and self._dataset_key(getattr(result, "dataset", None)) != self._dataset_key(self._selected_dataset)
                ):
                    self.statusBar().showMessage("Discarded repair plan for a dataset that is no longer selected")
                    continue
                self._last_repair_plan = result
                self._validation.setPlainText(self._format_repair_plan(result))
                self._set_selected_actions_enabled(self._selected_dataset is not None)
                self._set_execute_repair_enabled(
                    self._selected_dataset is not None and bool(getattr(result, "actionable", False))
                )
                self.statusBar().showMessage("OHLCV repair plan ready")
            elif name == "execute_repair":
                self._last_repair_plan = None
                self._validation.setPlainText(self._format_repair_execution(result))
                self._set_selected_actions_enabled(self._selected_dataset is not None)
                self._set_execute_repair_enabled(False)
                dataset = getattr(result, "dataset", self._selected_dataset)
                if dataset is not None:
                    self._set_dataset_validation_status(
                        dataset,
                        self._display_validation_status(self._text(result, "validation_status")),
                    )
                self.statusBar().showMessage("OHLCV repair execution complete")
                if self._selected_dataset is not None:
                    self._details.setPlainText("Refreshing selected dataset inspection...")
                    self._start_future(
                        "inspect",
                        self._bridge.inspect_historical_ohlcv_dataset(**self._identity_kwargs(self._selected_dataset)),
                    )
            elif name == "rebuild_metadata":
                self._validation.setPlainText(self._format_metadata_rebuild(result))
                self._set_selected_actions_enabled(self._selected_dataset is not None)
                self.statusBar().showMessage("OHLCV metadata rebuilt")
                if self._selected_dataset is not None:
                    self._details.setPlainText("Refreshing selected dataset inspection...")
                    self._start_future(
                        "inspect",
                        self._bridge.inspect_historical_ohlcv_dataset(**self._identity_kwargs(self._selected_dataset)),
                    )
            elif name == "delete":
                self._details.setPlainText(self._format_delete(result))
                self._validation.setPlainText("Dataset list refreshed after delete.")
                self._last_repair_plan = None
                self._selected_dataset = None
                self._set_selected_actions_enabled(False)
                self.statusBar().showMessage("OHLCV dataset deleted")
                self._request_dataset_list(select_first=False)

        if not self._pending and self._watch.isActive():
            self._watch.stop()

    def _handle_future_error(self, name: str, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if name == "list":
            self._refresh_button.setEnabled(True)
            self._set_dataset_selection_buttons_enabled(False)
            self._details.setPlainText(f"Dataset list failed:\n{message}")
        elif name == "inspect":
            self._details.setPlainText(f"Dataset inspection failed:\n{message}")
        elif name == "validate_batch":
            if self._validation_batch_current is not None:
                self._set_dataset_validation_status(self._validation_batch_current, "Error")
            self._validation.setPlainText(f"Validation failed:\n{message}")
            self._finish_validation_batch(cancelled=True)
            self._set_selected_actions_enabled(self._selected_dataset is not None)
        elif name == "repair_plan":
            self._validation.setPlainText(f"Repair planning failed:\n{message}")
            self._last_repair_plan = None
            self._set_execute_repair_enabled(False)
            self._set_selected_actions_enabled(self._selected_dataset is not None)
        elif name == "execute_repair":
            self._validation.setPlainText(f"Repair execution failed:\n{message}")
            self._set_execute_repair_enabled(self._last_repair_plan is not None)
            self._set_selected_actions_enabled(self._selected_dataset is not None)
        elif name == "rebuild_metadata":
            self._details.setPlainText(f"Metadata rebuild failed:\n{message}")
            self._set_selected_actions_enabled(self._selected_dataset is not None)
        elif name == "delete":
            self._details.setPlainText(f"Dataset delete failed:\n{message}")
            self._set_selected_actions_enabled(self._selected_dataset is not None)
        self.statusBar().showMessage(f"OHLCV maintenance action failed: {message}")

    def _render_dataset_list(self, result: object) -> None:
        datasets = tuple(result or ())  # type: ignore[arg-type]
        self._datasets = datasets
        self._last_repair_plan = None
        self._refresh_button.setEnabled(True)
        self._set_dataset_selection_buttons_enabled(bool(datasets))
        select_first = self._select_first_after_refresh
        self._select_first_after_refresh = True

        self._dataset_table.blockSignals(True)
        self._dataset_table.setRowCount(0)
        for row, summary in enumerate(datasets):
            self._dataset_table.insertRow(row)
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                (check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsEditable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setData(Qt.ItemDataRole.UserRole, summary)
            self._dataset_table.setItem(row, 0, check_item)

            values = [
                self._text(summary, "exchange"),
                self._text(summary, "market_type"),
                self._text(summary, "symbol"),
                self._text(summary, "timeframe"),
                self._text(summary, "storage_segment"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                self._dataset_table.setItem(row, column + 1, item)

            validation_status = self._validation_status_by_key.get(
                self._dataset_key(summary),
                self._display_validation_status(self._text(summary, "validation_status")),
            )
            validation_item = QTableWidgetItem(validation_status)
            self._dataset_table.setItem(row, 6, validation_item)
            self._apply_row_validation_style(row, validation_status)
        self._dataset_table.resizeColumnsToContents()

        if datasets and select_first:
            self._dataset_table.selectRow(0)
        self._dataset_table.blockSignals(False)

        if datasets and select_first:
            self._on_selection_changed()
            self.statusBar().showMessage(f"Loaded {len(datasets)} OHLCV dataset(s)")
        elif datasets:
            self._selected_dataset = None
            self._set_selected_actions_enabled(False)
            self.statusBar().showMessage(f"Loaded {len(datasets)} OHLCV dataset(s)")
        else:
            self._selected_dataset = None
            self._set_selected_actions_enabled(False)
            self._set_dataset_selection_buttons_enabled(False)
            self._details.setPlainText("No OHLCV datasets found.")
            self._validation.setPlainText("No dataset selected.")
            self.statusBar().showMessage("No OHLCV datasets found")

    def _current_dataset(self) -> object | None:
        row = self._dataset_table.currentRow()
        if row < 0:
            return None
        item = self._dataset_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _identity_kwargs(self, summary: object) -> dict[str, str]:
        return {
            "exchange": self._text(summary, "exchange"),
            "market_type": self._text(summary, "market_type"),
            "symbol": self._text(summary, "symbol"),
            "timeframe": self._text(summary, "timeframe"),
        }

    def _format_inspection(self, report: object) -> str:
        dataset = getattr(report, "dataset", None)
        manifest = getattr(report, "manifest", None)
        lines = [
            "Dataset",
            f"  Exchange: {self._text(dataset, 'exchange')}",
            f"  Market type: {self._text(dataset, 'market_type')}",
            f"  Symbol: {self._text(dataset, 'symbol')}",
            f"  Timeframe: {self._text(dataset, 'timeframe')}",
            f"  Storage segment: {self._text(dataset, 'storage_segment')}",
            "",
            "Files",
            f"  CSV: {self._text(dataset, 'csv_path')}",
            f"  Metadata: {self._text(dataset, 'metadata_path')}",
            "",
            "Local State",
            f"  CSV exists: {self._yes_no(getattr(report, 'csv_exists', False))}",
            f"  Metadata exists: {self._yes_no(getattr(report, 'metadata_exists', False))}",
            f"  Metadata valid: {self._yes_no(getattr(report, 'metadata_valid', False))}",
            f"  Metadata status: {self._text(report, 'metadata_status')}",
            f"  Local state source: {self._text(report, 'local_state_source')}",
            f"  Row count: {self._text(report, 'row_count')}",
            f"  First ts_ms: {self._text(report, 'first_ts_ms')}",
            f"  Last ts_ms: {self._text(report, 'last_ts_ms')}",
        ]
        metadata_error = self._text(report, "metadata_error")
        if metadata_error:
            lines.append(f"  Metadata error: {metadata_error}")

        issues = tuple(getattr(report, "issues", ()) or ())
        if issues:
            lines.extend(["", "Inspection Issues"])
            lines.extend(f"  - {issue}" for issue in issues)

        if manifest is not None:
            lines.extend(
                [
                    "",
                    "Manifest",
                    f"  Unique ID: {self._text(manifest, 'unique_id')}",
                    f"  Artifact UID: {self._text(manifest, 'artifact_uid')}",
                    f"  Family: {self._text(manifest, 'artifact_family')}",
                    f"  Storage family: {self._text(manifest, 'storage_family')}",
                    f"  Manifest market: {self._manifest_market(manifest)}",
                    f"  CSV relpath: {self._text(manifest, 'csv_relpath')}",
                    f"  Metadata relpath: {self._text(manifest, 'metadata_relpath')}",
                    f"  Row count: {self._text(manifest, 'row_count')}",
                    f"  Column count: {self._text(manifest, 'column_count')}",
                    f"  Columns: {', '.join(tuple(getattr(manifest, 'columns', ()) or ())) or '-'}",
                    f"  First UTC: {self._text(manifest, 'first_ts_utc')}",
                    f"  First Europe/Rome: {self._text(manifest, 'first_ts_rome')}",
                    f"  Last UTC: {self._text(manifest, 'last_ts_utc')}",
                    f"  Last Europe/Rome: {self._text(manifest, 'last_ts_rome')}",
                    f"  Timeline status: {self._text(manifest, 'timeline_status')}",
                    f"  Validation status: {self._text(manifest, 'validation_status')}",
                    f"  Explicit validation: {self._display_validation_status(self._text(manifest, 'explicit_validation_status'))}",
                    f"  Validated at: {self._text(manifest, 'validated_at')}",
                    f"  Validator: {self._text(manifest, 'validation_validator')}",
                    f"  Validation row count: {self._text(manifest, 'validation_row_count')}",
                    f"  Validation issue count: {self._text(manifest, 'validation_issue_count')}",
                    f"  Validation warnings: {self._text(manifest, 'validation_warning_count')}",
                    f"  Validation errors: {self._text(manifest, 'validation_error_count')}",
                    f"  Validation message: {self._text(manifest, 'validation_message')}",
                    f"  Fingerprint size bytes: {self._text(manifest, 'fingerprint_size_bytes')}",
                    f"  Fingerprint modified ms: {self._text(manifest, 'fingerprint_modified_at_ms')}",
                ]
            )
            notes = tuple(getattr(manifest, "validation_notes", ()) or ())
            if notes:
                lines.extend(["", "Manifest Validation Notes"])
                lines.extend(f"  - {note}" for note in notes)
        return "\n".join(lines)

    def _format_validation(self, report: object) -> str:
        dataset = getattr(report, "dataset", None)
        lines = [
            "Validation",
            f"  Dataset: {self._dataset_label(dataset)}",
            f"  Status: {self._text(report, 'status')}",
            f"  Row count: {self._text(report, 'row_count')}",
            f"  Metadata updated: {self._yes_no(getattr(report, 'metadata_updated', False))}",
        ]
        metadata_error = self._text(report, "metadata_update_error")
        if metadata_error:
            lines.append(f"  Metadata update error: {metadata_error}")
        issues = tuple(getattr(report, "issues", ()) or ())
        if issues:
            lines.extend(["", "Issues"])
            lines.extend(
                f"  - {self._text(issue, 'severity')}: {self._text(issue, 'message')}"
                for issue in issues
            )
        else:
            lines.extend(["", "No validation issues detected."])
        return "\n".join(lines)

    def _format_batch_validation(self, latest_report: object) -> str:
        lines = [
            "Batch Validation",
            f"  Completed: {self._validation_batch_done} / {self._validation_batch_total}",
            "",
            "Dataset Status",
        ]
        for summary in self._validation_batch_targets:
            status = self._validation_status_by_key.get(self._dataset_key(summary), "Unknown")
            lines.append(f"  {self._dataset_label(summary)}: {status}")
        lines.extend(["", "Latest Result", self._format_validation(latest_report)])
        return "\n".join(lines)

    def _format_repair_plan(self, plan: object) -> str:
        dataset = getattr(plan, "dataset", None)
        lines = [
            "Repair Plan",
            f"  Dataset: {self._dataset_label(dataset)}",
            f"  Validation status: {self._text(plan, 'status')}",
            f"  Row count: {self._text(plan, 'row_count')}",
            f"  Actionable: {self._yes_no(getattr(plan, 'actionable', False))}",
            f"  Message: {self._text(plan, 'message')}",
        ]

        ranges = tuple(getattr(plan, "ranges", ()) or ())
        if ranges:
            lines.extend(["", "Proposed Redownload Ranges"])
            for index, item in enumerate(ranges, start=1):
                rows = ", ".join(str(row) for row in tuple(getattr(item, "rows", ()) or ()))
                lines.extend(
                    [
                        f"  Range {index}",
                        f"    Start ts_ms: {self._text(item, 'start_ts_ms')}",
                        f"    End ts_ms: {self._text(item, 'end_ts_ms')}",
                        f"    Start UTC: {self._text(item, 'start_utc')}",
                        f"    End UTC: {self._text(item, 'end_utc')}",
                        f"    Start Europe/Rome: {self._text(item, 'start_rome')}",
                        f"    End Europe/Rome: {self._text(item, 'end_rome')}",
                        f"    Rows: {rows or '-'}",
                        f"    Issue count: {self._text(item, 'issue_count')}",
                        f"    Reason: {self._text(item, 'reason')}",
                    ]
                )
        else:
            lines.extend(["", "No proposed redownload ranges."])

        warnings = tuple(getattr(plan, "warnings", ()) or ())
        if warnings:
            lines.extend(["", "Warnings"])
            lines.extend(f"  - {warning}" for warning in warnings)

        issues = tuple(getattr(plan, "issues", ()) or ())
        if issues:
            lines.extend(["", "Validation Issues"])
            lines.extend(
                f"  - {self._text(issue, 'severity')}: {self._text(issue, 'message')}"
                for issue in issues
            )
        return "\n".join(lines)

    def _format_repair_execution(self, report: object) -> str:
        dataset = getattr(report, "dataset", None)
        lines = [
            "Repair Execution Complete",
            f"  Dataset: {self._dataset_label(dataset)}",
            f"  Ranges requested: {self._text(report, 'ranges_requested')}",
            f"  Ranges completed: {self._text(report, 'ranges_completed')}",
            f"  Final validation status: {self._text(report, 'validation_status')}",
            f"  Final validation row count: {self._text(report, 'validation_row_count')}",
            f"  Metadata updated: {self._yes_no(getattr(report, 'metadata_updated', False))}",
            f"  Cache invalidated: {self._yes_no(getattr(report, 'cache_invalidated', False))}",
            "",
            "Files",
            f"  CSV: {self._text(report, 'csv_path')}",
            f"  Metadata: {self._text(report, 'metadata_path')}",
        ]
        metadata_error = self._text(report, "metadata_update_error")
        if metadata_error:
            lines.append(f"  Metadata update error: {metadata_error}")

        range_results = tuple(getattr(report, "range_results", ()) or ())
        if range_results:
            lines.extend(["", "Executed Ranges"])
            for index, item in enumerate(range_results, start=1):
                lines.extend(
                    [
                        f"  Range {index}",
                        f"    Start ts_ms: {self._text(item, 'start_ts_ms')}",
                        f"    End ts_ms: {self._text(item, 'end_ts_ms')}",
                        f"    Start UTC: {self._text(item, 'start_utc')}",
                        f"    End UTC: {self._text(item, 'end_utc')}",
                        f"    Rows after: {self._text(item, 'total_rows_after')}",
                        f"    Job ID: {self._text(item, 'job_id')}",
                    ]
                )

        issues = tuple(getattr(report, "validation_issues", ()) or ())
        if issues:
            lines.extend(["", "Final Validation Issues"])
            lines.extend(
                f"  - {self._text(issue, 'severity')}: {self._text(issue, 'message')}"
                for issue in issues
            )
        else:
            lines.extend(["", "Final validation detected no issues."])

        lines.extend(["", self._text(report, "message")])
        return "\n".join(lines)

    def _format_delete(self, report: object) -> str:
        dataset = getattr(report, "dataset", None)
        return "\n".join(
            [
                "Delete Complete",
                f"  Dataset: {self._dataset_label(dataset)}",
                f"  CSV deleted: {self._yes_no(getattr(report, 'csv_deleted', False))}",
                f"  Metadata deleted: {self._yes_no(getattr(report, 'metadata_deleted', False))}",
                f"  Cache invalidated: {self._yes_no(getattr(report, 'cache_invalidated', False))}",
                "",
                "Files",
                f"  CSV: {self._text(report, 'csv_path')}",
                f"  Metadata: {self._text(report, 'metadata_path')}",
                "",
                self._text(report, "message"),
            ]
        )

    def _format_metadata_rebuild(self, report: object) -> str:
        dataset = getattr(report, "dataset", None)
        return "\n".join(
            [
                "Metadata Rebuild Complete",
                f"  Dataset: {self._dataset_label(dataset)}",
                f"  Metadata rebuilt: {self._yes_no(getattr(report, 'metadata_rebuilt', False))}",
                f"  Cache invalidated: {self._yes_no(getattr(report, 'cache_invalidated', False))}",
                f"  Row count: {self._text(report, 'row_count')}",
                "",
                "Files",
                f"  CSV: {self._text(report, 'csv_path')}",
                f"  Metadata: {self._text(report, 'metadata_path')}",
                "",
                self._text(report, "message"),
            ]
        )

    def _confirm_rebuild_metadata(self, summary: object) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Rebuild OHLCV Metadata")
        dialog.setText("Rebuild metadata for the selected OHLCV dataset?")
        dialog.setInformativeText(
            f"Dataset: {self._dataset_label(summary)}\n\n"
            "The CSV values will not be changed.\n"
            f"Metadata sidecar to rewrite: {self._text(summary, 'metadata_path')}"
        )
        rebuild_button = dialog.addButton("Rebuild Metadata", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is rebuild_button

    def _confirm_delete(self, summary: object) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Delete OHLCV Dataset")
        dialog.setText("Delete the selected OHLCV dataset?")
        dialog.setInformativeText(
            f"Dataset: {self._dataset_label(summary)}\n\n"
            "The following files will be deleted if present:\n"
            f"CSV: {self._text(summary, 'csv_path')}\n"
            f"Metadata: {self._text(summary, 'metadata_path')}"
        )
        delete_button = dialog.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _confirm_execute_repair(self, plan: object) -> bool:
        dataset = getattr(plan, "dataset", None)
        ranges = tuple(getattr(plan, "ranges", ()) or ())
        range_lines = [
            f"{index}. {self._text(item, 'start_utc')} -> {self._text(item, 'end_utc')}"
            for index, item in enumerate(ranges, start=1)
        ]

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Execute OHLCV Repair")
        dialog.setText("Execute the reviewed OHLCV repair plan?")
        dialog.setInformativeText(
            f"Dataset: {self._dataset_label(dataset)}\n\n"
            "The planned ranges will be redownloaded and merged into candles.csv.\n"
            "Metadata and validation status will be updated after repair.\n\n"
            "Planned ranges:\n"
            + ("\n".join(range_lines) if range_lines else "-")
        )
        execute_button = dialog.addButton("Execute Repair", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is execute_button

    def _set_selected_actions_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled) and not self._validation_running
        self._validate_button.setEnabled(enabled)
        self._repair_plan_button.setEnabled(enabled)
        self._rebuild_metadata_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)
        self._set_execute_repair_enabled(enabled and self._last_repair_plan is not None)

    def _set_execute_repair_enabled(self, enabled: bool) -> None:
        self._execute_repair_button.setEnabled(
            bool(enabled)
            and not self._validation_running
            and self._selected_dataset is not None
            and self._last_repair_plan is not None
            and bool(getattr(self._last_repair_plan, "actionable", False))
        )

    def _checked_datasets(self) -> tuple[object, ...]:
        datasets: list[object] = []
        for row in range(self._dataset_table.rowCount()):
            item = self._dataset_table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            summary = item.data(Qt.ItemDataRole.UserRole)
            if summary is not None:
                datasets.append(summary)
        return tuple(datasets)

    def _start_validation_batch(self, summaries: tuple[object, ...]) -> None:
        self._validation_running = True
        self._validation_batch_targets = summaries
        self._validation_batch_queue = list(summaries)
        self._validation_batch_current = None
        self._validation_batch_total = len(summaries)
        self._validation_batch_done = 0
        self._validation_batch_cancel_requested = False
        self._refresh_button.setEnabled(False)
        self._set_dataset_selection_buttons_enabled(False)
        self._set_selected_actions_enabled(False)

        if len(summaries) > 1:
            progress = QProgressDialog(
                "Validating selected OHLCV datasets...",
                "Cancel",
                0,
                len(summaries),
                self,
            )
            progress.setWindowTitle("OHLCV Validation")
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.canceled.connect(self._cancel_validation_batch)
            self._validation_progress = progress
            progress.show()

        self._validation.setPlainText(
            f"Validation running for {len(summaries)} OHLCV dataset(s)..."
        )
        self.statusBar().showMessage(
            f"Validating {len(summaries)} selected OHLCV dataset(s)..."
        )
        self._start_next_validation_in_batch()

    def _start_next_validation_in_batch(self) -> None:
        if self._validation_batch_cancel_requested:
            self._finish_validation_batch(cancelled=True)
            return
        if not self._validation_batch_queue:
            self._finish_validation_batch(cancelled=False)
            return

        summary = self._validation_batch_queue.pop(0)
        self._validation_batch_current = summary
        self._start_future(
            "validate_batch",
            self._bridge.validate_historical_ohlcv_dataset(**self._identity_kwargs(summary)),
        )

    def _handle_validation_batch_result(self, report: object) -> None:
        summary = self._validation_batch_current
        if summary is not None:
            self._set_dataset_validation_status(summary, self._validation_status_for_report(report))
        self._validation_batch_done += 1

        if self._validation_progress is not None:
            self._validation_progress.setValue(self._validation_batch_done)

        if self._validation_batch_total > 1:
            self._validation.setPlainText(self._format_batch_validation(report))
        else:
            self._validation.setPlainText(self._format_validation(report))

        self._start_next_validation_in_batch()

    def _cancel_validation_batch(self) -> None:
        self._validation_batch_cancel_requested = True
        self.statusBar().showMessage("Validation cancellation requested")

    def _finish_validation_batch(self, *, cancelled: bool) -> None:
        self._validation_running = False
        self._validation_batch_queue = []
        self._validation_batch_current = None
        self._refresh_button.setEnabled(True)
        self._set_dataset_selection_buttons_enabled(bool(self._datasets))
        self._set_selected_actions_enabled(self._selected_dataset is not None)

        if self._validation_progress is not None:
            self._validation_progress.close()
            self._validation_progress = None

        if cancelled:
            self.statusBar().showMessage("Validation cancelled")
        else:
            self.statusBar().showMessage(
                f"Validation complete for {self._validation_batch_done} OHLCV dataset(s)"
            )

    def _set_dataset_validation_status(self, summary: object, status: str) -> None:
        self._validation_status_by_key[self._dataset_key(summary)] = status
        for row in range(self._dataset_table.rowCount()):
            item = self._dataset_table.item(row, 0)
            row_summary = None if item is None else item.data(Qt.ItemDataRole.UserRole)
            if row_summary is None or self._dataset_key(row_summary) != self._dataset_key(summary):
                continue
            status_item = self._dataset_table.item(row, 6)
            if status_item is not None:
                status_item.setText(status)
            self._apply_row_validation_style(row, status)
            break

    def _validation_status_for_report(self, report: object) -> str:
        return self._display_validation_status(self._text(report, "status"))

    def _display_validation_status(self, status: str) -> str:
        status = str(status or "").strip().lower()
        if status == "ok":
            return "OK"
        if status == "warning":
            return "Warning"
        if status == "error":
            return "Error"
        return "Unknown"

    def _apply_row_validation_style(self, row: int, status: str) -> None:
        background = QBrush()
        foreground = QBrush()
        if status == "OK":
            background = QBrush(QColor(232, 246, 239))
        elif status == "Warning":
            background = QBrush(QColor(255, 248, 214))
        elif status == "Error":
            background = QBrush(QColor(255, 232, 232))
            foreground = QBrush(QColor(122, 24, 24))

        for column in range(self._dataset_table.columnCount()):
            item = self._dataset_table.item(row, column)
            if item is None:
                continue
            item.setBackground(background)
            item.setForeground(foreground)

    def _dataset_key(self, summary: object) -> tuple[str, str, str, str]:
        return (
            self._text(summary, "exchange"),
            self._text(summary, "market_type"),
            self._text(summary, "symbol"),
            self._text(summary, "timeframe"),
        )

    def _set_all_dataset_checks(self, state: Qt.CheckState) -> None:
        for row in range(self._dataset_table.rowCount()):
            item = self._dataset_table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def _set_dataset_selection_buttons_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled) and not self._validation_running
        self._select_all_button.setEnabled(enabled)
        self._deselect_all_button.setEnabled(enabled)

    def _dataset_label(self, dataset: object) -> str:
        if dataset is None:
            return "-"
        return (
            f"{self._text(dataset, 'exchange')} / {self._text(dataset, 'market_type')} / "
            f"{self._text(dataset, 'symbol')} / {self._text(dataset, 'timeframe')}"
        )

    def _manifest_market(self, manifest: object) -> str:
        return (
            f"{self._text(manifest, 'market_exchange')} / {self._text(manifest, 'market_type')} / "
            f"{self._text(manifest, 'market_symbol')} / {self._text(manifest, 'market_timeframe')}"
        )

    def _text(self, obj: object, name: str) -> str:
        if obj is None:
            return ""
        value = getattr(obj, name, "")
        if value is None:
            return ""
        return str(value)

    def _yes_no(self, value: object) -> str:
        return "yes" if bool(value) else "no"
