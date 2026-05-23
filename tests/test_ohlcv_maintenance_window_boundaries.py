from __future__ import annotations

from pathlib import Path


def test_ohlcv_maintenance_window_uses_core_bridge_not_data_layer_files() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "from leonardo.gui.core_bridge import CoreBridge" in source
    assert "from leonardo.data.historical" not in source
    assert "delete_historical_ohlcv_dataset" in source
    assert "rebuild_historical_ohlcv_metadata" in source
    assert "QMessageBox" in source
    assert "CsvOHLCVStore" not in source
    assert "HistoricalDatasetValidator" not in source
    assert "ArtifactMetadataBackfill" not in source
    assert "rebuild_metadata_sidecar" not in source
    assert "metadata_path_for_csv" not in source
    assert "pd.read_csv" not in source
    assert "unlink(" not in source
    assert "remove(" not in source
    assert "rmtree(" not in source
    assert "write_text(" not in source


def test_ohlcv_maintenance_window_exposes_checked_batch_validation_status() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "QTableWidget(0, 7" in source
    assert '"Select", "Exchange", "Market", "Symbol", "Timeframe", "Storage", "Validation"' in source
    assert "Qt.ItemFlag.ItemIsUserCheckable" in source
    assert "Qt.CheckState.Unchecked" in source
    assert "def _checked_datasets" in source
    assert "def _start_validation_batch" in source
    assert "QProgressDialog" in source
    assert 'if status == "ok":\n            return "OK"' in source
    assert 'if status == "warning":\n            return "Warning"' in source
    assert 'if status == "error":\n            return "Error"' in source
    assert "def _apply_row_validation_style" in source
    assert "validate_historical_ohlcv_dataset" in source


def test_ohlcv_validation_uses_same_validator_path_as_downloads() -> None:
    maintenance_source = Path("src/leonardo/data/historical/ohlcv_maintenance.py").read_text(encoding="utf-8")
    downloader_source = Path("src/leonardo/data/historical/downloader.py").read_text(encoding="utf-8")

    assert "HistoricalDatasetValidator(summary.timeframe).validate(summary.csv_path)" in maintenance_source
    assert "HistoricalDatasetValidator(market.timeframe)" in downloader_source


def test_window_manager_tracks_ohlcv_maintenance_window() -> None:
    source = Path("src/leonardo/gui/windows/window_manager.py").read_text(encoding="utf-8")

    assert "OHLCVMaintenanceWindow" in source
    assert "open_ohlcv_maintenance" in source
    assert "window_open(\n                    \"ohlcv_maintenance\"" in source
    assert "window_close(\"ohlcv_maintenance\"" in source
