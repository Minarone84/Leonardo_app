from __future__ import annotations

from pathlib import Path

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PRESET_ISSUE_BROKEN,
    PRESET_ISSUE_WARNING,
    PRESET_STATUS_BROKEN,
    PRESET_STATUS_READY,
    PRESET_STATUS_WARNING,
    PresetCompatibilityIssue,
    build_compatibility_report,
    evaluate_study_setup_compatibility,
    evaluate_workspace_snapshot_compatibility,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS = REPO_ROOT / "src" / "leonardo" / "gui" / "windows"
DATA_PRESETS = REPO_ROOT / "src" / "leonardo" / "data" / "chart_presets"
DIALOGS = WINDOWS / "_historical_data_manager"
HDM = WINDOWS / "historical_data_manager_window.py"


def _study_payload(*, tool_key: str = "ema", family: str = "indicator") -> dict:
    return {
        "schema_version": 1,
        "family": family,
        "tool_key": tool_key,
        "display_name": f"{tool_key.upper()} 20",
        "pane_target": "price",
        "params": {"period": 20},
        "source_kind": "temporary",
        "input_bindings": {"source": "close"},
        "input_binding_meta": {"source": {"column_name": "close"}},
        "required_inputs": ["source"],
        "saved_artifact_ref": None,
        "style": {
            "signal_styles": {},
            "fill_styles": {},
            "style_modules": [],
        },
    }


def _dataset(symbol: str = "BTCUSDT", timeframe: str = "30m") -> dict:
    return {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": symbol,
        "timeframe": timeframe,
    }


def _chart_payload(*, position: int = 1, studies: list[dict] | None = None) -> dict:
    return {
        "position": position,
        "dataset": _dataset(),
        "viewport": {"center_ts_ms": 1000, "visible_bars": 500},
        "price_view_state": {},
        "studies": [_study_payload()] if studies is None else studies,
    }


def _setup(tmp_path: Path, *, studies: list[dict] | None = None, created_from: dict | None = None):
    store = ChartStudySetupStore(tmp_path / "chart_presets" / "study_setups")
    return store.create_setup(
        display_name="Compatibility Setup",
        description="",
        created_from=_dataset() if created_from is None else created_from,
        studies=[_study_payload()] if studies is None else studies,
        setup_id="compat_setup",
    )


def _snapshot(tmp_path: Path, *, charts: list[dict] | None = None):
    store = HistoricalWorkspaceSnapshotStore(
        tmp_path / "chart_presets" / "workspace_snapshots"
    )
    return store.create_snapshot(
        display_name="Compatibility Snapshot",
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[_chart_payload()] if charts is None else charts,
        snapshot_id="compat_snapshot",
    )


class _Panel:
    def __init__(self, dataset: dict | None = None) -> None:
        self._dataset = _dataset() if dataset is None else dataset

    def dataset_descriptor(self) -> dict:
        return dict(self._dataset)


class _Workspace:
    def __init__(
        self,
        *,
        chart_count: int = 0,
        available_slots: int = 8,
        detached_reserved_slots: int = 0,
    ) -> None:
        self._chart_count = chart_count
        self._available_slots = available_slots
        self._detached_reserved_slots = detached_reserved_slots

    def chart_count(self) -> int:
        return self._chart_count

    def available_embedded_slot_count(self) -> int:
        return self._available_slots

    def detached_reserved_slot_count(self) -> int:
        return self._detached_reserved_slots


class _Core:
    def __init__(self, *, exists: bool = True) -> None:
        self._exists = exists

    def historical_dataset_exists(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        return self._exists


class _RawSnapshot:
    snapshot_id = "raw_snapshot"

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.charts = payload.get("charts", [])

    def to_dict(self) -> dict:
        return dict(self._payload)


class _RawSetup:
    setup_id = "raw_setup"

    def __init__(self, studies: list[dict]) -> None:
        self.created_from = _dataset()
        self.studies = studies


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_compatibility_model_ready_warning_broken_loadability() -> None:
    ready = build_compatibility_report([])
    warning = build_compatibility_report(
        [PresetCompatibilityIssue(PRESET_ISSUE_WARNING, "caveat", "Warn")]
    )
    broken = build_compatibility_report(
        [PresetCompatibilityIssue(PRESET_ISSUE_BROKEN, "blocked", "Broken")]
    )

    assert ready.status == PRESET_STATUS_READY
    assert ready.can_load is True
    assert warning.status == PRESET_STATUS_WARNING
    assert warning.can_load is True
    assert broken.status == PRESET_STATUS_BROKEN
    assert broken.can_load is False


def test_study_setup_unknown_tool_key_is_broken(tmp_path: Path) -> None:
    setup = _setup(tmp_path, studies=[_study_payload(tool_key="missing_tool")])

    report = evaluate_study_setup_compatibility(
        setup,
        target_panel=_Panel(),
        load_mode="append",
    )

    assert report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "unknown_tool_key" for issue in report.issues)


