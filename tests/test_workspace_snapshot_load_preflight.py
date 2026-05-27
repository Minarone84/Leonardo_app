from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

import leonardo.gui.windows.historical_data_manager_window as hdm_module
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
    HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
    HistoricalWorkspaceSnapshot,
)
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    ready_report,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_dialogs import (
    WorkspaceSnapshotLoadPreflightDialog,
)
from leonardo.gui.windows.historical_data_manager_window import (
    HistoricalDataManagerWindow,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _chart_payload(position: int = 1) -> dict:
    return {
        "position": position,
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


def _snapshot(*, notebook_ref: dict | None = None) -> HistoricalWorkspaceSnapshot:
    return HistoricalWorkspaceSnapshot(
        schema_version=HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        object_type=HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
        snapshot_id="snap_1",
        content_hash="",
        display_name="Momentum Desk",
        description="Two chart momentum layout",
        created_at_ms=1000,
        updated_at_ms=2000,
        workspace={"visualization_mode": "fit_8"},
        charts=(_chart_payload(1), _chart_payload(2)),
        notebook_ref=notebook_ref,
    )


class _Signal:
    def __init__(self) -> None:
        self._slots: list[object] = []

    def connect(self, slot: object) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()  # type: ignore[misc]


class _FakeLoadWorkspaceSnapshotDialog:
    def __init__(self, *, exec_result: int, load_mode: str, **_kwargs: object) -> None:
        self.exec_result = exec_result
        self._load_mode = load_mode

    def exec(self) -> int:
        return self.exec_result

    def selected_snapshot_id(self) -> str:
        return "snap_1"

    def load_mode(self) -> str:
        return self._load_mode


class _SelectionDialogFactory:
    def __init__(
        self,
        *,
        exec_result: int = int(QDialog.DialogCode.Accepted),
        load_mode: str = "replace",
    ) -> None:
        self.exec_result = exec_result
        self.load_mode = load_mode

    def __call__(self, **kwargs: object) -> _FakeLoadWorkspaceSnapshotDialog:
        return _FakeLoadWorkspaceSnapshotDialog(
            exec_result=self.exec_result,
            load_mode=self.load_mode,
            **kwargs,
        )


class _FakePreflightDialog:
    def __init__(
        self,
        *,
        snapshot: HistoricalWorkspaceSnapshot,
        load_mode: str,
        parent: object | None = None,
        auto_confirm: bool,
        exec_result: int,
    ) -> None:
        self.snapshot = snapshot
        self.load_mode = load_mode
        self.parent = parent
        self.auto_confirm = auto_confirm
        self.exec_result = exec_result
        self.load_requested = _Signal()
        self.started = False
        self.success_message = ""
        self.failure_message = ""
        self.cancelled_message = ""

    def exec(self) -> int:
        if self.auto_confirm:
            self.load_requested.emit()
        return self.exec_result

    def start_loading(self) -> None:
        self.started = True

    def mark_success(self, message: str) -> None:
        self.success_message = message

    def mark_failure(self, message: str) -> None:
        self.failure_message = message

    def mark_cancelled(self, message: str) -> None:
        self.cancelled_message = message


class _PreflightDialogFactory:
    def __init__(
        self,
        *,
        auto_confirm: bool,
        exec_result: int = int(QDialog.DialogCode.Accepted),
    ) -> None:
        self.auto_confirm = auto_confirm
        self.exec_result = exec_result
        self.dialog: _FakePreflightDialog | None = None

    def __call__(self, **kwargs: object) -> _FakePreflightDialog:
        self.dialog = _FakePreflightDialog(
            **kwargs,
            auto_confirm=self.auto_confirm,
            exec_result=self.exec_result,
        )
        return self.dialog


class _FakeAction:
    def __init__(self) -> None:
        self.enabled_states: list[bool] = []

    def setEnabled(self, enabled: bool) -> None:
        self.enabled_states.append(bool(enabled))


class _FakeWorkspace:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.load_calls: list[tuple[list[dict], str]] = []
        self.visualization_modes: list[str] = []

    def chart_count(self) -> int:
        return 1

    def available_embedded_slot_count(self) -> int:
        return 8

    def detached_reserved_slot_count(self) -> int:
        return 0

    def load_workspace_snapshot_charts(self, charts: list[dict], *, mode: str) -> None:
        if self.fail:
            raise RuntimeError("restore failed")
        self.load_calls.append((charts, mode))

    def set_visualization_mode(self, mode: str) -> None:
        self.visualization_modes.append(mode)


class _FakeStore:
    def __init__(self, snapshot: HistoricalWorkspaceSnapshot) -> None:
        self.snapshot = snapshot
        self.loaded_ids: list[str] = []

    def load_snapshot(self, snapshot_id: str) -> HistoricalWorkspaceSnapshot:
        self.loaded_ids.append(snapshot_id)
        return self.snapshot

    def delete_snapshot(self, snapshot_id: str) -> bool:
        return bool(snapshot_id)


class _FakeWindow:
    _on_load_workspace_snapshot = HistoricalDataManagerWindow._on_load_workspace_snapshot
    _set_workspace_snapshot_load_busy = (
        HistoricalDataManagerWindow._set_workspace_snapshot_load_busy
    )

    def __init__(
        self,
        *,
        snapshot: HistoricalWorkspaceSnapshot,
        workspace: _FakeWorkspace,
        dirty_allowed: bool = True,
    ) -> None:
        self._workspace_widget = workspace
        self._store = _FakeStore(snapshot)
        self._snapshots = [snapshot]
        self._core = object()
        self._action_load_workspace_snapshot = _FakeAction()
        self._workspace_snapshot_load_in_progress = False
        self._current_workspace_snapshot_id: str | None = None
        self._current_workspace_notebook_ref: dict | None = None
        self._dirty_allowed = dirty_allowed
        self.statuses: list[str] = []
        self.dirty_prompts: list[str] = []
        self.sync_count = 0
        self.opened_refs: list[tuple[dict | None, bool]] = []

    def _set_status(self, message: str) -> None:
        self.statuses.append(message)

    def _load_workspace_snapshot_objects(self) -> list[HistoricalWorkspaceSnapshot]:
        return self._snapshots

    def _workspace_snapshot_store(self) -> _FakeStore:
        return self._store

    def _notebook_store(self) -> object:
        return object()

    def _confirm_dirty_notebook_action(self, *, action_label: str) -> bool:
        self.dirty_prompts.append(action_label)
        return self._dirty_allowed

    def _sync_view_mode_controls(self) -> None:
        self.sync_count += 1

    def _set_current_workspace_notebook_ref(self, notebook_ref: dict | None) -> None:
        self._current_workspace_notebook_ref = dict(notebook_ref) if notebook_ref else None

    def _open_notebook_ref_from_snapshot(
        self,
        notebook_ref: dict | None,
        *,
        confirm_dirty: bool = True,
    ) -> str:
        self.opened_refs.append((notebook_ref, confirm_dirty))
        if notebook_ref:
            return "Assigned notebook 'Notebook A' was opened."
        return ""


def _patch_dialogs(
    monkeypatch,
    *,
    preflight_auto_confirm: bool,
    preflight_exec_result: int = int(QDialog.DialogCode.Accepted),
) -> _PreflightDialogFactory:
    monkeypatch.setattr(
        hdm_module,
        "LoadWorkspaceSnapshotDialog",
        _SelectionDialogFactory(),
    )
    factory = _PreflightDialogFactory(
        auto_confirm=preflight_auto_confirm,
        exec_result=preflight_exec_result,
    )
    monkeypatch.setattr(hdm_module, "WorkspaceSnapshotLoadPreflightDialog", factory)
    monkeypatch.setattr(
        hdm_module,
        "evaluate_workspace_snapshot_compatibility",
        lambda *_args, **_kwargs: ready_report(),
    )
    return factory


def test_preflight_dialog_shows_snapshot_summary_and_honest_loading_state() -> None:
    _qapp()
    snapshot = _snapshot(
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook A"}
    )
    dialog = WorkspaceSnapshotLoadPreflightDialog(
        snapshot=snapshot,
        load_mode="replace",
    )
    try:
        assert dialog.windowTitle() == "Load Workspace Snapshot"
        assert dialog._name_label.text() == "Snapshot: Momentum Desk"
        assert dialog._description_label.text() == "Description: Two chart momentum layout"
        assert dialog._chart_count_label.text() == "Chart count: 2"
        assert dialog._notebook_label.text() == "Notebook assignment: Notebook A (nb_1)"
        assert (
            dialog._warning_label.text()
            == "Loading this Workspace Snapshot will replace the current workspace layout."
        )
        assert "Position 1: bybit / linear / BTCUSDT / 1h" in dialog._chart_summary.toPlainText()
        assert dialog._load_button.isEnabled()
        assert dialog._cancel_button.isEnabled()
        assert not dialog._ok_button.isEnabled()

        dialog.start_loading()
        assert not dialog._load_button.isEnabled()
        assert not dialog._cancel_button.isEnabled()
        assert dialog._progress.minimum() == 0
        assert dialog._progress.maximum() == 0

        dialog.mark_success("loaded")
        assert dialog._ok_button.isEnabled()
        assert dialog._progress.value() == 1

        dialog.mark_failure("failed")
        assert dialog._ok_button.isEnabled()
        assert dialog._status_label.text() == "failed"
    finally:
        dialog.close()


def test_preflight_dialog_shows_no_notebook_assignment() -> None:
    _qapp()
    dialog = WorkspaceSnapshotLoadPreflightDialog(
        snapshot=_snapshot(),
        load_mode="load_into_current",
    )
    try:
        assert dialog._notebook_label.text() == "Notebook assignment: No notebook assigned"
        assert (
            dialog._warning_label.text()
            == "Loading this Workspace Snapshot will add charts to the current workspace layout."
        )
    finally:
        dialog.close()


def test_preflight_cancel_prevents_workspace_restore(monkeypatch) -> None:
    _qapp()
    snapshot = _snapshot()
    workspace = _FakeWorkspace()
    window = _FakeWindow(snapshot=snapshot, workspace=workspace)
    _patch_dialogs(
        monkeypatch,
        preflight_auto_confirm=False,
        preflight_exec_result=int(QDialog.DialogCode.Rejected),
    )

    window._on_load_workspace_snapshot()

    assert workspace.load_calls == []
    assert window.statuses[-1] == "Workspace snapshot load cancelled"


def test_confirm_restores_snapshot_and_updates_notebook_indicator(monkeypatch) -> None:
    _qapp()
    notebook_ref = {"notebook_id": "nb_1", "display_name": "Notebook A"}
    snapshot = _snapshot(notebook_ref=notebook_ref)
    workspace = _FakeWorkspace()
    window = _FakeWindow(snapshot=snapshot, workspace=workspace)
    factory = _patch_dialogs(monkeypatch, preflight_auto_confirm=True)

    window._on_load_workspace_snapshot()

    assert workspace.load_calls == [([dict(chart) for chart in snapshot.charts], "replace")]
    assert workspace.visualization_modes == ["fit_8"]
    assert window._current_workspace_snapshot_id == "snap_1"
    assert window._current_workspace_notebook_ref == notebook_ref
    assert window.dirty_prompts == ["loading the assigned notebook"]
    assert window.opened_refs == [(notebook_ref, False)]
    assert window.sync_count == 1
    assert window._action_load_workspace_snapshot.enabled_states == [False, True]
    assert factory.dialog is not None
    assert factory.dialog.started
    assert "Workspace Snapshot 'Momentum Desk' loaded." in factory.dialog.success_message


def test_dirty_notebook_cancel_aborts_after_preflight_before_restore(monkeypatch) -> None:
    _qapp()
    snapshot = _snapshot(
        notebook_ref={"notebook_id": "nb_1", "display_name": "Notebook A"}
    )
    workspace = _FakeWorkspace()
    window = _FakeWindow(
        snapshot=snapshot,
        workspace=workspace,
        dirty_allowed=False,
    )
    factory = _patch_dialogs(monkeypatch, preflight_auto_confirm=True)

    window._on_load_workspace_snapshot()

    assert workspace.load_calls == []
    assert window._current_workspace_snapshot_id is None
    assert window.dirty_prompts == ["loading the assigned notebook"]
    assert factory.dialog is not None
    assert not factory.dialog.started
    assert factory.dialog.cancelled_message == (
        "Workspace Snapshot load cancelled before restore."
    )


def test_restore_failure_is_reported_in_preflight_dialog(monkeypatch) -> None:
    _qapp()
    snapshot = _snapshot()
    workspace = _FakeWorkspace(fail=True)
    window = _FakeWindow(snapshot=snapshot, workspace=workspace)
    factory = _patch_dialogs(monkeypatch, preflight_auto_confirm=True)

    window._on_load_workspace_snapshot()

    assert window._current_workspace_snapshot_id is None
    assert window._action_load_workspace_snapshot.enabled_states == [False, True]
    assert factory.dialog is not None
    assert "restore failed" in factory.dialog.failure_message
