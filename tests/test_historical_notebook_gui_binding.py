from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from leonardo.data.chart_presets.notebook_store import (
    DEFAULT_POI_MARKER_OFFSET,
    DEFAULT_PT_LONG_MARKER_OFFSET,
    DEFAULT_PT_SHORT_MARKER_OFFSET,
    HISTORICAL_NOTEBOOK_OBJECT_TYPE,
    HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
    HistoricalNotebook,
    notebook_chart_key,
)
from leonardo.gui.windows._historical_data_manager.notebook_window import (
    HistoricalNotebookWindow,
)
import leonardo.gui.windows.historical_data_manager_window as hdm_module
from leonardo.gui.windows.historical_data_manager_window import (
    HistoricalDataManagerWindow,
)
from PySide6.QtWidgets import QApplication, QComboBox, QToolButton


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
NOTEBOOK = WINDOWS / "_historical_data_manager" / "notebook_window.py"
HDM = WINDOWS / "historical_data_manager_window.py"

_QAPP: QApplication | None = None


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def test_notebook_window_has_structured_tabs_and_tables() -> None:
    source = _source(NOTEBOOK)

    assert "class HistoricalNotebookWindow(QMainWindow)" in source
    assert "QToolButton" in source
    assert "QTableWidget" in source
    assert '"Notes"' in source
    assert '"Potential Trades"' in source
    assert '"Point of Interest"' in source
    assert '"Date / Time"' in source
    assert '"Direction"' in source
    assert '"Long"' in source
    assert '"Short"' in source
    assert '"Good"' in source
    assert '"Bad"' in source
    assert '"Title"' in source
    assert '"Description"' in source


def test_trades_and_poi_tables_use_explicit_go_to_buttons_only() -> None:
    source = _source(NOTEBOOK)
    table_body = _function_source(NOTEBOOK, "_new_section_table")
    append_body = _function_source(NOTEBOOK, "_append_row_payload")
    goto_button_body = _function_source(NOTEBOOK, "_set_goto_button_cell")
    row_goto_body = _function_source(NOTEBOOK, "_on_row_goto_clicked")
    double_click_body = _function_source(NOTEBOOK, "_on_table_cell_double_clicked")

    assert '_NOTE_COLUMNS = ("Delete", "Date / Time", "Note")' in source
    assert '"Go",\n    "Delete",\n    "Date / Time",\n    "Direction",' in source
    assert '_POI_COLUMNS = ("Go", "Delete", "Date / Time", "Title", "Description")' in source
    assert "notes_table = self._new_section_table" in source
    assert "trades_table = self._new_section_table" in source
    assert "poi_table = self._new_section_table" in source
    assert source.count("self._set_goto_button_cell(table, row_index)") == 2
    assert "if section == _SECTION_TRADES:" in append_body
    assert "if section == _SECTION_POI:" in append_body
    assert "button.setText(\"Go\")" in goto_button_body
    assert "Center chart on this row's Date / Time" in goto_button_body
    assert "self._on_row_goto_button_clicked(" in goto_button_body
    assert "button=button" in goto_button_body
    assert "row=row" not in goto_button_body
    assert "cellDoubleClicked.connect" not in table_body
    assert "self._on_row_goto_clicked(table, row)" not in double_click_body
    assert "table.closePersistentEditor(item)" in row_goto_body
    assert "section not in {_SECTION_TRADES, _SECTION_POI}" in row_goto_body
    assert "date_text = self._item_text(table, row, date_column)" in row_goto_body
    assert "self.goto_requested.emit(chart_key, int(ts_ms))" in row_goto_body
    assert "chart_key not in self._active_chart_keys" not in row_goto_body


def test_row_goto_button_resolves_current_row_dynamically() -> None:
    source = _source(NOTEBOOK)
    button_body = _function_source(NOTEBOOK, "_set_goto_button_cell")
    clicked_body = _function_source(NOTEBOOK, "_on_row_goto_button_clicked")
    resolver_body = _function_source(NOTEBOOK, "_row_for_cell_widget")

    assert "def _on_row_goto_button_clicked" in source
    assert "def _row_for_cell_widget" in source
    assert "row=row" not in button_body
    assert "button=button" in button_body
    assert "self._row_for_cell_widget(table, button)" in clicked_body
    assert "self._on_row_goto_clicked(table, row)" in clicked_body
    assert "table.cellWidget(row, column) is widget" in resolver_body
    assert "return -1" in resolver_body


