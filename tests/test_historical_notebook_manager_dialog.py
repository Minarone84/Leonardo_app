from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from leonardo.data.chart_presets.notebook_store import (
    HistoricalNotebookStore,
    notebook_chart_key,
)
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.windows._historical_data_manager.notebook_manager_dialog import (
    HistoricalNotebookManagerDialog,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _dataset(symbol: str = "BTCUSDT") -> dict:
    return {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": symbol,
        "timeframe": "30m",
    }


def _chart_entry(symbol: str = "BTCUSDT") -> dict:
    dataset = _dataset(symbol)
    return {
        "chart_key": notebook_chart_key(dataset),
        "dataset": dataset,
        "last_seen_position": 1,
        "notes": [],
        "trades": [],
        "points_of_interest": [],
    }


def _chart_payload(symbol: str = "BTCUSDT") -> dict:
    return {
        "position": 1,
        "dataset": _dataset(symbol),
        "viewport": {"center_ts_ms": 1700000000000, "visible_bars": 500},
        "price_view_state": {},
        "studies": [],
    }


def _stores(
    tmp_path: Path,
) -> tuple[HistoricalNotebookStore, HistoricalWorkspaceSnapshotStore]:
    return (
        HistoricalNotebookStore(tmp_path / "chart_presets" / "notebooks"),
        HistoricalWorkspaceSnapshotStore(
            tmp_path / "chart_presets" / "workspace_snapshots"
        ),
    )


def _save_notebook(
    store: HistoricalNotebookStore,
    *,
    notebook_id: str,
    display_name: str,
) -> None:
    notebook = store.create_notebook(
        display_name=display_name,
        description=f"{display_name} description",
        chart_entries=[_chart_entry()],
        notebook_id=notebook_id,
        created_at_ms=1000,
        updated_at_ms=2000,
    )
    store.save_notebook(notebook)


def _save_snapshot(
    store: HistoricalWorkspaceSnapshotStore,
    *,
    snapshot_id: str,
    display_name: str,
    notebook_ref: dict | None = None,
) -> None:
    snapshot = store.create_snapshot(
        display_name=display_name,
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()],
        notebook_ref=notebook_ref,
        snapshot_id=snapshot_id,
        created_at_ms=1000,
        updated_at_ms=2000,
    )
    store.save_snapshot(snapshot)


def _dialog(
    notebook_store: HistoricalNotebookStore,
    snapshot_store: HistoricalWorkspaceSnapshotStore,
) -> HistoricalNotebookManagerDialog:
    _qapp()
    return HistoricalNotebookManagerDialog(
        notebook_store=notebook_store,
        workspace_snapshot_store=snapshot_store,
    )


def _select_notebook(
    dialog: HistoricalNotebookManagerDialog,
    notebook_id: str,
) -> None:
    table = dialog._table
    assert table is not None
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        assert item is not None
        if str(item.data(dialog._NOTEBOOK_ID_ROLE)) == notebook_id:
            table.selectRow(row)
            return
    raise AssertionError(f"Notebook row not found: {notebook_id}")


def test_notebook_manager_lists_assigned_and_unassigned_notebooks(tmp_path: Path) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_assigned", display_name="Assigned")
    _save_notebook(notebook_store, notebook_id="nb_free", display_name="Free")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_assigned",
        display_name="Assigned Snapshot",
        notebook_ref={"notebook_id": "nb_assigned", "display_name": "Assigned"},
    )
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_free",
        display_name="Free Snapshot",
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        table = dialog._table
        assert table is not None
        rows = {
            str(table.item(row, 0).data(dialog._NOTEBOOK_ID_ROLE)): [
                table.item(row, column).text() for column in range(table.columnCount())
            ]
            for row in range(table.rowCount())
        }

        assert rows["nb_assigned"][0] == "Assigned"
        assert rows["nb_assigned"][3] == "1"
        assert rows["nb_assigned"][4] == "Assigned Snapshot"
        assert rows["nb_free"][0] == "Free"
        assert rows["nb_free"][3] == "0"
        assert rows["nb_free"][4] == "Unassigned"
        assert rows["nb_assigned"][2] == "1970-01-01 00:00:02 UTC"
    finally:
        dialog.close()


