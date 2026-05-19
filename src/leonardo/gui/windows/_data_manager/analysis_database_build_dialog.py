from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
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

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.gui.windows._data_manager.analysis_database_feature_builder import (
    build_manifest_features_from_saved_columns,
)
from leonardo.gui.windows._data_manager.saved_artifact_columns import (
    SavedArtifactColumn,
    load_saved_artifact_columns,
)


class AnalysisDatabaseBuildDialog(QDialog):
    """Build confirmation and inspection dialog for one Analysis Database.

    This dialog does not edit the saved manifest recipe. It previews the
    database's current components and the saved artifact columns available in
    the selected dataset, highlighting artifacts already present in the
    database recipe. The build action materializes ``dataframe.csv`` from the
    selected database's existing manifest recipe.
    """

    database_materialized = Signal(object)  # AnalysisDatabaseManifest
    status_message = Signal(str)

    _EXISTING_COMPONENT_BRUSH = QBrush(QColor(255, 252, 214))

    def __init__(
        self,
        *,
        historical_root: Path,
        manifest: AnalysisDatabaseManifest,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._manifest = manifest
        self._store = AnalysisDatabaseStore(historical_root=self._historical_root)
        self._candidate_columns = load_saved_artifact_columns(
            historical_root=self._historical_root,
            market=self._manifest.market,
        )

        self.setWindowTitle("Build Analysis Database")
        self.resize(960, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        intro = QLabel(
            "Build creates dataframe.csv from this database's saved manifest recipe. "
            "It does not add, remove, or replace artifacts. Saved artifacts already present "
            "in the recipe are highlighted in pale yellow below.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        current_group = QGroupBox("Database Components to Build", self)
        current_layout = QVBoxLayout(current_group)
        current_layout.setContentsMargins(8, 12, 8, 8)
        current_layout.setSpacing(8)

        self._details = QPlainTextEdit(current_group)
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(150)
        current_layout.addWidget(self._details)

        self._current_list = QListWidget(current_group)
        current_layout.addWidget(self._current_list, 1)

        body.addWidget(current_group, 3)

        candidate_group = QGroupBox("Saved Artifacts Available in Dataset", self)
        candidate_layout = QVBoxLayout(candidate_group)
        candidate_layout.setContentsMargins(8, 12, 8, 8)
        candidate_layout.setSpacing(8)

        self._candidate_hint = QLabel(candidate_group)
        self._candidate_hint.setWordWrap(True)
        candidate_layout.addWidget(self._candidate_hint)

        self._candidate_list = QListWidget(candidate_group)
        candidate_layout.addWidget(self._candidate_list, 1)

        body.addWidget(candidate_group, 2)

        self._build_button = QPushButton("Build Database", self)
        self._build_button.clicked.connect(self._build_database)
        root.addWidget(self._build_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._refresh_view()

    def _refresh_view(self) -> None:
        self._details.setPlainText(self._manifest_details())
        self._refresh_current_components()
        self._refresh_candidate_components()

    def _manifest_details(self) -> str:
        return "\n".join(
            [
                f"Database: {self._manifest.display_name}",
                f"Database ID: {self._manifest.database_id}",
                f"Status: {self._manifest.status}",
                f"Feature columns: {len(self._manifest.feature_columns)}",
                "",
                "Build preserves database_id, folder, display name, base-column policy, "
                "user description, and the saved feature recipe.",
            ]
        )

    def _refresh_current_components(self) -> None:
        self._current_list.clear()
        for column in self._manifest.feature_columns:
            label = f"{column.db_column_name}\n{column.source_family} · {column.source_column_name}"
            item = QListWidgetItem(label, self._current_list)
            item.setToolTip(column.db_column_name)

    def _refresh_candidate_components(self) -> None:
        self._candidate_list.clear()
        if not self._candidate_columns:
            self._candidate_hint.setText("No saved indicator, oscillator, or construct columns found for this dataset.")
            return

        self._candidate_hint.setText(
            f"Found {len(self._candidate_columns)} saved artifact column(s). "
            "Pale yellow rows are already present in the selected database recipe."
        )
        existing_db_columns = self._existing_db_column_names()
        for column in self._candidate_columns:
            label = (
                f"{column.family[:-1].capitalize()} · {column.tool_title} · "
                f"{column.instance_key}  ->  {column.column_name}"
            )
            item = QListWidgetItem(label, self._candidate_list)
            item.setToolTip(str(column.path))
            if self._candidate_db_column_name(column) in existing_db_columns:
                item.setBackground(self._EXISTING_COMPONENT_BRUSH)
                item.setToolTip(f"Already present in this database recipe\n{column.path}")

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

    def _build_database(self) -> None:
        answer = QMessageBox.question(
            self,
            "Build Analysis Database",
            (
                f"Build analysis database '{self._manifest.display_name}'?\n\n"
                f"Database ID: {self._manifest.database_id}\n\n"
                "This creates dataframe.csv from the saved manifest recipe. It does not add, remove, or replace artifacts."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            updated = self._store.materialize_database(
                market=self._manifest.market,
                database_id=self._manifest.database_id,
                overwrite=True,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Build Failed",
                f"Failed to build selected database:\n{exc!r}",
            )
            self.status_message.emit(f"Failed to build analysis database: {exc!r}")
            return

        self._manifest = updated
        self.database_materialized.emit(updated)
        self.status_message.emit(f"Built selected analysis database: {updated.display_name}")
        QMessageBox.information(
            self,
            "Analysis Database Built",
            f"Built analysis database '{updated.display_name}'.",
        )
        self.accept()
