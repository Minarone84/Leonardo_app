from __future__ import annotations

from pathlib import Path

from leonardo.gui.tools.release_checks import run_all_checks


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _minimal_clean_gui_tree(tmp_path: Path) -> Path:
    gui_root = tmp_path / "gui"
    _write(
        gui_root / "windows" / "_data_manager" / "button_rack.py",
        """
def make_button_rack(*buttons):
    rack = object()
    for button in buttons:
        rack.addWidget(button)
    rack.addStretch(1)
    return rack
""",
    )
    _write(
        gui_root / "windows" / "data_manager_window.py",
        """
class DataManagerWindow:
    def _build_central_widget(self):
        self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)
        self._database_list.database_materialized.connect(self._on_analysis_database_materialized)
        self._database_list.build_requested.connect(self._on_database_build_requested)
        self._database_list.preview_requested.connect(self._preview.load_csv_path)
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "analysis_database_list_widget.py",
        """
from button_rack import make_button_rack

class AnalysisDatabaseListWidget:
    def __init__(self):
        root = QHBoxLayout(self)
        self._build_button = QPushButton("Build Selected Database")
        self._rebuild_button = QPushButton("Rebuild Selected Database")
        root.addLayout(make_button_rack(self._build_button, self._rebuild_button), 0)

    def _build_selected(self):
        manifest = self._single_checked_manifest(action_label="building")
        self.build_requested.emit(manifest)
        return manifest

    def _rebuild_selected(self):
        manifest = self._single_checked_manifest(action_label="rebuilding")
        return self._materialize_checked_manifest(
            manifest=manifest,
            action_label="Rebuild",
            detail="rebuild",
        )

    def _materialize_checked_manifest(self, *, manifest, action_label, detail):
        updated = self._store.materialize_database(
            market=manifest.market,
            database_id=manifest.database_id,
            overwrite=True,
        )
        return updated
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "analysis_database_build_dialog.py",
        """
class AnalysisDatabaseBuildDialog:
    _EXISTING_COMPONENT_BRUSH = object()

    def __init__(self):
        self.columns = load_saved_artifact_columns()

    def _build_database(self):
        updated = self._store.materialize_database(
            market=self._manifest.market,
            database_id=self._manifest.database_id,
            overwrite=True,
        )
        return updated
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "saved_artifact_selector_widget.py",
        """
from button_rack import make_button_rack

class SavedArtifactSelectorWidget:
    def __init__(self):
        root = QHBoxLayout(self)
        self._preview_button = QPushButton("Preview Selected Artifact")
        root.addLayout(make_button_rack(self._preview_button), 0)

    def _single_checked_column(self):
        return None

    def _refresh_preview_button(self):
        self._preview_button.setEnabled(self._single_checked_column() is not None)

    def _preview_selected_artifact(self):
        column = self._single_checked_column()
        if column is None:
            return
        self.preview_requested.emit(column.path, "title")
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "dataframe_preview_widget.py",
        """
from button_rack import make_button_rack

class DataFramePreviewWidget:
    def __init__(self):
        root = QHBoxLayout(self)
        self._clear_button = QPushButton("Clear Preview")
        root.addLayout(make_button_rack(self._clear_button), 0)

    def _prepare_preview_dataframe(self, dataframe):
        out = dataframe.copy()
        out.insert(1, "ts_utc", [])
        out.insert(2, "ts_rome", [])
        out = out.drop(columns=["time"])
        return out
""",
    )

    for filename, button_text in {
        "dataset_selector_widget.py": "Refresh Datasets",
        "metadata_tools_widget.py": "Check / Restore Missing or Corrupt Metadata",
        "tool_calculation_widget.py": "Calculate and Save Artifact",
        "analysis_database_builder_widget.py": "Save Draft Manifest",
    }.items():
        _write(
            gui_root / "windows" / "_data_manager" / filename,
            f"""
from button_rack import make_button_rack

class PlaceholderWidget:
    def __init__(self):
        root = QHBoxLayout(self)
        button = QPushButton({button_text!r})
        root.addLayout(make_button_rack(button), 0)
""",
        )
    return gui_root


def _failure_codes(gui_root: Path) -> set[str]:
    return {failure.code for failure in run_all_checks(gui_root)}


def test_release_checks_accept_clean_data_manager_boundaries(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)

    assert run_all_checks(gui_root) == []


def test_release_checks_reject_database_builder_artifact_replacement_path(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "analysis_database_list_widget.py",
        """
from leonardo.gui.windows._data_manager.analysis_database_builder_widget import build_manifest_features_from_saved_columns
from leonardo.gui.windows._data_manager.saved_artifact_selector_widget import SavedArtifactColumn

class AnalysisDatabaseListWidget:
    artifact_selection_started = object()
    artifact_selection_finished = object()

    def __init__(self):
        self._artifact_selection_phase = False
        self._selected_artifact_columns: list[SavedArtifactColumn] = []

    def set_selected_artifact_columns(self, columns):
        self._selected_artifact_columns = columns

    def _materialize_selected(self):
        self._materialize_button = QPushButton("Build / Rebuild Selected Database")
        manifest = self._store.rebuild_database_with_features(
            market=self.market,
            database_id=self.database_id,
            feature_sources=(),
            feature_columns=(),
        )
        return manifest
""",
    )

    failures = run_all_checks(gui_root)
    assert "data_manager_db_builder_boundary" in {failure.code for failure in failures}
    assert "data_manager_db_builder_materialize" in {failure.code for failure in failures}


