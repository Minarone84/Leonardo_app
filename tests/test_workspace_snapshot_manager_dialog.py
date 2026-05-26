from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractItemView, QApplication

from leonardo.data.chart_presets.notebook_store import (
    HistoricalNotebookStore,
    notebook_chart_key,
)
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotManagerDialog,
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


def _dataset() -> dict:
    return {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "30m",
    }


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
            "description": "Snapshot study metadata.",
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


def _chart_payload() -> dict:
    return {
        "position": 1,
        "dataset": _dataset(),
        "viewport": {"center_ts_ms": 1700000000000, "visible_bars": 500},
        "price_view_state": {},
        "studies": [_study_payload()],
    }


def _snapshot_store(tmp_path: Path) -> HistoricalWorkspaceSnapshotStore:
    return HistoricalWorkspaceSnapshotStore(
        tmp_path / "chart_presets" / "workspace_snapshots"
    )


def _notebook_store(tmp_path: Path) -> HistoricalNotebookStore:
    return HistoricalNotebookStore(tmp_path / "chart_presets" / "notebooks")


def _save_snapshot(
    store: HistoricalWorkspaceSnapshotStore,
    *,
    notebook_ref: dict | None = None,
) -> None:
    snapshot = store.create_snapshot(
        display_name="Morning Workspace",
        description="Reusable workspace",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()],
        notebook_ref=notebook_ref,
        snapshot_id="snapshot_1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    store.save_snapshot(snapshot)


def _save_notebook(store: HistoricalNotebookStore) -> None:
    dataset = _dataset()
    notebook = store.create_notebook(
        display_name="Notebook 1",
        description="Notebook description",
        chart_entries=[
            {
                "chart_key": notebook_chart_key(dataset),
                "dataset": dataset,
                "last_seen_position": 1,
                "notes": [],
                "trades": [],
                "points_of_interest": [],
            }
        ],
        notebook_id="nb_1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    store.save_notebook(notebook)


def _dialog(store: HistoricalWorkspaceSnapshotStore) -> WorkspaceSnapshotManagerDialog:
    _qapp()
    return WorkspaceSnapshotManagerDialog(store=store)


def test_manager_lists_snapshot_charts_studies_and_notebook_ref(tmp_path: Path) -> None:
    store = _snapshot_store(tmp_path)
    _save_snapshot(
        store,
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )

    dialog = _dialog(store)
    try:
        assert dialog._snapshot_list.count() == 1
        assert dialog._snapshot_list.currentItem().text() == "Morning Workspace"
        detail_text = dialog._detail_text.toPlainText()
        assert "Notebook 1 (nb_1)" in detail_text
        assert "Charts: 1" in detail_text
        assert dialog._chart_table.rowCount() == 1
        assert dialog._chart_table.item(0, 2).text() == "bybit / linear / BTCUSDT"
        assert dialog._study_table.rowCount() == 1
        assert dialog._study_table.item(0, 1).text() == "EMA 20"
        assert dialog._study_table.item(0, 4).text() == "yes"
        assert dialog._study_table.editTriggers() == QAbstractItemView.NoEditTriggers
    finally:
        dialog.close()


def test_manager_updates_top_level_snapshot_without_mutating_payload(
    tmp_path: Path,
) -> None:
    store = _snapshot_store(tmp_path)
    _save_snapshot(
        store,
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    original = store.load_snapshot("snapshot_1")

    dialog = _dialog(store)
    try:
        dialog._name_edit.setText("Morning Workspace Updated")
        dialog._description_edit.setPlainText("Updated workspace description")
        dialog._on_save_clicked()
    finally:
        dialog.close()

    updated = store.load_snapshot("snapshot_1")

    assert updated.snapshot_id == original.snapshot_id
    assert updated.display_name == "Morning Workspace Updated"
    assert updated.description == "Updated workspace description"
    assert updated.created_at_ms == original.created_at_ms
    assert updated.updated_at_ms >= original.updated_at_ms
    assert updated.content_hash != original.content_hash
    assert updated.notebook_ref == {"notebook_id": "nb_1", "display_name": "Notebook 1"}
    assert updated.workspace == original.workspace
    assert updated.charts == original.charts
    assert len(list(store.root_dir.glob("*.json"))) == 1


def test_manager_delete_snapshot_does_not_delete_assigned_notebook(
    tmp_path: Path,
) -> None:
    snapshot_store = _snapshot_store(tmp_path)
    notebook_store = _notebook_store(tmp_path)
    _save_notebook(notebook_store)
    _save_snapshot(
        snapshot_store,
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    notebook_path = notebook_store.notebook_path("nb_1")

    dialog = _dialog(snapshot_store)
    try:
        dialog._confirm_delete_snapshot = lambda snapshot: True
        dialog._on_delete_clicked()
        assert dialog._snapshot_list.count() == 0
    finally:
        dialog.close()

    assert not snapshot_store.snapshot_exists("snapshot_1")
    assert notebook_path.exists()


def test_research_suite_has_workspace_snapshot_manager_entry_point() -> None:
    source = HDM.read_text(encoding="utf-8")

    assert 'QAction("Manage Workspace Snapshots..."' in source
    assert "WorkspaceSnapshotManagerDialog" in source
    assert "self._on_manage_workspace_snapshots" in source
