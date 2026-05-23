from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from leonardo.data.naming import MarketId, canonicalize, normalize_timeframe

DatasetType = Literal[
    "ohlcv",
    "indicators",
    "oscillators",
    "constructs",
    "analysis_databases",
    "trade_signal",
    "signal_elaboration",
]


def timeframe_to_storage_segment(timeframe: str) -> str:
    """
    Return the filesystem segment for a canonical timeframe.

    Canonical timeframe identity remains unchanged in APIs and metadata. The
    storage segment is allowed to differ where case-insensitive filesystems
    would otherwise collapse distinct canonical values such as ``1m`` and
    ``1M`` into one directory.
    """
    canonical = normalize_timeframe(timeframe)
    if canonical.endswith("M"):
        return f"{canonical[:-1]}mo"
    return canonical


def storage_segment_to_timeframe(segment: str) -> str:
    """
    Return the canonical timeframe represented by a storage segment.

    This accepts current collision-safe month segments such as ``1mo`` and
    legacy canonical segments such as ``1M``.
    """
    return normalize_timeframe(segment)


@dataclass(frozen=True)
class HistoricalPaths:
    """
    Deterministic filesystem layout for historical data.

    Layout:
      <root>/
        <exchange>/
          <market_type>/
            <symbol>/
              <timeframe_storage_segment>/
                <dataset>/

    Example:
      data/historical/bybit/linear/BTCUSDT/30m/ohlcv/
    """

    root: Path

    def partition_dir(self, m: MarketId) -> Path:
        return (
            self.root
            / m.exchange
            / m.market_type
            / m.symbol
            / timeframe_to_storage_segment(m.timeframe)
        )

    def dataset_dir(self, m: MarketId, dataset: DatasetType) -> Path:
        return self.partition_dir(m) / dataset

    def ensure_dataset_dir(self, m: MarketId, dataset: DatasetType) -> Path:
        p = self.dataset_dir(m, dataset)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ohlcv_dir(self, m: MarketId) -> Path:
        return self.dataset_dir(m, "ohlcv")

    def ensure_ohlcv_dir(self, m: MarketId) -> Path:
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
) -> tuple[MarketId, HistoricalPaths]:
    """
    Canonicalize inputs (Option A) and return (MarketId, HistoricalPaths).
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
) -> tuple[MarketId, Path]:
    """
    Convenience helper returning (MarketId, <ohlcv_dir>).
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
