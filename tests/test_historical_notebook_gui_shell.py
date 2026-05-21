from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
HDM = WINDOWS / "historical_data_manager_window.py"
PRIVATE = WINDOWS / "_historical_data_manager"
NOTEBOOK = PRIVATE / "notebook_window.py"
INIT = PRIVATE / "__init__.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_historical_data_manager_replaces_historical_menu_with_notes_menu() -> None:
    source = _source(HDM)

    assert 'menu_bar.addMenu("Notes")' in source
    assert 'menu_bar.addMenu("Historical")' not in source
    assert "_menu_notes" in source
    assert "_menu_historical" not in source


def test_notes_menu_defines_notebook_shell_actions() -> None:
    source = _source(HDM)

    assert "_action_create_notebook" in source
    assert "_action_save_notebook" in source
    assert "_action_load_notebook" in source
    assert "_action_assign_notebook_to_workspace_snapshot" in source
    assert 'QAction("Create New Notebook"' in source
    assert 'QAction("Save Notebook"' in source
    assert 'QAction("Load Notebook"' in source
    assert 'QAction("Assign Notebook to Workspace Snapshot"' in source
    assert "menu_notes.addAction(action_create_notebook)" in source
    assert "menu_notes.addAction(action_save_notebook)" in source
    assert "menu_notes.addAction(action_load_notebook)" in source
    assert "menu_notes.addAction(action_assign_notebook)" in source


def test_create_notebook_action_opens_notebook_gui_shell() -> None:
    source = _source(HDM)

    assert "HistoricalNotebookWindow" in source
    assert "def _on_create_notebook" in source
    assert "def _refresh_notebook_from_workspace" in source
    assert "refresh_requested.connect(self._refresh_notebook_from_workspace)" in source
    assert "refresh_from_chart_options(self._chart_options())" in source
    assert "self._notebook_window.show()" in source
    assert "self._notebook_window.raise_()" in source
    assert "self._notebook_window.activateWindow()" in source


def test_notebook_menu_shell_does_not_implement_persistence_or_snapshot_schema() -> None:
    source = _source(HDM) + "\n" + _source(NOTEBOOK)

    assert "NotebookStore" not in source
    assert "notebook_ref" not in source
    assert "save_notebook(" not in source
    assert "load_notebook(" not in source
    assert "workspace_snapshot_store" not in _source(NOTEBOOK)


def test_notebook_window_gui_shell_structure() -> None:
    source = _source(NOTEBOOK)

    assert "class HistoricalNotebookWindow(QMainWindow)" in source
    assert "refresh_requested = Signal()" in source
    assert "QTabWidget" in source
    assert "QPlainTextEdit" in source
    assert "Refresh Charts" in source
    assert "Assigned snapshot: Not assigned" in source
    assert '"Notes"' in source
    assert '"Trades"' in source
    assert '"Point of Interest"' in source
    assert "def refresh_from_chart_options" in source
    assert "setTabTextColor" in source
    assert "Chart is not currently active; notes are preserved." in source


def test_historical_data_manager_private_package_exports_notebook_window() -> None:
    source = _source(INIT)

    assert "HistoricalNotebookWindow" in source
    assert '"HistoricalNotebookWindow"' in source
