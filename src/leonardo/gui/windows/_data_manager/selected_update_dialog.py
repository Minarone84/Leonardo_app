from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SelectedUpdateDialog(QDialog):
    """Present selected-item update preflight, running, and terminal report states."""

    confirmed = Signal()

    def __init__(
        self,
        *,
        title: str,
        summary: str,
        item_names: Iterable[str],
        confirm_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._summary_label = QLabel(summary, self)
        self._summary_label.setWordWrap(True)
        root.addWidget(self._summary_label)

        self._item_list = QListWidget(self)
        for name in item_names:
            QListWidgetItem(str(name), self._item_list)
        root.addWidget(self._item_list, 1)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._report = QPlainTextEdit(self)
        self._report.setReadOnly(True)
        self._report.setPlaceholderText("Result details will appear after the operation finishes.")
        root.addWidget(self._report, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._confirm_button = QPushButton(confirm_label, self)
        self._confirm_button.clicked.connect(self.confirmed.emit)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.clicked.connect(self.reject)
        self._ok_button = QPushButton("OK", self)
        self._ok_button.setEnabled(False)
        self._ok_button.clicked.connect(self.accept)
        button_row.addWidget(self._confirm_button)
        button_row.addWidget(self._cancel_button)
        button_row.addWidget(self._ok_button)
        root.addLayout(button_row)

    def set_running(self, message: str) -> None:
        """Switch to the synchronous running state without offering cancellation."""
        self._summary_label.setText(message)
        self._confirm_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._ok_button.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)

    def set_terminal_report(self, report_text: str) -> None:
        """Show the terminal report and enable acknowledgement."""
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._confirm_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._ok_button.setEnabled(True)
        self._ok_button.setDefault(True)
        self._report.setPlainText(report_text)


def selected_plan_report_text(plan: object) -> str:
    """Format a selected update plan without deriving policy in the GUI."""
    lines: list[str] = []
    summary = getattr(plan, "summary", {}) or {}
    if summary:
        lines.append("Summary:")
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    lines.append("Items:")
    for item in getattr(plan, "items", ()) or ():
        lines.extend(_plan_item_lines(item))

    actions = tuple(getattr(plan, "actions", ()) or ())
    lines.append("")
    lines.append(f"Executable actions: {len(actions)}")
    for action in actions:
        label = str(getattr(action, "label", "") or getattr(action, "action_id", ""))
        reason = str(getattr(action, "reason", "") or "")
        lines.append(f"- {label}: {reason}")
    return "\n".join(lines).strip()


def selected_execution_report_text(report: object) -> str:
    """Format selected update execution results for GUI display."""
    lines: list[str] = []
    summary = getattr(report, "summary", {}) or {}
    if summary:
        lines.append("Summary:")
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    lines.append("Results:")
    for result in getattr(report, "results", ()) or ():
        status = str(getattr(result, "status", "") or "unknown").upper()
        message = str(getattr(result, "message", "") or "")
        action_id = str(getattr(result, "action_id", "") or "")
        lines.append(f"- {status} {action_id}: {message}")
        error = str(getattr(result, "error", "") or "")
        if error:
            lines.append(f"  Error: {error}")
    return "\n".join(lines).strip()


def selected_update_preflight_text(
    *,
    selected_count: int,
    actionable_count: int | None = None,
    operation: str,
) -> str:
    if actionable_count is None:
        return f"{operation}\n\nSelected items: {selected_count}"
    skipped_count = max(0, selected_count - actionable_count)
    return (
        f"{operation}\n\n"
        f"Selected items: {selected_count}\n"
        f"Actionable OLD items: {actionable_count}\n"
        f"Skipped by latest plan: {skipped_count}"
    )


def _plan_item_lines(item: object) -> list[str]:
    display = str(getattr(item, "display_name", "") or getattr(item, "item_id", ""))
    status = str(getattr(item, "status", "") or "unknown").upper()
    actionable = "actionable" if bool(getattr(item, "actionable", False)) else "not actionable"
    reason = str(getattr(item, "reason", "") or "")
    lines = [f"- {display}: {status}, {actionable}. {reason}"]
    for warning in getattr(item, "warnings", ()) or ():
        lines.append(f"  Warning: {warning}")
    for blocker in getattr(item, "blockers", ()) or ():
        lines.append(f"  Blocker: {blocker}")
    return lines
