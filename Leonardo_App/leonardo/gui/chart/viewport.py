from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QRectF


class ChartViewport(QObject):
    viewport_changed = Signal()

    def __init__(self, total_count: int, visible_count: int = 120) -> None:
        super().__init__()

        # real candles count
        self._data_total = max(0, int(total_count))
        # how many empty slots to the right (future)
        self._future_pad = 0

        # total slots shown on x axis (real + future)
        self._total = max(1, self._data_total + self._future_pad)

        self._visible = max(1, min(int(visible_count), self._total))
        self._start = max(0, self._total - self._visible)

        self._crosshair_index: int | None = None

        # anchored zoom default ON
        self._anchor_zoom_enabled: bool = True

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

        # When enabling anchor, snap view to latest real candle.
        if enabled:
            self._snap_right_to_data()

        self.viewport_changed.emit()

    @property
    def anchor_zoom_enabled(self) -> bool:
        return self._anchor_zoom_enabled

    # ---------------------------
    # totals / future padding
    # ---------------------------

    def set_future_padding(self, n: int) -> None:
        self._future_pad = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=not self._anchor_zoom_enabled)

    def set_total(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=not self._anchor_zoom_enabled)

    def set_total_preserve_position(self, total: int) -> None:
        self._data_total = max(0, int(total))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_total_count(self, n: int) -> None:
        """
        Workspace calls this after snapshot/append.
        - If anchor is ON: keep right-aligned to latest candle (Bybit-like).
        - If anchor is OFF: preserve the user's position (allow future).
        """
        self._data_total = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=not self._anchor_zoom_enabled)

    def set_total_count_preserve_position(self, n: int) -> None:
        """
        Historical-mode helper:
        preserve the current viewport position regardless of anchor setting.
        """
        self._data_total = max(0, int(n))
        self._recompute_total_and_clamp(preserve_position=True)

    def set_window(self, start: int, end: int) -> None:
        old_visible = self._visible
        old_start = self._start

        start_i = max(0, int(start))
        end_i = max(start_i + 1, int(end))

        end_i = min(end_i, self._total)
        start_i = max(0, min(start_i, end_i - 1))

        visible = max(1, end_i - start_i)
        visible = min(visible, self._total)
        start_i = max(0, min(start_i, self._total - visible))

        self._visible = visible
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

        self._total = max(1, self._data_total + self._future_pad)

        if self._visible <= 1 and self._data_total > 1:
            self._visible = min(120, self._total)
        else:
            self._visible = max(1, min(self._visible, self._total))

        if preserve_position:
            self._start = max(0, min(self._start, self._total - self._visible))
        else:
            self._snap_right_to_data()

        if self._crosshair_index is not None and not (0 <= self._crosshair_index < self._total):
            self._crosshair_index = None

        if (self._total != old_total) or (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()

    def _snap_right_to_data(self) -> None:
        """
        Anchored behavior: right edge of the window sits on the last REAL candle slot,
        leaving future_pad as empty space to the right.
        """
        if self._data_total <= 0:
            self._start = 0
            self._visible = max(1, min(self._visible, self._total))
            return

        # Right edge should be exactly data_total (exclusive)
        end = self._data_total
        self._start = end - self._visible

        # Clamp into legal window bounds
        self._start = max(0, min(self._start, self._total - self._visible))

    # ---------------------------
    # pan
    # ---------------------------

    def pan_left(self, step: int = 10) -> None:
        self._start = max(0, self._start - int(step))
        self.viewport_changed.emit()

    def pan_right(self, step: int = 10) -> None:
        self._start = min(self._total - self._visible, self._start + int(step))
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
        if self._visible <= 20:
            return
        new_visible = max(20, int(self._visible * 0.8))
        self._set_visible_anchored(new_visible, anchor_idx, anchor_rel)

    def zoom_out_at(self, anchor_idx: int, anchor_rel: float) -> None:
        new_visible = min(self._total, int(self._visible * 1.25))
        self._set_visible_anchored(new_visible, anchor_idx, anchor_rel)

    def _set_visible_anchored(self, new_visible: int, anchor_idx: int, anchor_rel: float) -> None:
        old_visible = self._visible
        old_start = self._start

        new_visible = max(1, min(int(new_visible), self._total))

        anchor_rel = max(0.0, min(1.0, float(anchor_rel)))
        anchor_idx = max(0, min(self._total - 1, int(anchor_idx)))

        pos = int(round(anchor_rel * max(1, new_visible - 1)))
        new_start = anchor_idx - pos
        new_start = max(0, min(new_start, self._total - new_visible))

        self._visible = new_visible
        self._start = new_start

        # If anchor mode is ON, snap right edge to data after zoom
        if self._anchor_zoom_enabled:
            self._snap_right_to_data()

        if (self._visible != old_visible) or (self._start != old_start):
            self.viewport_changed.emit()