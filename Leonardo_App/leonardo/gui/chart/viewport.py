from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QRectF


class ChartViewport(QObject):
    viewport_changed = Signal()

    def __init__(self, total_count: int, visible_count: int = 120) -> None:
        super().__init__()
        self._total = max(1, total_count)
        self._visible = min(visible_count, self._total)
        self._start = self._total - self._visible
        self._crosshair_index: int | None = None

        # NEW: make this explicit (no getattr-based state)
        self._anchor_zoom_enabled: bool = True

    @property
    def total(self) -> int:
        return self._total

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

    def set_total(self, total: int) -> None:
        self._total = max(1, total)
        self._visible = min(self._visible, self._total)
        self._start = max(0, min(self._start, self._total - self._visible))
        self.viewport_changed.emit()

    def pan_left(self, step: int = 10) -> None:
        self._start = max(0, self._start - step)
        self.viewport_changed.emit()

    def pan_right(self, step: int = 10) -> None:
        self._start = min(self._total - self._visible, self._start + step)
        self.viewport_changed.emit()

    def set_crosshair(self, index: int | None) -> None:
        if index == self._crosshair_index:
            return
        self._crosshair_index = index
        self.viewport_changed.emit()

    def index_from_x(self, plot: QRectF, x: float) -> int:
        start, end = self.start, self.end
        n = max(1, end - start)
        if plot.width() <= 1:
            return start
        t = (x - plot.left()) / plot.width()
        rel = int(round(t * (n - 1)))
        rel = max(0, min(n - 1, rel))
        return start + rel

    def x_from_index(self, plot: QRectF, idx: int) -> float:
        start, end = self.start, self.end
        n = max(1, end - start)
        idx = max(start, min(end - 1, idx))
        if n <= 1 or plot.width() <= 1:
            return plot.left()
        rel = idx - start
        t = rel / (n - 1)
        return plot.left() + t * plot.width()

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
        new_visible = max(1, min(new_visible, self._total))

        if anchor_rel < 0.0:
            anchor_rel = 0.0
        elif anchor_rel > 1.0:
            anchor_rel = 1.0

        anchor_idx = max(0, min(self._total - 1, anchor_idx))

        pos = int(round(anchor_rel * max(1, new_visible - 1)))

        new_start = anchor_idx - pos
        new_start = max(0, min(new_start, self._total - new_visible))

        changed = (new_visible != self._visible) or (new_start != self._start)
        self._visible = new_visible
        self._start = new_start

        if changed:
            self.viewport_changed.emit()

    # ---------------------------
    # Anchor zoom toggle
    # ---------------------------

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._anchor_zoom_enabled == enabled:
            return
        self._anchor_zoom_enabled = enabled
        self.viewport_changed.emit()

    @property
    def anchor_zoom_enabled(self) -> bool:
        return self._anchor_zoom_enabled