def test_poi_row_goto_button_click_emits_dataset_key_and_timestamp() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["points_of_interest"]
        window._append_empty_row(table)
        row = table.rowCount() - 1
        date_item = table.item(row, 2)
        assert date_item is not None
        date_item.setText("2026-05-21 14:30")

        captured: list[tuple[str, int]] = []
        window.goto_requested.connect(
            lambda emitted_key, emitted_ts: captured.append(
                (str(emitted_key), int(emitted_ts))
            )
        )

        button = table.cellWidget(row, 0)
        assert isinstance(button, QToolButton)
        button.click()

        expected_ts = int(
            datetime(2026, 5, 21, 14, 30, tzinfo=timezone.utc).timestamp()
            * 1000
        )
        assert captured == [(chart_key, expected_ts)]
        assert window._status_label.text() == "Go To requested: 2026-05-21 14:30"
    finally:
        window.close()


def test_trade_row_goto_button_click_emits_without_creating_poi_markers() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["trades"]
        window._append_empty_row(table)
        row = table.rowCount() - 1
        date_item = table.item(row, 2)
        assert date_item is not None
        date_item.setText("2026-05-21 14:30")

        captured: list[tuple[str, int]] = []
        marker_emissions: list[bool] = []
        window.goto_requested.connect(
            lambda emitted_key, emitted_ts: captured.append(
                (str(emitted_key), int(emitted_ts))
            )
        )
        window.poi_markers_changed.connect(lambda: marker_emissions.append(True))

        button = table.cellWidget(row, 0)
        assert isinstance(button, QToolButton)
        button.click()

        expected_ts = int(
            datetime(2026, 5, 21, 14, 30, tzinfo=timezone.utc).timestamp()
            * 1000
        )
        assert captured == [(chart_key, expected_ts)]
        assert marker_emissions == []
        assert window.poi_markers_by_chart_key()[chart_key] == []
        assert window.pt_markers_by_chart_key()[chart_key] == []
    finally:
        window.close()


def test_new_trade_rows_have_unselected_direction_and_do_not_project_markers() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["trades"]
        window._append_empty_row(table)
        row = table.rowCount() - 1
        date_item = table.item(row, 2)
        assert date_item is not None
        date_item.setText("2026-05-21 14:30")

        combo = table.cellWidget(row, 3)
        assert isinstance(combo, QComboBox)
        assert [combo.itemText(index) for index in range(combo.count())] == [
            "",
            "Long",
            "Short",
        ]
        assert combo.currentText() == ""

        trade = window.chart_entries_payload()[0]["trades"][0]
        assert trade["direction"] == ""
        assert window.pt_markers_by_chart_key()[chart_key] == []
    finally:
        window.close()


def test_long_and_short_trade_rows_project_directional_pt_markers() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["trades"]
        window._append_empty_row(table)
        window._append_empty_row(table)
        for row, direction in ((0, "Long"), (1, "Short")):
            date_item = table.item(row, 2)
            assert date_item is not None
            date_item.setText(f"2026-05-2{row + 1} 14:30")
            combo = table.cellWidget(row, 3)
            assert isinstance(combo, QComboBox)
            combo.setCurrentText(direction)

        window._pt_long_marker_offset_spin.setValue(64)
        window._pt_short_marker_offset_spin.setValue(32)
        markers = window.pt_markers_by_chart_key()[chart_key]

        assert [marker["direction"] for marker in markers] == ["Long", "Short"]
        assert markers[0]["marker_side"] == "below"
        assert markers[0]["marker_offset"] == 64
        assert markers[1]["marker_side"] == "above"
        assert markers[1]["marker_offset"] == -32
        for marker in markers:
            assert "starting_price" in marker
            assert "target_pct_movement" in marker
            assert "closing_price" in marker
            assert "outcome" in marker
            assert "note" in marker
    finally:
        window.close()


