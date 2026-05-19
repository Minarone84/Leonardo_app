from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Signal


class ChartViewport(QObject):
    viewport_changed = Signal()
    crosshair_changed = Signal()

    # Horizontal viewport policy (same for all timeframes)
    MIN_VISIBLE_BARS = 20
    MAX_VISIBLE_BARS = 2000

    def __init__(self, total_count: int, visible_count: int = 120) -> None:
        super().__init__()

        # Canonical dataset candle count. The viewport never mutates dataset
        # truth; it only moves a camera over a fixed chart-space domain derived
        # from that truth plus explicit chart-local padding.
        self._data_total = max(0, int(total_count))

        # Fixed chart-space domain padding. This is a visualization-domain
        # contract, not a refill or anchoring policy.
        self._left_pad = 0
        self._right_pad = 0

        self._crosshair_index: int | None = None

        # Legacy compatibility flag preserved for upstream gesture/UI wiring.
        # The viewport must not use this flag to reintroduce latest-edge camera
        # ownership during zoom; horizontal placement is resolved only from the
        # explicit zoom anchor and fixed chart-space clamps.
        self._anchor_zoom_enabled: bool = True

        self._total = max(1, self._domain_size())
        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        self._visible = max(1, min(int(visible_count), max_visible))

        # Initial position: latest real candle aligned to the right data edge.
        self._start = self._latest_aligned_start()

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
    def left_pad(self) -> int:
        return self._left_pad

    @property
    def right_pad(self) -> int:
        return self._right_pad

    @property
    def future_pad(self) -> int:
        # Compatibility alias for older callers.
        return self._right_pad

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

    @property
    def domain_start(self) -> int:
        return self._domain_start()

    @property
    def domain_end_exclusive(self) -> int:
        return self._domain_end_exclusive()

    # ---------------------------
    # legacy anchor-zoom compatibility toggle
    # ---------------------------

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        # Compatibility-only mirror for downstream gesture/UI code. The
        # viewport keeps exposing this flag, but horizontal zoom placement no
        # longer branches on it.
        enabled = bool(enabled)
        if self._anchor_zoom_enabled == enabled:
            return

        self._anchor_zoom_enabled = enabled
        self.viewport_changed.emit()

    @property
    def anchor_zoom_enabled(self) -> bool:
        return self._anchor_zoom_enabled

    # ---------------------------
    # totals / domain padding
    # ---------------------------

    def set_domain_padding(self, *, left_pad: int, right_pad: int) -> None:
        new_left = max(0, int(left_pad))
        new_right = max(0, int(right_pad))
        if self._left_pad == new_left and self._right_pad == new_right:
            return

        self._left_pad = new_left
        self._right_pad = new_right
        self._recompute_total_and_clamp(preserve_position=True)

    def set_future_padding(self, n: int) -> None:
        # Compatibility alias: older callers only understood right-side padding.
        self.set_domain_padding(left_pad=self._left_pad, right_pad=n)

    def set_total(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_preserve_position(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_count(self, n: int) -> None:
        """
        Workspace calls this after snapshot/append.
        Preserve the user's current horizontal position.
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

    def _domain_start(self) -> int:
        return -self._left_pad

    def _domain_end_exclusive(self) -> int:
        return self._data_total + self._right_pad

    def _domain_size(self) -> int:
        return self._domain_end_exclusive() - self._domain_start()

    def _latest_aligned_start(self) -> int:
        """Start index that keeps the latest real candle at the right data edge."""
        target_start = self._data_total - self._visible
        return max(self._min_start(), min(target_start, self._max_start()))

    def _min_start(self) -> int:
        """Minimum legal viewport start over the fixed chart-space domain."""
        return self._domain_start()

    def _max_start(self) -> int:
        """Maximum legal viewport start over the fixed chart-space domain."""
        return max(self._min_start(), self._domain_end_exclusive() - self._visible)

    def _min_index(self) -> int:
        """Minimum legal slot index visible on the x axis."""
        return self._domain_start()

    def _max_index(self) -> int:
        """Maximum legal slot index visible on the x axis."""
        return max(self._min_index(), self._domain_end_exclusive() - 1)

    def _crosshair_index_is_valid(self, index: int) -> bool:
        return self._min_index() <= int(index) <= self._max_index()

    def set_window(self, start: int, end: int) -> None:
        old_visible = self._visible
        old_start = self._start

        start_i = int(start)
        end_i = max(start_i + 1, int(end))

        self._total = max(1, self._domain_size())

        visible = max(1, end_i - start_i)
        visible = min(visible, min(self.MAX_VISIBLE_BARS, self._total))
        self._visible = visible

        min_start = self._min_start()
        max_start = self._max_start()
        start_i = max(min_start, min(start_i, max_start))
        self._start = start_i

        if self._crosshair_index is not None and not self._crosshair_index_is_valid(self._crosshair_index):
            self._crosshair_index = None

        if (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()

    def set_range(self, start: int, end: int) -> None:
        self.set_window(start, end)

    def _recompute_total_and_clamp(self, *, preserve_position: bool) -> None:
        old_total = self._total
        old_visible = self._visible
        old_start = self._start

        self._total = max(1, self._domain_size())

        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        if self._visible <= 1 and self._data_total > 1:
            self._visible = min(120, max_visible)
        else:
            self._visible = max(1, min(self._visible, max_visible))

        if preserve_position:
            self._start = max(self._min_start(), min(self._start, self._max_start()))
        else:
            self._start = self._latest_aligned_start()

        if self._crosshair_index is not None and not self._crosshair_index_is_valid(self._crosshair_index):
            self._crosshair_index = None

        if (self._total != old_total) or (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()

    def _snap_right_to_data(self) -> None:
        """Snap the viewport to the latest real-data edge."""
        self._start = self._latest_aligned_start()

    def _is_right_aligned_to_data(self) -> bool:
        """True when the viewport ends at the latest real-data edge."""
        return self.end == self._data_total

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

        # Only emit when the camera actually moved. Emitting at the boundary
        # causes avoidable repaint/contract churn without changing visible state.
        if self._start != old_start:
            self.viewport_changed.emit()

    def pan_right(self, step: int = 10) -> None:
        step = int(step)
        if step <= 0:
            return

        old_start = self._start
        max_start = self._max_start()
        self._start = min(max_start, self._start + step)

        # Only emit when the camera actually moved. Emitting at the boundary
        # causes avoidable repaint/contract churn without changing visible state.
        if self._start != old_start:
            self.viewport_changed.emit()

    def set_crosshair(self, index: int | None) -> None:
        """Set the current crosshair index.

        Crosshair movement is not a camera move. Emitting viewport_changed
        here causes heavy viewport-driven refresh paths to fire on every
        mouse move. A dedicated crosshair_changed signal preserves correct
        repaint behavior without promoting crosshair motion into viewport
        ownership.
        """
        if index == self._crosshair_index:
            return
        self._crosshair_index = index
        self.crosshair_changed.emit()

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

        self._total = max(1, self._domain_size())

        max_visible = min(self.MAX_VISIBLE_BARS, self._total)
        new_visible = max(1, min(int(new_visible), max_visible))
        self._visible = new_visible

        anchor_rel = max(0.0, min(1.0, float(anchor_rel)))
        anchor_idx = max(self._min_index(), min(int(anchor_idx), self._max_index()))

        # Horizontal zoom remains camera-only. The explicit zoom anchor chooses
        # the post-zoom placement, and fixed chart-space clamps keep the camera
        # inside the workspace-owned domain. This path intentionally does not
        # special-case the latest real-data edge.
        pos = int(round(anchor_rel * max(1, new_visible - 1)))
        new_start = anchor_idx - pos
        new_start = max(self._min_start(), min(new_start, self._max_start()))
        self._start = new_start

        if self._crosshair_index is not None and not self._crosshair_index_is_valid(self._crosshair_index):
            self._crosshair_index = None

        if (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()
