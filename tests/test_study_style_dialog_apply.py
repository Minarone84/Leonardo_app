from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox

import leonardo.gui.windows._historical_chart_panel.historical_chart_panel_style as style_module
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRegistry,
    ChartStudyRuntimeState,
    PANE_TARGET_PRICE,
    STUDY_FAMILY_INDICATOR,
    StudyComputationConfig,
    StudyDisplayStyle,
    StudyFillStyle,
    StudySignalStyle,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_style import (
    HistoricalChartPanelStyleMixin,
)
from leonardo.gui.windows._historical_chart_panel.study_style_dialog import (
    StudyStyleDialog,
)


ROOT = Path(__file__).resolve().parents[1]
STYLE_DIALOG = ROOT / "src" / "leonardo" / "gui" / "windows" / "_historical_chart_panel" / "study_style_dialog.py"
STYLE_MIXIN = (
    ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "_historical_chart_panel"
    / "historical_chart_panel_style.py"
)
OVERLAY_ROWS = ROOT / "src" / "leonardo" / "gui" / "chart" / "panes" / "overlay_rows.py"
OSCILLATOR_PANE = ROOT / "src" / "leonardo" / "gui" / "chart" / "panes" / "oscillator_pane.py"

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


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _sample_style() -> StudyDisplayStyle:
    return StudyDisplayStyle(
        color="#22C55E",
        line_width=2,
        signal_styles={
            "sma_20": StudySignalStyle(
                color="#22C55E",
                line_width=2,
                line_style="solid",
                visible=True,
            )
        },
        fill_styles={
            "sma_band": StudyFillStyle(
                fill_id="sma_band",
                signal_a="sma_20",
                signal_b="sma_50",
                color="#3B82F6",
                opacity=0.12,
                visible=True,
            )
        },
    )


def _sample_dialog() -> StudyStyleDialog:
    return StudyStyleDialog(
        display_name="SMA 20",
        current_style=_sample_style(),
        signal_names=["sma_20"],
        fill_specs=[
            {
                "fill_id": "sma_band",
                "title": "SMA Band",
                "signal_a": "sma_20",
                "signal_b": "sma_50",
            }
        ],
        defaults_study_key="sma",
    )


def _select_combo_data(combo: QComboBox, value: str) -> None:
    for index in range(combo.count()):
        if str(combo.itemData(index) or "") == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo data {value!r} not found")


def test_style_dialog_exposes_apply_ok_cancel_and_apply_stays_open() -> None:
    _qapp()
    dialog = _sample_dialog()
    try:
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None

        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)

        assert apply_button is not None
        assert ok_button is not None
        assert cancel_button is not None

        calls: list[dict[str, Any]] = []
        dialog.apply_requested.connect(lambda: calls.append(dialog.style_patch()))

        apply_button.click()

        assert len(calls) == 1
        assert dialog.result() == 0
    finally:
        dialog.close()


def test_white_preset_is_available_for_signal_and_fill_styles() -> None:
    _qapp()
    dialog = _sample_dialog()
    try:
        signal_controls = dialog._signal_controls["sma_20"]
        signal_combo = signal_controls["preset_combo"]
        signal_color = signal_controls["color_edit"]

        fill_controls = dialog._fill_controls["sma_band"]
        fill_combo = fill_controls["preset_combo"]
        fill_color = fill_controls["color_edit"]

        assert isinstance(signal_combo, QComboBox)
        assert isinstance(fill_combo, QComboBox)

        _select_combo_data(signal_combo, "#FFFFFF")
        _select_combo_data(fill_combo, "#FFFFFF")

        assert signal_color.text() == "#FFFFFF"
        assert fill_color.text() == "#FFFFFF"

        patch = dialog.style_patch()
        assert patch["signal_patches"]["sma_20"]["color"] == "#FFFFFF"
        assert patch["fill_patches"]["sma_band"]["color"] == "#FFFFFF"
    finally:
        dialog.close()


class _Signal:
    def __init__(self) -> None:
        self._slots: list[object] = []

    def connect(self, slot: object) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()  # type: ignore[misc]


class _FakeDialog:
    def __init__(
        self,
        *,
        patch: dict[str, Any],
        auto_apply: bool,
        exec_result: int,
        **_kwargs: Any,
    ) -> None:
        self.apply_requested = _Signal()
        self.patch = patch
        self.auto_apply = auto_apply
        self.exec_result = exec_result

    def exec(self) -> int:
        if self.auto_apply:
            self.apply_requested.emit()
        return self.exec_result

    def style_patch(self) -> dict[str, Any]:
        return self.patch


class _DialogFactory:
    def __init__(
        self,
        *,
        patch: dict[str, Any],
        auto_apply: bool,
        exec_result: int,
    ) -> None:
        self.patch = patch
        self.auto_apply = auto_apply
        self.exec_result = exec_result
        self.dialog: _FakeDialog | None = None

    def __call__(self, **kwargs: Any) -> _FakeDialog:
        self.dialog = _FakeDialog(
            patch=self.patch,
            auto_apply=self.auto_apply,
            exec_result=self.exec_result,
            **kwargs,
        )
        return self.dialog


def _sample_study() -> ChartStudyInstance:
    return ChartStudyInstance(
        instance_id="study_1",
        dataset_id="bybit_linear_BTCUSDT_1h",
        pane_target=PANE_TARGET_PRICE,
        display_name="SMA 20",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_INDICATOR,
            tool_key="sma",
            params={"period": 20},
            input_bindings={"source": "close"},
        ),
        style=_sample_style(),
        runtime=ChartStudyRuntimeState(render_keys=["sma|study_1|sma_20"]),
    )


