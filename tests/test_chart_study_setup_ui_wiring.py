from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
DATA_STORE = ROOT / "src" / "leonardo" / "data" / "chart_presets" / "study_setup_store.py"
HDM = WINDOWS / "historical_data_manager_window.py"
WORKSPACE = WINDOWS / "historical_workspace_widget.py"
PANEL = WINDOWS / "historical_chart_panel.py"
DIALOGS = WINDOWS / "_historical_data_manager" / "study_setup_dialogs.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_historical_data_manager_defines_case_a_study_setup_actions() -> None:
    source = _source(HDM)

    assert "_action_save_study_setup" in source
    assert "_action_load_study_setup" in source
    assert 'QAction("Save Study Setup..."' in source
    assert 'QAction("Load Study Setup..."' in source
    assert "self._on_save_study_setup" in source
    assert "self._on_load_study_setup" in source


def test_file_menu_and_menu_bar_corner_reuse_same_qactions() -> None:
    source = _source(HDM)

    assert "menu_file.addAction(action_save_study_setup)" in source
    assert "menu_file.addAction(action_load_study_setup)" in source
    assert "def _build_menu_bar_corner_widget" in source
    assert "def _make_menu_bar_action_button" in source
    assert "setDefaultAction(action)" in source
    assert "action=self._action_save_study_setup" in source
    assert "action=self._action_load_study_setup" in source
    assert "historicalDataManagerMenuBarCornerWidget" in source
    assert "study_setup_toolbar = QToolBar" not in source


def test_study_setup_store_root_uses_runtime_chart_presets_path() -> None:
    body = _function_source(HDM, "_chart_study_setup_store_root")

    assert "self._ctx.config.runtime.data_dir" in body
    assert '"chart_presets"' in body
    assert '"study_setups"' in body
    assert "artifact_recipes" not in body
    assert "historical" not in body


def test_save_and_load_dialogs_have_required_concepts() -> None:
    source = _source(DIALOGS)

    assert "class SaveStudySetupDialog" in source
    assert "class LoadStudySetupDialog" in source
    assert "_name_edit" in source
    assert "_description_edit" in source
    assert "_source_chart_combo" in source
    assert "_target_chart_combo" in source
    assert "Append to existing studies" in source
    assert "Replace existing studies" in source
    assert "Study Recap" in source
    assert "Created from" in source


def test_workspace_exposes_narrow_embedded_chart_accessors() -> None:
    source = _source(WORKSPACE)

    assert "def list_embedded_chart_panels" in source
    assert "def get_panel_by_position" in source
    assert "return self._chart_slots[index]" in source


def test_chart_panel_exports_and_loads_serialized_studies_through_panel_owner() -> None:
    source = _source(PANEL)
    apply_body = _function_source(PANEL, "apply_serialized_study_setup")
    restore_body = _function_source(PANEL, "_restore_serialized_study_style")

    assert "def export_serialized_studies" in source
    assert "serialize_chart_study(study)" in source
    assert "def apply_serialized_study_setup" in source
    assert "deserialize_chart_study_payload" in apply_body
    assert "self._controller.apply_financial_tool(controller_payload)" in apply_body
    assert "mode: str = \"append\"" in source
    assert "normalized_mode == \"replace\"" in apply_body
    assert "remove_study_instance" in apply_body
    assert "deserialize_study_style_payload" in restore_body
    assert "_reapply_study_render_series" in restore_body
    assert "runtime.render_keys" not in apply_body


def test_data_manager_save_and_load_paths_use_store_and_panel_helpers() -> None:
    save_body = _function_source(HDM, "_on_save_study_setup")
    load_body = _function_source(HDM, "_on_load_study_setup")

    assert "ChartStudySetupStore" in _source(HDM)
    assert "panel.export_serialized_studies()" in save_body
    assert "store.create_setup" in save_body
    assert "store.save_setup" in save_body
    assert "store.load_setup" in load_body
    assert "evaluate_study_setup_compatibility" in load_body
    assert "compatibility_report.can_load" in load_body
    assert "format_compatibility_report" in load_body
    assert "panel.apply_serialized_study_setup" in load_body
    assert "dialog.load_mode()" in load_body


def test_chart_preset_data_store_still_has_no_gui_imports() -> None:
    source = _source(DATA_STORE)

    assert "leonardo.gui" not in source
    assert "PySide" not in source
