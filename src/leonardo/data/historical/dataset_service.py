from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict
import bisect
import time

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.paths import (
    HistoricalPaths,
    storage_segment_to_timeframe,
    timeframe_to_storage_segment,
)
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.naming import MarketId


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


LOADABLE_OHLCV_VALIDATION_STATUSES: frozenset[str] = frozenset({"ok", "modified"})
BLOCKED_OHLCV_VALIDATION_STATUSES: frozenset[str] = frozenset(
    {"unknown", "not_validated", "warning", "error"}
)


@dataclass(frozen=True)
class DatasetLoadability:
    dataset_id: DatasetId
    loadable: bool
    validation_status: str
    reason: str
    csv_path: str
    metadata_path: str


def is_ohlcv_dataset_loadable(validation_status: str | None) -> bool:
    """Return whether a metadata validation status is accepted for chart loading."""
    return str(validation_status or "").strip().lower() in LOADABLE_OHLCV_VALIDATION_STATUSES


def evaluate_ohlcv_dataset_loadability(
    *,
    historical_root: Path,
    market: MarketId,
) -> DatasetLoadability:
    """Evaluate whether an OHLCV dataset is accepted for data-layer loading.

    The acceptance boundary is the persisted OHLCV metadata sidecar. Download
    preliminary validation is not sufficient: the validation status must be
    ``ok`` or ``modified`` and the stored validation fingerprint must still
    match the current CSV.
    """
    dataset_id = DatasetId(
        exchange=_safe_historical_segment(market.exchange, label="exchange"),
        market_type=_safe_historical_segment(market.market_type, label="market_type"),
        symbol=_safe_historical_segment(market.symbol, label="symbol"),
        timeframe=_safe_historical_segment(market.timeframe, label="timeframe"),
    )
    paths = HistoricalPaths(root=Path(historical_root))
    store = CsvOHLCVStore()
    csv_path = store.file_path(paths.ohlcv_dir(market))
    metadata_path = metadata_path_for_csv(csv_path)

    def blocked(status: str, reason: str) -> DatasetLoadability:
        return DatasetLoadability(
            dataset_id=dataset_id,
            loadable=False,
            validation_status=status,
            reason=reason,
            csv_path=str(csv_path),
            metadata_path=str(metadata_path),
        )

    if not csv_path.is_file():
        return blocked("unknown", "OHLCV candles.csv is missing.")
    if not metadata_path.is_file():
        return blocked(
            "unknown",
            "This OHLCV dataset has no metadata sidecar. Open Historical \u2192 OHLCV Maintenance to rebuild metadata and validate it.",
        )

    local_state = store.inspect(csv_path, market=market, repair_metadata=False)
    if not local_state.metadata_valid:
        issue_text = "; ".join(local_state.issues) if local_state.issues else "metadata could not be validated"
        return blocked(
            "unknown",
            f"This OHLCV dataset metadata is missing, unreadable, mismatched, or stale: {issue_text}. Open Historical \u2192 OHLCV Maintenance to inspect it.",
        )

    manifest = _load_historical_manifest(metadata_path)
    if manifest is None:
        return blocked(
            "unknown",
            "This OHLCV dataset metadata is unreadable. Open Historical \u2192 OHLCV Maintenance to rebuild metadata and validate it.",
        )

    validation_status = str(manifest.validation.status or "unknown").strip().lower()
    if not is_ohlcv_dataset_loadable(validation_status):
        return blocked(
            validation_status,
            blocked_ohlcv_validation_reason(validation_status),
        )

    current_fingerprint = store.file_fingerprint(csv_path)
    validation_fingerprint = manifest.validation.csv_fingerprint
    if validation_fingerprint.size_bytes != current_fingerprint.size_bytes:
        return blocked(
            "unknown",
            "This OHLCV dataset changed after validation. Re-run validation in OHLCV Maintenance.",
        )
    if validation_fingerprint.modified_at_ms != current_fingerprint.modified_at_ms:
        return blocked(
            "unknown",
            "This OHLCV dataset changed after validation. Re-run validation in OHLCV Maintenance.",
        )

    reason = (
        "Modified: valid after documented source correction."
        if validation_status == "modified"
        else "Dataset is manually validated and loadable."
    )
    return DatasetLoadability(
        dataset_id=dataset_id,
        loadable=True,
        validation_status=validation_status,
        reason=reason,
        csv_path=str(csv_path),
        metadata_path=str(metadata_path),
    )


