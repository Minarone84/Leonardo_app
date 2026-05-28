from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPlainTextEdit, QPushButton

from leonardo.gui.windows._data_manager import dialog_geometry as dm_dialog_geometry
from leonardo.gui.windows._data_manager.construct_batch_dialog import (
    ConstructBatchBuilderDialog,
)
from leonardo.gui.windows._data_manager.tool_calculation_widget import (
    _DataManagerFinancialToolsWindow,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo"
DATA_MANAGER = SRC / "gui" / "windows" / "_data_manager"
WINDOWS = SRC / "gui" / "windows"

_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(10, 20, 2000, 1200)


def _set_combo_value(combo, value: str) -> None:
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value!r}")


def test_data_manager_popup_uses_sixty_percent_available_width_and_height(monkeypatch) -> None:
    _qapp()
    dialog = QDialog()
    dialog.setMinimumSize(900, 620)
    monkeypatch.setattr(
        dm_dialog_geometry,
        "_screen_for_dialog",
        lambda _dialog: _FakeScreen(),
    )

    dm_dialog_geometry.apply_data_manager_dialog_initial_size(
        dialog,
        default_width=900,
        default_height=620,
    )

    assert dialog.width() == 1200
    assert dialog.height() == 720
    assert dialog.x() == 10 + (2000 - 1200) // 2
    assert dialog.y() == 20 + (1200 - 720) // 2

    tool_source = _source(DATA_MANAGER / "tool_calculation_widget.py")
    geometry_source = _source(DATA_MANAGER / "dialog_geometry.py")
    assert "apply_data_manager_dialog_initial_size" in tool_source
    assert "default_width=900" in tool_source
    assert "default_height=620" in tool_source
    assert "DATA_MANAGER_DIALOG_INITIAL_HEIGHT_RATIO = 0.60" in geometry_source
    assert "availableGeometry()" in geometry_source


def test_construct_batch_button_is_data_manager_save_only_and_construct_scoped(
    tmp_path: Path,
) -> None:
    _qapp()
    window = _DataManagerFinancialToolsWindow(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        historical_root=tmp_path,
        save_only=True,
    )
    try:
        button = window._construct_batch_button

        assert button.text() == "Construct Batch..."
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "indicator")
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "oscillator")
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "construct")
        assert not button.isHidden()
        assert button.isEnabled()
    finally:
        window.close()


def test_construct_batch_button_opens_placeholder_dialog(tmp_path: Path) -> None:
    _qapp()
    window = _DataManagerFinancialToolsWindow(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        historical_root=tmp_path,
        save_only=True,
    )
    try:
        _set_combo_value(window._tool_type_combo, "construct")
        window._construct_batch_button.click()

        assert isinstance(window._construct_batch_dialog, ConstructBatchBuilderDialog)
    finally:
        if window._construct_batch_dialog is not None:
            window._construct_batch_dialog.close()
        window.close()


def test_construct_batch_builder_shell_labels_and_disabled_actions() -> None:
    _qapp()
    dialog = ConstructBatchBuilderDialog()
    try:
        text = "\n".join(
            [label.text() for label in dialog.findChildren(QLabel)]
            + [edit.toPlainText() for edit in dialog.findChildren(QPlainTextEdit)]
            + [
                dialog._construct_list.item(index).text()
                for index in range(dialog._construct_list.count())
            ]
        )

        for expected in (
            "Unary source expansion",
            "Binary delta expansion",
            "delta = minuend - subtrahend",
            "derivative",
            "angle",
            "percent_span_angle",
            "angle_momentum",
            "delta",
        ):
            assert expected in text

        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        for text in (
            "Preview Plan",
            "Save Recipes",
            "Save as Collection",
            "Calculate Artifacts",
        ):
            assert text in buttons
            assert not buttons[text].isEnabled()

        assert buttons["Close"].isEnabled()
    finally:
        dialog.close()


def test_construct_batch_gui_shell_keeps_backend_boundaries() -> None:
    dialog_source = _source(DATA_MANAGER / "construct_batch_dialog.py")
    tool_source = _source(DATA_MANAGER / "tool_calculation_widget.py")

    assert "ConstructBatchBuilderDialog" in tool_source
    assert "Construct Batch..." in tool_source
    assert "Construct Batch" not in _source(WINDOWS / "financial_tools_manager_window.py")
    assert "Construct Batch" not in _source(WINDOWS / "historical_chart_panel.py")

    forbidden_dialog_tokens = (
        "ArtifactRecipeStore",
        "ArtifactRecipeCollectionStore",
        "ArtifactCalculationService",
        "DataManagerSelectedUpdateService",
        "write_text",
        "json.dump",
        "to_csv",
        "save_manifest",
        "materialize_database",
    )
    for token in forbidden_dialog_tokens:
        assert token not in dialog_source
