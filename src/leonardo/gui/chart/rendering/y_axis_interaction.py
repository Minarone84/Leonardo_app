from __future__ import annotations

import math
from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent


class PriceYAxisInteractionMixin:
    def _resolved_y_range_from_view_state(self) -> Optional[tuple[float, float]]:
        """Return the explicit pane-owned y-range contract when valid."""
        try:
            lo = float(self._view_state.get("y_lo"))
            hi = float(self._view_state.get("y_hi"))
        except Exception:
            return None

        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            return None
        return (lo, hi)

    def _persist_non_anchored_range(self, lo: float, hi: float) -> Optional[tuple[float, float]]:
        """Persist the pane-owned y-range after direct user interaction.

        The renderer no longer owns long-lived price scaling. It only writes
        back the current explicit range contract while executing a gesture.

        Important contract rule:
        - invalid ranges must not cause the renderer to invent a replacement
          vertical scale
        - if the explicit pane-owned range contract is currently missing, this
          method must leave pane state unchanged rather than synthesizing a
          renderer-owned fallback such as ``0..1``
        """
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            resolved = self._resolved_y_range_from_view_state()
            if resolved is None:
                return None
            lo, hi = resolved

        self._view_state["y_lo"] = float(lo)
        self._view_state["y_hi"] = float(hi)
        return float(lo), float(hi)

    def _is_y_drag_active(self) -> bool:
        """Return whether price-axis drag interaction is active.

        The transient interaction flag is stored in pane-owned view state so the
        renderer is not the sole owner of vertical gesture lifecycle.
        """
        try:
            return bool(self._view_state.get("y_drag_active", False))
        except Exception:
            return False

    def _y_drag_mode_from_view_state(self) -> Optional[str]:
        """Return the active price-axis drag mode from pane-owned state."""
        raw = self._view_state.get("y_drag_mode")
        text = str(raw).strip().lower() if raw is not None else ""
        return text if text in {"zoom", "pan"} else None

    def _y_drag_start_y_from_view_state(self) -> Optional[float]:
        """Return the drag start y coordinate from pane-owned state."""
        raw = self._view_state.get("y_drag_start_y")
        if raw is None:
            return None
        try:
            return float(raw)
        except Exception:
            return None

    def _y_drag_start_range_from_view_state(self) -> Optional[tuple[float, float]]:
        """Return the drag start range from pane-owned state when valid."""
        raw_lo = self._view_state.get("y_drag_start_lo")
        raw_hi = self._view_state.get("y_drag_start_hi")
        try:
            lo = float(raw_lo)
            hi = float(raw_hi)
        except Exception:
            return None
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            return None
        return lo, hi

    def _begin_y_drag(self, *, mode: str, start_y: float, lo: float, hi: float) -> None:
        """Persist price-axis drag lifecycle into pane-owned view state."""
        self._view_state["y_drag_active"] = True
        self._view_state["y_drag_mode"] = str(mode)
        self._view_state["y_drag_start_y"] = float(start_y)
        self._view_state["y_drag_start_lo"] = float(lo)
        self._view_state["y_drag_start_hi"] = float(hi)

    def _end_y_drag(self) -> None:
        """Clear transient price-axis drag lifecycle from pane-owned state."""
        self._view_state["y_drag_active"] = False
        self._view_state.pop("y_drag_mode", None)
        self._view_state.pop("y_drag_start_y", None)
        self._view_state.pop("y_drag_start_lo", None)
        self._view_state.pop("y_drag_start_hi", None)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        plot = self._plot_rect()

        if event.button() == Qt.LeftButton and self._axis_rect(plot).contains(
            event.position()
        ):
            if not self._is_anchor_enabled():
                drag_range = self._current_y_range_for_drag()
                if drag_range is None:
                    # The renderer must not invent a drag-start scale when the
                    # explicit pane-owned y-range contract is absent.
                    event.accept()
                    return

                lo, hi = drag_range
                drag_mode = "pan" if (event.modifiers() & Qt.ShiftModifier) else "zoom"
                self._begin_y_drag(
                    mode=drag_mode,
                    start_y=float(event.position().y()),
                    lo=lo,
                    hi=hi,
                )
                event.accept()
                return

            event.accept()
            return

        if event.button() == Qt.LeftButton and plot.contains(event.position()):
            self._dragging = True
            self._last_drag_x = int(event.position().x())
            self._last_drag_y = int(event.position().y())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._is_y_drag_active():
            self._end_y_drag()
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._last_drag_x = None
            self._last_drag_y = None
            event.accept()
            return

        super().mouseReleaseEvent(event)


    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pt = event.position().toPoint()
        plot = self._plot_rect()

        drag_start_y = self._y_drag_start_y_from_view_state()
        if self._is_y_drag_active() and not self._is_anchor_enabled() and drag_start_y is not None:
            dy = float(event.position().y()) - drag_start_y
            self._apply_y_axis_drag(plot, dy)
            # Vertical drag updates the explicit y-range contract in pane-owned
            # state, so the surface must repaint immediately.
            self.update()
            event.accept()
            return

        if self._dragging and self._last_drag_x is not None and plot.contains(pt):
            # While dragging/panning, suppress crosshair hover so we don't churn
            # overlay + crosshair updates.
            self._crosshair.set_hover_on_price(False)
            self._mouse_pt = None

            dx = pt.x() - self._last_drag_x
            if dx != 0:
                # Horizontal pan triggers viewport_changed, and workspace owns the
                # resulting contract push + repaint. Avoid redundant local
                # update() calls here.
                self._pan_by_pixels(plot, dx)
                self._last_drag_x = pt.x()

            need_update = False
            if not self._is_anchor_enabled() and self._last_drag_y is not None:
                dy = pt.y() - self._last_drag_y
                if dy != 0:
                    # Manual vertical pan (autoscale off) mutates pane-owned
                    # y-range contract directly, so repaint locally.
                    self._pan_y_by_pixels(plot, dy)
                    self._last_drag_y = pt.y()
                    need_update = True

            if need_update:
                self.update()

            event.accept()
            return

        # Non-dragging hover/crosshair behavior.
        old_idx = self._crosshair.index
        old_hover = self._crosshair.hover_on_price

        if plot.contains(pt):
            idx = self._viewport.index_from_x(plot, float(pt.x()))
            self._crosshair.set_index(idx)
            self._crosshair.set_hover_on_price(True)
            self._mouse_pt = pt

            crosshair_changed = (self._crosshair.index != old_idx) or (
                self._crosshair.hover_on_price != old_hover
            )

            # If crosshair state changed, it already emitted a repaint signal.
            # Only request an explicit repaint when the crosshair stayed on the
            # same candle and we just need to move the horizontal line.
            if not crosshair_changed:
                self.update()
            return

        # Outside plot: clear hover line. Only repaint if hover state changed.
        self._crosshair.set_hover_on_price(False)
        self._mouse_pt = None

        if self._crosshair.hover_on_price != old_hover:
            # crosshair.changed schedules repaint
            return

    def leaveEvent(self, event) -> None:
        self._crosshair.set_hover_on_price(False)
        self._mouse_pt = None
        self._end_y_drag()
        self.update()
        super().leaveEvent(event)

    def _is_anchor_enabled(self) -> bool:
        """Return whether workspace-owned price autoscale currently owns y-range.

        Older wiring mirrored this state through ChartViewport.anchor_zoom_enabled.
        The price-pane vertical contract now travels through view_state, so the
        renderer consumes that explicit pane/workspace state first and only falls
        back to the viewport compatibility flag for older callers.
        """
        if isinstance(self._view_state, dict) and "autoscale_enabled" in self._view_state:
            return bool(self._view_state.get("autoscale_enabled", True))
        return bool(getattr(self._viewport, "anchor_zoom_enabled", True))

    def _current_y_range_for_drag(self) -> Optional[Tuple[float, float]]:
        """Return the explicit pane-owned y-range available for interaction.

        The price renderer must not synthesize a vertical range when the
        workspace/pane contract is missing. Drag handlers therefore use this
        helper as a gate: if no explicit range is present, vertical gestures are
        ignored rather than creating renderer-owned scale truth.
        """
        return self._resolved_y_range_from_view_state()

    def _apply_y_axis_drag(self, plot: QRectF, dy_pixels: float) -> None:
        start_range = self._y_drag_start_range_from_view_state()
        if start_range is None:
            return

        lo0, hi0 = start_range
        rng0 = max(1e-9, hi0 - lo0)
        h = max(1.0, plot.height())
        mode = self._y_drag_mode_from_view_state()

        if mode == "zoom":
            s = 1.0 + (dy_pixels / 180.0)
            s = max(0.15, min(8.0, s))
            new_rng = rng0 * s
            mid = (lo0 + hi0) * 0.5
            lo = mid - new_rng * 0.5
            hi = mid + new_rng * 0.5
            self._persist_non_anchored_range(lo, hi)
            return

        if mode == "pan":
            delta = (dy_pixels / h) * rng0
            lo = lo0 + delta
            hi = hi0 + delta
            self._persist_non_anchored_range(lo, hi)
            return

    def _pan_y_by_pixels(self, plot: QRectF, dy_pixels: int) -> None:
        current_range = self._current_y_range_for_drag()
        if current_range is None:
            return

        lo, hi = current_range
        rng = max(1e-9, hi - lo)
        h = max(1.0, plot.height())

        delta = (float(dy_pixels) / h) * rng
        new_lo = lo + delta
        new_hi = hi + delta
        self._persist_non_anchored_range(new_lo, new_hi)

    def _y_for_price(self, plot: QRectF, price: float, lo: float, hi: float) -> float:
        t = (price - lo) / (hi - lo)
        return plot.bottom() - t * plot.height()

    def _pan_by_pixels(self, plot: QRectF, dx_pixels: int) -> None:
        if dx_pixels == 0:
            return

        step = int(abs(dx_pixels) / max(1.0, plot.width()) * self._viewport.visible)
        step = max(1, step)

        if dx_pixels > 0:
            self._viewport.pan_left(step)
        else:
            self._viewport.pan_right(step)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        try:
            mx = float(event.position().x())
        except Exception:
            mx = float(event.x())

        if not plot.contains(mx, plot.center().y()):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(
            1, self._viewport.visible
        )

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()