def test_release_checks_reject_data_manager_artifact_selection_wiring_to_database_builder(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "data_manager_window.py",
        """
class DataManagerWindow:
    def _build_central_widget(self):
        self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)
        self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)
        self._database_list.artifact_selection_started.connect(self._on_database_artifact_selection_started)
        self._database_list.artifact_selection_finished.connect(self._on_database_artifact_selection_finished)

    def _on_database_artifact_selection_started(self):
        pass

    def _on_database_artifact_selection_finished(self):
        pass

    def _on_artifact_selection_exit_requested(self):
        pass
""",
    )

    assert "data_manager_window_wiring" in _failure_codes(gui_root)


def test_release_checks_reject_highlight_driven_saved_artifact_preview(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "analysis_database_build_dialog.py",
        """
class AnalysisDatabaseBuildDialog:
    _EXISTING_COMPONENT_BRUSH = object()

    def __init__(self):
        self.columns = load_saved_artifact_columns()

    def _build_database(self):
        updated = self._store.materialize_database(
            market=self._manifest.market,
            database_id=self._manifest.database_id,
            overwrite=True,
        )
        return updated
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "saved_artifact_selector_widget.py",
        """
class SavedArtifactSelectorWidget:
    def __init__(self):
        self._preview_button = QPushButton("Preview Highlighted Artifact")

    def _current_column(self):
        item = self._list.currentItem()
        return item.data(0)

    def _refresh_preview_button(self):
        self._preview_button.setEnabled(self._current_column() is not None)

    def _preview_selected_artifact(self):
        column = self._current_column()
        self.preview_requested.emit(column.path, "title")
""",
    )

    assert "data_manager_artifact_selection" in _failure_codes(gui_root)


def test_release_checks_reject_preview_without_readable_timestamp_columns(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "dataframe_preview_widget.py",
        """
from button_rack import make_button_rack

class DataFramePreviewWidget:
    def __init__(self):
        root = QHBoxLayout(self)
        self._clear_button = QPushButton("Clear Preview")
        root.addLayout(make_button_rack(self._clear_button), 0)

    def _prepare_preview_dataframe(self, dataframe):
        return dataframe
""",
    )

    assert "data_manager_preview_timestamps" in _failure_codes(gui_root)


def test_release_checks_reject_combined_build_rebuild_action(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "analysis_database_list_widget.py",
        """
class AnalysisDatabaseListWidget:
    def __init__(self):
        self._materialize_button = QPushButton("Build / Rebuild Selected Database")

    def _materialize_selected(self):
        manifest = self._single_checked_manifest(action_label="building/rebuilding")
        return self._store.materialize_database(
            market=manifest.market,
            database_id=manifest.database_id,
            overwrite=True,
        )
""",
    )

    failures = run_all_checks(gui_root)
    codes = {failure.code for failure in failures}
    assert "data_manager_db_builder_boundary" in codes
    assert "data_manager_db_builder_materialize" in codes


def test_release_checks_reject_missing_or_invalid_build_dialog(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    (gui_root / "windows" / "_data_manager" / "analysis_database_build_dialog.py").write_text(
        "class AnalysisDatabaseBuildDialog:\n    pass\n",
        encoding="utf-8",
    )

    assert "data_manager_build_dialog" in _failure_codes(gui_root)



def test_release_checks_reject_main_widget_without_button_rack(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "metadata_tools_widget.py",
        """
class MetadataToolsWidget:
    def __init__(self):
        root = QVBoxLayout(self)
        self._restore_button = QPushButton("Check / Restore Missing or Corrupt Metadata")
        root.addWidget(self._restore_button)
""",
    )

    assert "data_manager_button_rack" in _failure_codes(gui_root)



def test_release_checks_reject_small_saved_recipe_dialogs(tmp_path: Path) -> None:
    gui_root = _minimal_clean_gui_tree(tmp_path)
    _write(
        gui_root / "windows" / "_data_manager" / "artifact_recipe_dialog.py",
        """
class ArtifactRecipeDialog:
    def __init__(self):
        self.resize(740, 480)
        self._recipe_list = QListWidget()
        body.addWidget(list_group, 2)
""",
    )
    _write(
        gui_root / "windows" / "_data_manager" / "artifact_recipe_collection_dialog.py",
        """
class ArtifactRecipeCollectionDialog:
    def __init__(self):
        self.resize(940, 560)
        self._collection_list = QListWidget()
        self._recipe_list = QListWidget()
        body.addWidget(collection_group, 2)
        body.addWidget(detail_group, 4)
""",
    )

    assert "data_manager_recipe_dialog_readability" in _failure_codes(gui_root)
