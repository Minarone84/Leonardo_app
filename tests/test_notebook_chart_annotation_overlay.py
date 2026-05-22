from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_chart_panel.py"
HDM = ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_data_manager_window.py"
NOTEBOOK = ROOT / "src" / "leonardo" / "gui" / "windows" / "_historical_data_manager" / "notebook_window.py"
STUDY_SETUP_STORE = ROOT / "src" / "leonardo" / "data" / "chart_presets" / "study_setup_store.py"
SNAPSHOT_STORE = ROOT / "src" / "leonardo" / "data" / "chart_presets" / "workspace_snapshot_store.py"
CHART_RENDER = ROOT / "src" / "leonardo" / "gui" / "chart" / "chart_render.py"
PRICE_PANE = ROOT / "src" / "leonardo" / "gui" / "chart" / "panes" / "price_pane.py"
WORKSPACE = ROOT / "src" / "leonardo" / "gui" / "chart" / "workspace.py"
Y_AXIS_INTERACTION = ROOT / "src" / "leonardo" / "gui" / "chart" / "rendering" / "y_axis_interaction.py"
MARKER_PAINTER = ROOT / "src" / "leonardo" / "gui" / "chart" / "rendering" / "marker_painter.py"
FINANCIAL_TOOLS = ROOT / "src" / "leonardo" / "financial_tools"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_notebook_poi_overlay_uses_dedicated_chart_api_not_hidden_studies() -> None:
    panel_source = _source(PANEL)
    set_body = _function_source(PANEL, "set_notebook_poi_markers")
    refresh_body = _function_source(PANEL, "_refresh_notebook_poi_overlay")
    set_pt_body = _function_source(PANEL, "set_notebook_pt_markers")
    refresh_pt_body = _function_source(PANEL, "_refresh_notebook_pt_overlay")
    refresh_pt_direction_body = _function_source(PANEL, "_refresh_notebook_pt_direction_overlay")

    assert "def set_notebook_poi_markers" in panel_source
    assert "def clear_notebook_poi_markers" in panel_source
    assert "def set_notebook_pt_markers" in panel_source
    assert "def clear_notebook_pt_markers" in panel_source
    assert "not registered as\n        chart studies" in set_body
    assert "not\n        registered as chart studies or financial-tool outputs" in set_pt_body
    assert "ChartStudyInstance" not in set_body
    assert "ChartStudyRegistry" not in set_body
    assert "_registry" not in set_body
    assert "ChartStudyInstance" not in set_pt_body
    assert "ChartStudyRegistry" not in set_pt_body
    assert "_registry" not in set_pt_body
    assert "apply_overlay_series" in refresh_body
    assert "__notebook_poi_markers__" in refresh_body
    assert "remove_overlay_series" in refresh_body
    assert "apply_overlay_series" in refresh_pt_direction_body
    assert "__notebook_pt_long_markers__" in refresh_pt_body
    assert "__notebook_pt_short_markers__" in refresh_pt_body
    assert "remove_overlay_series" in refresh_pt_direction_body


def test_marker_payloads_contain_required_runtime_fields() -> None:
    panel_body = _function_source(PANEL, "set_notebook_poi_markers")
    panel_pt_body = _function_source(PANEL, "set_notebook_pt_markers")
    notebook_body = _function_source(NOTEBOOK, "_build_poi_markers_by_chart_key_from_entries")
    notebook_pt_body = _function_source(NOTEBOOK, "_build_pt_markers_by_chart_key_from_entries")

    for key in ('"ts_ms"', '"title"', '"description"'):
        assert key in panel_body
        assert key in notebook_body

    for key in (
        '"ts_ms"',
        '"direction"',
        '"starting_price"',
        '"target_pct_movement"',
        '"closing_price"',
        '"outcome"',
        '"note"',
        '"marker_side"',
        '"marker_offset"',
    ):
        assert key in panel_pt_body
        assert key in notebook_pt_body


