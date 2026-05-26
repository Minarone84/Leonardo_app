from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import time
import uuid
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QFontMetrics,
    QTextCharFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.notebook_store import (
    DEFAULT_POI_MARKER_OFFSET,
    DEFAULT_PT_LONG_MARKER_OFFSET,
    DEFAULT_PT_SHORT_MARKER_OFFSET,
    HISTORICAL_NOTEBOOK_OBJECT_TYPE,
    HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
    HistoricalNotebook,
    normalize_notebook_annotation_settings,
    normalize_notebook_chart_entry,
    notebook_chart_key,
)


_DATASET_KEYS = ("exchange", "market_type", "symbol", "timeframe")
_SECTION_NOTES = "notes"
_SECTION_TRADES = "trades"
_SECTION_POI = "points_of_interest"

_GOTO_COLUMN = 0
_ACTION_BUTTON_WIDTH = 58
_SUPPORTED_DATE_TIME_TEXT = "9999-12-31 23:59:59"
_POI_TITLE_COLUMN_WIDTH = 300

_NOTE_COLUMNS = ("Delete", "Date / Time", "Note")
_TRADE_COLUMNS = (
    "Go",
    "Delete",
    "Date / Time",
    "Direction",
    "Starting Price",
    "Target % Movement",
    "Closing Price",
    "Outcome",
    "Note",
)
_POI_COLUMNS = ("Go", "Delete", "Date / Time", "Title", "Description")


class _NotebookRichTextEdit(QTextEdit):
    focused = Signal(object)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit(self)


