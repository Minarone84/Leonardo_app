from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
    ArtifactRecipeDependencyEdge,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.naming import canonicalize


def _payload(*, period: int = 14, symbol: str = "BTC/USDT") -> dict:
    return {
        "tool_type": "oscillator",
        "tool_key": "rsi",
        "tool_title": "RSI",
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": symbol,
        "timeframe": "30m",
        "params": {"period": period},
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": ["close"],
        "output_names": [f"rsi_{period}"],
        "output_signals": [
            {
                "name": f"rsi_{period}",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
                "label": f"RSI {period}",
                "description": "",
            }
        ],
    }


def _recipes(tmp_path: Path):
    recipe_store = ArtifactRecipeStore(historical_root=tmp_path)
    first = recipe_store.save_recipe(_payload(period=14))
    second = recipe_store.save_recipe(_payload(period=21))
    return first, second


def test_collection_store_saves_loads_and_lists_collection(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    collection = store.build_collection(
        market=first.market,
        display_name="BTCUSDT_30m_rsi_pack",
        description="RSI feature pack",
        recipes=(first, second),
        source_database_id="adb__source",
        metadata={"purpose": "test"},
    )
    saved = store.save_collection(collection)

    assert saved.collection_id.startswith("arc__h")
    assert saved.collection_hash_short.startswith("h")
    assert saved.display_name == "BTCUSDT_30m_rsi_pack"
    assert saved.source_database_id == "adb__source"

    path = store.collection_path(
        market=saved.market,
        collection_id=saved.collection_id,
    )
    assert path.exists()
    assert path.parent == (
        tmp_path
        / "bybit"
        / "linear"
        / "BTCUSDT"
        / "30m"
        / "artifact_recipe_collections"
    )

    loaded = store.load_collection(
        market=saved.market,
        collection_id=saved.collection_id,
    )
    assert loaded == saved
    assert [recipe.recipe_id for recipe in loaded.recipe_snapshots] == [
        first.recipe_id,
        second.recipe_id,
    ]

    summaries = store.list_collections(market=first.market)
    assert len(summaries) == 1
    assert summaries[0].collection_id == saved.collection_id
    assert summaries[0].recipe_count == 2
    assert summaries[0].source_database_id == "adb__source"


def test_collection_overwrite_preserves_created_at(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    initial = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="BTCUSDT_30m_rsi_pack",
            recipes=(first, second),
        )
    )
    overwritten = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="BTCUSDT_30m_rsi_pack",
            recipes=(first, second),
            description="updated description",
        )
    )

    assert overwritten.collection_id == initial.collection_id
    assert overwritten.collection_hash == initial.collection_hash
    assert overwritten.created_at_ms == initial.created_at_ms
    assert overwritten.updated_at_ms >= overwritten.created_at_ms
    assert overwritten.description == "updated description"


def test_collection_identity_is_stable_for_same_ordered_recipes(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    a = store.build_collection(
        market=first.market,
        display_name="Pack A",
        recipes=(first, second),
    )
    b = store.build_collection(
        market=first.market,
        display_name="Different display name",
        description="Different mutable description",
        recipes=(first, second),
    )

    assert a.collection_id == b.collection_id
    assert a.collection_hash == b.collection_hash


def test_collection_order_affects_hash(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    forward = store.build_collection(
        market=first.market,
        display_name="Forward",
        recipes=(first, second),
    )
    reverse = store.build_collection(
        market=first.market,
        display_name="Reverse",
        recipes=(second, first),
    )

    assert forward.collection_id != reverse.collection_id
    assert forward.collection_hash != reverse.collection_hash


def test_collection_rename_preserves_id_and_hash(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    saved = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="Original Pack",
            recipes=(first, second),
        )
    )

    renamed = store.rename_collection(
        market=first.market,
        collection_id=saved.collection_id,
        new_display_name="Renamed Pack",
    )

    assert renamed.collection_id == saved.collection_id
    assert renamed.collection_hash == saved.collection_hash
    assert renamed.display_name == "Renamed Pack"
    assert renamed.updated_at_ms >= saved.updated_at_ms


def test_collection_delete_does_not_delete_recipe_json_files(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    recipe_store = ArtifactRecipeStore(historical_root=tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    saved = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="Delete Pack",
            recipes=(first, second),
        )
    )

    collection_path = store.collection_path(
        market=first.market,
        collection_id=saved.collection_id,
    )
    first_recipe_path = recipe_store.recipe_path(
        market=first.market,
        recipe_id=first.recipe_id,
    )
    second_recipe_path = recipe_store.recipe_path(
        market=second.market,
        recipe_id=second.recipe_id,
    )

    store.delete_collection(
        market=first.market,
        collection_id=saved.collection_id,
    )

    assert not collection_path.exists()
    assert first_recipe_path.exists()
    assert second_recipe_path.exists()


def test_collection_rejects_empty_recipes(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    with pytest.raises(ValueError, match="at least one recipe"):
        store.build_collection(
            market=market,
            display_name="Empty Pack",
            recipes=(),
        )


def test_collection_rejects_recipes_from_different_market(tmp_path: Path) -> None:
    recipe_store = ArtifactRecipeStore(historical_root=tmp_path)
    btc_recipe = recipe_store.save_recipe(_payload(period=14, symbol="BTC/USDT"))
    eth_recipe = recipe_store.save_recipe(_payload(period=14, symbol="ETH/USDT"))
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)

    with pytest.raises(ValueError, match="different market"):
        store.build_collection(
            market=btc_recipe.market,
            display_name="Mixed Market Pack",
            recipes=(btc_recipe, eth_recipe),
        )


def test_collection_persists_dependency_edges_as_metadata_only(tmp_path: Path) -> None:
    first, second = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    edge = ArtifactRecipeDependencyEdge(
        from_recipe_id=first.recipe_id,
        to_recipe_id=second.recipe_id,
        reason="second recipe consumes first output",
        required_columns=first.output_names,
        source_family="oscillators",
        source_artifact_uid="oscillator:bybit:linear:BTCUSDT:30m:test",
    )

    saved = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="Dependency Pack",
            recipes=(first, second),
            dependency_edges=(edge,),
        )
    )
    loaded = store.load_collection(
        market=first.market,
        collection_id=saved.collection_id,
    )

    assert loaded.dependency_edges == (edge,)
    assert loaded.dependency_edges[0].required_columns == first.output_names