class OscillatorYAxisInteractionMixin:
    def _sync_view_state_from_owner(self) -> None:
        """Refresh renderer-local mirrors from pane-owned oscillator state.

        ``y_offset`` remains pane-owned contract state. The renderer keeps only
        a transient numeric mirror for efficient paint-time use and rejects any
        non-finite upstream value so drawing math stays well-defined.
        """
        try:
            value = float(self._view_state.get("y_offset", 0.0))
        except Exception:
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        self._y_offset = value

    def _resolved_y_range_from_view_state(self) -> Optional[tuple[float, float]]:
        """Return the explicit pane-owned oscillator y-range contract when valid.

        The renderer must reject incomplete or non-finite upstream contracts
        instead of silently inventing a fallback range on its own.
        """
        try:
            lo = float(self._view_state.get("y_lo"))
            hi = float(self._view_state.get("y_hi"))
        except Exception:
            return None
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            return None
        return (lo, hi)

    def _persist_y_offset(self, value: float) -> float:
        """Persist the current oscillator vertical offset into pane-owned state.

        The persisted offset is sanitized to a finite numeric value so the pane
        contract cannot accumulate invalid drag results.
        """
        resolved = float(value)
        if not math.isfinite(resolved):
            resolved = 0.0
        self._y_offset = resolved
        self._view_state["y_offset"] = self._y_offset
        return self._y_offset

    def _is_y_drag_active(self) -> bool:
        """Return whether oscillator right-drag interaction is active."""
        try:
            return bool(self._view_state.get("y_drag_active", False))
        except Exception:
            return False

    def _drag_last_mouse_y(self) -> Optional[float]:
        """Return the last recorded drag y-position from pane-owned state."""
        raw = self._view_state.get("y_drag_last_mouse_y")
        if raw is None:
            return None
        try:
            return float(raw)
        except Exception:
            return None

    def _begin_y_drag(self, y: float) -> None:
        """Start pane-owned oscillator right-drag interaction."""
        self._view_state["y_drag_active"] = True
        self._view_state["y_drag_last_mouse_y"] = float(y)

    def _update_y_drag_position(self, y: float) -> None:
        """Update pane-owned last drag y-position."""
        self._view_state["y_drag_last_mouse_y"] = float(y)

    def _end_y_drag(self) -> None:
        """End pane-owned oscillator right-drag interaction."""
        self._view_state["y_drag_active"] = False
        self._view_state.pop("y_drag_last_mouse_y", None)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            try:
                y = float(e.position().y())
            except Exception:
                y = float(e.y())
            self._begin_y_drag(y)
            e.accept()
            return

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        plot = self._plot_rect()
        try:
            x = float(e.position().x())
            y = float(e.position().y())
        except Exception:
            x = float(e.x())
            y = float(e.y())

        last_mouse_y = self._drag_last_mouse_y()
        if self._is_y_drag_active() and last_mouse_y is not None:
            dy = y - last_mouse_y
            self._persist_y_offset(self._y_offset + dy)
            self._update_y_drag_position(y)
            self.update()
            e.accept()
            return

        if not plot.contains(x, y):
            self._crosshair.set_hover_on_price(False)
            return

        idx = self._viewport.index_from_x(plot, x)
        self._crosshair.set_index(idx)
        self._crosshair.set_hover_on_price(False)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            self._end_y_drag()
            e.accept()
            return

        super().mouseReleaseEvent(e)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        try:
            mx = float(event.position().x())
            my = float(event.position().y())
        except Exception:
            mx = float(event.x())
            my = float(event.y())

        if not plot.contains(mx, my):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(1, self._viewport.visible)

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()

    def leaveEvent(self, e) -> None:
        self._crosshair.set_hover_on_price(False)
        self._end_y_drag()
        super().leaveEvent(e)
