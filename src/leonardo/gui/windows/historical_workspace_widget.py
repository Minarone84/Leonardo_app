from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
)

from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.historical_chart_panel import HistoricalChartPanel


class HistoricalWorkspaceWidget(QWidget):
    """
    Managed embedded workspace for up to 8 historical chart panels.

    Layout policy:
    - 8 stable chart slots
    - slot order is always 1-2, 3-4, 5-6, 7-8
    - detached charts keep their original slot for dock-back
    - Scroll 4 mode keeps two rows visible and scrolls to slots 5-8
    - Fit 8 mode fits all four rows into the available workspace
    """

    MAX_CHARTS = 8
    SLOT_COLUMNS = 2
    SLOT_ROWS = 4
    VIEW_MODE_SCROLL_4 = "scroll_4"
    VIEW_MODE_FIT_8 = "fit_8"

    visualization_mode_changed = Signal(str)

    def __init__(
        self,
        *,
        core_bridge: CoreBridge,
        window_manager=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._core = core_bridge
        self._window_manager = window_manager
        self._chart_slots: List[Optional[HistoricalChartPanel]] = [None] * self.MAX_CHARTS
        self._detached_slots: Dict[HistoricalChartPanel, int] = {}
        self._visualization_mode = self.VIEW_MODE_SCROLL_4

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._empty_state = QLabel(
            "No historical charts loaded.\nUse File → New Chart to load one.",
            self,
        )
        self._empty_state.setAlignment(Qt.AlignCenter)
        self._empty_state.setStyleSheet(
            """
            QLabel {
                border: 1px solid #4A4A4A;
                background-color: #1A1A1A;
                color: #D8D8D8;
                font-size: 14px;
            }
            """
        )

        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setWidget(self._grid_host)

        root.addWidget(self._empty_state, 1)
        root.addWidget(self._scroll_area, 1)

        self._scroll_area.hide()
        self._grid_host.hide()

    def chart_count(self) -> int:
        return sum(1 for panel in self._chart_slots if panel is not None)

    def visualization_mode(self) -> str:
        return self._visualization_mode

    @classmethod
    def visualization_mode_label(cls, mode: str) -> str:
        if mode == cls.VIEW_MODE_FIT_8:
            return "Fit 8"
        return "Scroll 4"

    def set_visualization_mode(self, mode: str) -> None:
        if mode not in {self.VIEW_MODE_SCROLL_4, self.VIEW_MODE_FIT_8}:
            raise ValueError(f"Unsupported historical workspace visualization mode: {mode!r}")

        changed = self._visualization_mode != mode
        self._visualization_mode = mode

        self._update_visualization_mode_geometry()
        self._relayout()
        if changed:
            self.visualization_mode_changed.emit(mode)

    def can_add_chart(self) -> bool:
        return self._first_available_slot_index() is not None

    def add_chart(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        slot_index = self._first_available_slot_index()
        if slot_index is None:
            return False

        panel = HistoricalChartPanel(core_bridge=self._core, parent=self._grid_host)
        self._connect_panel_workspace_signals(panel)
        panel.open_dataset(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._chart_slots[slot_index] = panel
        self._relayout()
        return True

    def add_existing_panel(self, panel: HistoricalChartPanel) -> bool:
        slot_index = self._detached_slots.pop(panel, None)
        if slot_index is None:
            slot_index = self._first_available_slot_index()
        elif self._chart_slots[slot_index] is not None:
            self._detached_slots[panel] = slot_index
            return False

        if slot_index is None:
            return False

        self._disconnect_panel_workspace_signals(panel)
        self._connect_panel_workspace_signals(panel)
        panel.setParent(self._grid_host)
        self._chart_slots[slot_index] = panel
        self._relayout()
        return True

    def remove_chart(self, panel: HistoricalChartPanel) -> bool:
        return self._remove_chart(panel, preserve_detached_slot=False)

    def clear_all_charts(self) -> None:
        """Dispose every embedded historical chart panel owned by this workspace.

        Ownership stays local to the workspace:
        - the workspace owns embedded panel membership and layout
        - each panel owns its own chart-session/controller teardown

        This method exists specifically for shell-close teardown so the
        Historical Data Manager can ask the workspace to release its embedded
        sessions without reaching into controller internals itself.
        """
        for panel in list(self._embedded_panels()):
            removed = self.remove_chart(panel)
            if not removed:
                continue
            self._dispose_panel(panel)

    def _dispose_panel(self, panel: HistoricalChartPanel) -> None:
        """Dispose one removed panel using its own public teardown path."""
        dispose = getattr(panel, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        panel.deleteLater()

    def move_panel_to_slot(self, panel: HistoricalChartPanel, slot_number: int) -> bool:
        target_index = slot_number - 1
        if target_index < 0 or target_index >= self.MAX_CHARTS:
            self._sync_all_panel_positions()
            return False

        current_index = self._slot_index_for_panel(panel)
        if current_index is None:
            self._sync_all_panel_positions()
            return False

        if current_index == target_index:
            self._sync_panel_position(panel, current_index)
            return True

        if target_index in set(self._detached_slots.values()):
            self._sync_panel_position(panel, current_index)
            return False

        target_panel = self._chart_slots[target_index]
        self._chart_slots[target_index] = panel
        self._chart_slots[current_index] = target_panel
        self._relayout()
        return True

    def _connect_panel_workspace_signals(self, panel: HistoricalChartPanel) -> None:
        panel.detach_requested.connect(self._on_panel_detach_requested)
        panel.close_requested.connect(self._on_panel_close_requested)
        position_signal = getattr(panel, "position_change_requested", None)
        if position_signal is not None:
            try:
                position_signal.connect(self._on_panel_position_change_requested)
            except Exception:
                pass

    def _disconnect_panel_workspace_signals(self, panel: HistoricalChartPanel) -> None:
        try:
            panel.detach_requested.disconnect(self._on_panel_detach_requested)
        except Exception:
            pass

        try:
            panel.close_requested.disconnect(self._on_panel_close_requested)
        except Exception:
            pass

        position_signal = getattr(panel, "position_change_requested", None)
        if position_signal is not None:
            try:
                position_signal.disconnect(self._on_panel_position_change_requested)
            except Exception:
                pass

    def _on_panel_detach_requested(self, panel_obj: object) -> None:
        panel = panel_obj if isinstance(panel_obj, HistoricalChartPanel) else None
        if panel is None:
            return

        if self._slot_index_for_panel(panel) is None:
            return

        if self._window_manager is None:
            QMessageBox.warning(
                self,
                "Historical Workspace",
                "Window manager not available. Cannot float chart.",
            )
            return

        removed = self._remove_chart(panel, preserve_detached_slot=True)
        if not removed:
            return

        self._window_manager.float_historical_chart_panel(panel=panel, parent=self.window())

    def _on_panel_close_requested(self, panel_obj: object) -> None:
        panel = panel_obj if isinstance(panel_obj, HistoricalChartPanel) else None
        if panel is None:
            return

        removed = self.remove_chart(panel)
        if not removed:
            return

        self._dispose_panel(panel)

    def _on_panel_position_change_requested(self, panel_obj: object, slot_number: int) -> None:
        panel = panel_obj if isinstance(panel_obj, HistoricalChartPanel) else None
        if panel is None:
            return
        self.move_panel_to_slot(panel, slot_number)

    def _embedded_panels(self) -> List[HistoricalChartPanel]:
        return [panel for panel in self._chart_slots if panel is not None]

    def _slot_index_for_panel(self, panel: HistoricalChartPanel) -> Optional[int]:
        for index, slot_panel in enumerate(self._chart_slots):
            if slot_panel is panel:
                return index
        return None

    def _first_available_slot_index(self) -> Optional[int]:
        reserved_slots = set(self._detached_slots.values())
        for index, panel in enumerate(self._chart_slots):
            if panel is None and index not in reserved_slots:
                return index
        return None

    def _remove_chart(
        self,
        panel: HistoricalChartPanel,
        *,
        preserve_detached_slot: bool,
    ) -> bool:
        slot_index = self._slot_index_for_panel(panel)
        if slot_index is None:
            return False

        self._chart_slots[slot_index] = None
        if preserve_detached_slot:
            self._detached_slots[panel] = slot_index
            try:
                panel.destroyed.connect(lambda _=None, panel=panel: self._forget_detached_panel(panel))
            except Exception:
                pass
        else:
            self._detached_slots.pop(panel, None)

        self._clear_layout()
        panel.setParent(None)
        self._relayout()
        return True

    def _forget_detached_panel(self, panel: HistoricalChartPanel) -> None:
        self._detached_slots.pop(panel, None)

    def _sync_panel_position(self, panel: HistoricalChartPanel, slot_index: int) -> None:
        sync_position = getattr(panel, "set_workspace_position", None)
        if callable(sync_position):
            try:
                sync_position(slot_index + 1)
            except Exception:
                pass

    def _sync_all_panel_positions(self) -> None:
        for index, panel in enumerate(self._chart_slots):
            if panel is not None:
                self._sync_panel_position(panel, index)

    def _update_visualization_mode_geometry(self) -> None:
        if self._visualization_mode == self.VIEW_MODE_SCROLL_4:
            row_count = self._visual_layout_row_count()
            viewport_height = self._scroll_area.viewport().height()
            if row_count > 2:
                minimum_height = int(viewport_height * (row_count / 2))
            else:
                minimum_height = 0
            self._grid_host.setMinimumHeight(max(minimum_height, 0))
            self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            return

        self._grid_host.setMinimumHeight(0)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _visual_layout_row_count(self) -> int:
        count = self.chart_count()
        if count <= 2:
            return 1 if count else 0
        if count == 3:
            return 2
        return (count + 1) // 2

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_visualization_mode_geometry()

    def _clear_layout(self) -> None:
        while self._grid.count() > 0:
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self._grid_host)

    def _relayout(self) -> None:
        self._clear_layout()

        embedded_panels = [
            (slot_index, panel)
            for slot_index, panel in enumerate(self._chart_slots)
            if panel is not None
        ]
        if not embedded_panels:
            self._scroll_area.hide()
            self._grid_host.hide()
            self._empty_state.show()
            return

        self._empty_state.hide()
        self._grid_host.show()
        self._scroll_area.show()
        self._update_visualization_mode_geometry()

        row_count = self._visual_layout_row_count()
        for row in range(self.SLOT_ROWS):
            self._grid.setRowStretch(row, 1 if row < row_count else 0)
        for col in range(4):
            self._grid.setColumnStretch(col, 1 if col < self.SLOT_COLUMNS else 0)

        for visual_index, (slot_index, panel) in enumerate(embedded_panels):
            row, col, row_span, col_span = self._visual_grid_position(
                visual_index,
                len(embedded_panels),
            )
            self._grid.addWidget(panel, row, col, row_span, col_span)
            self._sync_panel_position(panel, slot_index)

    def _visual_grid_position(self, visual_index: int, count: int) -> tuple[int, int, int, int]:
        if count == 1:
            return 0, 0, 1, self.SLOT_COLUMNS

        if count == 3 and visual_index == 0:
            return 0, 0, 1, self.SLOT_COLUMNS

        if count in {5, 7} and visual_index == count - 1:
            return visual_index // self.SLOT_COLUMNS, 0, 1, self.SLOT_COLUMNS

        if count == 3:
            adjusted_index = visual_index - 1
            return 1, adjusted_index, 1, 1

        return visual_index // self.SLOT_COLUMNS, visual_index % self.SLOT_COLUMNS, 1, 1

    def warn_max_charts(self) -> None:
        QMessageBox.information(
            self,
            "Historical Workspace",
            "Maximum of 8 historical charts reached.",
        )
