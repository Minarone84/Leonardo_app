from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.artifact_recovery_planner import ArtifactRecoveryPlanner
from leonardo.data.historical.artifact_recipe_collection_store import ArtifactRecipeCollectionStore
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
    build_source_ohlcv_provenance_snapshot,
)
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _issues_for_status(status: str) -> tuple[tuple[str, str], ...]:
    if status == "error":
        return (("error", "test validation error"),)
    if status == "warning":
        return (("warning", "test validation warning"),)
    return ()


def _write_ohlcv(
    root: Path,
    *,
    rows: int = 20,
    validation_status: str = "ok",
    write_metadata: bool = True,
    price_offset: float = 0.0,
):
    market = _market()
    paths = HistoricalPaths(root=root)
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    start = 1_700_000_000_000
    candles = [
        Candle(
            ts_ms=start + idx * 1_800_000,
            open=100.0 + idx + price_offset,
            high=101.0 + idx + price_offset,
            low=99.0 + idx + price_offset,
            close=100.5 + idx + price_offset,
            volume=10.0 + idx,
        )
        for idx in range(rows)
    ]
    store = CsvOHLCVStore()
    store.write_atomic(csv_path, candles, market=market, write_metadata=write_metadata)
    if write_metadata:
        store.record_validation_result(
            csv_path,
            market=market,
            status=validation_status,
            row_count=len(candles),
            issues=_issues_for_status(validation_status),
            validator="HistoricalDatasetValidator",
        )
    return market, csv_path


def _rsi_payload(*, period: int = 14) -> dict[str, object]:
    market = _market()
    return {
        "tool_type": "oscillator",
        "tool_key": "rsi",
        "tool_title": "RSI",
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
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


def _utc_payload() -> dict[str, object]:
    market = _market()
    return {
        "tool_type": "indicator",
        "tool_key": "universal_trend_classifier",
        "tool_title": "Universal Trend Classifier",
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
        "params": {"trend_fractal_window": 5, "range_fractal_window": 3},
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": ["open", "high", "low", "close"],
        "output_names": ["hor_upper", "hor_lower"],
        "output_signals": [
            {
                "name": "hor_upper",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
            },
            {
                "name": "hor_lower",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
            },
        ],
    }


def _construct_payload_with_source(source_path: Path, *, column_name: str = "ema_9") -> dict[str, object]:
    market = _market()
    return {
        "tool_type": "construct",
        "tool_key": "derivative",
        "tool_title": "Derivative",
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
        "params": {"source": column_name, "order": 1},
        "input_bindings": {"source": column_name},
        "input_binding_meta": {
            "source": {
                "family": "indicators",
                "source_kind": "saved",
                "tool_key": "ema",
                "instance_key": "ema__default__period-9",
                "column_name": column_name,
                "artifact_path": str(source_path),
            }
        },
        "required_inputs": [column_name],
        "output_names": [f"{column_name}__d1"],
        "output_signals": [
            {
                "name": f"{column_name}__d1",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
            }
        ],
    }


def _recipe(root: Path, payload: dict[str, object]) -> ArtifactRecipe:
    return ArtifactRecipeStore(historical_root=root).save_recipe(payload)


def _collection(root: Path, *recipes: ArtifactRecipe):
    store = ArtifactRecipeCollectionStore(historical_root=root)
    return store.save_collection(
        store.build_collection(
            market=recipes[0].market,
            display_name="Recovery Pack",
            recipes=recipes,
        )
    )


def _source_ohlcv_metadata(root: Path, market) -> tuple[ArtifactMetadataEntry, ...]:
    return (
        ArtifactMetadataEntry(
            namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
            key=SOURCE_OHLCV_PROVENANCE_KEY,
            value=build_source_ohlcv_provenance_snapshot(
                historical_root=root,
                market=market,
            ),
        ),
    )


def _save_rsi_artifact(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    params: dict[str, object] | None = None,
    include_source_snapshot: bool = True,
):
    planner = ArtifactRecoveryPlanner(historical_root=root)
    instance_key = planner.expected_instance_key(recipe)
    period = int(recipe.params["period"])
    market = recipe.market
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=market,
        kind="oscillators",
        tool_key="rsi",
        instance_key=instance_key,
        df=pd.DataFrame(
            {
                "ts_ms": [1_700_000_000_000, 1_700_001_800_000],
                f"rsi_{period}": [50.0, 55.0],
            }
        ),
        params=params if params is not None else dict(recipe.params),
        params_status="explicit",
        bindings={},
        bindings_status="unknown",
        metadata=_source_ohlcv_metadata(root, market) if include_source_snapshot else (),
    )