def test_study_setup_invalid_serialized_payload_is_broken() -> None:
    payload = _study_payload()
    payload["params"] = []
    setup = _RawSetup([payload])

    report = evaluate_study_setup_compatibility(
        setup,
        target_panel=_Panel(),
        load_mode="append",
    )

    assert report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "invalid_study_payload" for issue in report.issues)


def test_different_created_from_dataset_is_warning_for_portable_studies(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path, created_from=_dataset(symbol="ETHUSDT"))

    report = evaluate_study_setup_compatibility(
        setup,
        target_panel=_Panel(),
        load_mode="append",
    )

    assert report.status == PRESET_STATUS_WARNING
    assert report.can_load is True
    assert any(issue.code == "different_target_dataset" for issue in report.issues)


def test_workspace_snapshot_capacity_and_detached_rules_are_broken(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path, charts=[_chart_payload(position=1), _chart_payload(position=2)])

    capacity_report = evaluate_workspace_snapshot_compatibility(
        snapshot,
        workspace=_Workspace(chart_count=7, available_slots=8),
        core_bridge=_Core(),
        load_mode="load_into_current",
    )
    replace_report = evaluate_workspace_snapshot_compatibility(
        snapshot,
        workspace=_Workspace(detached_reserved_slots=1),
        core_bridge=_Core(),
        load_mode="replace",
    )

    assert capacity_report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "insufficient_non_reserved_slots" for issue in capacity_report.issues)
    assert replace_report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "detached_reservations_block_replace" for issue in replace_report.issues)


def test_workspace_snapshot_dataset_and_mode_preflight_blocks_broken_loads(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    missing_dataset_report = evaluate_workspace_snapshot_compatibility(
        snapshot,
        workspace=_Workspace(),
        core_bridge=_Core(exists=False),
        load_mode="replace",
    )
    invalid_mode_report = evaluate_workspace_snapshot_compatibility(
        _RawSnapshot(
            {
                "schema_version": 1,
                "object_type": "historical_workspace_snapshot",
                "snapshot_id": "bad_mode",
                "content_hash": "",
                "display_name": "Bad Mode",
                "description": "",
                "created_at_ms": 1,
                "updated_at_ms": 1,
                "workspace": {"visualization_mode": "bad_mode"},
                "charts": [_chart_payload()],
            }
        ),
        workspace=_Workspace(),
        core_bridge=_Core(),
        load_mode="replace",
    )

    assert missing_dataset_report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "missing_dataset" for issue in missing_dataset_report.issues)
    assert invalid_mode_report.status == PRESET_STATUS_BROKEN
    assert any(issue.code == "invalid_snapshot_structure" for issue in invalid_mode_report.issues)


def test_dialogs_expose_compatibility_status_and_block_broken_loads() -> None:
    study_dialog_source = _source(DIALOGS / "study_setup_dialogs.py")
    workspace_dialog_source = _source(DIALOGS / "workspace_snapshot_dialogs.py")
    manager_source = _source(HDM)

    assert "compatibility_provider" in study_dialog_source
    assert "_compatibility_text" in study_dialog_source
    assert "compatibility_report" in study_dialog_source
    assert "can_load" in study_dialog_source
    assert "compatibility_provider" in workspace_dialog_source
    assert "_compatibility_text" in workspace_dialog_source
    assert "compatibility_report" in workspace_dialog_source
    assert "can_load" in workspace_dialog_source
    assert "evaluate_study_setup_compatibility" in manager_source
    assert "evaluate_workspace_snapshot_compatibility" in manager_source
    assert "format_compatibility_report" in manager_source


def test_workspace_save_dialog_surfaces_detached_chart_exclusion_warning() -> None:
    source = _source(DIALOGS / "workspace_snapshot_dialogs.py")

    assert "Detached charts are not included in this snapshot" in source
    assert "detached_reserved_slot_count" in source


def test_preset_compatibility_does_not_use_runtime_render_keys_as_truth() -> None:
    source = _source(DIALOGS / "preset_compatibility.py")
    manager_source = _source(HDM)

    assert "render_keys" not in source
    assert "computed arrays" not in manager_source


def test_chart_preset_data_stores_remain_gui_free() -> None:
    study_store_source = _source(DATA_PRESETS / "study_setup_store.py")
    snapshot_store_source = _source(DATA_PRESETS / "workspace_snapshot_store.py")

    assert "leonardo.gui" not in study_store_source
    assert "PySide" not in study_store_source
    assert "leonardo.gui" not in snapshot_store_source
    assert "PySide" not in snapshot_store_source
