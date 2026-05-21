from __future__ import annotations

import ast
from pathlib import Path

from leonardo.data.chart_presets.notebook_store import notebook_chart_key


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
NOTEBOOK = WINDOWS / "_historical_data_manager" / "notebook_window.py"
HDM = WINDOWS / "historical_data_manager_window.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_notebook_window_has_structured_tabs_and_tables() -> None:
    source = _source(NOTEBOOK)

    assert "class HistoricalNotebookWindow(QMainWindow)" in source
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
    body = _function_source(NOTEBOOK, "_on_table_cell_double_clicked")

    assert "goto_requested = Signal(str, int)" in source
    assert "self.goto_requested.emit(chart_key, int(ts_ms))" in body
    assert "center_view_on_timestamp_ms" not in source
    assert "center_on_index" not in source


def test_poi_marker_checkbox_and_signal_exist() -> None:
    source = _source(NOTEBOOK)

    assert "Show POI markers on charts" in source
    assert "poi_markers_changed = Signal()" in source
    assert "poi_overlay_requested = Signal(bool)" in source
    assert "poi_markers_by_chart_key" in source


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
