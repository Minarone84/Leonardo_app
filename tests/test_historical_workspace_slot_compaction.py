from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"
WORKSPACE = WINDOWS / "historical_workspace_widget.py"


def _source(path: Path = WORKSPACE) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(function_name: str, path: Path = WORKSPACE) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def test_workspace_slot_compaction_helpers_exist() -> None:
    source = _source()

    assert "def _compact_embedded_chart_slots" in source
    assert "def _available_embedded_slot_indexes" in source


def test_workspace_slot_compaction_excludes_detached_reservations() -> None:
    available_body = _function_source("_available_embedded_slot_indexes")
    compact_body = _function_source("_compact_embedded_chart_slots")

    assert "set(self._detached_slots.values())" in available_body
    assert "if index not in reserved_slots" in available_body
    assert "_available_embedded_slot_indexes()" in compact_body
    assert "_embedded_panels()" in compact_body
    assert "[None] * self.MAX_CHARTS" in compact_body
    assert "normalized_slots[slot_index] = panel" in compact_body
    assert "self._chart_slots = normalized_slots" in compact_body


def test_workspace_remove_and_detached_cleanup_paths_compact_slots() -> None:
    remove_body = _function_source("_remove_chart")
    forget_body = _function_source("_forget_detached_panel")

    assert "preserve_detached_slot" in remove_body
    assert "self._detached_slots[panel] = slot_index" in remove_body
    assert "self._compact_embedded_chart_slots()" in remove_body
    assert "self._detached_slots.pop(panel, None)" in forget_body
    assert "self._compact_embedded_chart_slots()" in forget_body


def test_workspace_move_path_normalizes_after_swap() -> None:
    body = _function_source("move_panel_to_slot")

    assert "target_index in set(self._detached_slots.values())" in body
    assert "target_panel = self._chart_slots[target_index]" in body
    assert "self._chart_slots[target_index] = panel" in body
    assert "self._chart_slots[current_index] = target_panel" in body
    assert "self._compact_embedded_chart_slots()" in body
    assert "self._relayout()" not in body


def test_workspace_new_and_docked_chart_paths_preserve_first_available_policy() -> None:
    first_available_body = _function_source("_first_available_slot_index")
    add_body = _function_source("add_chart")
    add_existing_body = _function_source("add_existing_panel")

    assert "self._available_embedded_slot_indexes()" in first_available_body
    assert "if self._chart_slots[index] is None" in first_available_body
    assert "slot_index = self._first_available_slot_index()" in add_body
    assert "self._compact_embedded_chart_slots()" in add_body
    assert "slot_index = self._detached_slots.pop(panel, None)" in add_existing_body
    assert "self._detached_slots[panel] = slot_index" in add_existing_body
    assert "self._compact_embedded_chart_slots()" in add_existing_body


def test_workspace_compaction_keeps_position_controls_synced_via_relayout() -> None:
    compact_body = _function_source("_compact_embedded_chart_slots")
    relayout_body = _function_source("_relayout")

    assert "self._relayout()" in compact_body
    assert "self._sync_panel_position(panel, slot_index)" in relayout_body
