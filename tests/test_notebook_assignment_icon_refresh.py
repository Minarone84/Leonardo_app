from __future__ import annotations

import ast
from pathlib import Path

from leonardo.gui.windows.historical_data_manager_window import (
    HistoricalDataManagerWindow,
)


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
HDM = WINDOWS / "historical_data_manager_window.py"
NOTEBOOK_MANAGER = WINDOWS / "_historical_data_manager" / "notebook_manager_dialog.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


class _FakeAction:
    def __init__(self) -> None:
        self.enabled: bool | None = None
        self.tooltip = ""
        self.status_tip = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def setStatusTip(self, text: str) -> None:
        self.status_tip = text


class _FakeWindow:
    _set_current_workspace_notebook_ref = (
        HistoricalDataManagerWindow._set_current_workspace_notebook_ref
    )
    _sync_open_assigned_notebook_action = (
        HistoricalDataManagerWindow._sync_open_assigned_notebook_action
    )
    _on_notebook_assignment_changed = (
        HistoricalDataManagerWindow._on_notebook_assignment_changed
    )


def _window(*, snapshot_id: str | None = "snap_current") -> _FakeWindow:
    window = _FakeWindow()
    window._current_workspace_snapshot_id = snapshot_id
    window._current_workspace_notebook_ref = None
    window._action_open_assigned_notebook = _FakeAction()
    return window


def test_assignment_to_current_snapshot_refreshes_notebook_indicator() -> None:
    window = _window(snapshot_id="snap_current")
    notebook_ref = {
        "notebook_id": "nb_1",
        "display_name": "Notebook 1",
    }

    window._on_notebook_assignment_changed("snap_current", notebook_ref)

    assert window._current_workspace_notebook_ref == notebook_ref
    action = window._action_open_assigned_notebook
    assert action.enabled is True
    assert action.tooltip == "Open the notebook assigned to the current workspace snapshot."
    assert action.status_tip == "Open the notebook assigned to the current workspace snapshot."


def test_assignment_to_other_snapshot_does_not_refresh_current_indicator() -> None:
    window = _window(snapshot_id="snap_current")
    existing_ref = {
        "notebook_id": "nb_existing",
        "display_name": "Existing Notebook",
    }
    window._set_current_workspace_notebook_ref(existing_ref)

    window._on_notebook_assignment_changed(
        "snap_other",
        {
            "notebook_id": "nb_other",
            "display_name": "Other Notebook",
        },
    )

    assert window._current_workspace_notebook_ref == existing_ref
    assert window._action_open_assigned_notebook.enabled is True


def test_unassign_from_current_snapshot_clears_notebook_indicator() -> None:
    window = _window(snapshot_id="snap_current")
    window._set_current_workspace_notebook_ref(
        {
            "notebook_id": "nb_1",
            "display_name": "Notebook 1",
        }
    )

    window._on_notebook_assignment_changed("snap_current", None)

    assert window._current_workspace_notebook_ref is None
    action = window._action_open_assigned_notebook
    assert action.enabled is False
    assert action.tooltip == "No notebook assigned to the current workspace snapshot."
    assert action.status_tip == "No notebook assigned to the current workspace snapshot."


def test_assignment_refresh_wiring_does_not_reload_workspace() -> None:
    manager_body = _function_source(HDM, "_on_open_notebook_manager")
    changed_body = _function_source(HDM, "_on_notebook_assignment_changed")
    save_body = _function_source(HDM, "_on_save_workspace_snapshot")
    load_body = _function_source(HDM, "_on_load_workspace_snapshot")
    manager_source = _source(NOTEBOOK_MANAGER)

    assert "notebook_assignment_changed = Signal(str, object)" in manager_source
    assert "self.notebook_assignment_changed.emit(target_summary.snapshot_id, dict(notebook_ref))" in manager_source
    assert "self.notebook_assignment_changed.emit(target_summary.snapshot_id, None)" in manager_source
    assert "dialog.notebook_assignment_changed.connect" in manager_body
    assert "self._on_notebook_assignment_changed" in manager_body
    assert "self._set_current_workspace_notebook_ref(notebook_ref)" in changed_body
    assert "self._set_current_workspace_notebook_ref(None)" in changed_body
    assert "load_workspace_snapshot_charts" not in changed_body
    assert "_refresh_notebook_from_workspace" not in changed_body
    assert "self._current_workspace_snapshot_id = saved.snapshot_id" in save_body
    assert "self._current_workspace_snapshot_id = snapshot.snapshot_id" in load_body


def test_assignment_refresh_path_does_not_write_json_directly() -> None:
    changed_body = _function_source(HDM, "_on_notebook_assignment_changed")

    forbidden = (
        "write_text",
        "json.dump",
        "open(",
        "save_snapshot",
        "save_notebook",
        "update_snapshot",
        "update_notebook",
    )
    for token in forbidden:
        assert token not in changed_body
