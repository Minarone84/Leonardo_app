from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


_DATASET_KEYS = ("exchange", "market_type", "symbol", "timeframe")


class HistoricalNotebookWindow(QMainWindow):
    """GUI-only notebook shell for Historical Workspace analysis.

    This window deliberately does not save, load, or assign notebook data.
    Persistence and Workspace Snapshot linkage are implemented by a later
    notebook feature phase. For now, the window provides the chart-oriented
    note-taking structure that those future workflows will populate.
    """

    refresh_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historical Notebook")
        self.resize(980, 720)
        self.setMinimumSize(760, 520)

        self._chart_tab_indexes: dict[str, int] = {}
        self._chart_tab_labels: dict[str, str] = {}

        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel("Notebook name", root)
        title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_row.addWidget(title_label)

        self._name_edit = QLineEdit(root)
        self._name_edit.setObjectName("historicalNotebookNameEdit")
        self._name_edit.setPlaceholderText("Untitled notebook")
        self._name_edit.setText("Untitled notebook")
        header_row.addWidget(self._name_edit, 2)

        self._assigned_snapshot_label = QLabel("Assigned snapshot: Not assigned", root)
        self._assigned_snapshot_label.setObjectName("historicalNotebookAssignedSnapshotLabel")
        self._assigned_snapshot_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_row.addWidget(self._assigned_snapshot_label, 2)

        self._refresh_button = QPushButton("Refresh Charts", root)
        self._refresh_button.setObjectName("historicalNotebookRefreshChartsButton")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        header_row.addWidget(self._refresh_button)

        layout.addLayout(header_row)

        self._status_label = QLabel("Notebook shell ready.", root)
        self._status_label.setObjectName("historicalNotebookStatusLabel")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._chart_tabs = QTabWidget(root)
        self._chart_tabs.setObjectName("historicalNotebookChartTabs")
        self._chart_tabs.setTabsClosable(False)
        self._chart_tabs.setMovable(True)
        layout.addWidget(self._chart_tabs, 1)

    def refresh_from_chart_options(self, chart_options: Sequence[Mapping[str, Any]]) -> None:
        """Refresh chart tabs from current embedded chart descriptors.

        Existing tabs are preserved so notes do not disappear when a chart is
        temporarily closed. Tabs whose chart is no longer active are marked red.
        """
        active_keys: set[str] = set()

        for raw_option in chart_options:
            option = dict(raw_option)
            chart_key = self._chart_key(option)
            if not chart_key:
                continue

            active_keys.add(chart_key)
            label = self._chart_tab_label(option)
            if chart_key not in self._chart_tab_indexes:
                self._add_chart_tab(chart_key, label)
            else:
                self._chart_tab_labels[chart_key] = label
                self._refresh_tab_indexes()
                index = self._chart_tab_indexes.get(chart_key)
                if index is not None:
                    self._chart_tabs.setTabText(index, label)
            self._mark_chart_tab_active(chart_key, True)

        for chart_key in list(self._chart_tab_indexes.keys()):
            self._mark_chart_tab_active(chart_key, chart_key in active_keys)

        if not self._chart_tab_indexes:
            self._status_label.setText("No embedded charts are currently available.")
        else:
            self._status_label.setText(
                f"Notebook tracks {len(self._chart_tab_indexes)} chart tab(s); "
                f"{len(active_keys)} currently active."
            )

    def _add_chart_tab(self, chart_key: str, label: str) -> None:
        inner_tabs = QTabWidget(self._chart_tabs)
        inner_tabs.setObjectName("historicalNotebookInnerTabs")

        inner_tabs.addTab(self._new_text_editor("Notes"), "Notes")
        inner_tabs.addTab(self._new_text_editor("Trades"), "Trades")
        inner_tabs.addTab(self._new_text_editor("Point of Interest"), "Point of Interest")

        index = self._chart_tabs.addTab(inner_tabs, label)
        self._chart_tab_indexes[chart_key] = index
        self._chart_tab_labels[chart_key] = label
        self._mark_chart_tab_active(chart_key, True)

    def _new_text_editor(self, placeholder: str) -> QPlainTextEdit:
        editor = QPlainTextEdit(self._chart_tabs)
        editor.setPlaceholderText(placeholder)
        return editor

    def _mark_chart_tab_active(self, chart_key: str, active: bool) -> None:
        self._refresh_tab_indexes()
        index = self._chart_tab_indexes.get(chart_key)
        if index is None:
            return

        if active:
            self._chart_tabs.tabBar().setTabTextColor(index, QColor("#d8d8d8"))
            self._chart_tabs.setTabToolTip(index, "Chart is currently active.")
            return

        self._chart_tabs.tabBar().setTabTextColor(index, QColor("#ff5555"))
        self._chart_tabs.setTabToolTip(
            index,
            "Chart is not currently active; notes are preserved.",
        )

    def _refresh_tab_indexes(self) -> None:
        for index in range(self._chart_tabs.count()):
            label = self._chart_tabs.tabText(index)
            for chart_key, stored_label in list(self._chart_tab_labels.items()):
                if label == stored_label:
                    self._chart_tab_indexes[chart_key] = index

    def _chart_key(self, option: Mapping[str, Any]) -> str:
        dataset = option.get("dataset", {}) or {}
        if not isinstance(dataset, Mapping):
            dataset = {}

        position = str(option.get("position", "") or "").strip()
        parts = [position]
        parts.extend(str(dataset.get(key, "") or "").strip().lower() for key in _DATASET_KEYS)
        if not any(parts):
            return ""
        return "|".join(parts)

    def _chart_tab_label(self, option: Mapping[str, Any]) -> str:
        dataset = option.get("dataset", {}) or {}
        if not isinstance(dataset, Mapping):
            dataset = {}

        position = str(option.get("position", "") or "").strip()
        symbol = str(dataset.get("symbol", "") or "").strip()
        timeframe = str(dataset.get("timeframe", "") or "").strip()
        exchange = str(dataset.get("exchange", "") or "").strip()
        market_type = str(dataset.get("market_type", "") or "").strip()

        title = " ".join(part for part in (symbol, timeframe) if part).strip()
        if not title:
            title = str(option.get("label", "") or "").strip() or "Chart"

        prefix = f"#{position}" if position else "Chart"
        detail = " / ".join(part for part in (exchange, market_type) if part)
        return f"{prefix} — {title}" + (f" ({detail})" if detail else "")
