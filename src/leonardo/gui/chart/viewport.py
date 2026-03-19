from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Signal


class ChartViewport(QObject):
    viewport_changed = Signal()

    # Horizontal viewport policy (same for all timeframes)
    MIN_VISIBLE_BARS = 20
    MAX_VISIBLE_BARS = 2000

    def __init__(self, total_count: int, visible_count: int = 120) -> None:
        super().__init__()

        # real candles count
        self._data_total = max(0, int(total_count))
        # explicit future padding request
        self._future_pad = 0

        self._crosshair_index: int | None = None

        # anchored zoom default ON
        self._anchor_zoom_enabled: bool = True

        # total slots shown on x axis (real + future)
        self._total = max(1, self._data_total + self._effective_future_pad())

        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        self._visible = max(1, min(int(visible_count), max_visible))

        # Initial position at latest.
        self._start = self._max_start()

    # ---------------------------
    # basic properties
    # ---------------------------

    @property
    def total(self) -> int:
        return self._total

    @property
    def data_total(self) -> int:
        return self._data_total

    @property
    def future_pad(self) -> int:
        return self._future_pad

    @property
    def start(self) -> int:
        return self._start

    @property
    def visible(self) -> int:
        return self._visible

    @property
    def end(self) -> int:
        return self._start + self._visible

    @property
    def crosshair_index(self) -> int | None:
        return self._crosshair_index

    # ---------------------------
    # anchor zoom toggle
    # ---------------------------

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._anchor_zoom_enabled == enabled:
            return

        self._anchor_zoom_enabled = enabled

        # IMPORTANT:
        # Toggling anchor mode must NOT teleport the viewport to latest.
        # Preserve the current historical position and only change the zoom policy.
        self._recompute_total_and_clamp(preserve_position=True)
        self.viewport_changed.emit()

    @property
    def anchor_zoom_enabled(self) -> bool:
        return self._anchor_zoom_enabled

    # ---------------------------
    # totals / future padding
    # ---------------------------

    def set_future_padding(self, n: int) -> None:
        self._future_pad = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_preserve_position(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_count(self, n: int) -> None:
        """
        Workspace calls this after snapshot/append.
        Preserve the user's current horizontal position regardless of anchor mode.
        """
        self._data_total = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_count_preserve_position(self, n: int) -> None:
        """
        Historical-mode helper:
        preserve the current viewport position regardless of anchor setting.
        """
        self._data_total = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=True)

    def _effective_future_pad(self) -> int:
        """
        Effective right-side future capacity.

        Anchor zoom ON:
            no future padding should be visible while right-aligned latest zoom
            is active.

        Anchor zoom OFF:
            reserve enough right-side space so the youngest real bar can be the
            only visible real bar at the far-right legal boundary.
        """
        if self._anchor_zoom_enabled:
            return 0
        return max(self._future_pad, self.MAX_VISIBLE_BARS - 1)

    def _latest_aligned_start(self) -> int:
        """
        Start index that keeps the latest real candle at the right edge
        of the visible window.
        """
        if self._data_total <= 0:
            return 0
        return max(0, self._data_total - self._visible)

    def _min_start(self) -> int:
        """
        Minimum legal viewport start.

        Allow panning into a left-side missing-history zone until the oldest real
        bar is the only visible real bar on the right side of the chart.
        """
        if self._data_total <= 0:
            return 0
        return -(self._visible - 1)

    def _max_start(self) -> int:
        """
        Maximum legal viewport start.

        Anchor zoom ON:
            clamp to latest-aligned real-data window.

        Anchor zoom OFF:
            allow panning into a right-side future zone until the youngest real
            bar is the only visible real bar on the left side of the chart.
        """
        if self._anchor_zoom_enabled:
            return self._latest_aligned_start()

        if self._data_total <= 0:
            return max(0, self._total - 1)

        return self._data_total - 1

    def _min_index(self) -> int:
        """
        Minimum legal slot index visible on the x axis.
        """
        return self._min_start()

    def _max_index(self) -> int:
        """
        Maximum legal slot index visible on the x axis.

        This is NOT the same as _max_start(). _max_start() bounds the viewport
        window origin, while this bounds individual slot indices.
        """
        return self._total - 1

    def set_window(self, start: int, end: int) -> None:
        old_visible = self._visible
        old_start = self._start

        start_i = int(start)
        end_i = max(start_i + 1, int(end))

        visible = max(1, end_i - start_i)
        visible = min(visible, min(self.MAX_VISIBLE_BARS, self._total))
        self._visible = visible

        self._total = max(1, self._data_total + self._effective_future_pad())

        min_start = self._min_start()
        max_start = self._max_start()
        start_i = max(min_start, min(start_i, max_start))
        self._start = start_i

        if self._crosshair_index is not None and not (0 <= self._crosshair_index < self._total):
            self._crosshair_index = None

        if (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()

    def set_range(self, start: int, end: int) -> None:
        self.set_window(start, end)

    def _recompute_total_and_clamp(self, *, preserve_position: bool) -> None:
        old_total = self._total
        old_visible = self._visible
        old_start = self._start

        self._total = max(1, self._data_total + self._effective_future_pad())

        max_visible = min(self.MAX_VISIBLE_BARS, self._total)

        if self._visible <= 1 and self._data_total > 1:
            self._visible = min(120, max_visible)
        else:
            self._visible = max(1, min(self._visible, max_visible))

        if preserve_position:
            self._start = max(self._min_start(), min(self._start, self._max_start()))
        else:
            self._start = self._max_start()

        if self._crosshair_index is not None and not (0 <= self._crosshair_index < self._total):
            self._crosshair_index = None

        if (self._total != old_total) or (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()

    def _snap_right_to_data(self) -> None:
        """
        Snap the viewport to the latest legal right position for the current mode.
        """
        self._start = self._max_start()

    def _is_right_aligned_to_data(self) -> bool:
        """
        True when the current viewport is at the mode-appropriate right boundary.
        """
        return self._start == self._max_start()

    # ---------------------------
    # pan
    # ---------------------------

    def pan_left(self, step: int = 10) -> None:
        step = int(step)
        if step <= 0:
            return

        old_start = self._start
        min_start = self._min_start()
        self._start = max(min_start, self._start - step)

        at_left_boundary = (old_start == min_start and self._start == min_start)
        if self._start != old_start or at_left_boundary:
            self.viewport_changed.emit()

    def pan_right(self, step: int = 10) -> None:
        step = int(step)
        if step <= 0:
            return

        old_start = self._start
        max_start = self._max_start()
        self._start = min(max_start, self._start + step)

        at_right_boundary = (old_start == max_start and self._start == max_start)
        if self._start != old_start or at_right_boundary:
            self.viewport_changed.emit()

    # ---------------------------
    # crosshair
    # ---------------------------

    def set_crosshair(self, index: int | None) -> None:
        if index == self._crosshair_index:
            return
        self._crosshair_index = index
        self.viewport_changed.emit()

    # ---------------------------
    # index <-> x mapping (DISCRETE GRID)
    # ---------------------------

    def index_from_x(self, plot: QRectF, x: float) -> int:
        start, end = self.start, self.end
        n = max(1, end - start)

        if plot.width() <= 1:
            return start

        cell_w = plot.width() / n
        rel = int((x - plot.left()) / max(1e-9, cell_w))
        rel = max(0, min(n - 1, rel))
        return start + rel

    def x_from_index(self, plot: QRectF, idx: int) -> float:
        start, end = self.start, self.end
        n = max(1, end - start)

        if plot.width() <= 1:
            return plot.left()

        idx = max(start, min(end - 1, idx))
        rel = idx - start

        cell_w = plot.width() / n
        return plot.left() + (rel + 0.5) * cell_w

    # ---------------------------
    # zoom anchored at mouse
    # ---------------------------

    def zoom_in_at(self, anchor_idx: int, anchor_rel: float) -> None:
        if self._visible <= self.MIN_VISIBLE_BARS:
            return
        new_visible = max(self.MIN_VISIBLE_BARS, int(self._visible * 0.8))
        self._set_visible_anchored(new_visible, anchor_idx, anchor_rel)

    def zoom_out_at(self, anchor_idx: int, anchor_rel: float) -> None:
        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        new_visible = min(max_visible, int(self._visible * 1.25))
        self._set_visible_anchored(new_visible, anchor_idx, anchor_rel)

    def _set_visible_anchored(self, new_visible: int, anchor_idx: int, anchor_rel: float) -> None:
        old_visible = self._visible
        old_start = self._start
        was_right_aligned = self._is_right_aligned_to_data()

        self._total = max(1, self._data_total + self._effective_future_pad())

        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        new_visible = max(1, min(int(new_visible), max_visible))
        self._visible = new_visible

        anchor_rel = max(0.0, min(1.0, float(anchor_rel)))

        # anchor_idx is a SLOT INDEX under the cursor, not a viewport start.
        anchor_idx = max(self._min_index(), min(int(anchor_idx), self._max_index()))

        if self._anchor_zoom_enabled and was_right_aligned:
            # Keep latest alignment only when the user was already at the latest edge.
            self._start = self._max_start()
        else:
            # Historical exploration must preserve the actual slot anchor
            # instead of teleporting to latest.
            pos = int(round(anchor_rel * max(1, new_visible - 1)))
            new_start = anchor_idx - pos
            new_start = max(self._min_start(), min(new_start, self._max_start()))
            self._start = new_start

        if self._crosshair_index is not None and not (0 <= self._crosshair_index < self._total):
            self._crosshair_index = None

        if (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()