def test_manager_assignment_updates_only_workspace_snapshot_notebook_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(snapshot_store, snapshot_id="snap_1", display_name="Snapshot 1")
    notebook_path = notebook_store.notebook_path("nb_1")
    notebook_before = json.loads(notebook_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **_kwargs: (args[3][0], True),
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        dialog._on_assign_clicked()
    finally:
        dialog.close()

    snapshot = snapshot_store.load_snapshot("snap_1")
    assert snapshot.notebook_ref == {
        "notebook_id": "nb_1",
        "display_name": "Notebook 1",
    }
    assert json.loads(notebook_path.read_text(encoding="utf-8")) == notebook_before
    assert "assigned_workspaces" not in notebook_before
    assert "workspace_snapshots" not in notebook_before


def test_manager_unassignment_clears_only_workspace_snapshot_notebook_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_1",
        display_name="Snapshot 1",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    notebook_path = notebook_store.notebook_path("nb_1")
    notebook_before = json.loads(notebook_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        dialog._on_unassign_clicked()
    finally:
        dialog.close()

    assert snapshot_store.load_snapshot("snap_1").notebook_ref is None
    assert json.loads(notebook_path.read_text(encoding="utf-8")) == notebook_before


def test_manager_warns_before_linking_already_assigned_notebook(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_assigned",
        display_name="Assigned Snapshot",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    _save_snapshot(snapshot_store, snapshot_id="snap_target", display_name="Target Snapshot")

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **_kwargs: (args[3][1], True),
    )
    questions: list[str] = []

    def _question(*args, **_kwargs):
        questions.append(str(args[2]))
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", _question)

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        dialog._on_assign_clicked()
    finally:
        dialog.close()

    assert questions
    assert "already assigned to" in questions[0]
    assert snapshot_store.load_snapshot("snap_target").notebook_ref is None


def test_manager_can_link_same_notebook_to_multiple_snapshots_after_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_assigned",
        display_name="Assigned Snapshot",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    _save_snapshot(snapshot_store, snapshot_id="snap_target", display_name="Target Snapshot")

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **_kwargs: (args[3][1], True),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        dialog._on_assign_clicked()
    finally:
        dialog.close()

    assigned_ref = snapshot_store.load_snapshot("snap_assigned").notebook_ref
    target_ref = snapshot_store.load_snapshot("snap_target").notebook_ref
    assert assigned_ref == target_ref == {
        "notebook_id": "nb_1",
        "display_name": "Notebook 1",
    }

    notebook = notebook_store.load_notebook("nb_1")
    notebook_store.save_notebook(
        replace(notebook, description="Shared edit", updated_at_ms=3000),
        overwrite=True,
    )

    assert notebook_store.load_notebook(assigned_ref["notebook_id"]).description == (
        "Shared edit"
    )
    assert notebook_store.load_notebook(target_ref["notebook_id"]).description == (
        "Shared edit"
    )


def test_manager_delete_unassigned_notebook_confirms_deletes_and_refreshes(
    tmp_path: Path,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_notebook(notebook_store, notebook_id="nb_2", display_name="Notebook 2")

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        confirmations: list[tuple[str, int]] = []
        deleted: list[str] = []
        dialog._confirm_delete_notebook = (
            lambda summary, assignments: confirmations.append(
                (summary.notebook_id, len(assignments))
            )
            or True
        )
        dialog.notebook_deleted.connect(lambda notebook_id: deleted.append(notebook_id))

        dialog._on_delete_clicked()

        table = dialog._table
        assert table is not None
        remaining_ids = {
            str(table.item(row, 0).data(dialog._NOTEBOOK_ID_ROLE))
            for row in range(table.rowCount())
        }
        assert confirmations == [("nb_1", 0)]
        assert deleted == ["nb_1"]
        assert remaining_ids == {"nb_2"}
        assert not notebook_store.notebook_path("nb_1").exists()
        assert notebook_store.notebook_path("nb_2").exists()
    finally:
        dialog.close()


def test_manager_delete_assigned_notebook_clears_snapshot_refs_and_notebook_file(
    tmp_path: Path,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_1",
        display_name="Snapshot 1",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_2",
        display_name="Snapshot 2",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        confirmations: list[tuple[str, tuple[str, ...]]] = []
        dialog._confirm_delete_notebook = (
            lambda summary, assignments: confirmations.append(
                (
                    summary.notebook_id,
                    tuple(item.display_name for item in assignments),
                )
            )
            or True
        )

        dialog._on_delete_clicked()

        assert confirmations == [("nb_1", ("Snapshot 1", "Snapshot 2"))]
        assert not notebook_store.notebook_path("nb_1").exists()
        assert snapshot_store.load_snapshot("snap_1").notebook_ref is None
        assert snapshot_store.load_snapshot("snap_2").notebook_ref is None
        table = dialog._table
        assert table is not None
        assert table.rowCount() == 0
    finally:
        dialog.close()


def test_manager_delete_confirmation_cancel_leaves_notebook_and_refs(
    tmp_path: Path,
) -> None:
    notebook_store, snapshot_store = _stores(tmp_path)
    _save_notebook(notebook_store, notebook_id="nb_1", display_name="Notebook 1")
    _save_snapshot(
        snapshot_store,
        snapshot_id="snap_1",
        display_name="Snapshot 1",
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook 1"},
    )

    dialog = _dialog(notebook_store, snapshot_store)
    try:
        _select_notebook(dialog, "nb_1")
        dialog._confirm_delete_notebook = lambda _summary, _assignments: False

        dialog._on_delete_clicked()

        assert notebook_store.notebook_path("nb_1").exists()
        assert snapshot_store.load_snapshot("snap_1").notebook_ref == {
            "notebook_id": "nb_1",
            "display_name": "Notebook 1",
        }
        table = dialog._table
        assert table is not None
        assert table.rowCount() == 1
    finally:
        dialog.close()
