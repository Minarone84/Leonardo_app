from __future__ import annotations

import uuid
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from leonardo.common.market_types import Candle as GuiCandle
from leonardo.data.historical.dataset_service import DatasetId, SlicePayload, SliceRequest
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.historical_chart.construct_sources import HistoricalChartConstructSourceMixin
from leonardo.gui.historical_chart.data_access import HistoricalChartDataAccessMixin
from leonardo.gui.historical_chart.projection import HistoricalChartProjectionMixin
from leonardo.gui.historical_chart.refill_policy import HistoricalChartRefillPolicyMixin
from leonardo.gui.historical_chart.session import (
    AppliedStudyProjection,
    ChartDataSession,
    StoredStudyLine,
)
from leonardo.gui.historical_chart.tool_execution import HistoricalChartToolExecutionMixin


__all__ = [
    "StoredStudyLine",
    "AppliedStudyProjection",
    "ChartDataSession",
    "HistoricalChartController",
]


class HistoricalChartController(
    HistoricalChartToolExecutionMixin,
    HistoricalChartProjectionMixin,
    HistoricalChartConstructSourceMixin,
    HistoricalChartDataAccessMixin,
    HistoricalChartRefillPolicyMixin,
    QObject,
):
    """
    GUI-thread historical chart controller.

    Responsibilities
    ----------------
    - Coordinate historical dataset opening and slice requests through CoreBridge.
    - Keep resident-slice session state aligned with the chart workspace.
    - Compute financial tools on the full historical dataset.
    - Convert full-dataset results into resident-local chart series for rendering.
    - Persist full-dataset results for Save operations.

    Threading rule
    --------------
    concurrent.futures.Future callbacks may execute on the Core thread, not on
    the GUI thread. Any UI-affecting application path must therefore be
    marshalled back through Qt signals.

    Architectural rule reinforced here
    ----------------------------------
    Rendering must remain resident-local.

    That means:
    - computation may operate on the full dataset
    - persistence may operate on the full dataset
    - render payloads sent to the chart layer must be trimmed to the current
      resident slice before they become ChartSeries objects

    This controller is therefore the boundary where full-dataset truth is
    converted into resident-local render truth.
    """

    error = Signal(str)
    _dataset_open_result_ready = Signal(object, object, object)  # DatasetId, open_generation, result/error
    _slice_result_ready = Signal(object, object, object)  # request_id, DatasetId, result/error
    _slice_payload_ready = Signal(object)  # SlicePayload (internal GUI-thread marshalling)
    slice_ready = Signal(object)  # SlicePayload already applied to session/workspace
    projected_studies_refreshed = Signal(object)  # list[dict[str, Any]]

    apply_succeeded = Signal(dict)
    save_succeeded = Signal(dict)
    save_failed = Signal(dict)

    # Historical horizontal policy (same for all timeframes)
    DEFAULT_VISIBLE_BARS = 500
    MAX_VISIBLE_BARS = 2000
    RESIDENT_TARGET_BARS = 5000

    # Dataset-service request policy derived from the above:
    # 2000 visible max + 1500 left buffer + 1500 right buffer = 5000 resident target.
    # A larger resident window reduces how often horizontal navigation must
    # trigger a full resident-slice refresh and study reprojection cycle.
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
        self._dataset_open_generation: int = 0

        # Historical chart-session data authority.
        #
        # This centralizes dataset/session truth inside the controller so the
        # viewport and render layers remain downstream consumers rather than
        # accidental owners of chart data state.
        self._session = ChartDataSession()
        self._initial_view_applied: bool = False
        self._request_in_flight: bool = False
        self._suppress_viewport_refill: bool = False
        self._is_disposed: bool = False

        self._dataset_open_result_ready.connect(self._apply_dataset_open_result)
        self._slice_result_ready.connect(self._apply_slice_result)
        self._slice_payload_ready.connect(self._apply_slice)
        self._workspace.viewport.viewport_changed.connect(self._on_viewport_changed)
        self.destroyed.connect(self._on_qobject_destroyed)
        try:
            self._workspace.destroyed.connect(self._on_workspace_destroyed)
        except Exception:
            pass

    def current_input_bar_count(self) -> Optional[int]:
        """
        Return the full input row count known for the active chart session.

        Apply preflight needs an informational count without forcing tool
        calculation or full-dataset loading. The controller session already
        owns canonical dataset length when the chart open path has completed.
        """
        if self._is_disposed:
            return None

        count = self._session.dataset_count
        if count is not None:
            return max(0, int(count))

        cached_df = self._session.full_dataset_df
        if cached_df is not None:
            return int(len(cached_df))

        return None

    def dispose(self) -> None:
        """Stop this controller from applying any further async results.

        The controller owns chart-session data truth and async refill/application
        callbacks. Disposal therefore does not invent new shell or pane
        semantics; it only seals this controller's own callback boundary so late
        results cannot write into a workspace that is closing or already gone.
        """
        if self._is_disposed:
            return

        self._is_disposed = True
        self._dataset_open_generation += 1
        self._latest_request_id = None
        self._request_in_flight = False
        self._suppress_viewport_refill = True

        try:
            self._dataset_open_result_ready.disconnect(self._apply_dataset_open_result)
        except Exception:
            pass

        try:
            self._slice_result_ready.disconnect(self._apply_slice_result)
        except Exception:
            pass

        try:
            self._slice_payload_ready.disconnect(self._apply_slice)
        except Exception:
            pass

        try:
            self._workspace.viewport.viewport_changed.disconnect(self._on_viewport_changed)
        except Exception:
            pass

    @Slot()
    def _on_workspace_destroyed(self) -> None:
        self.dispose()

    @Slot(object)
    def _on_qobject_destroyed(self, _obj: object = None) -> None:
        self._is_disposed = True

    def open_dataset(self, exchange: str, market_type: str, symbol: str, timeframe: str) -> None:
        if self._is_disposed:
            return

        dataset = DatasetId(exchange, market_type, symbol, timeframe)
        self._dataset_open_generation += 1
        open_generation = self._dataset_open_generation
        self._latest_request_id = None
        self._dataset = dataset
        self._exchange = exchange
        self._market_type = market_type
        self._symbol = symbol
        self._timeframe = timeframe

        self._session.reset_for_dataset(dataset)
        self._initial_view_applied = False
        self._request_in_flight = False
        self._suppress_viewport_refill = False

        svc = self._get_historical_dataset_service()
        if svc is None:
            return

        fut = self._core.submit(svc.open_dataset(dataset))
        fut.add_done_callback(
            lambda done_fut, opened_dataset=dataset, generation=open_generation: (
                self._on_dataset_opened(
                    done_fut,
                    dataset=opened_dataset,
                    open_generation=generation,
                )
            )
        )

    def request_slice(self, *, center_ts_ms: int, reason: str) -> None:
        if self._is_disposed:
            return

        if self._dataset is None:
            return

        if self._request_in_flight:
            # The controller is the sole owner of resident-slice refill policy.
            # While one request is in flight, the viewport may still move, but it
            # must not spawn a second resident-truth owner. The latest camera
            # state will be re-evaluated after the active request completes.
            return

        svc = self._get_historical_dataset_service()
        if svc is None:
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

        request_dataset = self._dataset
        fut = self._core.submit(svc.get_slice(req))
        fut.add_done_callback(
            lambda done_fut, issued_request_id=request_id, issued_dataset=request_dataset: (
                self._on_slice_ready(
                    done_fut,
                    request_id=issued_request_id,
                    dataset=issued_dataset,
                )
            )
        )

    def center_view_on_timestamp_ms(self, ts_ms: int) -> bool:
        if self._is_disposed:
            return False

        if self._dataset is None:
            return False

        if not self._session.timeline_ts_ms:
            return False

        index = self._session.nearest_global_index_for_ts_ms(int(ts_ms))
        if index is None:
            self.error.emit("Cannot center chart: the active dataset timeline is empty.")
            return False

        viewport = self._workspace.viewport
        if hasattr(viewport, "center_on_index"):
            viewport.center_on_index(index)  # type: ignore[attr-defined]
            return True

        visible = max(1, int(getattr(viewport, "visible", self.DEFAULT_VISIBLE_BARS)))
        start = int(index) - (visible // 2)
        viewport.set_window(start, start + visible)
        return True

    def current_center_timestamp_ms(self) -> Optional[int]:
        """Return the nearest dataset timestamp at the current viewport center."""
        if self._is_disposed:
            return None

        if self._dataset is None or not self._session.timeline_ts_ms:
            return None

        viewport = self._workspace.viewport
        visible = max(1, int(getattr(viewport, "visible", self.DEFAULT_VISIBLE_BARS)))
        start = int(getattr(viewport, "start", 0))
        center_index = start + (visible // 2)
        center_ts_ms = self._session.global_index_to_ts_ms(center_index)
        if center_ts_ms is not None:
            return int(center_ts_ms)

        clamped_index = max(
            0,
            min(center_index, len(self._session.timeline_ts_ms) - 1),
        )
        return self._session.global_index_to_ts_ms(clamped_index)

    def export_viewport_state(self) -> dict[str, object]:
        """
        Return durable horizontal camera state for workspace snapshot payloads.

        The controller owns the canonical timeline and viewport bridge, so it is
        the boundary that can translate the current chart-space center into a
        durable timestamp. Padding-space centers are clamped to the nearest real
        candle timestamp while preserving a global-index fallback.
        """
        viewport = self._workspace.viewport
        visible = max(1, int(getattr(viewport, "visible", self.DEFAULT_VISIBLE_BARS)))
        start = int(getattr(viewport, "start", 0))
        center_index = start + (visible // 2)
        fallback_global_index = center_index
        center_ts_ms = self._session.global_index_to_ts_ms(center_index)

        if center_ts_ms is None and self._session.timeline_ts_ms:
            clamped_index = max(
                0,
                min(center_index, len(self._session.timeline_ts_ms) - 1),
            )
            fallback_global_index = clamped_index
            center_ts_ms = self._session.global_index_to_ts_ms(clamped_index)

        return {
            "center_ts_ms": center_ts_ms,
            "visible_bars": visible,
            "fallback_global_index": fallback_global_index,
        }

    def _on_dataset_opened(
        self,
        fut,
        *,
        dataset: DatasetId,
        open_generation: int,
    ) -> None:
        """Collect one Core dataset-open result and marshal it to the GUI thread."""
        if self._is_disposed:
            return

        try:
            result = fut.result()
        except BaseException as e:
            result = e

        self._dataset_open_result_ready.emit(dataset, int(open_generation), result)

    @Slot(object, object, object)
    def _apply_dataset_open_result(
        self,
        dataset_obj: object,
        open_generation_obj: object,
        result_obj: object,
    ) -> None:
        """Apply one opened-dataset result after Qt GUI-thread marshalling.

        Future callbacks may run on the Core thread.  This slot is the only
        place where an open result is allowed to mutate controller/session
        state.  The generation and dataset guards prevent a late result from an
        older open request from priming timeline truth or requesting an initial
        slice for the active chart session.
        """
        if self._is_disposed:
            return

        if not isinstance(dataset_obj, DatasetId):
            return

        try:
            open_generation = int(open_generation_obj)
        except Exception:
            return

        if open_generation != self._dataset_open_generation:
            return

        if self._dataset is None or dataset_obj != self._dataset:
            return

        if self._session.dataset_id is not None and dataset_obj != self._session.dataset_id:
            return

        if isinstance(result_obj, BaseException):
            self.error.emit(f"open_dataset failed: {result_obj!r}")
            return

        meta = result_obj

        try:
            self._session.set_dataset_count(int(getattr(meta, "count")))
        except Exception:
            self._session.set_dataset_count(None)

        svc = self._get_historical_dataset_service()
        if svc is None:
            return

        try:
            self._populate_session_truth_from_service(svc)
        except Exception as e:
            self.error.emit(f"Failed to prime canonical chart-session timeline: {e!r}")
            return

        if open_generation != self._dataset_open_generation:
            return

        if self._dataset is None or dataset_obj != self._dataset:
            return

        if self._session.dataset_id is not None and dataset_obj != self._session.dataset_id:
            return

        try:
            center_ts_ms = int(getattr(meta, "last_ts_ms"))
        except Exception as e:
            self.error.emit(f"Historical dataset metadata did not expose last_ts_ms: {e!r}")
            return

        self.request_slice(center_ts_ms=center_ts_ms, reason="initial")

    def _on_slice_ready(
        self,
        fut,
        *,
        request_id: str,
        dataset: DatasetId,
    ) -> None:
        """Collect one Core slice result and marshal it to the GUI thread."""
        if self._is_disposed:
            return

        try:
            result = fut.result()
        except BaseException as e:
            result = e

        self._slice_result_ready.emit(str(request_id), dataset, result)

    @Slot(object, object, object)
    def _apply_slice_result(
        self,
        request_id_obj: object,
        dataset_obj: object,
        result_obj: object,
    ) -> None:
        """Apply one slice result after Qt GUI-thread marshalling.

        Stale slice results must not mutate request flags for a newer active
        request.  The request-id and dataset guards therefore run before any
        session state is changed or errors are surfaced.
        """
        if self._is_disposed:
            return

        request_id = str(request_id_obj or "")
        if not request_id or request_id != self._latest_request_id:
            return

        if not isinstance(dataset_obj, DatasetId):
            return

        if self._dataset is None or dataset_obj != self._dataset:
            return

        if self._session.dataset_id is not None and dataset_obj != self._session.dataset_id:
            return

        if isinstance(result_obj, BaseException):
            self._request_in_flight = False
            self.error.emit(f"get_slice failed: {result_obj!r}")
            self._on_viewport_changed()
            return

        payload: SlicePayload = result_obj  # type: ignore[assignment]
        if payload.request_id != self._latest_request_id:
            self._request_in_flight = False
            self._on_viewport_changed()
            return

        self._slice_payload_ready.emit(payload)

    @Slot()
    def _on_viewport_changed(self) -> None:
        if self._is_disposed:
            return

        if not self._should_consider_refill():
            return

        need_left, need_right, view_start, view_end = self._evaluate_refill_pressure()
        if not need_left and not need_right:
            return

        center_global = self._refill_center_global_index(
            view_start=view_start,
            view_end=view_end,
        )
        center_ts_ms = self._global_index_to_ts_ms(center_global)
        if center_ts_ms is None:
            return

        self.request_slice(
            center_ts_ms=center_ts_ms,
            reason=self._refill_reason(need_left=need_left, need_right=need_right),
        )

    @Slot(object)
    def _apply_slice(self, payload_obj: object) -> None:
        """Apply one resident slice into controller/session and workspace.

        The controller owns resident-slice truth, canonical-to-resident study
        reprojection, and the downstream data push into the workspace. Pane
        lifecycle and layout remain workspace-owned, so this slot intentionally
        does not toggle optional pane visibility.
        """
        if self._is_disposed:
            self._request_in_flight = False
            return

        payload: SlicePayload = payload_obj  # type: ignore[assignment]

        if self._session.dataset_id is not None and payload.dataset_id != self._session.dataset_id:
            self._request_in_flight = False
            self.error.emit(
                "Discarded historical slice for a dataset that does not match the active chart session."
            )
            self._on_viewport_changed()
            return

        if self._initial_view_applied and not self._payload_covers_current_viewport(payload):
            # The viewport has moved since this request was issued. Because the
            # controller is the sole owner of resident-slice truth, stale slice
            # results must be discarded here instead of being applied and then
            # forcing downstream layers to recover from mismatched truth.
            self._request_in_flight = False
            self._on_viewport_changed()
            return

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

        self._session.set_resident_slice(
            base_index=int(getattr(payload, "base_index", 0)),
            candles=candles,
            has_more_left=bool(getattr(payload, "has_more_left", False)),
            has_more_right=bool(getattr(payload, "has_more_right", False)),
        )
        self._refresh_all_study_projections()
        projected_payloads = self.get_projected_study_payloads()

        self._suppress_viewport_refill = True
        try:
            self._workspace.apply_historical_slice(
                symbol=self._symbol,
                timeframe=self._timeframe,
                candles=candles,
                resident_base_index=self._session.resident_base_index,
                dataset_total=(
                    self._session.dataset_count
                    if self._session.dataset_count is not None
                    else len(candles)
                ),
            )

            # The controller applies resident-local data only. Whether
            # auxiliary panes such as volume are present is a downstream
            # workspace/panel layout decision and must not be toggled here.
            if not self._initial_view_applied:
                self._set_viewport_to_latest(visible_target=self.DEFAULT_VISIBLE_BARS)
                self._initial_view_applied = True
        finally:
            self._suppress_viewport_refill = False
            self._request_in_flight = False

        self.projected_studies_refreshed.emit(projected_payloads)
        self.slice_ready.emit(payload)
        self._on_viewport_changed()
