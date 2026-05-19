from __future__ import annotations

from typing import Optional

from leonardo.data.historical.dataset_service import SlicePayload


class HistoricalChartRefillPolicyMixin:
    def _should_consider_refill(self) -> bool:
        """Return True when the controller can evaluate refill policy.

        Viewport notifications are pure camera-change inputs. Refill policy is
        controller-owned and may be evaluated even while a request is already in
        flight. The controller still issues at most one request at a time, but
        it must keep observing camera state so stale returned slices can be
        discarded and current need can be re-evaluated immediately.
        """
        if self._is_disposed:
            return False
        if self._dataset is None:
            return False
        if self._session.dataset_count is None or self._session.dataset_count <= 0:
            return False
        if self._suppress_viewport_refill:
            return False
        if self._session.resident_size <= 0:
            return False
        if not self._initial_view_applied:
            return False
        return True

    def _normalized_viewport_window(self) -> tuple[int, int]:
        """Resolve the current camera into a dataset-interest window.

        The viewport is a camera over fixed chart space and may legally move
        into padded slots before the first candle or after the latest candle.
        Resident-slice policy, however, must stay grounded in canonical dataset
        coordinates. This helper therefore converts the current camera into the
        dataset window that is currently relevant to the user:

        - overlapping camera regions are clipped into canonical dataset space
        - camera regions fully inside left padding map to the dataset's first
          edge-adjacent window
        - camera regions fully inside right padding map to the dataset's latest
          edge-adjacent window

        This keeps refill ownership in the controller without letting the
        viewport redefine dataset truth.
        """
        dataset_count = int(self._session.dataset_count or 0)
        if dataset_count <= 0:
            return (0, 0)

        vp = self._workspace.viewport
        raw_start = int(vp.start)
        raw_end = int(vp.end)
        raw_visible = max(1, raw_end - raw_start)

        if raw_end <= 0:
            return (0, min(dataset_count, raw_visible))

        if raw_start >= dataset_count:
            return (max(0, dataset_count - raw_visible), dataset_count)

        view_start = max(0, min(raw_start, dataset_count))
        view_end = max(view_start, min(raw_end, dataset_count))

        if view_end > view_start:
            return (view_start, view_end)

        if raw_start < 0:
            return (0, min(dataset_count, raw_visible))

        return (max(0, dataset_count - raw_visible), dataset_count)

    def _slice_payload_bounds(self, payload: SlicePayload) -> tuple[int, int]:
        """Return one slice payload's dataset coverage window."""
        base_index = max(0, int(getattr(payload, "base_index", 0)))
        size = len(list(getattr(payload, "ts_ms", []) or []))
        return (base_index, base_index + size)

    def _payload_covers_current_viewport(self, payload: SlicePayload) -> bool:
        """True when a returned slice still covers the current camera interest window.

        This is the controller-side stale-slice guard that prevents an old
        refill result from replacing resident truth after the user has already
        moved the viewport somewhere else.
        """
        view_start, view_end = self._normalized_viewport_window()
        if view_end <= view_start:
            return True

        payload_start, payload_end = self._slice_payload_bounds(payload)
        return payload_start <= view_start and payload_end >= view_end

    def _resident_window_bounds(self) -> tuple[int, int]:
        """Return the current resident window in dataset coordinates."""
        resident_left = int(self._session.resident_base_index)
        resident_right_exclusive = resident_left + int(self._session.resident_size)
        return (resident_left, resident_right_exclusive)

    def _evaluate_refill_pressure(self) -> tuple[bool, bool, int, int]:
        """Evaluate whether the current camera window pressures the resident window.

        Returns:
            (need_left, need_right, view_start, view_end)
        """
        view_start, view_end = self._normalized_viewport_window()
        resident_left, resident_right_exclusive = self._resident_window_bounds()

        left_margin = view_start - resident_left
        right_margin = resident_right_exclusive - view_end

        underflow_left = view_start < resident_left
        underflow_right = view_end > resident_right_exclusive

        need_left = bool(
            self._session.has_more_left
            and (underflow_left or left_margin <= self.REFILL_THRESHOLD)
        )
        need_right = bool(
            self._session.has_more_right
            and (underflow_right or right_margin <= self.REFILL_THRESHOLD)
        )
        return (need_left, need_right, view_start, view_end)

    def _refill_center_global_index(self, *, view_start: int, view_end: int) -> int:
        """Choose the dataset-global center index for the next slice request."""
        dataset_count = int(self._session.dataset_count or 0)
        if dataset_count <= 0:
            return 0

        if view_end > view_start:
            center_global = view_start + ((view_end - view_start) // 2)
        else:
            center_global = dataset_count - 1

        return max(0, min(center_global, dataset_count - 1))

    def _refill_reason(self, *, need_left: bool, need_right: bool) -> str:
        if need_left and not need_right:
            return "refill-left"
        if need_right and not need_left:
            return "refill-right"
        return "refill-both"

    def _global_index_to_ts_ms(self, global_index: int) -> Optional[int]:
        return self._session.global_index_to_ts_ms(global_index)

    def _set_viewport_to_latest(self, *, visible_target: int) -> None:
        if self._is_disposed:
            return

        vp = self._workspace.viewport
        total = (
            int(self._session.dataset_count)
            if self._session.dataset_count is not None
            else int(self._session.resident_size)
        )
        if total <= 0:
            return

        try:
            viewport_total = int(getattr(vp, "total"))
        except Exception:
            viewport_total = max(1, int(total))

        try:
            max_visible = int(getattr(vp, "MAX_VISIBLE_BARS"))
        except Exception:
            max_visible = self.MAX_VISIBLE_BARS

        visible = max(1, min(int(visible_target), max_visible, viewport_total))
        start = int(total) - visible
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
