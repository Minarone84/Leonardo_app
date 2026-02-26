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

    if ctx.registry.get(SVC_GUI_WINDOW_MANAGER) is None:
        ctx.register_service(
            SVC_GUI_WINDOW_MANAGER,
            WindowManager(ctx=ctx, core_bridge=core, parent=win),
        )

    if hasattr(win, "on_core_started"):
        win.on_core_started()

    try:
        return app.exec()
    finally:
        core.stop()
