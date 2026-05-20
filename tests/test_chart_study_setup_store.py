from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.data.chart_presets.study_setup_store import (
    CHART_STUDY_SETUP_OBJECT_TYPE,
    CHART_STUDY_SETUP_SCHEMA_VERSION,
    ChartStudySetupStore,
    build_chart_study_setup_content_hash,
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


def _store(tmp_path: Path) -> tuple[ChartStudySetupStore, Path]:
    root = tmp_path / "chart_presets" / "study_setups"
    return ChartStudySetupStore(root), root


def _saved_setup(tmp_path: Path):
    store, _ = _store(tmp_path)
    setup = store.create_setup(
        display_name="Momentum Setup",
        description="Reusable chart studies",
        created_from={
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=[_study_payload()],
        setup_id="setup_test",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    return store, store.save_setup(setup)


def test_store_path_is_global_and_injected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    setup = store.create_setup(
        display_name="Global Setup",
        description="",
        created_from={},
        studies=[_study_payload()],
    )
    saved = store.save_setup(setup)

    assert store.root_dir == root
    assert store.setup_path(saved.setup_id) == root / f"{saved.setup_id}.json"
    assert store.setup_path(saved.setup_id).exists()
    assert not (root / "bybit").exists()


def test_create_save_load_round_trip_preserves_metadata_and_studies(
    tmp_path: Path,
) -> None:
    store, saved = _saved_setup(tmp_path)

    loaded = store.load_setup(saved.setup_id)

    assert loaded == saved
    assert loaded.object_type == CHART_STUDY_SETUP_OBJECT_TYPE
    assert loaded.schema_version == CHART_STUDY_SETUP_SCHEMA_VERSION
    assert loaded.display_name == "Momentum Setup"
    assert loaded.description == "Reusable chart studies"
    assert loaded.created_from["symbol"] == "BTCUSDT"
    assert loaded.studies[0]["tool_key"] == "ema"
    assert loaded.studies[0]["input_bindings"] == {"source": "close"}


def test_summary_listing_contains_dialog_ready_metadata(tmp_path: Path) -> None:
    store, saved = _saved_setup(tmp_path)

    summaries = store.list_summaries()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.setup_id == saved.setup_id
    assert summary.display_name == "Momentum Setup"
    assert summary.description == "Reusable chart studies"
    assert summary.created_from["timeframe"] == "1h"
    assert summary.study_count == 1
    assert summary.tool_keys == ("ema",)
    assert summary.path == store.setup_path(saved.setup_id)


def test_filename_uses_setup_id_not_display_name(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    setup = store.create_setup(
        display_name="Setup With Spaces & Special Characters!",
        description="",
        created_from={},
        studies=[_study_payload()],
        setup_id="stable_setup_id",
    )

    saved = store.save_setup(setup)

    assert (root / "stable_setup_id.json").exists()
    assert saved.display_name not in store.setup_path(saved.setup_id).name


def test_duplicate_display_name_is_rejected_for_different_setup_ids(
    tmp_path: Path,
) -> None:
    store, _ = _saved_setup(tmp_path)

    with pytest.raises(ValueError, match="display_name already exists"):
        store.create_setup(
            display_name="Momentum Setup",
            description="Duplicate name",
            created_from={},
            studies=[_study_payload(period=50)],
            setup_id="different_setup_id",
        )


def test_same_setup_id_can_be_overwritten_without_duplicate_name_error(
    tmp_path: Path,
) -> None:
    store, saved = _saved_setup(tmp_path)

    updated = replace(
        saved,
        description="Updated description",
        updated_at_ms=saved.updated_at_ms + 1,
    )
    overwritten = store.save_setup(updated, overwrite=True)

    assert overwritten.setup_id == saved.setup_id
    assert overwritten.display_name == saved.display_name
    assert overwritten.description == "Updated description"
    assert overwritten.content_hash != saved.content_hash


def test_wrong_object_type_is_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    root.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "object_type": "artifact_recipe",
        "setup_id": "bad_type",
        "content_hash": "",
        "display_name": "Bad Type",
        "description": "",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "created_from": {},
        "studies": [_study_payload()],
    }
    (root / "bad_type.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="object_type"):
        store.load_setup("bad_type")


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    root.mkdir(parents=True)
    payload = {
        "schema_version": 999,
        "object_type": CHART_STUDY_SETUP_OBJECT_TYPE,
        "setup_id": "bad_schema",
        "content_hash": "",
        "display_name": "Bad Schema",
        "description": "",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "created_from": {},
        "studies": [_study_payload()],
    }
    (root / "bad_schema.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        store.load_setup("bad_schema")


def test_empty_studies_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)

    with pytest.raises(ValueError, match="at least one study"):
        store.create_setup(
            display_name="Empty Setup",
            description="",
            created_from={},
            studies=[],
        )


def test_non_json_safe_studies_are_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    study = _study_payload()
    study["params"] = {"bad": object()}

    with pytest.raises(TypeError, match="JSON-serializable"):
        store.create_setup(
            display_name="Unsafe Setup",
            description="",
            created_from={},
            studies=[study],
        )


def test_delete_setup_removes_file_and_reports_result(tmp_path: Path) -> None:
    store, saved = _saved_setup(tmp_path)
    path = store.setup_path(saved.setup_id)

    assert path.exists()
    assert store.delete_setup(saved.setup_id) is True
    assert not path.exists()
    assert store.delete_setup(saved.setup_id) is False
    with pytest.raises(FileNotFoundError):
        store.load_setup(saved.setup_id)


def test_content_hash_is_deterministic_and_tracks_content_changes(
    tmp_path: Path,
) -> None:
    store, saved = _saved_setup(tmp_path)

    loaded = store.load_setup(saved.setup_id)
    assert loaded.content_hash == saved.content_hash

    payload_a = {
        "schema_version": 1,
        "object_type": CHART_STUDY_SETUP_OBJECT_TYPE,
        "setup_id": "same",
        "display_name": "Same",
        "description": "Same",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "created_from": {"b": 2, "a": 1},
        "studies": [
            {
                "tool_key": "ema",
                "family": "indicator",
                "params": {"b": 2, "a": 1},
                "style": {},
            }
        ],
    }
    payload_b = {
        "studies": [
            {
                "style": {},
                "params": {"a": 1, "b": 2},
                "family": "indicator",
                "tool_key": "ema",
            }
        ],
        "created_from": {"a": 1, "b": 2},
        "updated_at_ms": 1,
        "created_at_ms": 1,
        "description": "Same",
        "display_name": "Same",
        "setup_id": "same",
        "object_type": CHART_STUDY_SETUP_OBJECT_TYPE,
        "schema_version": 1,
    }

    assert build_chart_study_setup_content_hash(payload_a) == (
        build_chart_study_setup_content_hash(payload_b)
    )

    updated = store.save_setup(
        replace(
            saved,
            description="Changed description",
            updated_at_ms=saved.updated_at_ms + 1,
        ),
        overwrite=True,
    )

    assert updated.content_hash != saved.content_hash


def test_data_chart_preset_store_does_not_import_gui() -> None:
    source = (
        REPO_ROOT / "src/leonardo/data/chart_presets/study_setup_store.py"
    ).read_text(encoding="utf-8")

    assert "leonardo.gui" not in source
    assert "PySide" not in source
