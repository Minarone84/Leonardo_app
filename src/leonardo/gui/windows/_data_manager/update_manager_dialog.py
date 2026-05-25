from __future__ import annotations

from typing import Mapping, Optional

from PySide6.QtCore import Qt, Signal
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

from leonardo.data.historical.data_manager_update_service import (
    DataManagerUpdateAction,
    DataManagerUpdateExecutionReport,
    DataManagerUpdatePlan,
    DataManagerUpdatePlanItem,
)


_EXECUTABLE_ACTION_TYPES = {"regenerate_artifact", "rebuild_analysis_database"}


class DataManagerUpdatePlanDialog(QDialog):
    """Display and confirm recipe-collection Data Manager update plans.

    The dialog is presentation-only. It renders a plan produced by the
    data-layer update service, emits selected execution intent, and renders the
    returned execution report. It does not classify freshness, inspect metadata,
    regenerate artifacts, rebuild databases, or mutate storage.
    """

    execute_selected_requested = Signal(object)  # tuple[str, ...]
    execute_all_requested = Signal()
    status_message = Signal(str)

    def __init__(
        self,
        *,
        plan: DataManagerUpdatePlan,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(plan, DataManagerUpdatePlan):
            raise TypeError("DataManagerUpdatePlanDialog requires a DataManagerUpdatePlan")

        self._plan = plan
        self._items_by_id = {item.item_id: item for item in plan.items}
        self._actions_by_id = {action.action_id: action for action in plan.actions}
        self._action_items: dict[str, QListWidgetItem] = {}

        self.setWindowTitle("Data Manager Update Plan")
        self.resize(1120, 760)
        self.setMinimumSize(980, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._summary_label = QLabel(self._summary_text(plan), self)
        self._summary_label.setWordWrap(True)
        root.addWidget(self._summary_label)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        items_group = QGroupBox("Plan Items", self)
        items_layout = QVBoxLayout(items_group)
        items_layout.setContentsMargins(8, 12, 8, 8)
        self._items_text = QPlainTextEdit(items_group)
        self._items_text.setReadOnly(True)
        self._items_text.setPlainText(self._plan_items_text(plan))
        items_layout.addWidget(self._items_text, 1)
        body.addWidget(items_group, 5)

        actions_group = QGroupBox("Planned Actions", self)
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.setContentsMargins(8, 12, 8, 8)

        self._action_list = QListWidget(actions_group)
        self._action_list.setWordWrap(True)
        self._action_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._action_list.setUniformItemSizes(False)
        actions_layout.addWidget(self._action_list, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        actions_layout.addLayout(action_row)

        self._execute_selected_button = QPushButton("Execute Selected", actions_group)
        self._execute_selected_button.clicked.connect(self._execute_selected)
        action_row.addWidget(self._execute_selected_button)

        self._execute_all_button = QPushButton("Execute All Actionable", actions_group)
        self._execute_all_button.clicked.connect(self._execute_all)
        action_row.addWidget(self._execute_all_button)

        body.addWidget(actions_group, 5)

        report_group = QGroupBox("Execution Report", self)
        report_layout = QVBoxLayout(report_group)
        report_layout.setContentsMargins(8, 12, 8, 8)
        self._report_text = QPlainTextEdit(report_group)
        self._report_text.setReadOnly(True)
        self._report_text.setPlaceholderText("Execute selected actions to see results.")
        report_layout.addWidget(self._report_text, 1)
        root.addWidget(report_group, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._populate_actions()
        self._refresh_buttons()

    def plan(self) -> DataManagerUpdatePlan:
        """Return the plan currently displayed by the dialog."""
        return self._plan

    def set_execution_report(self, report: DataManagerUpdateExecutionReport) -> None:
        """Render an execution report returned by the data-layer update service."""
        if not isinstance(report, DataManagerUpdateExecutionReport):
            raise TypeError("set_execution_report() requires a DataManagerUpdateExecutionReport")
        self._report_text.setPlainText(self._execution_report_text(report))
        self.status_message.emit(
            "Data Manager update finished: "
            f"{report.summary.get('completed', 0)} completed, "
            f"{report.summary.get('failed', 0)} failed, "
            f"{report.summary.get('skipped', 0)} skipped, "
            f"{report.summary.get('blocked', 0)} blocked"
        )

    def _populate_actions(self) -> None:
        self._action_list.clear()
        self._action_items.clear()

        if not self._plan.actions:
            item = QListWidgetItem("No update actions are planned.", self._action_list)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            return

        for action in self._plan.actions:
            executable = self._is_executable_action(action)
            label = self._action_label(action, executable=executable)
            item = QListWidgetItem(label, self._action_list)
            item.setData(Qt.ItemDataRole.UserRole, action.action_id)
            item.setToolTip(action.reason)
            if executable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._action_items[action.action_id] = item

    def _refresh_buttons(self) -> None:
        executable_count = sum(
            1 for action in self._plan.actions if self._is_executable_action(action)
        )
        self._execute_selected_button.setEnabled(executable_count > 0)
        self._execute_all_button.setEnabled(executable_count > 0)

    def _execute_selected(self) -> None:
        action_ids = self.selected_action_ids()
        if not action_ids:
            QMessageBox.information(
                self,
                "Data Manager Update",
                "No executable update actions selected.",
            )
            return
        if not self._confirm_execution(action_ids=action_ids, all_actionable=False):
            return
        self.execute_selected_requested.emit(action_ids)

    def _execute_all(self) -> None:
        action_ids = tuple(
            action.action_id
            for action in self._plan.actions
            if self._is_executable_action(action)
        )
        if not action_ids:
            QMessageBox.information(
                self,
                "Data Manager Update",
                "No executable update actions are available.",
            )
            return
        if not self._confirm_execution(action_ids=action_ids, all_actionable=True):
            return
        self.execute_all_requested.emit()

    def selected_action_ids(self) -> tuple[str, ...]:
        """Return checked executable action ids in plan order."""
        action_ids: list[str] = []
        for action in self._plan.actions:
            item = self._action_items.get(action.action_id)
            if item is None or not self._is_executable_action(action):
                continue
            if item.checkState() == Qt.CheckState.Checked:
                action_ids.append(action.action_id)
        return tuple(action_ids)

    def _confirm_execution(
        self,
        *,
        action_ids: tuple[str, ...],
        all_actionable: bool,
    ) -> bool:
        selected_actions = [
            self._actions_by_id[action_id]
            for action_id in action_ids
            if action_id in self._actions_by_id
        ]
        regenerate_count = sum(
            1 for action in selected_actions if action.action_type == "regenerate_artifact"
        )
        rebuild_count = sum(
            1
            for action in selected_actions
            if action.action_type == "rebuild_analysis_database"
        )
        scope = "all executable actions" if all_actionable else "selected actions"
        answer = QMessageBox.question(
            self,
            "Execute Data Manager Update",
            (
                f"Execute {len(action_ids)} {scope}?\n\n"
                f"Artifact regenerations: {regenerate_count}\n"
                f"Analysis Database rebuilds: {rebuild_count}\n\n"
                "Execution writes derived artifacts and materialized database outputs "
                "through data-layer update services."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _is_executable_action(self, action: DataManagerUpdateAction) -> bool:
        if action.blocked or action.action_type not in _EXECUTABLE_ACTION_TYPES:
            return False
        item = self._items_by_id.get(action.target_item_id)
        return item is None or item.actionability == "actionable"

    def _action_label(
        self,
        action: DataManagerUpdateAction,
        *,
        executable: bool,
    ) -> str:
        item = self._items_by_id.get(action.target_item_id)
        item_status = "" if item is None else f" [{item.status}]"
        dependency_text = ""
        if action.depends_on_actions:
            dependency_text = f"\nDepends on: {', '.join(action.depends_on_actions)}"
        executable_text = "Executable" if executable else "Not executable"
        return (
            f"{action.label}{item_status}\n"
            f"{action.action_type} - {executable_text}\n"
            f"Reason: {action.reason}"
            f"{dependency_text}"
        )

    def _summary_text(self, plan: DataManagerUpdatePlan) -> str:
        market = plan.market
        market_text = " / ".join(
            str(market.get(key, ""))
            for key in ("exchange", "market_type", "symbol", "timeframe")
        )
        summary = plan.summary
        return (
            f"Collection: {plan.target_display_name or plan.target_id}\n"
            f"Collection ID: {plan.target_id}\n"
            f"Dataset: {market_text}\n"
            f"Linked database: {plan.source_database_id or '(none)'}\n"
            f"Current: {summary.get('current', 0)} | Missing: {summary.get('missing', 0)} | "
            f"Stale: {summary.get('stale', 0)} | Unknown: {summary.get('freshness_unknown', 0)} | "
            f"Blocked: {summary.get('blocked', 0)} | Needs rebuild: {summary.get('needs_rebuild', 0)}"
        )

    def _plan_items_text(self, plan: DataManagerUpdatePlan) -> str:
        lines: list[str] = []
        for item in plan.items:
            lines.extend(self._plan_item_lines(item))
            lines.append("")
        if plan.blockers:
            lines.append("Blockers:")
            lines.extend(f"- {blocker.message}" for blocker in plan.blockers)
            lines.append("")
        if plan.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in plan.warnings)
        return "\n".join(lines).strip()

    def _plan_item_lines(self, item: DataManagerUpdatePlanItem) -> list[str]:
        lines = [
            f"{item.item_type}: {item.display_name}",
            f"Status: {item.status}",
            f"Actionability: {item.actionability}",
        ]
        if item.reasons:
            lines.append("Reasons:")
            lines.extend(f"- {reason}" for reason in item.reasons[:6])
            if len(item.reasons) > 6:
                lines.append(f"... {len(item.reasons) - 6} more")
        return lines

    def _execution_report_text(self, report: DataManagerUpdateExecutionReport) -> str:
        summary = report.summary
        lines = [
            f"Report ID: {report.report_id}",
            f"Plan ID: {report.plan_id}",
            f"Started: {report.started_at_utc}",
            f"Finished: {report.finished_at_utc or '(not finished)'}",
            "",
            f"Requested: {summary.get('requested', 0)}",
            f"Completed: {summary.get('completed', 0)}",
            f"Skipped: {summary.get('skipped', 0)}",
            f"Failed: {summary.get('failed', 0)}",
            f"Blocked: {summary.get('blocked', 0)}",
        ]
        if report.results:
            lines.extend(["", "Action results:"])
            for result in report.results:
                lines.append(f"- {result.action_id}: {result.status} - {result.message}")
                reason = _metadata_reason(result.metadata)
                if reason:
                    lines.append(f"  Reason: {reason}")
                if result.error:
                    lines.append(f"  Error: {result.error}")
        if report.blockers:
            lines.extend(["", "Blockers:"])
            lines.extend(f"- {blocker.message}" for blocker in report.blockers)
        if report.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {warning}" for warning in report.warnings)
        return "\n".join(lines)


def _metadata_reason(metadata: Mapping[str, object]) -> str:
    value = metadata.get("reason")
    return str(value or "").strip()
