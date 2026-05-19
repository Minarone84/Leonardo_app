from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from leonardo.common.market_types import Candle
from leonardo.gui.chart.model import Series


class WorkspaceAutoscaleMixin:
    @property
    def price_autoscale_enabled(self) -> bool:
        """Return the workspace-owned price-pane autoscale state."""
        return bool(self._price_autoscale_enabled)

    def _set_price_autoscale_state(self, enabled: bool) -> None:
        """Store price autoscale in the workspace-owned pane view state."""
        resolved = bool(enabled)
        self._price_autoscale_enabled = resolved
        self._price_state.view_state["autoscale_enabled"] = resolved

        # Autoscale owns the y-range while enabled, so stale manual drag
        # lifecycle keys must not survive when control returns to autoscale.
        if resolved:
            self._price_state.view_state["y_drag_active"] = False
            for key in (
                "y_drag_mode",
                "y_drag_start_y",
                "y_drag_start_lo",
                "y_drag_start_hi",
            ):
                self._price_state.view_state.pop(key, None)

    def set_price_autoscale_enabled(self, enabled: bool) -> None:
        """Set the user-facing price-pane autoscale contract.

        This is the canonical workspace API. The legacy anchor-zoom name is
        retained below only as a compatibility alias for older callers.
        """
        resolved = bool(enabled)
        self._set_price_autoscale_state(resolved)

        # Preserve the existing viewport API until the panel/viewport naming
        # cleanup is completed in a later pass. This is a compatibility mirror,
        # not the autoscale source of truth.
        self._viewport.set_anchor_zoom_enabled(resolved)

        self._sync_price_pane_contract()
        self._refresh_price_pane()

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        # Compatibility entry point: older callers still route the autoscale
        # toggle through the historical "anchor zoom" control. Delegate to the
        # explicit price autoscale API so the button, workspace, pane, and
        # renderer all consume one state path.
        self.set_price_autoscale_enabled(bool(enabled))

    def set_price_pane_view_state(self, view_state: Optional[Dict[str, Any]]) -> None:
        """Persist price-pane view state in workspace ownership and push it downstream.

        This method preserves the canonical workspace-owned mapping object for
        the price pane. Render surfaces may write direct gesture updates back
        into that same mapping, so rebinding the dict here would silently split
        ownership across layers and orphan downstream consumers.
        """
        self._replace_mapping_contents(self._price_state.view_state, view_state)
        self._sync_price_pane_contract()

    def price_pane_view_state(self) -> Dict[str, Any]:
        return dict(self._price_state.view_state)

    def _replace_mapping_contents(
        self,
        target: Dict[str, Any],
        source: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Replace mapping contents in place while preserving workspace ownership."""
        normalized = dict(source or {})
        target.clear()
        target.update(normalized)
        return target

    # ------------------------------------------------------------------
    # Price autoscale helpers
    # ------------------------------------------------------------------

    def _series_is_visible(self, series: Series) -> bool:
        """Return whether one render series currently participates visually."""
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return True
        try:
            return bool(getattr(style_obj, "visible", True))
        except Exception:
            return True

    def _series_render_mode(self, series: Series) -> str:
        """Return the declared renderer mode for one overlay series."""
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return "line"
        try:
            return str(getattr(style_obj, "render_mode", "line") or "line").strip().lower()
        except Exception:
            return "line"

    def _marker_vertical_headroom_px(self, series: Series) -> tuple[int, int]:
        """Return extra top/bottom pixel headroom required by one marker series."""
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return (0, 0)

        try:
            size = int(getattr(style_obj, "marker_size", 0) or 0)
        except Exception:
            size = 0
        if size <= 0:
            return (0, 0)

        try:
            offset_px = int(getattr(style_obj, "marker_offset_px", 0) or 0)
        except Exception:
            offset_px = 0

        resolved_size = max(6, min(32, size))
        half = resolved_size / 2.0
        safety_px = 2.0

        top_px = max(0.0, half - float(offset_px)) + safety_px
        bottom_px = max(0.0, half + float(offset_px)) + safety_px
        return (int(math.ceil(top_px)), int(math.ceil(bottom_px)))

    def _estimated_price_plot_height_px(self) -> float:
        """Return a conservative estimate of drawable price-plot height."""
        try:
            pane_height = int(self._price.height())
        except Exception:
            pane_height = 0

        if pane_height <= 0:
            return 300.0

        # Conservative pad: the renderer reserves top/bottom padding and axis space.
        return float(max(80, pane_height - 40))

    def _iter_price_overlay_series_safe(self) -> Iterable[Series]:
        """Yield overlay series without forcing list allocation in hot paths."""
        it = getattr(self, "_iter_price_overlay_series", None)
        if callable(it):
            try:
                return it()
            except Exception:
                pass

        payload = getattr(self, "_price_overlay_series_payload", None)
        if callable(payload):
            try:
                return payload()
            except Exception:
                pass

        return []

    def _visible_price_extrema(self) -> Optional[tuple[float, float]]:
        """Return finite visible OHLC low/high without allocating candle lists."""
        start = int(getattr(self._viewport, "start", 0))
        end = int(getattr(self._viewport, "end", 0))
        candles = self._model.candles

        try:
            resident_base_index = int(getattr(self._model, "resident_base_index", 0))
        except Exception:
            resident_base_index = 0

        local_start = start - resident_base_index
        local_end = end - resident_base_index
        if local_end <= 0 or local_start >= len(candles):
            return None

        lo_i = max(0, local_start)
        hi_i = min(len(candles), local_end)

        lo: Optional[float] = None
        hi: Optional[float] = None

        for i in range(lo_i, hi_i):
            c = candles[i]
            low = float(c.low)
            high = float(c.high)
            if lo is None or low < lo:
                lo = low
            if hi is None or high > hi:
                hi = high

        if lo is None or hi is None:
            return None
        return (lo, hi)

    def _visible_overlay_extrema_and_marker_headroom_px(
        self,
    ) -> tuple[Optional[float], Optional[float], int, int]:
        """Return visible overlay low/high plus marker headroom in one pass."""
        start = int(getattr(self._viewport, "start", 0))
        end = int(getattr(self._viewport, "end", 0))

        try:
            resident_base_index = int(getattr(self._model, "resident_base_index", 0))
        except Exception:
            resident_base_index = 0

        lo: Optional[float] = None
        hi: Optional[float] = None
        max_top_px = 0
        max_bottom_px = 0

        for series in self._iter_price_overlay_series_safe():
            if not self._series_is_visible(series):
                continue

            values = getattr(series, "values", None)
            if values is None:
                continue
            try:
                values_len = len(values)  # type: ignore[arg-type]
            except Exception:
                continue
            if values_len <= 0:
                continue

            local_start = start - resident_base_index
            local_end = end - resident_base_index
            if local_end <= 0 or local_start >= values_len:
                continue

            lo_i = max(0, local_start)
            hi_i = min(values_len, local_end)

            has_visible = False
            for i in range(lo_i, hi_i):
                try:
                    numeric = float(values[i])
                except Exception:
                    continue
                if not math.isfinite(numeric):
                    continue
                has_visible = True
                if lo is None or numeric < lo:
                    lo = numeric
                if hi is None or numeric > hi:
                    hi = numeric

            if not has_visible:
                continue

            if self._series_render_mode(series) == "marker":
                top_px, bottom_px = self._marker_vertical_headroom_px(series)
                max_top_px = max(max_top_px, top_px)
                max_bottom_px = max(max_bottom_px, bottom_px)

        return (lo, hi, max_top_px, max_bottom_px)

    def _marker_headroom_value_margins(
        self,
        *,
        lo: float,
        hi: float,
        top_px: int,
        bottom_px: int,
    ) -> tuple[float, float]:
        """Convert marker headroom pixels into explicit value-space margins."""
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            return (0.0, 0.0)
        if top_px <= 0 and bottom_px <= 0:
            return (0.0, 0.0)

        span = max(1e-6, hi - lo)
        plot_height_px = self._estimated_price_plot_height_px()
        low_margin = span * (float(max(0, bottom_px)) / plot_height_px)
        high_margin = span * (float(max(0, top_px)) / plot_height_px)
        return (low_margin, high_margin)

    def _resident_price_extrema_cached(self) -> tuple[float, float]:
        """Return resident candle low/high with a small cache.

        This avoids rescanning large resident slices when the viewport is
        entirely inside padding (no visible candles).
        """
        candles = self._model.candles
        if not candles:
            return (0.0, 1.0)

        # Cache key: enough to detect slice replacement and last-candle edits.
        try:
            first_ts = int(candles[0].ts_ms)
        except Exception:
            first_ts = 0
        try:
            last = candles[-1]
            last_ts = int(last.ts_ms)
            last_low = float(last.low)
            last_high = float(last.high)
        except Exception:
            last_ts = 0
            last_low = 0.0
            last_high = 0.0

        key = (len(candles), first_ts, last_ts, last_low, last_high)

        cache = getattr(self, "_price_resident_extrema_cache", None)
        if isinstance(cache, tuple) and len(cache) == 2:
            cached_key, cached_val = cache
            if cached_key == key and isinstance(cached_val, tuple) and len(cached_val) == 2:
                return (float(cached_val[0]), float(cached_val[1]))

        lo = float("inf")
        hi = float("-inf")
        for c in candles:
            low = float(c.low)
            high = float(c.high)
            if low < lo:
                lo = low
            if high > hi:
                hi = high

        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            lo = 0.0
            hi = 1.0

        self._price_resident_extrema_cache = (key, (lo, hi))
        return (lo, hi)

    def _resolved_price_y_range(self) -> tuple[float, float]:
        """Resolve the explicit workspace-owned price y-range contract."""
        candles = self._model.candles
        if not candles:
            return (0.0, 1.0)

        current_view_state = self._price_state.view_state

        autoscale_enabled = bool(
            current_view_state.get(
                "autoscale_enabled",
                self._price_autoscale_enabled,
            )
        )
        self._price_autoscale_enabled = autoscale_enabled
        current_view_state["autoscale_enabled"] = autoscale_enabled

        def padded_range(lo: float, hi: float) -> tuple[float, float]:
            if hi <= lo:
                return (lo, lo + 1.0)
            span = max(1e-6, hi - lo)
            return (lo - 0.03 * span, hi + 0.03 * span)

        def visible_range() -> tuple[float, float]:
            candle_extrema = self._visible_price_extrema()
            if candle_extrema is None:
                lo, hi = self._resident_price_extrema_cached()
                return padded_range(lo, hi)

            lo, hi = candle_extrema
            lo, hi = padded_range(lo, hi)

            overlay_lo, overlay_hi, marker_top_px, marker_bottom_px = (
                self._visible_overlay_extrema_and_marker_headroom_px()
            )
            if overlay_lo is not None and overlay_hi is not None:
                lo = min(lo, overlay_lo)
                hi = max(hi, overlay_hi)
                lo, hi = padded_range(lo, hi)

            low_margin, high_margin = self._marker_headroom_value_margins(
                lo=lo,
                hi=hi,
                top_px=marker_top_px,
                bottom_px=marker_bottom_px,
            )
            if low_margin > 0.0 or high_margin > 0.0:
                lo -= low_margin
                hi += high_margin
                lo, hi = padded_range(lo, hi)

            return (lo, hi)

        if autoscale_enabled:
            lo, hi = visible_range()
            current_view_state["y_lo"] = float(lo)
            current_view_state["y_hi"] = float(hi)
            return (lo, hi)

        # Manual y-range ownership.
        try:
            lo = float(current_view_state.get("y_lo"))
            hi = float(current_view_state.get("y_hi"))
        except Exception:
            lo, hi = visible_range()
            current_view_state["y_lo"] = float(lo)
            current_view_state["y_hi"] = float(hi)
            return (lo, hi)

        if hi <= lo:
            lo, hi = visible_range()
            current_view_state["y_lo"] = float(lo)
            current_view_state["y_hi"] = float(hi)
            return (lo, hi)

        return (lo, hi)

    def _push_price_render_payload(self) -> None:
        """Push the current viewport-dependent price y-range into PricePane."""
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(contracts=True)
            return

        lo, hi = self._resolved_price_y_range()
        self._price_state.view_state["y_lo"] = float(lo)
        self._price_state.view_state["y_hi"] = float(hi)

        if hasattr(self._price, "apply_view_state_contract"):
            self._price.apply_view_state_contract(self._price_state.view_state)  # type: ignore[attr-defined]
