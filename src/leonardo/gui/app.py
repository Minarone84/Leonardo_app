from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from leonardo.core.registry_keys import SVC_GUI_WINDOW_MANAGER
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.main_window import MainWindow
from leonardo.gui.windows.window_manager import WindowManager


def run_gui() -> int:
    app = QApplication(sys.argv)

    core = CoreBridge()
    win = MainWindow(core_bridge=core)
    win.show()

    core.start()
    ctx = core.context

    # WindowManager is a GUI-owned QObject and is registered only after Qt
    # construction so service lookup can find it without transferring lifecycle
    # ownership to the Core application.
    win.window_manager = WindowManager(ctx=ctx, core_bridge=core, parent=win)  # type: ignore[attr-defined]
    core.window_manager = win.window_manager  # optional convenience
    ctx.register_service(SVC_GUI_WINDOW_MANAGER, win.window_manager)  # type: ignore[attr-defined]

    if hasattr(win, "on_core_started"):
        win.on_core_started()

    try:
        return app.exec()
    finally:
        core.stop()
