from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot

from leonardo.common.market_types import Candle as GuiCandle
from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import DatasetId, SlicePayload, SliceRequest
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import default_historical_root
from leonardo.data.naming import canonicalize
from leonardo.financial_tools.indicators.indicators import Indicators, IndicatorRequest
from leonardo.financial_tools.oscillators.oscillators import Oscillators, OscillatorRequest
from leonardo.gui.chart.model import Series as ChartSeries
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.core_bridge import CoreBridge


class HistoricalChartController(QObject):
    """
    GUI-thread controller.
    Talks to Core via CoreBridge.submit(coro) and receives results via callbacks.

    IMPORTANT:
    concurrent.futures.Future callbacks may execute on the CORE thread.
    Therefore we must marshal payload application back to the GUI thread.
    """

    error = Signal(str)
    slice_ready = Signal(object)  # SlicePayload

    apply_succeeded = Signal(dict)
    save_succeeded = Signal(dict)
    save_failed = Signal(dict)

    # Historical horizontal policy (same for all timeframes)
    DEFAULT_VISIBLE_BARS = 500
    MAX_VISIBLE_BARS = 2000
    RESIDENT_TARGET_BARS = 3000

    # Dataset-service request policy derived from the above:
    # 2000 visible max + 500 left buffer + 500 right buffer = 3000 resident target
    REQUEST_VISIBLE_MAX = MAX_VISIBLE_BARS
    REQUEST_BUFFER_LEFT = (RESIDENT_TARGET_BARS - MAX_VISIBLE_BARS) // 2
    REQUEST_BUFFER_RIGHT = (RESIDENT_TARGET_BARS - MAX_VISIBLE_BARS) // 2

    # Refill threshold: start refilling when about half a side buffer is consumed.
    REFILL_THRESHOLD = min(250, REQUEST_BUFFER_LEFT)

    def __init__(
        self,
        *,
        core_bridge: CoreBridge,
        workspace: ChartWorkspaceWidget,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._core = core_bridge
        self._workspace = workspace

        self._dataset: Optional[DatasetId] = None
        self._symbol: str = ""
        self._timeframe: str = ""
        self._exchange: str = ""
        self._market_type: str = ""

        self._latest_request_id: Optional[str] = None

        # Historical session state
        self._dataset_count: Optional[int] = None
        self._resident_base_index: int = 0
        self._resident_size: int = 0
        self._has_more_left: bool = False
        self._has_more_right: bool = False
        self._initial_view_applied: bool = False
        self._request_in_flight: bool = False
        self._suppress_viewport_refill: bool = False

        self.slice_ready.connect(self._apply_slice)
        self._workspace.viewport.viewport_changed.connect(self._on_viewport_changed)

    # ---------------- API ----------------

    def open_dataset(self, exchange: str, market_type: str, symbol: str, timeframe: str) -> None:
        dataset = DatasetId(exchange, market_type, symbol, timeframe)
        self._dataset = dataset
        self._exchange = exchange
        self._market_type = market_type
        self._symbol = symbol
        self._timeframe = timeframe

        self._dataset_count = None
        self._resident_base_index = 0
        self._resident_size = 0
        self._has_more_left = False
        self._has_more_right = False
        self._initial_view_applied = False
        self._request_in_flight = False
        self._suppress_viewport_refill = False

        svc = self._core.context.registry.get(SVC_HISTORICAL_DATASET)
        if svc is None:
            self.error.emit("HistoricalDatasetService not found in ctx.registry")
            return

        fut = self._core.submit(svc.open_dataset(dataset))
        fut.add_done_callback(self._on_dataset_opened)

    def request_slice(self, *, center_ts_ms: int, reason: str) -> None:
        if self._dataset is None:
            return

        svc = self._core.context.registry.get(SVC_HISTORICAL_DATASET)
        if svc is None:
            self.error.emit("HistoricalDatasetService not found in ctx.registry")
            return

        request_id = uuid.uuid4().hex
        self._latest_request_id = request_id
        self._request_in_flight = True

        req = SliceRequest(
            tab_id="historical-tab",
            request_id=request_id,
            dataset_id=self._dataset,
            center_ts_ms=center_ts_ms,
            visible_max=self.REQUEST_VISIBLE_MAX,
            buffer_left=self.REQUEST_BUFFER_LEFT,
            buffer_right=self.REQUEST_BUFFER_RIGHT,
            reason=reason,
        )

        fut = self._core.submit(svc.get_slice(req))
        fut.add_done_callback(self._on_slice_ready)

    def apply_financial_tool(self, payload: Dict[str, Any]) -> None:
        """
        Apply a financial tool to the current historical chart.

        IMPORTANT for this phase:
        - Computation uses the current resident candle slice already loaded in memory.
        - It does NOT persist anything to disk.
        - It does NOT yet compute on the full historical dataset on disk.
        """
        if not payload:
            self.error.emit("Empty financial tool payload.")
            return

        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key
        params = payload.get("params", {})

        if not tool_type or not tool_key:
            self.error.emit("Invalid financial tool payload: missing tool_type or tool_key.")
            return

        dcd_df = self._build_resident_dataframe()
        if dcd_df is None or dcd_df.empty:
            self.error.emit("Cannot apply financial tool: no resident historical candles loaded.")
            return

        try:
            if tool_type == "indicator":
                result = Indicators.calculate(
                    IndicatorRequest(name=tool_key, data=dcd_df, params=params)
                )
                self.apply_succeeded.emit(
                    self._build_apply_payload(
                        result,
                        tool_type=tool_type,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        params=params,
                    )
                )
                return

            if tool_type == "oscillator":
                result = Oscillators.calculate(
                    OscillatorRequest(name=tool_key, data=dcd_df, params=params)
                )
                self.apply_succeeded.emit(
                    self._build_apply_payload(
                        result,
                        tool_type=tool_type,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        params=params,
                    )
                )
                return

            if tool_type == "construct":
                self.error.emit("Construct application is not implemented yet.")
                return

            self.error.emit(f"Unsupported financial tool type: {tool_type}")
        except Exception as e:
            self.error.emit(f"apply_financial_tool failed: {e!r}")

    def save_financial_tool(self, payload: Dict[str, Any]) -> None:
        """
        Persist a financial tool result computed on the FULL canonical historical dataset.

        Save semantics are intentionally different from Apply:
        - Apply uses current resident candles for quick display.
        - Save loads the full dataset from disk for analysis-grade persistence.
        """
        if not payload:
            self.error.emit("Empty financial tool payload.")
            return

        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key
        params = payload.get("params", {})

        if not tool_type or not tool_key:
            self.error.emit("Invalid save payload: missing tool_type or tool_key.")
            return

        save_meta: Dict[str, Any] = {
            "tool_type": tool_type,
            "tool_title": tool_title,
            "tool_key": tool_key,
            "exchange": self._exchange,
            "market_type": self._market_type,
            "symbol": self._symbol,
            "timeframe": self._timeframe,
            "params": dict(params),
            "saved_path": "",
            "error": "",
        }

        if tool_type == "construct":
            save_meta["error"] = "Construct saving is not implemented yet."
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            market = canonicalize(
                exchange=self._exchange,
                market_type=self._market_type,
                symbol=self._symbol,
                timeframe=self._timeframe,
            )
        except Exception as e:
            save_meta["error"] = f"Failed to canonicalize market for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            full_df = self._load_full_dataset_dataframe()
        except Exception as e:
            save_meta["error"] = f"Failed to load full historical dataset for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        if full_df.empty:
            save_meta["error"] = "Cannot save financial tool: full historical dataset is empty."
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            if tool_type == "indicator":
                result = Indicators.calculate(
                    IndicatorRequest(name=tool_key, data=full_df, params=params)
                )
                kind = "indicators"
            elif tool_type == "oscillator":
                result = Oscillators.calculate(
                    OscillatorRequest(name=tool_key, data=full_df, params=params)
                )
                kind = "oscillators"
            else:
                save_meta["error"] = f"Unsupported save tool type: {tool_type}"
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return
        except Exception as e:
            save_meta["error"] = f"Failed to compute financial tool for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            result_df = self._result_to_dataframe(result)
            instance_key = self._build_instance_key(params)
            historical_root = default_historical_root()
            store = DerivedCsvStore(historical_root=historical_root)

            path = store.save_dataframe(
                market=market,
                kind=kind,  # type: ignore[arg-type]
                tool_key=tool_key,
                instance_key=instance_key,
                df=result_df,
            )
            save_meta["saved_path"] = str(path)
        except Exception as e:
            save_meta["error"] = f"Failed to persist financial tool: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        self.save_succeeded.emit(save_meta)
        self.error.emit(f"Saved {tool_key} to {path}")

    # ---------------- callbacks ----------------

    def _on_dataset_opened(self, fut) -> None:
        try:
            meta = fut.result()
        except Exception as e:
            self.error.emit(f"open_dataset failed: {e!r}")
            return

        try:
            self._dataset_count = int(meta.count)
        except Exception:
            self._dataset_count = None

        self.request_slice(center_ts_ms=meta.last_ts_ms, reason="initial")

    def _on_slice_ready(self, fut) -> None:
        try:
            payload: SlicePayload = fut.result()
        except Exception as e:
            self._request_in_flight = False
            self.error.emit(f"get_slice failed: {e!r}")
            return

        if payload.request_id != self._latest_request_id:
            return

        self.slice_ready.emit(payload)

    # ---------------- viewport refill trigger ----------------

    @Slot()
    def _on_viewport_changed(self) -> None:
        if self._dataset is None:
            return
        if self._dataset_count is None or self._dataset_count <= 0:
            return
        if self._request_in_flight:
            return
        if self._suppress_viewport_refill:
            return
        if self._resident_size <= 0:
            return
        if not self._initial_view_applied:
            return

        vp = self._workspace.viewport
        raw_start = int(vp.start)
        raw_end = int(vp.end)

        view_start = max(0, min(raw_start, self._dataset_count))
        view_end = max(view_start, min(raw_end, self._dataset_count))

        resident_left = self._resident_base_index
        resident_right_exclusive = self._resident_base_index + self._resident_size

        left_margin = view_start - resident_left
        right_margin = resident_right_exclusive - view_end

        underflow_left = view_start < resident_left
        underflow_right = view_end > resident_right_exclusive

        need_left = self._has_more_left and (underflow_left or left_margin <= self.REFILL_THRESHOLD)
        need_right = self._has_more_right and (underflow_right or right_margin <= self.REFILL_THRESHOLD)

        if not need_left and not need_right:
            return

        if view_end > view_start:
            center_global = view_start + ((view_end - view_start) // 2)
        else:
            center_global = self._dataset_count - 1

        center_global = max(0, min(center_global, self._dataset_count - 1))

        center_ts_ms = self._global_index_to_ts_ms(center_global)
        if center_ts_ms is None:
            return

        reason = "refill-left" if need_left and not need_right else (
            "refill-right" if need_right and not need_left else "refill-both"
        )
        self.request_slice(center_ts_ms=center_ts_ms, reason=reason)

    def _infer_resident_tf_ms(self) -> Optional[int]:
        candles = self._workspace.model.candles
        if len(candles) < 2:
            return None

        try:
            prev_ts = int(candles[-2].ts_ms)
            last_ts = int(candles[-1].ts_ms)
        except Exception:
            return None

        tf_ms = last_ts - prev_ts
        if tf_ms <= 0:
            return None

        return tf_ms

    def _global_index_to_ts_ms(self, global_index: int) -> Optional[int]:
        candles = self._workspace.model.candles
        if not candles:
            return None

        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(candles):
            try:
                return int(candles[local].ts_ms)
            except Exception:
                return None

        tf_ms = self._infer_resident_tf_ms()
        if tf_ms is None:
            return None

        try:
            first_ts = int(candles[0].ts_ms)
            last_local = len(candles) - 1
            last_global = self._resident_base_index + last_local
            last_ts = int(candles[last_local].ts_ms)
        except Exception:
            return None

        if global_index < self._resident_base_index:
            steps = int(global_index) - self._resident_base_index
            return first_ts + (steps * tf_ms)

        if global_index > last_global:
            steps = int(global_index) - last_global
            return last_ts + (steps * tf_ms)

        return None

    # ---------------- financial tool helpers ----------------

    def _build_resident_dataframe(self) -> Optional[pd.DataFrame]:
        candles = self._workspace.model.candles
        if not candles:
            return None

        rows: list[dict[str, Any]] = []
        for c in candles:
            rows.append(
                {
                    "ts_ms": int(c.ts_ms),
                    "time": int(c.ts_ms),
                    "timeframe": self._timeframe,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                    "Volume": float(c.volume),
                }
            )

        return pd.DataFrame(rows)

    def _load_full_dataset_dataframe(self) -> pd.DataFrame:
        if self._dataset is None:
            raise RuntimeError("No historical dataset is currently open.")

        svc = self._core.context.registry.get(SVC_HISTORICAL_DATASET)
        if svc is None:
            raise RuntimeError("HistoricalDatasetService not found in ctx.registry")

        data_root = Path(getattr(svc, "_data_root"))
        candles_path = (
            data_root
            / "historical"
            / self._dataset.exchange
            / self._dataset.market_type
            / self._dataset.symbol
            / self._dataset.timeframe
            / "ohlcv"
            / "candles.csv"
        )

        if not candles_path.exists():
            raise FileNotFoundError(f"Candles CSV not found: {candles_path}")

        df = pd.read_csv(candles_path)
        if df.empty:
            return df

        # Normalize columns for downstream financial tools.
        required_cols = ["ts_ms", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Full candles dataset missing required columns: {missing}")

        out = df.copy()
        out["time"] = out["ts_ms"]
        out["timeframe"] = self._timeframe
        out["Volume"] = out["volume"]
        return out

    def _build_param_signature(self, params: Dict[str, Any]) -> str:
        if not params:
            return "default"

        parts: list[str] = []
        for key in sorted(params.keys()):
            val = params[key]
            parts.append(f"{key}={val}")
        return ",".join(parts)

    def _build_instance_key(self, params: Dict[str, Any]) -> str:
        if not params:
            return "default"

        parts: list[str] = []
        for key in sorted(params.keys()):
            val = str(params[key]).strip().lower()
            val = val.replace(" ", "-")
            val = val.replace("=", "-")
            val = val.replace(",", "-")
            parts.append(f"{key}-{val}")
        return "__".join(parts)

    def _build_series_key(self, *, tool_key: str, params: Dict[str, Any], line_key: str) -> str:
        param_sig = self._build_param_signature(params)
        return f"{tool_key}|{param_sig}|{line_key}"

    def _build_series_title(self, *, tool_title: str, params: Dict[str, Any], line_title: str) -> str:
        param_sig = self._build_param_signature(params)
        return f"{tool_title} [{param_sig}] · {line_title}"

    def _build_apply_payload(
        self,
        result,
        *,
        tool_type: str,
        tool_key: str,
        tool_title: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        series_list: list[ChartSeries] = []

        for line in result.lines:
            values = [float(v) if pd.notna(v) else float("nan") for v in line.values.tolist()]
            series_list.append(
                ChartSeries(
                    key=self._build_series_key(tool_key=tool_key, params=params, line_key=line.key),
                    title=self._build_series_title(tool_title=tool_title, params=params, line_title=line.title),
                    values=values,
                )
            )

        return {
            "tool_type": tool_type,
            "tool_key": tool_key,
            "tool_title": tool_title,
            "display_name": getattr(result, "title", tool_title) or tool_title,
            "params": dict(getattr(result, "params", params) or params),
            "series_list": series_list,
        }

    def _result_to_dataframe(self, result) -> pd.DataFrame:
        df = pd.DataFrame(index=result.index)

        if getattr(result, "time", None) is not None:
            df["time"] = result.time
        if getattr(result, "timeframe", None) is not None:
            df["timeframe"] = result.timeframe

        for line in result.lines:
            series = line.values.reindex(result.index)
            if pd.api.types.is_numeric_dtype(series):
                df[line.key] = series.astype("float32")
            else:
                df[line.key] = series

        if "time" not in df.columns:
            if "ts_ms" in df.columns:
                df["time"] = df["ts_ms"]
            else:
                df["time"] = list(range(len(df)))

        if "timeframe" not in df.columns:
            df["timeframe"] = self._timeframe

        return df.reset_index(drop=True)

    # ---------------- apply historical slice ----------------

    @Slot(object)
    def _apply_slice(self, payload_obj: object) -> None:
        payload: SlicePayload = payload_obj  # type: ignore[assignment]

        candles = [
            GuiCandle(
                ts_ms=ts,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                is_closed=True,
            )
            for ts, o, h, l, c, v in zip(
                payload.ts_ms,
                payload.open,
                payload.high,
                payload.low,
                payload.close,
                payload.volume,
                strict=True,
            )
        ]

        self._resident_base_index = int(getattr(payload, "base_index", 0))
        self._resident_size = len(candles)
        self._has_more_left = bool(getattr(payload, "has_more_left", False))
        self._has_more_right = bool(getattr(payload, "has_more_right", False))

        self._suppress_viewport_refill = True
        try:
            self._workspace.apply_historical_slice(
                symbol=self._symbol,
                timeframe=self._timeframe,
                candles=candles,
                resident_base_index=self._resident_base_index,
                dataset_total=self._dataset_count if self._dataset_count is not None else len(candles),
            )

            self._workspace.set_volume_enabled(True)

            if not self._initial_view_applied:
                self._set_viewport_to_latest(visible_target=self.DEFAULT_VISIBLE_BARS)
                self._initial_view_applied = True
        finally:
            self._suppress_viewport_refill = False
            self._request_in_flight = False

        self._on_viewport_changed()

    def _set_viewport_to_latest(self, *, visible_target: int) -> None:
        vp = self._workspace.viewport
        total = self._dataset_count if self._dataset_count is not None else len(self._workspace.model.candles)
        if total <= 0:
            return

        visible = min(int(visible_target), int(total))
        start = max(0, int(total) - visible)
        end = int(total)

        if hasattr(vp, "set_window"):
            vp.set_window(start, end)  # type: ignore[attr-defined]
        elif hasattr(vp, "set_range"):
            vp.set_range(start, end)  # type: ignore[attr-defined]
        else:
            if hasattr(vp, "start"):
                try:
                    setattr(vp, "start", start)
                except Exception:
                    pass
            if hasattr(vp, "end"):
                try:
                    setattr(vp, "end", end)
                except Exception:
                    pass