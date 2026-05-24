from __future__ import annotations

from pathlib import Path


ROOT = Path("src/leonardo")
HDM = ROOT / "gui" / "windows" / "historical_data_manager_window.py"
PRESET_COMPATIBILITY = ROOT / "gui" / "windows" / "_historical_data_manager" / "preset_compatibility.py"
CORE_BRIDGE = ROOT / "gui" / "core_bridge.py"
DATASET_SERVICE = ROOT / "data" / "historical" / "dataset_service.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_historical_data_manager_create_chart_uses_loadability_gate() -> None:
    source = _source(HDM)

    assert "historical_dataset_loadability" in source
    assert "No validated OHLCV datasets available" in source
    assert "Open Historical \\u2192 OHLCV Maintenance" in source
    assert "Selected OHLCV dataset is not accepted for chart loading" in source
    assert "timeframe} (Modified)" in source


def test_historical_data_manager_gui_does_not_parse_ohlcv_or_metadata() -> None:
    source = _source(HDM)

    assert "candles.meta" not in source
    assert "metadata_path_for_csv" not in source
    assert "HistoricalDatasetValidator" not in source
    assert "pd.read_csv" not in source
    assert "read_csv" not in source
    assert "json.load" not in source


def test_core_bridge_exposes_thin_historical_dataset_loadability_boundary() -> None:
    source = _source(CORE_BRIDGE)

    assert "def historical_dataset_loadability" in source
    assert "dataset_loadability(dataset_id)" in source
    assert "LOADABLE_OHLCV_VALIDATION_STATUSES" not in source


def test_workspace_snapshot_preflight_uses_loadability_reason() -> None:
    source = _source(PRESET_COMPATIBILITY)

    assert "historical_dataset_loadability" in source
    assert "blocked_ohlcv_dataset" in source
    assert "dataset is not loadable" in source
    assert "candles.meta" not in source
    assert "metadata_path_for_csv" not in source
    assert "HistoricalDatasetValidator" not in source


def test_dataset_service_owns_loadable_ohlcv_status_policy() -> None:
    source = _source(DATASET_SERVICE)

    assert 'LOADABLE_OHLCV_VALIDATION_STATUSES: frozenset[str] = frozenset({"ok", "modified"})' in source
    assert '"not_validated"' in source
    assert '"warning"' in source
    assert "def is_ohlcv_dataset_loadable" in source
    assert "def dataset_loadability" in source
    assert "validation.csv_fingerprint" in source
