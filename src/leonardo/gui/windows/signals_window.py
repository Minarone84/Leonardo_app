from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QProgressBar,
    QDial,
)


class SignalsWindow(QMainWindow):
    """
    Trading Signals window (dummy Phase 0):
    - Menu bar placeholders: A / B / C
    - Status bar
    - Dummy widgets: vertical bars + dials
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Leonardo — Trading Signals")
        self.resize(900, 600)

        # Menu placeholders
        mb = self.menuBar()
        mb.addMenu("A")
        mb.addMenu("B")
        mb.addMenu("C")

        # Status bar
        self.statusBar().showMessage("Stopped")

        # Central
        root = QWidget(self)
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)

        title = QLabel("Trading Signals (dummy)", root)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        main.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(18)
        main.addLayout(grid)

        # --- Left: vertical bars (audio-meter style) ---
        bars_box = QWidget(root)
        bars_layout = QHBoxLayout(bars_box)
        bars_layout.setContentsMargins(0, 0, 0, 0)
        bars_layout.setSpacing(10)

        self._bars: list[QProgressBar] = []
        for _ in range(10):
            pb = QProgressBar(bars_box)
            pb.setRange(0, 100)
            pb.setValue(0)
            pb.setTextVisible(False)
            pb.setOrientation(Qt.Vertical)
            pb.setFixedHeight(260)
            pb.setFixedWidth(18)
            pb.setStyleSheet(
                "QProgressBar { border: 1px solid #444; background: #111; }"
                "QProgressBar::chunk { background: #2aa198; }"
            )
            self._bars.append(pb)
            bars_layout.addWidget(pb)

        grid.addWidget(QLabel("Signal Strength (bars)"), 0, 0)
        grid.addWidget(bars_box, 1, 0)

        # --- Right: speedometer-like dials ---
        dials_box = QWidget(root)
        dials_layout = QHBoxLayout(dials_box)
        dials_layout.setContentsMargins(0, 0, 0, 0)
        dials_layout.setSpacing(24)

        self._dials: list[QDial] = []
        self._dial_labels: list[QLabel] = []

        for name in ("Momentum", "Risk"):
            col = QWidget(dials_box)
            col_l = QVBoxLayout(col)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(6)

            lab = QLabel(name, col)
            lab.setAlignment(Qt.AlignHCenter)

            dial = QDial(col)
            dial.setRange(0, 100)
            dial.setNotchesVisible(True)
            dial.setEnabled(False)  # display-only for now

            val = QLabel("0", col)
            val.setAlignment(Qt.AlignHCenter)
            val.setStyleSheet("font-family: Consolas; font-size: 14px;")

            self._dials.append(dial)
            self._dial_labels.append(val)

            col_l.addWidget(lab)
            col_l.addWidget(dial)
            col_l.addWidget(val)

            dials_layout.addWidget(col)

        grid.addWidget(QLabel("Aggregates (dials)"), 0, 1)
        grid.addWidget(dials_box, 1, 1)

        # Dummy update timer (owner controls start/stop via set_streaming)
        self._rng = random.Random(42)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        # NOTE: do not start timer here

        # Ensure visuals reflect "Stopped" on creation
        self._reset_visuals()

    def set_streaming(self, active: bool) -> None:
        self.statusBar().showMessage("Streaming" if active else "Stopped")

        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            if self._timer.isActive():
                self._timer.stop()
            self._reset_visuals()

    def _reset_visuals(self) -> None:
        for b in self._bars:
            b.setValue(0)

        for dial, val in zip(self._dials, self._dial_labels):
            dial.setValue(0)
            val.setText("0")

    def _tick(self) -> None:
        # Dummy animation (replace later with real signal inputs)
        for b in self._bars:
            b.setValue(self._rng.randint(0, 100))

        for dial, val in zip(self._dials, self._dial_labels):
            x = self._rng.randint(0, 100)
            dial.setValue(x)
            val.setText(str(x))
