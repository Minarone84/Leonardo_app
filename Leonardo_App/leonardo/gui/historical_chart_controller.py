from __future__ import annotations

import uuid
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from leonardo.common.market_types import Candle as GuiCandle
from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import DatasetId, SliceRequest, SlicePayload
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.workspace import ChartWorkspaceWidget


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

        # Historical session state (Phase 1 groundwork)
        self._dataset_count: Optional[int] = None
        self._resident_base_index: int = 0
        self._resident_size: int = 0
        self._has_more_left: bool = False
        self._has_more_right: bool = False
        self._initial_view_applied: bool = False
        self._request_in_flight: bool = False
        self._suppress_viewport_refill: bool = False

        # Vieport/slice policy constants
        self._VISIBLE_TARGET = 500
        self._BUFFER_LEFT = 250
        self._BUFFER_RIGHT = 250
        
        # Ensure UI mutations happen on the GUI thread
        self.slice_ready.connect(self._apply_slice)

        # Refill-on-pan trigger
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
            visible_max=self._VISIBLE_TARGET,
            buffer_left=self._BUFFER_LEFT,
            buffer_right=self._BUFFER_RIGHT,
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

        # Preserve dataset-global size for Phase 1 stabilization
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

        # Marshal to GUI thread (prevents Qt cross-thread parenting)
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
        start = int(vp.start)
        end = int(vp.end)
        visible = max(1, int(vp.visible))

        resident_left = self._resident_base_index
        resident_right_exclusive = self._resident_base_index + self._resident_size

        left_margin = start - resident_left
        right_margin = resident_right_exclusive - end

        side_buffer = min(self._BUFFER_LEFT, self._BUFFER_RIGHT)
        refill_threshold = max(50, min(side_buffer // 3, 100))

        need_left = self._has_more_left and left_margin <= refill_threshold
        need_right = self._has_more_right and right_margin <= refill_threshold

        if not need_left and not need_right:
            return

        center_global = start + (visible // 2)
        center_global = max(0, min(center_global, self._dataset_count - 1))

        # Clamp to current resident slice so timestamp lookup always uses a resident candle.
        resident_right_inclusive = resident_right_exclusive - 1
        center_global = max(resident_left, min(center_global, resident_right_inclusive))

        center_ts_ms = self._global_index_to_ts_ms(center_global)
        if center_ts_ms is None:
            return

        reason = "refill-left" if need_left and not need_right else (
            "refill-right" if need_right and not need_left else "refill-both"
        )
        self.request_slice(center_ts_ms=center_ts_ms, reason=reason)

    def _global_index_to_ts_ms(self, global_index: int) -> Optional[int]:
        local = global_index - self._resident_base_index
        candles = self._workspace.model.candles
        if 0 <= local < len(candles):
            try:
                return int(candles[local].ts_ms)
            except Exception:
                return None
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

            self._workspace.set_volume_enabled(True)

            if not self._initial_view_applied:
                self._set_viewport_to_latest(visible_target=self._VISIBLE_TARGET)
                self._initial_view_applied = True
        finally:
            self._suppress_viewport_refill = False
            self._request_in_flight = False

        # Follow-up boundary check:
        # if the viewport is still pressing a slice edge after apply,
        # let the controller request the next refill immediately.
        self._on_viewport_changed()

    def _set_viewport_to_latest(self, *, visible_target: int) -> None:
        vp = self._workspace.viewport
        total = self._dataset_count if self._dataset_count is not None else len(self._workspace.model.candles)
        if total <= 0:
            return

        visible = min(int(visible_target), int(total))
        start = max(0, int(total) - visible)
        end = int(total)

        # Prefer explicit API if present
        if hasattr(vp, "set_window"):
            vp.set_window(start, end)  # type: ignore[attr-defined]
        elif hasattr(vp, "set_range"):
            vp.set_range(start, end)  # type: ignore[attr-defined]
        else:
            # fallback
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