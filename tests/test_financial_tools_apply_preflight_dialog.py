from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.gui.windows._historical_chart_panel.apply_progress_dialog import (
    FinancialToolApplyProgressDialog,
)
import leonardo.gui.windows._historical_chart_panel.historical_chart_panel_study_apply as apply_module
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_study_apply import (
    HistoricalChartPanelStudyApplyMixin,
)


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
STUDY_APPLY_MIXIN = WINDOWS / "_historical_chart_panel" / "historical_chart_panel_study_apply.py"
APPLY_DIALOG = WINDOWS / "_historical_chart_panel" / "apply_progress_dialog.py"
TOOL_EXECUTION = ROOT / "src" / "leonardo" / "gui" / "historical_chart" / "tool_execution.py"

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


class _Signal:
    def __init__(self) -> None:
        self._slots: list[object] = []

    def connect(self, slot: object) -> None:
        self._slots.append(slot)

    def disconnect(self, slot: object) -> None:
        self._slots.remove(slot)

    def emit(self, *args: object) -> None:
        for slot in list(self._slots):
            slot(*args)  # type: ignore[misc]


class _FakeController:
    def __init__(self, *, mode: str = "success", bar_count: int | None = 321) -> None:
        self.mode = mode
        self.bar_count = bar_count
        self.calls: list[dict] = []
        self.apply_succeeded = _Signal()
        self.error = _Signal()

    def current_input_bar_count(self) -> int | None:
        return self.bar_count

    def apply_financial_tool(self, payload: dict) -> None:
        self.calls.append(payload)
        if self.mode == "success":
            self.apply_succeeded.emit({"display_name": "EMA 20"})
            return
        if self.mode == "error":
            self.error.emit("apply failed")
            return
        raise RuntimeError("apply exploded")


class _FakePanel(HistoricalChartPanelStudyApplyMixin):
    def __init__(self, controller: _FakeController) -> None:
        self._controller = controller
        self._active_apply_progress_dialog = None
        self._editing_study_instance_id = "editing"
        self.errors: list[str] = []

    def dataset_title(self) -> str:
        return "Historical Chart: Bybit_linear_BTCUSDT_1h"

    def _on_error(self, message: str) -> None:
        self.errors.append(message)


class _FakeDialog:
    def __init__(
        self,
        *,
        tool_title: str,
        dataset_label: str,
        input_bar_count: int | None,
        parent: object | None = None,
        auto_start: bool = False,
        exec_result: int = 0,
    ) -> None:
        self.tool_title = tool_title
        self.dataset_label = dataset_label
        self.input_bar_count = input_bar_count
        self.parent = parent
        self.auto_start = auto_start
        self.exec_result = exec_result
        self.apply_requested = _Signal()
        self.started = False
        self.cancel_enabled = True
        self.success_message = ""
        self.failure_message = ""

    def exec(self) -> int:
        if self.auto_start:
            self.apply_requested.emit()
        return self.exec_result

    def start_applying(self) -> None:
        self.started = True
        self.cancel_enabled = False

    def mark_success(self, message: str) -> None:
        self.success_message = message

    def mark_failure(self, message: str) -> None:
        self.failure_message = message


class _DialogFactory:
    def __init__(self, *, auto_start: bool, exec_result: int = 0) -> None:
        self.auto_start = auto_start
        self.exec_result = exec_result
        self.dialog: _FakeDialog | None = None

    def __call__(self, **kwargs: object) -> _FakeDialog:
        self.dialog = _FakeDialog(
            **kwargs,
            auto_start=self.auto_start,
            exec_result=self.exec_result,
        )
        return self.dialog


def _payload() -> dict:
    return {
        "tool_type": "indicator",
        "tool_key": "ema",
        "tool_title": "EMA 20",
        "params": {"period": 20},
    }