def test_notes_row_date_does_not_emit_go_to() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["notes"]
        window._append_empty_row(table)
        row = table.rowCount() - 1
        date_item = table.item(row, 1)
        assert date_item is not None
        date_item.setText("2026-05-21 14:30")
        button = table.cellWidget(row, 0)
        assert isinstance(button, QToolButton)
        assert button.text() == "Delete"

        captured: list[tuple[str, int]] = []
        window.goto_requested.connect(
            lambda emitted_key, emitted_ts: captured.append(
                (str(emitted_key), int(emitted_ts))
            )
        )

        window._on_table_cell_double_clicked(table, row, 1)

        assert captured == []
    finally:
        window.close()


def test_date_time_double_click_does_not_emit_go_to_for_navigation_tabs() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        captured: list[tuple[str, int]] = []
        window.goto_requested.connect(
            lambda emitted_key, emitted_ts: captured.append(
                (str(emitted_key), int(emitted_ts))
            )
        )

        for section in ("trades", "points_of_interest"):
            table = window._tables_by_chart_key[chart_key][section]
            window._append_empty_row(table)
            row = table.rowCount() - 1
            date_item = table.item(row, 2)
            assert date_item is not None
            date_item.setText("2026-05-21 14:30")
            window._on_table_cell_double_clicked(table, row, 2)

        assert captured == []
    finally:
        window.close()


def test_notebook_table_columns_match_required_layout() -> None:
    source = _source(NOTEBOOK)
    empty_body = _function_source(NOTEBOOK, "_append_empty_row")
    append_body = _function_source(NOTEBOOK, "_append_row_payload")
    rows_body = _function_source(NOTEBOOK, "_rows_from_table")
    configure_body = _function_source(NOTEBOOK, "_configure_table_columns")
    delete_message_body = _function_source(NOTEBOOK, "_delete_confirmation_message")

    assert "_GOTO_COLUMN = 0" in source
    assert "_ACTION_BUTTON_WIDTH = 58" in source
    assert "_SUPPORTED_DATE_TIME_TEXT = \"9999-12-31 23:59:59\"" in source
    assert "_POI_TITLE_COLUMN_WIDTH = 300" in source
    assert "self._increase_window_font(point_delta=1)" in source
    assert "def _apply_bold_tab_font" in source
    assert "_DATE_COLUMN" not in source
    assert "QHeaderView.Stretch" in configure_body
    assert "table.setColumnWidth(3, _POI_TITLE_COLUMN_WIDTH)" in configure_body
    assert "table.setItem(row_index, date_column, date_item)" in append_body
    assert "self._set_delete_button_cell(table, row_index)" in append_body
    assert "table.setItem(row_index, 2, self._table_item(str(payload.get(\"note\"" in append_body
    assert '"direction": ""' in empty_body
    assert 'self._set_combo_cell(table, row_index, 3, ("", "Long", "Short")' in append_body
    assert "enumerate(numeric_keys, start=4)" in append_body
    assert "self._set_combo_cell(table, row_index, 7" in append_body
    assert "table.setItem(row_index, 8" in append_body
    assert "table.setItem(row_index, 3, self._table_item(str(payload.get(\"title\"" in append_body
    assert "table.setItem(row_index, 4, self._table_item(str(payload.get(\"description\"" in append_body
    assert "date_text = self._item_text(table, row, date_column)" in rows_body
    assert '"note": self._item_text(table, row, 2)' in rows_body
    assert '"direction": self._combo_text(table, row, 3)' in rows_body
    assert '"starting_price": self._float_or_none(self._item_text(table, row, 4))' in rows_body
    assert '"target_pct_movement": self._float_or_none(self._item_text(table, row, 5))' in rows_body
    assert '"closing_price": self._float_or_none(self._item_text(table, row, 6))' in rows_body
    assert '"outcome": self._combo_text(table, row, 7) or "Good"' in rows_body
    assert '"note": self._item_text(table, row, 8)' in rows_body
    assert '"title": self._item_text(table, row, 3)' in rows_body
    assert '"description": self._item_text(table, row, 4)' in rows_body
    assert "asset_bought" not in append_body
    assert "asset_bought" not in rows_body
    assert "Delete this note?" in delete_message_body
    assert "Delete this potential trade?" in delete_message_body
    assert "Delete this point of interest?" in delete_message_body
    assert "This action cannot be undone." in delete_message_body


