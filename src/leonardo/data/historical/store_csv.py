from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Dict


@dataclass(frozen=True)
class Candle:
    """
    Canonical candle representation for persistence.
    Timestamp is ms epoch UTC.
    """
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class CsvOHLCVStore:
    """
    CSV store for a single partition:
      .../<exchange>/<market_type>/<symbol>/<timeframe>/ohlcv/candles.csv

    Guarantees:
    - read returns sorted by ts_ms ascending
    - write_atomic replaces the file atomically
    - merge_idempotent dedupes by ts_ms and prefers incoming on collision
    """

    FILENAME = "candles.csv"
    HEADER = ["ts_ms", "open", "high", "low", "close", "volume"]

    def file_path(self, ohlcv_dir: Path) -> Path:
        return ohlcv_dir / self.FILENAME

    def read(self, file_path: Path) -> List[Candle]:
        if not file_path.exists():
            return []

        out: List[Candle] = []
        with file_path.open("r", newline="") as f:
            r = csv.DictReader(f)
            # tolerate missing header/columns with clear error
            for row in r:
                out.append(
                    Candle(
                        ts_ms=int(row["ts_ms"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )

        out.sort(key=lambda c: c.ts_ms)
        return out

    def write_atomic(self, file_path: Path, candles: List[Candle]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory then atomic replace
        fd, tmp_path = tempfile.mkstemp(
            prefix=file_path.name + ".",
            suffix=".tmp",
            dir=str(file_path.parent),
        )
        try:
            with os.fdopen(fd, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.HEADER)
                for c in candles:
                    w.writerow([c.ts_ms, c.open, c.high, c.low, c.close, c.volume])

            os.replace(tmp_path, file_path)
        finally:
            # If replace failed, try cleanup temp
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass


def merge_idempotent(existing: Iterable[Candle], incoming: Iterable[Candle]) -> List[Candle]:
    """
    Merge by ts_ms, removing duplicates.
    On collision (same timestamp), prefer incoming.
    """
    by_ts: Dict[int, Candle] = {c.ts_ms: c for c in existing}
    for c in incoming:
        by_ts[c.ts_ms] = c

    out = list(by_ts.values())
    out.sort(key=lambda c: c.ts_ms)
    return out