def test_apply_progress_dialog_shows_preflight_and_honest_states() -> None:
    _qapp()
    dialog = FinancialToolApplyProgressDialog(
        tool_title="EMA 20",
        dataset_label="Historical Chart: Bybit_linear_BTCUSDT_1h",
        input_bar_count=321,
    )
    try:
        assert dialog.windowTitle() == "Apply Study"
        assert dialog._tool_label.text() == "Study: EMA 20"
        assert dialog._dataset_label.text() == "Target: Historical Chart: Bybit_linear_BTCUSDT_1h"
        assert dialog._bar_count_label.text() == "Input bars to process: 321"
        assert dialog._apply_button.isEnabled()
        assert dialog._cancel_button.isEnabled()
        assert not dialog._ok_button.isEnabled()

        dialog.start_applying()
        assert not dialog._apply_button.isEnabled()
        assert not dialog._cancel_button.isEnabled()
        assert not dialog._ok_button.isEnabled()
        assert dialog._progress.minimum() == 0
        assert dialog._progress.maximum() == 0

        dialog.mark_success("Applied EMA 20.")
        assert dialog._ok_button.isEnabled()
        assert dialog._progress.maximum() == 1
        assert dialog._progress.value() == 1

        dialog.mark_failure("apply failed")
        assert dialog._ok_button.isEnabled()
        assert dialog._progress.maximum() == 1
        assert dialog._status_label.text() == "apply failed"
    finally:
        dialog.close()


def test_pre_execution_cancel_prevents_controller_apply(monkeypatch) -> None:
    _qapp()
    controller = _FakeController()
    panel = _FakePanel(controller)
    factory = _DialogFactory(auto_start=False)
    monkeypatch.setattr(apply_module, "FinancialToolApplyProgressDialog", factory)

    panel._on_financial_tools_apply_requested(_payload())

    assert controller.calls == []
    assert factory.dialog is not None
    assert factory.dialog.tool_title == "EMA 20"
    assert factory.dialog.dataset_label == "Historical Chart: Bybit_linear_BTCUSDT_1h"
    assert factory.dialog.input_bar_count == 321
    assert panel._active_apply_progress_dialog is None


def test_apply_start_calls_existing_controller_apply_and_marks_success(monkeypatch) -> None:
    _qapp()
    controller = _FakeController(mode="success", bar_count=500)
    panel = _FakePanel(controller)
    payload = _payload()
    factory = _DialogFactory(auto_start=True)
    monkeypatch.setattr(apply_module, "FinancialToolApplyProgressDialog", factory)

    panel._on_financial_tools_apply_requested(payload)

    assert controller.calls == [payload]
    assert factory.dialog is not None
    assert factory.dialog.started
    assert factory.dialog.cancel_enabled is False
    assert factory.dialog.success_message == "Applied EMA 20."
    assert factory.dialog.failure_message == ""


def test_apply_failure_is_visible_in_dialog(monkeypatch) -> None:
    _qapp()
    controller = _FakeController(mode="error")
    panel = _FakePanel(controller)
    factory = _DialogFactory(auto_start=True)
    monkeypatch.setattr(apply_module, "FinancialToolApplyProgressDialog", factory)

    panel._on_financial_tools_apply_requested(_payload())

    assert controller.calls
    assert factory.dialog is not None
    assert factory.dialog.failure_message == "apply failed"
    assert factory.dialog.success_message == ""


def test_apply_exception_is_visible_and_edit_state_is_cleared(monkeypatch) -> None:
    _qapp()
    controller = _FakeController(mode="raise")
    panel = _FakePanel(controller)
    factory = _DialogFactory(auto_start=True)
    monkeypatch.setattr(apply_module, "FinancialToolApplyProgressDialog", factory)

    panel._on_financial_tools_apply_requested(_payload())

    assert factory.dialog is not None
    assert "Financial tool apply failed" in factory.dialog.failure_message
    assert panel._editing_study_instance_id is None
    assert panel.errors


def test_dialog_does_not_own_study_registration_or_persistence() -> None:
    dialog_source = _source(APPLY_DIALOG)
    success_body = _function_source(STUDY_APPLY_MIXIN, "_on_financial_tools_apply_succeeded")
    apply_body = _function_source(TOOL_EXECUTION, "apply_financial_tool")

    assert "_study_registry" not in dialog_source
    assert "self._study_registry.add" in success_body
    assert "ArtifactRecipeStore" not in apply_body
    assert "save_recipe(" not in apply_body
    assert "save_dataframe(" not in apply_body
    assert "calculate_and_save" not in apply_body


def test_apply_preflight_does_not_add_worker_or_fake_cancellation_architecture() -> None:
    source = _source(APPLY_DIALOG) + _source(STUDY_APPLY_MIXIN)

    assert "QThread" not in source
    assert "TaskManager" not in source
    assert "Future" not in source
    assert "cancel_token" not in source
    assert "cancellation_token" not in source
    assert "QProgressBar" in source
    assert "Input bars to process" in source
