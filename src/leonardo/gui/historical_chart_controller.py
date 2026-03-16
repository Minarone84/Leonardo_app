from __future__ import annotations

import uuid
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from leonardo.common.market_types import Candle as GuiCandle
from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import DatasetId, SlicePayload, SliceRequest
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

        # Ensure UI mutations happen on the GUI thread
        self.slice_ready.connect(self._apply_slice)

        # Refill-on-pan / refill-on-zoom trigger
        self._workspace.viewport.viewport_changed.connect(self._on_viewport_changed)

    # ---------------- API ----------------

    def open_dataset(self, exchange: str, market_type: str, symbol: str, timeframe: str) -> None:
        dataset = DatasetId(exchange, market_type, symbol, timeframe)
        self._dataset = dataset
        self._symbol = symbol
        self._timeframe = timeframe

        # Reset per-dataset historical session state
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

    # ---------------- callbacks (may execute off the GUI thread) ----------------

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

        # Initial slice centered at newest candle
        self.request_slice(center_ts_ms=meta.last_ts_ms, reason="initial")

    def _on_slice_ready(self, fut) -> None:
        try:
            payload: SlicePayload = fut.result()
        except Exception as e:
            self._request_in_flight = False
            self.error.emit(f"get_slice failed: {e!r}")
            return

        if payload.request_id != self._latest_request_id:
            return  # stale response

        # Marshal to GUI thread
        self.slice_ready.emit(payload)

    # ---------------- viewport refill trigger (GUI thread) ----------------

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

        # Only the dataset-covered portion of the viewport should participate
        # in refill logic. Future-pad slots to the right are intentional empty
        # space, not missing historical data.
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

        # Pick the center from the real-data portion of the viewport, not from
        # future-pad space.
        if view_end > view_start:
            center_global = view_start + ((view_end - view_start) // 2)
        else:
            # Degenerate case: viewport is entirely outside real data on the right.
            center_global = self._dataset_count - 1

        center_global = max(0, min(center_global, self._dataset_count - 1))

        # IMPORTANT:
        # Do NOT clamp center_global back into the current resident slice.
        # That makes refills chase the old slice instead of following the
        # viewport's actual global target during historical navigation.
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

    # ---------------- apply (GUI thread) ----------------

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

            # Ensure volume pane is visible for historical charts
            self._workspace.set_volume_enabled(True)

            # Initial load only: show the latest default window.
            if not self._initial_view_applied:
                self._set_viewport_to_latest(visible_target=self.DEFAULT_VISIBLE_BARS)
                self._initial_view_applied = True
        finally:
            self._suppress_viewport_refill = False
            self._request_in_flight = False

        # Follow-up boundary/coverage check:
        # if zoom/pan still leaves us close to or beyond resident coverage,
        # request the next slice immediately.
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