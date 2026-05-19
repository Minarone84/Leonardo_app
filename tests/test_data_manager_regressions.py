from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo"
DATA_MANAGER = SRC / "gui" / "windows" / "_data_manager"
WINDOWS = SRC / "gui" / "windows"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_analysis_database_feature_builder_helper_is_gui_owned_shared_mapper() -> None:
    """Saved artifact column -> manifest feature mapping is shared GUI helper code.

    The mapper consumes Data Manager ``SavedArtifactColumn`` objects, so it is
    intentionally GUI-owned. It may be reused by recipe-creation/component-edit
    UI, but Database Builder must still not consume it for rebuild.
    """
    helper_path = DATA_MANAGER / "analysis_database_feature_builder.py"
    helper_source = _source(helper_path)
    helper_function = _function_source(helper_path, "build_manifest_features_from_saved_columns")

    assert "SavedArtifactColumn" in helper_source
    assert "saved_artifact_columns import SavedArtifactColumn" in helper_source
    assert "AnalysisFeatureSource" in helper_source
    assert "AnalysisDatabaseColumn" in helper_source
    assert "build_feature_source_id" in helper_source
    assert "build_database_column_name" in helper_source
    assert "AnalysisDatabaseStore" not in helper_source
    assert "materialize_database" not in helper_source
    assert "rebuild_database_with_features" not in helper_source
    assert "selected_columns: Sequence[SavedArtifactColumn]" in helper_function


def test_database_seed_creator_imports_shared_feature_builder_helper() -> None:
    """Seed creation may use the shared mapper; it should not define it locally."""
    path = DATA_MANAGER / "analysis_database_builder_widget.py"
    source = _source(path)

    assert "analysis_database_feature_builder import" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "def build_manifest_features_from_saved_columns" not in source
    assert "def _build_feature_source" not in source
    assert "build_feature_source_id" not in source
    assert "build_database_column_name" not in source


def test_database_builder_no_longer_consumes_saved_artifact_selection() -> None:
    """Database Builder must rebuild from its own manifest only.

    Creating a database recipe from checked artifact columns belongs to the
    Database seed creator. The database list/build widget must not keep the old
    two-phase artifact replacement flow alive, because rebuild means
    materialize the selected existing database by database_id.
    """
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    tree = _tree(path)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name.split(".")[0])

    assert "build_manifest_features_from_saved_columns" not in imported_names
    assert "SavedArtifactColumn" not in imported_names
    assert "set_selected_artifact_columns" not in source
    assert "Build / Rebuild Selected Database" not in source
    assert "artifact_selection_started" not in source
    assert "artifact_selection_finished" not in source
    assert "_artifact_selection_phase" not in source
    assert "rebuild_database_with_features" not in source


def test_database_builder_build_and_rebuild_buttons_use_existing_manifest_recipe() -> None:
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    build_source = _function_source(path, "_build_selected")
    rebuild_source = _function_source(path, "_rebuild_selected")
    materialize_source = _function_source(path, "_materialize_checked_manifest")

    assert "Build Selected Database" in source
    assert "Rebuild Selected Database" in source
    assert "Build / Rebuild Selected Database" not in source

    assert "_single_checked_manifest" in build_source
    assert "build_requested.emit(manifest)" in build_source
    assert "already materialized" in build_source
    assert "materialize_database" not in build_source

    assert "_single_checked_manifest" in rebuild_source
    assert "_materialize_checked_manifest" in rebuild_source
    assert "not materialized yet" in rebuild_source

    assert "materialize_database" in materialize_source
    assert "database_id=manifest.database_id" in materialize_source
    assert "build_draft_manifest" not in materialize_source
    assert "save_manifest" not in materialize_source
    assert "rebuild_database_with_features" not in materialize_source


def test_data_manager_wires_saved_artifacts_only_to_seed_creator() -> None:
    """Checked saved artifacts should feed draft creation, not database rebuild."""
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)" in source
    assert "self._artifact_selector.selection_changed.connect(self._on_saved_artifact_selection_changed)" not in source
    assert "self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)" not in source
    assert "artifact_selection_started" not in source
    assert "artifact_selection_finished" not in source
    assert "_on_database_artifact_selection_started" not in source
    assert "_on_database_artifact_selection_finished" not in source
    assert "_on_artifact_selection_exit_requested" not in source


def test_saved_artifact_preview_uses_exactly_one_checked_artifact() -> None:
    path = DATA_MANAGER / "saved_artifact_selector_widget.py"
    source = _source(path)
    preview_source = _function_source(path, "_preview_selected_artifact")
    button_source = _function_source(path, "_refresh_preview_button")

    assert "Preview Selected Artifact" in source
    assert "_single_checked_column" in preview_source
    assert "_single_checked_column() is not None" in button_source
    assert "currentItem" not in preview_source
    assert "_current_column" not in source


def test_dataframe_preview_adds_readable_timestamps_without_mutating_source_csv() -> None:
    path = DATA_MANAGER / "dataframe_preview_widget.py"
    source = _source(path)
    prepare_source = _function_source(path, "_prepare_preview_dataframe")

    assert "ts_utc" in source
    assert "ts_rome" in source
    assert "out = dataframe.copy()" in prepare_source
    assert "out.insert" in prepare_source
    assert "drop(columns=[\"time\"])" in source