def _save_peaks_troughs_artifact(root: Path, df: pd.DataFrame) -> Path:
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=_market(),
        kind="indicators",
        tool_key="peaks_troughs",
        instance_key="peaks_troughs",
        df=df,
        params={},
        params_status="explicit",
    )


def test_recovery_planner_reports_missing_artifact_as_recalculable(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.missing_count == 1
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    item = report.items[0]
    assert item.status == "missing"
    assert item.can_recalculate is True
    assert item.existing_csv is False
    assert item.expected_instance_key == "rsi__default__period-14"


def test_recovery_planner_reports_up_to_date_when_csv_and_metadata_match(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.success is True
    assert report.up_to_date_count == 1
    assert report.actionable_recipe_ids == ()
    item = report.items[0]
    assert item.status == "up_to_date"
    assert item.can_recalculate is True
    assert item.existing_csv is True
    assert item.existing_metadata is True


def test_recovery_planner_reports_freshness_unknown_when_metadata_is_missing(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    csv_path = _save_rsi_artifact(tmp_path, recipe)
    csv_path.with_name(f"{csv_path.stem}.meta.json").unlink()
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.freshness_unknown_count == 1
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    item = report.items[0]
    assert item.status == "freshness_unknown"
    assert item.can_recalculate is True
    assert item.existing_csv is True
    assert item.existing_metadata is False
    assert "metadata sidecar is missing" in item.notes[0]


def test_recovery_planner_reports_stale_when_metadata_params_do_not_match(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe, params={"period": 21})
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.stale_count == 1
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    item = report.items[0]
    assert item.status == "stale"
    assert item.can_recalculate is True
    assert "params" in item.stale_reasons[0]


def test_recovery_planner_reports_source_drift_when_ohlcv_fingerprint_changes(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.stale_count == 1
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    item = report.items[0]
    assert item.status == "stale"
    assert item.can_recalculate is True
    assert any("source_csv_fingerprint_changed" in reason for reason in item.stale_reasons)


def test_recovery_planner_blocks_source_drift_recovery_when_current_ohlcv_is_not_loadable(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe)
    _write_ohlcv(tmp_path, validation_status="unknown", price_offset=1_000_000.0)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.blocked_count == 1
    assert report.actionable_recipe_ids == ()
    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("not loadable" in reason for reason in item.blocked_reasons)


def test_recovery_planner_keeps_legacy_missing_source_snapshot_recalculable(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe, include_source_snapshot=False)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.freshness_unknown_count == 1
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    item = report.items[0]
    assert item.status == "freshness_unknown"
    assert item.can_recalculate is True
    assert any("missing_recorded_source_ohlcv_snapshot" in note for note in item.notes)


def test_recovery_planner_preserves_recipe_stale_reason_with_source_drift(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    _save_rsi_artifact(tmp_path, recipe, params={"period": 21})
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "stale"
    assert any("params" in reason for reason in item.stale_reasons)
    assert any("source_csv_fingerprint_changed" in reason for reason in item.stale_reasons)


def test_recovery_planner_blocks_recovery_when_ohlcv_is_missing(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.blocked_count == 1
    assert report.actionable_recipe_ids == ()
    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("OHLCV" in reason for reason in item.blocked_reasons)


def test_recovery_planner_allows_modified_ohlcv_for_recalculation(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, validation_status="modified")
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.missing_count == 1
    assert report.blocked_count == 0
    assert report.actionable_recipe_ids == (recipe.recipe_id,)


@pytest.mark.parametrize("status", ["unknown", "error", "warning"])
def test_recovery_planner_blocks_unaccepted_ohlcv_statuses(
    tmp_path: Path,
    status: str,
) -> None:
    _write_ohlcv(tmp_path, validation_status=status)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.blocked_count == 1
    assert report.actionable_recipe_ids == ()
    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("not loadable" in reason for reason in item.blocked_reasons)
    assert any("OHLCV Maintenance" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_missing_ohlcv_metadata(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, write_metadata=False)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("metadata sidecar" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_stale_ohlcv_validation_fingerprint(tmp_path: Path) -> None:
    _market, csv_path = _write_ohlcv(tmp_path, validation_status="ok")
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("changed after validation" in reason or "stale" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_construct_recovery_when_saved_source_is_missing(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    missing_source_path = tmp_path / "missing_source.csv"
    recipe = _recipe(tmp_path, _construct_payload_with_source(missing_source_path))
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.blocked_count == 1
    assert report.actionable_recipe_ids == ()
    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("Source artifact" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_utc_when_peaks_troughs_artifact_is_missing(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _utc_payload())
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    assert report.blocked_count == 1
    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("Peaks & Troughs" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_utc_when_peaks_troughs_columns_are_missing(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _utc_payload())
    _save_peaks_troughs_artifact(
        tmp_path,
        pd.DataFrame(
            {
                "ts_ms": [1_700_000_000_000, 1_700_001_800_000],
                "peak_fractal_5": [1.0, 2.0],
                "trough_fractal_5": [3.0, 4.0],
            }
        ),
    )
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("does not contain columns required by UTC" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_utc_when_peaks_troughs_join_key_is_missing(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _utc_payload())
    path = _save_peaks_troughs_artifact(
        tmp_path,
        pd.DataFrame(
            {
                "ts_ms": [1_700_000_000_000, 1_700_001_800_000],
                "peak_fractal_5": [1.0, 2.0],
                "trough_fractal_5": [3.0, 4.0],
                "peak_fractal_3": [5.0, 6.0],
                "trough_fractal_3": [7.0, 8.0],
            }
        ),
    )
    pd.read_csv(path).drop(columns=["ts_ms"]).to_csv(path, index=False)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("cannot be aligned safely for UTC" in reason for reason in item.blocked_reasons)


def test_recovery_planner_blocks_utc_when_peaks_troughs_join_key_has_duplicates(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _utc_payload())
    path = _save_peaks_troughs_artifact(
        tmp_path,
        pd.DataFrame(
            {
                "ts_ms": [1_700_000_000_000, 1_700_001_800_000],
                "peak_fractal_5": [1.0, 2.0],
                "trough_fractal_5": [3.0, 4.0],
                "peak_fractal_3": [5.0, 6.0],
                "trough_fractal_3": [7.0, 8.0],
            }
        ),
    )
    broken = pd.read_csv(path)
    broken.loc[1, "ts_ms"] = broken.loc[0, "ts_ms"]
    broken.to_csv(path, index=False)
    collection = _collection(tmp_path, recipe)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)

    item = report.items[0]
    assert item.status == "blocked"
    assert item.can_recalculate is False
    assert any("duplicate 'ts_ms' values" in reason for reason in item.blocked_reasons)


def test_recovery_planner_uses_shared_utc_dependency_column_resolver() -> None:
    root = Path(__file__).resolve().parents[1]
    planner_source = (
        root / "src" / "leonardo" / "data" / "historical" / "artifact_recovery_planner.py"
    ).read_text(encoding="utf-8")

    assert "from leonardo.data.historical.utc_dependency_sources import utc_peak_trough_columns" in planner_source
    assert "def _utc_peak_trough_columns" not in planner_source


def test_recovery_planner_selected_recipe_ids_keep_collection_order(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, _rsi_payload(period=14))
    second = _recipe(tmp_path, _rsi_payload(period=21))
    third = _recipe(tmp_path, _rsi_payload(period=28))
    collection = _collection(tmp_path, first, second, third)

    report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(
        collection,
        selected_recipe_ids=(third.recipe_id, first.recipe_id),
    )

    assert report.requested_recipe_ids == (first.recipe_id, third.recipe_id)
    assert [item.recipe_index for item in report.items] == [0, 2]
    assert report.actionable_recipe_ids == (first.recipe_id, third.recipe_id)


def test_recovery_planner_rejects_unknown_selected_recipe_id(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _rsi_payload(period=14))
    collection = _collection(tmp_path, recipe)

    with pytest.raises(ValueError, match="not in collection"):
        ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(
            collection,
            selected_recipe_ids=("ar__missing",),
        )
