from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
DATA_PRESETS = ROOT / "src" / "leonardo" / "data" / "chart_presets"
HDM = WINDOWS / "historical_data_manager_window.py"
WORKSPACE = WINDOWS / "historical_workspace_widget.py"
PANEL = WINDOWS / "historical_chart_panel.py"
CONTROLLER = ROOT / "src" / "leonardo" / "gui" / "historical_chart_controller.py"
DIALOGS = WINDOWS / "_historical_data_manager" / "workspace_snapshot_dialogs.py"
STUDY_STORE = DATA_PRESETS / "study_setup_store.py"
SNAPSHOT_STORE = DATA_PRESETS / "workspace_snapshot_store.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_historical_data_manager_defines_workspace_snapshot_actions() -> None:
    source = _source(HDM)

    assert "_action_save_workspace_snapshot" in source
    assert "_action_load_workspace_snapshot" in source
    assert 'QAction("Save Workspace Snapshot..."' in source
    assert 'QAction("Load Workspace Snapshot..."' in source
    assert "self._on_save_workspace_snapshot" in source
    assert "self._on_load_workspace_snapshot" in source


def test_file_menu_and_toolbar_reuse_workspace_snapshot_qactions() -> None:
    source = _source(HDM)

    assert "menu_file.addAction(action_save_workspace_snapshot)" in source
    assert "menu_file.addAction(action_load_workspace_snapshot)" in source
    assert "study_setup_toolbar.addAction(self._action_save_workspace_snapshot)" in source
    assert "study_setup_toolbar.addAction(self._action_load_workspace_snapshot)" in source


def test_workspace_snapshot_store_root_uses_runtime_chart_presets_path() -> None:
    body = _function_source(HDM, "_workspace_snapshot_store_root")

    assert "self._ctx.config.runtime.data_dir" in body
    assert '"chart_presets"' in body
    assert '"workspace_snapshots"' in body
    assert "artifact_recipes" not in body
    assert "historical" not in body


def test_workspace_snapshot_dialogs_have_required_concepts() -> None:
    source = _source(DIALOGS)

    assert "class SaveWorkspaceSnapshotDialog" in source
    assert "class LoadWorkspaceSnapshotDialog" in source
    assert "_name_edit" in source
    assert "_description_edit" in source
    assert "Workspace Recap" in source
    assert "Chart Recap" in source
    assert "_study_recap_lines" in source
    assert "Replace current workspace" in source
    assert "Load into current workspace" in source


def test_save_path_uses_snapshot_store_and_embedded_chart_export() -> None:
    source = _source(HDM)
    save_body = _function_source(HDM, "_on_save_workspace_snapshot")

    assert "HistoricalWorkspaceSnapshotStore" in source
    assert "workspace.export_workspace_snapshot_payload()" in save_body
    assert "store.create_snapshot" in save_body
    assert "store.save_snapshot" in save_body
    assert "detached_reserved_slot_count" in save_body


def test_load_path_preflights_and_uses_workspace_restore_helper() -> None:
    load_body = _function_source(HDM, "_on_load_workspace_snapshot")

    assert "store.load_snapshot" in load_body
    assert "evaluate_workspace_snapshot_compatibility" in load_body
    assert "compatibility_report.can_load" in load_body
    assert "format_compatibility_report" in load_body
    assert "workspace.load_workspace_snapshot_charts(charts, mode=load_mode)" in load_body
    assert "workspace.set_visualization_mode" in load_body
    assert "render_keys" not in load_body


def test_workspace_owns_snapshot_chart_placement_and_capacity() -> None:
    source = _source(WORKSPACE)
    load_body = _function_source(WORKSPACE, "load_workspace_snapshot_charts")

    assert "def export_workspace_snapshot_payload" in source
    assert "def detached_reserved_slot_count" in source
    assert "def available_embedded_slot_count" in source
    assert "def load_workspace_snapshot_charts" in source
    assert "_detached_slots" in load_body
    assert "_available_embedded_slot_indexes" in load_body
    assert "loaded_panels" in load_body
    assert "existing_panels" in load_body
    assert "open_workspace_snapshot_chart" in load_body


def test_panel_exports_and_defers_chart_local_snapshot_restore() -> None:
    source = _source(PANEL)
    export_body = _function_source(PANEL, "export_workspace_chart_snapshot")
    pending_body = _function_source(PANEL, "_apply_pending_workspace_snapshot_chart")

    assert "def export_workspace_chart_snapshot" in source
    assert "def open_workspace_snapshot_chart" in source
    assert "def restore_workspace_chart_viewport" in source
    assert "_pending_workspace_snapshot_chart" in source
    assert "export_serialized_studies()" in export_body
    assert "export_viewport_state()" in export_body
    assert "apply_serialized_study_setup(studies, mode=\"append\")" in pending_body
    assert "restore_workspace_chart_viewport" in pending_body
    assert "runtime.render_keys" not in pending_body


def test_controller_exports_viewport_state_from_session_truth() -> None:
    body = _function_source(CONTROLLER, "export_viewport_state")

    assert "global_index_to_ts_ms" in body
    assert "timeline_ts_ms" in body
    assert "center_ts_ms" in body
    assert "visible_bars" in body
    assert "fallback_global_index" in body


def test_chart_preset_data_stores_still_have_no_gui_imports() -> None:
    study_store_source = _source(STUDY_STORE)
    snapshot_store_source = _source(SNAPSHOT_STORE)

    assert "leonardo.gui" not in study_store_source
    assert "PySide" not in study_store_source
    assert "leonardo.gui" not in snapshot_store_source
    assert "PySide" not in snapshot_store_source
