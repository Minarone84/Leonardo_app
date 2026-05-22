from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from leonardo.data.chart_presets.study_setup_store import (
    CHART_STUDY_SETUP_OBJECT_TYPE,
    CHART_STUDY_SETUP_SCHEMA_VERSION,
    ChartStudySetup,
)
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
    HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
    HistoricalWorkspaceSnapshot,
)
from leonardo.gui.windows._historical_data_manager.study_setup_dialogs import (
    LoadStudySetupDialog,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_dialogs import (
    LoadWorkspaceSnapshotDialog,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _study_payload() -> dict:
    return {
        "family": "indicator",
        "tool_key": "ema",
        "display_name": "EMA 20",
        "pane_target": "price",
        "params": {"period": 20},
        "style": {},
    }


def _study_setup(setup_id: str, display_name: str) -> ChartStudySetup:
    return ChartStudySetup(
        schema_version=CHART_STUDY_SETUP_SCHEMA_VERSION,
        object_type=CHART_STUDY_SETUP_OBJECT_TYPE,
        setup_id=setup_id,
        content_hash="",
        display_name=display_name,
        description="Reusable study setup",
        created_at_ms=1000,
        updated_at_ms=1000,
        created_from={
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=(_study_payload(),),
    )


def _chart_payload() -> dict:
    return {
        "position": 1,
        "dataset": {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        "viewport": {},
        "price_view_state": {},
        "studies": [],
    }


def _workspace_snapshot(
    snapshot_id: str,
    display_name: str,
    *,
    notebook_ref: dict | None = None,
) -> HistoricalWorkspaceSnapshot:
    return HistoricalWorkspaceSnapshot(
        schema_version=HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        object_type=HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
        snapshot_id=snapshot_id,
        content_hash="",
        display_name=display_name,
        description="Reusable workspace",
        created_at_ms=1000,
        updated_at_ms=1000,
        workspace={"visualization_mode": "scroll_4"},
        charts=(_chart_payload(),),
        notebook_ref=notebook_ref,
    )


def test_study_setup_delete_cancel_leaves_dialog_state_unchanged() -> None:
    _qapp()
    setups = [
        _study_setup("setup_a", "Setup A"),
        _study_setup("setup_b", "Setup B"),
    ]
    deleted: list[str] = []
    dialog = LoadStudySetupDialog(
        setups=setups,
        chart_options=[{"label": "Chart 1", "position": 1, "study_count": 1}],
        delete_setup=lambda setup_id: deleted.append(setup_id) or True,
        setups_loader=lambda: setups,
    )
    try:
        dialog._confirm_delete_setup = lambda setup: False

        dialog._on_delete_clicked()

        assert deleted == []
        assert dialog.selected_setup_id() == "setup_a"
        assert dialog._setup_list.count() == 2
    finally:
        dialog.close()


def test_study_setup_delete_confirm_removes_selected_row_and_clears_selection() -> None:
    _qapp()
    setups = [
        _study_setup("setup_a", "Setup A"),
        _study_setup("setup_b", "Setup B"),
    ]
    remaining = [setups[1]]
    deleted: list[str] = []
    dialog = LoadStudySetupDialog(
        setups=setups,
        chart_options=[{"label": "Chart 1", "position": 1, "study_count": 1}],
        delete_setup=lambda setup_id: deleted.append(setup_id) or True,
        setups_loader=lambda: remaining,
    )
    try:
        dialog._confirm_delete_setup = lambda setup: True

        dialog._on_delete_clicked()

        load_button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert deleted == ["setup_a"]
        assert dialog._setup_list.count() == 1
        assert dialog.selected_setup_id() == ""
        assert load_button is not None
        assert not load_button.isEnabled()
        assert not dialog._delete_button.isEnabled()
    finally:
        dialog.close()


def test_workspace_snapshot_delete_confirm_keeps_notebook_reference_external() -> None:
    _qapp()
    snapshots = [
        _workspace_snapshot(
            "snapshot_a",
            "Snapshot A",
            notebook_ref={
                "notebook_id": "notebook_a",
                "display_name": "Notebook A",
            },
        ),
        _workspace_snapshot("snapshot_b", "Snapshot B"),
    ]
    remaining = [snapshots[1]]
    deleted: list[str] = []
    dialog = LoadWorkspaceSnapshotDialog(
        snapshots=snapshots,
        current_chart_count=0,
        available_slot_count=8,
        delete_snapshot=lambda snapshot_id: deleted.append(snapshot_id) or True,
        snapshots_loader=lambda: remaining,
    )
    try:
        dialog._confirm_delete_snapshot = lambda snapshot: True

        dialog._on_delete_clicked()

        load_button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert deleted == ["snapshot_a"]
        assert snapshots[0].notebook_ref == {
            "notebook_id": "notebook_a",
            "display_name": "Notebook A",
        }
        assert dialog._snapshot_list.count() == 1
        assert dialog.selected_snapshot_id() == ""
        assert load_button is not None
        assert not load_button.isEnabled()
        assert not dialog._delete_button.isEnabled()
    finally:
        dialog.close()


def test_delete_buttons_disable_when_no_saved_item_is_selected() -> None:
    _qapp()
    setup_dialog = LoadStudySetupDialog(
        setups=[_study_setup("setup_a", "Setup A")],
        chart_options=[{"label": "Chart 1", "position": 1, "study_count": 1}],
        delete_setup=lambda setup_id: True,
    )
    snapshot_dialog = LoadWorkspaceSnapshotDialog(
        snapshots=[_workspace_snapshot("snapshot_a", "Snapshot A")],
        current_chart_count=0,
        available_slot_count=8,
        delete_snapshot=lambda snapshot_id: True,
    )
    try:
        setup_dialog._setup_list.clearSelection()
        setup_dialog._setup_list.setCurrentRow(-1)
        setup_dialog._refresh_details()
        snapshot_dialog._snapshot_list.clearSelection()
        snapshot_dialog._snapshot_list.setCurrentRow(-1)
        snapshot_dialog._refresh_details()

        assert not setup_dialog._delete_button.isEnabled()
        assert not snapshot_dialog._delete_button.isEnabled()
    finally:
        setup_dialog.close()
        snapshot_dialog.close()
