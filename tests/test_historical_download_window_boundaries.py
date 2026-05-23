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


def test_historical_download_window_exposes_ohlcv_maintenance_intent_only() -> None:
    source = Path("src/leonardo/gui/windows/historical_download_window.py").read_text(encoding="utf-8")

    assert "ohlcv_maintenance_requested = Signal()" in source
    assert "self.maintenance_btn = QPushButton(\"OHLCV Maintenance...\")" in source
    assert "self.maintenance_btn.clicked.connect(self.ohlcv_maintenance_requested.emit)" in source
    assert "OHLCVMaintenanceWindow" not in source
