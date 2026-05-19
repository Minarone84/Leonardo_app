from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CheckFailure:
    code: str
    path: str
    detail: str


def _iter_py_files(gui_root: Path) -> Iterable[Path]:
    for p in gui_root.rglob("*.py"):
        # skip bytecode/caches implicitly
        if "__pycache__" in p.parts:
            continue
        yield p


def _relpath(gui_root: Path, p: Path) -> str:
    try:
        return p.relative_to(gui_root.parent).as_posix()  # "gui/..."
    except Exception:
        return p.as_posix()


def _check_compile(gui_root: Path) -> list[CheckFailure]:
    """Syntax/parse check without creating __pycache__ or .pyc files."""
    failures: list[CheckFailure] = []
    for p in _iter_py_files(gui_root):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception as e:
            failures.append(CheckFailure(code="compile", path=_relpath(gui_root, p), detail=f"read failed: {e}"))
            continue
        try:
            compile(src, str(p), "exec")
        except SyntaxError as e:
            failures.append(CheckFailure(code="compile", path=_relpath(gui_root, p), detail=f"syntax error: {e.msg}"))
        except Exception as e:
            failures.append(CheckFailure(code="compile", path=_relpath(gui_root, p), detail=f"compile failed: {e}"))
    return failures


def _check_no_cache_trash(gui_root: Path) -> list[CheckFailure]:
    failures: list[CheckFailure] = []

    forbidden_dirs = {"__pycache__", ".pytest_cache", ".git"}
    for d in gui_root.rglob("*"):
        if d.is_dir() and d.name in forbidden_dirs:
            failures.append(CheckFailure(code="cache_dir", path=_relpath(gui_root, d), detail=f"forbidden dir: {d.name}"))

    for p in gui_root.rglob("*.pyc"):
        failures.append(CheckFailure(code="pyc", path=_relpath(gui_root, p), detail="compiled bytecode in tree"))

    return failures


def _check_viewport_changed_ownership(gui_root: Path) -> list[CheckFailure]:
    allowed = {
        "gui/chart/workspace.py",
        "gui/historical_chart_controller.py",
    }
    failures: list[CheckFailure] = []
    for p in _iter_py_files(gui_root):
        # tools/ is not part of the runtime ownership model; skip it.
        if "tools" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8")
        if "viewport_changed.connect" in txt:
            rel = _relpath(gui_root, p)
            if rel not in allowed:
                failures.append(
                    CheckFailure(
                        code="viewport_listener",
                        path=rel,
                        detail="viewport_changed.connect found outside allowed ownership files",
                    )
                )
    return failures


