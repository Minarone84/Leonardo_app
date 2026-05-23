"""Qt window for historical OHLCV dataset inspection and maintenance actions."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
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
    Inspector and explicit delete workflow for persisted OHLCV datasets.

    The window owns presentation and user interaction only. Dataset catalog
    inspection, validation, and deletion are requested through CoreBridge so
    persistence contracts remain in the data layer.
    """

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bridge = core_bridge
        self._datasets: tuple[object, ...] = ()
        self._selected_dataset: object | None = None
        self._pending: dict[str, Future[object]] = {}
        self._select_first_after_refresh = True

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
        self._rebuild_metadata_button = QPushButton("Rebuild Metadata...", self)
        self._delete_button = QPushButton("Delete Selected", self)
        self._validate_button.setEnabled(False)
        self._rebuild_metadata_button.setEnabled(False)
        self._delete_button.setEnabled(False)
        toolbar.addWidget(self._refresh_button)
        toolbar.addWidget(self._validate_button)
        toolbar.addWidget(self._rebuild_metadata_button)
        toolbar.addWidget(self._delete_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 5)

        dataset_group = QGroupBox("OHLCV Datasets", splitter)
        dataset_layout = QVBoxLayout(dataset_group)
        self._dataset_table = QTableWidget(0, 5, dataset_group)
        self._dataset_table.setHorizontalHeaderLabels(["Exchange", "Market", "Symbol", "Timeframe", "Storage"])
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
        self._validation.setPlainText("Run Analyze / Validate Selected to inspect the selected dataset.")
        validation_layout.addWidget(self._validation, 1)
        layout.addWidget(validation_group, 2)

        self._watch = QTimer(self)
        self._watch.setInterval(150)
        self._watch.timeout.connect(self._poll_pending)

        self._refresh_button.clicked.connect(self.refresh_datasets)
        self._validate_button.clicked.connect(self.validate_selected)
        self._rebuild_metadata_button.clicked.connect(self.rebuild_metadata_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._dataset_table.itemSelectionChanged.connect(self._on_selection_changed)

        self.refresh_datasets()

    def refresh_datasets(self) -> None:
        """Request the current read-only OHLCV dataset catalog."""
        self._request_dataset_list(select_first=True)

    def _request_dataset_list(self, *, select_first: bool) -> None:
        """Request the dataset catalog and control post-refresh selection."""
        self._select_first_after_refresh = bool(select_first)
        self._refresh_button.setEnabled(False)
        self._start_future("list", self._bridge.list_historical_ohlcv_datasets())
        self.statusBar().showMessage("Loading OHLCV dataset list...")

    def validate_selected(self) -> None:
        """Request validation for the currently selected dataset."""
        summary = self._selected_dataset
        if summary is None:
            self.statusBar().showMessage("Select an OHLCV dataset before validating")
            return
        self._set_selected_actions_enabled(False)
        self._validation.setPlainText("Validation running...")
        self._start_future("validate", self._bridge.validate_historical_ohlcv_dataset(**self._identity_kwargs(summary)))
        self.statusBar().showMessage("Validating selected OHLCV dataset...")

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
        self._set_selected_actions_enabled(summary is not None)
        self._validation.setPlainText("Run Analyze / Validate Selected to inspect the selected dataset.")
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
            elif name == "validate":
                self._validation.setPlainText(self._format_validation(result))
                self._set_selected_actions_enabled(self._selected_dataset is not None)
                self.statusBar().showMessage("Validation complete")
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
            self._details.setPlainText(f"Dataset list failed:\n{message}")
        elif name == "inspect":
            self._details.setPlainText(f"Dataset inspection failed:\n{message}")
        elif name == "validate":
            self._validation.setPlainText(f"Validation failed:\n{message}")
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
        self._refresh_button.setEnabled(True)
        select_first = self._select_first_after_refresh
        self._select_first_after_refresh = True

        self._dataset_table.blockSignals(True)
        self._dataset_table.setRowCount(0)
        for row, summary in enumerate(datasets):
            self._dataset_table.insertRow(row)
            values = [
                self._text(summary, "exchange"),
                self._text(summary, "market_type"),
                self._text(summary, "symbol"),
                self._text(summary, "timeframe"),
                self._text(summary, "storage_segment"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, summary)
                self._dataset_table.setItem(row, column, item)
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
        ]
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

    def _set_selected_actions_enabled(self, enabled: bool) -> None:
        self._validate_button.setEnabled(enabled)
        self._rebuild_metadata_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)

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
