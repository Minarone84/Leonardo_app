from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.gui.windows._historical_data_manager.study_environment_manager_dialog import (
    StudyEnvironmentManagerDialog,
)


ROOT = Path(__file__).resolve().parents[1]
HDM = ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_data_manager_window.py"

_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _study_payload(*, tool_key: str = "ema", period: int = 20) -> dict:
    return {
        "schema_version": 1,
        "family": "indicator",
        "tool_key": tool_key,
        "display_name": f"{tool_key.upper()} {period}",
        "pane_target": "price",
        "params": {"period": period},
        "source_kind": "temporary",
        "input_bindings": {"source": "close"},
        "input_binding_meta": {"source": {"column_name": "close"}},
        "required_inputs": ["source"],
        "saved_artifact_ref": None,
        "user_metadata": {
            "important": True,
            "description": "Original metadata.",
            "dataset_role": "supporting_indicator",
        },
        "style": {
            "color": "#22C55E",
            "line_width": 2,
            "signal_styles": {},
            "fill_styles": {},
            "style_modules": [],
        },
    }


def _store(tmp_path: Path) -> ChartStudySetupStore:
    return ChartStudySetupStore(tmp_path / "chart_presets" / "study_setups")


def _save_setup(store: ChartStudySetupStore) -> None:
    setup = store.create_setup(
        display_name="Momentum Environment",
        description="Reusable chart studies",
        created_from={
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=[_study_payload()],
        setup_id="setup_1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    store.save_setup(setup)


def _dialog(store: ChartStudySetupStore) -> StudyEnvironmentManagerDialog:
    _qapp()
    return StudyEnvironmentManagerDialog(store=store)


def test_manager_lists_environment_and_displays_contained_studies(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_setup(store)

    dialog = _dialog(store)
    try:
        assert dialog._setup_list.count() == 1
        assert dialog._setup_list.currentItem().text() == "Momentum Environment"
        assert "BTCUSDT" in dialog._detail_text.toPlainText()
        assert dialog._study_table.rowCount() == 1
        assert dialog._study_table.item(0, 1).text() == "EMA 20"
        assert dialog._study_table.item(0, 2).text() == "indicator/ema"
        assert dialog._study_table.item(0, 3).text() == "period=20"
        assert dialog._study_table.item(0, 4).text() == "yes"
        assert dialog._study_table.item(0, 5).text() == "supporting_indicator"
    finally:
        dialog.close()


def test_manager_updates_top_level_and_study_metadata_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_setup(store)
    original = store.load_setup("setup_1")
    original_study = dict(original.studies[0])

    dialog = _dialog(store)
    try:
        dialog._name_edit.setText("Momentum Environment Updated")
        dialog._description_edit.setPlainText("Updated manager description")
        dialog._study_table.selectRow(0)
        dialog._important_check.setChecked(False)
        for index in range(dialog._role_combo.count()):
            if dialog._role_combo.itemData(index) == "utc":
                dialog._role_combo.setCurrentIndex(index)
                break
        dialog._study_description_edit.setPlainText("Updated semantic metadata.")
        dialog._on_save_clicked()
    finally:
        dialog.close()

    updated = store.load_setup("setup_1")
    updated_study = updated.studies[0]

    assert updated.setup_id == original.setup_id
    assert updated.display_name == "Momentum Environment Updated"
    assert updated.description == "Updated manager description"
    assert updated.created_at_ms == original.created_at_ms
    assert updated.updated_at_ms >= original.updated_at_ms
    assert updated.content_hash != original.content_hash
    assert updated_study["user_metadata"] == {
        "important": False,
        "description": "Updated semantic metadata.",
        "dataset_role": "utc",
    }
    assert updated_study["params"] == original_study["params"]
    assert updated_study["style"] == original_study["style"]
    assert len(list(store.root_dir.glob("*.json"))) == 1


def test_manager_delete_uses_store_delete_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save_setup(store)

    dialog = _dialog(store)
    try:
        dialog._confirm_delete_environment = lambda setup: True
        dialog._on_delete_clicked()
        assert dialog._setup_list.count() == 0
    finally:
        dialog.close()

    assert not store.setup_exists("setup_1")


def test_research_suite_has_study_environment_manager_entry_point() -> None:
    source = HDM.read_text(encoding="utf-8")

    assert 'QAction("Manage Study Environments..."' in source
    assert "StudyEnvironmentManagerDialog" in source
    assert "self._on_manage_study_environments" in source
