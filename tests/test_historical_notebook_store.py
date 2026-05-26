from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.data.chart_presets.notebook_store import (
    DEFAULT_POI_MARKER_OFFSET,
    DEFAULT_PT_LONG_MARKER_OFFSET,
    DEFAULT_PT_SHORT_MARKER_OFFSET,
    HISTORICAL_NOTEBOOK_OBJECT_TYPE,
    HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
    HistoricalNotebookStore,
    build_historical_notebook_content_hash,
    notebook_chart_key,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _dataset(symbol: str = "BTCUSDT") -> dict:
    return {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": symbol,
        "timeframe": "30m",
    }


def _chart_entry(*, symbol: str = "BTCUSDT") -> dict:
    dataset = _dataset(symbol)
    return {
        "chart_key": notebook_chart_key(dataset),
        "dataset": dataset,
        "last_seen_position": 3,
        "notes": [
            {
                "row_id": "note_1",
                "date_text": "2026-05-21 14:30",
                "ts_ms": 1779373800000,
                "note": "Retest note",
            }
        ],
        "trades": [
            {
                "row_id": "trade_1",
                "date_text": "2026-05-21 14:30",
                "ts_ms": 1779373800000,
                "direction": "Long",
                "starting_price": 100000.0,
                "target_pct_movement": 2.5,
                "closing_price": 102500.0,
                "equity": 1000.0,
                "leverage": 3.0,
                "asset_bought": 0.03,
                "outcome": "Good",
                "note": "Clean continuation",
            }
        ],
        "points_of_interest": [
            {
                "row_id": "poi_1",
                "date_text": "2026-05-21 14:30",
                "ts_ms": 1779373800000,
                "title": "Breakout retest",
                "description": "Price retested previous resistance.",
            }
        ],
    }


def _store(tmp_path: Path) -> tuple[HistoricalNotebookStore, Path]:
    root = tmp_path / "chart_presets" / "notebooks"
    return HistoricalNotebookStore(root), root


def _saved_notebook(tmp_path: Path):
    store, _ = _store(tmp_path)
    notebook = store.create_notebook(
        display_name="London Notes",
        description="Workspace analysis",
        chart_entries=[_chart_entry()],
        notebook_id="notebook_test",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    return store, store.save_notebook(notebook)


def test_save_load_roundtrip_preserves_notebook_rows(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)

    loaded = store.load_notebook(saved.notebook_id)

    assert loaded == saved
    assert loaded.object_type == HISTORICAL_NOTEBOOK_OBJECT_TYPE
    assert loaded.schema_version == HISTORICAL_NOTEBOOK_SCHEMA_VERSION
    assert loaded.display_name == "London Notes"
    assert loaded.description == "Workspace analysis"
    assert loaded.chart_entries[0]["chart_key"] == "bybit|linear|btcusdt|30m"
    assert loaded.chart_entries[0]["notes"][0]["note"] == "Retest note"
    assert loaded.chart_entries[0]["trades"][0]["direction"] == "Long"
    assert loaded.chart_entries[0]["points_of_interest"][0]["title"] == "Breakout retest"
    assert loaded.annotation_settings == {
        "poi_marker_offset": DEFAULT_POI_MARKER_OFFSET,
        "pt_long_marker_offset": DEFAULT_PT_LONG_MARKER_OFFSET,
        "pt_short_marker_offset": DEFAULT_PT_SHORT_MARKER_OFFSET,
    }


def test_save_load_roundtrip_preserves_parallel_rich_text_fields(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    entry = _chart_entry()
    entry["notes"][0]["note_html"] = "<p><b>Retest note</b></p>"
    entry["trades"][0]["note_html"] = "<p><u>Clean continuation</u></p>"
    entry["points_of_interest"][0]["title_html"] = "<p><b>Breakout retest</b></p>"
    entry["points_of_interest"][0]["description_html"] = (
        "<p><span style=\"color:#ff0000;\">Price retested previous resistance.</span></p>"
    )

    saved = store.save_notebook(
        store.create_notebook(
            display_name="Rich Notes",
            description="Workspace analysis",
            description_html="<p><b>Workspace analysis</b></p>",
            chart_entries=[entry],
            notebook_id="rich_notebook",
            created_at_ms=1000,
            updated_at_ms=1000,
        )
    )
    loaded = store.load_notebook(saved.notebook_id)

    assert loaded.description == "Workspace analysis"
    assert loaded.description_html == "<p><b>Workspace analysis</b></p>"
    assert loaded.chart_entries[0]["notes"][0]["note"] == "Retest note"
    assert loaded.chart_entries[0]["notes"][0]["note_html"] == "<p><b>Retest note</b></p>"
    assert loaded.chart_entries[0]["trades"][0]["note_html"] == "<p><u>Clean continuation</u></p>"
    assert loaded.chart_entries[0]["points_of_interest"][0]["title_html"] == (
        "<p><b>Breakout retest</b></p>"
    )
    assert loaded.chart_entries[0]["points_of_interest"][0]["description_html"].startswith(
        "<p><span"
    )


def test_annotation_settings_roundtrip_and_missing_defaults(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    notebook = store.create_notebook(
        display_name="Offset Notes",
        description="",
        chart_entries=[_chart_entry()],
        annotation_settings={
            "poi_marker_offset": 36,
            "pt_long_marker_offset": 72,
            "pt_short_marker_offset": 24,
        },
        notebook_id="offset_notebook",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    saved = store.save_notebook(notebook)

    loaded = store.load_notebook(saved.notebook_id)

    assert loaded.annotation_settings == {
        "poi_marker_offset": 36,
        "pt_long_marker_offset": 72,
        "pt_short_marker_offset": 24,
    }
    assert loaded.to_dict()["annotation_settings"] == loaded.annotation_settings

    payload = loaded.to_dict()
    payload.pop("annotation_settings")
    payload["notebook_id"] = "legacy_without_offsets"
    payload["display_name"] = "Legacy Without Offsets"
    (root / "legacy_without_offsets.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    legacy = store.load_notebook("legacy_without_offsets")

    assert legacy.annotation_settings == {
        "poi_marker_offset": DEFAULT_POI_MARKER_OFFSET,
        "pt_long_marker_offset": DEFAULT_PT_LONG_MARKER_OFFSET,
        "pt_short_marker_offset": DEFAULT_PT_SHORT_MARKER_OFFSET,
    }

    payload = loaded.to_dict()
    payload["annotation_settings"] = {
        "poi_marker_offset": 40,
        "pt_marker_offset": 77,
    }
    payload["notebook_id"] = "legacy_shared_pt_offset"
    payload["display_name"] = "Legacy Shared PT Offset"
    (root / "legacy_shared_pt_offset.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    legacy_shared = store.load_notebook("legacy_shared_pt_offset")

    assert legacy_shared.annotation_settings == {
        "poi_marker_offset": 40,
        "pt_long_marker_offset": 77,
        "pt_short_marker_offset": 77,
    }


def test_summary_listing_contains_counts(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)

    summaries = store.list_summaries()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.notebook_id == saved.notebook_id
    assert summary.display_name == "London Notes"
    assert summary.description == "Workspace analysis"
    assert summary.chart_count == 1
    assert summary.note_count == 1
    assert summary.trade_count == 1
    assert summary.poi_count == 1
    assert summary.chart_summaries[0]["symbol"] == "BTCUSDT"


def test_filename_uses_notebook_id_not_display_name(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    notebook = store.create_notebook(
        display_name="Notebook With Spaces & Symbols!",
        description="",
        chart_entries=[],
        notebook_id="stable_notebook_id",
    )

    saved = store.save_notebook(notebook)

    assert (root / "stable_notebook_id.json").exists()
    assert saved.display_name not in store.notebook_path(saved.notebook_id).name


def test_duplicate_display_name_is_rejected(tmp_path: Path) -> None:
    store, _ = _saved_notebook(tmp_path)

    with pytest.raises(ValueError, match="display_name already exists"):
        store.create_notebook(
            display_name="London Notes",
            description="Duplicate",
            chart_entries=[],
            notebook_id="different_notebook_id",
        )


def test_same_notebook_id_can_be_overwritten(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)

    updated = replace(
        saved,
        description="Updated",
        updated_at_ms=saved.updated_at_ms + 1,
    )
    overwritten = store.save_notebook(updated, overwrite=True)

    assert overwritten.notebook_id == saved.notebook_id
    assert overwritten.description == "Updated"
    assert overwritten.content_hash != saved.content_hash


def test_update_notebook_reuses_identity_and_replaces_content(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)
    updated_entry = _chart_entry(symbol="ETHUSDT")

    updated = store.update_notebook(
        notebook_id=saved.notebook_id,
        display_name=saved.display_name,
        description="Updated workspace analysis",
        chart_entries=[updated_entry],
        annotation_settings={
            "poi_marker_offset": 42,
            "pt_long_marker_offset": 84,
            "pt_short_marker_offset": 21,
        },
    )

    assert updated.notebook_id == saved.notebook_id
    assert updated.created_at_ms == saved.created_at_ms
    assert updated.updated_at_ms > saved.updated_at_ms
    assert updated.content_hash != saved.content_hash
    assert updated.description == "Updated workspace analysis"
    assert updated.chart_entries[0]["chart_key"] == "bybit|linear|ethusdt|30m"
    assert updated.annotation_settings == {
        "poi_marker_offset": 42,
        "pt_long_marker_offset": 84,
        "pt_short_marker_offset": 21,
    }
    assert len(list(store.root_dir.glob("*.json"))) == 1
    assert store.load_notebook(saved.notebook_id) == updated


def test_save_as_new_from_existing_notebook_content_creates_new_identity(
    tmp_path: Path,
) -> None:
    store, saved = _saved_notebook(tmp_path)

    copied = store.save_notebook(
        store.create_notebook(
            display_name="London Notes Copy",
            description=saved.description,
            chart_entries=saved.chart_entries,
            annotation_settings=saved.annotation_settings,
        )
    )

    assert copied.notebook_id != saved.notebook_id
    assert copied.created_at_ms >= saved.created_at_ms
    assert len(list(store.root_dir.glob("*.json"))) == 2
    assert store.load_notebook(saved.notebook_id).display_name == "London Notes"


def test_wrong_object_type_and_schema_are_rejected(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    root.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "object_type": "historical_workspace_snapshot",
        "notebook_id": "bad_type",
        "content_hash": "",
        "display_name": "Bad Type",
        "description": "",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "chart_entries": [],
    }
    (root / "bad_type.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="object_type"):
        store.load_notebook("bad_type")

    payload["object_type"] = HISTORICAL_NOTEBOOK_OBJECT_TYPE
    payload["schema_version"] = 999
    payload["notebook_id"] = "bad_schema"
    (root / "bad_schema.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        store.load_notebook("bad_schema")


def test_missing_dataset_identity_is_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    entry = _chart_entry()
    entry["dataset"].pop("symbol")

    with pytest.raises(ValueError, match="dataset.symbol"):
        store.create_notebook(
            display_name="Bad Dataset",
            description="",
            chart_entries=[entry],
        )


@pytest.mark.parametrize("direction", ["Buy", "long", "Flat"])
def test_invalid_trade_direction_is_rejected(tmp_path: Path, direction: str) -> None:
    store, _ = _store(tmp_path)
    entry = _chart_entry()
    entry["trades"][0]["direction"] = direction

    with pytest.raises(ValueError, match="direction"):
        store.create_notebook(
            display_name="Bad Direction",
            description="",
            chart_entries=[entry],
        )


@pytest.mark.parametrize("outcome", ["Win", "good", "Neutral"])
def test_invalid_trade_outcome_is_rejected(tmp_path: Path, outcome: str) -> None:
    store, _ = _store(tmp_path)
    entry = _chart_entry()
    entry["trades"][0]["outcome"] = outcome

    with pytest.raises(ValueError, match="outcome"):
        store.create_notebook(
            display_name="Bad Outcome",
            description="",
            chart_entries=[entry],
        )


def test_non_json_safe_payload_is_rejected(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    entry = _chart_entry()
    entry["notes"][0]["bad"] = object()

    with pytest.raises(TypeError, match="JSON-serializable"):
        store.create_notebook(
            display_name="Unsafe Notebook",
            description="",
            chart_entries=[entry],
        )


def test_delete_notebook_removes_file(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)

    assert store.delete_notebook(saved.notebook_id) is True
    assert store.delete_notebook(saved.notebook_id) is False
    with pytest.raises(FileNotFoundError):
        store.load_notebook(saved.notebook_id)


def test_content_hash_is_deterministic(tmp_path: Path) -> None:
    store, saved = _saved_notebook(tmp_path)

    loaded = store.load_notebook(saved.notebook_id)
    assert loaded.content_hash == saved.content_hash

    payload_a = saved.to_dict()
    payload_b = {
        "chart_entries": payload_a["chart_entries"],
        "updated_at_ms": payload_a["updated_at_ms"],
        "created_at_ms": payload_a["created_at_ms"],
        "description": payload_a["description"],
        "display_name": payload_a["display_name"],
        "notebook_id": payload_a["notebook_id"],
        "object_type": payload_a["object_type"],
        "schema_version": payload_a["schema_version"],
        "annotation_settings": payload_a["annotation_settings"],
    }

    assert build_historical_notebook_content_hash(payload_a) == (
        build_historical_notebook_content_hash(payload_b)
    )


def test_content_hash_includes_rich_text_fields(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    plain = store.save_notebook(
        store.create_notebook(
            display_name="Hash Notes",
            description="Workspace analysis",
            chart_entries=[_chart_entry()],
            notebook_id="hash_plain",
            created_at_ms=1000,
            updated_at_ms=1000,
        )
    )
    payload_plain = plain.to_dict()
    payload_rich = dict(payload_plain)
    payload_rich["description_html"] = "<p><b>Workspace analysis</b></p>"

    assert build_historical_notebook_content_hash(payload_plain) != (
        build_historical_notebook_content_hash(payload_rich)
    )


def test_notebook_store_has_no_gui_imports() -> None:
    source = (
        REPO_ROOT / "src/leonardo/data/chart_presets/notebook_store.py"
    ).read_text(encoding="utf-8")

    assert "leonardo.gui" not in source
    assert "PySide" not in source
