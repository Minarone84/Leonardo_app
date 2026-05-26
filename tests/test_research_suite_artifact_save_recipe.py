from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.artifact_recipe_store import (
    ARTIFACT_RECIPE_METADATA_NAMESPACE,
    ArtifactRecipeStore,
    artifact_recipe_metadata_entries,
)
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import canonicalize
from leonardo.gui.historical_chart.tool_execution import HistoricalChartToolExecutionMixin


ROOT = Path(__file__).resolve().parents[1]
TOOL_EXECUTION = ROOT / "src" / "leonardo" / "gui" / "historical_chart" / "tool_execution.py"
HDM_WINDOW = ROOT / "src" / "leonardo" / "gui" / "windows" / "historical_data_manager_window.py"


class _ChartToolExecutionHarness(HistoricalChartToolExecutionMixin):
    def __init__(self, *, data_dir: Path) -> None:
        self._core = SimpleNamespace(
            context=SimpleNamespace(
                config=SimpleNamespace(
                    runtime=SimpleNamespace(data_dir=str(data_dir)),
                ),
            ),
        )

    def _build_instance_key(self, tool_key: str, params: dict[str, object]) -> str:
        return f"{tool_key}__test"


def _payload() -> dict[str, object]:
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


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _load_manifest(csv_path: Path) -> HistoricalCsvArtifactManifest:
    with metadata_path_for_csv(csv_path).open("r", encoding="utf-8") as handle:
        return HistoricalCsvArtifactManifest.from_dict(json.load(handle))


def test_research_suite_artifact_recipe_helper_uses_data_manager_visible_store(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "configured_data"
    historical_root = data_dir / "historical"
    harness = _ChartToolExecutionHarness(data_dir=data_dir)

    recipe = harness._save_artifact_recipe(_payload())

    store = ArtifactRecipeStore(historical_root=historical_root)
    summaries = store.list_recipes(market=recipe.market)

    assert [summary.recipe_id for summary in summaries] == [recipe.recipe_id]
    assert store.recipe_path(market=recipe.market, recipe_id=recipe.recipe_id).exists()


def test_research_suite_recipe_save_reuses_equivalent_recipe(tmp_path: Path) -> None:
    harness = _ChartToolExecutionHarness(data_dir=tmp_path / "configured_data")

    first = harness._save_artifact_recipe(_payload())
    second = harness._save_artifact_recipe(_payload())

    store = ArtifactRecipeStore(historical_root=tmp_path / "configured_data" / "historical")
    assert second.recipe_id == first.recipe_id
    assert second.recipe_hash == first.recipe_hash
    assert len(store.list_recipes(market=first.market)) == 1


def test_recipe_metadata_entries_are_json_safe_and_non_identity_affecting(
    tmp_path: Path,
) -> None:
    recipe = ArtifactRecipeStore(historical_root=tmp_path).save_recipe(_payload())
    entries = artifact_recipe_metadata_entries(recipe)

    payload = [entry.to_dict() for entry in entries]
    json.dumps(payload, sort_keys=True)

    metadata_by_key = {entry.key: entry for entry in entries}
    assert metadata_by_key["recipe_id"].namespace == ARTIFACT_RECIPE_METADATA_NAMESPACE
    assert metadata_by_key["recipe_id"].value == recipe.recipe_id
    assert metadata_by_key["recipe_hash"].value == recipe.recipe_hash
    assert metadata_by_key["recipe_hash_short"].value == recipe.recipe_hash_short
    assert all(entry.identity_affecting is False for entry in entries)


def test_saved_artifact_sidecar_records_recipe_identity(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
    recipe = ArtifactRecipeStore(historical_root=tmp_path).save_recipe(_payload())
    csv_path = DerivedCsvStore(historical_root=tmp_path).save_dataframe(
        market=market,
        kind="oscillators",
        tool_key="rsi",
        instance_key="rsi__period-14",
        df=pd.DataFrame(
            {
                "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
                "rsi_14": [50.0, 55.0],
            }
        ),
        params={"period": 14},
        params_status="explicit",
        metadata=artifact_recipe_metadata_entries(recipe),
    )

    manifest = _load_manifest(csv_path)
    metadata_by_key = {
        (entry.namespace, entry.key): entry
        for entry in manifest.metadata
    }

    assert (
        metadata_by_key[(ARTIFACT_RECIPE_METADATA_NAMESPACE, "recipe_id")].value
        == recipe.recipe_id
    )
    assert (
        metadata_by_key[(ARTIFACT_RECIPE_METADATA_NAMESPACE, "recipe_hash")].value
        == recipe.recipe_hash
    )


def test_research_suite_save_persists_recipe_before_artifact_save() -> None:
    body = _function_source(TOOL_EXECUTION, "save_financial_tool")

    assert "_save_artifact_recipe(payload)" in body
    assert "artifact_recipe_metadata_entries(recipe)" in body
    assert body.index("_save_artifact_recipe(payload)") < body.index(
        "_load_full_dataset_dataframe()"
    )
    assert body.index("_save_artifact_recipe(payload)") < body.index("save_dataframe(")


def test_apply_study_remains_non_persistent() -> None:
    body = _function_source(TOOL_EXECUTION, "apply_financial_tool")

    assert "ArtifactRecipeStore" not in body
    assert "save_recipe(" not in body
    assert "save_dataframe(" not in body


def test_study_setup_and_workspace_snapshot_saves_do_not_persist_recipes() -> None:
    setup_body = _function_source(HDM_WINDOW, "_on_save_study_setup")
    snapshot_body = _function_source(HDM_WINDOW, "_on_save_workspace_snapshot")

    for body in (setup_body, snapshot_body):
        assert "ArtifactRecipeStore" not in body
        assert "save_recipe(" not in body
        assert "artifact_recipes" not in body
