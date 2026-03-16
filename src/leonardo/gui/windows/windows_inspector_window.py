from __future__ import annotations

from typing import Optional, Dict, Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
)

from leonardo.core.context import AppContext
from leonardo.gui.core_bridge import CoreBridge


class WindowsInspectorWindow(QMainWindow):
    """
    Displays the live registry-truth view of open windows.
    Reads snapshot via core loop (thread-safe) and renders in GUI.
    """

    def __init__(self, *, ctx: AppContext, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._core = core_bridge

        self.setWindowTitle("Leonardo — Windows Inspector")
        self.resize(700, 400)

        self.statusBar().showMessage("Ready")

        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Name", "Type", "Open"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self._table)

        # Poll timer
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        # Initial paint
        self.refresh()

    def closeEvent(self, event) -> None:
        if self._timer.isActive():
            self._timer.stop()
        super().closeEvent(event)

    def refresh(self) -> None:
        """
        Fetch snapshot on core loop (thread-safe), then render.
        """
        async def _snap() -> Dict[str, Dict[str, Any]]:
            # windows_state() returns a copy (good)
            return self._ctx.state.windows_state()

        try:
            fut = self._core.submit(_snap())
            snap = fut.result(timeout=0.2)
        except Exception:
            # Core stopping or busy. Keep last view.
            return

        self._render(snap)

    def _render(self, snap: Dict[str, Dict[str, Any]]) -> None:
        rows = list(snap.values())
        rows.sort(key=lambda d: str(d.get("name", "")))

        self._table.setRowCount(len(rows))

        for r, meta in enumerate(rows):
            name = str(meta.get("name", ""))
            typ = str(meta.get("type", ""))
            is_open = bool(meta.get("is_open", False))

            it_name = QTableWidgetItem(name)
            it_type = QTableWidgetItem(typ)
            it_open = QTableWidgetItem("YES" if is_open else "NO")

            it_open.setTextAlignment(Qt.AlignCenter)

            self._table.setItem(r, 0, it_name)
            self._table.setItem(r, 1, it_type)
            self._table.setItem(r, 2, it_open)

        self.statusBar().showMessage(f"Windows tracked: {len(rows)}")
