from __future__ import annotations

from pathlib import Path

from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.naming import canonicalize


def _payload() -> dict:
    return {
        "tool_type": "oscillator",
        "tool_key": "rsi",
        "tool_title": "RSI",
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTC/USDT",
        "timeframe": "30m",
        "params": {"period": 14},
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": ["close"],
        "output_names": ["rsi_14"],
        "output_signals": [
            {
                "name": "rsi_14",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
                "label": "RSI 14",
                "description": "",
            }
        ],
    }


def test_artifact_recipe_store_saves_loads_and_lists_recipe(tmp_path: Path) -> None:
    store = ArtifactRecipeStore(historical_root=tmp_path)
    recipe = store.save_recipe(_payload())

    assert recipe.recipe_id.startswith("ar__oscillator__rsi__h")
    assert recipe.recipe_hash_short.startswith("h")
    assert recipe.display_name == "RSI · rsi_14"
    assert recipe.market == canonicalize("bybit", "linear", "BTCUSDT", "30m")

    recipe_path = store.recipe_path(
        market=recipe.market,
        recipe_id=recipe.recipe_id,
    )
    assert recipe_path.exists()
    assert recipe_path.parent == (
        tmp_path
        / "bybit"
        / "linear"
        / "BTCUSDT"
        / "30m"
        / "artifact_recipes"
    )

    loaded = store.load_recipe(
        market=recipe.market,
        recipe_id=recipe.recipe_id,
    )
    assert loaded == recipe
    assert loaded.to_payload()["tool_key"] == "rsi"
    assert loaded.to_payload()["params"] == {"period": 14}

    summaries = store.list_recipes(market=recipe.market)
    assert len(summaries) == 1
    assert summaries[0].recipe_id == recipe.recipe_id
    assert summaries[0].output_names == ("rsi_14",)


def test_artifact_recipe_store_overwrite_preserves_created_at(tmp_path: Path) -> None:
    store = ArtifactRecipeStore(historical_root=tmp_path)

    first = store.save_recipe(_payload())
    second = store.save_recipe(_payload())

    assert second.recipe_id == first.recipe_id
    assert second.recipe_hash == first.recipe_hash
    assert second.created_at_ms == first.created_at_ms
    assert second.updated_at_ms >= second.created_at_ms


def test_artifact_recipe_store_payload_change_creates_new_recipe_id(
    tmp_path: Path,
) -> None:
    store = ArtifactRecipeStore(historical_root=tmp_path)

    first = store.save_recipe(_payload())

    modified = _payload()
    modified["params"] = {"period": 21}
    modified["output_names"] = ["rsi_21"]

    second = store.save_recipe(modified)

    assert second.recipe_id != first.recipe_id
    assert len(store.list_recipes(market=first.market)) == 2


def test_artifact_recipe_store_delete_recipe(tmp_path: Path) -> None:
    store = ArtifactRecipeStore(historical_root=tmp_path)

    recipe = store.save_recipe(_payload())
    path = store.recipe_path(
        market=recipe.market,
        recipe_id=recipe.recipe_id,
    )
    assert path.exists()

    store.delete_recipe(
        market=recipe.market,
        recipe_id=recipe.recipe_id,
    )

    assert not path.exists()
    assert store.list_recipes(market=recipe.market) == []