def require_ohlcv_dataset_loadable(
    *,
    historical_root: Path,
    market: MarketId,
    context: str,
) -> DatasetLoadability:
    """Return loadability or raise when an OHLCV dataset is not accepted."""
    loadability = evaluate_ohlcv_dataset_loadability(
        historical_root=historical_root,
        market=market,
    )
    if not loadability.loadable:
        raise PermissionError(
            format_ohlcv_loadability_error(loadability, context=context)
        )
    return loadability


def format_ohlcv_loadability_error(
    loadability: DatasetLoadability,
    *,
    context: str,
) -> str:
    """Format a user-actionable data-layer loadability failure."""
    dataset_id = loadability.dataset_id
    identity = (
        f"{dataset_id.exchange} / {dataset_id.market_type} / "
        f"{dataset_id.symbol} / {dataset_id.timeframe}"
    )
    status = str(loadability.validation_status or "unknown").strip().lower() or "unknown"
    context_text = f" for {context}" if str(context or "").strip() else ""
    return (
        f"OHLCV dataset {identity} is not loadable{context_text}: "
        f"validation.status is {status}. {loadability.reason} "
        "Open Historical \u2192 OHLCV Maintenance to analyze, repair, or source-correct this dataset before using it in Data Manager."
    )


def blocked_ohlcv_validation_reason(validation_status: str) -> str:
    """Return the standard reason for an unaccepted OHLCV validation status."""
    status = str(validation_status or "unknown").strip().lower()
    if status in {"unknown", "not_validated"}:
        return (
            "This OHLCV dataset has not been manually validated. "
            "Open Historical \u2192 OHLCV Maintenance and run Analyze Checked."
        )
    if status == "error":
        return (
            "This OHLCV dataset failed validation. "
            "Open Historical \u2192 OHLCV Maintenance to repair or source-correct it."
        )
    if status == "warning":
        return (
            "This OHLCV dataset has validation warnings and is blocked until a loading policy is approved. "
            "Open Historical \u2192 OHLCV Maintenance to review it."
        )
    return (
        "This OHLCV dataset is not accepted for chart loading. "
        "Open Historical \u2192 OHLCV Maintenance to inspect it."
    )


def _load_historical_manifest(metadata_path: Path) -> HistoricalCsvArtifactManifest | None:
    try:
        with Path(metadata_path).open("r", encoding="utf-8") as handle:
            return HistoricalCsvArtifactManifest.from_dict(json.load(handle))
    except Exception:
        return None


def _safe_historical_segment(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"Invalid historical dataset {label}: {value!r}")
    return text


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