def _try_contains_apply_contract_call(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "apply_contract":
            return True
    return False


def _handler_is_swallow_all(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}:
        return True
    return False


def _handler_body_is_pass_only(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1:
        return False
    return isinstance(handler.body[0], ast.Pass)


def _check_no_swallowed_apply_contract(gui_root: Path) -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    for p in _iter_py_files(gui_root):
        if "tools" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(txt, filename=str(p))
        except SyntaxError:
            # compile gate handles syntax errors
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not _try_contains_apply_contract_call(node):
                continue
            for handler in node.handlers:
                if _handler_is_swallow_all(handler) and _handler_body_is_pass_only(handler):
                    failures.append(
                        CheckFailure(
                            code="apply_contract_swallow",
                            path=_relpath(gui_root, p),
                            detail="apply_contract call is inside a swallow-all try/except pass block",
                        )
                    )
                    break
    return failures


def _check_no_surface_setters(gui_root: Path) -> list[CheckFailure]:
    """Ensure render surfaces remain contract-only consumers (no set_* soup)."""
    target_file = gui_root / "chart" / "series_render.py"
    if not target_file.exists():
        return []

    txt = target_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(txt, filename=str(target_file))
    except SyntaxError:
        return []

    surface_classes = {"ChartRenderSurface", "VolumeRenderSurface", "OscillatorRenderSurface"}
    forbidden = {
        "set_candles",
        "set_volume",
        "set_series_list",
        "set_view_state",
        "set_resident_base_index",
        "set_visual_policy",
    }

    failures: list[CheckFailure] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in surface_classes:
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in forbidden:
                failures.append(
                    CheckFailure(
                        code="surface_setter",
                        path=_relpath(gui_root, target_file),
                        detail=f"{node.name} defines forbidden legacy setter '{item.name}'",
                    )
                )
    return failures


def _check_pricepane_no_model_overlay_fallback(gui_root: Path) -> list[CheckFailure]:
    price_pane = gui_root / "chart" / "panes" / "price_pane.py"
    if not price_pane.exists():
        return []
    txt = price_pane.read_text(encoding="utf-8")
    forbidden = [
        "model.overlays_view(",
        ".overlays_view(",
    ]
    failures: list[CheckFailure] = []
    for frag in forbidden:
        if frag in txt:
            failures.append(
                CheckFailure(
                    code="pricepane_model_overlay_fallback",
                    path=_relpath(gui_root, price_pane),
                    detail=f"found forbidden overlay discovery fallback: {frag}",
                )
            )
    return failures


def _read_optional(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    txt = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(txt, filename=str(path))
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(txt, node) or ""
    return ""


def _check_data_manager_database_builder_boundaries(gui_root: Path) -> list[CheckFailure]:
    """Keep Database Builder from becoming a database-component editor.

    Database recipe creation from checked artifact columns belongs to
    AnalysisDatabaseBuilderWidget. Database Builder must only manage existing
    Analysis Databases and materialize/rebuild them from their own saved
    manifest recipes. Build and rebuild are separate UI actions, but both must
    call the same store-owned materialization path by database_id.
    """
    path = gui_root / "windows" / "_data_manager" / "analysis_database_list_widget.py"
    txt = _read_optional(path)
    if txt is None:
        return []

    failures: list[CheckFailure] = []
    rel = _relpath(gui_root, path)
    forbidden_fragments = {
        "build_manifest_features_from_saved_columns": "database-builder must not build replacement feature recipes from checked saved artifacts",
        "SavedArtifactColumn": "database-builder must not consume saved-artifact column objects",
        "set_selected_artifact_columns": "database-builder must not receive checked saved-artifact selections",
        "artifact_selection_started": "database-builder must not expose artifact-selection phase signals",
        "artifact_selection_finished": "database-builder must not expose artifact-selection phase signals",
        "_artifact_selection_phase": "database-builder must not keep legacy artifact-selection phase state",
        "rebuild_database_with_features": "database-builder rebuild must not replace database feature components",
        "Build selected artifacts": "database-builder must not expose legacy component-replacement action text",
        "Build / Rebuild Selected Database": "build and rebuild must remain separate explicit actions",
    }
    for fragment, detail in forbidden_fragments.items():
        if fragment in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_db_builder_boundary",
                    path=rel,
                    detail=f"{detail}: {fragment!r}",
                )
            )

    required_fragments = {
        "Build Selected Database": "database-builder must expose a separate Build action",
        "Rebuild Selected Database": "database-builder must expose a separate Rebuild action",
        "def _build_selected": "database-builder must have an explicit build handler",
        "def _rebuild_selected": "database-builder must have an explicit rebuild handler",
        "def _materialize_checked_manifest": "database-builder must share one manifest-driven materialization helper",
    }
    for fragment, detail in required_fragments.items():
        if fragment not in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_db_builder_boundary",
                    path=rel,
                    detail=f"{detail}: missing {fragment!r}",
                )
            )

    build_source = _function_source(path, "_build_selected")
    rebuild_source = _function_source(path, "_rebuild_selected")
    materialize_source = _function_source(path, "_materialize_checked_manifest")

    if build_source:
        for fragment, detail in {
            "_single_checked_manifest": "_build_selected must target exactly one checked existing database",
            "build_requested.emit(manifest)": "_build_selected must open the dedicated build dialog by emitting build intent",
        }.items():
            if fragment not in build_source:
                failures.append(
                    CheckFailure(
                        code="data_manager_db_builder_materialize",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )
        for fragment, detail in {
            "materialize_database": "_build_selected must not directly materialize; the build dialog owns build confirmation",
            "rebuild_database_with_features": "_build_selected must not replace database feature components",
        }.items():
            if fragment in build_source:
                failures.append(
                    CheckFailure(
                        code="data_manager_db_builder_materialize",
                        path=rel,
                        detail=f"{detail}: {fragment!r}",
                    )
                )
    else:
        failures.append(
            CheckFailure(
                code="data_manager_db_builder_materialize",
                path=rel,
                detail="_build_selected() not found",
            )
        )

    if rebuild_source:
        for fragment, detail in {
            "_single_checked_manifest": "_rebuild_selected must target exactly one checked existing database",
            "_materialize_checked_manifest": "_rebuild_selected must delegate to the shared manifest materialization helper",
        }.items():
            if fragment not in rebuild_source:
                failures.append(
                    CheckFailure(
                        code="data_manager_db_builder_materialize",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )
    else:
        failures.append(
            CheckFailure(
                code="data_manager_db_builder_materialize",
                path=rel,
                detail="_rebuild_selected() not found",
            )
        )

    if materialize_source:
        required = {
            "materialize_database": "materialize helper must use store-owned manifest-driven materialization",
            "database_id=manifest.database_id": "materialize helper must preserve the selected existing database_id",
        }
        for fragment, detail in required.items():
            if fragment not in materialize_source:
                failures.append(
                    CheckFailure(
                        code="data_manager_db_builder_materialize",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )
        forbidden_in_materialize = {
            "build_draft_manifest": "materialize helper must not create a new database draft",
            "save_manifest": "materialize helper must not manually save a draft manifest",
            "rebuild_database_with_features": "materialize helper must not replace database feature components",
        }
        for fragment, detail in forbidden_in_materialize.items():
            if fragment in materialize_source:
                failures.append(
                    CheckFailure(
                        code="data_manager_db_builder_materialize",
                        path=rel,
                        detail=f"{detail}: {fragment!r}",
                    )
                )
    else:
        failures.append(
            CheckFailure(
                code="data_manager_db_builder_materialize",
                path=rel,
                detail="_materialize_checked_manifest() not found",
            )
        )
    return failures

def _check_data_manager_window_wiring(gui_root: Path) -> list[CheckFailure]:
    path = gui_root / "windows" / "data_manager_window.py"
    txt = _read_optional(path)
    if txt is None:
        return []

    failures: list[CheckFailure] = []
    rel = _relpath(gui_root, path)
    required = {
        "self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)":
            "checked saved-artifact columns must feed Database seed creator",
    }
    for fragment, detail in required.items():
        if fragment not in txt:
            failures.append(CheckFailure(code="data_manager_window_wiring", path=rel, detail=f"{detail}: missing {fragment!r}"))

    forbidden = {
        "self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)":
            "checked saved-artifact columns must not feed Database Builder",
        "artifact_selection_started": "DataManagerWindow must not coordinate legacy Database Builder artifact-selection mode",
        "artifact_selection_finished": "DataManagerWindow must not coordinate legacy Database Builder artifact-selection mode",
        "_on_database_artifact_selection_started": "legacy Database Builder artifact-selection handler must not exist",
        "_on_database_artifact_selection_finished": "legacy Database Builder artifact-selection handler must not exist",
        "_on_artifact_selection_exit_requested": "legacy Database Builder artifact-selection cancel handler must not exist",
    }
    for fragment, detail in forbidden.items():
        if fragment in txt:
            failures.append(CheckFailure(code="data_manager_window_wiring", path=rel, detail=f"{detail}: {fragment!r}"))
    return failures


def _check_saved_artifact_selector_selection(gui_root: Path) -> list[CheckFailure]:
    path = gui_root / "windows" / "_data_manager" / "saved_artifact_selector_widget.py"
    txt = _read_optional(path)
    if txt is None:
        return []

    failures: list[CheckFailure] = []
    rel = _relpath(gui_root, path)
    if "Preview Selected Artifact" not in txt:
        failures.append(
            CheckFailure(
                code="data_manager_artifact_selection",
                path=rel,
                detail="preview action must be named 'Preview Selected Artifact'",
            )
        )
    for fragment in ("Preview Highlighted", "_current_column"):
        if fragment in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_artifact_selection",
                    path=rel,
                    detail=f"artifact preview/selection must not depend on highlighted row: {fragment!r}",
                )
            )

    refresh_source = _function_source(path, "_refresh_preview_button")
    preview_source = _function_source(path, "_preview_selected_artifact")
    if "_single_checked_column() is not None" not in refresh_source:
        failures.append(
            CheckFailure(
                code="data_manager_artifact_selection",
                path=rel,
                detail="preview button must enable only when exactly one artifact column is checked",
            )
        )
    if "_single_checked_column" not in preview_source or "currentItem" in preview_source:
        failures.append(
            CheckFailure(
                code="data_manager_artifact_selection",
                path=rel,
                detail="preview action must target the single checked artifact column, not the highlighted row",
            )
        )
    return failures


def _check_dataframe_preview_timestamps(gui_root: Path) -> list[CheckFailure]:
    path = gui_root / "windows" / "_data_manager" / "dataframe_preview_widget.py"
    txt = _read_optional(path)
    if txt is None:
        return []

    failures: list[CheckFailure] = []
    rel = _relpath(gui_root, path)
    required_fragments = {
        "ts_utc": "preview must add readable UTC timestamps for ts_ms-backed CSVs",
        "ts_rome": "preview must add readable Europe/Rome timestamps for ts_ms-backed CSVs",
        "out = dataframe.copy()": "preview formatting must be display-only and avoid mutating source dataframe",
        "out.insert": "preview should insert readable timestamp columns next to source timestamps",
        "drop(columns=[\"time\"]": "preview should hide duplicate epoch-like time column when ts_ms is already visible",
    }
    for fragment, detail in required_fragments.items():
        if fragment not in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_preview_timestamps",
                    path=rel,
                    detail=f"{detail}: missing {fragment!r}",
                )
            )
    return failures



