from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QProgressBar

import leonardo.gui.windows.historical_download_window as download_window
from leonardo.gui.windows.historical_download_window import (
    DownloadTaskMonitorDialog,
    HistoricalDownloadWindow,
)


_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _CountingProgressBar(QProgressBar):
    def __init__(self) -> None:
        super().__init__()
        self.range_calls = 0
        self.value_calls = 0
        self.format_calls = 0

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802 - Qt override
        self.range_calls += 1
        super().setRange(minimum, maximum)

    def setValue(self, value: int) -> None:  # noqa: N802 - Qt override
        self.value_calls += 1
        super().setValue(value)

    def setFormat(self, text: str) -> None:  # noqa: N802 - Qt override
        self.format_calls += 1
        super().setFormat(text)


def _progress_fields(*, ratio: float, page: int) -> dict[str, object]:
    return {
        "timeframe": "1m",
        "progress_ratio": ratio,
        "page": page,
        "expected_pages": 10,
        "downloaded_bars": page * 10,
        "expected_bars": 100,
        "total_rows": page * 10,
    }


def _dialog() -> DownloadTaskMonitorDialog:
    _qapp()
    dialog = DownloadTaskMonitorDialog(on_stop=lambda: None)
    dialog.set_context(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframes=("1m",),
        is_batch=False,
    )
    return dialog


def test_monitor_dialog_coalesces_rapid_progress_and_flushes_latest(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(download_window.time, "monotonic", clock)
    dialog = _dialog()

    dialog.update_from_event("download progress", _progress_fields(ratio=0.1, page=1), is_batch_job=False)
    for page in range(2, 6):
        clock.value += 0.01
        dialog.update_from_event(
            "download progress",
            _progress_fields(ratio=float(page) / 10.0, page=page),
            is_batch_job=False,
        )

    text = dialog.log_box.toPlainText()
    assert text.count("[download progress]") == 1
    assert "page=1/10" in text
    assert dialog.current_progress.value() == 10

    dialog._flush_pending_live_progress()

    text = dialog.log_box.toPlainText()
    assert text.count("[download progress]") == 2
    assert "page=5/10" in text
    assert dialog.current_progress.value() == 50


def test_monitor_dialog_flushes_pending_progress_before_error(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(download_window.time, "monotonic", clock)
    dialog = _dialog()

    dialog.update_from_event("download progress", _progress_fields(ratio=0.2, page=2), is_batch_job=False)
    clock.value += 0.01
    dialog.update_from_event("download progress", _progress_fields(ratio=0.3, page=3), is_batch_job=False)

    dialog.update_from_event(
        "download failed",
        {"timeframe": "1m", "error": "provider timeout"},
        is_batch_job=False,
    )

    text = dialog.log_box.toPlainText()
    assert "page=3/10" in text
    assert "[download failed] Download failed: provider timeout" in text
    assert dialog.ok_btn.isEnabled()
    assert dialog.current_progress.format() == "Current timeframe 1m: stopped"


def test_monitor_dialog_skips_redundant_same_state_progress_bar_updates() -> None:
    _qapp()
    dialog = DownloadTaskMonitorDialog(on_stop=lambda: None)
    bar = _CountingProgressBar()

    dialog._set_bar_ratio(bar, 0.25, label="Current timeframe 1m")
    first_counts = (bar.range_calls, bar.value_calls, bar.format_calls)

    dialog._set_bar_ratio(bar, 0.25, label="Current timeframe 1m")
    assert (bar.range_calls, bar.value_calls, bar.format_calls) == first_counts

    dialog._set_bar_ratio(bar, 0.26, label="Current timeframe 1m")
    assert bar.value_calls == first_counts[1] + 1
    assert bar.format_calls == first_counts[2] + 1


def test_main_window_live_progress_status_is_coalesced(monkeypatch) -> None:
    _qapp()
    clock = _Clock()
    monkeypatch.setattr(download_window.time, "monotonic", clock)
    window = HistoricalDownloadWindow(
        object(),
        exchange_names=["bybit"],
        get_supported_markets=lambda _exchange: [],
        get_supported_timeframes=lambda _exchange, _market: [],
    )

    window._set_live_progress_status("Progress: page=1")
    assert window._status_text == "Progress: page=1"

    clock.value += 0.01
    window._set_live_progress_status("Progress: page=2")
    assert window._status_text == "Progress: page=1"
    assert window._pending_live_status == "Progress: page=2"

    window._flush_pending_live_status()
    assert window._status_text == "Progress: page=2"
    assert window._pending_live_status is None


def test_download_progress_throttling_stays_gui_only() -> None:
    text = Path(download_window.__file__).read_text(encoding="utf-8")

    assert "from leonardo.data.historical.downloader" not in text
    assert "HistoricalDownloader" not in text
    assert "write_atomic" not in text
    assert "to_csv" not in text
