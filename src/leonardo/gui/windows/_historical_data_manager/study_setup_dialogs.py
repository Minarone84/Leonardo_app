from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.study_setup_store import ChartStudySetup
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PresetCompatibilityReport,
    format_compatibility_report,
    ready_report,
)


def _params_summary(params: Mapping[str, Any]) -> str:
    if not params:
        return "default"
    return ", ".join(f"{key}={params[key]}" for key in sorted(params.keys(), key=str))


def _study_recap_lines(studies: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for index, study in enumerate(studies, start=1):
        family = str(study.get("family", "") or "").strip() or "study"
        tool_key = str(study.get("tool_key", "") or "").strip() or "unknown"
        display_name = str(study.get("display_name", "") or "").strip() or tool_key
        pane_target = str(study.get("pane_target", "") or "").strip() or "none"
        params = study.get("params", {}) or {}
        params_text = _params_summary(params if isinstance(params, Mapping) else {})
        lines.append(
            f"{index}. {display_name}  |  {family}/{tool_key}  |  "
            f"pane={pane_target}  |  params: {params_text}"
        )
    return lines


def _dataset_text(data: Mapping[str, Any]) -> str:
    parts = [
        str(data.get("exchange", "") or "").strip(),
        str(data.get("market_type", "") or "").strip(),
        str(data.get("symbol", "") or "").strip(),
        str(data.get("timeframe", "") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or "Unknown dataset"


class SaveStudySetupDialog(QDialog):
    """Collect user metadata and source-chart choice for a study environment save."""

    def __init__(
        self,
        *,
        chart_options: Sequence[Mapping[str, Any]],
        existing_setups: Sequence[ChartStudySetup] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chart_options = [dict(option) for option in chart_options]
        self._existing_setups = list(existing_setups)
        self._existing_setups_by_id = {
            setup.setup_id: setup for setup in self._existing_setups
        }

        self.setWindowTitle("Save Study Environment")
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form_group = QGroupBox("Environment Details", self)
        form = QFormLayout(form_group)
        form.setContentsMargins(10, 14, 10, 10)
        form.setSpacing(8)

        mode_row = QWidget(form_group)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)

        self._save_new_radio = QRadioButton("Save as new Study Environment", mode_row)
        self._update_existing_radio = QRadioButton(
            "Update existing Study Environment",
            mode_row,
        )
        self._save_new_radio.setChecked(True)
        self._update_existing_radio.setEnabled(bool(self._existing_setups))
        self._save_new_radio.toggled.connect(self._on_save_mode_changed)
        self._update_existing_radio.toggled.connect(self._on_save_mode_changed)
        mode_layout.addWidget(self._save_new_radio)
        mode_layout.addWidget(self._update_existing_radio)
        mode_layout.addStretch(1)
        form.addRow("Mode", mode_row)

        self._existing_setup_combo = QComboBox(form_group)
        for setup in self._existing_setups:
            self._existing_setup_combo.addItem(setup.display_name, setup.setup_id)
        self._existing_setup_combo.setEnabled(False)
        self._existing_setup_combo.currentIndexChanged.connect(
            self._on_existing_setup_changed
        )
        form.addRow("Existing environment", self._existing_setup_combo)

        self._name_edit = QLineEdit(form_group)
        self._name_edit.setPlaceholderText("Study environment name")
        self._name_edit.textChanged.connect(self._refresh_save_enabled)
        form.addRow("Name", self._name_edit)

        self._description_edit = QTextEdit(form_group)
        self._description_edit.setPlaceholderText("Description")
        self._description_edit.setFixedHeight(90)
        form.addRow("Description", self._description_edit)

        self._source_chart_combo = QComboBox(form_group)
        for option in self._chart_options:
            label = str(option.get("label", "") or "").strip()
            position = int(option.get("position", 0) or 0)
            self._source_chart_combo.addItem(label or f"Chart {position}", position)
        self._source_chart_combo.currentIndexChanged.connect(self._refresh_recap)
        form.addRow("Source chart", self._source_chart_combo)

        root.addWidget(form_group)

        recap_group = QGroupBox("Study Recap", self)
        recap_layout = QVBoxLayout(recap_group)
        recap_layout.setContentsMargins(10, 14, 10, 10)
        recap_layout.setSpacing(8)

        self._recap_text = QPlainTextEdit(recap_group)
        self._recap_text.setReadOnly(True)
        recap_layout.addWidget(self._recap_text, 1)

        root.addWidget(recap_group, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._refresh_recap()
        self._refresh_save_enabled()

    def display_name(self) -> str:
        """Return the user-facing study environment name entered in the dialog."""
        return self._name_edit.text().strip()

    def description(self) -> str:
        """Return the optional study environment description entered in the dialog."""
        return self._description_edit.toPlainText().strip()

    def save_mode(self) -> str:
        """Return whether the dialog should save a new setup or update one."""
        if self._update_existing_radio.isChecked():
            return "update"
        return "new"

    def selected_existing_setup_id(self) -> str:
        """Return the selected setup identity for update mode."""
        data = self._existing_setup_combo.currentData()
        return str(data or "").strip()

    def selected_chart_position(self) -> int:
        """Return the one-based source chart position selected for saving."""
        data = self._source_chart_combo.currentData()
        return int(data) if isinstance(data, int) else 0

    def _selected_chart_option(self) -> dict[str, Any]:
        position = self.selected_chart_position()
        for option in self._chart_options:
            if int(option.get("position", 0) or 0) == position:
                return option
        return {}

    def _selected_existing_setup(self) -> ChartStudySetup | None:
        setup_id = self.selected_existing_setup_id()
        if not setup_id:
            return None
        return self._existing_setups_by_id.get(setup_id)

    def _on_save_mode_changed(self, *_args: object) -> None:
        is_update = self.save_mode() == "update"
        self._existing_setup_combo.setEnabled(
            is_update and self._existing_setup_combo.count() > 0
        )
        if is_update:
            self._preload_existing_setup_details()
        self._refresh_save_enabled()

    def _on_existing_setup_changed(self, *_args: object) -> None:
        if self.save_mode() == "update":
            self._preload_existing_setup_details()
        self._refresh_save_enabled()

    def _preload_existing_setup_details(self) -> None:
        setup = self._selected_existing_setup()
        if setup is None:
            return
        self._name_edit.setText(setup.display_name)
        self._description_edit.setPlainText(setup.description)

    def _refresh_recap(self) -> None:
        option = self._selected_chart_option()
        studies = list(option.get("studies", []) or [])
        lines = [
            f"Chart: {option.get('label', 'Unknown chart')}",
            f"Study count: {len(studies)}",
            "",
        ]
        lines.extend(_study_recap_lines(studies) or ["No studies on this chart."])
        self._recap_text.setPlainText("\n".join(lines))
        self._refresh_save_enabled()

    def _refresh_save_enabled(self) -> None:
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is None:
            return
        option = self._selected_chart_option()
        has_name = bool(self.display_name())
        has_studies = bool(option.get("study_count", 0))
        has_update_target = (
            self.save_mode() != "update" or bool(self.selected_existing_setup_id())
        )
        save_button.setEnabled(has_name and has_studies and has_update_target)


class LoadStudySetupDialog(QDialog):
    """Collect environment, target-chart, and append/replace choices for loading."""

    def __init__(
        self,
        *,
        setups: Sequence[ChartStudySetup],
        chart_options: Sequence[Mapping[str, Any]],
        compatibility_provider: Callable[[ChartStudySetup, int, str], PresetCompatibilityReport] | None = None,
        delete_setup: Callable[[str], bool] | None = None,
        setups_loader: Callable[[], Sequence[ChartStudySetup]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._setups_by_id = {setup.setup_id: setup for setup in setups}
        self._chart_options = [dict(option) for option in chart_options]
        self._compatibility_provider = compatibility_provider
        self._delete_setup = delete_setup
        self._setups_loader = setups_loader
        self._current_compatibility_report = ready_report()

        self.setWindowTitle("Load Study Environment")
        self.resize(900, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        list_group = QGroupBox("Saved Study Environments", self)
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(10, 14, 10, 10)
        list_layout.setSpacing(8)

        self._setup_list = QListWidget(list_group)
        self._setup_list.setWordWrap(True)
        self._setup_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._setup_list.currentItemChanged.connect(lambda *_: self._refresh_details())
        list_layout.addWidget(self._setup_list, 1)
        body.addWidget(list_group, 4)

        detail_group = QGroupBox("Environment Details", self)
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(10, 14, 10, 10)
        detail_layout.setSpacing(8)

        self._detail_text = QPlainTextEdit(detail_group)
        self._detail_text.setReadOnly(True)
        detail_layout.addWidget(self._detail_text, 1)

        target_form = QFormLayout()
        target_form.setSpacing(8)

        self._target_chart_combo = QComboBox(detail_group)
        for option in self._chart_options:
            label = str(option.get("label", "") or "").strip()
            position = int(option.get("position", 0) or 0)
            self._target_chart_combo.addItem(label or f"Chart {position}", position)
        self._target_chart_combo.currentIndexChanged.connect(lambda *_: self._refresh_details())
        target_form.addRow("Target chart", self._target_chart_combo)

        mode_row = QWidget(detail_group)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)

        self._append_radio = QRadioButton("Append to existing studies", mode_row)
        self._replace_radio = QRadioButton("Replace existing studies", mode_row)
        self._append_radio.setChecked(True)
        self._append_radio.toggled.connect(lambda *_: self._refresh_details())
        self._replace_radio.toggled.connect(lambda *_: self._refresh_details())
        mode_layout.addWidget(self._append_radio)
        mode_layout.addWidget(self._replace_radio)
        mode_layout.addStretch(1)
        target_form.addRow("Load mode", mode_row)

        detail_layout.addLayout(target_form)

        self._compatibility_text = QPlainTextEdit(detail_group)
        self._compatibility_text.setReadOnly(True)
        self._compatibility_text.setMaximumHeight(140)
        detail_layout.addWidget(self._compatibility_text)

        body.addWidget(detail_group, 5)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        load_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if load_button is not None:
            load_button.setText("Load")
        self._delete_button = self._buttons.addButton(
            "Delete",
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        self._delete_button.clicked.connect(self._on_delete_clicked)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._populate_setups(setups)
        self._refresh_details()

    def selected_setup_id(self) -> str:
        """Return the storage identity for the selected study environment."""
        item = self._setup_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def selected_target_chart_position(self) -> int:
        """Return the one-based target chart position selected for loading."""
        data = self._target_chart_combo.currentData()
        return int(data) if isinstance(data, int) else 0

    def load_mode(self) -> str:
        """Return the selected load behavior for the target chart."""
        if self._replace_radio.isChecked():
            return "replace"
        return "append"

    def compatibility_report(self) -> PresetCompatibilityReport:
        """Return the latest compatibility report displayed by the dialog."""
        return self._current_compatibility_report

    def _populate_setups(
        self,
        setups: Sequence[ChartStudySetup],
        *,
        select_first: bool = True,
    ) -> None:
        self._setups_by_id = {setup.setup_id: setup for setup in setups}
        self._setup_list.clear()
        for setup in setups:
            item = QListWidgetItem(
                f"{setup.display_name}\n{setup.description}\n"
                f"{len(setup.studies)} study/studies",
                self._setup_list,
            )
            item.setData(Qt.ItemDataRole.UserRole, setup.setup_id)
        if select_first and self._setup_list.count() > 0:
            self._setup_list.setCurrentRow(0)

    def _selected_setup(self) -> ChartStudySetup | None:
        setup_id = self.selected_setup_id()
        if not setup_id:
            return None
        return self._setups_by_id.get(setup_id)

    def _refresh_details(self) -> None:
        setup = self._selected_setup()
        load_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        delete_button = self._delete_button

        if setup is None:
            self._detail_text.setPlainText("Select a saved study environment.")
            self._current_compatibility_report = ready_report()
            self._compatibility_text.setPlainText("")
            if load_button is not None:
                load_button.setEnabled(False)
            delete_button.setEnabled(False)
            return

        lines = [
            f"Name: {setup.display_name}",
            f"Description: {setup.description}",
            f"Created: {setup.created_at_ms}",
            f"Updated: {setup.updated_at_ms}",
            f"Created from: {_dataset_text(setup.created_from)}",
            f"Study count: {len(setup.studies)}",
            "",
            "Studies:",
        ]
        lines.extend(_study_recap_lines(setup.studies) or ["No studies."])
        self._detail_text.setPlainText("\n".join(lines))

        self._current_compatibility_report = self._compatibility_report_for_setup(setup)
        self._compatibility_text.setPlainText(
            format_compatibility_report(self._current_compatibility_report)
        )
        if load_button is not None:
            load_button.setEnabled(
                self._target_chart_combo.count() > 0
                and self._current_compatibility_report.can_load
            )
        delete_button.setEnabled(self._delete_setup is not None)

    def _on_delete_clicked(self) -> None:
        setup = self._selected_setup()
        if setup is None:
            QMessageBox.information(
                self,
                "Delete Study Environment",
                "Select a saved study environment to delete.",
            )
            self._refresh_details()
            return
        if self._delete_setup is None:
            QMessageBox.warning(
                self,
                "Delete Study Environment",
                "Study environment deletion is not available in this context.",
            )
            self._refresh_details()
            return
        if not self._confirm_delete_setup(setup):
            return

        try:
            deleted = self._delete_setup(setup.setup_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Delete Study Environment",
                f"Could not delete study environment.\n{exc!r}",
            )
            return
        if not deleted:
            QMessageBox.warning(
                self,
                "Delete Study Environment",
                "Could not delete study environment.\nThe selected saved study environment was not found.",
            )
            self._reload_setups_after_delete(setup.setup_id)
            return

        self._reload_setups_after_delete(setup.setup_id)

    def _confirm_delete_setup(self, setup: ChartStudySetup) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Delete Study Environment")
        dialog.setText(f'Delete study environment "{setup.display_name}"?')
        dialog.setInformativeText("This action cannot be undone.")
        delete_button = dialog.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _reload_setups_after_delete(self, deleted_setup_id: str) -> None:
        if self._setups_loader is not None:
            setups = list(self._setups_loader())
        else:
            setups = [
                setup
                for setup_id, setup in self._setups_by_id.items()
                if setup_id != deleted_setup_id
            ]
        self._populate_setups(setups, select_first=False)
        self._setup_list.clearSelection()
        self._setup_list.setCurrentRow(-1)
        self._refresh_details()

    def _compatibility_report_for_setup(
        self,
        setup: ChartStudySetup,
    ) -> PresetCompatibilityReport:
        if self._compatibility_provider is None:
            return ready_report()
        return self._compatibility_provider(
            setup,
            self.selected_target_chart_position(),
            self.load_mode(),
        )
