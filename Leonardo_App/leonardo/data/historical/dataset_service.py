from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict
import bisect
import time


@dataclass(frozen=True)
class DatasetId:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str

    def key(self) -> Tuple[str, str, str, str]:
        return (self.exchange, self.market_type, self.symbol, self.timeframe)


@dataclass(frozen=True)
class DatasetMeta:
    first_ts_ms: int
    last_ts_ms: int
    count: int
    path: str


@dataclass(frozen=True)
class SliceRequest:
    tab_id: str
    request_id: str
    dataset_id: DatasetId
    center_ts_ms: int
    visible_max: int = 1000
    buffer_left: int = 500
    buffer_right: int = 500
    reason: str = "pan"


@dataclass(frozen=True)
class SlicePayload:
    tab_id: str
    request_id: str
    dataset_id: DatasetId

    base_index: int  # global index of the first row in the dataset
    ts_ms: List[int]
    open: List[float]
    high: List[float]
    low: List[float]
    close: List[float]
    volume: List[float]

    has_more_left: bool
    has_more_right: bool
    first_ts_ms: int
    last_ts_ms: int


class LruSliceCache:
    """
    Simple LRU cache keyed by (dataset_key, start_idx, end_idx_exclusive).
    Cache size is bounded by number of entries (not bytes).
    """
    def __init__(self, max_entries: int = 128) -> None:
        self._max = max_entries
        self._d: "OrderedDict[Tuple[Tuple[str, str, str, str], int, int], SlicePayload]" = OrderedDict()

    def get(self, key):
        v = self._d.get(key)
        if v is None:
            return None
        self._d.move_to_end(key)
        return v

    def put(self, key, value: SlicePayload) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)


