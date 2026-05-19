from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout


def make_button_rack(*buttons: QPushButton) -> QVBoxLayout:
    """Return a right-side vertical rack for widget action buttons.

    The rack preserves each button's normal/default height and pushes unused
    vertical space below the actions instead of stretching the buttons.
    """
    rack = QVBoxLayout()
    rack.setContentsMargins(0, 0, 0, 0)
    rack.setSpacing(8)
    for button in buttons:
        rack.addWidget(button)
    rack.addStretch(1)
    return rack
