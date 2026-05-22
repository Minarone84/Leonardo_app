from __future__ import annotations

import ast
from pathlib import Path
import textwrap

from leonardo.gui.chart.viewport import ChartViewport


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
HDM = WINDOWS / "historical_data_manager_window.py"
PANEL = WINDOWS / "historical_chart_panel.py"
WORKSPACE = WINDOWS / "historical_workspace_widget.py"
VIEWPORT = ROOT / "src" / "leonardo" / "gui" / "chart" / "viewport.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _function_from_source(path: Path, function_name: str):
    namespace: dict[str, object] = {}
    exec(textwrap.dedent(_function_source(path, function_name)), namespace)
    return namespace[function_name]


class _Action:
    def __init__(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked


class _Panel:
    def __init__(self, ts_ms: int | None) -> None:
        self._ts_ms = ts_ms
        self.center_calls: list[int] = []

    def current_center_timestamp_ms(self) -> int | None:
        return self._ts_ms

    def center_on_timestamp_ms(self, ts_ms: int) -> bool:
        self.center_calls.append(int(ts_ms))
        return True


class _Workspace:
    def __init__(self, panels: list[_Panel]) -> None:
        self._panels = panels

    def list_active_chart_panels(self) -> list[_Panel]:
        return list(self._panels)


class _Manager:
    def __init__(self, *, checked: bool, panels: list[_Panel]) -> None:
        self._action_pan_anchor = _Action(checked)
        self._syncing_pan_anchor = False
        self._workspace_widget = _Workspace(panels)
        self.status_messages: list[str] = []

    def _set_status(self, message: str) -> None:
        self.status_messages.append(message)

    def _active_historical_chart_panels(self) -> list[_Panel]:
        return self._workspace_widget.list_active_chart_panels()


def test_pan_anchor_quick_action_is_checkable_and_off_by_default() -> None:
    source = _source(HDM)
    corner_body = _function_source(HDM, "_build_menu_bar_corner_widget")

    assert "_action_pan_anchor" in source
    assert 'QAction("Pan Anchor", self, checkable=True)' in source
    assert "action_pan_anchor.setChecked(False)" in source
    assert "Synchronize horizontal panning across all active historical charts." in source
    assert "action=self._action_pan_anchor" in corner_body
    assert "text=\"Pan Anchor\"" in corner_body


def test_viewport_pan_signal_is_limited_to_horizontal_pan_methods() -> None:
    viewport = ChartViewport(total_count=1000, visible_count=100)
    pan_events: list[str] = []

    viewport.horizontal_pan_changed.connect(lambda: pan_events.append("pan"))

    viewport.pan_left(10)
    assert pan_events == ["pan"]

    pan_events.clear()
    viewport.zoom_in_at(viewport.start + 10, 0.5)
    viewport.set_window(viewport.start - 5, viewport.end - 5)

    assert pan_events == []


def test_pan_anchor_sync_uses_source_timestamp_and_preserves_reentry_guard() -> None:
    source = _Panel(1700000000000)
    target_a = _Panel(1700000300000)
    target_b = _Panel(1700000600000)
    manager = _Manager(checked=True, panels=[source, target_a, target_b])
    handler = _function_from_source(HDM, "_on_pan_anchor_panel_panned")

    handler(manager, source)

    assert target_a.center_calls == [1700000000000]
    assert target_b.center_calls == [1700000000000]
    assert source.center_calls == []
    assert manager._syncing_pan_anchor is False

    manager._syncing_pan_anchor = True
    handler(manager, source)

    assert target_a.center_calls == [1700000000000]
    assert target_b.center_calls == [1700000000000]


def test_pan_anchor_off_does_not_recenter_other_panels() -> None:
    source = _Panel(1700000000000)
    target = _Panel(1700000300000)
    manager = _Manager(checked=False, panels=[source, target])
    handler = _function_from_source(HDM, "_on_pan_anchor_panel_panned")

    handler(manager, source)

    assert target.center_calls == []


def test_pan_anchor_uses_workspace_active_panels_and_panel_timestamp_helpers() -> None:
    hdm_source = _source(HDM)
    panel_source = _source(PANEL)
    workspace_source = _source(WORKSPACE)
    viewport_source = _source(VIEWPORT)
    sync_body = _function_source(HDM, "_on_pan_anchor_panel_panned")

    assert "list_active_chart_panels" in hdm_source
    assert "current_center_timestamp_ms" in sync_body
    assert "center_on_timestamp_ms" in sync_body
    assert "_syncing_pan_anchor" in sync_body
    assert "horizontal_pan_requested = Signal(object)" in panel_source
    assert "horizontal_pan_changed.connect(self._on_horizontal_pan_changed)" in panel_source
    assert "chart_horizontal_pan_requested = Signal(object)" in workspace_source
    assert "self._detached_slots" in _function_source(WORKSPACE, "list_active_chart_panels")
    assert "horizontal_pan_changed = Signal()" in viewport_source
