from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.naming import canonicalize
from leonardo.gui.windows._data_manager.study_setup_recipe_export_dialog import (
    StudySetupRecipeExportDialog,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "1h")


def _study_payload(
    *,
    family: str = "indicator",
    tool_key: str = "ema",
    display_name: str = "EMA 20",
    params: dict[str, object] | None = None,
    important: bool = True,
    dataset_role: str = "supporting_indicator",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "family": family,
        "tool_key": tool_key,
        "display_name": display_name,
        "pane_target": "price",
        "params": dict(params or {"period": 20}),
        "source_kind": "temporary",
        "input_bindings": {"source": "close"},
        "input_binding_meta": {
            "source": {
                "source_kind": "default",
                "family": "default",
                "column_name": "close",
            }
        },
        "required_inputs": ["source"],
        "saved_artifact_ref": None,
        "user_metadata": {
            "important": important,
            "description": "Export test study.",
            "dataset_role": dataset_role,
        },
        "style": {
            "signal_styles": {},
            "fill_styles": {},
            "style_modules": [],
        },
    }


def _save_setup(
    tmp_path: Path,
    *,
    studies: list[dict[str, object]] | None = None,
    created_from: dict[str, object] | None = None,
) -> None:
    store = ChartStudySetupStore(tmp_path / "chart_presets" / "study_setups")
    setup = store.create_setup(
        display_name="Dialog Export Setup",
        description="Study setup export dialog test.",
        created_from=created_from
        if created_from is not None
        else {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=studies or [_study_payload()],
        setup_id="dialog_export_setup",
    )
    store.save_setup(setup)


def _dialog(tmp_path: Path) -> StudySetupRecipeExportDialog:
    _qapp()
    return StudySetupRecipeExportDialog(
        historical_root=tmp_path / "historical",
        study_setup_root=tmp_path / "chart_presets" / "study_setups",
        target_market=_market(),
    )


def test_dialog_lists_saved_study_setups_and_builds_plan(tmp_path: Path) -> None:
    _save_setup(tmp_path)
    dialog = _dialog(tmp_path)
    try:
        assert dialog._setup_list.count() == 1
        assert dialog.selected_setup_id() == "dialog_export_setup"
        assert dialog._current_plan is not None
        assert dialog._candidate_table.rowCount() == 1
        assert dialog._candidate_table.item(0, 5).text() == "exportable"
    finally:
        dialog.close()


def test_important_only_refreshes_plan(tmp_path: Path) -> None:
    _save_setup(
        tmp_path,
        studies=[
            _study_payload(
                tool_key="ema",
                display_name="EMA 20",
                important=False,
            ),
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
                important=True,
            ),
        ],
    )
    dialog = _dialog(tmp_path)
    try:
        assert dialog._candidate_table.item(0, 5).text() == "exportable"

        dialog._important_only_check.setChecked(True)

        assert dialog._current_plan is not None
        assert dialog._current_plan.important_only is True
        assert dialog._candidate_table.item(0, 5).text() == "skipped"
        assert dialog._candidate_table.item(1, 5).text() == "exportable"
    finally:
        dialog.close()


def test_only_exportable_candidates_are_selectable(tmp_path: Path) -> None:
    _save_setup(
        tmp_path,
        studies=[
            _study_payload(tool_key="ema", display_name="EMA 20"),
            _study_payload(tool_key="missing_tool", display_name="Missing Tool"),
        ],
    )
    dialog = _dialog(tmp_path)
    try:
        exportable_item = dialog._candidate_table.item(0, 0)
        blocked_item = dialog._candidate_table.item(1, 0)

        assert bool(exportable_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert not bool(blocked_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert dialog.checked_candidate_ids() == (
            "dialog_export_setup__study_0",
        )
    finally:
        dialog.close()


def test_save_selected_persists_recipes_and_collection(tmp_path: Path) -> None:
    _save_setup(
        tmp_path,
        studies=[
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
            ),
            _study_payload(tool_key="ema", display_name="EMA 20"),
        ],
    )
    dialog = _dialog(tmp_path)
    reports = []
    dialog.recipes_persisted.connect(lambda report: reports.append(report))
    try:
        dialog._save_collection_check.setChecked(True)
        dialog._collection_name_edit.setText("Study Export Pack")

        dialog._save_selected()

        recipe_summaries = ArtifactRecipeStore(
            historical_root=tmp_path / "historical"
        ).list_recipes(market=_market())
        collection_summaries = ArtifactRecipeCollectionStore(
            historical_root=tmp_path / "historical"
        ).list_collections(market=_market())

        assert len(recipe_summaries) == 2
        assert len(collection_summaries) == 1
        assert collection_summaries[0].display_name == "Study Export Pack"
        assert reports
        assert reports[0].summary["saved"] == 2
        assert "Saved collection ID" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_save_selected_with_no_checked_candidates_does_not_persist(
    tmp_path: Path,
) -> None:
    _save_setup(tmp_path)
    dialog = _dialog(tmp_path)
    try:
        item = dialog._candidate_table.item(0, 0)
        item.setCheckState(Qt.CheckState.Unchecked)

        dialog._save_selected()

        recipes = ArtifactRecipeStore(
            historical_root=tmp_path / "historical"
        ).list_recipes(market=_market())
        assert recipes == []
        assert "Select one or more exportable candidates" in dialog._report_text.toPlainText()
    finally:
        dialog.close()
