from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QMainWindow

from leonardo.core.context import AppContext
from leonardo.core.registry_keys import SVC_GUI_WINDOW_MANAGER
from leonardo.gui.chart.workspace import ChartWorkspaceWidget, OscillatorSpec
from leonardo.gui.core_bridge import CoreBridge


class MainWindow(QMainWindow):
    """Temporary GUI entry point for Leonardo.

    IMPORTANT:
        This window is currently acting as a test harness in disguise.

        It exists primarily to:
        - validate Core ↔ GUI integration
        - manually trigger realtime feeds
        - visually inspect chart updates and runtime behavior

    Architectural status:
        This is NOT the final connection management UI.

        In later phases, connection lifecycle (start/stop/status/inspection)
        will be handled by a dedicated window or subsystem. At that point:

        - connection orchestration should NOT live here
        - feed triggering should NOT be initiated from menu actions
        - this window should become a pure workspace/view layer

    Design constraints (must remain true):
        - No runtime truth should be owned here (StateStore is authoritative)
        - No connection lifecycle logic beyond simple triggering
        - No direct adapter manipulation

    In short:
        Treat this file as a controlled integration surface, not a foundation.
    """

    def __init__(self, core_bridge: CoreBridge) -> None:
        super().__init__()
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
        self._core.realtime_state_changed.connect(self._on_realtime_state_changed)

        # chart data updates from core -> GUI
        if hasattr(self._core, "chart_snapshot"):
            self._core.chart_snapshot.connect(self._on_chart_snapshot)  # type: ignore[attr-defined]
        if hasattr(self._core, "chart_patch"):
            self._core.chart_patch.connect(self._on_chart_patch)  # type: ignore[attr-defined]

        # Menu bar
        mb = self.menuBar()
        menu1 = mb.addMenu("menu1")
        menu2 = mb.addMenu("Analysis")
        historical_menu = mb.addMenu("Historical")

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

        self._act_open_runtime_inspector = QAction("Open Runtime Inspector", self)
        self._act_open_runtime_inspector.setEnabled(False)
        self._act_open_runtime_inspector.triggered.connect(self._open_runtime_inspector)
        menu1.addAction(self._act_open_runtime_inspector)

        # ---- Analysis actions ----
        self._act_open_data_manager = QAction("Data Manager", self)
        self._act_open_data_manager.setEnabled(False)
        self._act_open_data_manager.triggered.connect(self._open_data_manager)
        menu2.addAction(self._act_open_data_manager)

        # ---- Historical tools ----
        self._act_open_hist_download = QAction("Historical Download Manager", self)
        self._act_open_hist_download.setEnabled(False)
        self._act_open_hist_download.triggered.connect(self._open_historical_download_manager)
        historical_menu.addAction(self._act_open_hist_download)

        self._act_open_ohlcv_maintenance = QAction("OHLCV Maintenance...", self)
        self._act_open_ohlcv_maintenance.setEnabled(False)
        self._act_open_ohlcv_maintenance.triggered.connect(self._open_ohlcv_maintenance)
        historical_menu.addAction(self._act_open_ohlcv_maintenance)

        self._act_open_hist_manager = QAction("Research Suite", self)
        self._act_open_hist_manager.setEnabled(False)
        self._act_open_hist_manager.triggered.connect(self._open_historical_data_manager)
        historical_menu.addAction(self._act_open_hist_manager)

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
        self._act_open_runtime_inspector.setEnabled(True)
        self._act_open_data_manager.setEnabled(True)
        self._act_open_hist_download.setEnabled(True)
        self._act_open_ohlcv_maintenance.setEnabled(True)
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

    @Slot(bool)
    def _on_realtime_state_changed(self, active: bool) -> None:
        """Refresh temporary realtime-related GUI affordances.

        The window remains a temporary interaction surface, but it no longer
        owns feed futures or direct feed lifecycle actions. This slot keeps the
        local UI in sync with the explicit bridge-owned Core command surface.
        """
        self._sync_realtime_ui()

        wm = self._wm()
        if wm is None:
            return

        win = wm.get_signals()
        if win is not None:
            win.set_streaming(active)

        # --- Phase 4: clear chart on realtime stop ---
        if not active:
            try:
                if hasattr(self._workspace, "model"):
                    self._workspace.model.set_candles([])
                    self._workspace.model.set_volume([])

                if hasattr(self._workspace, "clear_financial_tools"):
                    self._workspace.clear_financial_tools()

                # Optional but recommended: reset label
                self._workspace.set_asset_label("Disconnected")

                if hasattr(self._workspace.viewport, "set_total_count"):
                    self._workspace.viewport.set_total_count(0)

                # Force repaint so UI actually updates
                if hasattr(self._workspace, "_refresh_price_pane"):
                    self._workspace._refresh_price_pane()

            except Exception as e:
                print("Failed to clear workspace on realtime stop:", repr(e))

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

    # ---- Analysis handlers ----

    def _open_data_manager(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_data_manager(parent=self)
        self.statusBar().showMessage("Data Manager opened")

    # ---- Runtime Inspector handler ----

    def _open_runtime_inspector(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Runtime window manager missing")
            return
        
        # Prefer new API if available, fallback to legacy for compatibility
        if hasattr(wm, "open_runtime_inspector"):
            wm.open_runtime_inspector()
        else:
            wm.open_windows_inspector()

    # ---- Historical handlers ----

    def _open_historical_download_manager(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_historical_download_manager(core_bridge=self._core, parent=self)

    def _open_ohlcv_maintenance(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_ohlcv_maintenance(parent=self)
        self.statusBar().showMessage("OHLCV Maintenance opened")

    def _open_historical_data_manager(self) -> None:
        wm = self._wm()
        if wm is None:
            self.statusBar().showMessage("Window manager missing")
            return
        wm.open_historical_data_manager(core_bridge=self._core, parent=self)
        self.statusBar().showMessage("Research Suite opened")

    # ---- Realtime + Signals (state-driven GUI) ----

    def _is_realtime_active(self) -> bool:
        return self._ctx().state.is_realtime_active()

    def _sync_realtime_ui(self) -> None:
        active = self._is_realtime_active()
        self._act_start_rt.setEnabled(not active)
        self._act_stop_rt.setEnabled(active)
        self._act_open_signals.setEnabled(active)

    def _start_realtime(self) -> None:
        """Request realtime startup through the Core bridge.

        This window remains a temporary integration surface, but direct feed
        task creation now lives behind the explicit GUI → Core bridge boundary
        introduced in Phase 4.
        """
        self._core.start_realtime_feed(
            market="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            limit=200,
            testnet=False,
        )

    def _stop_realtime(self) -> None:
        """Request realtime shutdown through the Core bridge."""
        self._core.stop_realtime_feed()

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