def test_annotation_offset_controls_are_notebook_state() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        assert window.annotation_settings_payload() == {
            "poi_marker_offset": DEFAULT_POI_MARKER_OFFSET,
            "pt_long_marker_offset": DEFAULT_PT_LONG_MARKER_OFFSET,
            "pt_short_marker_offset": DEFAULT_PT_SHORT_MARKER_OFFSET,
        }

        emissions: list[bool] = []
        window.poi_markers_changed.connect(lambda: emissions.append(True))
        window._poi_marker_offset_spin.setValue(34)
        window._pt_long_marker_offset_spin.setValue(68)
        window._pt_short_marker_offset_spin.setValue(24)

        settings = window.annotation_settings_payload()
        assert emissions == [True, True, True]
        assert settings == {
            "poi_marker_offset": 34,
            "pt_long_marker_offset": 68,
            "pt_short_marker_offset": 24,
        }
        assert window.current_notebook().to_dict()["annotation_settings"] == settings

        notebook = HistoricalNotebook(
            schema_version=HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
            object_type=HISTORICAL_NOTEBOOK_OBJECT_TYPE,
            notebook_id="offset_notebook",
            content_hash="",
            display_name="Offset Notebook",
            description="",
            created_at_ms=1000,
            updated_at_ms=2000,
            annotation_settings={
                "poi_marker_offset": 42,
                "pt_long_marker_offset": 84,
                "pt_short_marker_offset": 21,
            },
            chart_entries=(
                {
                    "chart_key": chart_key,
                    "dataset": dataset,
                    "last_seen_position": 1,
                    "notes": [],
                    "trades": [],
                    "points_of_interest": [],
                },
            ),
        )
        window.set_notebook(notebook)

        assert window.annotation_marker_offsets() == {
            "poi_marker_offset": 42,
            "pt_long_marker_offset": 84,
            "pt_short_marker_offset": 21,
        }
    finally:
        window.close()


def test_notebook_window_tracks_dirty_state_for_editor_changes() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        assert window.is_dirty() is False

        window._name_edit.setText("Edited notebook")
        assert window.is_dirty() is True
        window.mark_clean()

        window._description_edit.setPlainText("Edited description")
        assert window.is_dirty() is True
        window.mark_clean()

        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        assert window.is_dirty() is True
        window.mark_clean()

        notes_table = window._tables_by_chart_key[chart_key]["notes"]
        window._append_empty_row(notes_table)
        assert window.is_dirty() is True
        window.mark_clean()

        note_item = notes_table.item(0, 2)
        assert note_item is not None
        note_item.setText("Tracked note")
        assert window.is_dirty() is True
        window.mark_clean()

        trades_table = window._tables_by_chart_key[chart_key]["trades"]
        window._append_empty_row(trades_table)
        window.mark_clean()
        direction_combo = trades_table.cellWidget(0, 3)
        assert isinstance(direction_combo, QComboBox)
        direction_combo.setCurrentText("Long")
        assert window.is_dirty() is True
        window.mark_clean()

        window._poi_marker_offset_spin.setValue(DEFAULT_POI_MARKER_OFFSET + 1)
        assert window.is_dirty() is True
        window.mark_clean()

        window._confirm_row_delete = lambda _section: True
        delete_button = notes_table.cellWidget(0, 0)
        assert isinstance(delete_button, QToolButton)
        delete_button.click()
        assert window.is_dirty() is True
    finally:
        window.close()


