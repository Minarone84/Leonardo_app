from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo" / "gui"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_historical_chart_panel_go_to_button_is_left_of_financial_tools() -> None:
    source = _source(SRC / "windows" / "historical_chart_panel.py")

    assert "QInputDialog" in source
    assert "_go_to_button = QToolButton" in source
    assert 'setText("Go to")' in source
    assert "_go_to_button.clicked.connect(self._on_go_to_clicked)" in source
    assert "center_view_on_timestamp_ms" in source

    go_to_pos = source.index("status_layout.addWidget(self._go_to_button)")
    financial_tools_pos = source.index("status_layout.addWidget(self._financial_tools_button)")
    assert go_to_pos < financial_tools_pos


def test_historical_chart_controller_owns_go_to_timeline_navigation() -> None:
    path = SRC / "historical_chart_controller.py"
    source = _source(path)
    body = _function_source(path, "center_view_on_timestamp_ms")

    assert "def center_view_on_timestamp_ms" in source
    assert "nearest_global_index_for_ts_ms" in body
    assert "center_on_index" in body
    assert "request_slice(" not in body


def test_chart_data_session_supports_nearest_timestamp_lookup() -> None:
    source = _source(SRC / "historical_chart" / "session.py")

    assert "def nearest_global_index_for_ts_ms" in source
    assert "bisect_left" in source


def test_chart_viewport_exposes_center_on_index_camera_operation() -> None:
    path = SRC / "chart" / "viewport.py"
    source = _source(path)
    body = _function_source(path, "center_on_index")

    assert "def center_on_index" in source
    assert "self.set_window" in body
