from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.gui.windows._historical_data_manager.study_setup_dialogs import (
    SaveStudySetupDialog,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _study_payload(
    *,
    tool_key: str = "ema",
    description: str = "Original metadata.",
    important: bool = False,
    dataset_role: str = "unspecified",
) -> dict:
    return {
        "schema_version": 1,
        "family": "indicator",
        "tool_key": tool_key,
        "display_name": "Duplicate Study Name",
        "pane_target": "price",
        "params": {"period": 20},
        "source_kind": "temporary",
        "input_bindings": {"source": "close"},
        "input_binding_meta": {"source": {"column_name": "close"}},
        "required_inputs": ["source"],
        "saved_artifact_ref": None,
        "user_metadata": {
            "important": important,
            "description": description,
            "dataset_role": dataset_role,
        },
        "style": {
            "color": "#22C55E",
            "line_width": 2,
            "signal_styles": {},
            "fill_styles": {},
            "style_modules": [],
        },
    }


def _dialog(studies: list[dict]) -> SaveStudySetupDialog:
    _qapp()
    dialog = SaveStudySetupDialog(
        chart_options=[
            {
                "label": "Chart 1",
                "position": 1,
                "study_count": len(studies),
                "studies": studies,
            }
        ],
        existing_setups=[],
    )
    dialog._name_edit.setText("Saved Environment")
    return dialog


def _set_combo_value(combo: QComboBox, value: str) -> None:
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value}")


def test_save_dialog_lists_studies_and_prefills_metadata() -> None:
    studies = [
        _study_payload(
            important=True,
            dataset_role="supporting_indicator",
            description="Prefilled semantic note.",
        )
    ]

    dialog = _dialog(studies)
    try:
        table = dialog._metadata_table
        important = table.cellWidget(0, 2)
        role = table.cellWidget(0, 3)
        description = table.cellWidget(0, 4)

        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "Duplicate Study Name"
        assert table.item(0, 1).text() == "indicator/ema"
        assert isinstance(important, QCheckBox)
        assert important.isChecked()
        assert isinstance(role, QComboBox)
        assert role.currentData() == "supporting_indicator"
        assert isinstance(description, QLineEdit)
        assert description.text() == "Prefilled semantic note."
    finally:
        dialog.close()


def test_save_dialog_applies_metadata_by_row_order_and_preserves_payload() -> None:
    studies = [
        _study_payload(tool_key="ema", description="First"),
        _study_payload(tool_key="sma", description="Second"),
    ]
    original_style = dict(studies[0]["style"])
    original_params = dict(studies[0]["params"])

    dialog = _dialog(studies)
    try:
        table = dialog._metadata_table
        important = table.cellWidget(0, 2)
        role = table.cellWidget(0, 3)
        description = table.cellWidget(0, 4)

        assert isinstance(important, QCheckBox)
        assert isinstance(role, QComboBox)
        assert isinstance(description, QLineEdit)

        important.setChecked(True)
        _set_combo_value(role, "utc")
        description.setText("Updated at save time.")

        updated = dialog.studies_with_metadata(studies)
    finally:
        dialog.close()

    assert updated[0]["user_metadata"] == {
        "important": True,
        "description": "Updated at save time.",
        "dataset_role": "utc",
    }
    assert updated[1]["user_metadata"]["description"] == "Second"
    assert updated[0]["params"] == original_params
    assert updated[0]["style"] == original_style
    assert studies[0]["user_metadata"]["description"] == "First"


def test_save_dialog_metadata_payload_can_be_saved_as_new_or_updated(
    tmp_path: Path,
) -> None:
    studies = [_study_payload(description="Before dialog")]
    store = ChartStudySetupStore(tmp_path / "study_setups")

    dialog = _dialog(studies)
    try:
        table = dialog._metadata_table
        important = table.cellWidget(0, 2)
        role = table.cellWidget(0, 3)
        description = table.cellWidget(0, 4)

        assert isinstance(important, QCheckBox)
        assert isinstance(role, QComboBox)
        assert isinstance(description, QLineEdit)

        important.setChecked(True)
        _set_combo_value(role, "visual_only")
        description.setText("Dialog metadata")
        updated_studies = dialog.studies_with_metadata(studies)
    finally:
        dialog.close()

    setup = store.create_setup(
        display_name="Dialog Metadata Setup",
        description="",
        created_from={},
        studies=updated_studies,
        setup_id="setup_dialog_metadata",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    saved = store.save_setup(setup)
    updated = store.update_setup(
        setup_id=saved.setup_id,
        display_name=saved.display_name,
        description=saved.description,
        created_from=saved.created_from,
        studies=updated_studies,
    )

    assert store.load_setup(saved.setup_id).studies[0]["user_metadata"] == {
        "important": True,
        "description": "Dialog metadata",
        "dataset_role": "visual_only",
    }
    assert updated.setup_id == saved.setup_id
    assert updated.created_at_ms == saved.created_at_ms
    assert len(list(store.root_dir.glob("*.json"))) == 1
