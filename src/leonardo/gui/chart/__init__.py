from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout


class _PlaceholderRenderSurface(QFrame):
    """
    Placeholder for the custom renderer you will build later.
    Keeps the UI structure stable while you iterate.
    """
    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Sunken)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        msg = QLabel(label, self)
        msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg)


class _TopLeftOverlay(QWidget):
    """
    Floating overlay container (asset + studies) to be placed inside the PricePane.
    """
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._asset = QLabel("—", self)
        self._studies = QLabel("", self)

        # readable overlay; you can style later
        for lab in (self._asset, self._studies):
            lab.setTextInteractionFlags(Qt.NoTextInteraction)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        layout.addWidget(self._asset)
        layout.addWidget(self._studies)

        # mild background so it’s readable (can be replaced with stylesheets later)
        self.setStyleSheet(
            "QWidget { background: rgba(0, 0, 0, 90); border-radius: 6px; }"
            "QLabel { color: white; }"
        )

    def set_asset(self, text: str) -> None:
        self._asset.setText(text)

    def set_studies(self, indicators: List[str], oscillators: List[str]) -> None:
        ind = ", ".join(indicators) if indicators else "—"
        osc = ", ".join(oscillators) if oscillators else "—"
        self._studies.setText(f"Indicators: {ind}\nOsc: {osc}")


class PricePane(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._surface = _PlaceholderRenderSurface("PRICE CHART (placeholder renderer)", self)
        self._overlay = _TopLeftOverlay(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        # Initial overlay content
        self._overlay.set_asset("ASSET · TF")
        self._overlay.set_studies([], [])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Position overlay in top-left inside the pane
        self._overlay.move(12, 12)
        self._overlay.adjustSize()

    def set_asset_label(self, text: str) -> None:
        self._overlay.set_asset(text)
        self._overlay.adjustSize()

    def set_studies(self, indicators: List[str], oscillators: List[str]) -> None:
        self._overlay.set_studies(indicators, oscillators)
        self._overlay.adjustSize()


class VolumePane(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_PlaceholderRenderSurface("VOLUME (placeholder)", self))


class OscillatorPane(QWidget):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_PlaceholderRenderSurface(f"OSCILLATOR: {title} (placeholder)", self))
