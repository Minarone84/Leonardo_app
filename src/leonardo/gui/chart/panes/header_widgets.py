from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

class _PaneOverlay(QWidget):
    """
    Generic floating overlay container.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)

        self.setStyleSheet(
            "QWidget { background: rgba(0, 0, 0, 90); border-radius: 6px; }"
            "QLabel { color: white; }"
            "QToolButton {"
            "  color: white;"
            "  background: rgba(255, 255, 255, 22);"
            "  border: 1px solid rgba(255, 255, 255, 40);"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "}"
            "QToolButton:hover {"
            "  background: rgba(255, 255, 255, 36);"
            "}"
            "QToolButton:disabled {"
            "  color: rgba(255, 255, 255, 90);"
            "  background: rgba(255, 255, 255, 10);"
            "  border: 1px solid rgba(255, 255, 255, 20);"
            "}"
        )

    @property
    def layout_box(self) -> QVBoxLayout:
        return self._layout

    def anchor_top_left(self, *, margin: int = 12) -> None:
        """Size and anchor this floating pane overlay to the top-left corner."""
        resolved_margin = max(0, int(margin))
        self.adjustSize()
        self.move(resolved_margin, resolved_margin)

class _HeaderInfoBlock(QWidget):
    """
    Title + OHLC block used at the top of the price overlay card.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        self._title = QLabel("", self)
        self._line1 = QLabel("", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self._title)
        layout.addWidget(self._line1)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_line1(self, text: str) -> None:
        self._line1.setText(text)
