from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QFrame,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.model import Series
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRegistry,
    ChartStudyRuntimeState,
    PANE_TARGET_OSCILLATOR,
    PANE_TARGET_PRICE,
    STUDY_FAMILY_CONSTRUCT,
    STUDY_FAMILY_INDICATOR,
    STUDY_FAMILY_OSCILLATOR,
    STUDY_SOURCE_TEMPORARY,
    StudyComputationConfig,
)
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.historical_chart_controller import HistoricalChartController
from leonardo.gui.windows.financial_tool_manager_window import FinancialToolManagerWindow


class HistoricalChartPanel(QFrame):
    """
    Reusable historical chart content widget.

    This widget is shell-agnostic:
    - it can live embedded inside HistoricalDataManagerWindow
    - it can be hosted inside a floating HistoricalChartWindow
    """

    detach_requested = Signal(object)
    dock_requested = Signal(object)
    close_requested = Signal(object)

    def __init__(self, *, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._core = core_bridge

        self._exchange: str = ""
        self._market_type: str = ""
        self._symbol: str = ""
        self._timeframe: str = ""

        self._is_floating: bool = False
        self._financial_tool_manager_window: Optional[FinancialToolManagerWindow] = None
        self._study_registry = ChartStudyRegistry()

        # Tracks the study currently being edited so Apply can replace it
        # instead of creating a second visible instance.
        self._editing_study_instance_id: Optional[str] = None

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
        self._anchor_zoom_button.setText("Anchor Zoom")
        self._anchor_zoom_button.setCheckable(True)
        self._anchor_zoom_button.setChecked(True)
        self._anchor_zoom_button.setToolTip("Keep zoom locked to the latest real candle")
        self._anchor_zoom_button.toggled.connect(self._on_anchor_zoom_toggled)
        status_layout.addWidget(self._anchor_zoom_button)

        root.addWidget(self._status_bar, 0)

        self._controller = HistoricalChartController(
            core_bridge=self._core,
            workspace=self._workspace,
            parent=self,
        )
        self._controller.error.connect(self._on_error)
        self._controller.apply_succeeded.connect(self._on_financial_tool_apply_succeeded)
        self._controller.save_succeeded.connect(self._on_financial_tool_save_succeeded)
        self._controller.save_failed.connect(self._on_financial_tool_save_failed)

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
        else:
            self._float_button.setText("Float")
            self._float_button.setToolTip("Detach this chart into a floating window")
            self._close_button.setToolTip("Close this embedded chart")

    def is_floating(self) -> bool:
        return self._is_floating

    def open_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> None:
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

    def remove_study_instance(self, instance_id: str) -> bool:
        """
        Remove a displayed study from this chart session.

        Removal is chart-session local only:
        - rendered series are removed from the workspace
        - the study instance is removed from the registry
        - persisted artifacts are NOT deleted
        """
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

        if self._editing_study_instance_id == normalized_id:
            self._editing_study_instance_id = None

        self._on_error(
            f"Removed {removed.computation.family} study '{removed.display_name}' from chart session."
        )
        return True

    def _remove_study_rendered_series(self, study: ChartStudyInstance) -> None:
        for render_key in study.runtime.render_keys:
            if study.pane_target == PANE_TARGET_OSCILLATOR:
                self._workspace.remove_oscillator_series(render_key)
            else:
                self._workspace.remove_overlay_series(render_key)

    def _connect_price_pane_study_signals(self) -> None:
        price_pane = getattr(self._workspace, "_price", None)
        if price_pane is None:
            return

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

    def _find_study_by_render_key(self, render_key: str) -> Optional[ChartStudyInstance]:
        normalized_key = str(render_key).strip()
        if not normalized_key:
            return None

        for study in self._study_registry.list_all():
            if normalized_key in study.runtime.render_keys:
                return study
        return None

    def _on_price_pane_study_remove_requested(self, render_key: str) -> None:
        study = self._find_study_by_render_key(render_key)
        if study is None:
            self._on_error(f"Cannot remove study: render key '{render_key}' is not registered.")
            return

        self.remove_study_instance(study.instance_id)

    def _on_price_pane_study_edit_requested(self, render_key: str) -> None:
        study = self._find_study_by_render_key(render_key)
        if study is None:
            self._on_error(f"Cannot edit study: render key '{render_key}' is not registered.")
            return

        self._editing_study_instance_id = study.instance_id

        manager = self._ensure_financial_tool_manager_window()

        dataset_changed = (
            getattr(manager, "_exchange", "") != self._exchange
            or getattr(manager, "_market_type", "") != self._market_type
            or getattr(manager, "_symbol", "") != self._symbol
            or getattr(manager, "_timeframe", "") != self._timeframe
        )

        if dataset_changed:
            manager = self._recreate_financial_tool_manager_window()

        preload_ok = False
        if hasattr(manager, "load_study_for_edit"):
            try:
                preload_ok = bool(
                    manager.load_study_for_edit(
                        tool_type=study.computation.family,
                        tool_key=study.computation.tool_key,
                        params=study.computation.params,
                    )
                )
            except Exception as e:
                self._on_error(f"Study preload failed for '{study.display_name}': {e!r}")

        manager.show()
        manager.raise_()
        manager.activateWindow()

        if preload_ok:
            self._on_error(
                "Study edit preloaded for "
                f"'{study.display_name}' "
                f"(tool_key={study.computation.tool_key}, params={study.computation.params})."
            )
        else:
            self._on_error(
                "Study edit opened without preload for "
                f"'{study.display_name}' "
                f"(tool_key={study.computation.tool_key}, params={study.computation.params})."
            )

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

    def _connect_financial_tool_manager_signals(self, manager: FinancialToolManagerWindow) -> None:
        manager.apply_requested.connect(self._on_financial_tool_apply_requested)
        manager.save_requested.connect(self._on_financial_tool_save_requested)

    def _ensure_financial_tool_manager_window(self) -> FinancialToolManagerWindow:
        if self._financial_tool_manager_window is None:
            self._financial_tool_manager_window = FinancialToolManagerWindow(
                exchange=self._exchange,
                market_type=self._market_type,
                symbol=self._symbol,
                timeframe=self._timeframe,
                parent=self,
            )
            self._connect_financial_tool_manager_signals(self._financial_tool_manager_window)

        return self._financial_tool_manager_window

    def _recreate_financial_tool_manager_window(self) -> FinancialToolManagerWindow:
        if self._financial_tool_manager_window is not None:
            try:
                self._financial_tool_manager_window.close()
            except Exception:
                pass

        self._financial_tool_manager_window = FinancialToolManagerWindow(
            exchange=self._exchange,
            market_type=self._market_type,
            symbol=self._symbol,
            timeframe=self._timeframe,
            parent=self,
        )
        self._connect_financial_tool_manager_signals(self._financial_tool_manager_window)
        return self._financial_tool_manager_window

    def _on_open_financial_tools_clicked(self) -> None:
        if not self.dataset_key():
            return

        self._editing_study_instance_id = None

        manager = self._ensure_financial_tool_manager_window()

        dataset_changed = (
            getattr(manager, "_exchange", "") != self._exchange
            or getattr(manager, "_market_type", "") != self._market_type
            or getattr(manager, "_symbol", "") != self._symbol
            or getattr(manager, "_timeframe", "") != self._timeframe
        )

        if dataset_changed:
            manager = self._recreate_financial_tool_manager_window()

        manager.show()
        manager.raise_()
        manager.activateWindow()

    def _on_financial_tool_apply_requested(self, payload: dict) -> None:
        try:
            self._controller.apply_financial_tool(payload)
        except Exception as e:
            self._editing_study_instance_id = None
            self._on_error(f"Financial tool apply failed: {e!r}")

    def _on_financial_tool_save_requested(self, payload: dict) -> None:
        try:
            self._controller.save_financial_tool(payload)
        except Exception as e:
            self._on_error(f"Financial tool save failed: {e!r}")

    def _normalize_study_family(self, tool_type: str) -> str:
        normalized = str(tool_type).strip().lower()
        if normalized == STUDY_FAMILY_INDICATOR:
            return STUDY_FAMILY_INDICATOR
        if normalized == STUDY_FAMILY_OSCILLATOR:
            return STUDY_FAMILY_OSCILLATOR
        if normalized == STUDY_FAMILY_CONSTRUCT:
            return STUDY_FAMILY_CONSTRUCT
        return normalized

    def _pane_target_for_study_family(self, family: str) -> str:
        if family == STUDY_FAMILY_OSCILLATOR:
            return PANE_TARGET_OSCILLATOR
        return PANE_TARGET_PRICE

    def _apply_series_list_to_workspace(self, family: str, series_list: List[Series]) -> List[str]:
        render_keys: List[str] = []
        for series in series_list:
            if family == STUDY_FAMILY_OSCILLATOR:
                self._workspace.apply_oscillator_series(series)
            else:
                self._workspace.apply_overlay_series(series)
            render_keys.append(series.key)
        return render_keys

    def _register_applied_study(
        self,
        *,
        family: str,
        tool_key: str,
        display_name: str,
        params: Dict[str, Any],
        render_keys: List[str],
        series_list: List[Series],
    ) -> ChartStudyInstance:
        last_value = None
        for series in series_list:
            if series.values:
                candidate = series.values[-1]
                try:
                    if candidate == candidate:
                        last_value = float(candidate)
                        break
                except Exception:
                    continue

        study = ChartStudyInstance(
            instance_id=uuid.uuid4().hex,
            dataset_id=self.dataset_key(),
            pane_target=self._pane_target_for_study_family(family),
            display_name=str(display_name).strip() or tool_key,
            computation=StudyComputationConfig(
                family=family,
                tool_key=tool_key,
                params=dict(params),
                source_kind=STUDY_SOURCE_TEMPORARY,
            ),
            runtime=ChartStudyRuntimeState(
                last_value=last_value,
                render_keys=list(render_keys),
            ),
        )
        self._study_registry.add(study)
        return study

    def _replace_edited_study_if_needed(self) -> None:
        if not self._editing_study_instance_id:
            return

        instance_id = self._editing_study_instance_id
        self._editing_study_instance_id = None

        existing = self._study_registry.get(instance_id)
        if existing is None:
            return

        self.remove_study_instance(instance_id)

    def _on_financial_tool_apply_succeeded(self, payload: dict) -> None:
        if not payload:
            self._editing_study_instance_id = None
            return

        family = self._normalize_study_family(str(payload.get("tool_type", "")))
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        display_name = str(payload.get("display_name", payload.get("tool_title", tool_key))).strip()
        params = dict(payload.get("params", {}) or {})
        series_list = list(payload.get("series_list", []) or [])

        if not tool_key or not series_list:
            self._editing_study_instance_id = None
            self._on_error("Financial tool apply returned no renderable series.")
            return

        self._replace_edited_study_if_needed()

        render_keys = self._apply_series_list_to_workspace(family, series_list)
        study = self._register_applied_study(
            family=family,
            tool_key=tool_key,
            display_name=display_name,
            params=params,
            render_keys=render_keys,
            series_list=series_list,
        )
        self._on_error(
            f"Applied {study.computation.family} study '{study.display_name}' to chart session."
        )

    def _build_save_success_message(self, payload: Dict[str, Any]) -> str:
        params = payload.get("params", {}) or {}
        lines = [
            f"{str(payload.get('tool_type', '')).strip().capitalize()} {payload.get('tool_title', '')} was saved successfully.",
            "",
            f"Exchange: {payload.get('exchange', '')}",
            f"Market type: {payload.get('market_type', '')}",
            f"Asset: {payload.get('symbol', '')}",
            f"Timeframe: {payload.get('timeframe', '')}",
            "",
            "Parameters / metadata:",
        ]

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

        lines.extend(
            [
                "",
                "Saved to:",
                str(payload.get("saved_path", "")),
            ]
        )
        return "\n".join(lines)

    def _build_save_error_message(self, payload: Dict[str, Any]) -> str:
        params = payload.get("params", {}) or {}
        lines = [
            f"{str(payload.get('tool_type', '')).strip().capitalize()} {payload.get('tool_title', '')} was not saved.",
            "",
            f"Exchange: {payload.get('exchange', '')}",
            f"Market type: {payload.get('market_type', '')}",
            f"Asset: {payload.get('symbol', '')}",
            f"Timeframe: {payload.get('timeframe', '')}",
            "",
            "Parameters / metadata:",
        ]

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

        saved_path = str(payload.get("saved_path", "")).strip()
        if saved_path:
            lines.extend(
                [
                    "",
                    "Target path:",
                    saved_path,
                ]
            )

        error_text = str(payload.get("error", "")).strip()
        if error_text:
            lines.extend(
                [
                    "",
                    "Reason:",
                    error_text,
                ]
            )

        return "\n".join(lines)

    def _on_financial_tool_save_succeeded(self, payload: dict) -> None:
        QMessageBox.information(
            self,
            "Financial Tool Saved",
            self._build_save_success_message(payload),
        )

    def _on_financial_tool_save_failed(self, payload: dict) -> None:
        QMessageBox.critical(
            self,
            "Financial Tool Save Failed",
            self._build_save_error_message(payload),
        )

    def _on_float_or_dock_clicked(self) -> None:
        if self._is_floating:
            self.dock_requested.emit(self)
        else:
            self.detach_requested.emit(self)

    def _on_close_clicked(self) -> None:
        self.close_requested.emit(self)

    def _on_anchor_zoom_toggled(self, checked: bool) -> None:
        self._workspace.set_anchor_zoom_enabled(bool(checked))

    def _on_error(self, msg: str) -> None:
        print(f"[HistoricalChartPanel] {msg}")