def test_notebook_window_clean_states_after_load_save_and_reset() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    notebook = HistoricalNotebook(
        schema_version=HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
        object_type=HISTORICAL_NOTEBOOK_OBJECT_TYPE,
        notebook_id="clean_state_notebook",
        content_hash="",
        display_name="Clean State",
        description="Loaded description",
        created_at_ms=1000,
        updated_at_ms=2000,
        annotation_settings={
            "poi_marker_offset": 42,
            "pt_long_marker_offset": 84,
            "pt_short_marker_offset": 21,
        },
        chart_entries=(
            {
                "chart_key": chart_key,
                "dataset": dataset,
                "last_seen_position": 1,
                "notes": [{"row_id": "note_1", "date_text": "", "ts_ms": None, "note": "Loaded"}],
                "trades": [],
                "points_of_interest": [],
            },
        ),
    )
    window = HistoricalNotebookWindow()
    try:
        window.set_notebook(notebook)
        assert window.is_dirty() is False

        window._name_edit.setText("Dirty")
        assert window.is_dirty() is True
        window.mark_saved(notebook)
        assert window.is_dirty() is False

        window._description_edit.setPlainText("Dirty again")
        assert window.is_dirty() is True
        window.reset_notebook(status="New notebook ready.")
        assert window.is_dirty() is False
    finally:
        window.close()


class _FakeDirtyNotebook:
    def __init__(self, dirty: bool = True) -> None:
        self._dirty = dirty
        self.cleaned = False

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self.cleaned = True
        self._dirty = False


class _FakeMessageBox:
    Warning = object()
    AcceptRole = object()
    DestructiveRole = object()
    RejectRole = object()

    clicked_label = "Cancel"
    last: "_FakeMessageBox | None" = None

    def __init__(self, _parent) -> None:
        self.buttons: dict[str, object] = {}
        self.labels: list[str] = []
        self.informative_text = ""
        _FakeMessageBox.last = self

    def setIcon(self, _icon) -> None:
        return None

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setText(self, _text: str) -> None:
        return None

    def setInformativeText(self, text: str) -> None:
        self.informative_text = text

    def addButton(self, label: str, _role) -> object:
        button = object()
        self.buttons[label] = button
        self.labels.append(label)
        return button

    def setDefaultButton(self, _button) -> None:
        return None

    def exec(self) -> int:
        return 0

    def clickedButton(self) -> object | None:
        return self.buttons.get(type(self).clicked_label)


def test_dirty_notebook_confirmation_save_discard_and_cancel(monkeypatch) -> None:
    monkeypatch.setattr(hdm_module, "QMessageBox", _FakeMessageBox)

    saves: list[bool] = []
    notebook = _FakeDirtyNotebook()
    fake_self = SimpleNamespace(
        _notebook_window=notebook,
        _on_save_notebook=lambda *, show_success_message=True: saves.append(
            bool(show_success_message)
        )
        or True,
    )

    _FakeMessageBox.clicked_label = "Save"
    assert HistoricalDataManagerWindow._confirm_dirty_notebook_action(
        fake_self,
        action_label="closing the notebook",
    ) is True
    assert saves == [False]
    assert _FakeMessageBox.last is not None
    assert _FakeMessageBox.last.labels == ["Save", "Don't Save", "Cancel"]
    assert "closing the notebook" in _FakeMessageBox.last.informative_text

    saves.clear()
    notebook = _FakeDirtyNotebook()
    fake_self = SimpleNamespace(
        _notebook_window=notebook,
        _on_save_notebook=lambda *, show_success_message=True: saves.append(
            bool(show_success_message)
        )
        or True,
    )
    _FakeMessageBox.clicked_label = "Don't Save"
    assert HistoricalDataManagerWindow._confirm_dirty_notebook_action(
        fake_self,
        action_label="opening another notebook",
    ) is True
    assert saves == []
    assert notebook.cleaned is True

    notebook = _FakeDirtyNotebook()
    fake_self = SimpleNamespace(
        _notebook_window=notebook,
        _on_save_notebook=lambda *, show_success_message=True: True,
    )
    _FakeMessageBox.clicked_label = "Cancel"
    assert HistoricalDataManagerWindow._confirm_dirty_notebook_action(
        fake_self,
        action_label="creating a new notebook",
    ) is False
    assert notebook.cleaned is False


