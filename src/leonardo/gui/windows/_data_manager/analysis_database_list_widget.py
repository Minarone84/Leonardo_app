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
from leonardo.data.historical.data_manager_selected_update_service import (
    DataManagerSelectedUpdateService,
    SelectedAnalysisDatabaseUpdateRef,
    SelectedDatabaseUpdatePlan,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.button_rack import make_button_rack
from leonardo.gui.windows._data_manager.selected_update_dialog import (
    SelectedUpdateDialog,
    selected_execution_report_text,
    selected_plan_report_text,
    selected_update_preflight_text,
)


_BASE_LABEL_ROLE = Qt.UserRole + 1
_UPDATE_STATUS_ROLE = Qt.UserRole + 2
_UPDATE_ACTIONABLE_ROLE = Qt.UserRole + 3
_UPDATE_ITEM_ID_ROLE = Qt.UserRole + 4


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
    collection_extend_requested = Signal(object)  # AnalysisDatabaseManifest
    preview_requested = Signal(object, str)  # Path, title
    status_message = Signal(str)

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Database Builder", parent)
        self._historical_root = Path(historical_root)
        self._store = AnalysisDatabaseStore(historical_root=self._historical_root)
        self._selected_update_service = DataManagerSelectedUpdateService(
            historical_root=self._historical_root,
        )
        self._market: Optional[MarketId] = None
        self._selected_manifest: Optional[AnalysisDatabaseManifest] = None
        self._latest_update_plan: SelectedDatabaseUpdatePlan | None = None

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

        self._select_all_button = QPushButton("Select All", self)
        self._select_all_button.setEnabled(False)
        self._select_all_button.clicked.connect(self.select_all_databases)

        self._deselect_all_button = QPushButton("Deselect All", self)
        self._deselect_all_button.setEnabled(False)
        self._deselect_all_button.clicked.connect(self.deselect_all_databases)

        self._check_update_button = QPushButton("Check Update", self)
        self._check_update_button.setToolTip("Check update status for checked Analysis Database rows.")
        self._check_update_button.setEnabled(False)
        self._check_update_button.clicked.connect(self._check_selected_database_updates)

        self._update_selected_button = QPushButton("Update Selected Databases", self)
        self._update_selected_button.setToolTip(
            "Enabled only when the latest update check marks at least one checked database as OLD/actionable."
        )
        self._update_selected_button.setEnabled(False)
        self._update_selected_button.clicked.connect(self._update_selected_databases)

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

        self._extend_from_collection_button = QPushButton("Extend Database from Collection...", self)
        self._extend_from_collection_button.setToolTip(
            "Enabled only when exactly one database is checked. Resolves a saved recipe collection before extending the selected database."
        )
        self._extend_from_collection_button.setEnabled(False)
        self._extend_from_collection_button.clicked.connect(self._extend_from_collection_selected)

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
                self._select_all_button,
                self._deselect_all_button,
                self._check_update_button,
                self._update_selected_button,
                self._build_button,
                self._rebuild_button,
                self._edit_components_button,
                self._extend_from_collection_button,
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

    def select_all_databases(self) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(Qt.Checked)
        self._list.blockSignals(False)
        self._refresh_action_buttons()

    def deselect_all_databases(self) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(Qt.Unchecked)
        self._list.blockSignals(False)
        self._refresh_action_buttons()

    def refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._details.clear()
        self._selected_manifest = None
        self._latest_update_plan = None
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
            "Check exactly one database to select it for build, rebuild, component editing, collection extension, rename, delete, or preview. "
            "Build creates dataframe.csv for draft/unmaterialized databases. "
            "Rebuild rewrites dataframe.csv for materialized databases using the same manifest recipe. "
            "Neither action adds, removes, or replaces artifacts. Use Edit Selected Database Components for explicit recipe changes."
        )
        self._list.blockSignals(True)
        for summary in summaries:
            label = self._summary_label(summary)
            item = QListWidgetItem(label, self._list)
            item.setData(Qt.UserRole, summary)
            item.setData(_BASE_LABEL_ROLE, label)
            item.setData(_UPDATE_STATUS_ROLE, None)
            item.setData(_UPDATE_ACTIONABLE_ROLE, False)
            item.setData(_UPDATE_ITEM_ID_ROLE, None)
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

    def _extend_from_collection_selected(self) -> None:
        manifest = self._single_checked_manifest(action_label="extending from a recipe collection")
        if manifest is None:
            return

        self.collection_extend_requested.emit(manifest)
        self.status_message.emit(
            f"Extending selected analysis database from recipe collection: {manifest.display_name}"
        )

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
        self._extend_from_collection_button.setEnabled(has_single_checked)
        self._rename_button.setEnabled(has_single_checked)
        self._delete_button.setEnabled(has_single_checked)
        self._preview_button.setEnabled(has_single_checked and is_materialized)
        self._select_all_button.setEnabled(self._list.count() > 0)
        self._deselect_all_button.setEnabled(checked_count > 0)
        self._check_update_button.setEnabled(checked_count > 0)
        self._update_selected_button.setEnabled(bool(self._checked_actionable_database_action_ids()))

    def _check_selected_database_updates(self) -> None:
        summaries = self._checked_summaries()
        if not summaries:
            QMessageBox.information(
                self,
                "Check Update",
                "Check one or more Analysis Database rows before checking update status.",
            )
            self._refresh_action_buttons()
            return

        refs = [self._database_update_ref(summary) for summary in summaries]
        dialog = SelectedUpdateDialog(
            title="Check Selected Database Updates",
            summary=selected_update_preflight_text(
                selected_count=len(refs),
                operation="Check update status for selected Analysis Databases.",
            ),
            item_names=[summary.display_name for summary in summaries],
            confirm_label="Check Update",
            parent=self.window(),
        )
        dialog.confirmed.connect(
            lambda dialog=dialog, refs=tuple(refs): self._run_database_update_check(
                dialog=dialog,
                refs=refs,
            )
        )
        dialog.exec()

    def _run_database_update_check(
        self,
        *,
        dialog: SelectedUpdateDialog,
        refs: tuple[SelectedAnalysisDatabaseUpdateRef, ...],
    ) -> None:
        dialog.set_running("Checking selected Analysis Database update status...")
        try:
            plan = self._selected_update_service.plan_database_updates(refs)
        except Exception as exc:
            message = f"Failed to check selected database updates: {exc!r}"
            self.status_message.emit(message)
            dialog.set_terminal_report(message)
            QMessageBox.critical(self, "Selected Database Update Check Failed", message)
            return

        self._latest_update_plan = plan
        self._apply_database_update_plan(plan)
        self._refresh_action_buttons()
        dialog.set_terminal_report(selected_plan_report_text(plan))
        self.status_message.emit("Selected Analysis Database update check complete")

    def _update_selected_databases(self) -> None:
        if self._latest_update_plan is None:
            QMessageBox.information(
                self,
                "Update Selected Databases",
                "Run Check Update before updating selected Analysis Databases.",
            )
            self._refresh_action_buttons()
            return

        action_ids = self._checked_actionable_database_action_ids()
        if not action_ids:
            QMessageBox.information(
                self,
                "Update Selected Databases",
                "No checked database is marked OLD/actionable by the latest update check.",
            )
            self._refresh_action_buttons()
            return

        checked_count = len(self._checked_summaries())
        dialog = SelectedUpdateDialog(
            title="Update Selected Databases",
            summary=selected_update_preflight_text(
                selected_count=checked_count,
                actionable_count=len(action_ids),
                operation="Rebuild checked OLD/actionable Analysis Databases through the selected update service.",
            ),
            item_names=self._database_action_labels(action_ids),
            confirm_label="Update Selected Databases",
            parent=self.window(),
        )
        dialog.confirmed.connect(
            lambda dialog=dialog, action_ids=tuple(action_ids): self._run_database_update_execution(
                dialog=dialog,
                selected_action_ids=action_ids,
            )
        )
        dialog.exec()

    def _run_database_update_execution(
        self,
        *,
        dialog: SelectedUpdateDialog,
        selected_action_ids: tuple[str, ...],
    ) -> None:
        if self._latest_update_plan is None:
            dialog.set_terminal_report("No selected database update plan is available.")
            return

        dialog.set_running("Updating selected OLD/actionable Analysis Databases...")
        try:
            report = self._selected_update_service.execute_database_update_plan(
                self._latest_update_plan,
                selected_action_ids=selected_action_ids,
            )
        except Exception as exc:
            message = f"Failed to update selected databases: {exc!r}"
            self.status_message.emit(message)
            dialog.set_terminal_report(message)
            QMessageBox.critical(self, "Selected Database Update Failed", message)
            return

        dialog.set_terminal_report(selected_execution_report_text(report))
        self.status_message.emit("Selected Analysis Database update execution complete")
        self.refresh()

    def _database_update_ref(self, summary: AnalysisDatabaseSummary) -> SelectedAnalysisDatabaseUpdateRef:
        return SelectedAnalysisDatabaseUpdateRef(
            exchange=summary.market.exchange,
            market_type=summary.market.market_type,
            symbol=summary.market.symbol,
            timeframe=summary.market.timeframe,
            database_id=summary.database_id,
            display_name=summary.display_name,
        )

    def _apply_database_update_plan(self, plan: SelectedDatabaseUpdatePlan) -> None:
        items_by_database_id = {item.database_id: item for item in plan.items}
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            item = self._list.item(row)
            summary = item.data(Qt.UserRole)
            if not isinstance(summary, AnalysisDatabaseSummary):
                continue
            plan_item = items_by_database_id.get(summary.database_id)
            if plan_item is None:
                self._set_database_item_update_state(item, None, False, None)
            else:
                self._set_database_item_update_state(
                    item,
                    plan_item.status,
                    plan_item.actionable,
                    plan_item.item_id,
                )
        self._list.blockSignals(False)

    def _set_database_item_update_state(
        self,
        item: QListWidgetItem,
        status: str | None,
        actionable: bool,
        item_id: str | None,
    ) -> None:
        base_label = str(item.data(_BASE_LABEL_ROLE) or item.text())
        item.setData(_UPDATE_STATUS_ROLE, status)
        item.setData(_UPDATE_ACTIONABLE_ROLE, bool(actionable))
        item.setData(_UPDATE_ITEM_ID_ROLE, item_id)
        if status:
            item.setText(f"[{status.upper()}] {base_label}")
        else:
            item.setText(base_label)

    def _checked_actionable_database_action_ids(self) -> tuple[str, ...]:
        if self._latest_update_plan is None:
            return ()
        checked_item_ids = self._checked_actionable_database_item_ids()
        if not checked_item_ids:
            return ()
        return tuple(
            action.action_id
            for action in self._latest_update_plan.actions
            if action.item_id in checked_item_ids
        )

    def _checked_actionable_database_item_ids(self) -> set[str]:
        item_ids: set[str] = set()
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() != Qt.Checked:
                continue
            if item.data(_UPDATE_STATUS_ROLE) != "old":
                continue
            if not bool(item.data(_UPDATE_ACTIONABLE_ROLE)):
                continue
            item_id = str(item.data(_UPDATE_ITEM_ID_ROLE) or "")
            if item_id:
                item_ids.add(item_id)
        return item_ids

    def _database_action_labels(self, action_ids: tuple[str, ...]) -> list[str]:
        if self._latest_update_plan is None:
            return []
        action_by_id = {action.action_id: action for action in self._latest_update_plan.actions}
        labels: list[str] = []
        for action_id in action_ids:
            action = action_by_id.get(action_id)
            if action is None:
                labels.append(action_id)
            else:
                labels.append(action.label)
        return labels

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
