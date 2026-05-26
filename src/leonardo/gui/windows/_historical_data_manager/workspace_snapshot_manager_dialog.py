from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshot,
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.chart.study_serialization import (
    deserialize_study_user_metadata_payload,
)


class WorkspaceSnapshotManagerDialog(QDialog):
    """Inspect and maintain saved Workspace Snapshot metadata.

    The dialog owns user interaction only. Workspace Snapshot persistence
    remains owned by HistoricalWorkspaceSnapshotStore. Embedded chart and study
    payloads are displayed for inspection; RS4 only edits top-level snapshot
    display name and description.
    """

    _SNAPSHOT_ID_ROLE = Qt.UserRole

    def __init__(
        self,
        *,
        store: HistoricalWorkspaceSnapshotStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._current_snapshot: HistoricalWorkspaceSnapshot | None = None

        self.setWindowTitle("Workspace Snapshot Manager")
        self.resize(1180, 720)

        self._snapshot_list = QListWidget(self)
        self._name_edit = QLineEdit(self)
        self._description_edit = QPlainTextEdit(self)
        self._detail_text = QPlainTextEdit(self)
        self._chart_table = QTableWidget(0, 5, self)
        self._study_table = QTableWidget(0, 7, self)
        self._save_button = QPushButton("Save Changes", self)
        self._delete_button = QPushButton("Delete Workspace Snapshot", self)
        self._refresh_button = QPushButton("Refresh", self)
        self._status_label = QLabel("", self)

        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        list_group = QGroupBox("Saved Workspace Snapshots", self)
        list_layout = QVBoxLayout(list_group)
        self._snapshot_list.setObjectName("workspaceSnapshotManagerList")
        self._snapshot_list.itemSelectionChanged.connect(
            self._on_snapshot_selection_changed
        )
        list_layout.addWidget(self._snapshot_list, 1)
        content.addWidget(list_group, 1)

        detail_group = QGroupBox("Selected Workspace Snapshot", self)
        detail_layout = QVBoxLayout(detail_group)
        form = QGridLayout()
        form.addWidget(QLabel("Display name", detail_group), 0, 0)
        self._name_edit.setObjectName("workspaceSnapshotManagerNameEdit")
        form.addWidget(self._name_edit, 0, 1)
        form.addWidget(QLabel("Description", detail_group), 1, 0)
        self._description_edit.setObjectName("workspaceSnapshotManagerDescriptionEdit")
        self._description_edit.setFixedHeight(72)
        form.addWidget(self._description_edit, 1, 1)
        detail_layout.addLayout(form)

        self._detail_text.setObjectName("workspaceSnapshotManagerDetailText")
        self._detail_text.setReadOnly(True)
        self._detail_text.setFixedHeight(120)
        detail_layout.addWidget(self._detail_text)

        self._configure_chart_table()
        detail_layout.addWidget(self._chart_table, 1)

        self._configure_study_table()
        detail_layout.addWidget(self._study_table, 1)

        note = QLabel(
            "Embedded study metadata is shown for inspection. Edit Study "
            "Environment metadata from the Study Environment Manager or live "
            "chart before saving a new/update snapshot.",
            detail_group,
        )
        note.setWordWrap(True)
        note.setObjectName("workspaceSnapshotManagerReadOnlyNote")
        detail_layout.addWidget(note)

        content.addWidget(detail_group, 3)

        button_row = QHBoxLayout()
        button_row.addWidget(self._status_label, 1)
        self._refresh_button.clicked.connect(lambda *_: self._reload())
        button_row.addWidget(self._refresh_button)
        self._save_button.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self._save_button)
        self._delete_button.clicked.connect(self._on_delete_clicked)
        button_row.addWidget(self._delete_button)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        root.addLayout(button_row)

    def _configure_chart_table(self) -> None:
        table = self._chart_table
        table.setObjectName("workspaceSnapshotManagerChartTable")
        table.setHorizontalHeaderLabels(
            ["#", "Position", "Dataset", "Timeframe", "Studies"]
        )
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.itemSelectionChanged.connect(self._on_chart_selection_changed)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

    def _configure_study_table(self) -> None:
        table = self._study_table
        table.setObjectName("workspaceSnapshotManagerStudyTable")
        table.setHorizontalHeaderLabels(
            [
                "#",
                "Display Name",
                "Tool",
                "Params",
                "Important",
                "Dataset Role",
                "Description",
            ]
        )
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)

    def _reload(self, *, selected_snapshot_id: str | None = None) -> None:
        selected_id = str(selected_snapshot_id or self._selected_snapshot_id() or "")
        summaries = self._store.list_summaries()

        self._snapshot_list.blockSignals(True)
        try:
            self._snapshot_list.clear()
            for summary in summaries:
                item = QListWidgetItem(summary.display_name)
                item.setToolTip(
                    f"{summary.snapshot_id}\n"
                    f"{summary.description or '(no description)'}"
                )
                item.setData(self._SNAPSHOT_ID_ROLE, summary.snapshot_id)
                self._snapshot_list.addItem(item)
            if summaries:
                target_row = 0
                for row_index in range(self._snapshot_list.count()):
                    item = self._snapshot_list.item(row_index)
                    if item.data(self._SNAPSHOT_ID_ROLE) == selected_id:
                        target_row = row_index
                        break
                self._snapshot_list.setCurrentRow(target_row)
        finally:
            self._snapshot_list.blockSignals(False)

        if summaries:
            self._set_status(f"Loaded {len(summaries)} saved Workspace Snapshot(s).")
        else:
            self._set_status("No saved Workspace Snapshots were found.")
        self._on_snapshot_selection_changed()

    def _on_snapshot_selection_changed(self) -> None:
        snapshot_id = self._selected_snapshot_id()
        if not snapshot_id:
            self._set_current_snapshot(None)
            return
        try:
            snapshot = self._store.load_snapshot(snapshot_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Workspace Snapshot Manager",
                f"Could not load Workspace Snapshot: {exc!r}",
            )
            self._set_current_snapshot(None)
            return
        self._set_current_snapshot(snapshot)

    def _set_current_snapshot(self, snapshot: HistoricalWorkspaceSnapshot | None) -> None:
        self._current_snapshot = snapshot
        enabled = snapshot is not None
        self._name_edit.setEnabled(enabled)
        self._description_edit.setEnabled(enabled)
        self._save_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)

        if snapshot is None:
            self._name_edit.clear()
            self._description_edit.clear()
            self._detail_text.clear()
            self._chart_table.setRowCount(0)
            self._study_table.setRowCount(0)
            return

        self._name_edit.setText(snapshot.display_name)
        self._description_edit.setPlainText(snapshot.description)
        self._detail_text.setPlainText(self._snapshot_detail_text(snapshot))
        self._populate_charts(snapshot)
        if snapshot.charts:
            self._chart_table.selectRow(0)
        self._on_chart_selection_changed()

    def _populate_charts(self, snapshot: HistoricalWorkspaceSnapshot) -> None:
        table = self._chart_table
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for row_index, chart in enumerate(snapshot.charts):
                table.insertRow(row_index)
                dataset = _mapping_or_empty(chart.get("dataset"))
                values = [
                    str(row_index + 1),
                    str(chart.get("position", "") or ""),
                    _dataset_label(dataset),
                    str(dataset.get("timeframe", "") or ""),
                    str(len(_studies_from_chart(chart))),
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column in {0, 1, 4}:
                        item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row_index, column, item)
        finally:
            table.blockSignals(False)

    def _on_chart_selection_changed(self) -> None:
        snapshot = self._current_snapshot
        row = self._selected_chart_row()
        if snapshot is None or row < 0 or row >= len(snapshot.charts):
            self._study_table.setRowCount(0)
            return
        self._populate_studies(_studies_from_chart(snapshot.charts[row]))

    def _populate_studies(self, studies: list[dict[str, Any]]) -> None:
        table = self._study_table
        table.setRowCount(0)
        for row_index, study in enumerate(studies):
            metadata = _metadata_from_study(study)
            values = [
                str(row_index + 1),
                _study_display_name(study),
                _study_tool_text(study),
                _params_summary(study),
                "yes" if metadata.important else "no",
                metadata.dataset_role,
                metadata.description,
            ]
            table.insertRow(row_index)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)

    def _on_save_clicked(self) -> None:
        snapshot = self._current_snapshot
        if snapshot is None:
            return
        display_name = self._name_edit.text().strip()
        if not display_name:
            QMessageBox.information(
                self,
                "Workspace Snapshot Manager",
                "Display name is required.",
            )
            return

        try:
            updated = self._store.update_snapshot(
                snapshot_id=snapshot.snapshot_id,
                display_name=display_name,
                description=self._description_edit.toPlainText(),
                workspace=snapshot.workspace,
                charts=snapshot.charts,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Workspace Snapshot Manager",
                f"Could not update Workspace Snapshot: {exc!r}",
            )
            return

        self._set_status(f"Updated Workspace Snapshot: {updated.display_name}")
        self._reload(selected_snapshot_id=updated.snapshot_id)

    def _on_delete_clicked(self) -> None:
        snapshot = self._current_snapshot
        if snapshot is None:
            return
        if not self._confirm_delete_snapshot(snapshot):
            self._set_status("Workspace Snapshot delete cancelled.")
            return
        try:
            deleted = self._store.delete_snapshot(snapshot.snapshot_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Workspace Snapshot Manager",
                f"Could not delete Workspace Snapshot: {exc!r}",
            )
            return
        if not deleted:
            QMessageBox.warning(
                self,
                "Workspace Snapshot Manager",
                "The selected Workspace Snapshot file was not found.",
            )
        self._reload()

    def _confirm_delete_snapshot(self, snapshot: HistoricalWorkspaceSnapshot) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Delete Workspace Snapshot")
        dialog.setText(f'Delete Workspace Snapshot "{snapshot.display_name}"?')
        dialog.setInformativeText(
            "This removes only the saved Workspace Snapshot. "
            "Assigned notebooks, Study Environments, recipes, artifacts, and databases are not deleted.\n\n"
            "This action cannot be undone."
        )
        delete_button = dialog.addButton("Delete", QMessageBox.DestructiveRole)
        dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _selected_snapshot_id(self) -> str:
        item = self._snapshot_list.currentItem()
        if item is None:
            return ""
        return str(item.data(self._SNAPSHOT_ID_ROLE) or "").strip()

    def _selected_chart_row(self) -> int:
        rows = self._chart_table.selectionModel().selectedRows()
        if not rows:
            return -1
        return rows[0].row()

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def _snapshot_detail_text(self, snapshot: HistoricalWorkspaceSnapshot) -> str:
        notebook_ref = snapshot.notebook_ref
        if isinstance(notebook_ref, Mapping):
            notebook_id = str(notebook_ref.get("notebook_id", "") or "").strip()
            notebook_name = str(notebook_ref.get("display_name", "") or "").strip()
            notebook_text = (
                f"{notebook_name} ({notebook_id})" if notebook_name else notebook_id
            )
        else:
            notebook_text = "(none)"
        study_count = sum(len(_studies_from_chart(chart)) for chart in snapshot.charts)
        return "\n".join(
            [
                f"ID: {snapshot.snapshot_id}",
                f"Created: {_format_timestamp(snapshot.created_at_ms)}",
                f"Updated: {_format_timestamp(snapshot.updated_at_ms)}",
                f"Charts: {len(snapshot.charts)}",
                f"Studies: {study_count}",
                f"Notebook: {notebook_text}",
                f"Content hash: {snapshot.content_hash}",
            ]
        )


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _studies_from_chart(chart: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_studies = chart.get("studies", []) or []
    if not isinstance(raw_studies, (list, tuple)):
        return []
    return [dict(study) for study in raw_studies if isinstance(study, Mapping)]


def _metadata_from_study(study: Mapping[str, Any]):
    raw = study.get("user_metadata")
    payload = raw if isinstance(raw, Mapping) else {}
    return deserialize_study_user_metadata_payload(payload)


def _study_display_name(study: Mapping[str, Any]) -> str:
    return str(study.get("display_name", "") or study.get("tool_key", "") or "Study")


def _study_tool_text(study: Mapping[str, Any]) -> str:
    family = str(study.get("family", "") or "").strip()
    tool_key = str(study.get("tool_key", "") or "").strip()
    return f"{family}/{tool_key}" if family and tool_key else family or tool_key


def _params_summary(study: Mapping[str, Any]) -> str:
    params = study.get("params", {})
    if not isinstance(params, Mapping) or not params:
        return "(none)"
    pairs = [f"{key}={params[key]!r}" for key in sorted(params.keys(), key=str)]
    return ", ".join(pairs)


def _dataset_label(dataset: Mapping[str, Any]) -> str:
    return " / ".join(
        part
        for part in (
            str(dataset.get("exchange", "") or ""),
            str(dataset.get("market_type", "") or ""),
            str(dataset.get("symbol", "") or ""),
        )
        if part
    )


def _format_timestamp(timestamp_ms: int) -> str:
    if int(timestamp_ms) <= 0:
        return ""
    timestamp = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["WorkspaceSnapshotManagerDialog"]