def test_dirty_notebook_confirmation_save_failure_aborts(monkeypatch) -> None:
    monkeypatch.setattr(hdm_module, "QMessageBox", _FakeMessageBox)
    notebook = _FakeDirtyNotebook()
    fake_self = SimpleNamespace(
        _notebook_window=notebook,
        _on_save_notebook=lambda *, show_success_message=True: False,
    )

    _FakeMessageBox.clicked_label = "Save"
    assert HistoricalDataManagerWindow._confirm_dirty_notebook_action(
        fake_self,
        action_label="closing the notebook",
    ) is False
    assert notebook.cleaned is False


def test_row_delete_buttons_confirm_and_delete_selected_row() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["notes"]
        window._append_empty_row(table)
        window._append_empty_row(table)
        assert table.rowCount() == 2
        first = table.item(0, 2)
        second = table.item(1, 2)
        assert first is not None
        assert second is not None
        first.setText("keep")
        second.setText("delete")

        confirmations: list[str] = []
        window._confirm_row_delete = lambda section: confirmations.append(section) or True
        button = table.cellWidget(1, 0)
        assert isinstance(button, QToolButton)
        button.click()

        assert confirmations == ["notes"]
        assert table.rowCount() == 1
        assert window.chart_entries_payload()[0]["notes"][0]["note"] == "keep"
    finally:
        window.close()


def test_row_delete_confirmation_cancel_leaves_data_unchanged() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["trades"]
        window._append_empty_row(table)
        assert table.rowCount() == 1

        confirmations: list[str] = []
        window._confirm_row_delete = lambda section: confirmations.append(section) and False
        button = table.cellWidget(0, 1)
        assert isinstance(button, QToolButton)
        button.click()

        assert confirmations == ["trades"]
        assert table.rowCount() == 1
        assert len(window.chart_entries_payload()[0]["trades"]) == 1
    finally:
        window.close()


def test_poi_delete_updates_runtime_markers_once() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    window = HistoricalNotebookWindow()
    try:
        window.refresh_from_chart_options(
            [
                {
                    "position": 1,
                    "label": "Position 1: bybit / linear / BTCUSDT / 30m",
                    "dataset": dataset,
                }
            ]
        )
        table = window._tables_by_chart_key[chart_key]["points_of_interest"]
        window._append_empty_row(table)
        window._append_empty_row(table)
        first_date = table.item(0, 2)
        second_date = table.item(1, 2)
        first_title = table.item(0, 3)
        second_title = table.item(1, 3)
        assert first_date is not None
        assert second_date is not None
        assert first_title is not None
        assert second_title is not None
        first_date.setText("2026-05-21 14:30")
        second_date.setText("2026-05-22 15:30")
        first_title.setText("remove")
        second_title.setText("keep")

        emissions: list[bool] = []
        window.poi_markers_changed.connect(lambda: emissions.append(True))
        window._confirm_row_delete = lambda _section: True
        emissions.clear()

        button = table.cellWidget(0, 1)
        assert isinstance(button, QToolButton)
        button.click()

        markers = window.poi_markers_by_chart_key()[chart_key]
        assert len(emissions) == 1
        assert len(markers) == 1
        assert markers[0]["title"] == "keep"
    finally:
        window.close()