def test_date_go_to_reuses_existing_center_on_timestamp_path() -> None:
    generic_panel_body = _function_source(PANEL, "center_on_timestamp_ms")
    panel_body = _function_source(PANEL, "center_on_notebook_timestamp")
    manager_body = _function_source(HDM, "_on_notebook_goto_requested")
    notebook_body = _function_source(NOTEBOOK, "_on_row_goto_clicked")

    assert "center_view_on_timestamp_ms" in generic_panel_body
    assert "center_on_timestamp_ms" in panel_body
    assert "center_on_notebook_timestamp" in manager_body
    assert "self.goto_requested.emit(chart_key, int(ts_ms))" in notebook_body
    assert "center_view_on_timestamp_ms" not in notebook_body


def test_runtime_tooltip_and_grouped_marker_support_are_plumbed() -> None:
    panel_body = _function_source(PANEL, "_refresh_notebook_poi_overlay")
    pt_panel_body = _function_source(PANEL, "_refresh_notebook_pt_overlay")
    pt_direction_body = _function_source(PANEL, "_refresh_notebook_pt_direction_overlay")
    render_source = _source(CHART_RENDER)
    price_source = _source(PRICE_PANE)
    workspace_source = _source(WORKSPACE)
    interaction_source = _source(Y_AXIS_INTERACTION)

    assert "grouped_by_local_index" in panel_body
    assert '"\\n".join(titles)' in panel_body
    assert 'marker_text = "+"' in panel_body
    assert 'marker_shape="circle"' in panel_body
    assert "marker_offset_px=marker_offset_px" in panel_body
    assert "default=28" in panel_body
    assert 'marker_text="↑"' in pt_panel_body
    assert 'marker_text="↓"' in pt_panel_body
    assert 'color="#22C55E"' in pt_panel_body
    assert 'color="#EF4444"' in pt_panel_body
    assert 'marker_shape="circle"' in pt_direction_body
    assert "candle.high" in pt_direction_body
    assert "candle.low" in pt_direction_body
    assert "marker_offset_px=marker_offset_px" in pt_direction_body
    assert "default_offset=56" in pt_panel_body
    assert "default_offset=-56" in pt_panel_body
    assert "set_notebook_poi_tooltips" in render_source
    assert "set_notebook_poi_tooltips" in price_source
    assert "set_notebook_poi_tooltips" in workspace_source
    assert "_notebook_poi_tooltip_for_index" in interaction_source


def test_notebook_poi_marker_shape_uses_supported_circle_marker() -> None:
    panel_body = _function_source(PANEL, "_refresh_notebook_poi_overlay")
    pt_direction_body = _function_source(PANEL, "_refresh_notebook_pt_direction_overlay")
    marker_painter_source = _source(MARKER_PAINTER)

    assert 'marker_shape="circle"' in panel_body
    assert 'marker_shape="circle"' in pt_direction_body
    assert '"circle"' in marker_painter_source
    assert "drawEllipse" in marker_painter_source


def test_notebook_marker_state_is_not_serialized_into_presets_or_studies() -> None:
    study_setup_source = _source(STUDY_SETUP_STORE)
    snapshot_store_source = _source(SNAPSHOT_STORE)

    assert "__notebook_poi_markers__" not in study_setup_source
    assert "__notebook_pt_long_markers__" not in study_setup_source
    assert "__notebook_pt_short_markers__" not in study_setup_source
    assert "__notebook_poi_markers__" not in snapshot_store_source
    assert "__notebook_pt_long_markers__" not in snapshot_store_source
    assert "__notebook_pt_short_markers__" not in snapshot_store_source
    assert "points_of_interest" not in study_setup_source
    assert "notebook_ref" not in study_setup_source
    assert "notebook_ref" in snapshot_store_source
    assert "points_of_interest" not in snapshot_store_source


def test_financial_tool_runtime_is_not_touched_by_notebook_overlay() -> None:
    financial_tool_files = [
        path
        for path in FINANCIAL_TOOLS.rglob("*.py")
        if "__pycache__" not in path.parts
    ]

    assert financial_tool_files
    assert not any(
        "__notebook_poi_markers__" in path.read_text(encoding="utf-8")
        or "__notebook_pt_long_markers__" in path.read_text(encoding="utf-8")
        or "__notebook_pt_short_markers__" in path.read_text(encoding="utf-8")
        or "HistoricalNotebook" in path.read_text(encoding="utf-8")
        for path in financial_tool_files
    )
