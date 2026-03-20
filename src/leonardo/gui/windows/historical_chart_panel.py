from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.chart.model import Series, SeriesStyle
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
    StudyDisplayStyle,
)
from leonardo.gui.chart.workspace import ChartWorkspaceWidget
from leonardo.gui.historical_chart_controller import HistoricalChartController
from leonardo.gui.windows.financial_tool_manager_window import FinancialToolManagerWindow


class StudyStyleDialog(QDialog):
    """
    Small chart-local style editor.

    This dialog is intentionally limited to display settings only.
    It does not touch computation parameters.
    """

    def __init__(
        self,
        *,
        display_name: str,
        current_style: StudyDisplayStyle,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Study Style - {display_name}")
        self.setModal(True)
        self.resize(360, 180)

        self.setStyleSheet(
            """
            QDialog {
                background-color: rgb(18, 18, 22);
                color: rgb(220, 220, 230);
            }
            QLabel {
                color: rgb(210, 210, 220);
            }
            QComboBox, QLineEdit, QSpinBox {
                background-color: rgb(30, 30, 36);
                color: rgb(230, 230, 240);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 4px 6px;
            }
            QPushButton {
                color: rgb(230, 230, 240);
                background-color: rgb(40, 40, 48);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 6px 12px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        root.addLayout(form)

        self._color_edit = QLineEdit(self)
        self._color_edit.setPlaceholderText("#RRGGBB")
        self._color_edit.setText(str(current_style.color or "").strip())
        form.addRow("Color", self._color_edit)

        self._preset_combo = QComboBox(self)
        self._preset_combo.addItem("Keep typed color", "")
        for hex_color, label in (
            ("#FFA500", "Orange"),
            ("#00C8FF", "Cyan"),
            ("#1E90FF", "Blue"),
            ("#2962FF", "Deep Blue"),
            ("#BA68C8", "Purple"),
            ("#FFD666", "Amber"),
            ("#4CAF50", "Green"),
            ("#00E676", "Neon Green"),
            ("#EF5350", "Red"),
            ("#FF1744", "Bright Red"),
            ("#FFFFFF", "White"),
            ("#B0BEC5", "Grey"),
        ):
            self._preset_combo.addItem(label, hex_color)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Preset", self._preset_combo)

        initial_width = int(getattr(current_style, "line_width", 2))
        initial_width = max(1, min(8, initial_width))

        self._width_spin = QSpinBox(self)
        self._width_spin.setRange(1, 8)
        self._width_spin.setSingleStep(1)
        self._width_spin.setValue(initial_width)
        form.addRow("Width", self._width_spin)

        self._line_style_combo = QComboBox(self)
        self._line_style_combo.addItem("Solid", "solid")
        self._line_style_combo.addItem("Dotted", "dotted")
        self._line_style_combo.addItem("Dashed", "dashed")
        self._line_style_combo.addItem("Dash Dot", "dash_dot")
        self._set_combo_data(self._line_style_combo, current_style.line_style)
        form.addRow("Line Style", self._line_style_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_preset_changed(self) -> None:
        preset = str(self._preset_combo.currentData() or "").strip()
        if preset:
            self._color_edit.setText(preset)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        target = str(value or "").strip().lower()
        for idx in range(combo.count()):
            current = str(combo.itemData(idx) or "").strip().lower()
            if current == target:
                combo.setCurrentIndex(idx)
                return

    def style_patch(self) -> Dict[str, Any]:
        return {
            "color": self._normalized_color_or_default(self._color_edit.text().strip()),
            "line_width": int(self._width_spin.value()),
            "line_style": str(self._line_style_combo.currentData() or "solid"),
        }

    def _normalized_color_or_default(self, text: str) -> str:
        value = text.strip()
        if not value:
            return "#FFA500"

        color = QColor(value)
        if color.isValid():
            return color.name().upper()

        return "#FFA500"


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

        # Tracks pane objects that already had oscillator signals wired.
        self._wired_oscillator_pane_ids: set[int] = set()

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

        self._cleanup_oscillator_pane_signal_tracking()

        self._on_error(
            f"Removed {removed.computation.family} study '{removed.display_name}' from chart session."
        )
        return True

    def _normalize_study_family(self, tool_type: str) -> str:
        normalized = str(tool_type).strip().lower()
        if normalized == STUDY_FAMILY_INDICATOR:
            return STUDY_FAMILY_INDICATOR
        if normalized == STUDY_FAMILY_OSCILLATOR:
            return STUDY_FAMILY_OSCILLATOR
        if normalized == STUDY_FAMILY_CONSTRUCT:
            return STUDY_FAMILY_CONSTRUCT
        return normalized

    def _extract_behavior(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("behavior", {}) or {}
        if not isinstance(raw, dict):
            raw = {}

        output_mode = str(raw.get("output_mode", "")).strip().lower()
        if output_mode not in {"overlay", "oscillator-pane", "non-visual"}:
            family = self._normalize_study_family(str(payload.get("tool_type", "")))
            if family == STUDY_FAMILY_OSCILLATOR:
                output_mode = "oscillator-pane"
            else:
                output_mode = "overlay"

        chart_renderable = raw.get("chart_renderable", output_mode != "non-visual")
        supports_style = raw.get("supports_style", bool(chart_renderable))
        supports_pane_layout = raw.get("supports_pane_layout", output_mode == "oscillator-pane")
        supports_last_value = raw.get("supports_last_value", bool(chart_renderable))

        return {
            "output_mode": output_mode,
            "chart_renderable": bool(chart_renderable),
            "supports_style": bool(supports_style),
            "supports_pane_layout": bool(supports_pane_layout),
            "supports_last_value": bool(supports_last_value),
        }

    def _extract_output(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("output", {}) or {}
        if not isinstance(raw, dict):
            raw = {}

        output_names = raw.get("output_names", []) or []
        if not isinstance(output_names, list):
            output_names = list(output_names) if isinstance(output_names, tuple) else []

        return {
            "structure": str(raw.get("structure", "")).strip().lower(),
            "output_names": [str(name) for name in output_names],
            "accepts_empty_render_output": bool(raw.get("accepts_empty_render_output", False)),
        }

    def _pane_target_for_output_mode(self, output_mode: str) -> Optional[str]:
        normalized = str(output_mode).strip().lower()
        if normalized == "oscillator-pane":
            return PANE_TARGET_OSCILLATOR
        if normalized == "overlay":
            return PANE_TARGET_PRICE
        return None

    def _study_is_renderable(self, study: ChartStudyInstance) -> bool:
        return bool(study.runtime.render_keys)

    def _remove_study_rendered_series(self, study: ChartStudyInstance) -> None:
        if not self._study_is_renderable(study):
            return

        if study.pane_target == PANE_TARGET_OSCILLATOR:
            if hasattr(self._workspace, "remove_oscillator_study"):
                try:
                    self._workspace.remove_oscillator_study(study.instance_id)
                    self._cleanup_oscillator_pane_signal_tracking()
                    return
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study removal fallback engaged for "
                        f"'{study.display_name}': {e!r}"
                    )

        for render_key in study.runtime.render_keys:
            if study.pane_target == PANE_TARGET_OSCILLATOR:
                self._workspace.remove_oscillator_series(render_key)
            else:
                self._workspace.remove_overlay_series(render_key)

        self._cleanup_oscillator_pane_signal_tracking()

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

    def _on_price_pane_study_remove_requested(self, render_key: str) -> None:
        study = self._find_study_by_render_key(render_key)
        if study is None:
            self._on_error(f"Cannot remove study: render key '{render_key}' is not registered.")
            return

        self.remove_study_instance(study.instance_id)

    def _on_price_pane_study_style_requested(self, render_key: str) -> None:
        study = self._find_study_by_render_key(render_key)
        if study is None:
            self._on_error(f"Cannot style study: render key '{render_key}' is not registered.")
            return

        dialog = StudyStyleDialog(
            display_name=study.display_name,
            current_style=study.style,
            parent=self,
        )
        if dialog.exec() != int(QDialog.Accepted):
            return

        patch = dialog.style_patch()
        self._apply_study_style_patch(study.instance_id, patch)

    def _on_oscillator_pane_study_style_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot style oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot style oscillator study: unknown instance_id '{normalized_id}'.")
            return

        dialog = StudyStyleDialog(
            display_name=study.display_name,
            current_style=study.style,
            parent=self,
        )
        if dialog.exec() != int(QDialog.Accepted):
            return

        patch = dialog.style_patch()
        self._apply_study_style_patch(study.instance_id, patch)

    def _apply_study_style_patch(self, instance_id: str, patch: Dict[str, Any]) -> None:
        study = self._study_registry.get(instance_id)
        if study is None:
            self._on_error(f"Cannot apply style: unknown instance_id '{instance_id}'.")
            return

        if not self._study_is_renderable(study):
            self._on_error(f"Cannot apply style: study '{study.display_name}' is non-visual.")
            return

        new_style = study.style.merged(patch)
        updated_study = replace(study, style=new_style)
        self._study_registry.add(updated_study)

        self._reapply_study_render_series(updated_study)

        self._on_error(
            f"Updated style for study '{updated_study.display_name}' "
            f"(color={updated_study.style.color}, "
            f"width={updated_study.style.line_width}, "
            f"line_style={updated_study.style.line_style})."
        )

    def _reapply_study_render_series(self, study: ChartStudyInstance) -> None:
        if not self._study_is_renderable(study):
            return

        styled_series_list: List[Series] = []

        for render_key in study.runtime.render_keys:
            existing_series = None
            if study.pane_target == PANE_TARGET_OSCILLATOR:
                existing_series = self._workspace.model.oscillator(render_key)
            else:
                existing_series = self._workspace.model.overlays().get(render_key)

            if existing_series is None:
                continue

            styled_series = Series(
                key=existing_series.key,
                title=existing_series.title,
                values=list(existing_series.values),
                style=SeriesStyle(
                    color=study.style.color,
                    line_width=int(study.style.line_width),
                    line_style=str(study.style.line_style),
                ),
            )
            styled_series_list.append(styled_series)

        if not styled_series_list:
            return

        if study.pane_target == PANE_TARGET_OSCILLATOR:
            if hasattr(self._workspace, "apply_oscillator_study"):
                try:
                    self._workspace.apply_oscillator_study(
                        study_instance_id=study.instance_id,
                        title=study.display_name,
                        series_list=styled_series_list,
                    )
                    self._connect_oscillator_pane_signals_for_study(study.instance_id)
                    return
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study reapply fallback engaged for "
                        f"'{study.display_name}': {e!r}"
                    )

            for styled_series in styled_series_list:
                self._workspace.apply_oscillator_series(styled_series)
            return

        for styled_series in styled_series_list:
            self._workspace.apply_overlay_series(styled_series)

    def _on_price_pane_study_edit_requested(self, render_key: str) -> None:
        study = self._find_study_by_render_key(render_key)
        if study is None:
            self._on_error(f"Cannot edit study: render key '{render_key}' is not registered.")
            return

        self._open_study_for_edit(study)

    def _on_oscillator_pane_study_edit_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot edit oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot edit oscillator study: unknown instance_id '{normalized_id}'.")
            return

        self._open_study_for_edit(study)

    def _open_study_for_edit(self, study: ChartStudyInstance) -> None:
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

    def _on_oscillator_pane_study_remove_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot remove oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot remove oscillator study: unknown instance_id '{normalized_id}'.")
            return

        self.remove_study_instance(study.instance_id)

    def _on_oscillator_pane_move_up_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot move oscillator pane up: empty instance_id.")
            return

        if hasattr(self._workspace, "move_oscillator_pane_up"):
            try:
                moved = bool(self._workspace.move_oscillator_pane_up(normalized_id))
            except Exception as e:
                self._on_error(f"Oscillator pane move up failed: {e!r}")
                return

            if moved:
                study = self._study_registry.get(normalized_id)
                if study is not None:
                    self._on_error(f"Moved oscillator pane up for '{study.display_name}'.")
            return

        self._on_error("Oscillator pane move up is not available on the current workspace.")

    def _on_oscillator_pane_move_down_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot move oscillator pane down: empty instance_id.")
            return

        if hasattr(self._workspace, "move_oscillator_pane_down"):
            try:
                moved = bool(self._workspace.move_oscillator_pane_down(normalized_id))
            except Exception as e:
                self._on_error(f"Oscillator pane move down failed: {e!r}")
                return

            if moved:
                study = self._study_registry.get(normalized_id)
                if study is not None:
                    self._on_error(f"Moved oscillator pane down for '{study.display_name}'.")
            return

        self._on_error("Oscillator pane move down is not available on the current workspace.")

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

    def _apply_series_list_to_workspace(
        self,
        *,
        output_mode: str,
        series_list: List[Series],
        study_instance_id: Optional[str] = None,
        display_name: str = "",
    ) -> List[str]:
        render_keys: List[str] = []

        normalized_mode = str(output_mode).strip().lower()
        if normalized_mode == "non-visual":
            return render_keys

        if normalized_mode == "oscillator-pane" and study_instance_id:
            if hasattr(self._workspace, "apply_oscillator_study"):
                try:
                    self._workspace.apply_oscillator_study(
                        study_instance_id=study_instance_id,
                        title=str(display_name).strip(),
                        series_list=series_list,
                    )
                    render_keys.extend([series.key for series in series_list])
                    self._connect_oscillator_pane_signals_for_study(study_instance_id)
                    return render_keys
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study apply fallback engaged for "
                        f"'{display_name or study_instance_id}': {e!r}"
                    )

        for series in series_list:
            if normalized_mode == "oscillator-pane":
                self._workspace.apply_oscillator_series(series)
            else:
                self._workspace.apply_overlay_series(series)
            render_keys.append(series.key)

        return render_keys

    def _register_applied_study(
        self,
        *,
        family: str,
        output_mode: str,
        supports_last_value: bool,
        tool_key: str,
        display_name: str,
        params: Dict[str, Any],
        render_keys: List[str],
        series_list: List[Series],
        instance_id: Optional[str] = None,
    ) -> ChartStudyInstance:
        last_value = None
        if supports_last_value:
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
            instance_id=instance_id or uuid.uuid4().hex,
            dataset_id=self.dataset_key(),
            pane_target=self._pane_target_for_output_mode(output_mode),
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
        behavior = self._extract_behavior(payload)
        output = self._extract_output(payload)

        output_mode = str(behavior["output_mode"])
        chart_renderable = bool(behavior["chart_renderable"])
        supports_last_value = bool(behavior["supports_last_value"])
        accepts_empty_render_output = bool(output["accepts_empty_render_output"])

        tool_key = str(payload.get("tool_key", "")).strip().lower()
        display_name = str(payload.get("display_name", payload.get("tool_title", tool_key))).strip()
        params = dict(payload.get("params", {}) or {})
        series_list = list(payload.get("series_list", []) or [])

        if not tool_key:
            self._editing_study_instance_id = None
            self._on_error("Financial tool apply failed: missing tool_key.")
            return

        if chart_renderable and not series_list:
            self._editing_study_instance_id = None
            self._on_error("Financial tool apply returned no renderable series.")
            return

        if not chart_renderable and not accepts_empty_render_output and not series_list:
            self._editing_study_instance_id = None
            self._on_error(
                "Financial tool apply failed: non-visual output was not declared as a valid empty-render result."
            )
            return

        self._replace_edited_study_if_needed()

        provisional_instance_id = uuid.uuid4().hex
        render_keys: List[str] = []

        if chart_renderable:
            render_keys = self._apply_series_list_to_workspace(
                output_mode=output_mode,
                series_list=series_list,
                study_instance_id=provisional_instance_id if output_mode == "oscillator-pane" else None,
                display_name=display_name,
            )

        study = self._register_applied_study(
            family=family,
            output_mode=output_mode,
            supports_last_value=supports_last_value,
            tool_key=tool_key,
            display_name=display_name,
            params=params,
            render_keys=render_keys,
            series_list=series_list,
            instance_id=provisional_instance_id,
        )

        if output_mode == "oscillator-pane" and chart_renderable:
            self._connect_oscillator_pane_signals_for_study(study.instance_id)

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