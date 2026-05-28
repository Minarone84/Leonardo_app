from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from leonardo.data.historical.data_manager_selected_update_service import (
    DataManagerSelectedUpdateService,
    SelectedArtifactUpdatePlan,
    SelectedArtifactUpdatePlanItem,
    SelectedArtifactUpdateRef,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.saved_artifact_columns import (
    NON_SELECTABLE_COLUMNS,
    SavedArtifactColumn,
    load_saved_artifact_columns,
)
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


class SavedArtifactSelectorWidget(QGroupBox):
    """Read-only selector for saved analysis-usable derived artifact columns."""

    selection_changed = Signal(object)  # list[SavedArtifactColumn]
    preview_requested = Signal(object, str)  # Path, title
    exit_selection_requested = Signal()
    status_message = Signal(str)

    NON_SELECTABLE_COLUMNS = NON_SELECTABLE_COLUMNS

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Saved Indicators / Oscillators / Constructs", parent)
        self._historical_root = Path(historical_root)
        self._selected_update_service = DataManagerSelectedUpdateService(
            historical_root=self._historical_root,
        )
        self._market: Optional[MarketId] = None
        self._columns: list[SavedArtifactColumn] = []
        self._build_selection_mode = False
        self._latest_update_plan: SelectedArtifactUpdatePlan | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        content = QVBoxLayout()
        content.setSpacing(8)
        root.addLayout(content, 1)

        self._hint_label = QLabel(
            "Select a dataset to list saved artifacts. Check a column to select it; "
            "highlighting only focuses a row. Preview is available only when exactly one column is checked.",
            self,
        )
        self._hint_label.setWordWrap(True)
        content.addWidget(self._hint_label)

        self._select_all_button = QPushButton("Select All", self)
        self._select_all_button.setEnabled(False)
        self._select_all_button.clicked.connect(self.select_all_artifacts)

        self._deselect_all_button = QPushButton("Deselect All", self)
        self._deselect_all_button.setEnabled(False)
        self._deselect_all_button.clicked.connect(self.deselect_all_artifacts)

        self._check_update_button = QPushButton("Check Update", self)
        self._check_update_button.setToolTip("Check update status for checked saved artifact rows.")
        self._check_update_button.setEnabled(False)
        self._check_update_button.clicked.connect(self._check_selected_artifact_updates)

        self._update_selected_button = QPushButton("Update Selected Artifacts", self)
        self._update_selected_button.setToolTip(
            "Enabled only when the latest update check marks at least one checked artifact as OLD/actionable."
        )
        self._update_selected_button.setEnabled(False)
        self._update_selected_button.clicked.connect(self._update_selected_artifacts)

        self._preview_button = QPushButton("Preview Selected Artifact", self)
        self._preview_button.setToolTip("Preview is enabled only when exactly one artifact column is checked.")
        self._preview_button.setEnabled(False)
        self._preview_button.clicked.connect(self._preview_selected_artifact)

        self._exit_selection_button = QPushButton("Exit Selection", self)
        self._exit_selection_button.setVisible(False)
        self._exit_selection_button.clicked.connect(self._confirm_exit_selection)

        self._refresh_button = QPushButton("Refresh Saved Artifacts", self)
        self._refresh_button.clicked.connect(self.refresh)

        root.addLayout(
            make_button_rack(
                self._select_all_button,
                self._deselect_all_button,
                self._check_update_button,
                self._update_selected_button,
                self._preview_button,
                self._exit_selection_button,
                self._refresh_button,
            ),
            0,
        )

        self._list = QListWidget(self)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.currentItemChanged.connect(lambda _current, _previous: self._refresh_preview_button())
        content.addWidget(self._list, 1)

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
        self._refresh_preview_button()
        self._refresh_hint_label()
        self._refresh_update_buttons()

    def select_all_artifacts(self) -> None:
        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(Qt.Checked)
        self._list.blockSignals(False)
        self._emit_selection_changed()
        self._refresh_preview_button()
        self._refresh_hint_label()
        self._refresh_update_buttons()

    def deselect_all_artifacts(self) -> None:
        self.clear_selection()

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
        self._latest_update_plan = None
        self._columns = []

        if self._market is None:
            self._refresh_hint_label()
            self._list.blockSignals(False)
            self._emit_selection_changed()
            self._refresh_update_buttons()
            return

        self._columns = load_saved_artifact_columns(
            historical_root=self._historical_root,
            market=self._market,
        )

        if not self._columns:
            self._refresh_hint_label()
            self._list.blockSignals(False)
            self._emit_selection_changed()
            self._refresh_update_buttons()
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
            item.setData(_BASE_LABEL_ROLE, label)
            item.setData(_UPDATE_STATUS_ROLE, None)
            item.setData(_UPDATE_ACTIONABLE_ROLE, False)
            item.setData(_UPDATE_ITEM_ID_ROLE, None)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)

        self._list.blockSignals(False)
        self._emit_selection_changed()
        self._refresh_preview_button()
        self._refresh_update_buttons()

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
        self._refresh_update_buttons()

    def _refresh_preview_button(self) -> None:
        self._preview_button.setEnabled(self._single_checked_column() is not None)

    def _refresh_update_buttons(self) -> None:
        checked_count = len(self._checked_columns())
        self._select_all_button.setEnabled(self._list.count() > 0)
        self._deselect_all_button.setEnabled(checked_count > 0)
        self._check_update_button.setEnabled(checked_count > 0)
        self._update_selected_button.setEnabled(bool(self._checked_actionable_artifact_action_ids()))

    def _check_selected_artifact_updates(self) -> None:
        columns = self._checked_artifacts_for_update()
        if not columns:
            QMessageBox.information(
                self,
                "Check Update",
                "Check one or more saved artifact rows before checking update status.",
            )
            self._refresh_update_buttons()
            return

        refs = [self._artifact_update_ref(column) for column in columns]
        dialog = SelectedUpdateDialog(
            title="Check Selected Artifact Updates",
            summary=selected_update_preflight_text(
                selected_count=len(refs),
                operation="Check update status for selected saved artifacts.",
            ),
            item_names=[self._artifact_display_name(column) for column in columns],
            confirm_label="Check Update",
            parent=self.window(),
        )
        dialog.confirmed.connect(
            lambda dialog=dialog, refs=tuple(refs): self._run_artifact_update_check(
                dialog=dialog,
                refs=refs,
            )
        )
        dialog.exec()

    def _run_artifact_update_check(
        self,
        *,
        dialog: SelectedUpdateDialog,
        refs: tuple[SelectedArtifactUpdateRef, ...],
    ) -> None:
        dialog.set_running("Checking selected saved artifact update status...")
        try:
            plan = self._selected_update_service.plan_artifact_updates(refs)
        except Exception as exc:
            message = f"Failed to check selected artifact updates: {exc!r}"
            self.status_message.emit(message)
            dialog.set_terminal_report(message)
            QMessageBox.critical(self, "Selected Artifact Update Check Failed", message)
            return

        self._latest_update_plan = plan
        self._apply_artifact_update_plan(plan)
        self._refresh_update_buttons()
        dialog.set_terminal_report(selected_plan_report_text(plan))
        self.status_message.emit("Selected artifact update check complete")

    def _update_selected_artifacts(self) -> None:
        if self._latest_update_plan is None:
            QMessageBox.information(
                self,
                "Update Selected Artifacts",
                "Run Check Update before updating selected artifacts.",
            )
            self._refresh_update_buttons()
            return

        action_ids = self._checked_actionable_artifact_action_ids()
        if not action_ids:
            QMessageBox.information(
                self,
                "Update Selected Artifacts",
                "No checked artifact is marked OLD/actionable by the latest update check.",
            )
            self._refresh_update_buttons()
            return

        checked_count = len(self._checked_artifacts_for_update())
        dialog = SelectedUpdateDialog(
            title="Update Selected Artifacts",
            summary=selected_update_preflight_text(
                selected_count=checked_count,
                actionable_count=len(action_ids),
                operation="Regenerate checked OLD/actionable saved artifacts through the selected update service.",
            ),
            item_names=self._artifact_action_labels(action_ids),
            confirm_label="Update Selected Artifacts",
            parent=self.window(),
        )
        dialog.confirmed.connect(
            lambda dialog=dialog, action_ids=tuple(action_ids): self._run_artifact_update_execution(
                dialog=dialog,
                selected_action_ids=action_ids,
            )
        )
        dialog.exec()

    def _run_artifact_update_execution(
        self,
        *,
        dialog: SelectedUpdateDialog,
        selected_action_ids: tuple[str, ...],
    ) -> None:
        if self._latest_update_plan is None:
            dialog.set_terminal_report("No selected artifact update plan is available.")
            return

        dialog.set_running("Updating selected OLD/actionable saved artifacts...")
        try:
            report = self._selected_update_service.execute_artifact_update_plan(
                self._latest_update_plan,
                selected_action_ids=selected_action_ids,
            )
        except Exception as exc:
            message = f"Failed to update selected artifacts: {exc!r}"
            self.status_message.emit(message)
            dialog.set_terminal_report(message)
            QMessageBox.critical(self, "Selected Artifact Update Failed", message)
            return

        dialog.set_terminal_report(selected_execution_report_text(report))
        self.status_message.emit("Selected artifact update execution complete")
        self.refresh()

    def _checked_artifacts_for_update(self) -> list[SavedArtifactColumn]:
        selected: list[SavedArtifactColumn] = []
        seen: set[str] = set()
        for column in self._checked_columns():
            key = self._artifact_column_key(column)
            if key in seen:
                continue
            selected.append(column)
            seen.add(key)
        return selected

    def _artifact_update_ref(self, column: SavedArtifactColumn) -> SelectedArtifactUpdateRef:
        if self._market is None:
            raise RuntimeError("Cannot build selected artifact update reference without a selected market.")
        return SelectedArtifactUpdateRef(
            family=column.family,
            exchange=self._market.exchange,
            market_type=self._market.market_type,
            symbol=self._market.symbol,
            timeframe=self._market.timeframe,
            artifact_path=column.path,
            tool_key=column.tool_key,
            instance_key=column.instance_key,
            display_name=self._artifact_display_name(column),
        )

    def _artifact_display_name(self, column: SavedArtifactColumn) -> str:
        return f"{column.family[:-1].capitalize()} - {column.tool_title} - {column.instance_key}"

    def _apply_artifact_update_plan(self, plan: SelectedArtifactUpdatePlan) -> None:
        items_by_path: dict[str, SelectedArtifactUpdatePlanItem] = {}
        for plan_item in plan.items:
            key = self._artifact_plan_item_path_key(plan_item)
            if key:
                items_by_path[key] = plan_item

        self._list.blockSignals(True)
        for row in range(self._list.count()):
            item = self._list.item(row)
            column = item.data(Qt.UserRole)
            if not isinstance(column, SavedArtifactColumn):
                continue
            plan_item = items_by_path.get(self._artifact_column_key(column))
            if plan_item is None:
                self._set_artifact_item_update_state(item, None, False, None)
            else:
                self._set_artifact_item_update_state(
                    item,
                    plan_item.status,
                    plan_item.actionable,
                    plan_item.item_id,
                )
        self._list.blockSignals(False)

    def _set_artifact_item_update_state(
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

    def _checked_actionable_artifact_action_ids(self) -> tuple[str, ...]:
        if self._latest_update_plan is None:
            return ()
        checked_item_ids = self._checked_actionable_artifact_item_ids()
        if not checked_item_ids:
            return ()
        return tuple(
            action.action_id
            for action in self._latest_update_plan.actions
            if action.item_id in checked_item_ids
        )

    def _checked_actionable_artifact_item_ids(self) -> set[str]:
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

    def _artifact_action_labels(self, action_ids: tuple[str, ...]) -> list[str]:
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

    def _artifact_column_key(self, column: SavedArtifactColumn) -> str:
        return Path(column.path).as_posix()

    def _artifact_plan_item_path_key(self, plan_item: SelectedArtifactUpdatePlanItem) -> str:
        raw_path = plan_item.metadata.get("artifact_path")
        if raw_path is None:
            return ""
        return Path(str(raw_path)).as_posix()

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
