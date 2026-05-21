from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.data.chart_presets.workspace_snapshot_store import (
    HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
    HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
    HistoricalWorkspaceSnapshotStore,
    build_historical_workspace_snapshot_content_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


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
        "style": {
            "signal_styles": {
                f"{tool_key}_{period}": {
                    "color": "#22C55E",
                    "line_width": 2,
                }
            },
            "fill_styles": {},
            "style_modules": [],
        },
    }


def _workspace_payload(*, mode: str = "scroll_4") -> dict:
    return {"visualization_mode": mode}


def _chart_payload(
    *,
    position: int = 1,
    studies: list[dict] | None = None,
) -> dict:
    return {
        "position": position,
        "dataset": {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "30m",
        },
        "viewport": {
            "center_ts_ms": 1700000000000,
            "visible_bars": 500,
            "fallback_global_index": None,
        },
        "price_view_state": {},
        "studies": [_study_payload()] if studies is None else studies,
    }


def _store(tmp_path: Path) -> tuple[HistoricalWorkspaceSnapshotStore, Path]:
    root = tmp_path / "chart_presets" / "workspace_snapshots"
    return HistoricalWorkspaceSnapshotStore(root), root


def _saved_snapshot(tmp_path: Path):
    store, _ = _store(tmp_path)
    snapshot = store.create_snapshot(
        display_name="Morning Workspace",
        description="Reusable historical workspace",
        workspace=_workspace_payload(),
        charts=[_chart_payload()],
        snapshot_id="snapshot_test",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    return store, store.save_snapshot(snapshot)


def test_store_path_is_global_and_injected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    snapshot = store.create_snapshot(
        display_name="Global Snapshot",
        description="",
        workspace=_workspace_payload(),
        charts=[_chart_payload()],
    )
    saved = store.save_snapshot(snapshot)

    assert store.root_dir == root
    assert store.snapshot_path(saved.snapshot_id) == root / f"{saved.snapshot_id}.json"
    assert store.snapshot_path(saved.snapshot_id).exists()
    assert not (root / "bybit").exists()


def test_create_save_load_round_trip_preserves_workspace_charts_and_studies(
    tmp_path: Path,
) -> None:
    store, saved = _saved_snapshot(tmp_path)

    loaded = store.load_snapshot(saved.snapshot_id)

    assert loaded == saved
    assert loaded.object_type == HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE
    assert loaded.schema_version == HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION
    assert loaded.display_name == "Morning Workspace"
    assert loaded.description == "Reusable historical workspace"
    assert loaded.workspace["visualization_mode"] == "scroll_4"
    assert loaded.charts[0]["position"] == 1
    assert loaded.charts[0]["dataset"]["symbol"] == "BTCUSDT"
    assert loaded.charts[0]["studies"][0]["tool_key"] == "ema"


def test_summary_listing_contains_dialog_ready_metadata(tmp_path: Path) -> None:
    store, saved = _saved_snapshot(tmp_path)

    summaries = store.list_summaries()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.snapshot_id == saved.snapshot_id
    assert summary.display_name == "Morning Workspace"
    assert summary.description == "Reusable historical workspace"
    assert summary.workspace["visualization_mode"] == "scroll_4"
    assert summary.chart_count == 1
    assert summary.study_count == 1
    assert summary.chart_summaries[0]["position"] == 1
    assert summary.chart_summaries[0]["symbol"] == "BTCUSDT"
    assert summary.chart_summaries[0]["study_count"] == 1
    assert summary.path == store.snapshot_path(saved.snapshot_id)


def test_filename_uses_snapshot_id_not_display_name(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    snapshot = store.create_snapshot(
        display_name="Snapshot With Spaces & Special Characters!",
        description="",
        workspace=_workspace_payload(),
        charts=[_chart_payload()],
        snapshot_id="stable_snapshot_id",
    )

    saved = store.save_snapshot(snapshot)

    assert (root / "stable_snapshot_id.json").exists()
    assert saved.display_name not in store.snapshot_path(saved.snapshot_id).name


def test_duplicate_display_name_is_rejected_for_different_snapshot_ids(
    tmp_path: Path,
) -> None:
    store, _ = _saved_snapshot(tmp_path)

    with pytest.raises(ValueError, match="display_name already exists"):
        store.create_snapshot(
            display_name="Morning Workspace",
            description="Duplicate name",
            workspace=_workspace_payload(),
            charts=[_chart_payload(position=2)],
            snapshot_id="different_snapshot_id",
        )


def test_same_snapshot_id_can_be_overwritten_without_duplicate_name_error(
    tmp_path: Path,
) -> None:
    store, saved = _saved_snapshot(tmp_path)

    updated = replace(
        saved,
        description="Updated description",
        updated_at_ms=saved.updated_at_ms + 1,
    )
    overwritten = store.save_snapshot(updated, overwrite=True)

    assert overwritten.snapshot_id == saved.snapshot_id
    assert overwritten.display_name == saved.display_name
    assert overwritten.description == "Updated description"
    assert overwritten.content_hash != saved.content_hash


def test_wrong_object_type_is_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    root.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "object_type": "chart_study_setup",
        "snapshot_id": "bad_type",
        "content_hash": "",
        "display_name": "Bad Type",
        "description": "",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "workspace": _workspace_payload(),
        "charts": [_chart_payload()],
    }
    (root / "bad_type.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="object_type"):
        store.load_snapshot("bad_type")


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    root.mkdir(parents=True)
    payload = {
        "schema_version": 999,
        "object_type": HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
        "snapshot_id": "bad_schema",
        "content_hash": "",
        "display_name": "Bad Schema",
        "description": "",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "workspace": _workspace_payload(),
        "charts": [_chart_payload()],
    }
    (root / "bad_schema.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        store.load_snapshot("bad_schema")


def test_empty_charts_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    with pytest.raises(ValueError, match="at least one chart"):
        store.create_snapshot(
            display_name="Empty Snapshot",
            description="",
            workspace=_workspace_payload(),
            charts=[],
        )


def test_more_than_eight_charts_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    with pytest.raises(ValueError, match="at most 8 charts"):
        store.create_snapshot(
            display_name="Too Many Charts",
            description="",
            workspace=_workspace_payload(),
            charts=[_chart_payload(position=idx) for idx in range(1, 10)],
        )


def test_duplicate_chart_positions_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    with pytest.raises(ValueError, match="Duplicate chart position"):
        store.create_snapshot(
            display_name="Duplicate Positions",
            description="",
            workspace=_workspace_payload(),
            charts=[_chart_payload(position=1), _chart_payload(position=1)],
        )


@pytest.mark.parametrize("position", [0, 9, "1"])
def test_invalid_chart_positions_are_rejected(
    tmp_path: Path,
    position: object,
) -> None:
    store, _ = _store(tmp_path)
    chart = _chart_payload()
    chart["position"] = position

    with pytest.raises(ValueError, match="position"):
        store.create_snapshot(
            display_name="Bad Position",
            description="",
            workspace=_workspace_payload(),
            charts=[chart],
        )


def test_missing_dataset_identity_keys_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    chart = _chart_payload()
    chart["dataset"].pop("symbol")

    with pytest.raises(ValueError, match="dataset.symbol"):
        store.create_snapshot(
            display_name="Missing Dataset",
            description="",
            workspace=_workspace_payload(),
            charts=[chart],
        )


def test_invalid_workspace_visualization_mode_is_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    with pytest.raises(ValueError, match="visualization_mode"):
        store.create_snapshot(
            display_name="Bad Mode",
            description="",
            workspace=_workspace_payload(mode="grid_99"),
            charts=[_chart_payload()],
        )


def test_chart_with_zero_studies_is_accepted(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    snapshot = store.create_snapshot(
        display_name="No Study Chart",
        description="",
        workspace=_workspace_payload(mode="fit_8"),
        charts=[_chart_payload(studies=[])],
    )

    saved = store.save_snapshot(snapshot)
    loaded = store.load_snapshot(saved.snapshot_id)

    assert loaded.charts[0]["studies"] == []


def test_non_json_safe_payload_is_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    chart = _chart_payload()
    chart["viewport"] = {"bad": object()}

    with pytest.raises(TypeError, match="JSON-serializable"):
        store.create_snapshot(
            display_name="Unsafe Snapshot",
            description="",
            workspace=_workspace_payload(),
            charts=[chart],
        )


def test_delete_snapshot_removes_file_and_reports_result(tmp_path: Path) -> None:
    store, saved = _saved_snapshot(tmp_path)
    path = store.snapshot_path(saved.snapshot_id)

    assert path.exists()
    assert store.delete_snapshot(saved.snapshot_id) is True
    assert not path.exists()
    assert store.delete_snapshot(saved.snapshot_id) is False
    with pytest.raises(FileNotFoundError):
        store.load_snapshot(saved.snapshot_id)


def test_content_hash_is_deterministic_and_tracks_content_changes(
    tmp_path: Path,
) -> None:
    store, saved = _saved_snapshot(tmp_path)

    loaded = store.load_snapshot(saved.snapshot_id)
    assert loaded.content_hash == saved.content_hash

    payload_a = {
        "schema_version": 1,
        "object_type": HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
        "snapshot_id": "same",
        "display_name": "Same",
        "description": "Same",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "workspace": {"visualization_mode": "scroll_4", "b": 2, "a": 1},
        "charts": [
            {
                "position": 1,
                "dataset": {
                    "exchange": "bybit",
                    "market_type": "linear",
                    "symbol": "BTCUSDT",
                    "timeframe": "30m",
                },
                "viewport": {"visible_bars": 500, "center_ts_ms": 1},
                "price_view_state": {},
                "studies": [_study_payload()],
            }
        ],
    }
    payload_b = {
        "charts": [
            {
                "studies": [_study_payload()],
                "price_view_state": {},
                "viewport": {"center_ts_ms": 1, "visible_bars": 500},
                "dataset": {
                    "timeframe": "30m",
                    "symbol": "BTCUSDT",
                    "market_type": "linear",
                    "exchange": "bybit",
                },
                "position": 1,
            }
        ],
        "workspace": {"a": 1, "b": 2, "visualization_mode": "scroll_4"},
        "updated_at_ms": 1,
        "created_at_ms": 1,
        "description": "Same",
        "display_name": "Same",
        "snapshot_id": "same",
        "object_type": HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
        "schema_version": 1,
    }

    assert build_historical_workspace_snapshot_content_hash(payload_a) == (
        build_historical_workspace_snapshot_content_hash(payload_b)
    )

    updated = store.save_snapshot(
        replace(
            saved,
            description="Changed description",
            updated_at_ms=saved.updated_at_ms + 1,
        ),
        overwrite=True,
    )

    assert updated.content_hash != saved.content_hash


def test_workspace_snapshot_store_does_not_import_gui() -> None:
    source = (
        REPO_ROOT / "src/leonardo/data/chart_presets/workspace_snapshot_store.py"
    ).read_text(encoding="utf-8")

    assert "leonardo.gui" not in source
    assert "PySide" not in source
