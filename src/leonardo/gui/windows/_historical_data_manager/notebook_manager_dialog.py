from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.notebook_store import (
    HistoricalNotebookStore,
    HistoricalNotebookSummary,
)
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
    HistoricalWorkspaceSnapshotSummary,
)


class HistoricalNotebookManagerDialog(QDialog):
    """Manage saved notebooks and workspace snapshot notebook references.

    The dialog owns the Notebook Manager user interaction only. Notebook content
    remains persisted by HistoricalNotebookStore, while assignment state remains
    persisted as workspace snapshot ``notebook_ref`` values through
    HistoricalWorkspaceSnapshotStore. Assignment lists displayed by this dialog
    are derived from snapshot summaries and are not written into notebook files.
    """

    _NOTEBOOK_ID_ROLE = Qt.UserRole

    def __init__(
        self,
        *,
        notebook_store: HistoricalNotebookStore,
        workspace_snapshot_store: HistoricalWorkspaceSnapshotStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._notebook_store = notebook_store
        self._workspace_snapshot_store = workspace_snapshot_store
        self._selected_open_notebook_id = ""

        self.setWindowTitle("Notebook Manager")
        self.resize(980, 560)

        self._table: QTableWidget | None = None
        self._open_button: QPushButton | None = None
        self._assign_button: QPushButton | None = None
        self._unassign_button: QPushButton | None = None
        self._status_label: QLabel | None = None

        self._build_ui()
        self._reload()

    def selected_open_notebook_id(self) -> str:
        """Return the notebook selected for opening after dialog acceptance."""
        return self._selected_open_notebook_id

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        table = QTableWidget(0, 5, self)
        table.setObjectName("historicalNotebookManagerTable")
        table.setHorizontalHeaderLabels(
            [
                "Notebook",
                "Description",
                "Last Saved",
                "Assignment Count",
                "Assigned Workspace Snapshots",
            ]
        )
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.itemSelectionChanged.connect(self._on_selection_changed)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(table, 1)
        self._table = table

        status_label = QLabel("Notebook assignments are derived from workspace snapshots.", self)
        status_label.setObjectName("historicalNotebookManagerStatusLabel")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)
        self._status_label = status_label

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        open_button = QPushButton("Open", self)
        open_button.setObjectName("historicalNotebookManagerOpenButton")
        open_button.clicked.connect(self._on_open_clicked)
        button_row.addWidget(open_button)
        self._open_button = open_button

        assign_button = QPushButton("Assign...", self)
        assign_button.setObjectName("historicalNotebookManagerAssignButton")
        assign_button.clicked.connect(self._on_assign_clicked)
        button_row.addWidget(assign_button)
        self._assign_button = assign_button

        unassign_button = QPushButton("Unassign...", self)
        unassign_button.setObjectName("historicalNotebookManagerUnassignButton")
        unassign_button.clicked.connect(self._on_unassign_clicked)
        button_row.addWidget(unassign_button)
        self._unassign_button = unassign_button

        close_button = QPushButton("Close", self)
        close_button.setObjectName("historicalNotebookManagerCloseButton")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)
        self._on_selection_changed()

    def _reload(self, *, selected_notebook_id: str | None = None) -> None:
        table = self._table
        if table is None:
            return

        selected_id = str(selected_notebook_id or self._selected_notebook_id() or "")
        summaries = self._notebook_store.list_summaries()
        assignments = self._assignment_map()

        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for row_index, summary in enumerate(summaries):
                assigned_snapshots = assignments.get(summary.notebook_id, [])
                table.insertRow(row_index)
                self._set_table_item(row_index, 0, summary.display_name, summary.notebook_id)
                self._set_table_item(row_index, 1, summary.description, summary.notebook_id)
                self._set_table_item(
                    row_index,
                    2,
                    self._format_timestamp(summary.updated_at_ms),
                    summary.notebook_id,
                )
                count_item = self._set_table_item(
                    row_index,
                    3,
                    str(len(assigned_snapshots)),
                    summary.notebook_id,
                )
                count_item.setTextAlignment(Qt.AlignCenter)
                self._set_table_item(
                    row_index,
                    4,
                    self._assigned_snapshot_names(assigned_snapshots),
                    summary.notebook_id,
                )

            if summaries:
                target_row = 0
                if selected_id:
                    for row_index in range(table.rowCount()):
                        if self._notebook_id_for_row(row_index) == selected_id:
                            target_row = row_index
                            break
                table.selectRow(target_row)
        finally:
            table.blockSignals(False)

        if summaries:
            self._set_status(f"Loaded {len(summaries)} saved notebook(s).")
        else:
            self._set_status("No saved notebooks were found.")
        self._on_selection_changed()

    def _set_table_item(
        self,
        row: int,
        column: int,
        text: str,
        notebook_id: str,
    ) -> QTableWidgetItem:
        table = self._require_table()
        item = QTableWidgetItem(text)
        item.setData(self._NOTEBOOK_ID_ROLE, notebook_id)
        table.setItem(row, column, item)
        return item

    def _on_selection_changed(self) -> None:
        has_selection = bool(self._selected_notebook_id())
        for button in (self._open_button, self._assign_button, self._unassign_button):
            if button is not None:
                button.setEnabled(has_selection)

    def _on_open_clicked(self) -> None:
        notebook_id = self._selected_notebook_id()
        if not notebook_id:
            return
        self._selected_open_notebook_id = notebook_id
        self.accept()

    def _on_assign_clicked(self) -> None:
        summary = self._selected_notebook_summary()
        if summary is None:
            return

        snapshot_summaries = self._workspace_snapshot_store.list_summaries()
        if not snapshot_summaries:
            QMessageBox.information(
                self,
                "Assign Notebook",
                "No saved workspace snapshots were found.",
            )
            return

        labels = [self._snapshot_assignment_label(item) for item in snapshot_summaries]
        selected, accepted = QInputDialog.getItem(
            self,
            "Assign Notebook",
            "Workspace snapshot:",
            labels,
            0,
            False,
        )
        if not accepted:
            self._set_status("Notebook assignment cancelled.")
            return

        target_summary = snapshot_summaries[labels.index(selected)]
        if self._snapshot_references_notebook(target_summary, summary.notebook_id):
            self._set_status(
                f"Notebook '{summary.display_name}' is already assigned to "
                f"'{target_summary.display_name}'."
            )
            return

        existing_assignments = self._assignment_map().get(summary.notebook_id, [])
        if existing_assignments:
            assigned_names = self._assigned_snapshot_names(existing_assignments)
            answer = QMessageBox.question(
                self,
                "Assign Notebook",
                "This notebook is already assigned to: "
                f"{assigned_names}.\n\nLink the same notebook to another workspace snapshot?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._set_status("Notebook assignment cancelled.")
                return

        target_ref = target_summary.notebook_ref
        if isinstance(target_ref, Mapping):
            target_notebook_id = str(target_ref.get("notebook_id", "") or "").strip()
            if target_notebook_id and target_notebook_id != summary.notebook_id:
                answer = QMessageBox.question(
                    self,
                    "Assign Notebook",
                    f"Workspace snapshot '{target_summary.display_name}' already "
                    "references another notebook. Replace that reference?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    self._set_status("Notebook assignment cancelled.")
                    return

        try:
            snapshot = self._workspace_snapshot_store.load_snapshot(
                target_summary.snapshot_id
            )
            notebook_ref = {
                "notebook_id": summary.notebook_id,
                "display_name": summary.display_name,
            }
            updated = replace(
                snapshot,
                notebook_ref=notebook_ref,
                updated_at_ms=int(time.time() * 1000),
            )
            self._workspace_snapshot_store.save_snapshot(updated, overwrite=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Assign Notebook",
                f"Could not assign notebook: {exc!r}",
            )
            return

        self._reload(selected_notebook_id=summary.notebook_id)
        self._set_status(
            f"Assigned notebook '{summary.display_name}' to "
            f"'{target_summary.display_name}'."
        )

    def _on_unassign_clicked(self) -> None:
        summary = self._selected_notebook_summary()
        if summary is None:
            return

        assignments = self._assignment_map().get(summary.notebook_id, [])
        if not assignments:
            QMessageBox.information(
                self,
                "Unassign Notebook",
                "The selected notebook is not assigned to any workspace snapshot.",
            )
            return

        if len(assignments) == 1:
            target_summary = assignments[0]
        else:
            labels = [self._snapshot_assignment_label(item) for item in assignments]
            selected, accepted = QInputDialog.getItem(
                self,
                "Unassign Notebook",
                "Workspace snapshot:",
                labels,
                0,
                False,
            )
            if not accepted:
                self._set_status("Notebook unassignment cancelled.")
                return
            target_summary = assignments[labels.index(selected)]

        answer = QMessageBox.question(
            self,
            "Unassign Notebook",
            f"Remove notebook '{summary.display_name}' from workspace snapshot "
            f"'{target_summary.display_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._set_status("Notebook unassignment cancelled.")
            return

        try:
            snapshot = self._workspace_snapshot_store.load_snapshot(
                target_summary.snapshot_id
            )
            updated = replace(
                snapshot,
                notebook_ref=None,
                updated_at_ms=int(time.time() * 1000),
            )
            self._workspace_snapshot_store.save_snapshot(updated, overwrite=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unassign Notebook",
                f"Could not unassign notebook: {exc!r}",
            )
            return

        self._reload(selected_notebook_id=summary.notebook_id)
        self._set_status(
            f"Unassigned notebook '{summary.display_name}' from "
            f"'{target_summary.display_name}'."
        )

    def _selected_notebook_summary(self) -> HistoricalNotebookSummary | None:
        notebook_id = self._selected_notebook_id()
        if not notebook_id:
            return None
        for summary in self._notebook_store.list_summaries():
            if summary.notebook_id == notebook_id:
                return summary
        return None

    def _selected_notebook_id(self) -> str:
        table = self._table
        if table is None:
            return ""
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return ""
        return self._notebook_id_for_row(selected_rows[0].row())

    def _notebook_id_for_row(self, row: int) -> str:
        table = self._table
        if table is None:
            return ""
        item = table.item(row, 0)
        if item is None:
            return ""
        return str(item.data(self._NOTEBOOK_ID_ROLE) or "").strip()

    def _assignment_map(self) -> dict[str, list[HistoricalWorkspaceSnapshotSummary]]:
        assignments: dict[str, list[HistoricalWorkspaceSnapshotSummary]] = {}
        for summary in self._workspace_snapshot_store.list_summaries():
            notebook_ref = summary.notebook_ref
            if not isinstance(notebook_ref, Mapping):
                continue
            notebook_id = str(notebook_ref.get("notebook_id", "") or "").strip()
            if not notebook_id:
                continue
            assignments.setdefault(notebook_id, []).append(summary)
        return assignments

    def _snapshot_assignment_label(
        self,
        summary: HistoricalWorkspaceSnapshotSummary,
    ) -> str:
        notebook_name = ""
        notebook_ref = summary.notebook_ref
        if isinstance(notebook_ref, Mapping):
            notebook_name = str(notebook_ref.get("display_name", "") or "").strip()
        suffix = f" - assigned to {notebook_name}" if notebook_name else " - unassigned"
        return f"{summary.display_name} ({summary.chart_count} chart(s)){suffix}"

    def _snapshot_references_notebook(
        self,
        summary: HistoricalWorkspaceSnapshotSummary,
        notebook_id: str,
    ) -> bool:
        notebook_ref = summary.notebook_ref
        if not isinstance(notebook_ref, Mapping):
            return False
        return str(notebook_ref.get("notebook_id", "") or "").strip() == notebook_id

    def _assigned_snapshot_names(
        self,
        assignments: list[HistoricalWorkspaceSnapshotSummary],
    ) -> str:
        names = [item.display_name for item in assignments]
        return ", ".join(names) if names else "Unassigned"

    def _set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(text)

    def _require_table(self) -> QTableWidget:
        if self._table is None:
            raise RuntimeError("Notebook Manager table is not initialized.")
        return self._table

    @staticmethod
    def _format_timestamp(timestamp_ms: int) -> str:
        if int(timestamp_ms) <= 0:
            return ""
        timestamp = datetime.fromtimestamp(
            int(timestamp_ms) / 1000,
            tz=timezone.utc,
        )
        return timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["HistoricalNotebookManagerDialog"]
