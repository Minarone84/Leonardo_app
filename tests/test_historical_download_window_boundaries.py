from __future__ import annotations

from pathlib import Path


def test_historical_download_window_uses_core_bridge_download_boundary() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "from leonardo.data.historical.downloader" not in source
    assert "HistoricalDownloader" not in source
    assert "DownloadRequest" not in source
    assert "DownloadBatchRequest" not in source
    assert "runtime.data_dir" not in source
    assert ' / "historical"' not in source


def test_historical_download_window_status_uses_read_only_message_panel() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "self.status_panel = QPlainTextEdit()" in source
    assert "self.status_panel.setReadOnly(True)" in source
    assert "self._status_text" in source
    assert "self.status_lbl.text().startswith" not in source


def test_historical_download_window_reports_preliminary_validation_without_certifying_metadata() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "Preliminary validation:" in source
    assert "Metadata validation.status:" in source
    assert "Manual OHLCV Maintenance validation is still required" in source
    assert "Open Historical > OHLCV Maintenance" in source
    assert "font-weight: 700; color: #b00020;" in source
    assert "font-weight: 700; color: #8a5a00;" in source
    assert "Preliminary Validation Failed" in source
    assert "Preliminary Validation Warning" in source
    assert "record_validation_result" not in source
    assert "HistoricalDatasetValidator" not in source


def test_historical_download_window_applies_local_font_bump_to_download_surfaces() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "def _bump_historical_download_widget_tree_font" in source
    assert "point_size + points" in source
    assert "point_size_f + float(points)" in source
    assert "target.setFont(QFont(bumped))" in source
    assert "DownloadPreflightConfirmDialog" in source
    assert "DownloadTaskMonitorDialog" in source
    assert "_bump_historical_download_widget_tree_font(self)" in source
    assert "QPlainTextEdit" in source
    assert "QProgressBar" in source
    assert "QApplication.setFont" not in source


def test_historical_download_window_exposes_ohlcv_maintenance_intent_only() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "ohlcv_maintenance_requested = Signal()" in source
    assert "self.maintenance_btn = QPushButton(\"OHLCV Maintenance...\")" in source
    assert "self.maintenance_btn.clicked.connect(self.ohlcv_maintenance_requested.emit)" in source
    assert "OHLCVMaintenanceWindow" not in source
