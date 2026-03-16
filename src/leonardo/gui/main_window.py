from __future__ import annotations

from typing import Optional
from concurrent.futures import Future

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QMainWindow

from leonardo.core.context import AppContext
from leonardo.core.registry_keys import SVC_GUI_WINDOW_MANAGER
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.workspace import ChartWorkspaceWidget, OscillatorSpec


class MainWindow(QMainWindow):
    def __init__(self, core_bridge: CoreBridge) -> None:
        super().__init__()
        self._feed_future: Optional[Future[object]] = None

        self._core = core_bridge
        self._ctx_ref: Optional[AppContext] = None  # set in on_core_started()

        self.setWindowTitle("Leonardo")
        self.resize(1200, 800)

        # Central chart workspace
        self._workspace = ChartWorkspaceWidget(self)
        self.setCentralWidget(self._workspace)
        self._workspace.set_asset_label("Disconnected")

        # Status bar
        self.statusBar().showMessage("Ready")
        self._core.status_changed.connect(self._on_status_changed)

        # chart data updates from core -> GUI
        if hasattr(self._core, "chart_snapshot"):
            self._core.chart_snapshot.connect(self._on_chart_snapshot)  # type: ignore[attr-defined]
        if hasattr(self._core, "chart_patch"):
            self._core.chart_patch.connect(self._on_chart_patch)  # type: ignore[attr-defined]

        # Menu bar
        mb = self.menuBar()
        menu1 = mb.addMenu("menu1")
        menu2 = mb.addMenu("menu2")
        menu3 = mb.addMenu("menu3")

        # ---- Chart actions ----
        self._act_toggle_volume = QAction("Toggle Volume", self, checkable=True)
        self._act_toggle_volume.triggered.connect(self._on_toggle_volume)
        menu1.addAction(self._act_toggle_volume)

        self._act_add_rsi = QAction("Add RSI(14)", self)
        self._act_add_rsi.triggered.connect(lambda: self._add_osc("rsi_14", "RSI(14)"))
        menu1.addAction(self._act_add_rsi)

        self._act_add_macd = QAction("Add MACD(12,26,9)", self)
        self._act_add_macd.triggered.connect(lambda: self._add_osc("macd_12_26_9", "MACD(12,26,9)"))
        menu1.addAction(self._act_add_macd)

        self._act_clear_osc = QAction("Clear Oscillators", self)
        self._act_clear_osc.triggered.connect(self._clear_osc)
        menu1.addAction(self._act_clear_osc)

        menu1.addSeparator()

        # ---- Realtime + Signals actions ----
        self._act_start_rt = QAction("Start Realtime", self)
        self._act_start_rt.setEnabled(False)
        self._act_start_rt.triggered.connect(self._start_realtime)
        menu1.addAction(self._act_start_rt)

        self._act_stop_rt = QAction("Stop Realtime", self)
        self._act_stop_rt.setEnabled(False)
        self._act_stop_rt.triggered.connect(self._stop_realtime)
        menu1.addAction(self._act_stop_rt)

        menu1.addSeparator()

        self._act_open_signals = QAction("Open Trading Signals", self)
        self._act_open_signals.setEnabled(False)
        self._act_open_signals.triggered.connect(self._open_signals)
        menu1.addAction(self._act_open_signals)

        menu1.addSeparator()

        self._act_open_windows_inspector = QAction("Open Windows Inspector", self)
        self._act_open_windows_inspector.setEnabled(False)
        self._act_open_windows_inspector.triggered.connect(self._open_windows_inspector)
        menu1.addAction(self._act_open_windows_inspector)

        # ---- Zoom mode ----
        self._act_anchor_zoom = QAction("Anchor Zoom", self, checkable=True)
        self._act_anchor_zoom.setChecked(self._workspace.viewport.anchor_zoom_enabled)
        self._act_anchor_zoom.triggered.connect(self._on_anchor_zoom_toggled)
        menu2.addAction(self._act_anchor_zoom)

        # ---- Menu3: Historical tools ----
        self._act_open_hist_download = QAction("Historical Download Manager", self)
        self._act_open_hist_download.setEnabled(False)
        self._act_open_hist_download.triggered.connect(self._open_historical_download_manager)
        menu3.addAction(self._act_open_hist_download)

        self._act_open_hist_manager = QAction("Historical Data Manager", self)
        self._act_open_hist_manager.setEnabled(False)
        self._act_open_hist_manager.triggered.connect(self._open_historical_data_manager)
        menu3.addAction(self._act_open_hist_manager)

        # Studies overlay (kept)
        self._workspace.set_studies_labels(indicators=[], oscillators=[])

        # Audit polling (optional)
        self._audit_timer = QTimer(self)
        self._audit_timer.setInterval(750)
        self._audit_timer.timeout.connect(self._poll_audit_snapshot)
        self._audit_timer.start()

        # Track active studies for overlay
        self._active_indicators: list[str] = []
        self._active_oscillators: list[str] = []

    # Called by gui/app.py after core.start() + services registered
    def on_core_started(self) -> None:
        self._act_open_windows_inspector.setEnabled(True)
        self._act_open_hist_download.setEnabled(True)
        self._act_open_hist_manager.setEnabled(True)

        self._ctx_ref = self._core.context
        self._core.submit(self._ctx().state.window_open("main", "MainWindow", where="gui"))
        self._sync_realtime_ui()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.statusBar().showMessage("Shutting down...")
        self._audit_timer.stop()
        try:
            self._core.submit(self._ctx().state.window_close("main", where="gui"))
        except Exception:
            pass
        self._core.stop()
        super().closeEvent(event)

    # ---- Internals ----

    def _ctx(self) -> AppContext:
        if self._ctx_ref is None:
            raise RuntimeError("Core not started yet; AppContext unavailable")
        return self._ctx_ref

    def _wm(self):
        if self._ctx_ref is not None:
            wm = self._ctx().registry.get(SVC_GUI_WINDOW_MANAGER)
            if wm is not None:
                return wm

        wm = getattr(self, "window_manager", None)
        if wm is None:
            wm = getattr(self._core, "window_manager", None)
        return wm

    # ---- Status/audit ----

    @Slot(str)
    def _on_status_changed(self, text: str) -> None:
        self.statusBar().showMessage(text)

    @Slot()
    def _poll_audit_snapshot(self) -> None:
        snap = self._core.try_get_audit_snapshot()
        if not snap:
            return
        pass

    # ---- Chart data updates (core -> GUI) ----

    @Slot(object)
    def _on_chart_snapshot(self, snapshot: object) -> None:
        if hasattr(self._workspace, "apply_snapshot"):
            self._workspace.apply_snapshot(snapshot)  # type: ignore[attr-defined]

    @Slot(object)
    def _on_chart_patch(self, patch: object) -> None:
        if hasattr(self._workspace, "apply_patch"):
            self._workspace.apply_patch(patch)  # type: ignore[attr-defined]

    # ---- Chart actions ----

    @Slot(bool)
    def _on_toggle_volume(self, enabled: bool) -> None:
        self._workspace.set_volume_enabled(enabled)

    def _add_osc(self, key: str, title: str) -> None:
        self._workspace.add_oscillator(OscillatorSpec(key=key, title=title))
        if title not in self._active_oscillators:
            self._active_oscillators.append(title)
        self._workspace.set_studies_labels(self._active_indicators, self._active_oscillators)

    def _clear_osc(self) -> None:
        self._workspace.clear_oscillators()
        self._active_oscillators.clear()
        self._workspace.set_studies_labels(self._active_indicators, self._active_oscillators)

    # ---- Zoom mode handler ----

    def _on_anchor_zoom_toggled(self, enabled: bool) -> None:
        self._workspace.set_anchor_zoom_enabled(enabled)

    # ---- Windows Inspector handler ----

    def _open_windows_inspector(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_windows_inspector()

    # ---- Menu3: Historical handlers ----

    def _open_historical_download_manager(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_historical_download_manager(core_bridge=self._core, parent=self)

    def _open_historical_data_manager(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_historical_data_manager(core_bridge=self._core, parent=self)
        self.statusBar().showMessage("Historical Data Manager opened")

    # ---- Realtime + Signals (registry/state driven) ----

    def _is_realtime_active(self) -> bool:
        return self._ctx().state.is_realtime_active()

    def _sync_realtime_ui(self) -> None:
        active = self._is_realtime_active()
        self._act_start_rt.setEnabled(not active)
        self._act_stop_rt.setEnabled(active)
        self._act_open_signals.setEnabled(active)

    def _start_realtime(self) -> None:
        self._core.submit(self._ctx().state.set_realtime_active(True, where="gui"))
        self.statusBar().showMessage("Streaming")
        self._sync_realtime_ui()

        if self._feed_future is None or self._feed_future.done():
            from leonardo.core.market_data.bybit_feed import run_bybit_chart_feed

            self._feed_future = self._core.submit(
                run_bybit_chart_feed(
                    bridge=self._core,
                    market="linear",
                    symbol="BTCUSDT",
                    timeframe="30m",
                    limit=200,
                    testnet=False,
                )
            )

        wm = self._wm()
        if wm is not None:
            win = wm.get_signals()
            if win is not None:
                win.set_streaming(True)

    def _stop_realtime(self) -> None:
        self._core.submit(self._ctx().state.set_realtime_active(False, where="gui"))
        self.statusBar().showMessage("Ready")
        self._sync_realtime_ui()

        if self._feed_future is not None and not self._feed_future.done():
            self._feed_future.cancel()
        self._feed_future = None

        wm = self._wm()
        if wm is not None:
            win = wm.get_signals()
            if win is not None:
                win.set_streaming(False)

    def _open_signals(self) -> None:
        if not self._is_realtime_active():
            self.statusBar().showMessage("Signals available only while realtime is active")
            self._sync_realtime_ui()
            return

        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return

        win = wm.open_signals()
        win.set_streaming(True)