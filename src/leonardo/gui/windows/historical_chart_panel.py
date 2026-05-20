from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRegistry,
    PANE_TARGET_OSCILLATOR,
)
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.historical_chart_controller import HistoricalChartController
from leonardo.gui.windows.financial_tools_manager_window import FinancialToolsManagerWindow
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_study_apply import (
    HistoricalChartPanelStudyApplyMixin,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_projection_bridge import (
    HistoricalChartPanelProjectionBridgeMixin,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_style import (
    HistoricalChartPanelStyleMixin,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_oscillator_policy import (
    HistoricalChartPanelOscillatorPolicyMixin,
)
from leonardo.gui.windows._historical_chart_panel.historical_chart_panel_messages import (
    HistoricalChartPanelMessagesMixin,
)


class HistoricalChartPanel(
    QFrame,
    HistoricalChartPanelStudyApplyMixin,
    HistoricalChartPanelProjectionBridgeMixin,
    HistoricalChartPanelStyleMixin,
    HistoricalChartPanelOscillatorPolicyMixin,
    HistoricalChartPanelMessagesMixin,
):
    """
    Reusable historical chart content widget.

    This widget is shell-agnostic:
    - it can live embedded inside HistoricalDataManagerWindow
    - it can be hosted inside a floating HistoricalChartWindow
    """

    detach_requested = Signal(object)
    dock_requested = Signal(object)
    close_requested = Signal(object)
    position_change_requested = Signal(object, int)

    _RENDERABLE_OUTPUT_STRUCTURES = {
        "line-series",
        "multi-line-series",
        "levels",
        "bands",
        "state",
        "events",
    }

    _NON_RENDERABLE_OUTPUT_STRUCTURES = {
        "analysis-only",
    }

    _KNOWN_OUTPUT_STRUCTURES = _RENDERABLE_OUTPUT_STRUCTURES | _NON_RENDERABLE_OUTPUT_STRUCTURES

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._core = core_bridge

        self._exchange: str = ""
        self._market_type: str = ""
        self._symbol: str = ""
        self._timeframe: str = ""

        self._is_floating: bool = False
        self._financial_tools_manager_window: Optional[FinancialToolsManagerWindow] = None
        self._study_registry = ChartStudyRegistry()
        self._study_projection_key_by_instance_id: Dict[str, str] = {}

        self._editing_study_instance_id: Optional[str] = None
        self._wired_oscillator_pane_ids: set[int] = set()
        self._is_disposed: bool = False
        self._updating_position_combo: bool = False

        self.setObjectName("historicalChartPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setStyleSheet(
            """
            QFrame#historicalChartPanel {
                border: 1px solid rgb(52, 52, 60);
                background-color: rgb(18, 18, 22);
            }
            QWidget#historicalStatusBar {
                background-color: rgb(24, 24, 28);
                border-top: 1px solid rgb(48, 48, 56);
            }
            QLabel {
                color: rgb(190, 190, 205);
                padding-left: 8px;
                padding-right: 8px;
            }
            QToolButton {
                color: rgb(220, 220, 230);
                background-color: rgb(38, 38, 44);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 4px 10px;
            }
            QToolButton:checked {
                background-color: rgb(70, 95, 140);
                border: 1px solid rgb(100, 130, 185);
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._workspace = ChartWorkspaceWidget(parent=self)
        root.addWidget(self._workspace, 1)

        self._status_bar = QWidget(self)
        self._status_bar.setObjectName("historicalStatusBar")
        self._status_bar.setFixedHeight(32)

        status_layout = QHBoxLayout(self._status_bar)
        status_layout.setContentsMargins(6, 4, 6, 4)
        status_layout.setSpacing(6)

        self._status_label = QLabel("Historical Chart", self._status_bar)
        self._status_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        status_layout.addWidget(self._status_label)

        status_layout.addStretch(1)

        self._position_label = QLabel("Position", self._status_bar)
        self._position_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        status_layout.addWidget(self._position_label)

        self._position_combo = QComboBox(self._status_bar)
        self._position_combo.setToolTip("Move this chart to workspace slot 1-8")
        for slot_number in range(1, 9):
            self._position_combo.addItem(str(slot_number), slot_number)
        self._position_combo.currentIndexChanged.connect(self._on_position_changed)
        status_layout.addWidget(self._position_combo)

        self._go_to_button = QToolButton(self._status_bar)
        self._go_to_button.setText("Go to")
        self._go_to_button.setToolTip("Center this chart on a date or datetime")
        self._go_to_button.clicked.connect(self._on_go_to_clicked)
        status_layout.addWidget(self._go_to_button)

        self._financial_tools_button = QToolButton(self._status_bar)
        self._financial_tools_button.setText("Financial Tools")
        self._financial_tools_button.setToolTip("Open the Financial Tool Manager for this chart")
        self._financial_tools_button.clicked.connect(self._on_open_financial_tools_clicked)
        status_layout.addWidget(self._financial_tools_button)

        self._float_button = QToolButton(self._status_bar)
        self._float_button.clicked.connect(self._on_float_or_dock_clicked)
        status_layout.addWidget(self._float_button)

        self._close_button = QToolButton(self._status_bar)
        self._close_button.setText("Close")
        self._close_button.setToolTip("Close this embedded chart")
        self._close_button.clicked.connect(self._on_close_clicked)
        status_layout.addWidget(self._close_button)

        self._anchor_zoom_button = QToolButton(self._status_bar)
        self._anchor_zoom_button.setText("Autoscale")
        self._anchor_zoom_button.setCheckable(True)
        self._anchor_zoom_button.setChecked(True)
        self._anchor_zoom_button.setToolTip(
            "Fit all visible price-pane data vertically in the current view. "
            "Turn off to allow manual vertical pan and zoom."
        )
        self._anchor_zoom_button.toggled.connect(self._on_anchor_zoom_toggled)
        status_layout.addWidget(self._anchor_zoom_button)

        root.addWidget(self._status_bar, 0)

        self._controller = HistoricalChartController(
            core_bridge=self._core,
            workspace=self._workspace,
            parent=self,
        )
        self._controller.error.connect(self._on_error)
        self._controller.apply_succeeded.connect(self._on_financial_tools_apply_succeeded)
        self._controller.save_succeeded.connect(self._on_financial_tools_save_succeeded)
        self._controller.save_failed.connect(self._on_financial_tools_save_failed)
        self._controller.slice_ready.connect(self._on_controller_slice_ready)

        self._workspace.set_anchor_zoom_enabled(True)
        self.set_floating(False)

        self._connect_price_pane_study_signals()

    @property
    def workspace(self) -> ChartWorkspaceWidget:
        return self._workspace

    @property
    def study_registry(self) -> ChartStudyRegistry:
        return self._study_registry

    def set_floating(self, floating: bool) -> None:
        self._is_floating = bool(floating)
        if self._is_floating:
            self._float_button.setText("Dock")
            self._float_button.setToolTip("Dock this chart back into Historical Data Manager")
            self._close_button.setToolTip("Close this floating chart")
            self._position_combo.setEnabled(False)
            self._position_combo.setToolTip("Dock this chart to change its workspace position")
        else:
            self._float_button.setText("Float")
            self._float_button.setToolTip("Detach this chart into a floating window")
            self._close_button.setToolTip("Close this embedded chart")
            self._position_combo.setEnabled(True)
            self._position_combo.setToolTip("Move this chart to workspace slot 1-8")

    def set_workspace_position(self, slot_number: int) -> None:
        if slot_number < 1 or slot_number > 8:
            return

        self._updating_position_combo = True
        try:
            for index in range(self._position_combo.count()):
                if self._position_combo.itemData(index) == slot_number:
                    self._position_combo.setCurrentIndex(index)
                    break
        finally:
            self._updating_position_combo = False

    def is_floating(self) -> bool:
        return self._is_floating

    def dispose(self) -> None:
        """Dispose chart-session resources owned by this panel.

        Ownership remains explicit:
        - the panel owns chart-session lifecycle for this widget instance
        - the controller owns chart-session data truth and async guards
        - the workspace remains responsible for pane/layout behavior

        The panel therefore does not tear down pane semantics itself. It only
        closes panel-owned auxiliary windows and forwards teardown to the
        controller it owns.
        """
        if self._is_disposed:
            return

        self._is_disposed = True

        if self._financial_tools_manager_window is not None:
            try:
                self._financial_tools_manager_window.close()
            except Exception:
                pass
            self._financial_tools_manager_window = None

        dispose = getattr(self._controller, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass

    def _reset_chart_local_study_session_for_dataset_change(self) -> None:
        """Clear panel-owned study/session state before opening a different dataset.

        Studies are chart-session-local and dataset-bound. When this panel is
        reused for a different dataset, the panel must drop its previous chart-
        local study registry, projection-key fanout state, and rendered study
        payloads before the new controller session begins.
        """
        self._editing_study_instance_id = None
        self._study_projection_key_by_instance_id.clear()
        self._wired_oscillator_pane_ids.clear()

        clear_financial_tools = getattr(self._workspace, "clear_financial_tools", None)
        if callable(clear_financial_tools):
            try:
                clear_financial_tools()
            except Exception as e:
                self._on_error(
                    "Chart-local study reset fallback engaged during dataset change: "
                    f"{e!r}"
                )
                for study in list(self._study_registry.list_all()):
                    try:
                        self._remove_study_rendered_series(study)
                    except Exception:
                        pass
        else:
            for study in list(self._study_registry.list_all()):
                try:
                    self._remove_study_rendered_series(study)
                except Exception:
                    pass

        self._study_registry.clear()
        self._cleanup_oscillator_pane_signal_tracking()

        if self._financial_tools_manager_window is not None:
            try:
                self._financial_tools_manager_window.close()
            except Exception:
                pass
            self._financial_tools_manager_window = None

    def open_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        if self._is_disposed:
            return

        current_dataset_key = self.dataset_key()
        next_dataset_key = f"{exchange}:{market_type}:{symbol}:{timeframe}"
        dataset_changed = bool(current_dataset_key and current_dataset_key != next_dataset_key)
        if dataset_changed:
            self._reset_chart_local_study_session_for_dataset_change()

        self._exchange = exchange
        self._market_type = market_type
        self._symbol = symbol
        self._timeframe = timeframe

        self._set_dataset_identity(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._controller.open_dataset(exchange, market_type, symbol, timeframe)

    def dataset_key(self) -> str:
        if not self._exchange or not self._market_type or not self._symbol or not self._timeframe:
            return ""
        return f"{self._exchange}:{self._market_type}:{self._symbol}:{self._timeframe}"

    def dataset_title(self) -> str:
        return self._build_dataset_title(
            exchange=self._exchange,
            market_type=self._market_type,
            symbol=self._symbol,
            timeframe=self._timeframe,
        )

    def _register_study_projection_key(self, *, instance_id: str, projection_key: str) -> None:
        normalized_id = str(instance_id).strip()
        normalized_key = str(projection_key).strip()
        if not normalized_id:
            return
        if normalized_key:
            self._study_projection_key_by_instance_id[normalized_id] = normalized_key
            return
        self._study_projection_key_by_instance_id.pop(normalized_id, None)

    def _clear_study_projection_key(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            return
        self._study_projection_key_by_instance_id.pop(normalized_id, None)

    def remove_study_instance(self, instance_id: str) -> bool:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            return False

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot remove study: unknown instance_id '{normalized_id}'.")
            return False

        self._remove_study_rendered_series(study)
        removed = self._study_registry.remove(normalized_id)

        if removed is None:
            self._on_error(f"Study registry removal failed for '{normalized_id}'.")
            return False

        self._clear_study_projection_key(normalized_id)

        if self._editing_study_instance_id == normalized_id:
            self._editing_study_instance_id = None

        self._cleanup_oscillator_pane_signal_tracking()

        self._on_error(
            f"Removed {removed.computation.family} study '{removed.display_name}' from chart session."
        )
        return True







    def _connect_price_pane_study_signals(self) -> None:
        price_pane = getattr(self._workspace, "_price", None)
        if price_pane is None:
            return

        style_signal = getattr(price_pane, "study_style_requested", None)
        if style_signal is not None:
            try:
                style_signal.connect(self._on_price_pane_study_style_requested)
            except Exception:
                pass

        edit_signal = getattr(price_pane, "study_edit_requested", None)
        if edit_signal is not None:
            try:
                edit_signal.connect(self._on_price_pane_study_edit_requested)
            except Exception:
                pass

        remove_signal = getattr(price_pane, "study_remove_requested", None)
        if remove_signal is not None:
            try:
                remove_signal.connect(self._on_price_pane_study_remove_requested)
            except Exception:
                pass

    def _connect_oscillator_pane_signals_for_study(self, study_instance_id: str) -> None:
        pane = None
        if hasattr(self._workspace, "oscillator_pane_for_study"):
            try:
                pane = self._workspace.oscillator_pane_for_study(study_instance_id)
            except Exception:
                pane = None

        if pane is None:
            return

        pane_marker = id(pane)
        if pane_marker in self._wired_oscillator_pane_ids:
            return

        style_signal = getattr(pane, "study_style_requested", None)
        if style_signal is not None:
            try:
                style_signal.connect(self._on_oscillator_pane_study_style_requested)
            except Exception:
                pass

        edit_signal = getattr(pane, "study_edit_requested", None)
        if edit_signal is not None:
            try:
                edit_signal.connect(self._on_oscillator_pane_study_edit_requested)
            except Exception:
                pass

        remove_signal = getattr(pane, "study_remove_requested", None)
        if remove_signal is not None:
            try:
                remove_signal.connect(self._on_oscillator_pane_study_remove_requested)
            except Exception:
                pass

        move_up_signal = getattr(pane, "pane_move_up_requested", None)
        if move_up_signal is not None:
            try:
                move_up_signal.connect(self._on_oscillator_pane_move_up_requested)
            except Exception:
                pass

        move_down_signal = getattr(pane, "pane_move_down_requested", None)
        if move_down_signal is not None:
            try:
                move_down_signal.connect(self._on_oscillator_pane_move_down_requested)
            except Exception:
                pass

        destroyed_signal = getattr(pane, "destroyed", None)
        if destroyed_signal is not None:
            try:
                destroyed_signal.connect(
                    lambda *_args, marker=pane_marker: self._wired_oscillator_pane_ids.discard(marker)
                )
            except Exception:
                pass

        self._wired_oscillator_pane_ids.add(pane_marker)

    def _cleanup_oscillator_pane_signal_tracking(self) -> None:
        live_markers: set[int] = set()

        for study in self._study_registry.list_for_pane(PANE_TARGET_OSCILLATOR):
            pane = None
            if hasattr(self._workspace, "oscillator_pane_for_study"):
                try:
                    pane = self._workspace.oscillator_pane_for_study(study.instance_id)
                except Exception:
                    pane = None

            if pane is not None:
                live_markers.add(id(pane))

        self._wired_oscillator_pane_ids.intersection_update(live_markers)

    def _find_study_by_render_key(self, render_key: str) -> Optional[ChartStudyInstance]:
        normalized_key = str(render_key).strip()
        if not normalized_key:
            return None

        for study in self._study_registry.list_all():
            if normalized_key in study.runtime.render_keys:
                return study
        return None







































    def _set_dataset_identity(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        self._status_label.setText(
            self._build_dataset_status_text(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
            )
        )

    def _build_dataset_title(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> str:
        exchange_display = exchange[:1].upper() + exchange[1:] if exchange else exchange
        return f"Historical Chart: {exchange_display}_{market_type}_{symbol}_{timeframe}"

    def _build_dataset_status_text(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> str:
        return self._build_dataset_title(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )

    def _connect_financial_tools_manager_signals(self, manager: FinancialToolsManagerWindow) -> None:
        manager.apply_requested.connect(self._on_financial_tools_apply_requested)
        manager.save_requested.connect(self._on_financial_tools_save_requested)

    def _list_available_construct_source_options(self, family_kind: str) -> list[dict]:
        controller = getattr(self, "_controller", None)
        if controller is None:
            return []

        try:
            return controller.list_available_construct_source_options(family_kind=family_kind)
        except Exception:
            return []

    def _configured_historical_root(self) -> Path:
        """Return the active historical root from the Core runtime config."""
        return Path(self._core.context.config.runtime.data_dir) / "historical"

    def _ensure_financial_tools_manager_window(self) -> FinancialToolsManagerWindow:
        if self._financial_tools_manager_window is None:
            self._financial_tools_manager_window = FinancialToolsManagerWindow(
                exchange=self._exchange,
                market_type=self._market_type,
                symbol=self._symbol,
                timeframe=self._timeframe,
                source_options_provider=self._list_available_construct_source_options,
                historical_root=self._configured_historical_root(),
                parent=self,
            )
            self._connect_financial_tools_manager_signals(self._financial_tools_manager_window)

        return self._financial_tools_manager_window

    def _recreate_financial_tools_manager_window(self) -> FinancialToolsManagerWindow:
        if self._financial_tools_manager_window is not None:
            try:
                self._financial_tools_manager_window.close()
            except Exception:
                pass

        self._financial_tools_manager_window = FinancialToolsManagerWindow(
            exchange=self._exchange,
            market_type=self._market_type,
            symbol=self._symbol,
            timeframe=self._timeframe,
            source_options_provider=self._list_available_construct_source_options,
            historical_root=self._configured_historical_root(),
            parent=self,
        )
        self._connect_financial_tools_manager_signals(self._financial_tools_manager_window)
        return self._financial_tools_manager_window

    def _on_open_financial_tools_clicked(self) -> None:
        if not self.dataset_key():
            return

        self._editing_study_instance_id = None

        manager = self._ensure_financial_tools_manager_window()

        dataset_changed = (
            getattr(manager, "_exchange", "") != self._exchange
            or getattr(manager, "_market_type", "") != self._market_type
            or getattr(manager, "_symbol", "") != self._symbol
            or getattr(manager, "_timeframe", "") != self._timeframe
        )

        if dataset_changed:
            manager = self._recreate_financial_tools_manager_window()

        manager.show()
        manager.raise_()
        manager.activateWindow()














    def _on_controller_slice_ready(self, _payload_obj: object) -> None:
        """
        Historical slice-refresh hook.

        The controller applies the new resident candle slice first. Once that is
        done, the panel pulls the controller's current projected study payloads,
        resolves the final chart-local render state once, remaps that onto
        chart-local study ids, and reapplies it through the workspace bridge
        without recomputation.
        """
        self._refresh_rendered_studies_from_controller_projection()





    def _on_float_or_dock_clicked(self) -> None:
        if self._is_floating:
            self.dock_requested.emit(self)
        else:
            self.detach_requested.emit(self)

    def _on_close_clicked(self) -> None:
        self.close_requested.emit(self)

    def _on_position_changed(self) -> None:
        if self._updating_position_combo:
            return

        slot_number = self._position_combo.currentData()
        if isinstance(slot_number, int):
            self.position_change_requested.emit(self, slot_number)

    def _on_anchor_zoom_toggled(self, checked: bool) -> None:
        # Compatibility bridge: workspace still exposes the legacy method name,
        # but the panel surface presented to users is the price-pane autoscale
        # contract rather than a latest-edge zoom lock.
        self._workspace.set_anchor_zoom_enabled(bool(checked))

    def _go_to_uses_date_only_format(self) -> bool:
        timeframe = str(self._timeframe or "").strip()
        lowered = timeframe.lower()
        return (
            timeframe in {"D", "W", "M"}
            or timeframe.endswith("M")
            or lowered.endswith("d")
            or lowered.endswith("w")
        )

    def _go_to_input_format_hint(self) -> str:
        if self._go_to_uses_date_only_format():
            return "YYYY-MM-DD"
        return "YYYY-MM-DD HH:MM"

    def _parse_go_to_input_to_ts_ms(self, text: str) -> int:
        value = str(text or "").strip()
        if not value:
            raise ValueError("Go to date is empty.")

        if self._go_to_uses_date_only_format():
            formats = (
                "%Y-%m-%d",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
            )
        else:
            formats = (
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
            )

        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                parsed = parsed.replace(tzinfo=timezone.utc)
                return int(parsed.timestamp() * 1000)
            except ValueError:
                continue

        raise ValueError(f"Expected {self._go_to_input_format_hint()} for timeframe {self._timeframe or 'unknown'}.")

    def _on_go_to_clicked(self) -> None:
        if not self.dataset_key():
            self._on_error("Open a historical dataset before using Go to.")
            return

        hint = self._go_to_input_format_hint()
        text, accepted = QInputDialog.getText(
            self,
            "Go to date",
            f"Timeframe: {self._timeframe or 'unknown'}\nEnter {hint} (UTC):",
        )
        if not accepted:
            return

        if not str(text or "").strip():
            return

        try:
            ts_ms = self._parse_go_to_input_to_ts_ms(text)
        except ValueError as exc:
            self._on_error(f"Invalid Go to date: {exc}")
            return

        if not self._controller.center_view_on_timestamp_ms(ts_ms):
            self._on_error("Could not center chart on the requested date.")

    def _on_error(self, msg: str) -> None:
        if self._is_disposed:
            return
        print(f"[HistoricalChartPanel] {msg}")