def _check_data_manager_build_dialog(gui_root: Path) -> list[CheckFailure]:
    path = gui_root / "windows" / "_data_manager" / "analysis_database_build_dialog.py"
    txt = _read_optional(path)
    if txt is None:
        return []

    failures: list[CheckFailure] = []
    rel = _relpath(gui_root, path)
    required_fragments = {
        "class AnalysisDatabaseBuildDialog": "build dialog must define the explicit build surface",
        "load_saved_artifact_columns": "build dialog must auto-load saved artifacts for the selected dataset",
        "_EXISTING_COMPONENT_BRUSH": "build dialog must highlight existing database components",
        "materialize_database": "build dialog must delegate build to store-owned materialization",
        "database_id=self._manifest.database_id": "build dialog must preserve the selected existing database_id",
    }
    for fragment, detail in required_fragments.items():
        if fragment not in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_build_dialog",
                    path=rel,
                    detail=f"{detail}: missing {fragment!r}",
                )
            )
    forbidden_fragments = {
        "AnalysisDatabaseComponentEditor": "build dialog must not edit database components",
        "replace_components": "build dialog must not replace component recipes",
        "add_components": "build dialog must not add component recipes",
        "remove_components": "build dialog must not remove component recipes",
        "rebuild_database_with_features": "build dialog must not replace database feature components",
    }
    for fragment, detail in forbidden_fragments.items():
        if fragment in txt:
            failures.append(
                CheckFailure(
                    code="data_manager_build_dialog",
                    path=rel,
                    detail=f"{detail}: {fragment!r}",
                )
            )
    return failures


