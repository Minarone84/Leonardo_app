from __future__ import annotations

from pathlib import Path


def test_ohlcv_maintenance_window_uses_core_bridge_not_data_layer_files() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "from leonardo.gui.core_bridge import CoreBridge" in source
    assert "from leonardo.data.historical" not in source
    assert "delete_historical_ohlcv_dataset" in source
    assert "rebuild_historical_ohlcv_metadata" in source
    assert "plan_historical_ohlcv_repair" in source
    assert "execute_historical_ohlcv_repair" in source
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
    assert 'QPushButton("Select All"' in source
    assert 'QPushButton("Deselect All"' in source
    assert 'QPushButton("Analyze Checked"' in source
    assert "Analyze Current" not in source
    assert "def select_all_datasets" in source
    assert "def deselect_all_datasets" in source
    assert "def validate_current" not in source
    assert "Qt.ItemFlag.ItemIsUserCheckable" in source
    assert "Qt.CheckState.Unchecked" in source
    assert "itemChanged.connect(self._on_dataset_item_changed)" in source
    assert "def _checked_datasets" in source
    assert "def _start_validation_batch" in source
    assert "QProgressDialog" in source
    assert 'if status == "ok":\n            return "OK"' in source
    assert 'if status == "warning":\n            return "Warning"' in source
    assert 'if status == "error":\n            return "Error"' in source
    assert "def _apply_row_validation_style" in source
    assert "metadata_updated" in source
    assert "validate_historical_ohlcv_dataset" in source


def test_ohlcv_maintenance_window_exposes_single_dataset_repair_planning() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert 'QPushButton("Plan Repair"' in source
    assert "def plan_repair_selected" in source
    assert "plan_historical_ohlcv_repair" in source
    assert "def _format_repair_plan" in source
    assert "Repair Plan" in source
    assert "def _checked_datasets" in source
    assert "plan_repair_selected" in source
    assert "fetch_ohlcv" not in source
    assert "HistoricalDownloader" not in source
    assert "DownloadRequest" not in source


def test_ohlcv_maintenance_window_exposes_confirmed_repair_execution() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert 'QPushButton("Execute Repair..."' in source
    assert "def execute_repair_selected" in source
    assert "class OhlcvRepairConfirmDialog" in source
    assert "class OhlcvRepairProgressDialog" in source
    assert "def _confirm_execute_repair" in source
    assert "Confirm OHLCV Repair" in source
    assert "OHLCV Repair Progress" in source
    assert "execute_historical_ohlcv_repair" in source
    assert "def _format_repair_execution" in source
    assert "def _format_repair_confirmation" in source
    assert "Repair Execution Complete" in source
    assert "self._last_repair_plan" in source
    assert "Execute Repair" in source
    assert "candles.csv may be rewritten" in source
    assert "candles.meta.json may be rewritten" in source
    assert "Final validation status" in source
    assert "Cache invalidated" in source
    assert "Repair outcome" in source
    assert "Source-Invalid Candles" in source
    assert "source_invalid_anchors" in source
    assert "No local correction was applied." in source
    assert "Dataset remains Error." in source


def test_ohlcv_maintenance_window_centralizes_action_state_and_row_styling() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "def _update_action_state" in source
    assert "def _actions_busy" in source
    assert "def _can_execute_checked_repair_plan" in source
    assert "def _sole_checked_dataset" in source
    assert "def _clear_repair_plan" in source
    assert "def _restyle_dataset_row" in source
    assert "self._validate_button.setEnabled(bool(checked) and not busy)" in source
    assert "self._repair_plan_button.setEnabled(self._can_plan_checked_repair() and not busy)" in source
    assert "self._rebuild_metadata_button.setEnabled(checked_count == 1 and not busy)" in source
    assert "self._delete_button.setEnabled(checked_count == 1 and not busy)" in source
    assert "self._execute_repair_button.setEnabled(self._can_execute_checked_repair_plan() and not busy)" in source
    assert "QColor(198, 239, 206)" in source
    assert "QColor(0, 0, 0)" in source
    assert "QColor(156, 0, 6)" in source
    assert "QColor(255, 242, 128)" in source
    assert "QColor(224, 224, 224)" in source
    assert "font.setBold(bold)" in source


def test_ohlcv_maintenance_window_requires_current_validation_before_repair_planning() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "self._current_validation_keys: set[tuple[str, str, str, str]] = set()" in source
    assert "def _can_plan_checked_repair" in source
    assert "if key not in self._current_validation_keys:" in source
    assert 'return self._validation_status_by_key.get(key) in {"Error", "Warning"}' in source
    assert "current=True" in source
    assert "Run Analyze Checked for the checked dataset before planning repair" in source
    assert "self._repair_plan_button.setEnabled(checked_count == 1 and not busy)" not in source


def test_ohlcv_maintenance_window_preserves_repair_recap_after_auto_validation() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "self._pending_repair_validation_recap" in source
    assert "self._pending_repair_validation_key" in source
    assert "def _consume_pending_repair_validation_recap" in source
    assert "Repair Execution Recap" in source
    assert "self._pending_repair_validation_recap = repair_text" in source


def test_ohlcv_maintenance_window_uses_checked_rows_for_single_dataset_actions() -> None:
    source = Path("src/leonardo/gui/windows/ohlcv_maintenance_window.py").read_text(encoding="utf-8")

    assert "summary = self._sole_checked_dataset()" in source
    assert "Check exactly one OHLCV dataset before planning repair" in source
    assert "Check exactly one OHLCV dataset before rebuilding metadata" in source
    assert "Check exactly one OHLCV dataset before deleting" in source
    assert "self._start_validation_batch((dataset,))" in source
    assert "Repair plan cleared because checked dataset selection changed." in source


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
