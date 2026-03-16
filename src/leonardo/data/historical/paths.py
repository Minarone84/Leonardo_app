from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from leonardo.data.naming import CanonicalMarket, canonicalize

DatasetType = Literal[
    "ohlcv",
    "indicators",
    "oscillators",
    "trade_signal",
    "signal_elaboration",
]


@dataclass(frozen=True)
class HistoricalPaths:
    """
    Deterministic filesystem layout for historical data.

    Layout:
      <root>/
        <exchange>/
          <market_type>/
            <symbol>/
              <timeframe>/
                <dataset>/

    Example:
      data/historical/bybit/linear/BTCUSDT/30m/ohlcv/
    """

    root: Path

    def partition_dir(self, m: CanonicalMarket) -> Path:
        return self.root / m.exchange / m.market_type / m.symbol / m.timeframe

    def dataset_dir(self, m: CanonicalMarket, dataset: DatasetType) -> Path:
        return self.partition_dir(m) / dataset

    def ensure_dataset_dir(self, m: CanonicalMarket, dataset: DatasetType) -> Path:
        p = self.dataset_dir(m, dataset)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ohlcv_dir(self, m: CanonicalMarket) -> Path:
        return self.dataset_dir(m, "ohlcv")

    def ensure_ohlcv_dir(self, m: CanonicalMarket) -> Path:
        return self.ensure_dataset_dir(m, "ohlcv")


def default_historical_root() -> Path:
    """
    Default root. Later configurable via core config.
    """
    return Path("data") / "historical"


def build_market_and_paths(
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    timeframe: str,
    root: Path | None = None,
) -> tuple[CanonicalMarket, HistoricalPaths]:
    """
    Canonicalize inputs (Option A) and return (CanonicalMarket, HistoricalPaths).
    """
    m = canonicalize(exchange, market_type, symbol, timeframe)
    paths = HistoricalPaths(root=root or default_historical_root())
    return m, paths


def build_ohlcv_partition(
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    timeframe: str,
    root: Path | None = None,
    ensure: bool = True,
) -> tuple[CanonicalMarket, Path]:
    """
    Convenience helper returning (CanonicalMarket, <ohlcv_dir>).
    """
    m, paths = build_market_and_paths(
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        root=root,
    )
    d = paths.ensure_ohlcv_dir(m) if ensure else paths.ohlcv_dir(m)
    return m, d