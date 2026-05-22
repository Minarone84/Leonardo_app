from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
HDM = WINDOWS / "historical_data_manager_window.py"
PRIVATE = WINDOWS / "_historical_data_manager"
NOTEBOOK = PRIVATE / "notebook_window.py"
MANAGER = PRIVATE / "notebook_manager_dialog.py"
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
    assert "_action_notebook_manager" in source
    assert "_action_save_notebook" in source
    assert "_action_load_notebook" in source
    assert "_action_open_assigned_notebook" in source
    assert 'QAction("Create New Notebook"' in source
    assert 'QAction("Open Notebook"' in source
    assert 'QAction("Notebook Manager..."' in source
    assert 'QAction("Save Notebook"' in source
    assert 'QAction("Load Notebook"' in source
    assert "menu_notes.addAction(action_create_notebook)" in source
    assert "menu_notes.addAction(action_open_assigned_notebook)" in source
    assert "menu_notes.addAction(action_notebook_manager)" in source
    assert "menu_notes.addAction(action_save_notebook)" in source
    assert "menu_notes.addAction(action_load_notebook)" in source
    assert "Assign Notebook to Workspace Snapshot" not in source


def test_create_notebook_action_opens_notebook_gui_shell() -> None:
    source = _source(HDM)

    assert "HistoricalNotebookWindow" in source
    assert "def _on_create_notebook" in source
    assert "def _refresh_notebook_from_workspace" in source
    assert "refresh_requested.connect(self._refresh_notebook_from_workspace)" in source
    assert "refresh_from_chart_options(self._chart_options())" in source
    assert "notebook_window.show()" in source
    assert "notebook_window.raise_()" in source
    assert "notebook_window.activateWindow()" in source


def test_notebook_persistence_is_coordinated_by_data_manager_not_window() -> None:
    manager_source = _source(HDM)
    notebook_source = _source(NOTEBOOK)
    dialog_source = _source(MANAGER)

    assert "HistoricalNotebookStore" in manager_source
    assert "HistoricalNotebookManagerDialog" in manager_source
    assert "def _notebook_store_root" in manager_source
    assert '"chart_presets" / "notebooks"' in manager_source
    assert "def _on_save_notebook" in manager_source
    assert "def _on_notebook_close_save_requested" in manager_source
    assert "close_save_requested.connect" in manager_source
    assert "self._on_notebook_close_save_requested" in manager_source
    assert "def _on_load_notebook" in manager_source
    assert "def _on_open_notebook_manager" in manager_source
    assert "def _on_assign_clicked" in dialog_source
    assert "HistoricalWorkspaceSnapshotStore" in dialog_source
    assert "Delete Notebook" in dialog_source
    assert "def _on_delete_clicked" in dialog_source
    assert "delete_notebook" in dialog_source
    assert "notebook_ref=None" in dialog_source
    assert "HistoricalNotebookStore" not in notebook_source
    assert "workspace_snapshot_store" not in notebook_source


def test_notebook_window_close_requests_data_manager_save_without_store_ownership() -> None:
    manager_source = _source(HDM)
    notebook_source = _source(NOTEBOOK)
    close_body = notebook_source[
        notebook_source.index("    def closeEvent") : notebook_source.index(
            "    def notebook_id"
        )
    ]

    assert "close_save_requested = Signal(object)" in notebook_source
    assert "self.close_save_requested.emit(event)" in close_body
    assert "event.isAccepted()" in close_body
    assert "_on_notebook_close_save_requested" in manager_source
    assert "_on_save_notebook(show_success_message=False)" in manager_source
    assert "HistoricalNotebookStore" not in notebook_source


def test_notebook_window_gui_shell_structure() -> None:
    source = _source(NOTEBOOK)

    assert "class HistoricalNotebookWindow(QMainWindow)" in source
    assert "refresh_requested = Signal()" in source
    assert "save_requested = Signal()" in source
    assert "load_requested = Signal()" in source
    assert "assign_requested = Signal()" in source
    assert "goto_requested = Signal(str, object)" in source
    assert "def reset_notebook" in source
    assert "QTabWidget" in source
    assert "QTableWidget" in source
    assert "QPlainTextEdit" in source
    assert "Refresh Charts" in source
    assert "Assigned snapshot: Not assigned" in source
    assert '"Notes"' in source
    assert '"Potential Trades"' in source
    assert '"Point of Interest"' in source
    assert "def refresh_from_chart_options" in source
    assert "setTabTextColor" in source
    assert "Chart is not currently active; notes are preserved." in source


def test_historical_data_manager_private_package_exports_notebook_window() -> None:
    source = _source(INIT)

    assert "HistoricalNotebookWindow" in source
    assert "HistoricalNotebookManagerDialog" in source
    assert '"HistoricalNotebookWindow"' in source
    assert '"HistoricalNotebookManagerDialog"' in source
