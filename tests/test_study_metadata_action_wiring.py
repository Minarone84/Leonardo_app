from __future__ import annotations

from pathlib import Path

from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRegistry,
    ChartStudyRuntimeState,
    PANE_TARGET_PRICE,
    STUDY_FAMILY_INDICATOR,
    StudyComputationConfig,
    StudyDisplayStyle,
    StudyUserMetadata,
)
from leonardo.gui.chart.study_serialization import serialize_chart_study


def _sample_study() -> ChartStudyInstance:
    return ChartStudyInstance(
        instance_id="study_1",
        dataset_id="bybit_linear_BTCUSDT_1h",
        pane_target=PANE_TARGET_PRICE,
        display_name="SMA 20",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_INDICATOR,
            tool_key="sma",
            params={"period": 20},
            source_kind="temporary",
            input_bindings={"source": "close"},
            input_binding_meta={"source": {"column_name": "close"}},
            required_inputs=("source",),
        ),
        style=StudyDisplayStyle(color="#22C55E", line_width=2),
        runtime=ChartStudyRuntimeState(
            last_value=12.5,
            selected=True,
            status="ok",
            render_keys=["sma|study_1|sma_20"],
        ),
    )


def _updated_registry_study() -> ChartStudyInstance:
    registry = ChartStudyRegistry()
    original = registry.add(_sample_study())
    updated_metadata = StudyUserMetadata(
        important=True,
        dataset_role="supporting_indicator",
        description="Used by saved setup export review.",
    )

    updated = registry.update_user_metadata(original.instance_id, updated_metadata)

    assert updated.computation == original.computation
    assert updated.style == original.style
    assert updated.runtime == original.runtime
    assert updated.user_metadata == updated_metadata
    return updated


def test_registry_metadata_update_preserves_computation_style_and_runtime() -> None:
    _updated_registry_study()


def test_study_setup_payload_after_metadata_update_contains_user_metadata(
    tmp_path: Path,
) -> None:
    updated = _updated_registry_study()
    payload = serialize_chart_study(updated)
    store = ChartStudySetupStore(tmp_path / "study_setups")

    setup = store.create_setup(
        display_name="Metadata Setup",
        description="",
        created_from={
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=[payload],
        setup_id="setup_metadata_action",
    )
    saved = store.save_setup(setup)
    loaded = store.load_setup(saved.setup_id)

    assert loaded.studies[0]["user_metadata"] == {
        "important": True,
        "description": "Used by saved setup export review.",
        "dataset_role": "supporting_indicator",
    }


def test_workspace_snapshot_payload_after_metadata_update_contains_user_metadata(
    tmp_path: Path,
) -> None:
    updated = _updated_registry_study()
    payload = serialize_chart_study(updated)
    store = HistoricalWorkspaceSnapshotStore(tmp_path / "workspace_snapshots")

    snapshot = store.create_snapshot(
        display_name="Metadata Workspace",
        description="",
        workspace={"visualization_mode": "scroll_4"},
        charts=[
            {
                "position": 1,
                "dataset": {
                    "exchange": "bybit",
                    "market_type": "linear",
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                },
                "viewport": {},
                "price_view_state": {},
                "studies": [payload],
            }
        ],
        snapshot_id="snapshot_metadata_action",
    )
    saved = store.save_snapshot(snapshot)
    loaded = store.load_snapshot(saved.snapshot_id)

    assert loaded.charts[0]["studies"][0]["user_metadata"] == {
        "important": True,
        "description": "Used by saved setup export review.",
        "dataset_role": "supporting_indicator",
    }
