from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal


class Crosshair(QObject):
    """
    Shared crosshair state:

    - index is shared across all panes (price/volume/osc) -> vertical line.
    - hover_on_price is used only to decide whether the PRICE pane should draw
      its horizontal line at mouse Y (true cross on chart).
    """
    changed = Signal()
    cleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._active: bool = False
        self._index: Optional[int] = None
        self._hover_on_price: bool = False

    @property
    def active(self) -> bool:
        return self._active and self._index is not None

    @property
    def index(self) -> Optional[int]:
        return self._index

    @property
    def hover_on_price(self) -> bool:
        return self._hover_on_price

    def set_index(self, idx: int) -> None:
        idx = int(idx)
        if self._active and self._index == idx:
            return
        self._active = True
        self._index = idx
        self.changed.emit()

    def set_hover_on_price(self, hover: bool) -> None:
        hover = bool(hover)
        if self._hover_on_price == hover:
            return
        self._hover_on_price = hover
        self.changed.emit()

    def clear(self) -> None:
        if not self._active and self._index is None and not self._hover_on_price:
            return
        self._active = False
        self._index = None
        self._hover_on_price = False
        self.cleared.emit()