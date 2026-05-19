from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.saved_artifact_columns import (
    NON_SELECTABLE_COLUMNS,
    SavedArtifactColumn,
    load_saved_artifact_columns,
)


class SavedArtifactSelectorWidget(QGroupBox):
    """Read-only selector for saved analysis-usable derived artifact columns."""

    selection_changed = Signal(object)  # list[SavedArtifactColumn]
    preview_requested = Signal(object, str)  # Path, title
    exit_selection_requested = Signal()

    NON_SELECTABLE_COLUMNS = NON_SELECTABLE_COLUMNS

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Saved Indicators / Oscillators / Constructs", parent)
        self._historical_root = Path(historical_root)
        self._market: Optional[MarketId] = None
        self._columns: list[SavedArtifactColumn] = []
        self._build_selection_mode = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        self._hint_label = QLabel(
            "Select a dataset to list saved artifacts. Check a column to select it; "
            "highlighting only focuses a row. Preview is available only when exactly one column is checked.",
            self,
        )
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

        self._preview_button = QPushButton("Preview Selected Artifact", self)
        self._preview_button.setToolTip("Preview is enabled only when exactly one artifact column is checked.")
        self._preview_button.setEnabled(False)
        self._preview_button.clicked.connect(self._preview_selected_artifact)

        self._exit_selection_button = QPushButton("Exit Selection", self)
        self._exit_selection_button.setVisible(False)
        self._exit_selection_button.clicked.connect(self._confirm_exit_selection)

        self._refresh_button = QPushButton("Refresh Saved Artifacts", self)
        self._refresh_button.clicked.connect(self.refresh)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self._preview_button)
        button_row.addWidget(self._exit_selection_button)
        button_row.addWidget(self._refresh_button)
        button_row.addStretch(1)
        root.addLayout(button_row, 0)

        self._list = QListWidget(self)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.currentItemChanged.connect(lambda _current, _previous: self._refresh_preview_button())
        root.addWidget(self._list, 1)

    def set_market(self, market: Optional[MarketId]) -> None:
        self._market = market
        self.refresh()

    def set_build_selection_mode(self, enabled: bool) -> None:
        self._build_selection_mode = bool(enabled)
        self._exit_selection_button.setVisible(self._build_selection_mode)
        self._refresh_hint_label()

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(Qt.Unchecked)
        self._list.blockSignals(False)
        self._emit_selection_changed()

    def selected_columns(self) -> list[SavedArtifactColumn]:
        selected: list[SavedArtifactColumn] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() != Qt.Checked:
                continue
            data = item.data(Qt.UserRole)
            if isinstance(data, SavedArtifactColumn):
                selected.append(data)
        return selected

    def refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        self._preview_button.setEnabled(False)
        self._columns = []

        if self._market is None:
            self._refresh_hint_label()
            self._list.blockSignals(False)
            self._emit_selection_changed()
            return

        self._columns = load_saved_artifact_columns(
            historical_root=self._historical_root,
            market=self._market,
        )

        if not self._columns:
            self._refresh_hint_label()
            self._list.blockSignals(False)
            self._emit_selection_changed()
            return

        self._refresh_hint_label()
        for column in self._columns:
            label = (
                f"{column.family[:-1].capitalize()} · {column.tool_title} · "
                f"{column.instance_key}  ->  {column.column_name}"
            )
            item = QListWidgetItem(label, self._list)
            item.setToolTip(str(column.path))
            item.setData(Qt.UserRole, column)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)

        self._list.blockSignals(False)
        self._emit_selection_changed()
        self._refresh_preview_button()

    def _refresh_hint_label(self) -> None:
        checked_count = len(self.selected_columns())
        checked_text = f" Checked columns: {checked_count}." if self._columns else ""
        if self._market is None:
            self._hint_label.setText(
                "Select a dataset to list saved artifacts. Check a column to select it; "
                "highlighting only focuses a row. Preview is available only when exactly one column is checked."
            )
            return
        if not self._columns:
            self._hint_label.setText("No saved indicator, oscillator, or construct columns found for this dataset.")
            return
        if self._build_selection_mode:
            self._hint_label.setText(
                f"Build database selection is active. Found {len(self._columns)} saved artifact column(s)."
                f"{checked_text} Check columns to use, then press Build selected artifacts in Database Builder. "
                "Highlighting only focuses a row and does not select it."
            )
            return
        self._hint_label.setText(
            f"Found {len(self._columns)} saved artifact column(s).{checked_text} "
            "Check columns to select them for a future analysis database. "
            "Highlighting only focuses a row and does not select it. "
            "Preview is available only when exactly one column is checked."
        )

    def _confirm_exit_selection(self) -> None:
        answer = QMessageBox.question(
            self,
            "Exit Selection",
            "This will end the build database process, do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.exit_selection_requested.emit()

    def _checked_columns(self) -> list[SavedArtifactColumn]:
        return self.selected_columns()

    def _single_checked_column(self) -> Optional[SavedArtifactColumn]:
        checked = self._checked_columns()
        if len(checked) != 1:
            return None
        return checked[0]

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._emit_selection_changed()
        self._refresh_preview_button()
        self._refresh_hint_label()

    def _refresh_preview_button(self) -> None:
        self._preview_button.setEnabled(self._single_checked_column() is not None)

    def _preview_selected_artifact(self) -> None:
        column = self._single_checked_column()
        if column is None:
            QMessageBox.warning(
                self,
                "Preview Selected Artifact",
                "Check exactly one artifact column before previewing it. Highlighting alone does not select an artifact.",
            )
            self._refresh_preview_button()
            return
        title = f"{column.family[:-1].capitalize()} · {column.tool_title} · {column.instance_key}"
        self.preview_requested.emit(Path(column.path), title)

    def _emit_selection_changed(self) -> None:
        self.selection_changed.emit(self.selected_columns())
