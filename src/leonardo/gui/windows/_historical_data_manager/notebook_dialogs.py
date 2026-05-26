from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.notebook_store import HistoricalNotebook


class SaveNotebookDialog(QDialog):
    """
    Collect notebook save intent and user-facing notebook metadata.

    The dialog is presentation-only. It does not own notebook persistence,
    inspect workspace state, or write notebook JSON. Callers provide any
    existing notebooks that may be updated and use the accepted dialog result
    to call the appropriate store-owned save or update method.
    """

    def __init__(
        self,
        *,
        existing_notebooks: Sequence[HistoricalNotebook] = (),
        current_notebook_id: str | None = None,
        display_name: str = "",
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._existing_notebooks = list(existing_notebooks)
        self._existing_notebooks_by_id = {
            notebook.notebook_id: notebook for notebook in self._existing_notebooks
        }
        self._current_notebook_id = str(current_notebook_id or "").strip()

        self.setWindowTitle("Save Notebook")
        self.resize(560, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form_group = QGroupBox("Notebook Details", self)
        form = QFormLayout(form_group)
        form.setContentsMargins(10, 14, 10, 10)
        form.setSpacing(8)

        mode_row = QWidget(form_group)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)

        self._save_new_radio = QRadioButton("Save as new Notebook", mode_row)
        self._update_existing_radio = QRadioButton("Update existing Notebook", mode_row)
        self._update_existing_radio.setEnabled(bool(self._existing_notebooks))
        self._save_new_radio.toggled.connect(self._on_save_mode_changed)
        self._update_existing_radio.toggled.connect(self._on_save_mode_changed)
        mode_layout.addWidget(self._save_new_radio)
        mode_layout.addWidget(self._update_existing_radio)
        mode_layout.addStretch(1)
        form.addRow("Mode", mode_row)

        self._existing_notebook_combo = QComboBox(form_group)
        current_index = -1
        for index, notebook in enumerate(self._existing_notebooks):
            self._existing_notebook_combo.addItem(
                notebook.display_name,
                notebook.notebook_id,
            )
            if notebook.notebook_id == self._current_notebook_id:
                current_index = index
        if current_index >= 0:
            self._existing_notebook_combo.setCurrentIndex(current_index)
        self._existing_notebook_combo.setEnabled(False)
        self._existing_notebook_combo.currentIndexChanged.connect(
            self._on_existing_notebook_changed
        )
        form.addRow("Existing notebook", self._existing_notebook_combo)

        self._name_edit = QLineEdit(form_group)
        self._name_edit.setPlaceholderText("Notebook name")
        self._name_edit.setText(str(display_name or "").strip())
        self._name_edit.textChanged.connect(self._refresh_save_enabled)
        form.addRow("Name", self._name_edit)

        self._description_edit = QTextEdit(form_group)
        self._description_edit.setPlaceholderText("Description")
        self._description_edit.setFixedHeight(90)
        self._description_edit.setPlainText(str(description or ""))
        form.addRow("Description", self._description_edit)

        root.addWidget(form_group)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        if current_index >= 0:
            self._update_existing_radio.setChecked(True)
            self._name_edit.setText(str(display_name or "").strip())
            self._description_edit.setPlainText(str(description or ""))
        else:
            self._save_new_radio.setChecked(True)
        self._refresh_save_enabled()

    def display_name(self) -> str:
        """Return the user-facing notebook name."""
        return self._name_edit.text().strip()

    def description(self) -> str:
        """Return the optional notebook description."""
        return self._description_edit.toPlainText()

    def save_mode(self) -> str:
        """Return whether the dialog should save a new notebook or update one."""
        if self._update_existing_radio.isChecked():
            return "update"
        return "new"

    def selected_existing_notebook_id(self) -> str:
        """Return the selected notebook identity for update mode."""
        data = self._existing_notebook_combo.currentData()
        return str(data or "").strip()

    def _selected_existing_notebook(self) -> HistoricalNotebook | None:
        notebook_id = self.selected_existing_notebook_id()
        if not notebook_id:
            return None
        return self._existing_notebooks_by_id.get(notebook_id)

    def _on_save_mode_changed(self, *_args: object) -> None:
        is_update = self.save_mode() == "update"
        self._existing_notebook_combo.setEnabled(
            is_update and self._existing_notebook_combo.count() > 0
        )
        if is_update:
            self._preload_existing_notebook_details()
        self._refresh_save_enabled()

    def _on_existing_notebook_changed(self, *_args: object) -> None:
        if self.save_mode() == "update":
            self._preload_existing_notebook_details()
        self._refresh_save_enabled()

    def _preload_existing_notebook_details(self) -> None:
        notebook = self._selected_existing_notebook()
        if notebook is None:
            return
        self._name_edit.setText(notebook.display_name)
        self._description_edit.setPlainText(notebook.description)

    def _refresh_save_enabled(self, *_args: object) -> None:
        button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if button is None:
            return
        has_name = bool(self.display_name())
        has_update_target = bool(self.selected_existing_notebook_id())
        button.setEnabled(
            has_name and (self.save_mode() != "update" or has_update_target)
        )


__all__ = ["SaveNotebookDialog"]
