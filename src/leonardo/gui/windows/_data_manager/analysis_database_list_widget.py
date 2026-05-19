from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest, AnalysisDatabaseSummary
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_metadata_naming import format_ts_ms_rome, format_ts_ms_utc
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.button_rack import make_button_rack


class AnalysisDatabaseListWidget(QGroupBox):
    """Select, inspect, build, rebuild, rename, delete, and preview Analysis Databases.

    This widget manages existing Analysis Database artifacts. Build and rebuild
    are intentionally separate GUI actions, but both materialize the selected
    database from its own saved manifest recipe. Component editing is exposed
    as a separate explicit intent and must not be folded into rebuild semantics.
    """

    database_selected = Signal(object)  # AnalysisDatabaseManifest | None
    database_materialized = Signal(object)  # AnalysisDatabaseManifest
    build_requested = Signal(object)  # AnalysisDatabaseManifest
    component_edit_requested = Signal(object)  # AnalysisDatabaseManifest
    preview_requested = Signal(object, str)  # Path, title
    status_message = Signal(str)

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Database Builder", parent)
        self._historical_root = Path(historical_root)
        self._store = AnalysisDatabaseStore(historical_root=self._historical_root)
        self._market: Optional[MarketId] = None
        self._selected_manifest: Optional[AnalysisDatabaseManifest] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        content = QVBoxLayout()
        content.setSpacing(8)
        root.addLayout(content, 1)

        self._hint_label = QLabel("Select a dataset to list saved analysis databases.", self)
        self._hint_label.setWordWrap(True)
        content.addWidget(self._hint_label)

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        content.addWidget(self._list, 1)

        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setPlaceholderText(
            "Highlight an analysis database to inspect its manifest summary. "
            "Check one database to select it for actions."
        )
        content.addWidget(self._details, 1)

        self._build_button = QPushButton("Build Selected Database", self)
        self._build_button.setToolTip(
            "Enabled only when exactly one draft/unmaterialized database is checked. "
            "Build creates dataframe.csv from the selected database's saved manifest recipe."
        )
        self._build_button.setEnabled(False)
        self._build_button.clicked.connect(self._build_selected)

        self._rebuild_button = QPushButton("Rebuild Selected Database", self)
        self._rebuild_button.setToolTip(
            "Enabled only when exactly one materialized database is checked. "
            "Rebuild rewrites dataframe.csv from the same saved manifest recipe."
        )
        self._rebuild_button.setEnabled(False)
        self._rebuild_button.clicked.connect(self._rebuild_selected)

        self._edit_components_button = QPushButton("Edit Selected Database Components...", self)
        self._edit_components_button.setToolTip(
            "Enabled only when exactly one database is checked. Opens the explicit component editor; rebuild remains manifest-only."
        )
        self._edit_components_button.setEnabled(False)
        self._edit_components_button.clicked.connect(self._edit_components_selected)

        self._rename_button = QPushButton("Rename Selected Database", self)
        self._rename_button.setToolTip("Enabled only when exactly one database is checked.")
        self._rename_button.setEnabled(False)
        self._rename_button.clicked.connect(self._rename_selected)

        self._delete_button = QPushButton("Delete Selected Database", self)
        self._delete_button.setToolTip("Enabled only when exactly one database is checked.")
        self._delete_button.setEnabled(False)
        self._delete_button.clicked.connect(self._delete_selected)

        self._preview_button = QPushButton("Preview Selected Database", self)
        self._preview_button.setToolTip("Enabled only when exactly one checked database is materialized.")
        self._preview_button.setEnabled(False)
        self._preview_button.clicked.connect(self._preview_selected)

        self._refresh_button = QPushButton("Refresh Analysis Databases", self)
        self._refresh_button.clicked.connect(self.refresh)
        root.addLayout(
            make_button_rack(
                self._build_button,
                self._rebuild_button,
                self._edit_components_button,
                self._rename_button,
                self._delete_button,
                self._preview_button,
                self._refresh_button,
            ),
            0,
        )

    def set_market(self, market: Optional[MarketId]) -> None:
        self._market = market
        self.refresh()

    def refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._details.clear()
        self._selected_manifest = None
        self.database_selected.emit(None)
        self._refresh_action_buttons()

        if self._market is None:
            self._hint_label.setText(
                "Select a dataset to list saved analysis databases. "
                "Check exactly one database to select it for actions; highlighting only shows details."
            )
            return

        summaries = self._store.list_databases(market=self._market)
        if not summaries:
            self._hint_label.setText("No analysis database manifests found for this dataset.")
            return

        self._hint_label.setText(
            f"Found {len(summaries)} analysis database manifest(s). "
            "Check exactly one database to select it for build, rebuild, component editing, rename, delete, or preview. "
            "Build creates dataframe.csv for draft/unmaterialized databases. "
            "Rebuild rewrites dataframe.csv for materialized databases using the same manifest recipe. "
            "Neither action adds, removes, or replaces artifacts. Use Edit Selected Database Components for explicit recipe changes."
        )
        self._list.blockSignals(True)
        for summary in summaries:
            item = QListWidgetItem(self._summary_label(summary), self._list)
            item.setData(Qt.UserRole, summary)
            item.setToolTip(str(summary.manifest_path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        self._list.blockSignals(False)
        self._refresh_action_buttons()

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._refresh_action_buttons()

    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if not items:
            self._details.clear()
            self._selected_manifest = None
            self.database_selected.emit(None)
            self._refresh_action_buttons()
            return

        summary = items[0].data(Qt.UserRole)
        if not isinstance(summary, AnalysisDatabaseSummary):
            self._details.clear()
            self._selected_manifest = None
            self.database_selected.emit(None)
            self._refresh_action_buttons()
            return

        try:
            manifest = self._store.load_manifest(market=summary.market, database_id=summary.database_id)
        except Exception as exc:
            self._details.setPlainText(f"Failed to load manifest:\n{exc!r}")
            self._selected_manifest = None
            self.database_selected.emit(None)
            self._refresh_action_buttons()
            return

        self._selected_manifest = manifest
        self._details.setPlainText(self._manifest_details(manifest))
        self.database_selected.emit(manifest)
        self.status_message.emit(f"Highlighted analysis database: {manifest.display_name}")
        self._refresh_action_buttons()

    def _build_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="building")
        if manifest is None:
            return
        if self._is_materialized(manifest):
            QMessageBox.warning(
                self,
                "Build Selected Database",
                "The selected database is already materialized. Use Rebuild Selected Database instead.",
            )
            self._refresh_action_buttons()
            return

        self.build_requested.emit(manifest)
        self.status_message.emit(f"Opening build dialog for selected analysis database: {manifest.display_name}")

    def _rebuild_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="rebuilding")
        if manifest is None:
            return
        if not self._is_materialized(manifest):
            QMessageBox.warning(
                self,
                "Rebuild Selected Database",
                "The selected database is not materialized yet. Use Build Selected Database first.",
            )
            self._refresh_action_buttons()
            return

        self._materialize_checked_manifest(
            manifest=manifest,
            action_label="Rebuild",
            detail="This will rewrite dataframe.csv for the selected database using its existing manifest recipe.",
        )

    def _materialize_checked_manifest(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        action_label: str,
        detail: str,
    ) -> None:
        answer = QMessageBox.question(
            self,
            f"{action_label} Selected Database",
            (
                f"{action_label} selected analysis database '{manifest.display_name}'?\n\n"
                f"Database ID: {manifest.database_id}\n\n"
                f"{detail}\n\n"
                "This does not create another database, does not change the database name, "
                "and does not add, remove, or replace artifacts."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            updated = self._store.materialize_database(
                market=manifest.market,
                database_id=manifest.database_id,
                overwrite=True,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Analysis Database",
                f"Failed to {action_label.lower()} selected database:\n{exc!r}",
            )
            return

        self.refresh()
        self._select_database_by_id(updated.database_id)
        self.database_materialized.emit(updated)
        if action_label == "Rebuild":
            self.status_message.emit(f"Rebuilt selected analysis database: {updated.display_name}")
        else:
            self.status_message.emit(f"Built selected analysis database: {updated.display_name}")


    def _edit_components_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="editing components")
        if manifest is None:
            return

        self.component_edit_requested.emit(manifest)
        self.status_message.emit(f"Editing components for selected analysis database: {manifest.display_name}")

    def _rename_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="renaming")
        if manifest is None:
            return

        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Database",
            "Database name",
            text=manifest.display_name,
        )
        if not accepted:
            return

        try:
            updated = self._store.rename_database(
                market=manifest.market,
                database_id=manifest.database_id,
                new_display_name=new_name,
            )
        except (FileExistsError, ValueError) as exc:
            QMessageBox.warning(self, "Analysis Database", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Analysis Database", f"Failed to rename database:\n{exc!r}")
            return

        self.refresh()
        self._select_database_by_id(updated.database_id)
        self.status_message.emit(f"Renamed selected analysis database: {updated.display_name}")

    def _delete_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="deleting")
        if manifest is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Database",
            (
                f"Delete selected analysis database '{manifest.display_name}'?\n\n"
                "This removes the database folder, including manifest.json, dataframe.csv, and database-local files."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self._store.delete_database(market=manifest.market, database_id=manifest.database_id)
        except Exception as exc:
            QMessageBox.critical(self, "Analysis Database", f"Failed to delete database:\n{exc!r}")
            return

        display_name = manifest.display_name
        self.refresh()
        self.status_message.emit(f"Deleted selected analysis database: {display_name}")

    def _preview_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="previewing")
        if manifest is None:
            return
        if not self._is_materialized(manifest):
            QMessageBox.warning(
                self,
                "Analysis Database",
                "The selected analysis database is not materialized yet. Build it before previewing dataframe.csv.",
            )
            return

        path = self._store.dataframe_path(market=manifest.market, database_id=manifest.database_id)
        if not path.exists():
            QMessageBox.warning(self, "Analysis Database", f"dataframe.csv was not found:\n{path}")
            return

        self.preview_requested.emit(path, f"Analysis Database · {manifest.display_name}")
        self.status_message.emit(f"Previewing selected analysis database: {manifest.display_name}")

    def _checked_summaries(self) -> list[AnalysisDatabaseSummary]:
        summaries: list[AnalysisDatabaseSummary] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() != Qt.Checked:
                continue
            summary = item.data(Qt.UserRole)
            if isinstance(summary, AnalysisDatabaseSummary):
                summaries.append(summary)
        return summaries

    def _single_checked_summary(self) -> AnalysisDatabaseSummary | None:
        checked = self._checked_summaries()
        if len(checked) != 1:
            return None
        return checked[0]

    def _single_checked_manifest(self, *, action_label: str) -> AnalysisDatabaseManifest | None:
        summary = self._single_checked_summary()
        if summary is None:
            QMessageBox.warning(
                self,
                "Analysis Database",
                f"Check exactly one database before {action_label}. Highlighting alone does not select a database.",
            )
            self._refresh_action_buttons()
            return None
        try:
            return self._store.load_manifest(
                market=summary.market,
                database_id=summary.database_id,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Analysis Database",
                f"Failed to load selected database:\n{exc!r}",
            )
            return None

    def _refresh_action_buttons(self) -> None:
        checked = self._checked_summaries()
        checked_count = len(checked)
        has_single_checked = checked_count == 1
        selected_summary = checked[0] if has_single_checked else None
        is_materialized = (
            selected_summary is not None
            and selected_summary.status == "materialized"
            and selected_summary.row_count is not None
        )

        self._build_button.setEnabled(has_single_checked and not is_materialized)
        self._rebuild_button.setEnabled(has_single_checked and is_materialized)
        self._edit_components_button.setEnabled(has_single_checked)
        self._rename_button.setEnabled(has_single_checked)
        self._delete_button.setEnabled(has_single_checked)
        self._preview_button.setEnabled(has_single_checked and is_materialized)

    def _select_database_by_id(self, database_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            summary = item.data(Qt.UserRole)
            if isinstance(summary, AnalysisDatabaseSummary) and summary.database_id == database_id:
                self._list.setCurrentItem(item)
                return

    def _summary_label(self, summary: AnalysisDatabaseSummary) -> str:
        row_count = "draft" if summary.row_count is None else f"{summary.row_count} rows"
        column_count = "" if summary.column_count is None else f" · {summary.column_count} column(s)"
        return f"{summary.display_name} · {summary.status} · {summary.feature_count} feature(s) · {row_count}{column_count}"

    def _is_materialized(self, manifest: AnalysisDatabaseManifest) -> bool:
        return bool(manifest.status == "materialized" and manifest.materialization is not None and manifest.dataframe_filename)

    def _manifest_details(self, manifest: AnalysisDatabaseManifest) -> str:
        selected_base = [column.db_column_name for column in manifest.base_columns if column.selected]
        feature_lines = [
            f"- {column.db_column_name}  <-  {column.source_column_name}"
            for column in manifest.feature_columns
        ]
        source_lines = [
            f"- {source.tool_title} ({source.tool_key}) · {source.instance_key}"
            for source in manifest.feature_sources
        ]
        materialization = manifest.materialization
        if materialization is None:
            materialization_lines = ["Status: not materialized", "Dataframe: (none)"]
        else:
            materialization_lines = [
                f"Rows: {materialization.row_count}",
                f"Columns: {materialization.column_count}",
                self._format_ts_ms_line("First ts_ms", materialization.first_ts_ms),
                self._format_ts_ms_line("Last ts_ms", materialization.last_ts_ms),
                f"Dataframe sha256: {materialization.dataframe_sha256 or '(none)'}",
                f"Dataframe: {manifest.dataframe_filename or '(none)'}",
            ]

        sections = [
            f"Name: {manifest.display_name}",
            f"Database ID: {manifest.database_id}",
            f"Status: {manifest.status}",
            f"Market: {manifest.market.exchange} / {manifest.market.market_type} / {manifest.market.symbol} / {manifest.market.timeframe}",
            f"Description: {manifest.description.user_text or '(none)'}",
            "",
            manifest.description.generated_summary,
            "",
            "Materialization:",
            "\n".join(materialization_lines),
            "",
            "Studies/tools used:",
            manifest.description.studies_used_summary,
            "",
            "Selected base columns:",
            ", ".join(selected_base) if selected_base else "(none)",
            "",
            "Source artifacts:",
            "\n".join(source_lines) if source_lines else "(none)",
            "",
            "Feature columns:",
            "\n".join(feature_lines) if feature_lines else "(none)",
        ]
        return "\n".join(sections)

    def _format_ts_ms_line(self, label: str, ts_ms: int | None) -> str:
        raw = "(n/a)" if ts_ms is None else str(ts_ms)
        return f"{label}: {raw} | UTC: {format_ts_ms_utc(ts_ms)} | Europe/Rome: {format_ts_ms_rome(ts_ms)}"
