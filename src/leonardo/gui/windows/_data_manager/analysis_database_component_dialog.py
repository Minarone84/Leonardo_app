from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.analysis_database_component_editor import (
    AnalysisDatabaseComponentEditReport,
    AnalysisDatabaseComponentEditor,
)
from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest
from leonardo.gui.windows._data_manager.analysis_database_feature_builder import (
    build_manifest_features_from_saved_columns,
)
from leonardo.gui.windows._data_manager.saved_artifact_columns import (
    SavedArtifactColumn,
    load_saved_artifact_columns,
)


class AnalysisDatabaseComponentDialog(QDialog):
    """Explicit component editor for one Analysis Database.

    This dialog is a user-intent surface for changing an existing Analysis
    Database recipe. It auto-loads saved artifact columns for the database's
    market partition and highlights already-present components. It is separate
    from Database Builder's build/rebuild action: build/rebuild materializes the
    existing manifest, while this dialog edits the manifest feature recipe and
    resets materialization through the data-layer component editor.
    """

    components_changed = Signal(object)  # AnalysisDatabaseComponentEditReport
    status_message = Signal(str)

    _EXISTING_COMPONENT_BRUSH = QBrush(QColor("#C8F7C5"))
    _EXISTING_COMPONENT_FOREGROUND = QBrush(QColor("#000000"))

    def __init__(
        self,
        *,
        historical_root: Path,
        manifest: AnalysisDatabaseManifest,
        selected_columns: Sequence[object] = (),
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._manifest = manifest
        self._initial_checked_keys = {
            self._column_key(column)
            for column in selected_columns
            if isinstance(column, SavedArtifactColumn)
        }
        self._candidate_columns = load_saved_artifact_columns(
            historical_root=self._historical_root,
            market=self._manifest.market,
        )
        self._editor = AnalysisDatabaseComponentEditor(historical_root=self._historical_root)

        self.setWindowTitle("Edit Analysis Database Components")
        self.resize(1120, 700)
        self.setMinimumSize(1080, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "This editor intentionally changes the selected Analysis Database recipe. "
            "Saved artifacts are loaded automatically for this dataset. Light green rows are already present in the database. "
            "After saving component changes, the database is reset to draft state and must be rebuilt.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        current_group = QGroupBox("Current Database Components", self)
        current_layout = QVBoxLayout(current_group)
        current_layout.setContentsMargins(8, 12, 8, 8)
        current_layout.setSpacing(8)

        self._details = QPlainTextEdit(current_group)
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(150)
        current_layout.addWidget(self._details)

        self._current_list = QListWidget(current_group)
        self._current_list.itemChanged.connect(lambda _item: self._refresh_action_buttons())
        current_layout.addWidget(self._current_list, 1)

        remove_button = QPushButton("Remove Checked Components", current_group)
        remove_button.setToolTip("Removes checked existing feature columns from the database recipe.")
        remove_button.clicked.connect(self._remove_checked_components)
        self._remove_button = remove_button
        current_layout.addWidget(remove_button)

        body.addWidget(current_group, 3)

        candidate_group = QGroupBox("Saved Artifact Columns", self)
        candidate_layout = QVBoxLayout(candidate_group)
        candidate_layout.setContentsMargins(8, 12, 8, 8)
        candidate_layout.setSpacing(8)

        self._candidate_hint = QLabel(candidate_group)
        self._candidate_hint.setWordWrap(True)
        candidate_layout.addWidget(self._candidate_hint)

        self._candidate_list = QListWidget(candidate_group)
        self._candidate_list.itemChanged.connect(lambda _item: self._refresh_action_buttons())
        candidate_layout.addWidget(self._candidate_list, 1)

        candidate_action_row = QHBoxLayout()
        candidate_action_row.setSpacing(8)
        candidate_layout.addLayout(candidate_action_row)

        self._add_button = QPushButton("Add Checked Artifacts", candidate_group)
        self._add_button.setToolTip("Adds the checked saved artifact columns to this database recipe.")
        self._add_button.clicked.connect(self._add_checked_artifacts)
        candidate_action_row.addWidget(self._add_button)

        self._replace_button = QPushButton("Replace All Components", candidate_group)
        self._replace_button.setToolTip("Replaces the database feature recipe with the checked saved artifact columns.")
        self._replace_button.clicked.connect(self._replace_all_components)
        candidate_action_row.addWidget(self._replace_button)

        body.addWidget(candidate_group, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._refresh_view()

    def _refresh_view(self) -> None:
        self._details.setPlainText(self._manifest_details())
        self._refresh_current_components()
        self._refresh_candidate_components()
        self._refresh_action_buttons()

    def _manifest_details(self) -> str:
        return "\n".join(
            [
                f"Database: {self._manifest.display_name}",
                f"Database ID: {self._manifest.database_id}",
                f"Status: {self._manifest.status}",
                f"Feature columns: {len(self._manifest.feature_columns)}",
                "",
                "Saving component changes will preserve database_id, folder, display name, "
                "base-column policy, user description, and metadata. It will reset materialization "
                "and remove stale dataframe.csv if present.",
            ]
        )

    def _refresh_current_components(self) -> None:
        self._current_list.blockSignals(True)
        self._current_list.clear()
        for column in self._manifest.feature_columns:
            label = f"{column.db_column_name}\n{column.source_family} · {column.source_column_name}"
            item = QListWidgetItem(label, self._current_list)
            item.setData(Qt.ItemDataRole.UserRole, column.db_column_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        self._current_list.blockSignals(False)

    def _refresh_candidate_components(self) -> None:
        self._candidate_list.blockSignals(True)
        self._candidate_list.clear()
        if not self._candidate_columns:
            self._candidate_hint.setText("No saved indicator, oscillator, or construct columns found for this dataset.")
            self._candidate_list.blockSignals(False)
            return

        self._candidate_hint.setText(
            f"Found {len(self._candidate_columns)} saved artifact column(s). "
            "Check rows inside this dialog to add or replace components. Light green rows are already present."
        )
        existing_db_columns = self._existing_db_column_names()
        for column in self._candidate_columns:
            label = (
                f"{column.family[:-1].capitalize()} · {column.tool_title} · "
                f"{column.instance_key}  ->  {column.column_name}"
            )
            item = QListWidgetItem(label, self._candidate_list)
            item.setToolTip(str(column.path))
            item.setData(Qt.ItemDataRole.UserRole, column)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if self._column_key(column) in self._initial_checked_keys else Qt.CheckState.Unchecked
            )
            if self._candidate_db_column_name(column) in existing_db_columns:
                item.setBackground(self._EXISTING_COMPONENT_BRUSH)
                item.setForeground(self._EXISTING_COMPONENT_FOREGROUND)
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(f"Already present in this database recipe\n{column.path}")
        self._candidate_list.blockSignals(False)

    def _column_key(self, column: SavedArtifactColumn) -> tuple[str, str, str, str, str]:
        return (
            column.family,
            column.tool_key,
            column.instance_key,
            column.column_name,
            Path(column.path).as_posix(),
        )

    def _existing_db_column_names(self) -> set[str]:
        return {column.db_column_name for column in self._manifest.feature_columns}

    def _candidate_db_column_name(self, column: SavedArtifactColumn) -> str:
        try:
            _sources, feature_columns = build_manifest_features_from_saved_columns(
                historical_root=self._historical_root,
                market=self._manifest.market,
                selected_columns=(column,),
            )
            if feature_columns:
                return feature_columns[0].db_column_name
        except Exception:
            return ""
        return ""

    def _checked_candidate_columns(self) -> tuple[SavedArtifactColumn, ...]:
        columns: list[SavedArtifactColumn] = []
        for row in range(self._candidate_list.count()):
            item = self._candidate_list.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            column = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(column, SavedArtifactColumn):
                columns.append(column)
        return tuple(columns)

    def _checked_component_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for row in range(self._current_list.count()):
            item = self._current_list.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if name:
                names.append(name)
        return tuple(names)

    def _refresh_action_buttons(self) -> None:
        has_candidates = bool(self._checked_candidate_columns())
        has_checked_components = bool(self._checked_component_names())
        self._add_button.setEnabled(has_candidates)
        self._replace_button.setEnabled(has_candidates)
        self._remove_button.setEnabled(has_checked_components)

    def _candidate_feature_recipe(self):
        return build_manifest_features_from_saved_columns(
            historical_root=self._historical_root,
            market=self._manifest.market,
            selected_columns=self._checked_candidate_columns(),
        )

    def _add_checked_artifacts(self) -> None:
        checked_columns = self._checked_candidate_columns()
        if not checked_columns:
            QMessageBox.warning(
                self,
                "Edit Components",
                "Check one or more saved artifact columns before adding components.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Add Database Components",
            (
                f"Add {len(checked_columns)} checked artifact column(s) to "
                f"'{self._manifest.display_name}'?\n\n"
                "This changes the database recipe, resets materialization, and requires a rebuild."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        feature_sources, feature_columns = self._candidate_feature_recipe()
        self._apply_edit(
            action_label="add components",
            editor_call=lambda: self._editor.add_components(
                market=self._manifest.market,
                database_id=self._manifest.database_id,
                feature_sources=feature_sources,
                feature_columns=feature_columns,
            ),
        )

    def _replace_all_components(self) -> None:
        checked_columns = self._checked_candidate_columns()
        if not checked_columns:
            QMessageBox.warning(
                self,
                "Edit Components",
                "Check one or more saved artifact columns before replacing components.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Replace Database Components",
            (
                f"Replace all {len(self._manifest.feature_columns)} current component(s) in "
                f"'{self._manifest.display_name}' with {len(checked_columns)} checked artifact column(s)?\n\n"
                "This intentionally changes the database recipe, resets materialization, removes stale dataframe.csv, "
                "and requires a rebuild."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        feature_sources, feature_columns = self._candidate_feature_recipe()
        self._apply_edit(
            action_label="replace components",
            editor_call=lambda: self._editor.replace_components(
                market=self._manifest.market,
                database_id=self._manifest.database_id,
                feature_sources=feature_sources,
                feature_columns=feature_columns,
            ),
        )

    def _remove_checked_components(self) -> None:
        checked_names = self._checked_component_names()
        if not checked_names:
            QMessageBox.warning(
                self,
                "Edit Components",
                "Check one or more existing components before removing them.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Remove Database Components",
            (
                f"Remove {len(checked_names)} checked component(s) from '{self._manifest.display_name}'?\n\n"
                "This changes the database recipe, resets materialization, removes stale dataframe.csv, "
                "and requires a rebuild."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._apply_edit(
            action_label="remove components",
            editor_call=lambda: self._editor.remove_components(
                market=self._manifest.market,
                database_id=self._manifest.database_id,
                db_column_names=checked_names,
            ),
        )

    def _apply_edit(self, *, action_label: str, editor_call) -> None:
        try:
            report = editor_call()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Edit Components Failed",
                f"Failed to {action_label}:\n{exc!r}",
            )
            self.status_message.emit(f"Failed to {action_label}: {exc!r}")
            return

        self._manifest = report.manifest
        self.components_changed.emit(report)
        self.status_message.emit(
            f"Edited components for Analysis Database: {report.manifest.display_name}"
        )
        self._refresh_view()
        QMessageBox.information(
            self,
            "Database Components Updated",
            self._format_report(report),
        )

    def _format_report(self, report: AnalysisDatabaseComponentEditReport) -> str:
        reset = "yes" if report.materialization_reset else "no"
        removed = "yes" if report.dataframe_removed else "no"
        return "\n".join(
            [
                f"Database: {report.manifest.display_name}",
                f"Database ID: {report.database_id}",
                "",
                f"Previous feature count: {report.previous_feature_count}",
                f"New feature count: {report.new_feature_count}",
                f"Recipe changed: {'yes' if report.recipe_changed else 'no'}",
                f"Materialization reset: {reset}",
                f"Stale dataframe.csv removed: {removed}",
                "",
                "Use Build Selected Database to materialize the updated recipe.",
            ]
        )