def test_legacy_trade_fields_load_without_crashing_and_are_ignored_by_editor() -> None:
    _qapp()
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }
    chart_key = notebook_chart_key(dataset)
    notebook = HistoricalNotebook(
        schema_version=HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
        object_type=HISTORICAL_NOTEBOOK_OBJECT_TYPE,
        notebook_id="legacy_trade_notebook",
        content_hash="",
        display_name="Legacy Trades",
        description="",
        created_at_ms=1000,
        updated_at_ms=2000,
        chart_entries=(
            {
                "chart_key": chart_key,
                "dataset": dataset,
                "last_seen_position": 1,
                "notes": [],
                "trades": [
                    {
                        "row_id": "trade_1",
                        "date_text": "2026-05-21 14:30",
                        "ts_ms": 1779373800000,
                        "direction": "Long",
                        "starting_price": 100000.0,
                        "target_pct_movement": 2.5,
                        "closing_price": 102500.0,
                        "equity": 1000.0,
                        "leverage": 3.0,
                        "asset_bought": 0.03,
                        "outcome": "Good",
                        "note": "Legacy row",
                    }
                ],
                "points_of_interest": [],
            },
        ),
    )
    window = HistoricalNotebookWindow()
    try:
        window.set_notebook(notebook)
        payload = window.chart_entries_payload()
        trade = payload[0]["trades"][0]

        assert trade["direction"] == "Long"
        assert trade["starting_price"] == 100000.0
        assert trade["target_pct_movement"] == 2.5
        assert trade["closing_price"] == 102500.0
        assert trade["outcome"] == "Good"
        assert trade["note"] == "Legacy row"
        assert "equity" not in trade
        assert "leverage" not in trade
        assert "asset_bought" not in trade
    finally:
        window.close()


def test_notebook_chart_key_uses_dataset_identity_not_position() -> None:
    dataset = {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }

    assert notebook_chart_key(dataset) == "bybit|linear|btcusdt|30m"

    source = _source(NOTEBOOK)
    entry_body = _function_source(NOTEBOOK, "_entry_from_chart_option")
    assert "notebook_chart_key" in source
    assert "last_seen_position" in entry_body
    assert "position|" not in source


def test_refresh_preserves_missing_tabs_and_reactivates_by_dataset_key() -> None:
    source = _source(NOTEBOOK)
    refresh_body = _function_source(NOTEBOOK, "refresh_from_chart_options")

    assert "_active_chart_keys" in source
    assert "_chart_entries_by_key" in source
    assert "Chart is not currently active; notes are preserved." in source
    assert "last_seen_position" in refresh_body
    assert "_mark_chart_tab_active(chart_key, chart_key in self._active_chart_keys)" in source


def test_chart_tab_deletion_is_confirmed_and_refresh_can_recreate() -> None:
    source = _source(NOTEBOOK)
    close_body = _function_source(NOTEBOOK, "_on_chart_tab_close_requested")
    refresh_body = _function_source(NOTEBOOK, "refresh_from_chart_options")

    assert "setTabsClosable(True)" in source
    assert "QMessageBox.question" in close_body
    assert "_chart_entries_by_key.pop(chart_key" in close_body
    assert "self._chart_entries_by_key[chart_key] = entry" in refresh_body
    assert "no permanent blacklist" not in source.lower()


def test_date_go_to_emits_request_without_direct_chart_mutation() -> None:
    source = _source(NOTEBOOK)
    body = _function_source(NOTEBOOK, "_on_row_goto_clicked")

    assert "goto_requested = Signal(str, object)" in source
    assert "self.goto_requested.emit(chart_key, int(ts_ms))" in body
    assert "date_text = self._item_text(table, row, date_column)" in body
    assert "Go To requested:" in body
    assert "Go To failed: Date / Time is empty." in body
    assert "Go To failed: Date / Time could not be parsed." in body
    assert "chart_key not in self._active_chart_keys" not in body
    assert "center_view_on_timestamp_ms" not in source
    assert "center_on_index" not in source


def test_data_manager_routes_notebook_go_to_through_panel_controller_path() -> None:
    source = _source(HDM)
    body = _function_source(HDM, "_on_notebook_goto_requested")
    panel_lookup_body = _function_source(HDM, "_panel_for_notebook_chart_key")

    assert "notebook_window.goto_requested.connect(self._on_notebook_goto_requested)" in source
    assert "self._panel_for_notebook_chart_key(chart_key)" in body
    assert "center_on_notebook_timestamp" in body
    assert "Notebook Go To requested" in body
    assert "Notebook Go To failed: chart not active" in body
    assert "Notebook Go To failed: chart timeline is not ready" in body
    assert "Notebook Go To centered" in body
    assert "notebook_chart_key(dataset) == target_key" in panel_lookup_body


