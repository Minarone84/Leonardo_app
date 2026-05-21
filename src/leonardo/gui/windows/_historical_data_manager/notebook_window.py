from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import time
import uuid
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.notebook_store import (
    HISTORICAL_NOTEBOOK_OBJECT_TYPE,
    HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
    HistoricalNotebook,
    normalize_notebook_chart_entry,
    notebook_chart_key,
)


_DATASET_KEYS = ("exchange", "market_type", "symbol", "timeframe")
_SECTION_NOTES = "notes"
_SECTION_TRADES = "trades"
_SECTION_POI = "points_of_interest"

_NOTE_COLUMNS = ("Date / Time", "Note")
_TRADE_COLUMNS = (
    "Date / Time",
    "Direction",
    "Starting price",
    "Target % movement",
    "Closing price",
    "Equity",
    "Leverage",
    "Asset bought",
    "Outcome",
    "Note",
)
_POI_COLUMNS = ("Date / Time", "Title", "Description")


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
    goto_requested = Signal(str, int)
    poi_markers_changed = Signal()
    poi_overlay_requested = Signal(bool)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historical Notebook")
        self.resize(1020, 760)
        self.setMinimumSize(800, 560)

        self._notebook_id: str | None = None
        self._created_at_ms: int | None = None
        self._updated_at_ms: int | None = None
        self._chart_entries_by_key: dict[str, dict[str, Any]] = {}
        self._active_chart_keys: set[str] = set()
        self._chart_tab_indexes: dict[str, int] = {}
        self._chart_tab_labels: dict[str, str] = {}
        self._tables_by_chart_key: dict[str, dict[str, QTableWidget]] = {}
        self._updating_tables = False

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

        self._save_button = QPushButton("Save", root)
        self._save_button.setObjectName("historicalNotebookSaveButton")
        self._save_button.clicked.connect(self.save_requested.emit)
        header_row.addWidget(self._save_button)

        self._load_button = QPushButton("Load", root)
        self._load_button.setObjectName("historicalNotebookLoadButton")
        self._load_button.clicked.connect(self.load_requested.emit)
        header_row.addWidget(self._load_button)

        self._assign_button = QPushButton("Assign", root)
        self._assign_button.setObjectName("historicalNotebookAssignButton")
        self._assign_button.clicked.connect(self.assign_requested.emit)
        header_row.addWidget(self._assign_button)

        layout.addLayout(header_row)

        description_label = QLabel("Description", root)
        description_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(description_label)

        self._description_edit = QPlainTextEdit(root)
        self._description_edit.setObjectName("historicalNotebookDescriptionEdit")
        self._description_edit.setPlaceholderText("Notebook description")
        self._description_edit.setFixedHeight(58)
        layout.addWidget(self._description_edit)

        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(8)

        self._show_poi_markers_check = QCheckBox("Show POI markers on charts", root)
        self._show_poi_markers_check.setObjectName("historicalNotebookShowPoiMarkersCheck")
        self._show_poi_markers_check.toggled.connect(self._on_poi_overlay_toggled)
        tools_row.addWidget(self._show_poi_markers_check)
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
        layout.addWidget(self._chart_tabs, 1)

    def notebook_id(self) -> str | None:
        return self._notebook_id

    def display_name(self) -> str:
        return str(self._name_edit.text() or "").strip() or "Untitled notebook"

    def description(self) -> str:
        return str(self._description_edit.toPlainText() or "")

    def created_at_ms(self) -> int | None:
        return self._created_at_ms

    def chart_entries_payload(self) -> list[dict[str, Any]]:
        self._sync_all_entries_from_tables()
        return [
            normalize_notebook_chart_entry(entry)
            for _, entry in sorted(
                self._chart_entries_by_key.items(),
                key=lambda item: self._entry_sort_key(item[1]),
            )
        ]

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
            created_at_ms=created,
            updated_at_ms=now_ms,
            chart_entries=tuple(self.chart_entries_payload()),
        )

    def set_notebook(
        self,
        notebook: HistoricalNotebook,
        *,
        assigned_snapshot_label: str | None = None,
    ) -> None:
        """Replace in-memory editor state with a loaded notebook payload."""
        self._notebook_id = notebook.notebook_id
        self._created_at_ms = notebook.created_at_ms
        self._updated_at_ms = notebook.updated_at_ms
        self._name_edit.setText(notebook.display_name)
        self._description_edit.setPlainText(notebook.description)

        entries: dict[str, dict[str, Any]] = {}
        for raw_entry in notebook.chart_entries:
            entry = normalize_notebook_chart_entry(raw_entry)
            entries[str(entry["chart_key"])] = entry
        self._chart_entries_by_key = entries

        if assigned_snapshot_label:
            self._assigned_snapshot_label.setText(f"Assigned snapshot: {assigned_snapshot_label}")

        self._rebuild_chart_tabs()
        self._update_status()

    def mark_saved(self, notebook: HistoricalNotebook) -> None:
        self._notebook_id = notebook.notebook_id
        self._created_at_ms = notebook.created_at_ms
        self._updated_at_ms = notebook.updated_at_ms
        self._name_edit.setText(notebook.display_name)
        self._description_edit.setPlainText(notebook.description)
        self._update_status(prefix=f"Saved notebook: {notebook.display_name}.")

    def set_assigned_snapshot_label(self, label: str | None) -> None:
        resolved = str(label or "").strip()
        if resolved:
            self._assigned_snapshot_label.setText(f"Assigned snapshot: {resolved}")
        else:
            self._assigned_snapshot_label.setText("Assigned snapshot: Not assigned")

    def refresh_from_chart_options(self, chart_options: Sequence[Mapping[str, Any]]) -> None:
        """Refresh chart tabs from current embedded chart descriptors.

        Notebook chart identity is dataset-based. The workspace position is
        display metadata only and is stored as last_seen_position.
        """
        self._sync_all_entries_from_tables()
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

    def poi_markers_enabled(self) -> bool:
        return bool(self._show_poi_markers_check.isChecked())

    def poi_markers_by_chart_key(self) -> dict[str, list[dict[str, Any]]]:
        self._sync_all_entries_from_tables()
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
        inner_tabs.addTab(self._section_widget(trades_table, "Add Trade"), "Trades")
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
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(table, 1)
        return widget

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
        table.itemChanged.connect(lambda item, table=table: self._on_table_item_changed(table, item))
        table.cellDoubleClicked.connect(
            lambda row, column, table=table: self._on_table_cell_double_clicked(table, row, column)
        )
        return table

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
            table.resizeColumnsToContents()
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
                    "direction": "Long",
                    "starting_price": None,
                    "target_pct_movement": None,
                    "closing_price": None,
                    "equity": None,
                    "leverage": None,
                    "asset_bought": None,
                    "outcome": "Good",
                    "note": "",
                }
            )
        elif section == _SECTION_POI:
            payload.update({"title": "", "description": ""})
        self._append_row_payload(table, section, payload)
        self._sync_entry_from_table(table)

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
        table.setItem(row_index, 0, date_item)

        if section == _SECTION_NOTES:
            table.setItem(row_index, 1, self._table_item(str(payload.get("note", "") or ""), row_id=row_id))
            return

        if section == _SECTION_TRADES:
            self._set_combo_cell(table, row_index, 1, ("Long", "Short"), str(payload.get("direction", "Long") or "Long"))
            numeric_keys = (
                "starting_price",
                "target_pct_movement",
                "closing_price",
                "equity",
                "leverage",
                "asset_bought",
            )
            for offset, key in enumerate(numeric_keys, start=2):
                value = payload.get(key)
                table.setItem(row_index, offset, self._table_item("" if value is None else str(value), row_id=row_id))
            self._set_combo_cell(table, row_index, 8, ("Good", "Bad"), str(payload.get("outcome", "Good") or "Good"))
            table.setItem(row_index, 9, self._table_item(str(payload.get("note", "") or ""), row_id=row_id))
            return

        if section == _SECTION_POI:
            table.setItem(row_index, 1, self._table_item(str(payload.get("title", "") or ""), row_id=row_id))
            table.setItem(row_index, 2, self._table_item(str(payload.get("description", "") or ""), row_id=row_id))

    def _table_item(self, text: str, *, row_id: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setData(Qt.UserRole, row_id)
        return item

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
        combo.currentTextChanged.connect(lambda _text, table=table: self._sync_entry_from_table(table))
        table.setCellWidget(row, column, combo)

    def _on_table_item_changed(self, table: QTableWidget, _item: QTableWidgetItem) -> None:
        if self._updating_tables:
            return
        self._sync_entry_from_table(table)

    def _sync_entry_from_table(self, table: QTableWidget) -> None:
        if self._updating_tables:
            return
        chart_key = str(table.property("chart_key") or "")
        section = str(table.property("section") or "")
        entry = self._chart_entries_by_key.get(chart_key)
        if entry is None or section not in {_SECTION_NOTES, _SECTION_TRADES, _SECTION_POI}:
            return
        entry[section] = self._rows_from_table(table, section)
        if section == _SECTION_POI:
            self.poi_markers_changed.emit()

    def _sync_all_entries_from_tables(self) -> None:
        for table_map in self._tables_by_chart_key.values():
            for table in table_map.values():
                self._sync_entry_from_table(table)

    def _rows_from_table(self, table: QTableWidget, section: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in range(table.rowCount()):
            row_id = self._row_id_for_table_row(table, row)
            date_text = self._item_text(table, row, 0)
            ts_ms = self._parse_date_text_to_ts_ms(date_text)
            if section == _SECTION_NOTES:
                rows.append(
                    {
                        "row_id": row_id,
                        "date_text": date_text,
                        "ts_ms": ts_ms,
                        "note": self._item_text(table, row, 1),
                    }
                )
            elif section == _SECTION_TRADES:
                rows.append(
                    {
                        "row_id": row_id,
                        "date_text": date_text,
                        "ts_ms": ts_ms,
                        "direction": self._combo_text(table, row, 1) or "Long",
                        "starting_price": self._float_or_none(self._item_text(table, row, 2)),
                        "target_pct_movement": self._float_or_none(self._item_text(table, row, 3)),
                        "closing_price": self._float_or_none(self._item_text(table, row, 4)),
                        "equity": self._float_or_none(self._item_text(table, row, 5)),
                        "leverage": self._float_or_none(self._item_text(table, row, 6)),
                        "asset_bought": self._float_or_none(self._item_text(table, row, 7)),
                        "outcome": self._combo_text(table, row, 8) or "Good",
                        "note": self._item_text(table, row, 9),
                    }
                )
            elif section == _SECTION_POI:
                rows.append(
                    {
                        "row_id": row_id,
                        "date_text": date_text,
                        "ts_ms": ts_ms,
                        "title": self._item_text(table, row, 1),
                        "description": self._item_text(table, row, 2),
                    }
                )
        return rows

    def _row_id_for_table_row(self, table: QTableWidget, row: int) -> str:
        item = table.item(row, 0)
        if item is not None:
            row_id = str(item.data(Qt.UserRole) or "").strip()
            if row_id:
                return row_id
        row_id = uuid.uuid4().hex
        if item is not None:
            item.setData(Qt.UserRole, row_id)
        return row_id

    def _item_text(self, table: QTableWidget, row: int, column: int) -> str:
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

    def _on_table_cell_double_clicked(
        self,
        table: QTableWidget,
        row: int,
        column: int,
    ) -> None:
        if column != 0:
            return
        chart_key = str(table.property("chart_key") or "")
        if chart_key not in self._active_chart_keys:
            QMessageBox.information(
                self,
                "Notebook Go To",
                "Chart is not currently active; notes are preserved.",
            )
            return

        date_text = self._item_text(table, row, 0)
        ts_ms = self._parse_date_text_to_ts_ms(date_text)
        if ts_ms is None:
            QMessageBox.warning(
                self,
                "Notebook Go To",
                "Could not parse the Date / Time value. Use YYYY-MM-DD, "
                "YYYY-MM-DD HH:MM, or YYYY-MM-DD HH:MM:SS.",
            )
            return

        self.goto_requested.emit(chart_key, int(ts_ms))

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
        self.poi_markers_changed.emit()
        self._update_status()

    def _on_poi_overlay_toggled(self, checked: bool) -> None:
        self.poi_overlay_requested.emit(bool(checked))
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