class _FakePanel(HistoricalChartPanelStyleMixin):
    def __init__(self) -> None:
        self._study_registry = ChartStudyRegistry()
        self._study_registry.add(_sample_study())
        self.applied: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[str] = []

    def _find_study_by_render_key(self, _render_key: str) -> ChartStudyInstance | None:
        return self._study_registry.get("study_1")

    def _signal_names_for_study(self, _study: ChartStudyInstance) -> list[str]:
        return ["sma_20"]

    def _editable_fill_specs_for_study(self, _study: ChartStudyInstance) -> list[dict[str, str]]:
        return []

    def _defaults_study_key_for_tool_key(self, tool_key: str) -> str:
        return str(tool_key)

    def _apply_study_style_patch(self, instance_id: str, patch: dict[str, Any]) -> None:
        self.applied.append((instance_id, patch))

    def _on_error(self, message: str) -> None:
        self.errors.append(message)


def _style_patch(color: str) -> dict[str, Any]:
    return {
        "global_patch": {},
        "signal_patches": {"sma_20": {"color": color}},
        "fill_patches": {},
        "module_patches": {},
        "peaks_troughs_group_patch": {},
    }


def test_apply_signal_uses_existing_panel_style_patch_without_ok(monkeypatch) -> None:
    patch = _style_patch("#FFFFFF")
    factory = _DialogFactory(
        patch=patch,
        auto_apply=True,
        exec_result=int(QDialog.DialogCode.Rejected),
    )
    monkeypatch.setattr(style_module, "StudyStyleDialog", factory)

    panel = _FakePanel()
    panel._on_price_pane_study_style_requested("study_1")

    assert panel.applied == [("study_1", patch)]
    assert panel.errors == []


def test_ok_applies_current_style_patch(monkeypatch) -> None:
    patch = _style_patch("#00C8FF")
    factory = _DialogFactory(
        patch=patch,
        auto_apply=False,
        exec_result=int(QDialog.DialogCode.Accepted),
    )
    monkeypatch.setattr(style_module, "StudyStyleDialog", factory)

    panel = _FakePanel()
    panel._on_price_pane_study_style_requested("study_1")

    assert panel.applied == [("study_1", patch)]
    assert panel.errors == []


def test_cancel_does_not_apply_unapplied_style_edits(monkeypatch) -> None:
    factory = _DialogFactory(
        patch=_style_patch("#FF1744"),
        auto_apply=False,
        exec_result=int(QDialog.DialogCode.Rejected),
    )
    monkeypatch.setattr(style_module, "StudyStyleDialog", factory)

    panel = _FakePanel()
    panel._on_price_pane_study_style_requested("study_1")

    assert panel.applied == []
    assert panel.errors == []


def test_cancel_after_apply_does_not_rollback_committed_apply(monkeypatch) -> None:
    patch = _style_patch("#BA68C8")
    factory = _DialogFactory(
        patch=patch,
        auto_apply=True,
        exec_result=int(QDialog.DialogCode.Rejected),
    )
    monkeypatch.setattr(style_module, "StudyStyleDialog", factory)

    panel = _FakePanel()
    panel._on_price_pane_study_style_requested("study_1")

    assert panel.applied == [("study_1", patch)]
    assert panel.errors == []


def test_apply_failure_reports_error_without_corrupting_recorded_style() -> None:
    class _FailingPanel(_FakePanel):
        def _apply_study_style_patch(self, instance_id: str, patch: dict[str, Any]) -> None:
            raise RuntimeError(f"style failed for {instance_id}: {patch['signal_patches']}")

    panel = _FailingPanel()
    dialog: Any = _FakeDialog(
        patch=_style_patch("#FFFFFF"),
        auto_apply=False,
        exec_result=int(QDialog.DialogCode.Rejected),
    )

    panel._apply_style_dialog_patch(
        instance_id="study_1",
        dialog=dialog,
    )

    assert panel.applied == []
    assert len(panel.errors) == 1
    assert "Cannot apply style" in panel.errors[0]
    assert "style failed for study_1" in panel.errors[0]


def test_style_apply_boundaries_and_rs7_chart_controls_remain_intact() -> None:
    dialog_source = _source(STYLE_DIALOG)
    helper_body = _function_source(STYLE_MIXIN, "_apply_style_dialog_patch")
    apply_body = _function_source(STYLE_MIXIN, "_apply_study_style_patch")
    overlay_source = _source(OVERLAY_ROWS)
    oscillator_source = _source(OSCILLATOR_PANE)

    assert "apply_requested = Signal()" in dialog_source
    assert "self._apply_study_style_patch(instance_id, patch)" in helper_body
    assert "_reapply_study_render_series" in apply_body
    assert "apply_financial_tool" not in apply_body
    assert "save_recipe" not in apply_body
    assert "calculate_and_save" not in apply_body
    assert "AnalysisDatabase" not in apply_body

    assert "style_requested = Signal(str)" in overlay_source
    assert "edit_requested = Signal(str)" in overlay_source
    assert "remove_requested = Signal(str)" in overlay_source
    assert "metadata_requested" not in overlay_source
    assert "study_style_requested = Signal(str)" in oscillator_source
    assert "study_edit_requested = Signal(str)" in oscillator_source
    assert "study_remove_requested = Signal(str)" in oscillator_source
    assert "study_metadata_requested" not in oscillator_source
    assert "Metadata..." not in overlay_source + oscillator_source
