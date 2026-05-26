from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from leonardo.data.chart_presets.study_setup_store import (
    ChartStudySetup,
    ChartStudySetupStore,
)
from leonardo.gui.chart.studies import (
    STUDY_DATASET_ROLE_VALUES,
    StudyUserMetadata,
    normalize_study_dataset_role,
)
from leonardo.gui.chart.study_serialization import (
    deserialize_study_user_metadata_payload,
    serialize_study_user_metadata,
)


class StudyEnvironmentManagerDialog(QDialog):
    """Inspect and maintain saved Study Environment metadata.

    The dialog owns user interaction only. Study Environment persistence remains
    owned by ChartStudySetupStore. Per-study edits are limited to serialized
    ``user_metadata`` values and do not alter computation, style, bindings, or
    recipe/export behavior.
    """

    _SETUP_ID_ROLE = Qt.UserRole

    def __init__(
        self,
        *,
        store: ChartStudySetupStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._current_setup: ChartStudySetup | None = None
        self._study_payloads: list[dict[str, Any]] = []
        self._metadata_editor_updating = False

        self.setWindowTitle("Study Environment Manager")
        self.resize(1120, 680)

        self._setup_list = QListWidget(self)
        self._name_edit = QLineEdit(self)
        self._description_edit = QPlainTextEdit(self)
        self._detail_text = QPlainTextEdit(self)
        self._study_table = QTableWidget(0, 7, self)
        self._important_check = QCheckBox("Important", self)
        self._role_combo = QComboBox(self)
        self._study_description_edit = QPlainTextEdit(self)
        self._save_button = QPushButton("Save Changes", self)
        self._delete_button = QPushButton("Delete Study Environment", self)
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

        list_group = QGroupBox("Saved Study Environments", self)
        list_layout = QVBoxLayout(list_group)
        self._setup_list.setObjectName("studyEnvironmentManagerList")
        self._setup_list.itemSelectionChanged.connect(self._on_setup_selection_changed)
        list_layout.addWidget(self._setup_list, 1)
        content.addWidget(list_group, 1)

        detail_group = QGroupBox("Selected Study Environment", self)
        detail_layout = QVBoxLayout(detail_group)
        form = QGridLayout()
        form.addWidget(QLabel("Display name", detail_group), 0, 0)
        self._name_edit.setObjectName("studyEnvironmentManagerNameEdit")
        form.addWidget(self._name_edit, 0, 1)
        form.addWidget(QLabel("Description", detail_group), 1, 0)
        self._description_edit.setObjectName("studyEnvironmentManagerDescriptionEdit")
        self._description_edit.setFixedHeight(72)
        form.addWidget(self._description_edit, 1, 1)
        detail_layout.addLayout(form)

        self._detail_text.setObjectName("studyEnvironmentManagerDetailText")
        self._detail_text.setReadOnly(True)
        self._detail_text.setFixedHeight(104)
        detail_layout.addWidget(self._detail_text)

        self._configure_study_table()
        detail_layout.addWidget(self._study_table, 1)

        metadata_group = QGroupBox("Selected Study Metadata", detail_group)
        metadata_layout = QGridLayout(metadata_group)
        metadata_layout.addWidget(self._important_check, 0, 0, 1, 2)
        metadata_layout.addWidget(QLabel("Dataset role", metadata_group), 1, 0)
        self._configure_role_combo()
        metadata_layout.addWidget(self._role_combo, 1, 1)
        metadata_layout.addWidget(QLabel("Description", metadata_group), 2, 0)
        self._study_description_edit.setObjectName(
            "studyEnvironmentManagerStudyDescriptionEdit"
        )
        self._study_description_edit.setFixedHeight(74)
        metadata_layout.addWidget(self._study_description_edit, 2, 1)
        detail_layout.addWidget(metadata_group)

        content.addWidget(detail_group, 3)

        self._important_check.toggled.connect(self._on_study_metadata_edited)
        self._role_combo.currentIndexChanged.connect(self._on_study_metadata_edited)
        self._study_description_edit.textChanged.connect(self._on_study_metadata_edited)

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

    def _configure_study_table(self) -> None:
        table = self._study_table
        table.setObjectName("studyEnvironmentManagerStudyTable")
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
        table.itemSelectionChanged.connect(self._on_study_selection_changed)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)

    def _configure_role_combo(self) -> None:
        for role in STUDY_DATASET_ROLE_VALUES:
            self._role_combo.addItem(_role_label(role), role)

    def _reload(self, *, selected_setup_id: str | None = None) -> None:
        selected_id = str(selected_setup_id or self._selected_setup_id() or "")
        summaries = self._store.list_summaries()

        self._setup_list.blockSignals(True)
        try:
            self._setup_list.clear()
            for summary in summaries:
                item = QListWidgetItem(summary.display_name)
                item.setToolTip(
                    f"{summary.setup_id}\n"
                    f"{summary.description or '(no description)'}"
                )
                item.setData(self._SETUP_ID_ROLE, summary.setup_id)
                self._setup_list.addItem(item)
            if summaries:
                target_row = 0
                for row_index in range(self._setup_list.count()):
                    item = self._setup_list.item(row_index)
                    if item.data(self._SETUP_ID_ROLE) == selected_id:
                        target_row = row_index
                        break
                self._setup_list.setCurrentRow(target_row)
        finally:
            self._setup_list.blockSignals(False)

        if summaries:
            self._set_status(f"Loaded {len(summaries)} saved Study Environment(s).")
        else:
            self._set_status("No saved Study Environments were found.")
        self._on_setup_selection_changed()

    def _on_setup_selection_changed(self) -> None:
        setup_id = self._selected_setup_id()
        if not setup_id:
            self._set_current_setup(None)
            return
        try:
            setup = self._store.load_setup(setup_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Study Environment Manager",
                f"Could not load Study Environment: {exc!r}",
            )
            self._set_current_setup(None)
            return
        self._set_current_setup(setup)

    def _set_current_setup(self, setup: ChartStudySetup | None) -> None:
        self._current_setup = setup
        self._study_payloads = [dict(study) for study in setup.studies] if setup else []
        enabled = setup is not None
        self._name_edit.setEnabled(enabled)
        self._description_edit.setEnabled(enabled)
        self._save_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)

        if setup is None:
            self._name_edit.clear()
            self._description_edit.clear()
            self._detail_text.clear()
            self._study_table.setRowCount(0)
            self._set_metadata_editor_enabled(False)
            return

        self._name_edit.setText(setup.display_name)
        self._description_edit.setPlainText(setup.description)
        self._detail_text.setPlainText(self._setup_detail_text(setup))
        self._populate_studies()
        if self._study_payloads:
            self._study_table.selectRow(0)
        self._on_study_selection_changed()

    def _populate_studies(self) -> None:
        table = self._study_table
        table.blockSignals(True)
        try:
            table.setRowCount(0)
            for row_index, study in enumerate(self._study_payloads):
                table.insertRow(row_index)
                self._refresh_study_row(row_index, study)
        finally:
            table.blockSignals(False)

    def _refresh_study_row(self, row: int, study: Mapping[str, Any]) -> None:
        metadata = _metadata_from_study(study)
        values = [
            str(row + 1),
            _study_display_name(study),
            _study_tool_text(study),
            _params_summary(study),
            "yes" if metadata.important else "no",
            metadata.dataset_role,
            metadata.description,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setTextAlignment(Qt.AlignCenter)
            self._study_table.setItem(row, column, item)

    def _on_study_selection_changed(self) -> None:
        row = self._selected_study_row()
        if row < 0 or row >= len(self._study_payloads):
            self._set_metadata_editor_enabled(False)
            return

        metadata = _metadata_from_study(self._study_payloads[row])
        self._metadata_editor_updating = True
        try:
            self._important_check.setChecked(metadata.important)
            self._set_role_combo(metadata.dataset_role)
            self._study_description_edit.setPlainText(metadata.description)
        finally:
            self._metadata_editor_updating = False
        self._set_metadata_editor_enabled(True)

    def _on_study_metadata_edited(self, *_args: object) -> None:
        if self._metadata_editor_updating:
            return
        row = self._selected_study_row()
        if row < 0 or row >= len(self._study_payloads):
            return

        role = normalize_study_dataset_role(self._role_combo.currentData())
        metadata = StudyUserMetadata(
            important=self._important_check.isChecked(),
            dataset_role=role,
            description=self._study_description_edit.toPlainText().strip(),
        )
        study = dict(self._study_payloads[row])
        study["user_metadata"] = serialize_study_user_metadata(metadata)
        self._study_payloads[row] = study
        self._refresh_study_row(row, study)

    def _on_save_clicked(self) -> None:
        setup = self._current_setup
        if setup is None:
            return
        display_name = self._name_edit.text().strip()
        if not display_name:
            QMessageBox.information(
                self,
                "Study Environment Manager",
                "Display name is required.",
            )
            return

        try:
            updated = self._store.update_setup(
                setup_id=setup.setup_id,
                display_name=display_name,
                description=self._description_edit.toPlainText(),
                created_from=setup.created_from,
                studies=self._study_payloads,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Study Environment Manager",
                f"Could not update Study Environment: {exc!r}",
            )
            return

        self._set_status(f"Updated Study Environment: {updated.display_name}")
        self._reload(selected_setup_id=updated.setup_id)

    def _on_delete_clicked(self) -> None:
        setup = self._current_setup
        if setup is None:
            return
        if not self._confirm_delete_environment(setup):
            self._set_status("Study Environment delete cancelled.")
            return
        try:
            deleted = self._store.delete_setup(setup.setup_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Study Environment Manager",
                f"Could not delete Study Environment: {exc!r}",
            )
            return
        if not deleted:
            QMessageBox.warning(
                self,
                "Study Environment Manager",
                "The selected Study Environment file was not found.",
            )
        self._reload()

    def _confirm_delete_environment(self, setup: ChartStudySetup) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Delete Study Environment")
        dialog.setText(f'Delete Study Environment "{setup.display_name}"?')
        dialog.setInformativeText(
            "This removes only the saved Study Environment. "
            "Recipes, artifacts, databases, notebooks, and workspace snapshots are not deleted.\n\n"
            "This action cannot be undone."
        )
        delete_button = dialog.addButton("Delete", QMessageBox.DestructiveRole)
        dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _selected_setup_id(self) -> str:
        item = self._setup_list.currentItem()
        if item is None:
            return ""
        return str(item.data(self._SETUP_ID_ROLE) or "").strip()

    def _selected_study_row(self) -> int:
        rows = self._study_table.selectionModel().selectedRows()
        if not rows:
            return -1
        return rows[0].row()

    def _set_metadata_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self._important_check,
            self._role_combo,
            self._study_description_edit,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self._metadata_editor_updating = True
            try:
                self._important_check.setChecked(False)
                self._role_combo.setCurrentIndex(0)
                self._study_description_edit.clear()
            finally:
                self._metadata_editor_updating = False

    def _set_role_combo(self, value: object) -> None:
        role = normalize_study_dataset_role(value)
        for index in range(self._role_combo.count()):
            if self._role_combo.itemData(index) == role:
                self._role_combo.setCurrentIndex(index)
                return
        self._role_combo.setCurrentIndex(0)

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def _setup_detail_text(self, setup: ChartStudySetup) -> str:
        source = setup.created_from
        source_parts = [
            str(source.get(key, "") or "")
            for key in ("exchange", "market_type", "symbol", "timeframe")
        ]
        source_text = " / ".join(part for part in source_parts if part) or "(unknown)"
        return "\n".join(
            [
                f"ID: {setup.setup_id}",
                f"Created: {_format_timestamp(setup.created_at_ms)}",
                f"Updated: {_format_timestamp(setup.updated_at_ms)}",
                f"Source: {source_text}",
                f"Studies: {len(setup.studies)}",
                f"Content hash: {setup.content_hash}",
            ]
        )


def _metadata_from_study(study: Mapping[str, Any]) -> StudyUserMetadata:
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


def _role_label(role: str) -> str:
    if role == "utc":
        return "UTC"
    return str(role or "").replace("_", " ").title()


def _format_timestamp(timestamp_ms: int) -> str:
    if int(timestamp_ms) <= 0:
        return ""
    timestamp = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")


__all__ = ["StudyEnvironmentManagerDialog"]