class HistoricalNotebookWindow(QMainWindow):
    """Editable GUI shell for Historical Workspace notebook content.

    The window owns only in-memory notebook editing and user interaction
    signals. Persistent storage, Workspace Snapshot assignment, chart lookup,
    and chart navigation are coordinated by HistoricalDataManagerWindow.
    """

    refresh_requested = Signal()
    save_requested = Signal()
    load_requested = Signal()
    assign_requested = Signal()
    goto_requested = Signal(str, object)
    poi_markers_changed = Signal()
    poi_overlay_requested = Signal(bool)
    close_save_requested = Signal(object)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historical Notebook")
        self.resize(1020, 760)
        self.setMinimumSize(800, 560)
        self._increase_window_font(point_delta=1)

        self._notebook_id: str | None = None
        self._created_at_ms: int | None = None
        self._updated_at_ms: int | None = None
        self._chart_entries_by_key: dict[str, dict[str, Any]] = {}
        self._active_chart_keys: set[str] = set()
        self._chart_tab_indexes: dict[str, int] = {}
        self._chart_tab_labels: dict[str, str] = {}
        self._tables_by_chart_key: dict[str, dict[str, QTableWidget]] = {}
        self._updating_tables = False
        self._syncing_from_tables = False
        self._suppress_notebook_change_signals = False
        self._suppress_next_close_autosave = False
        self._suppress_dirty = False
        self._dirty = False
        self._current_text_editor: QTextEdit | None = None

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
        self._name_edit.textChanged.connect(lambda *_args: self.mark_dirty())
        header_row.addWidget(self._name_edit, 2)

        self._assigned_snapshot_label = QLabel("Assigned snapshot: Not assigned", root)
        self._assigned_snapshot_label.setObjectName("historicalNotebookAssignedSnapshotLabel")
        self._assigned_snapshot_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header_row.addWidget(self._assigned_snapshot_label, 2)

        self._refresh_button = QPushButton("Refresh Charts", root)
        self._refresh_button.setObjectName("historicalNotebookRefreshChartsButton")
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        header_row.addWidget(self._refresh_button)

        self._save_button = QPushButton("Save", root)
        self._save_button.setObjectName("historicalNotebookSaveButton")
        self._save_button.clicked.connect(self.save_requested.emit)
        header_row.addWidget(self._save_button)

        self._load_button = QPushButton("Load", root)
        self._load_button.setObjectName("historicalNotebookLoadButton")
        self._load_button.clicked.connect(self.load_requested.emit)
        header_row.addWidget(self._load_button)

        self._assign_button = QPushButton("Manager", root)
        self._assign_button.setObjectName("historicalNotebookAssignButton")
        self._assign_button.clicked.connect(self.assign_requested.emit)
        header_row.addWidget(self._assign_button)

        layout.addLayout(header_row)

        description_label = QLabel("Description", root)
        description_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(description_label)

        self._description_edit = _NotebookRichTextEdit(root)
        self._description_edit.setObjectName("historicalNotebookDescriptionEdit")
        self._description_edit.setPlaceholderText("Notebook description")
        self._description_edit.setFixedHeight(72)
        self._register_rich_text_editor(self._description_edit)
        layout.addWidget(self._description_edit)

        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(8)

        self._show_poi_markers_check = QCheckBox("Show notebook markers on charts", root)
        self._show_poi_markers_check.setObjectName("historicalNotebookShowPoiMarkersCheck")
        self._show_poi_markers_check.toggled.connect(self._on_poi_overlay_toggled)
        tools_row.addWidget(self._show_poi_markers_check)

        tools_row.addWidget(QLabel("POI marker offset", root))
        self._poi_marker_offset_spin = QSpinBox(root)
        self._poi_marker_offset_spin.setObjectName("historicalNotebookPoiMarkerOffsetSpin")
        self._poi_marker_offset_spin.setRange(0, 240)
        self._poi_marker_offset_spin.setSuffix(" px")
        self._poi_marker_offset_spin.setValue(DEFAULT_POI_MARKER_OFFSET)
        self._poi_marker_offset_spin.valueChanged.connect(self._on_annotation_offset_changed)
        tools_row.addWidget(self._poi_marker_offset_spin)

        tools_row.addWidget(QLabel("PT Long marker offset", root))
        self._pt_long_marker_offset_spin = QSpinBox(root)
        self._pt_long_marker_offset_spin.setObjectName("historicalNotebookPtLongMarkerOffsetSpin")
        self._pt_long_marker_offset_spin.setRange(0, 240)
        self._pt_long_marker_offset_spin.setSuffix(" px")
        self._pt_long_marker_offset_spin.setValue(DEFAULT_PT_LONG_MARKER_OFFSET)
        self._pt_long_marker_offset_spin.valueChanged.connect(self._on_annotation_offset_changed)
        tools_row.addWidget(self._pt_long_marker_offset_spin)

        tools_row.addWidget(QLabel("PT Short marker offset", root))
        self._pt_short_marker_offset_spin = QSpinBox(root)
        self._pt_short_marker_offset_spin.setObjectName("historicalNotebookPtShortMarkerOffsetSpin")
        self._pt_short_marker_offset_spin.setRange(0, 240)
        self._pt_short_marker_offset_spin.setSuffix(" px")
        self._pt_short_marker_offset_spin.setValue(DEFAULT_PT_SHORT_MARKER_OFFSET)
        self._pt_short_marker_offset_spin.valueChanged.connect(self._on_annotation_offset_changed)
        tools_row.addWidget(self._pt_short_marker_offset_spin)
        tools_row.addStretch(1)
        layout.addLayout(tools_row)

        self._status_label = QLabel("Notebook ready.", root)
        self._status_label.setObjectName("historicalNotebookStatusLabel")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._chart_tabs = QTabWidget(root)
        self._chart_tabs.setObjectName("historicalNotebookChartTabs")
        self._chart_tabs.setTabsClosable(True)
        self._chart_tabs.setMovable(True)
        self._chart_tabs.tabCloseRequested.connect(self._on_chart_tab_close_requested)
        self._apply_bold_tab_font(self._chart_tabs)
        layout.addWidget(self._chart_tabs, 1)

    def _increase_window_font(self, *, point_delta: int) -> None:
        font = self.font()
        point_size = font.pointSize()
        if point_size > 0:
            font.setPointSize(point_size + int(point_delta))
        else:
            point_size_f = font.pointSizeF()
            if point_size_f > 0:
                font.setPointSizeF(point_size_f + float(point_delta))
            else:
                font.setPointSize(10 + int(point_delta))
        self.setFont(font)

    def _apply_bold_tab_font(self, tabs: QTabWidget) -> None:
        font = tabs.tabBar().font()
        font.setBold(True)
        tabs.tabBar().setFont(font)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._suppress_next_close_autosave:
            self._suppress_next_close_autosave = False
            super().closeEvent(event)
            return

        self.close_save_requested.emit(event)
        if not event.isAccepted():
            return
        super().closeEvent(event)

    def notebook_id(self) -> str | None:
        return self._notebook_id

    def is_dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, value: bool) -> None:
        self._dirty = bool(value)

    def mark_dirty(self) -> None:
        if self._suppress_dirty or self._updating_tables:
            return
        self.set_dirty(True)

    def mark_clean(self) -> None:
        self.set_dirty(False)

    def display_name(self) -> str:
        return str(self._name_edit.text() or "").strip() or "Untitled notebook"

    def description(self) -> str:
        return str(self._description_edit.toPlainText() or "")

    def description_html(self) -> str:
        return self._html_payload_for_editor(self._description_edit)

    def created_at_ms(self) -> int | None:
        return self._created_at_ms

    def chart_entries_payload(self) -> list[dict[str, Any]]:
        self._sync_all_entries_from_tables()
        return self._normalized_chart_entries_snapshot()

    def current_notebook(self) -> HistoricalNotebook:
        now_ms = int(time.time() * 1000)
        created = int(self._created_at_ms) if self._created_at_ms is not None else now_ms
        notebook_id = self._notebook_id or uuid.uuid4().hex
        return HistoricalNotebook(
            schema_version=HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
            object_type=HISTORICAL_NOTEBOOK_OBJECT_TYPE,
            notebook_id=notebook_id,
            content_hash="",
            display_name=self.display_name(),
            description=self.description(),
            description_html=self.description_html(),
            created_at_ms=created,
            updated_at_ms=now_ms,
            annotation_settings=self.annotation_settings_payload(),
            chart_entries=tuple(self.chart_entries_payload()),
        )

    def set_notebook(
        self,
        notebook: HistoricalNotebook,
        *,
        assigned_snapshot_label: str | None = None,
    ) -> None:
        """Replace in-memory editor state with a loaded notebook payload."""
        self._suppress_dirty = True
        try:
            self._notebook_id = notebook.notebook_id
            self._created_at_ms = notebook.created_at_ms
            self._updated_at_ms = notebook.updated_at_ms
            self._name_edit.setText(notebook.display_name)
            self._set_rich_text_content(
                self._description_edit,
                plain_text=notebook.description,
                html_text=getattr(notebook, "description_html", ""),
            )
            self._set_annotation_settings(notebook.annotation_settings)

            entries: dict[str, dict[str, Any]] = {}
            for raw_entry in notebook.chart_entries:
                entry = normalize_notebook_chart_entry(raw_entry)
                entries[str(entry["chart_key"])] = entry
            self._chart_entries_by_key = entries

            self.set_assigned_snapshot_label(assigned_snapshot_label)

            self._rebuild_chart_tabs()
            self._update_status()
        finally:
            self._suppress_dirty = False
        self.mark_clean()

    def mark_saved(self, notebook: HistoricalNotebook) -> None:
        self._suppress_dirty = True
        try:
            self._notebook_id = notebook.notebook_id
            self._created_at_ms = notebook.created_at_ms
            self._updated_at_ms = notebook.updated_at_ms
            self._name_edit.setText(notebook.display_name)
            self._set_rich_text_content(
                self._description_edit,
                plain_text=notebook.description,
                html_text=getattr(notebook, "description_html", ""),
            )
            self._set_annotation_settings(notebook.annotation_settings)
            self._update_status(prefix=f"Saved notebook: {notebook.display_name}.")
        finally:
            self._suppress_dirty = False
        self.mark_clean()

    def reset_notebook(
        self,
        *,
        status: str = "Notebook ready.",
        suppress_next_close_autosave: bool = False,
    ) -> None:
        """Clear editor state so the next save creates a new notebook identity."""
        self._suppress_dirty = True
        try:
            self._notebook_id = None
            self._created_at_ms = None
            self._updated_at_ms = None
            self._suppress_next_close_autosave = bool(suppress_next_close_autosave)
            self._chart_entries_by_key.clear()
            self._active_chart_keys.clear()
            self._chart_tab_labels.clear()
            self._tables_by_chart_key.clear()
            self._name_edit.setText("Untitled notebook")
            self._description_edit.clear()
            self._set_annotation_settings(None)
            self.set_assigned_snapshot_label(None)
            self._rebuild_chart_tabs()
            self._status_label.setText(status)
        finally:
            self._suppress_dirty = False
        self.mark_clean()

    def set_assigned_snapshot_label(self, label: str | None) -> None:
        resolved = str(label or "").strip()
        if resolved:
            self._assigned_snapshot_label.setText(f"Assigned snapshot: {resolved}")
        else:
            self._assigned_snapshot_label.setText("Assigned snapshot: Not assigned")

    def _set_annotation_settings(self, settings: Mapping[str, Any] | None) -> None:
        normalized = normalize_notebook_annotation_settings(settings)
        for spin, key in (
            (self._poi_marker_offset_spin, "poi_marker_offset"),
            (self._pt_long_marker_offset_spin, "pt_long_marker_offset"),
            (self._pt_short_marker_offset_spin, "pt_short_marker_offset"),
        ):
            spin.blockSignals(True)
            try:
                spin.setValue(int(normalized[key]))
            finally:
                spin.blockSignals(False)

    def refresh_from_chart_options(self, chart_options: Sequence[Mapping[str, Any]]) -> None:
        """Refresh chart tabs from current embedded chart descriptors.

        Notebook chart identity is dataset-based. The workspace position is
        display metadata only and is stored as last_seen_position.
        """
        self._sync_all_entries_from_tables()
        before = self._normalized_chart_entries_snapshot()
        active_keys: set[str] = set()

        for raw_option in chart_options:
            option = dict(raw_option)
            entry = self._entry_from_chart_option(option)
            if entry is None:
                continue

            chart_key = str(entry["chart_key"])
            active_keys.add(chart_key)

            existing = self._chart_entries_by_key.get(chart_key)
            if existing is None:
                self._chart_entries_by_key[chart_key] = entry
            else:
                existing["dataset"] = dict(entry["dataset"])
                existing["last_seen_position"] = entry.get("last_seen_position")

            self._chart_tab_labels[chart_key] = self._chart_tab_label(
                self._chart_entries_by_key[chart_key]
            )

        self._active_chart_keys = active_keys
        self._rebuild_chart_tabs()
        self._update_status()
        if before != self._normalized_chart_entries_snapshot():
            self.mark_dirty()

    def poi_markers_enabled(self) -> bool:
        return bool(self._show_poi_markers_check.isChecked())

    def annotation_settings_payload(self) -> dict[str, int]:
        return normalize_notebook_annotation_settings(
            {
                "poi_marker_offset": self._poi_marker_offset_spin.value(),
                "pt_long_marker_offset": self._pt_long_marker_offset_spin.value(),
                "pt_short_marker_offset": self._pt_short_marker_offset_spin.value(),
            }
        )

    def annotation_marker_offsets(self) -> dict[str, int]:
        return self.annotation_settings_payload()

    def poi_markers_by_chart_key(self) -> dict[str, list[dict[str, Any]]]:
        self._sync_entries_for_marker_collection()
        return self._build_poi_markers_by_chart_key_from_entries()

    def pt_markers_by_chart_key(self) -> dict[str, list[dict[str, Any]]]:
        self._sync_entries_for_marker_collection()
        return self._build_pt_markers_by_chart_key_from_entries()

    def _sync_entries_for_marker_collection(self) -> None:
        if self._syncing_from_tables:
            return
        old_syncing = self._syncing_from_tables
        old_suppress = self._suppress_notebook_change_signals
        self._syncing_from_tables = True
        self._suppress_notebook_change_signals = True
        try:
            self._sync_all_entries_from_tables()
        finally:
            self._suppress_notebook_change_signals = old_suppress
            self._syncing_from_tables = old_syncing

    def _build_poi_markers_by_chart_key_from_entries(self) -> dict[str, list[dict[str, Any]]]:
        markers: dict[str, list[dict[str, Any]]] = {}
        for chart_key, entry in self._chart_entries_by_key.items():
            points = entry.get("points_of_interest", []) or []
            chart_markers: list[dict[str, Any]] = []
            for point in points:
                if not isinstance(point, Mapping):
                    continue
                ts_ms = point.get("ts_ms")
                if not isinstance(ts_ms, int):
                    continue
                title = str(point.get("title", "") or "").strip()
                description = str(point.get("description", "") or "").strip()
                chart_markers.append(
                    {
                        "ts_ms": int(ts_ms),
                        "title": title,
                        "description": description,
                    }
                )
            markers[chart_key] = chart_markers
        return markers

    def _build_pt_markers_by_chart_key_from_entries(self) -> dict[str, list[dict[str, Any]]]:
        marker_offsets = self.annotation_marker_offsets()
        markers: dict[str, list[dict[str, Any]]] = {}
        for chart_key, entry in self._chart_entries_by_key.items():
            trades = entry.get("trades", []) or []
            chart_markers: list[dict[str, Any]] = []
            for trade in trades:
                if not isinstance(trade, Mapping):
                    continue
                ts_ms = trade.get("ts_ms")
                if not isinstance(ts_ms, int):
                    continue
                direction = str(trade.get("direction", "") or "").strip()
                if direction == "Long":
                    marker_side = "below"
                    marker_offset = int(marker_offsets["pt_long_marker_offset"])
                elif direction == "Short":
                    marker_side = "above"
                    marker_offset = -int(marker_offsets["pt_short_marker_offset"])
                else:
                    continue
                chart_markers.append(
                    {
                        "ts_ms": int(ts_ms),
                        "direction": direction,
                        "starting_price": trade.get("starting_price"),
                        "target_pct_movement": trade.get("target_pct_movement"),
                        "closing_price": trade.get("closing_price"),
                        "outcome": str(trade.get("outcome", "") or "").strip(),
                        "note": str(trade.get("note", "") or "").strip(),
                        "marker_side": marker_side,
                        "marker_offset": marker_offset,
                    }
                )
            markers[chart_key] = chart_markers
        return markers

    def _rebuild_chart_tabs(self) -> None:
        current_index = self._chart_tabs.currentIndex()
        self._chart_tabs.blockSignals(True)
        try:
            self._chart_tabs.clear()
            self._chart_tab_indexes.clear()
            self._tables_by_chart_key.clear()

            for chart_key, entry in sorted(
                self._chart_entries_by_key.items(),
                key=lambda item: self._entry_sort_key(item[1]),
            ):
                label = self._chart_tab_label(entry)
                tab = self._new_chart_tab(chart_key, entry)
                tab.setProperty("chart_key", chart_key)
                index = self._chart_tabs.addTab(tab, label)
                self._chart_tab_indexes[chart_key] = index
                self._chart_tab_labels[chart_key] = label
                self._mark_chart_tab_active(chart_key, chart_key in self._active_chart_keys)

            if self._chart_tabs.count():
                self._chart_tabs.setCurrentIndex(
                    max(0, min(current_index, self._chart_tabs.count() - 1))
                )
        finally:
            self._chart_tabs.blockSignals(False)

    def _new_chart_tab(self, chart_key: str, entry: Mapping[str, Any]) -> QWidget:
        wrapper = QWidget(self._chart_tabs)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        warning = QLabel("Chart is not currently active; notes are preserved.", wrapper)
        warning.setObjectName("historicalNotebookMissingChartWarning")
        warning.setStyleSheet("color: #ff7777;")
        warning.setVisible(chart_key not in self._active_chart_keys)
        layout.addWidget(warning)

        inner_tabs = QTabWidget(wrapper)
        inner_tabs.setObjectName("historicalNotebookInnerTabs")
        self._apply_bold_tab_font(inner_tabs)
        layout.addWidget(inner_tabs, 1)

        notes_table = self._new_section_table(chart_key, _SECTION_NOTES, _NOTE_COLUMNS)
        trades_table = self._new_section_table(chart_key, _SECTION_TRADES, _TRADE_COLUMNS)
        poi_table = self._new_section_table(chart_key, _SECTION_POI, _POI_COLUMNS)

        self._tables_by_chart_key[chart_key] = {
            _SECTION_NOTES: notes_table,
            _SECTION_TRADES: trades_table,
            _SECTION_POI: poi_table,
        }

        inner_tabs.addTab(self._section_widget(notes_table, "Add Note"), "Notes")
        inner_tabs.addTab(self._section_widget(trades_table, "Add Trade"), "Potential Trades")
        inner_tabs.addTab(self._section_widget(poi_table, "Add Point of Interest"), "Point of Interest")

        self._populate_table(notes_table, entry.get(_SECTION_NOTES, []) or [], _SECTION_NOTES)
        self._populate_table(trades_table, entry.get(_SECTION_TRADES, []) or [], _SECTION_TRADES)
        self._populate_table(poi_table, entry.get(_SECTION_POI, []) or [], _SECTION_POI)

        return wrapper

    def _section_widget(self, table: QTableWidget, button_text: str) -> QWidget:
        widget = QWidget(self._chart_tabs)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        add_button = QPushButton(button_text, widget)
        add_button.clicked.connect(lambda checked=False, table=table: self._append_empty_row(table))
        row.addWidget(add_button)
        self._add_formatting_palette(row, widget)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(table, 1)
        return widget

    def _add_formatting_palette(self, row: QHBoxLayout, parent: QWidget) -> None:
        for text, tooltip, handler in (
            ("B", "Bold selected notebook text", self._toggle_bold_for_current_editor),
            ("U", "Underline selected notebook text", self._toggle_underline_for_current_editor),
            ("Color", "Set selected notebook text color", self._set_color_for_current_editor),
            ("List", "Apply bullet list to selected notebook text", self._apply_bullet_list_to_current_editor),
            ("1. List", "Apply numbered list to selected notebook text", self._apply_numbered_list_to_current_editor),
        ):
            button = QToolButton(parent)
            button.setText(text)
            button.setToolTip(tooltip)
            button.setAutoRaise(True)
            button.clicked.connect(handler)
            row.addWidget(button)

    def _new_section_table(
        self,
        chart_key: str,
        section: str,
        columns: Sequence[str],
    ) -> QTableWidget:
        table = QTableWidget(0, len(columns), self._chart_tabs)
        table.setObjectName(f"historicalNotebook{section.title().replace('_', '')}Table")
        table.setHorizontalHeaderLabels(list(columns))
        table.setProperty("chart_key", chart_key)
        table.setProperty("section", section)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        self._configure_table_columns(table, section)
        table.itemChanged.connect(lambda item, table=table: self._on_table_item_changed(table, item))
        return table

    def _configure_table_columns(self, table: QTableWidget, section: str) -> None:
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)

        date_column = self._date_column_for_section(section)
        if date_column >= 0:
            table.setColumnWidth(date_column, self._date_time_column_width(table))

        delete_column = self._delete_column_for_section(section)
        if delete_column >= 0:
            header.setSectionResizeMode(delete_column, QHeaderView.Fixed)
            table.setColumnWidth(delete_column, _ACTION_BUTTON_WIDTH)

        if section == _SECTION_NOTES:
            header.setSectionResizeMode(2, QHeaderView.Stretch)
            return

        if section == _SECTION_TRADES:
            header.setSectionResizeMode(_GOTO_COLUMN, QHeaderView.Fixed)
            table.setColumnWidth(_GOTO_COLUMN, _ACTION_BUTTON_WIDTH)
            table.setColumnWidth(3, 110)
            table.setColumnWidth(4, 120)
            table.setColumnWidth(5, 145)
            table.setColumnWidth(6, 120)
            table.setColumnWidth(7, 95)
            header.setSectionResizeMode(8, QHeaderView.Stretch)
            return

        if section == _SECTION_POI:
            header.setSectionResizeMode(_GOTO_COLUMN, QHeaderView.Fixed)
            table.setColumnWidth(_GOTO_COLUMN, _ACTION_BUTTON_WIDTH)
            table.setColumnWidth(3, _POI_TITLE_COLUMN_WIDTH)
            header.setSectionResizeMode(4, QHeaderView.Stretch)

    def _date_time_column_width(self, table: QTableWidget) -> int:
        return (
            QFontMetrics(table.font()).horizontalAdvance(_SUPPORTED_DATE_TIME_TEXT)
            + 34
        )

    def _date_column_for_section(self, section: str) -> int:
        if section == _SECTION_NOTES:
            return 1
        if section in {_SECTION_TRADES, _SECTION_POI}:
            return 2
        return -1

    def _delete_column_for_section(self, section: str) -> int:
        if section == _SECTION_NOTES:
            return 0
        if section in {_SECTION_TRADES, _SECTION_POI}:
            return 1
        return -1

    def _populate_table(
        self,
        table: QTableWidget,
        rows: Sequence[Any],
        section: str,
    ) -> None:
        self._updating_tables = True
        try:
            table.setRowCount(0)
            for raw_row in rows:
                row = dict(raw_row) if isinstance(raw_row, Mapping) else {}
                self._append_row_payload(table, section, row)
            self._configure_table_columns(table, section)
        finally:
            self._updating_tables = False

    def _append_empty_row(self, table: QTableWidget) -> None:
        section = str(table.property("section") or "")
        payload = {"row_id": uuid.uuid4().hex, "date_text": "", "ts_ms": None}
        if section == _SECTION_NOTES:
            payload["note"] = ""
        elif section == _SECTION_TRADES:
            payload.update(
                {
                    "direction": "",
                    "starting_price": None,
                    "target_pct_movement": None,
                    "closing_price": None,
                    "outcome": "Good",
                    "note": "",
                }
            )
        elif section == _SECTION_POI:
            payload.update({"title": "", "description": ""})
        self._append_row_payload(table, section, payload)
        self._sync_entry_from_table(table)
        self.mark_dirty()

    def _append_row_payload(
        self,
        table: QTableWidget,
        section: str,
        payload: Mapping[str, Any],
    ) -> None:
        row_index = table.rowCount()
        table.insertRow(row_index)
        row_id = str(payload.get("row_id", "") or uuid.uuid4().hex)
        date_item = self._table_item(str(payload.get("date_text", "") or ""), row_id=row_id)
        date_column = self._date_column_for_section(section)
        table.setItem(row_index, date_column, date_item)
        self._set_delete_button_cell(table, row_index)

        if section == _SECTION_NOTES:
            self._set_rich_text_cell(
                table,
                row_index,
                2,
                plain_text=str(payload.get("note", "") or ""),
                html_text=str(payload.get("note_html", "") or ""),
            )
            return

        if section == _SECTION_TRADES:
            self._set_goto_button_cell(table, row_index)
            self._set_combo_cell(table, row_index, 3, ("", "Long", "Short"), str(payload.get("direction", "") or ""))
            numeric_keys = (
                "starting_price",
                "target_pct_movement",
                "closing_price",
            )
            for offset, key in enumerate(numeric_keys, start=4):
                value = payload.get(key)
                table.setItem(row_index, offset, self._table_item("" if value is None else str(value), row_id=row_id))
            self._set_combo_cell(table, row_index, 7, ("Good", "Bad"), str(payload.get("outcome", "Good") or "Good"))
            self._set_rich_text_cell(
                table,
                row_index,
                8,
                plain_text=str(payload.get("note", "") or ""),
                html_text=str(payload.get("note_html", "") or ""),
            )
            return

        if section == _SECTION_POI:
            self._set_goto_button_cell(table, row_index)
            self._set_rich_text_cell(
                table,
                row_index,
                3,
                plain_text=str(payload.get("title", "") or ""),
                html_text=str(payload.get("title_html", "") or ""),
            )
            self._set_rich_text_cell(
                table,
                row_index,
                4,
                plain_text=str(payload.get("description", "") or ""),
                html_text=str(payload.get("description_html", "") or ""),
            )

    def _table_item(self, text: str, *, row_id: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.UserRole, row_id)
        return item

    def _register_rich_text_editor(self, editor: _NotebookRichTextEdit) -> None:
        editor.setAcceptRichText(True)
        editor.focused.connect(lambda target: self._set_current_text_editor(target))
        editor.textChanged.connect(self.mark_dirty)

    def _set_current_text_editor(self, editor: object) -> None:
        self._current_text_editor = editor if isinstance(editor, QTextEdit) else None

    def _rich_text_editor_at(
        self,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> QTextEdit | None:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QTextEdit):
            return widget
        return None

    def _set_rich_text_content(
        self,
        editor: QTextEdit,
        *,
        plain_text: str,
        html_text: str = "",
    ) -> None:
        previous_suppress_dirty = self._suppress_dirty
        self._suppress_dirty = True
        try:
            if str(html_text or "").strip():
                editor.setHtml(str(html_text))
            else:
                editor.setPlainText(str(plain_text or ""))
        finally:
            self._suppress_dirty = previous_suppress_dirty

    def _html_payload_for_editor(self, editor: QTextEdit) -> str:
        if not str(editor.toPlainText() or "").strip():
            return ""
        return str(editor.toHtml() or "")

    def _rich_text_plain_text(
        self,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> str:
        editor = self._rich_text_editor_at(table, row, column)
        if editor is None:
            return self._item_text(table, row, column)
        return str(editor.toPlainText() or "").strip()

    def _rich_text_html(
        self,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> str:
        editor = self._rich_text_editor_at(table, row, column)
        if editor is None:
            return ""
        return self._html_payload_for_editor(editor)

    def _add_html_payload(
        self,
        payload: dict[str, Any],
        key: str,
        html_text: str,
    ) -> None:
        if str(html_text or "").strip():
            payload[key] = html_text

    def _set_rich_text_cell(
        self,
        table: QTableWidget,
        row: int,
        column: int,
        *,
        plain_text: str,
        html_text: str = "",
    ) -> None:
        editor = _NotebookRichTextEdit(table)
        editor.setAcceptRichText(True)
        editor.setMinimumHeight(58)
        editor.setObjectName("historicalNotebookRichTextCell")
        self._register_rich_text_editor(editor)
        editor.textChanged.connect(lambda table=table: self._on_rich_text_cell_changed(table))
        self._set_rich_text_content(
            editor,
            plain_text=plain_text,
            html_text=html_text,
        )
        table.setCellWidget(row, column, editor)
        table.setRowHeight(row, max(table.rowHeight(row), 68))

    def _on_rich_text_cell_changed(self, table: QTableWidget) -> None:
        if self._updating_tables:
            return
        self._sync_entry_from_table(table)
        self.mark_dirty()

    def _toggle_bold_for_current_editor(self) -> None:
        editor = self._current_text_editor
        if editor is None:
            return
        fmt = QTextCharFormat()
        current_weight = editor.currentCharFormat().fontWeight()
        fmt.setFontWeight(QFont.Normal if current_weight >= QFont.Bold else QFont.Bold)
        self._merge_format_for_current_editor(fmt)

    def _toggle_underline_for_current_editor(self) -> None:
        editor = self._current_text_editor
        if editor is None:
            return
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not editor.currentCharFormat().fontUnderline())
        self._merge_format_for_current_editor(fmt)

    def _set_color_for_current_editor(self) -> None:
        editor = self._current_text_editor
        if editor is None:
            return
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self._merge_format_for_current_editor(fmt)

    def _merge_format_for_current_editor(self, fmt: QTextCharFormat) -> None:
        editor = self._current_text_editor
        if editor is None:
            return
        cursor = editor.textCursor()
        cursor.mergeCharFormat(fmt)
        editor.mergeCurrentCharFormat(fmt)
        editor.setTextCursor(cursor)
        self.mark_dirty()

    def _apply_bullet_list_to_current_editor(self) -> None:
        self._apply_list_to_current_editor(QTextListFormat.ListDisc)

    def _apply_numbered_list_to_current_editor(self) -> None:
        self._apply_list_to_current_editor(QTextListFormat.ListDecimal)

    def _apply_list_to_current_editor(self, style: QTextListFormat.Style) -> None:
        editor = self._current_text_editor
        if editor is None:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        list_format = QTextListFormat()
        list_format.setStyle(style)
        cursor.createList(list_format)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        self.mark_dirty()

    def _set_goto_button_cell(self, table: QTableWidget, row: int) -> None:
        button = QToolButton(table)
        button.setText("Go")
        button.setToolTip("Center chart on this row's Date / Time")
        button.setAutoRaise(True)
        button.clicked.connect(
            lambda _checked=False, table=table, button=button: self._on_row_goto_button_clicked(
                table,
                button,
            )
        )
        table.setCellWidget(row, _GOTO_COLUMN, button)

    def _set_delete_button_cell(self, table: QTableWidget, row: int) -> None:
        delete_column = self._delete_column_for_section(str(table.property("section") or ""))
        if delete_column < 0:
            return

        button = QToolButton(table)
        button.setText("Delete")
        button.setToolTip("Delete this notebook row")
        button.setAutoRaise(True)
        button.clicked.connect(
            lambda _checked=False, table=table, button=button: self._on_row_delete_button_clicked(
                table,
                button,
            )
        )
        table.setCellWidget(row, delete_column, button)

    def _on_row_goto_button_clicked(
        self,
        table: QTableWidget,
        button: QToolButton,
    ) -> None:
        row = self._row_for_cell_widget(table, button)
        if row < 0:
            self._set_goto_status("Go To failed: row could not be resolved.")
            return
        self._on_row_goto_clicked(table, row)

    def _on_row_delete_button_clicked(
        self,
        table: QTableWidget,
        button: QToolButton,
    ) -> None:
        row = self._row_for_cell_widget(table, button)
        if row < 0:
            self._status_label.setText("Delete failed: row could not be resolved.")
            return
        self._delete_table_row(table, row)

    def _row_for_cell_widget(self, table: QTableWidget, widget: QWidget) -> int:
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                if table.cellWidget(row, column) is widget:
                    return row
        return -1

    def _set_combo_cell(
        self,
        table: QTableWidget,
        row: int,
        column: int,
        choices: Sequence[str],
        value: str,
    ) -> None:
        combo = QComboBox(table)
        combo.addItems(list(choices))
        if value in choices:
            combo.setCurrentText(value)
        combo.currentTextChanged.connect(lambda _text, table=table: self._on_combo_cell_changed(table))
        table.setCellWidget(row, column, combo)

    def _on_table_item_changed(self, table: QTableWidget, _item: QTableWidgetItem) -> None:
        if self._updating_tables:
            return
        self._sync_entry_from_table(table)
        self.mark_dirty()

    def _on_combo_cell_changed(self, table: QTableWidget) -> None:
        if self._updating_tables:
            return
        self._sync_entry_from_table(table)
        self.mark_dirty()

    def _sync_entry_from_table(self, table: QTableWidget) -> None:
        if self._updating_tables:
            return
        chart_key = str(table.property("chart_key") or "")
        section = str(table.property("section") or "")
        entry = self._chart_entries_by_key.get(chart_key)
        if entry is None or section not in {_SECTION_NOTES, _SECTION_TRADES, _SECTION_POI}:
            return
        entry[section] = self._rows_from_table(table, section)
        if section in {_SECTION_TRADES, _SECTION_POI}:
            self._emit_poi_markers_changed()

    def _sync_all_entries_from_tables(self) -> None:
        for table_map in self._tables_by_chart_key.values():
            for table in table_map.values():
                self._sync_entry_from_table(table)

    def _rows_from_table(self, table: QTableWidget, section: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        date_column = self._date_column_for_section(section)
        for row in range(table.rowCount()):
            row_id = self._row_id_for_table_row(table, row)
            date_text = self._item_text(table, row, date_column)
            ts_ms = self._parse_date_text_to_ts_ms(date_text)
            if section == _SECTION_NOTES:
                row_payload = {
                    "row_id": row_id,
                    "date_text": date_text,
                    "ts_ms": ts_ms,
                    "note": self._rich_text_plain_text(table, row, 2),
                }
                self._add_html_payload(
                    row_payload,
                    "note_html",
                    self._rich_text_html(table, row, 2),
                )
                rows.append(row_payload)
            elif section == _SECTION_TRADES:
                row_payload = {
                    "row_id": row_id,
                    "date_text": date_text,
                    "ts_ms": ts_ms,
                    "direction": self._combo_text(table, row, 3),
                    "starting_price": self._float_or_none(self._item_text(table, row, 4)),
                    "target_pct_movement": self._float_or_none(self._item_text(table, row, 5)),
                    "closing_price": self._float_or_none(self._item_text(table, row, 6)),
                    "outcome": self._combo_text(table, row, 7) or "Good",
                    "note": self._rich_text_plain_text(table, row, 8),
                }
                self._add_html_payload(
                    row_payload,
                    "note_html",
                    self._rich_text_html(table, row, 8),
                )
                rows.append(row_payload)
            elif section == _SECTION_POI:
                row_payload = {
                    "row_id": row_id,
                    "date_text": date_text,
                    "ts_ms": ts_ms,
                    "title": self._rich_text_plain_text(table, row, 3),
                    "description": self._rich_text_plain_text(table, row, 4),
                }
                self._add_html_payload(
                    row_payload,
                    "title_html",
                    self._rich_text_html(table, row, 3),
                )
                self._add_html_payload(
                    row_payload,
                    "description_html",
                    self._rich_text_html(table, row, 4),
                )
                rows.append(row_payload)
        return rows

    def _row_id_for_table_row(self, table: QTableWidget, row: int) -> str:
        section = str(table.property("section") or "")
        item = table.item(row, self._date_column_for_section(section))
        if item is not None:
            row_id = str(item.data(Qt.UserRole) or "").strip()
            if row_id:
                return row_id
        row_id = uuid.uuid4().hex
        if item is not None:
            item.setData(Qt.UserRole, row_id)
        return row_id

    def _item_text(self, table: QTableWidget, row: int, column: int) -> str:
        editor = self._rich_text_editor_at(table, row, column)
        if editor is not None:
            return str(editor.toPlainText() or "").strip()
        item = table.item(row, column)
        if item is None:
            return ""
        return str(item.text() or "").strip()

    def _combo_text(self, table: QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            return str(widget.currentText() or "").strip()
        return ""

    def _float_or_none(self, text: str) -> float | None:
        value = str(text or "").strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _set_goto_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_row_goto_clicked(self, table: QTableWidget, row: int) -> None:
        section = str(table.property("section") or "")
        if section not in {_SECTION_TRADES, _SECTION_POI}:
            return

        chart_key = str(table.property("chart_key") or "").strip()
        if not chart_key:
            self._set_goto_status("Go To failed: notebook chart key is missing.")
            return

        date_column = self._date_column_for_section(section)
        item = table.item(row, date_column)
        if item is not None:
            table.closePersistentEditor(item)
        date_text = self._item_text(table, row, date_column)
        if not date_text:
            self._set_goto_status("Go To failed: Date / Time is empty.")
            return

        ts_ms = self._parse_date_text_to_ts_ms(date_text)
        if ts_ms is None:
            self._set_goto_status("Go To failed: Date / Time could not be parsed.")
            QMessageBox.warning(
                self,
                "Notebook Go To",
                "Could not parse the Date / Time value. Use YYYY-MM-DD, "
                "YYYY-MM-DD HH:MM, or YYYY-MM-DD HH:MM:SS.",
            )
            return

        self._set_goto_status(f"Go To requested: {date_text}")
        self.goto_requested.emit(chart_key, int(ts_ms))

    def _delete_table_row(self, table: QTableWidget, row: int) -> None:
        section = str(table.property("section") or "")
        if section not in {_SECTION_NOTES, _SECTION_TRADES, _SECTION_POI}:
            return
        if row < 0 or row >= table.rowCount():
            return
        if not self._confirm_row_delete(section):
            return

        table.removeRow(row)
        self._sync_entry_from_table(table)
        self.mark_dirty()
        self._status_label.setText(f"Deleted {self._row_label_for_section(section)}.")

    def _confirm_row_delete(self, section: str) -> bool:
        message = self._delete_confirmation_message(section)
        if not message:
            return False

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Delete Notebook Row")
        dialog.setText(message[0])
        dialog.setInformativeText(message[1])
        delete_button = dialog.addButton("Delete", QMessageBox.DestructiveRole)
        dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.setDefaultButton(delete_button)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _delete_confirmation_message(self, section: str) -> tuple[str, str] | None:
        if section == _SECTION_NOTES:
            return ("Delete this note?", "This action cannot be undone.")
        if section == _SECTION_TRADES:
            return ("Delete this potential trade?", "This action cannot be undone.")
        if section == _SECTION_POI:
            return ("Delete this point of interest?", "This action cannot be undone.")
        return None

    def _row_label_for_section(self, section: str) -> str:
        if section == _SECTION_NOTES:
            return "note"
        if section == _SECTION_TRADES:
            return "potential trade"
        if section == _SECTION_POI:
            return "point of interest"
        return "row"

    def _on_table_cell_double_clicked(
        self,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> None:
        return

    def _on_chart_tab_close_requested(self, index: int) -> None:
        widget = self._chart_tabs.widget(index)
        chart_key = str(widget.property("chart_key") or "") if widget is not None else ""
        if not chart_key:
            return

        answer = QMessageBox.question(
            self,
            "Remove Notebook Chart",
            "Remove this chart entry and all notebook rows for it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._chart_entries_by_key.pop(chart_key, None)
        self._chart_tab_indexes.pop(chart_key, None)
        self._chart_tab_labels.pop(chart_key, None)
        self._tables_by_chart_key.pop(chart_key, None)
        self._chart_tabs.removeTab(index)
        self._refresh_tab_indexes()
        self._emit_poi_markers_changed()
        self.mark_dirty()
        self._update_status()

    def _on_poi_overlay_toggled(self, checked: bool) -> None:
        self.poi_overlay_requested.emit(bool(checked))
        self._emit_poi_markers_changed()

    def _on_annotation_offset_changed(self, _value: int) -> None:
        self.mark_dirty()
        self._emit_poi_markers_changed()

    def _emit_poi_markers_changed(self) -> None:
        if self._syncing_from_tables or self._suppress_notebook_change_signals:
            return
        self.poi_markers_changed.emit()

    def _mark_chart_tab_active(self, chart_key: str, active: bool) -> None:
        self._refresh_tab_indexes()
        index = self._chart_tab_indexes.get(chart_key)
        if index is None:
            return

        if active:
            self._chart_tabs.tabBar().setTabTextColor(index, QColor("#d8d8d8"))
            self._chart_tabs.setTabToolTip(index, "Chart is currently active.")
        else:
            self._chart_tabs.tabBar().setTabTextColor(index, QColor("#ff5555"))
            self._chart_tabs.setTabToolTip(
                index,
                "Chart is not currently active; notes are preserved.",
            )

        tab = self._chart_tabs.widget(index)
        if tab is not None:
            warning = tab.findChild(QLabel, "historicalNotebookMissingChartWarning")
            if warning is not None:
                warning.setVisible(not active)

    def _refresh_tab_indexes(self) -> None:
        self._chart_tab_indexes.clear()
        for index in range(self._chart_tabs.count()):
            widget = self._chart_tabs.widget(index)
            chart_key = str(widget.property("chart_key") or "") if widget is not None else ""
            if chart_key:
                self._chart_tab_indexes[chart_key] = index

    def _entry_from_chart_option(self, option: Mapping[str, Any]) -> dict[str, Any] | None:
        dataset = option.get("dataset", {}) or {}
        if not isinstance(dataset, Mapping):
            return None
        normalized_dataset = {
            key: str(dataset.get(key, "") or "").strip()
            for key in _DATASET_KEYS
        }
        chart_key = notebook_chart_key(normalized_dataset)
        if not chart_key or not all(normalized_dataset.values()):
            return None
        return {
            "chart_key": chart_key,
            "dataset": normalized_dataset,
            "last_seen_position": option.get("position"),
            "notes": [],
            "trades": [],
            "points_of_interest": [],
        }

    def _chart_tab_label(self, entry: Mapping[str, Any]) -> str:
        dataset = entry.get("dataset", {}) or {}
        if not isinstance(dataset, Mapping):
            dataset = {}

        position = str(entry.get("last_seen_position", "") or "").strip()
        symbol = str(dataset.get("symbol", "") or "").strip()
        timeframe = str(dataset.get("timeframe", "") or "").strip()
        exchange = str(dataset.get("exchange", "") or "").strip()
        market_type = str(dataset.get("market_type", "") or "").strip()
        title = " ".join(part for part in (symbol, timeframe) if part).strip() or "Chart"
        prefix = f"#{position}" if position else "Chart"
        detail = " / ".join(part for part in (exchange, market_type) if part)
        return f"{prefix} - {title}" + (f" ({detail})" if detail else "")

    def _entry_sort_key(self, entry: Mapping[str, Any]) -> tuple[int, str]:
        try:
            position = int(entry.get("last_seen_position", 9999))
        except (TypeError, ValueError):
            position = 9999
        return (position, str(entry.get("chart_key", "") or ""))

    def _normalized_chart_entries_snapshot(self) -> list[dict[str, Any]]:
        return [
            normalize_notebook_chart_entry(entry)
            for _, entry in sorted(
                self._chart_entries_by_key.items(),
                key=lambda item: self._entry_sort_key(item[1]),
            )
        ]

    def _parse_date_text_to_ts_ms(self, text: str) -> int | None:
        value = str(text or "").strip()
        if not value:
            return None
        value = value.replace("T", " ")
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                return int(parsed.timestamp() * 1000)
            except ValueError:
                continue
        return None

    def _update_status(self, *, prefix: str = "") -> None:
        active_count = len(self._active_chart_keys)
        tracked_count = len(self._chart_entries_by_key)
        missing_count = max(0, tracked_count - active_count)
        parts = []
        if prefix:
            parts.append(prefix)
        parts.append(
            f"Notebook tracks {tracked_count} chart tab(s); "
            f"{active_count} active, {missing_count} inactive."
        )
        self._status_label.setText(" ".join(parts))