def test_database_builder_component_edit_is_explicit_intent_only() -> None:
    """Database Builder may expose component-edit intent, but rebuild must stay manifest-only."""
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    edit_source = _function_source(path, "_edit_components_selected")

    assert "Edit Selected Database Components" in source
    assert "component_edit_requested" in source
    assert "_single_checked_manifest" in edit_source
    assert "component_edit_requested.emit(manifest)" in edit_source
    assert "AnalysisDatabaseComponentEditor" not in source
    assert "build_manifest_features_from_saved_columns" not in source
    assert "SavedArtifactColumn" not in source
    assert "materialize_database" not in edit_source
    assert "rebuild_database_with_features" not in source


def test_component_editor_dialog_is_explicit_recipe_edit_surface() -> None:
    """The component dialog owns GUI intent and delegates recipe changes to the data-layer editor."""
    path = DATA_MANAGER / "analysis_database_component_dialog.py"
    source = _source(path)

    assert "class AnalysisDatabaseComponentDialog" in source
    assert "AnalysisDatabaseComponentEditor" in source
    assert "load_saved_artifact_columns" in source
    assert "_EXISTING_COMPONENT_BRUSH" in source
    assert "QColor" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "SavedArtifactColumn" in source
    assert "replace_components" in source
    assert "add_components" in source
    assert "remove_components" in source
    assert "components_changed" in source
    assert "materialize_database" not in source
    assert "rebuild_database_with_features" not in source


def test_data_manager_opens_component_editor_from_database_builder_intent() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "AnalysisDatabaseComponentDialog" in source
    assert "self._database_list.component_edit_requested.connect(self._on_database_component_edit_requested)" in source
    assert "dialog.components_changed.connect(self._on_analysis_database_components_changed)" in source
    assert "selected_columns=self._selected_artifact_columns" not in source
    assert "self._artifact_selector.selection_changed.connect(self._on_saved_artifact_selection_changed)" not in source
    assert "self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)" not in source


def test_saved_artifact_selector_uses_shared_column_loader() -> None:
    path = DATA_MANAGER / "saved_artifact_selector_widget.py"
    source = _source(path)

    assert "saved_artifact_columns import" in source
    assert "load_saved_artifact_columns" in source
    assert "DerivedCsvStore" not in source
    assert "get_indicator_specs" not in source


def test_build_dialog_auto_loads_saved_artifacts_and_builds_manifest_recipe() -> None:
    path = DATA_MANAGER / "analysis_database_build_dialog.py"
    source = _source(path)

    assert "class AnalysisDatabaseBuildDialog" in source
    assert "load_saved_artifact_columns" in source
    assert "_EXISTING_COMPONENT_BRUSH" in source
    assert "QColor" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "materialize_database" in source
    assert "database_id=self._manifest.database_id" in source
    assert "AnalysisDatabaseComponentEditor" not in source
    assert "replace_components" not in source
    assert "add_components" not in source
    assert "remove_components" not in source
    assert "rebuild_database_with_features" not in source


def test_data_manager_opens_build_dialog_from_database_builder_intent() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "AnalysisDatabaseBuildDialog" in source
    assert "self._database_list.build_requested.connect(self._on_database_build_requested)" in source
    assert "dialog.database_materialized.connect(self._on_build_dialog_database_materialized)" in source
    assert "self._database_list.refresh()" in _function_source(path, "_on_build_dialog_database_materialized")



def test_main_data_manager_widgets_use_right_side_button_racks() -> None:
    """Main Data Manager widgets should keep actions in a right-side vertical rack."""
    widget_files = (
        "dataset_selector_widget.py",
        "metadata_tools_widget.py",
        "tool_calculation_widget.py",
        "analysis_database_builder_widget.py",
        "saved_artifact_selector_widget.py",
        "analysis_database_list_widget.py",
        "dataframe_preview_widget.py",
    )
    for filename in widget_files:
        path = DATA_MANAGER / filename
        source = _source(path)
        assert "button_rack import make_button_rack" in source, filename
        assert "root = QHBoxLayout(self)" in source, filename
        assert "make_button_rack(" in source, filename

    helper_source = _source(DATA_MANAGER / "button_rack.py")
    assert "def make_button_rack" in helper_source
    assert "rack.addStretch(1)" in helper_source
    assert "rack.addWidget(button)" in helper_source



def test_saved_recipe_dialogs_use_expanded_readable_list_areas() -> None:
    recipe_source = _source(DATA_MANAGER / "artifact_recipe_dialog.py")
    collection_source = _source(DATA_MANAGER / "artifact_recipe_collection_dialog.py")

    assert "self.resize(1080, 640)" in recipe_source
    assert "self.setMinimumSize(960, 560)" in recipe_source
    assert "self._recipe_list.setMinimumWidth(480)" in recipe_source
    assert "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in recipe_source
    assert "body.addWidget(list_group, 5)" in recipe_source

    assert "self.resize(1180, 700)" in collection_source
    assert "self.setMinimumSize(1040, 620)" in collection_source
    assert "self._collection_list.setMinimumWidth(460)" in collection_source
    assert "self._collection_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in collection_source
    assert "self._recipe_list.setMinimumHeight(260)" in collection_source
    assert "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in collection_source
    assert "body.addWidget(collection_group, 4)" in collection_source
    assert "body.addWidget(detail_group, 5)" in collection_source
