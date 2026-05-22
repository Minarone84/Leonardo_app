from __future__ import annotations

import ast
from pathlib import Path

import pytest

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PRESET_STATUS_WARNING,
    evaluate_workspace_snapshot_compatibility,
)


ROOT = Path(__file__).resolve().parents[1]
HDM = ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_data_manager_window.py"
MANAGER = ROOT / "src" / "leonardo" / "gui" / "windows" / "_historical_data_manager" / "notebook_manager_dialog.py"
SNAPSHOT_STORE = ROOT / "src" / "leonardo" / "data" / "chart_presets" / "workspace_snapshot_store.py"
STUDY_STORE = ROOT / "src" / "leonardo" / "data" / "chart_presets" / "study_setup_store.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _study_payload() -> dict:
    return {
        "schema_version": 1,
        "family": "indicator",
        "tool_key": "ema",
        "display_name": "EMA 20",
        "pane_target": "price",
        "params": {"period": 20},
        "source_kind": "temporary",
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": [],
        "saved_artifact_ref": None,
        "style": {"signal_styles": {}, "fill_styles": {}, "style_modules": []},
    }


def _chart_payload() -> dict:
    return {
        "position": 1,
        "dataset": {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "30m",
        },
        "viewport": {"center_ts_ms": 1700000000000, "visible_bars": 500},
        "price_view_state": {},
        "studies": [_study_payload()],
    }


def _snapshot_store(tmp_path: Path) -> HistoricalWorkspaceSnapshotStore:
    return HistoricalWorkspaceSnapshotStore(tmp_path / "chart_presets" / "workspace_snapshots")


class _Workspace:
    def chart_count(self) -> int:
        return 0

    def available_embedded_slot_count(self) -> int:
        return 8

    def detached_reserved_slot_count(self) -> int:
        return 0


class _Core:
    def historical_dataset_exists(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        return True


class _MissingNotebookStore:
    def load_notebook(self, notebook_id: str) -> object:
        raise FileNotFoundError(notebook_id)


def test_workspace_snapshot_notebook_ref_roundtrip_and_missing_is_valid(tmp_path: Path) -> None:
    store = _snapshot_store(tmp_path)
    without_ref = store.create_snapshot(
        display_name="No Notebook",
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()],
        snapshot_id="no_notebook",
    )
    with_ref = store.create_snapshot(
        display_name="With Notebook",
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()],
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
        snapshot_id="with_notebook",
    )

    saved_without_ref = store.save_snapshot(without_ref)
    saved_with_ref = store.save_snapshot(with_ref)

    assert store.load_snapshot(saved_without_ref.snapshot_id).notebook_ref is None
    loaded_with_ref = store.load_snapshot(saved_with_ref.snapshot_id)
    assert loaded_with_ref.notebook_ref == {
        "notebook_id": "nb_1",
        "display_name": "Notebook 1",
    }
    assert store.list_summaries()[1].notebook_ref == loaded_with_ref.notebook_ref


def test_invalid_notebook_ref_is_rejected_at_snapshot_store_boundary(tmp_path: Path) -> None:
    store = _snapshot_store(tmp_path)

    with pytest.raises(ValueError, match="notebook_ref.notebook_id"):
        store.create_snapshot(
            display_name="Invalid Ref",
            description="",
            workspace={"visualization_mode": "scroll_4"},
            charts=[_chart_payload()],
            notebook_ref={"display_name": "Missing ID"},
        )


def test_study_setup_store_remains_notebook_free(tmp_path: Path) -> None:
    store = ChartStudySetupStore(tmp_path / "chart_presets" / "study_setups")
    setup = store.create_setup(
        display_name="Setup",
        description="",
        created_from={"exchange": "bybit", "market_type": "linear", "symbol": "BTCUSDT", "timeframe": "30m"},
        studies=[_study_payload()],
        setup_id="setup_1",
    )

    payload = setup.to_dict()

    assert "notebook_ref" not in payload
    assert "notebook" not in payload
    assert "notebook_ref" not in _source(STUDY_STORE)


def test_missing_notebook_ref_warns_without_blocking_snapshot_load(tmp_path: Path) -> None:
    snapshot = _snapshot_store(tmp_path).create_snapshot(
        display_name="With Missing Notebook",
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()],
        notebook_ref={"notebook_id": "missing_notebook"},
        snapshot_id="with_missing_notebook",
    )

    report = evaluate_workspace_snapshot_compatibility(
        snapshot,
        workspace=_Workspace(),
        core_bridge=_Core(),
        load_mode="replace",
        notebook_store=_MissingNotebookStore(),
    )

    assert report.status == PRESET_STATUS_WARNING
    assert report.can_load is True
    assert any(issue.code == "assigned_notebook_unavailable" for issue in report.issues)


def test_workspace_snapshot_load_and_notebook_manager_paths_use_notebook_ref() -> None:
    manager_source = _source(HDM)
    dialog_source = _source(MANAGER)
    load_body = _function_source(HDM, "_on_load_workspace_snapshot")
    manager_body = _function_source(HDM, "_on_open_notebook_manager")
    assign_body = _function_source(MANAGER, "_on_assign_clicked")
    unassign_body = _function_source(MANAGER, "_on_unassign_clicked")
    open_body = _function_source(HDM, "_open_notebook_ref_from_snapshot")

    assert "_open_notebook_ref_from_snapshot(snapshot.notebook_ref)" in load_body
    assert "HistoricalNotebookManagerDialog" in manager_source
    assert "workspace_snapshot_store=self._workspace_snapshot_store()" in manager_body
    assert "def _assignment_map" in dialog_source
    assert "notebook_ref = {" in assign_body
    assert '"notebook_id": summary.notebook_id' in assign_body
    assert "self._workspace_snapshot_store.save_snapshot(updated, overwrite=True)" in assign_body
    assert "notebook_ref=None" in unassign_body
    assert "self._workspace_snapshot_store.save_snapshot(updated, overwrite=True)" in unassign_body
    assert "self._set_current_workspace_notebook_ref(snapshot.notebook_ref)" in load_body
    assert "self._notebook_store().load_notebook(notebook_id)" in open_body
    assert "Assigned notebook could not be loaded" in open_body
    assert "notebook_store=self._notebook_store()" in manager_source


def test_snapshot_store_embeds_only_notebook_ref_not_full_notebook_content() -> None:
    source = _source(SNAPSHOT_STORE)

    assert "notebook_ref" in source
    assert "chart_entries" not in source
    assert "points_of_interest" not in source