REQUIRED_OHLCV_COLUMNS: Tuple[str, str, str, str, str, str] = (
    "ts_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


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

    def invalidate_dataset(self, dataset_key: Tuple[str, str, str, str]) -> int:
        keys = [key for key in self._d if key[0] == dataset_key]
        for key in keys:
            self._d.pop(key, None)
        return len(keys)

    def clear(self) -> int:
        count = len(self._d)
        self._d.clear()
        return count


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


    def _catalog_root(self) -> Path:
        """Return the historical dataset catalog root owned by this service."""
        return self._data_root / "historical"

    @staticmethod
    def _safe_catalog_segment(value: str, *, label: str) -> str:
        """Normalize one catalog path segment and reject traversal-like input."""
        return _safe_historical_segment(value, label=label)

    @staticmethod
    def _list_child_directories(path: Path) -> List[str]:
        if not path.exists() or not path.is_dir():
            return []
        return sorted(
            [child.name for child in path.iterdir() if child.is_dir()],
            key=str.lower,
        )

    @staticmethod
    def _partition_has_candles_file(partition_path: Path) -> bool:
        return (partition_path / "ohlcv" / "candles.csv").is_file()

    def dataset_loadability(self, dataset_id: DatasetId) -> DatasetLoadability:
        """Return whether one OHLCV dataset is accepted for chart loading.

        The chart loader accepts only explicitly validated datasets whose
        validation fingerprint still matches the current CSV. Download-time
        preliminary validation is intentionally ignored here; the persisted
        metadata validation block is the acceptance boundary.
        """
        self._safe_catalog_segment(dataset_id.exchange, label="exchange")
        self._safe_catalog_segment(dataset_id.market_type, label="market_type")
        self._safe_catalog_segment(dataset_id.symbol, label="symbol")
        self._safe_catalog_segment(dataset_id.timeframe, label="timeframe")

        market = MarketId(
            exchange=dataset_id.exchange,
            market_type=dataset_id.market_type,
            symbol=dataset_id.symbol,
            timeframe=dataset_id.timeframe,
        )
        return evaluate_ohlcv_dataset_loadability(
            historical_root=self._catalog_root(),
            market=market,
        )

    def list_dataset_exchanges(self) -> List[str]:
        """Return exchanges with at least one strict OHLCV dataset.

        This is the Core/data-owned dataset catalog surface for GUI selection.
        The GUI must consume this API instead of walking storage folders itself.
        """
        root = self._catalog_root()
        exchanges: List[str] = []
        for exchange_name in self._list_child_directories(root):
            if self.list_dataset_market_types(exchange_name):
                exchanges.append(exchange_name)
        return exchanges

    def list_dataset_market_types(self, exchange: str) -> List[str]:
        """Return market types with at least one strict OHLCV dataset."""
        exchange_name = self._safe_catalog_segment(exchange, label="exchange")
        exchange_path = self._catalog_root() / exchange_name
        market_types: List[str] = []
        for market_type_name in self._list_child_directories(exchange_path):
            if self.list_dataset_symbols(exchange_name, market_type_name):
                market_types.append(market_type_name)
        return market_types

    def list_dataset_symbols(self, exchange: str, market_type: str) -> List[str]:
        """Return symbols/assets with at least one strict OHLCV dataset."""
        exchange_name = self._safe_catalog_segment(exchange, label="exchange")
        market_type_name = self._safe_catalog_segment(market_type, label="market_type")
        symbol_root = self._catalog_root() / exchange_name / market_type_name
        symbols: List[str] = []
        for symbol_name in self._list_child_directories(symbol_root):
            if self.list_dataset_timeframes(exchange_name, market_type_name, symbol_name):
                symbols.append(symbol_name)
        return symbols

    def list_dataset_timeframes(self, exchange: str, market_type: str, symbol: str) -> List[str]:
        """Return timeframes whose partition contains strict ``ohlcv/candles.csv``."""
        return self._list_dataset_timeframes(exchange, market_type, symbol, loadable_only=False)

    def list_loadable_dataset_exchanges(self) -> List[str]:
        """Return exchanges with at least one accepted OHLCV dataset."""
        root = self._catalog_root()
        exchanges: List[str] = []
        for exchange_name in self._list_child_directories(root):
            if self.list_loadable_dataset_market_types(exchange_name):
                exchanges.append(exchange_name)
        return exchanges

    def list_loadable_dataset_market_types(self, exchange: str) -> List[str]:
        """Return market types with at least one accepted OHLCV dataset."""
        exchange_name = self._safe_catalog_segment(exchange, label="exchange")
        exchange_path = self._catalog_root() / exchange_name
        market_types: List[str] = []
        for market_type_name in self._list_child_directories(exchange_path):
            if self.list_loadable_dataset_symbols(exchange_name, market_type_name):
                market_types.append(market_type_name)
        return market_types

    def list_loadable_dataset_symbols(self, exchange: str, market_type: str) -> List[str]:
        """Return symbols/assets with at least one accepted OHLCV dataset."""
        exchange_name = self._safe_catalog_segment(exchange, label="exchange")
        market_type_name = self._safe_catalog_segment(market_type, label="market_type")
        symbol_root = self._catalog_root() / exchange_name / market_type_name
        symbols: List[str] = []
        for symbol_name in self._list_child_directories(symbol_root):
            if self.list_loadable_dataset_timeframes(exchange_name, market_type_name, symbol_name):
                symbols.append(symbol_name)
        return symbols

    def list_loadable_dataset_timeframes(self, exchange: str, market_type: str, symbol: str) -> List[str]:
        """Return accepted timeframes whose OHLCV metadata permits chart loading."""
        return self._list_dataset_timeframes(exchange, market_type, symbol, loadable_only=True)

    def _list_dataset_timeframes(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        *,
        loadable_only: bool,
    ) -> List[str]:
        exchange_name = self._safe_catalog_segment(exchange, label="exchange")
        market_type_name = self._safe_catalog_segment(market_type, label="market_type")
        symbol_name = self._safe_catalog_segment(symbol, label="symbol")
        asset_path = self._catalog_root() / exchange_name / market_type_name / symbol_name

        timeframes: List[str] = []
        seen_timeframes: set[str] = set()
        for timeframe_name in self._list_child_directories(asset_path):
            storage_segment = self._safe_catalog_segment(timeframe_name, label="timeframe")
            try:
                timeframe = storage_segment_to_timeframe(storage_segment)
            except ValueError:
                timeframe = storage_segment
            partition_path = asset_path / storage_segment
            dataset_id = DatasetId(
                exchange=exchange_name,
                market_type=market_type_name,
                symbol=symbol_name,
                timeframe=timeframe,
            )
            if self._partition_has_candles_file(partition_path) and (
                not loadable_only or self.dataset_loadability(dataset_id).loadable
            ):
                if timeframe not in seen_timeframes:
                    seen_timeframes.add(timeframe)
                    timeframes.append(timeframe)
        return timeframes

    def has_dataset(self, dataset_id: DatasetId) -> bool:
        """Return whether a dataset has the strict OHLCV value file expected by Core."""
        self._safe_catalog_segment(dataset_id.exchange, label="exchange")
        self._safe_catalog_segment(dataset_id.market_type, label="market_type")
        self._safe_catalog_segment(dataset_id.symbol, label="symbol")
        self._safe_catalog_segment(dataset_id.timeframe, label="timeframe")
        return self._resolve_path(dataset_id).is_file()

    def _resolve_path(self, dataset_id: DatasetId) -> Path:
        # Expected structure:
        # data/historical/{exchange}/{market_type}/{symbol}/{timeframe_segment}/ohlcv/candles.csv
        timeframe_segment = timeframe_to_storage_segment(dataset_id.timeframe)
        return (
            self._data_root
            / "historical"
            / dataset_id.exchange
            / dataset_id.market_type
            / dataset_id.symbol
            / timeframe_segment
            / "ohlcv"
            / "candles.csv"
        )

    def list_dataset_ids(self) -> List[DatasetId]:
        """Return all strict OHLCV dataset identities in catalog order."""
        datasets: List[DatasetId] = []
        for exchange_name in self.list_dataset_exchanges():
            for market_type_name in self.list_dataset_market_types(exchange_name):
                for symbol_name in self.list_dataset_symbols(exchange_name, market_type_name):
                    for timeframe_name in self.list_dataset_timeframes(
                        exchange_name,
                        market_type_name,
                        symbol_name,
                    ):
                        datasets.append(
                            DatasetId(
                                exchange=exchange_name,
                                market_type=market_type_name,
                                symbol=symbol_name,
                                timeframe=timeframe_name,
                            )
                        )
        return datasets

    def list_loadable_dataset_loadabilities(self) -> List[DatasetLoadability]:
        """Return accepted OHLCV dataset loadability reports in catalog order."""
        loadabilities: List[DatasetLoadability] = []
        for dataset_id in self.list_dataset_ids():
            loadability = self.dataset_loadability(dataset_id)
            if loadability.loadable:
                loadabilities.append(loadability)
        return loadabilities

    def dataset_exists(self, dataset_id: DatasetId) -> bool:
        """Compatibility alias for the strict dataset-catalog validation API."""
        return self.has_dataset(dataset_id)

    def invalidate_dataset_cache(self, dataset_id: DatasetId) -> bool:
        """Remove loaded and sliced cache entries for one dataset identity."""
        key = dataset_id.key()
        removed_loaded = self._datasets.pop(key, None) is not None
        removed_slices = self._slice_cache.invalidate_dataset(key)
        return removed_loaded or removed_slices > 0

    def invalidate_all_dataset_caches(self) -> int:
        """Clear all loaded datasets and all resident slice-cache entries."""
        count = len(self._datasets)
        self._datasets.clear()
        count += self._slice_cache.clear()
        return count

    async def open_dataset(self, dataset_id: DatasetId) -> DatasetMeta:
        """
        Loads dataset into memory (if not already loaded) and returns metadata.
        """
        key = dataset_id.key()
        async with self._dataset_lock(key):
            loadability = self.dataset_loadability(dataset_id)
            if not loadability.loadable:
                raise PermissionError(
                    "Historical OHLCV dataset is not accepted for chart loading: "
                    f"{loadability.reason}"
                )

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
            required = set(REQUIRED_OHLCV_COLUMNS)
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

    def _loaded_dataset_entry(self, dataset_id: DatasetId) -> Dict[str, object]:
        """Return the loaded in-memory entry for one dataset.

        HistoricalDatasetService is an async loading service. Public read
        helpers below intentionally expose already-opened dataset truth without
        making callers reach into ``_datasets``. Callers that need to guarantee
        loading should call/await ``open_dataset(...)`` first.
        """
        key = dataset_id.key()
        entry = self._datasets.get(key)
        if entry is None:
            raise RuntimeError(
                "Historical dataset is not loaded. Call open_dataset(dataset_id) "
                "before requesting timeline, columns, or dataframe access."
            )
        return entry

    def get_timeline_ts_ms(self, dataset_id: DatasetId) -> List[int]:
        """Return a defensive copy of the canonical loaded dataset timeline.

        This is the explicit controller-facing timeline API. It replaces
        downstream compatibility probing and private ``_datasets`` reach-through.
        """
        entry = self._loaded_dataset_entry(dataset_id)
        cols = entry.get("cols")
        if not isinstance(cols, dict):
            raise RuntimeError("Loaded historical dataset entry is missing column storage.")

        raw_ts = cols.get("ts_ms")
        if raw_ts is None:
            raise RuntimeError("Loaded historical dataset columns are missing 'ts_ms'.")

        return [int(ts) for ts in list(raw_ts)]

    def get_dataset_columns(self, dataset_id: DatasetId) -> Dict[str, List]:
        """Return defensive copies of the loaded OHLCV columns.

        The returned mapping is intentionally detached from the service cache so
        controller/dataframe normalization cannot mutate Core-owned storage.
        """
        entry = self._loaded_dataset_entry(dataset_id)
        cols = entry.get("cols")
        if not isinstance(cols, dict):
            raise RuntimeError("Loaded historical dataset entry is missing column storage.")

        missing = [name for name in REQUIRED_OHLCV_COLUMNS if name not in cols]
        if missing:
            raise RuntimeError(
                "Loaded historical dataset columns are missing required values: "
                f"{missing}"
            )

        return {
            name: list(cols[name])
            for name in REQUIRED_OHLCV_COLUMNS
        }

    def get_full_dataframe(self, dataset_id: DatasetId) -> pd.DataFrame:
        """Return the full loaded OHLCV dataset as a detached DataFrame.

        Historical chart apply/save paths consume this API as the explicit Core
        boundary for full-dataset compute truth. The controller remains
        responsible for downstream numeric/timeline validation before compute.
        """
        return pd.DataFrame(self.get_dataset_columns(dataset_id))

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
            # Cached slice data is reusable across requests, but request-
            # scoped envelope identity must be refreshed for the current call.
            return replace(
                cached,
                tab_id=req.tab_id,
                request_id=req.request_id,
            )

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
