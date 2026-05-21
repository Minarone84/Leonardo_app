from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from leonardo.data.chart_presets.notebook_store import notebook_chart_key
from leonardo.gui.windows._historical_data_manager.notebook_window import (
    HistoricalNotebookWindow,
)
from PySide6.QtWidgets import QApplication, QToolButton


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
    assert '"Trades"' in source
    assert '"Point of Interest"' in source
    assert '"Date / Time"' in source
    assert '"Direction"' in source
    assert '"Long"' in source
    assert '"Short"' in source
    assert '"Good"' in source
    assert '"Bad"' in source
    assert '"Title"' in source
    assert '"Description"' in source


def test_all_notebook_tables_share_date_time_go_to_path() -> None:
    source = _source(NOTEBOOK)
    table_body = _function_source(NOTEBOOK, "_new_section_table")
    goto_button_body = _function_source(NOTEBOOK, "_set_goto_button_cell")
    row_goto_body = _function_source(NOTEBOOK, "_on_row_goto_clicked")
    goto_body = _function_source(NOTEBOOK, "_on_table_cell_double_clicked")

    assert '_NOTE_COLUMNS = ("Go", "Date / Time", "Note")' in source
    assert '"Go",\n    "Date / Time",\n    "Direction",' in source
    assert '_POI_COLUMNS = ("Go", "Date / Time", "Title", "Description")' in source
    assert "notes_table = self._new_section_table" in source
    assert "trades_table = self._new_section_table" in source
    assert "poi_table = self._new_section_table" in source
    assert "self._set_goto_button_cell(table, row_index)" in source
    assert "button.setText(\"Go\")" in goto_button_body
    assert "Center chart on this row's Date / Time" in goto_button_body
    assert "self._on_row_goto_button_clicked(" in goto_button_body
    assert "button=button" in goto_button_body
    assert "row=row" not in goto_button_body
    assert "cellDoubleClicked.connect" in table_body
    assert "_on_table_cell_double_clicked(table, row, column)" in table_body
    assert "if column != _DATE_COLUMN:" in goto_body
    assert "self._on_row_goto_clicked(table, row)" in goto_body
    assert "table.closePersistentEditor(item)" in row_goto_body
    assert "date_text = self._item_text(table, row, _DATE_COLUMN)" in row_goto_body
    assert "self.goto_requested.emit(chart_key, int(ts_ms))" in row_goto_body
    assert "chart_key not in self._active_chart_keys" not in row_goto_body
    assert "_SECTION_POI" not in goto_body


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
    assert "table.cellWidget(row, _GOTO_COLUMN) is widget" in resolver_body
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
        date_item = table.item(row, 1)
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


def test_notebook_table_columns_shift_row_sync_indexes_for_go_button() -> None:
    source = _source(NOTEBOOK)
    append_body = _function_source(NOTEBOOK, "_append_row_payload")
    rows_body = _function_source(NOTEBOOK, "_rows_from_table")

    assert "_GOTO_COLUMN = 0" in source
    assert "_DATE_COLUMN = 1" in source
    assert "table.setItem(row_index, _DATE_COLUMN, date_item)" in append_body
    assert "table.setItem(row_index, 2, self._table_item(str(payload.get(\"note\"" in append_body
    assert "self._set_combo_cell(table, row_index, 2" in append_body
    assert "enumerate(numeric_keys, start=3)" in append_body
    assert "self._set_combo_cell(table, row_index, 9" in append_body
    assert "table.setItem(row_index, 10" in append_body
    assert "table.setItem(row_index, 2, self._table_item(str(payload.get(\"title\"" in append_body
    assert "table.setItem(row_index, 3, self._table_item(str(payload.get(\"description\"" in append_body
    assert "date_text = self._item_text(table, row, _DATE_COLUMN)" in rows_body
    assert '"direction": self._combo_text(table, row, 2) or "Long"' in rows_body
    assert '"starting_price": self._float_or_none(self._item_text(table, row, 3))' in rows_body
    assert '"asset_bought": self._float_or_none(self._item_text(table, row, 8))' in rows_body
    assert '"outcome": self._combo_text(table, row, 9) or "Good"' in rows_body
    assert '"note": self._item_text(table, row, 10)' in rows_body
    assert '"title": self._item_text(table, row, 2)' in rows_body
    assert '"description": self._item_text(table, row, 3)' in rows_body


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
    assert "date_text = self._item_text(table, row, _DATE_COLUMN)" in body
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

    assert "Show POI markers on charts" in source
    assert "poi_markers_changed = Signal()" in source
    assert "poi_overlay_requested = Signal(bool)" in source
    assert "poi_markers_by_chart_key" in source


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

    assert "self._syncing_from_tables = True" in body
    assert "self._suppress_notebook_change_signals = True" in body
    assert "self._sync_all_entries_from_tables()" in body
    assert "finally:" in body
    assert "self._build_poi_markers_by_chart_key_from_entries()" in body
    assert "poi_markers_changed.emit" not in body


def test_poi_table_sync_uses_guarded_marker_emit() -> None:
    body = _function_source(NOTEBOOK, "_sync_entry_from_table")

    assert "section == _SECTION_POI" in body
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


def test_historical_data_manager_coordinates_notebook_persistence() -> None:
    source = _source(HDM)

    assert "HistoricalNotebookStore" in source
    assert '"chart_presets" / "notebooks"' in source
    assert "def _on_save_notebook" in source
    assert "def _on_load_notebook" in source
    assert "def _on_assign_notebook_to_workspace_snapshot" in source
    assert "save_notebook" in source
    assert "load_notebook" in source
    assert "notebook_window.goto_requested.connect" in source
