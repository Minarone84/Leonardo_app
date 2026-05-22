from __future__ import annotations

import asyncio
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from leonardo.data.historical.downloader import DownloadBatchRequest, DownloadRequest
from leonardo.gui.core_bridge import CoreBridge


class _FakeDownloader:
    instances: list["_FakeDownloader"] = []

    def __init__(self, root: Path) -> None:
        self.root = root
        self.preflight_calls: list[tuple[object, object]] = []
        self.start_calls: list[tuple[object, object]] = []
        _FakeDownloader.instances.append(self)

    async def preflight(self, ctx: object, req: DownloadRequest) -> tuple[str, object, DownloadRequest]:
        self.preflight_calls.append((ctx, req))
        return ("preflight", ctx, req)

    async def preflight_batch(
        self,
        ctx: object,
        req: DownloadBatchRequest,
    ) -> tuple[str, object, DownloadBatchRequest]:
        self.preflight_calls.append((ctx, req))
        return ("preflight_batch", ctx, req)

    def start(self, ctx: object, req: DownloadRequest) -> str:
        self.start_calls.append((ctx, req))
        return "job-single"

    def start_batch(self, ctx: object, req: DownloadBatchRequest) -> str:
        self.start_calls.append((ctx, req))
        return "job-batch"


class _Bridge:
    _historical_download_root = staticmethod(CoreBridge._historical_download_root)
    preflight_historical_download = CoreBridge.preflight_historical_download
    preflight_historical_download_batch = CoreBridge.preflight_historical_download_batch
    start_historical_download = CoreBridge.start_historical_download
    start_historical_download_batch = CoreBridge.start_historical_download_batch

    def __init__(self, data_dir: Path) -> None:
        self.context = SimpleNamespace(config=SimpleNamespace(runtime=SimpleNamespace(data_dir=str(data_dir))))

    def submit(self, coro: Any) -> Future[Any]:
        fut: Future[Any] = Future()
        try:
            fut.set_result(asyncio.run(coro))
        except BaseException as exc:
            fut.set_exception(exc)
        return fut


def _install_fake_downloader(monkeypatch: Any) -> None:
    _FakeDownloader.instances.clear()
    monkeypatch.setattr("leonardo.gui.core_bridge.HistoricalDownloader", _FakeDownloader)


def test_core_bridge_preflight_builds_downloader_and_batch_request(monkeypatch: Any, tmp_path: Path) -> None:
    _install_fake_downloader(monkeypatch)
    bridge = _Bridge(tmp_path)

    result = CoreBridge.preflight_historical_download_batch(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframes=("1m", "5m"),
        start_ms=1,
        end_ms=2,
        limit=3,
    ).result()

    kind, ctx, req = result
    assert kind == "preflight_batch"
    assert ctx is bridge.context
    assert isinstance(req, DownloadBatchRequest)
    assert req.exchange == "bybit"
    assert req.market_type == "linear"
    assert req.symbol == "BTCUSDT"
    assert req.timeframes == ("1m", "5m")
    assert req.start_ms == 1
    assert req.end_ms == 2
    assert req.limit == 3
    assert _FakeDownloader.instances[0].root == tmp_path / "historical"


def test_core_bridge_start_preserves_single_download_return_shape(monkeypatch: Any, tmp_path: Path) -> None:
    _install_fake_downloader(monkeypatch)
    bridge = _Bridge(tmp_path)

    result = CoreBridge.start_historical_download(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="ETHUSDT",
        timeframe="15m",
        start_ms=10,
        end_ms=20,
        limit=30,
    ).result()

    assert result == {"job_id": "job-single", "timeframes": ("15m",)}
    _, req = _FakeDownloader.instances[0].start_calls[0]
    assert isinstance(req, DownloadRequest)
    assert req.exchange == "bybit"
    assert req.market_type == "linear"
    assert req.symbol == "ETHUSDT"
    assert req.timeframe == "15m"
    assert req.start_ms == 10
    assert req.end_ms == 20
    assert req.limit == 30
    assert _FakeDownloader.instances[0].root == tmp_path / "historical"


def test_core_bridge_start_preserves_batch_download_return_shape(monkeypatch: Any, tmp_path: Path) -> None:
    _install_fake_downloader(monkeypatch)
    bridge = _Bridge(tmp_path)

    result = CoreBridge.start_historical_download_batch(
        bridge,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframes=("1m", "1h"),
        start_ms=None,
        end_ms=None,
        limit=None,
    ).result()

    assert result == {"job_id": "job-batch", "timeframes": ("1m", "1h")}
    _, req = _FakeDownloader.instances[0].start_calls[0]
    assert isinstance(req, DownloadBatchRequest)
    assert req.exchange == "bybit"
    assert req.market_type == "linear"
    assert req.symbol == "BTCUSDT"
    assert req.timeframes == ("1m", "1h")
    assert req.start_ms is None
    assert req.end_ms is None
    assert req.limit is None
    assert _FakeDownloader.instances[0].root == tmp_path / "historical"