def test_notebook_window_is_non_modal_top_level_window() -> None:
    source = _source(NOTEBOOK)

    assert "class HistoricalNotebookWindow(QMainWindow)" in source
    assert "setWindowModality" not in source
    assert "ApplicationModal" not in source
    assert "WindowModal" not in source


def test_poi_marker_checkbox_and_signal_exist() -> None:
    source = _source(NOTEBOOK)

    assert "Show notebook markers on charts" in source
    assert "POI marker offset" in source
    assert "PT Long marker offset" in source
    assert "PT Short marker offset" in source
    assert "poi_markers_changed = Signal()" in source
    assert "poi_overlay_requested = Signal(bool)" in source
    assert "poi_markers_by_chart_key" in source
    assert "pt_markers_by_chart_key" in source


def test_poi_marker_signal_emission_is_guarded_against_table_sync_reentry() -> None:
    source = _source(NOTEBOOK)
    helper_body = _function_source(NOTEBOOK, "_emit_poi_markers_changed")

    assert "_syncing_from_tables" in source
    assert "_suppress_notebook_change_signals" in source
    assert "def _emit_poi_markers_changed" in source
    assert "self._syncing_from_tables or self._suppress_notebook_change_signals" in helper_body
    assert source.count("self.poi_markers_changed.emit()") == 1
    assert "self.poi_markers_changed.emit()" in helper_body


def test_poi_marker_collection_syncs_tables_without_emitting_markers() -> None:
    body = _function_source(NOTEBOOK, "poi_markers_by_chart_key")
    pt_body = _function_source(NOTEBOOK, "pt_markers_by_chart_key")
    sync_body = _function_source(NOTEBOOK, "_sync_entries_for_marker_collection")

    assert "self._sync_entries_for_marker_collection()" in body
    assert "self._sync_entries_for_marker_collection()" in pt_body
    assert "self._syncing_from_tables = True" in sync_body
    assert "self._suppress_notebook_change_signals = True" in sync_body
    assert "self._sync_all_entries_from_tables()" in sync_body
    assert "finally:" in sync_body
    assert "self._build_poi_markers_by_chart_key_from_entries()" in body
    assert "self._build_pt_markers_by_chart_key_from_entries()" in pt_body
    assert "poi_markers_changed.emit" not in body
    assert "poi_markers_changed.emit" not in pt_body


def test_poi_table_sync_uses_guarded_marker_emit() -> None:
    body = _function_source(NOTEBOOK, "_sync_entry_from_table")

    assert "section in {_SECTION_TRADES, _SECTION_POI}" in body
    assert "self._emit_poi_markers_changed()" in body
    assert "self.poi_markers_changed.emit()" not in body


def test_data_manager_has_poi_marker_reentry_guard() -> None:
    source = _source(HDM)
    changed_body = _function_source(HDM, "_on_notebook_poi_markers_changed")
    overlay_body = _function_source(HDM, "_on_notebook_poi_overlay_requested")
    apply_body = _function_source(HDM, "_apply_notebook_poi_markers")

    assert "_applying_notebook_poi_markers" in source
    assert "if self._applying_notebook_poi_markers:" in changed_body
    assert "if self._applying_notebook_poi_markers:" in overlay_body
    assert "self._applying_notebook_poi_markers = True" in apply_body
    assert "finally:" in apply_body
    assert "self._applying_notebook_poi_markers = False" in apply_body
    assert "notebook_window.poi_markers_by_chart_key()" in apply_body
    assert "notebook_window.pt_markers_by_chart_key()" in apply_body
    assert "notebook_window.annotation_marker_offsets()" in apply_body
    assert "set_notebook_pt_markers" in apply_body


def test_historical_data_manager_coordinates_notebook_persistence() -> None:
    source = _source(HDM)

    assert "HistoricalNotebookStore" in source
    assert "HistoricalNotebookManagerDialog" in source
    assert '"chart_presets" / "notebooks"' in source
    assert "def _on_save_notebook" in source
    assert "def _on_load_notebook" in source
    assert "def _on_open_notebook_manager" in source
    assert "save_notebook" in source
    assert "load_notebook" in source
    assert "notebook_window.goto_requested.connect" in source