class HistoricalDatasetService:
    """
    Read-only dataset accessor for historical candles.csv.
    v1 policy:
      - Load full CSV once per dataset (cached in-memory).
      - Serve windowed slices (visible<=1000 plus buffers).
      - Async safe: file IO/parsing runs via asyncio.to_thread().
    """

    def __init__(
        self,
        data_root: Path,
        *,
        slice_cache_entries: int = 128,
    ) -> None:
        self._data_root = data_root
        self._slice_cache = LruSliceCache(max_entries=slice_cache_entries)

        # Per-dataset in-memory store: ts and OHLCV columns
        self._datasets: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}
        self._locks: Dict[Tuple[str, str, str, str], asyncio.Lock] = {}

    def _dataset_lock(self, key: Tuple[str, str, str, str]) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _resolve_path(self, dataset_id: DatasetId) -> Path:
        # Expected structure:
        # data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv
        return (
            self._data_root
            / "historical"
            / dataset_id.exchange
            / dataset_id.market_type
            / dataset_id.symbol
            / dataset_id.timeframe
            / "ohlcv"
            / "candles.csv"
        )

    async def open_dataset(self, dataset_id: DatasetId) -> DatasetMeta:
        """
        Loads dataset into memory (if not already loaded) and returns metadata.
        """
        key = dataset_id.key()
        async with self._dataset_lock(key):
            cached = self._datasets.get(key)
            if cached is not None:
                meta: DatasetMeta = cached["meta"]  # type: ignore[assignment]
                return meta

            path = self._resolve_path(dataset_id)
            if not path.exists():
                raise FileNotFoundError(f"candles.csv not found: {path}")

            # Parse CSV off-thread
            cols = await asyncio.to_thread(self._load_csv_columns, path)

            ts = cols["ts_ms"]
            if not ts:
                raise ValueError(f"candles.csv is empty: {path}")

            meta = DatasetMeta(
                first_ts_ms=ts[0],
                last_ts_ms=ts[-1],
                count=len(ts),
                path=str(path),
            )

            self._datasets[key] = {
                "meta": meta,
                "cols": cols,
                "loaded_at_ms": int(time.time() * 1000),
            }
            return meta

    def _load_csv_columns(self, path: Path) -> Dict[str, List]:
        """
        Blocking CSV loader. Assumes headers include at least:
          ts_ms, open, high, low, close, volume
        If your store uses different header names, adjust here.
        """
        ts_ms: List[int] = []
        o: List[float] = []
        h: List[float] = []
        l: List[float] = []
        c: List[float] = []
        v: List[float] = []

        with path.open("r", newline="") as f:
            r = csv.DictReader(f)
            required = {"ts_ms", "open", "high", "low", "close", "volume"}
            if r.fieldnames is None or not required.issubset(set(r.fieldnames)):
                raise ValueError(f"Unexpected CSV headers in {path}. Expected {sorted(required)}; got {r.fieldnames}")

            for row in r:
                # Defensive parsing
                ts_ms.append(int(row["ts_ms"]))
                o.append(float(row["open"]))
                h.append(float(row["high"]))
                l.append(float(row["low"]))
                c.append(float(row["close"]))
                v.append(float(row["volume"]))

        # Defensive sort check (ingestion guarantees ascending, but don't trust files blindly)
        if len(ts_ms) >= 2 and ts_ms[0] > ts_ms[-1]:
            # If reversed, sort them. This is slow but safe for v1.
            idxs = sorted(range(len(ts_ms)), key=lambda i: ts_ms[i])
            ts_ms = [ts_ms[i] for i in idxs]
            o = [o[i] for i in idxs]
            h = [h[i] for i in idxs]
            l = [l[i] for i in idxs]
            c = [c[i] for i in idxs]
            v = [v[i] for i in idxs]

        return {"ts_ms": ts_ms, "open": o, "high": h, "low": l, "close": c, "volume": v}

    async def get_slice(self, req: SliceRequest) -> SlicePayload:
        """
        Returns a resident window slice around req.center_ts_ms:
          visible_max + buffer_left + buffer_right (edge-aware).
        """
        # Ensure dataset is loaded
        meta = await self.open_dataset(req.dataset_id)

        key = req.dataset_id.key()
        cols = self._datasets[key]["cols"]  # type: ignore[index]
        ts: List[int] = cols["ts_ms"]  # type: ignore[assignment]

        # Find insertion point for center_ts_ms
        center = req.center_ts_ms
        i = bisect.bisect_left(ts, center)
        if i >= len(ts):
            i = len(ts) - 1
        elif i > 0:
            # pick nearer of i-1, i
            if abs(ts[i - 1] - center) <= abs(ts[i] - center):
                i = i - 1

        visible = max(1, int(req.visible_max))
        bl = max(0, int(req.buffer_left))
        br = max(0, int(req.buffer_right))

        # Target resident counts
        resident_left = bl + (visible // 2)
        resident_right = br + (visible - (visible // 2))

        start = i - resident_left
        end = i + resident_right  # exclusive

        # Edge clamp with expansion to keep resident size if possible
        if start < 0:
            deficit = -start
            start = 0
            end = min(len(ts), end + deficit)
        if end > len(ts):
            deficit = end - len(ts)
            end = len(ts)
            start = max(0, start - deficit)

        # Cache lookup
        cache_key = (key, start, end)
        cached = self._slice_cache.get(cache_key)
        if cached is not None:
            return cached

        # Build slice arrays
        ts_s = ts[start:end]
        o_s = cols["open"][start:end]   # type: ignore[index]
        h_s = cols["high"][start:end]   # type: ignore[index]
        l_s = cols["low"][start:end]    # type: ignore[index]
        c_s = cols["close"][start:end]  # type: ignore[index]
        v_s = cols["volume"][start:end] # type: ignore[index]

        payload = SlicePayload(
            tab_id=req.tab_id,
            request_id=req.request_id,
            dataset_id=req.dataset_id,
            base_index=start,
            ts_ms=list(ts_s),
            open=list(o_s),
            high=list(h_s),
            low=list(l_s),
            close=list(c_s),
            volume=list(v_s),
            has_more_left=(start > 0),
            has_more_right=(end < meta.count),
            first_ts_ms=ts_s[0] if ts_s else meta.first_ts_ms,
            last_ts_ms=ts_s[-1] if ts_s else meta.last_ts_ms,
        )

        self._slice_cache.put(cache_key, payload)
        return payload