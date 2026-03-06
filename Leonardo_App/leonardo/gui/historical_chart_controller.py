from __future__ import annotations

import uuid
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from leonardo.common.market_types import Candle as GuiCandle, ChartSnapshot
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

        # Ensure UI mutations happen on the GUI thread
        self.slice_ready.connect(self._apply_slice)

    # ---------------- API ----------------

    def open_dataset(self, exchange: str, market_type: str, symbol: str, timeframe: str) -> None:
        dataset = DatasetId(exchange, market_type, symbol, timeframe)
        self._dataset = dataset
        self._symbol = symbol
        self._timeframe = timeframe

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

        req = SliceRequest(
            tab_id="historical-tab",
            request_id=request_id,
            dataset_id=self._dataset,
            center_ts_ms=center_ts_ms,
            visible_max=1000,
            buffer_left=500,
            buffer_right=500,
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

        # Initial slice centered at newest candle
        self.request_slice(center_ts_ms=meta.last_ts_ms, reason="initial")

    def _on_slice_ready(self, fut) -> None:
        try:
            payload: SlicePayload = fut.result()
        except Exception as e:
            self.error.emit(f"get_slice failed: {e!r}")
            return

        if payload.request_id != self._latest_request_id:
            return  # stale response

        # Marshal to GUI thread (prevents Qt cross-thread parenting)
        self.slice_ready.emit(payload)

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

        snap = ChartSnapshot(
            symbol=self._symbol,
            timeframe=self._timeframe,  # Literal type, but we pass canonical strings already
            candles=candles,
        )
        self._workspace.apply_snapshot(snap)

        # Ensure volume pane is visible for historical charts
        self._workspace.set_volume_enabled(True)

        # Best-effort: show the latest ~1000 bars
        self._set_viewport_to_latest(visible_target=1000)

    def _set_viewport_to_latest(self, *, visible_target: int) -> None:
        vp = self._workspace.viewport
        n = len(self._workspace.model.candles)
        if n <= 0:
            return

        visible = min(int(visible_target), n)
        start = max(0, n - visible)
        end = n

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