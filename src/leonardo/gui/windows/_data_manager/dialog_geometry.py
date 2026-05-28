"""Shared Data Manager dialog geometry helpers."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog


DATA_MANAGER_DIALOG_INITIAL_WIDTH_RATIO = 0.60


def apply_data_manager_dialog_initial_width(
    dialog: QDialog,
    *,
    default_width: int,
    default_height: int,
    width_ratio: float = DATA_MANAGER_DIALOG_INITIAL_WIDTH_RATIO,
) -> None:
    """
    Apply the Data Manager dialog initial sizing policy.

    The initial width is based on the available screen geometry while existing
    minimum-size constraints remain authoritative. The default height preserves
    the caller's prior intended opening height unless the available screen is
    smaller than that height.
    """

    screen = _screen_for_dialog(dialog)
    if screen is None:
        dialog.resize(default_width, default_height)
        return

    available = screen.availableGeometry()
    if not available.isValid():
        dialog.resize(default_width, default_height)
        return

    preferred_width = int(available.width() * width_ratio)
    width = _bounded_dimension(
        preferred_width,
        minimum=dialog.minimumWidth(),
        maximum=available.width(),
    )
    height = _bounded_dimension(
        min(default_height, available.height()),
        minimum=dialog.minimumHeight(),
        maximum=available.height(),
    )
    left = available.left() + (available.width() - width) // 2
    top = available.top() + (available.height() - height) // 2

    dialog.resize(width, height)
    dialog.move(left, top)
    QTimer.singleShot(
        0,
        lambda: _fit_dialog_frame_inside_available_geometry(dialog, screen),
    )


def _screen_for_dialog(dialog: QDialog) -> Any | None:
    parent = dialog.parentWidget()
    if parent is not None:
        screen = parent.screen()
        if screen is not None:
            return screen

    screen = dialog.screen()
    if screen is not None:
        return screen

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    return app.primaryScreen()


def _bounded_dimension(value: int, *, minimum: int, maximum: int) -> int:
    if maximum >= minimum:
        return min(max(minimum, value), maximum)
    return max(minimum, value)


def _fit_dialog_frame_inside_available_geometry(dialog: QDialog, screen: Any) -> None:
    available = screen.availableGeometry()
    if not available.isValid():
        return

    frame = dialog.frameGeometry()
    if not frame.isValid():
        return

    width = dialog.width()
    height = dialog.height()
    frame_width_delta = max(0, frame.width() - dialog.width())
    frame_height_delta = max(0, frame.height() - dialog.height())

    if frame.width() > available.width():
        width = _bounded_dimension(
            available.width() - frame_width_delta,
            minimum=dialog.minimumWidth(),
            maximum=available.width(),
        )
    if frame.height() > available.height():
        height = _bounded_dimension(
            available.height() - frame_height_delta,
            minimum=dialog.minimumHeight(),
            maximum=available.height(),
        )
    if width != dialog.width() or height != dialog.height():
        dialog.resize(width, height)
        frame = dialog.frameGeometry()

    target_left = available.left() + (available.width() - frame.width()) // 2
    target_top = available.top() + (available.height() - frame.height()) // 2

    if frame.left() < available.left():
        target_left = available.left()
    if frame.right() > available.right():
        target_left = min(target_left, available.right() - frame.width() + 1)
    target_left = max(available.left(), target_left)

    if frame.top() < available.top():
        target_top = available.top()
    if frame.bottom() > available.bottom():
        target_top = min(target_top, available.bottom() - frame.height() + 1)
    target_top = max(available.top(), target_top)

    current_frame = dialog.frameGeometry()
    dialog.move(
        dialog.x() + target_left - current_frame.left(),
        dialog.y() + target_top - current_frame.top(),
    )
