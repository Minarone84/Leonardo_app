from __future__ import annotations

import sys
import asyncio
from pathlib import Path

from PySide6.QtWidgets import QApplication

from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import HistoricalDatasetService
from leonardo.gui.core_bridge import CoreBridge
from leonardo.core.config import load_config
from leonardo.gui.main_window import MainWindow
from leonardo.gui.windows.window_manager import WindowManager


def run_gui() -> int:
    app = QApplication(sys.argv)

    core = CoreBridge()
    win = MainWindow(core_bridge=core)
    win.show()

    core.start()
    ctx = core.context

    # Register historical dataset service on the CORE loop (thread-safe)
    async def _core_register_dataset_service() -> None:
        if ctx.registry.get(SVC_HISTORICAL_DATASET) is None:
            cfg = load_config()
            ctx.registry.set(
                SVC_HISTORICAL_DATASET,
                HistoricalDatasetService(
                    data_root=Path(cfg.runtime.data_dir),
                    slice_cache_entries=256,
                ),
            )

    core.submit(_core_register_dataset_service())

    # GUI-owned WindowManager (must live in GUI thread)
    win.window_manager = WindowManager(ctx=ctx, core_bridge=core, parent=win)  # type: ignore[attr-defined]
    core.window_manager = win.window_manager  # optional convenience

    if hasattr(win, "on_core_started"):
        win.on_core_started()

    try:
        return app.exec()
    finally:
        core.stop()