def _check_data_manager_button_racks(gui_root: Path) -> list[CheckFailure]:
    """Keep Data Manager widget actions in right-side vertical button racks."""
    data_manager_root = gui_root / "windows" / "_data_manager"
    helper_path = data_manager_root / "button_rack.py"
    failures: list[CheckFailure] = []

    helper_txt = _read_optional(helper_path)
    if helper_txt is None:
        return []
    helper_rel = _relpath(gui_root, helper_path)
    for fragment, detail in {
        "def make_button_rack": "button rack helper must define make_button_rack",
        "rack.addWidget(button)": "button rack helper must add each action button normally",
        "rack.addStretch(1)": "button rack helper must preserve button height by pushing extra space below buttons",
    }.items():
        if fragment not in helper_txt:
            failures.append(
                CheckFailure(
                    code="data_manager_button_rack",
                    path=helper_rel,
                    detail=f"{detail}: missing {fragment!r}",
                )
            )

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
        path = data_manager_root / filename
        txt = _read_optional(path)
        if txt is None:
            continue
        rel = _relpath(gui_root, path)
        for fragment, detail in {
            "button_rack import make_button_rack": "widget must import the shared right-side button-rack helper",
            "root = QHBoxLayout(self)": "widget root layout must split content and action rack horizontally",
            "make_button_rack(": "widget action buttons must be placed in the right-side button rack",
        }.items():
            if fragment not in txt:
                failures.append(
                    CheckFailure(
                        code="data_manager_button_rack",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )
    return failures



def _check_data_manager_recipe_dialog_readability(gui_root: Path) -> list[CheckFailure]:
    """Keep saved recipe and collection dialogs wide enough for long names."""
    data_manager_root = gui_root / "windows" / "_data_manager"
    failures: list[CheckFailure] = []

    recipe_path = data_manager_root / "artifact_recipe_dialog.py"
    recipe_txt = _read_optional(recipe_path)
    if recipe_txt is not None:
        rel = _relpath(gui_root, recipe_path)
        for fragment, detail in {
            "self.resize(1080, 640)": "Saved Recipes dialog must open wide enough for long recipe names",
            "self.setMinimumSize(960, 560)": "Saved Recipes dialog must keep a readable minimum size",
            "self._recipe_list.setMinimumWidth(480)": "Saved Recipes list must have a wide readable column",
            "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)": "Saved Recipes list must not elide long names",
            "body.addWidget(list_group, 5)": "Saved Recipes list must get the larger body share",
        }.items():
            if fragment not in recipe_txt:
                failures.append(
                    CheckFailure(
                        code="data_manager_recipe_dialog_readability",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )

    collection_path = data_manager_root / "artifact_recipe_collection_dialog.py"
    collection_txt = _read_optional(collection_path)
    if collection_txt is not None:
        rel = _relpath(gui_root, collection_path)
        for fragment, detail in {
            "self.resize(1180, 700)": "Saved Recipe Collections dialog must open wide enough for long collection names",
            "self.setMinimumSize(1040, 620)": "Saved Recipe Collections dialog must keep a readable minimum size",
            "self._collection_list.setMinimumWidth(460)": "Saved Collections list must have a wide readable column",
            "self._collection_list.setTextElideMode(Qt.TextElideMode.ElideNone)": "Saved Collections list must not elide long names",
            "self._recipe_list.setMinimumHeight(260)": "Collection recipe-subset list must remain readable",
            "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)": "Collection recipe-subset list must not elide long names",
            "body.addWidget(collection_group, 4)": "Saved Collections list must get a larger body share",
            "body.addWidget(detail_group, 5)": "Collection details must retain adequate body space",
        }.items():
            if fragment not in collection_txt:
                failures.append(
                    CheckFailure(
                        code="data_manager_recipe_dialog_readability",
                        path=rel,
                        detail=f"{detail}: missing {fragment!r}",
                    )
                )
    return failures

def run_all_checks(gui_root: Path) -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    failures.extend(_check_compile(gui_root))
    failures.extend(_check_no_cache_trash(gui_root))
    failures.extend(_check_viewport_changed_ownership(gui_root))
    failures.extend(_check_no_swallowed_apply_contract(gui_root))
    failures.extend(_check_no_surface_setters(gui_root))
    failures.extend(_check_pricepane_no_model_overlay_fallback(gui_root))
    failures.extend(_check_data_manager_database_builder_boundaries(gui_root))
    # M6F accepted Data Manager layout no longer requires right-side button racks.
    # The older button-rack guardrail was intentionally removed from release
    # checks so layout polishing does not fail accepted compact/contextual UI.
    failures.extend(_check_data_manager_build_dialog(gui_root))
    failures.extend(_check_data_manager_recipe_dialog_readability(gui_root))
    failures.extend(_check_data_manager_window_wiring(gui_root))
    failures.extend(_check_saved_artifact_selector_selection(gui_root))
    failures.extend(_check_dataframe_preview_timestamps(gui_root))
    return failures


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    gui_root = Path(__file__).resolve().parents[1]  # .../gui
    if argv:
        gui_root = Path(argv[0]).resolve()

    failures = run_all_checks(gui_root)
    if not failures:
        print("OK: GUI release checks passed.")
        return 0

    print("FAIL: GUI release checks failed:")
    for f in failures:
        print(f" - [{f.code}] {f.path}: {f.detail}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
