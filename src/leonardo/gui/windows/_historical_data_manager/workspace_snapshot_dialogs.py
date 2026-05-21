from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshot,
)
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PresetCompatibilityReport,
    format_compatibility_report,
    ready_report,
)


def _dataset_text(data: Mapping[str, Any]) -> str:
    parts = [
        str(data.get("exchange", "") or "").strip(),
        str(data.get("market_type", "") or "").strip(),
        str(data.get("symbol", "") or "").strip(),
        str(data.get("timeframe", "") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or "Unknown dataset"


def _workspace_mode_text(workspace: Mapping[str, Any]) -> str:
    mode = str(workspace.get("visualization_mode", "") or "").strip()
    if mode == "fit_8":
        return "Fit 8"
    return "Scroll 4"


def _study_count(charts: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for chart in charts:
        studies = chart.get("studies", []) or []
        count += (
            len(studies)
            if isinstance(studies, Sequence) and not isinstance(studies, (str, bytes))
            else 0
        )
    return count


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
            f"    {index}. {display_name} | {family}/{tool_key} | "
            f"pane={pane_target} | params: {params_text}"
        )
    return lines


def _chart_recap_lines(charts: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for chart in sorted(charts, key=lambda item: int(item.get("position", 0) or 0)):
        position = int(chart.get("position", 0) or 0)
        dataset = chart.get("dataset", {}) or {}
        studies = chart.get("studies", []) or []
        study_items = (
            studies
            if isinstance(studies, Sequence) and not isinstance(studies, (str, bytes))
            else []
        )
        lines.append(
            f"Position {position}: {_dataset_text(dataset if isinstance(dataset, Mapping) else {})} "
            f"({len(study_items)} study/studies)"
        )
        lines.extend(_study_recap_lines(study_items) or ["    No studies."])
    return lines


class SaveWorkspaceSnapshotDialog(QDialog):
    """Collect user metadata and show a workspace snapshot recap before saving."""

    def __init__(
        self,
        *,
        snapshot_payload: Mapping[str, Any],
        detached_reserved_slot_count: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot_payload = dict(snapshot_payload)
        self._detached_reserved_slot_count = int(detached_reserved_slot_count)

        self.setWindowTitle("Save Workspace Snapshot")
        self.resize(860, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form_group = QGroupBox("Snapshot Details", self)
        form = QFormLayout(form_group)
        form.setContentsMargins(10, 14, 10, 10)
        form.setSpacing(8)

        self._name_edit = QLineEdit(form_group)
        self._name_edit.setPlaceholderText("Workspace snapshot name")
        self._name_edit.textChanged.connect(self._refresh_save_enabled)
        form.addRow("Name", self._name_edit)

        self._description_edit = QTextEdit(form_group)
        self._description_edit.setPlaceholderText("Description")
        self._description_edit.setFixedHeight(90)
        form.addRow("Description", self._description_edit)
        root.addWidget(form_group)

        recap_group = QGroupBox("Workspace Recap", self)
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
        """Return the user-facing workspace snapshot name."""
        return self._name_edit.text().strip()

    def description(self) -> str:
        """Return the optional workspace snapshot description."""
        return self._description_edit.toPlainText().strip()

    def _refresh_recap(self) -> None:
        workspace = self._snapshot_payload.get("workspace", {}) or {}
        charts = self._snapshot_payload.get("charts", []) or []
        chart_items = (
            charts
            if isinstance(charts, Sequence) and not isinstance(charts, (str, bytes))
            else []
        )
        lines = [
            f"Visualization mode: {_workspace_mode_text(workspace if isinstance(workspace, Mapping) else {})}",
            f"Embedded chart count: {len(chart_items)}",
            f"Total study count: {_study_count(chart_items)}",
        ]
        if self._detached_reserved_slot_count:
            lines.append(
                "Detached charts are not included in this snapshot; "
                f"{self._detached_reserved_slot_count} dock-back slot(s) are reserved."
            )
        lines.extend(["", "Chart Recap:"])
        lines.extend(_chart_recap_lines(chart_items) or ["No embedded charts."])
        self._recap_text.setPlainText("\n".join(lines))

    def _refresh_save_enabled(self) -> None:
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is None:
            return
        charts = self._snapshot_payload.get("charts", []) or []
        save_button.setEnabled(bool(self.display_name()) and bool(charts))


class LoadWorkspaceSnapshotDialog(QDialog):
    """Collect snapshot and workspace load-mode choices for loading."""

    def __init__(
        self,
        *,
        snapshots: Sequence[HistoricalWorkspaceSnapshot],
        current_chart_count: int,
        available_slot_count: int,
        detached_reserved_slot_count: int = 0,
        compatibility_provider: Callable[[HistoricalWorkspaceSnapshot, str], PresetCompatibilityReport] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshots_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        self._current_chart_count = int(current_chart_count)
        self._available_slot_count = int(available_slot_count)
        self._detached_reserved_slot_count = int(detached_reserved_slot_count)
        self._compatibility_provider = compatibility_provider
        self._current_compatibility_report = ready_report()

        self.setWindowTitle("Load Workspace Snapshot")
        self.resize(980, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        list_group = QGroupBox("Saved Workspace Snapshots", self)
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(10, 14, 10, 10)
        list_layout.setSpacing(8)

        self._snapshot_list = QListWidget(list_group)
        self._snapshot_list.setWordWrap(True)
        self._snapshot_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._snapshot_list.currentItemChanged.connect(lambda *_: self._refresh_details())
        list_layout.addWidget(self._snapshot_list, 1)
        body.addWidget(list_group, 4)

        detail_group = QGroupBox("Snapshot Details", self)
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(10, 14, 10, 10)
        detail_layout.setSpacing(8)

        self._detail_text = QPlainTextEdit(detail_group)
        self._detail_text.setReadOnly(True)
        detail_layout.addWidget(self._detail_text, 1)

        mode_group = QGroupBox("Load Mode", detail_group)
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(10, 14, 10, 10)
        mode_layout.setSpacing(6)

        self._replace_radio = QRadioButton("Replace current workspace", mode_group)
        self._load_into_current_radio = QRadioButton("Load into current workspace", mode_group)
        self._replace_radio.setChecked(True)
        self._replace_radio.toggled.connect(lambda *_: self._refresh_details())
        self._load_into_current_radio.toggled.connect(lambda *_: self._refresh_details())
        mode_layout.addWidget(self._replace_radio)
        mode_layout.addWidget(self._load_into_current_radio)
        detail_layout.addWidget(mode_group)

        self._slot_status_label = QLabel(detail_group)
        self._slot_status_label.setWordWrap(True)
        detail_layout.addWidget(self._slot_status_label)

        self._compatibility_text = QPlainTextEdit(detail_group)
        self._compatibility_text.setReadOnly(True)
        self._compatibility_text.setMaximumHeight(150)
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
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._populate_snapshots(snapshots)
        self._refresh_details()

    def selected_snapshot_id(self) -> str:
        """Return the storage identity for the selected workspace snapshot."""
        item = self._snapshot_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def load_mode(self) -> str:
        """Return the selected workspace snapshot load behavior."""
        if self._load_into_current_radio.isChecked():
            return "load_into_current"
        return "replace"

    def compatibility_report(self) -> PresetCompatibilityReport:
        """Return the latest compatibility report displayed by the dialog."""
        return self._current_compatibility_report

    def _populate_snapshots(
        self,
        snapshots: Sequence[HistoricalWorkspaceSnapshot],
    ) -> None:
        self._snapshot_list.clear()
        for snapshot in snapshots:
            item = QListWidgetItem(
                f"{snapshot.display_name}\n{snapshot.description}\n"
                f"{len(snapshot.charts)} chart(s), {_study_count(snapshot.charts)} study/studies",
                self._snapshot_list,
            )
            item.setData(Qt.ItemDataRole.UserRole, snapshot.snapshot_id)
        if self._snapshot_list.count() > 0:
            self._snapshot_list.setCurrentRow(0)

    def _selected_snapshot(self) -> HistoricalWorkspaceSnapshot | None:
        snapshot_id = self.selected_snapshot_id()
        if not snapshot_id:
            return None
        return self._snapshots_by_id.get(snapshot_id)

    def _refresh_details(self) -> None:
        snapshot = self._selected_snapshot()
        load_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)

        if snapshot is None:
            self._detail_text.setPlainText("Select a saved workspace snapshot.")
            self._slot_status_label.setText("")
            self._current_compatibility_report = ready_report()
            self._compatibility_text.setPlainText("")
            if load_button is not None:
                load_button.setEnabled(False)
            return

        lines = [
            f"Name: {snapshot.display_name}",
            f"Description: {snapshot.description}",
            f"Created: {snapshot.created_at_ms}",
            f"Updated: {snapshot.updated_at_ms}",
            f"Workspace mode: {_workspace_mode_text(snapshot.workspace)}",
            f"Chart count: {len(snapshot.charts)}",
            f"Total study count: {_study_count(snapshot.charts)}",
            "",
            "Chart Recap:",
        ]
        lines.extend(_chart_recap_lines(snapshot.charts))
        self._detail_text.setPlainText("\n".join(lines))

        if self.load_mode() == "load_into_current":
            required = self._current_chart_count + len(snapshot.charts)
            self._slot_status_label.setText(
                f"Load into current workspace requires {required} of "
                f"{self._available_slot_count} non-reserved slot(s)."
            )
        elif self._detached_reserved_slot_count:
            self._slot_status_label.setText(
                "Replace mode is blocked while detached charts reserve "
                f"{self._detached_reserved_slot_count} dock-back slot(s)."
            )
        else:
            self._slot_status_label.setText(
                "Replace mode will remove current embedded charts first."
            )

        self._current_compatibility_report = self._compatibility_report_for_snapshot(snapshot)
        self._compatibility_text.setPlainText(
            format_compatibility_report(self._current_compatibility_report)
        )
        if load_button is not None:
            load_button.setEnabled(self._current_compatibility_report.can_load)

    def _compatibility_report_for_snapshot(
        self,
        snapshot: HistoricalWorkspaceSnapshot,
    ) -> PresetCompatibilityReport:
        if self._compatibility_provider is None:
            return ready_report()
        return self._compatibility_provider(snapshot, self.load_mode())
