from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.data.chart_presets.study_setup_store import ChartStudySetupStore
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshotStore,
)
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PRESET_STATUS_WARNING,
    PresetCompatibilityReport,
    evaluate_study_setup_compatibility,
    evaluate_workspace_snapshot_compatibility,
    format_compatibility_report,
)
from leonardo.gui.windows._historical_data_manager.study_setup_dialogs import (
    LoadStudySetupDialog,
    SaveStudySetupDialog,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_dialogs import (
    LoadWorkspaceSnapshotDialog,
    SaveWorkspaceSnapshotDialog,
)
from leonardo.gui.windows.historical_workspace_widget import HistoricalWorkspaceWidget


class HistoricalChartSelectionDialog(QDialog):
    """
    Dialog used to select a historical dataset path in a guided order:

    Exchange -> Market Type -> Asset -> Timeframe

    Data source:
    CoreBridge → HistoricalDatasetService dataset catalog
    """

    def __init__(
        self,
        *,
        ctx: AppContext,
        core_bridge: CoreBridge,
        window_manager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._ctx = ctx
        self._core = core_bridge
        self._window_manager = window_manager
        self._is_registered = False

        self._selected_exchange: str = ""
        self._selected_market_type: str = ""
        self._selected_asset: str = ""
        self._selected_timeframe: str = ""

        self.setWindowTitle("New Historical Chart")
        self.setModal(True)
        self.resize(460, 240)


        self._exchange_combo: Optional[QComboBox] = None
        self._market_type_combo: Optional[QComboBox] = None
        self._asset_combo: Optional[QComboBox] = None
        self._timeframe_combo: Optional[QComboBox] = None
        self._load_button: Optional[QPushButton] = None
        self._close_button: Optional[QPushButton] = None
        self._info_label: Optional[QLabel] = None

        self._build_ui()
        self._populate_exchanges()

    def selected_dataset(self) -> tuple[str, str, str, str]:
        return (
            self._selected_exchange,
            self._selected_market_type,
            self._selected_asset,
            self._selected_timeframe,
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._register_window()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._unregister_window()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._unregister_window()
        super().done(result)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        info_label = QLabel(
            "Select exchange, market type, asset, and timeframe in order.",
            self,
        )
        info_label.setWordWrap(True)
        self._info_label = info_label

        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        exchange_combo = QComboBox(self)
        exchange_combo.currentIndexChanged.connect(self._on_exchange_changed)
        self._exchange_combo = exchange_combo

        market_type_combo = QComboBox(self)
        market_type_combo.setEnabled(False)
        market_type_combo.currentIndexChanged.connect(self._on_market_type_changed)
        self._market_type_combo = market_type_combo

        asset_combo = QComboBox(self)
        asset_combo.setEnabled(False)
        asset_combo.currentIndexChanged.connect(self._on_asset_changed)
        self._asset_combo = asset_combo

        timeframe_combo = QComboBox(self)
        timeframe_combo.setEnabled(False)
        timeframe_combo.currentIndexChanged.connect(self._on_timeframe_changed)
        self._timeframe_combo = timeframe_combo

        form_layout.addRow("Exchange", exchange_combo)
        form_layout.addRow("Market Type", market_type_combo)
        form_layout.addRow("Asset", asset_combo)
        form_layout.addRow("Timeframe", timeframe_combo)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        load_button = QPushButton("Load Data", self)
        load_button.setEnabled(False)
        load_button.clicked.connect(self._on_load_data_clicked)
        self._load_button = load_button

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.reject)
        self._close_button = close_button

        button_layout.addWidget(load_button)
        button_layout.addWidget(close_button)

        root_layout.addWidget(info_label)
        root_layout.addLayout(form_layout)
        root_layout.addStretch(1)
        root_layout.addLayout(button_layout)

    def _populate_exchanges(self) -> None:
        if self._exchange_combo is None:
            return

        self._reset_combo(self._exchange_combo, placeholder="")
        self._reset_combo(self._market_type_combo, placeholder="")
        self._reset_combo(self._asset_combo, placeholder="")
        self._reset_combo(self._timeframe_combo, placeholder="")

        try:
            exchange_names = self._core.list_historical_dataset_exchanges()
        except Exception as e:
            self._exchange_combo.setEnabled(False)
            self._set_info_text(f"Historical dataset catalog is unavailable: {e!r}")
            return

        for exchange_name in exchange_names:
            display_name = self._capitalize_first_letter(exchange_name)
            self._exchange_combo.addItem(display_name, exchange_name)

        has_values = bool(exchange_names)
        self._exchange_combo.setEnabled(has_values)
        if has_values:
            self._set_info_text("Select an exchange to continue.")
        else:
            self._set_info_text("No historical OHLCV datasets were found.")

    def _populate_market_types(self, exchange_name: str) -> None:
        if self._market_type_combo is None:
            return

        self._reset_combo(self._market_type_combo, placeholder="")
        self._reset_combo(self._asset_combo, placeholder="")
        self._reset_combo(self._timeframe_combo, placeholder="")

        try:
            market_type_names = self._core.list_historical_dataset_market_types(exchange_name)
        except Exception as e:
            self._market_type_combo.setEnabled(False)
            self._set_info_text(f"Could not list market types: {e!r}")
            self._update_load_button_state()
            return

        for market_type_name in market_type_names:
            self._market_type_combo.addItem(market_type_name, market_type_name)

        self._market_type_combo.setEnabled(self._market_type_combo.count() > 1)
        if self._asset_combo is not None:
            self._asset_combo.setEnabled(False)
        if self._timeframe_combo is not None:
            self._timeframe_combo.setEnabled(False)

        self._update_load_button_state()
        if market_type_names:
            self._set_info_text("Select a market type.")
        else:
            self._set_info_text("No market types are available for this exchange.")

    def _populate_assets(self, exchange_name: str, market_type_name: str) -> None:
        if self._asset_combo is None:
            return

        self._reset_combo(self._asset_combo, placeholder="")
        self._reset_combo(self._timeframe_combo, placeholder="")

        try:
            asset_names = self._core.list_historical_dataset_symbols(
                exchange_name,
                market_type_name,
            )
        except Exception as e:
            self._asset_combo.setEnabled(False)
            self._set_info_text(f"Could not list assets: {e!r}")
            self._update_load_button_state()
            return

        for asset_name in asset_names:
            self._asset_combo.addItem(asset_name, asset_name)

        self._asset_combo.setEnabled(self._asset_combo.count() > 1)
        if self._timeframe_combo is not None:
            self._timeframe_combo.setEnabled(False)

        self._update_load_button_state()
        if asset_names:
            self._set_info_text("Select an asset.")
        else:
            self._set_info_text("No assets are available for this exchange/market type.")

    def _populate_timeframes(
        self,
        exchange_name: str,
        market_type_name: str,
        asset_name: str,
    ) -> None:
        if self._timeframe_combo is None:
            return

        self._reset_combo(self._timeframe_combo, placeholder="")

        try:
            timeframe_names = self._core.list_historical_dataset_timeframes(
                exchange_name,
                market_type_name,
                asset_name,
            )
        except Exception as e:
            self._timeframe_combo.setEnabled(False)
            self._set_info_text(f"Could not list timeframes: {e!r}")
            self._update_load_button_state()
            return

        for timeframe_name in timeframe_names:
            self._timeframe_combo.addItem(timeframe_name, timeframe_name)

        self._timeframe_combo.setEnabled(self._timeframe_combo.count() > 1)
        self._update_load_button_state()
        if timeframe_names:
            self._set_info_text("Select a timeframe.")
        else:
            self._set_info_text("No timeframes are available for this asset.")

    def _on_exchange_changed(self) -> None:
        exchange_name = self._current_data(self._exchange_combo)
        if not exchange_name:
            self._reset_combo(self._market_type_combo, placeholder="")
            self._reset_combo(self._asset_combo, placeholder="")
            self._reset_combo(self._timeframe_combo, placeholder="")
            if self._market_type_combo is not None:
                self._market_type_combo.setEnabled(False)
            if self._asset_combo is not None:
                self._asset_combo.setEnabled(False)
            if self._timeframe_combo is not None:
                self._timeframe_combo.setEnabled(False)
            self._update_load_button_state()
            self._set_info_text("Select an exchange to continue.")
            return

        self._populate_market_types(exchange_name)

    def _on_market_type_changed(self) -> None:
        exchange_name = self._current_data(self._exchange_combo)
        market_type_name = self._current_data(self._market_type_combo)

        if not exchange_name or not market_type_name:
            self._reset_combo(self._asset_combo, placeholder="")
            self._reset_combo(self._timeframe_combo, placeholder="")
            if self._asset_combo is not None:
                self._asset_combo.setEnabled(False)
            if self._timeframe_combo is not None:
                self._timeframe_combo.setEnabled(False)
            self._update_load_button_state()
            self._set_info_text("Select a market type.")
            return

        self._populate_assets(exchange_name, market_type_name)

    def _on_asset_changed(self) -> None:
        exchange_name = self._current_data(self._exchange_combo)
        market_type_name = self._current_data(self._market_type_combo)
        asset_name = self._current_data(self._asset_combo)

        if not exchange_name or not market_type_name or not asset_name:
            self._reset_combo(self._timeframe_combo, placeholder="")
            if self._timeframe_combo is not None:
                self._timeframe_combo.setEnabled(False)
            self._update_load_button_state()
            self._set_info_text("Select an asset.")
            return

        self._populate_timeframes(exchange_name, market_type_name, asset_name)

    def _on_timeframe_changed(self) -> None:
        self._update_load_button_state()

        if self._has_complete_selection():
            self._set_info_text("Selection complete. Load Data is available.")
        else:
            self._set_info_text("Select a timeframe.")

    def _on_load_data_clicked(self) -> None:
        selected_exchange = self._current_data(self._exchange_combo)
        selected_market_type = self._current_data(self._market_type_combo)
        selected_asset = self._current_data(self._asset_combo)
        selected_timeframe = self._current_data(self._timeframe_combo)

        if not selected_exchange or not selected_market_type or not selected_asset or not selected_timeframe:
            QMessageBox.warning(
                self,
                "Load Data",
                "Dataset selection is incomplete.",
            )
            return

        try:
            exists = self._core.historical_dataset_exists(
                exchange=selected_exchange,
                market_type=selected_market_type,
                symbol=selected_asset,
                timeframe=selected_timeframe,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Load Data",
                f"Could not validate dataset through Core: {e!r}",
            )
            return

        if not exists:
            QMessageBox.warning(
                self,
                "Load Data",
                "Selected dataset is not available through the Core historical dataset service.",
            )
            return

        self._selected_exchange = selected_exchange
        self._selected_market_type = selected_market_type
        self._selected_asset = selected_asset
        self._selected_timeframe = selected_timeframe

        self.accept()

    def _register_window(self) -> None:
        if self._is_registered:
            return
        try:
            self._core.submit(
                self._ctx.state.window_open(
                    "historical_chart_selection_dialog",
                    "HistoricalChartSelectionDialog",
                    where="gui",
                )
            )
            self._is_registered = True
        except Exception:
            pass

    def _unregister_window(self) -> None:
        if not self._is_registered:
            return
        try:
            self._core.submit(
                self._ctx.state.window_close(
                    "historical_chart_selection_dialog",
                    where="gui",
                )
            )
        except Exception:
            pass
        self._is_registered = False

    def _has_complete_selection(self) -> bool:
        return (
            bool(self._current_data(self._exchange_combo))
            and bool(self._current_data(self._market_type_combo))
            and bool(self._current_data(self._asset_combo))
            and bool(self._current_data(self._timeframe_combo))
        )

    def _update_load_button_state(self) -> None:
        if self._load_button is not None:
            self._load_button.setEnabled(self._has_complete_selection())

    def _set_info_text(self, text: str) -> None:
        if self._info_label is not None:
            self._info_label.setText(text)

    @staticmethod
    def _reset_combo(combo: Optional[QComboBox], placeholder: str = "") -> None:
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, "")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    @staticmethod
    def _current_data(combo: Optional[QComboBox]) -> str:
        if combo is None:
            return ""
        data = combo.currentData()
        return str(data) if data is not None else ""

    @staticmethod
    def _capitalize_first_letter(text: str) -> str:
        if not text:
            return text
        return text[0].upper() + text[1:]



class HistoricalDataManagerWindow(QMainWindow):
    """
    Top-level shell window for Leonardo historical data management.

    Current scope:
    - dedicated top-level QMainWindow
    - menu bar with 3 menus
    - status bar
    - central workspace area

    Future scope:
    - host up to 4 embedded historical chart panels
    - dataset actions
    - timeframe / layout management
    - detachable historical chart windows
    """

    def __init__(
        self,
        *,
        ctx: AppContext,
        core_bridge: CoreBridge,
        window_manager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._ctx = ctx
        self._core = core_bridge
        self._window_manager = window_manager

        self.setWindowTitle("Leonardo - Historical Data Manager")
        self.resize(1400, 900)

        self._menu_bar: Optional[QMenuBar] = None
        self._status_bar: Optional[QStatusBar] = None

        self._menu_file: Optional[QMenu] = None
        self._menu_window: Optional[QMenu] = None
        self._menu_historical: Optional[QMenu] = None
        self._study_setup_toolbar: Optional[QToolBar] = None

        self._action_new_chart: Optional[QAction] = None
        self._action_save_study_setup: Optional[QAction] = None
        self._action_load_study_setup: Optional[QAction] = None
        self._action_save_workspace_snapshot: Optional[QAction] = None
        self._action_load_workspace_snapshot: Optional[QAction] = None
        self._action_close: Optional[QAction] = None
        self._action_placeholder_tile: Optional[QAction] = None
        self._action_placeholder_open_chart: Optional[QAction] = None
        self._action_placeholder_open_dataset: Optional[QAction] = None
        self._action_placeholder_refresh: Optional[QAction] = None
        self._action_view_mode_scroll_4: Optional[QAction] = None
        self._action_view_mode_fit_8: Optional[QAction] = None
        self._view_mode_action_group: Optional[QActionGroup] = None
        self._view_mode_label: Optional[QLabel] = None

        self._workspace_widget: Optional[HistoricalWorkspaceWidget] = None
        self._is_closing: bool = False

        self._build_ui()

    def workspace_widget(self) -> Optional[HistoricalWorkspaceWidget]:
        return self._workspace_widget

    def closeEvent(self, event: QCloseEvent) -> None:
        """Tear down embedded chart sessions before the shell is destroyed.

        The Historical Data Manager owns the embedded workspace shell, not the
        controller internals of each chart. It therefore delegates teardown to
        the workspace-owned panel lifecycle rather than reaching into resident
        truth or pane semantics directly.
        """
        if self._is_closing:
            super().closeEvent(event)
            return

        self._is_closing = True

        notify_closing = getattr(self._window_manager, "notify_historical_data_manager_closing", None)
        if callable(notify_closing):
            try:
                notify_closing(self)
            except Exception:
                pass

        clear_all_charts = getattr(self._workspace_widget, "clear_all_charts", None)
        if callable(clear_all_charts):
            try:
                clear_all_charts()
            except Exception:
                pass

        super().closeEvent(event)

    def _build_ui(self) -> None:
        self._build_menu_bar()
        self._build_status_bar()
        self._build_central_widget()

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        self._menu_bar = menu_bar

        menu_file = menu_bar.addMenu("File")
        menu_window = menu_bar.addMenu("Window")
        menu_historical = menu_bar.addMenu("Historical")

        self._menu_file = menu_file
        self._menu_window = menu_window
        self._menu_historical = menu_historical

        action_new_chart = QAction("New Chart", self)
        action_new_chart.triggered.connect(self._on_new_chart)
        self._action_new_chart = action_new_chart
        menu_file.addAction(action_new_chart)

        menu_file.addSeparator()

        action_save_study_setup = QAction("Save Study Setup...", self)
        action_save_study_setup.setToolTip(
            "Save the studies, parameters, and styles from one chart."
        )
        action_save_study_setup.setStatusTip(
            "Save the studies, parameters, and styles from one chart."
        )
        action_save_study_setup.triggered.connect(self._on_save_study_setup)
        self._action_save_study_setup = action_save_study_setup
        menu_file.addAction(action_save_study_setup)

        action_load_study_setup = QAction("Load Study Setup...", self)
        action_load_study_setup.setToolTip("Apply a saved study setup to a chart.")
        action_load_study_setup.setStatusTip("Apply a saved study setup to a chart.")
        action_load_study_setup.triggered.connect(self._on_load_study_setup)
        self._action_load_study_setup = action_load_study_setup
        menu_file.addAction(action_load_study_setup)

        menu_file.addSeparator()

        action_save_workspace_snapshot = QAction("Save Workspace Snapshot...", self)
        action_save_workspace_snapshot.setToolTip(
            "Save all embedded charts, positions, view mode, studies, parameters, and styles."
        )
        action_save_workspace_snapshot.setStatusTip(
            "Save all embedded charts, positions, view mode, studies, parameters, and styles."
        )
        action_save_workspace_snapshot.triggered.connect(self._on_save_workspace_snapshot)
        self._action_save_workspace_snapshot = action_save_workspace_snapshot
        menu_file.addAction(action_save_workspace_snapshot)

        action_load_workspace_snapshot = QAction("Load Workspace Snapshot...", self)
        action_load_workspace_snapshot.setToolTip(
            "Load a saved historical workspace snapshot."
        )
        action_load_workspace_snapshot.setStatusTip(
            "Load a saved historical workspace snapshot."
        )
        action_load_workspace_snapshot.triggered.connect(self._on_load_workspace_snapshot)
        self._action_load_workspace_snapshot = action_load_workspace_snapshot
        menu_file.addAction(action_load_workspace_snapshot)

        menu_file.addSeparator()

        action_close = QAction("Close", self)
        action_close.triggered.connect(self.close)
        self._action_close = action_close
        menu_file.addAction(action_close)

        menu_file.addSeparator()

        action_open_dataset = QAction("Open Dataset", self)
        action_open_dataset.triggered.connect(self._on_open_dataset_placeholder)
        self._action_placeholder_open_dataset = action_open_dataset
        menu_file.addAction(action_open_dataset)

        action_tile = QAction("Tile Subwindows", self)
        action_tile.triggered.connect(self._on_tile_subwindows_placeholder)
        self._action_placeholder_tile = action_tile
        menu_window.addAction(action_tile)

        menu_window.addSeparator()

        view_mode_group = QActionGroup(self)
        view_mode_group.setExclusive(True)
        self._view_mode_action_group = view_mode_group

        action_view_scroll_4 = QAction("Scroll 4", self, checkable=True)
        action_view_scroll_4.triggered.connect(
            lambda checked: checked
            and self._set_workspace_visualization_mode(HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4)
        )
        self._action_view_mode_scroll_4 = action_view_scroll_4
        view_mode_group.addAction(action_view_scroll_4)
        menu_window.addAction(action_view_scroll_4)

        action_view_fit_8 = QAction("Fit 8", self, checkable=True)
        action_view_fit_8.triggered.connect(
            lambda checked: checked
            and self._set_workspace_visualization_mode(HistoricalWorkspaceWidget.VIEW_MODE_FIT_8)
        )
        self._action_view_mode_fit_8 = action_view_fit_8
        view_mode_group.addAction(action_view_fit_8)
        menu_window.addAction(action_view_fit_8)

        view_mode_label = QLabel(self)
        view_mode_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        view_mode_label.setStyleSheet(
            "QLabel { color: rgb(190, 190, 205); padding-left: 12px; padding-right: 12px; }"
        )
        self._view_mode_label = view_mode_label
        menu_bar.setCornerWidget(view_mode_label, Qt.TopRightCorner)

        action_open_chart = QAction("Open Historical Chart", self)
        action_open_chart.triggered.connect(self._on_open_chart_placeholder)
        self._action_placeholder_open_chart = action_open_chart
        menu_historical.addAction(action_open_chart)

        action_refresh = QAction("Refresh", self)
        action_refresh.triggered.connect(self._on_refresh_placeholder)
        self._action_placeholder_refresh = action_refresh
        menu_historical.addAction(action_refresh)

        study_setup_toolbar = QToolBar("Study Setups", self)
        study_setup_toolbar.setObjectName("historicalDataManagerStudySetupToolbar")
        study_setup_toolbar.setMovable(False)
        study_setup_toolbar.addAction(self._action_save_study_setup)
        study_setup_toolbar.addAction(self._action_load_study_setup)
        study_setup_toolbar.addAction(self._action_save_workspace_snapshot)
        study_setup_toolbar.addAction(self._action_load_workspace_snapshot)
        self.addToolBar(Qt.TopToolBarArea, study_setup_toolbar)
        self._study_setup_toolbar = study_setup_toolbar

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        status_bar.setSizeGripEnabled(False)
        status_bar.showMessage("Historical Data Manager ready")
        self.setStatusBar(status_bar)
        self._status_bar = status_bar

    def _build_central_widget(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        workspace_widget = HistoricalWorkspaceWidget(
            core_bridge=self._core,
            window_manager=self._window_manager,
            parent=root,
        )
        self._workspace_widget = workspace_widget
        workspace_widget.visualization_mode_changed.connect(self._on_workspace_view_mode_changed)

        layout.addWidget(workspace_widget, 1)

        self.setCentralWidget(root)
        self._sync_view_mode_controls()

    def _set_workspace_visualization_mode(self, mode: str) -> None:
        if self._workspace_widget is None:
            self._set_status("Historical workspace not ready")
            self._sync_view_mode_controls()
            return
        self._workspace_widget.set_visualization_mode(mode)

    def _on_workspace_view_mode_changed(self, _mode: str) -> None:
        self._sync_view_mode_controls()

    def _sync_view_mode_controls(self) -> None:
        workspace = self._workspace_widget
        mode = (
            workspace.visualization_mode()
            if workspace is not None
            else HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4
        )

        if self._action_view_mode_scroll_4 is not None:
            self._action_view_mode_scroll_4.blockSignals(True)
            self._action_view_mode_scroll_4.setChecked(mode == HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4)
            self._action_view_mode_scroll_4.blockSignals(False)

        if self._action_view_mode_fit_8 is not None:
            self._action_view_mode_fit_8.blockSignals(True)
            self._action_view_mode_fit_8.setChecked(mode == HistoricalWorkspaceWidget.VIEW_MODE_FIT_8)
            self._action_view_mode_fit_8.blockSignals(False)

        if self._view_mode_label is not None:
            self._view_mode_label.setText(
                f"View: {HistoricalWorkspaceWidget.visualization_mode_label(mode)}"
            )

    def _on_new_chart(self) -> None:
        if self._workspace_widget is None:
            self._set_status("Historical workspace not ready")
            return

        if not self._workspace_widget.can_add_chart():
            self._workspace_widget.warn_max_charts()
            self._set_status("Maximum of 8 historical charts reached")
            return

        dialog = HistoricalChartSelectionDialog(
            ctx=self._ctx,
            core_bridge=self._core,
            window_manager=self._window_manager,
            parent=self,
        )

        if dialog.exec() != QDialog.Accepted:
            self._set_status("Historical chart creation cancelled")
            return

        exchange, market_type, symbol, timeframe = dialog.selected_dataset()
        if not exchange or not market_type or not symbol or not timeframe:
            self._set_status("Historical chart dataset selection was incomplete")
            return

        created = self._workspace_widget.add_chart(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
        )
        if not created:
            self._workspace_widget.warn_max_charts()
            self._set_status("Maximum of 8 historical charts reached")
            return

        exchange_display = exchange[:1].upper() + exchange[1:] if exchange else exchange
        self._set_status(
            f"Embedded chart loaded: {exchange_display}_{market_type}_{symbol}_{timeframe}"
        )

    def _chart_study_setup_store_root(self) -> Path:
        return Path(self._ctx.config.runtime.data_dir) / "chart_presets" / "study_setups"

    def _chart_study_setup_store(self) -> ChartStudySetupStore:
        return ChartStudySetupStore(self._chart_study_setup_store_root())

    def _workspace_snapshot_store_root(self) -> Path:
        return Path(self._ctx.config.runtime.data_dir) / "chart_presets" / "workspace_snapshots"

    def _workspace_snapshot_store(self) -> HistoricalWorkspaceSnapshotStore:
        return HistoricalWorkspaceSnapshotStore(self._workspace_snapshot_store_root())

    def _chart_options(self) -> list[dict[str, Any]]:
        workspace = self._workspace_widget
        if workspace is None:
            return []

        options: list[dict[str, Any]] = []
        for position, panel in workspace.list_embedded_chart_panels():
            dataset = panel.dataset_descriptor()
            studies = panel.study_setup_recap_entries()
            label = (
                f"Position {position}: "
                f"{dataset.get('exchange', '')} / "
                f"{dataset.get('market_type', '')} / "
                f"{dataset.get('symbol', '')} / "
                f"{dataset.get('timeframe', '')}"
            )
            options.append(
                {
                    "position": position,
                    "label": label,
                    "dataset": dataset,
                    "study_count": len(studies),
                    "studies": studies,
                }
            )
        return options

    def _panel_for_chart_position(self, position: int):
        workspace = self._workspace_widget
        if workspace is None:
            return None
        return workspace.get_panel_by_position(int(position))

    def _on_save_study_setup(self) -> None:
        chart_options = self._chart_options()
        if not chart_options:
            QMessageBox.information(
                self,
                "Save Study Setup",
                "Open a historical chart before saving a study setup.",
            )
            return

        dialog = SaveStudySetupDialog(chart_options=chart_options, parent=self)
        if dialog.exec() != QDialog.Accepted:
            self._set_status("Study setup save cancelled")
            return

        panel = self._panel_for_chart_position(dialog.selected_chart_position())
        if panel is None:
            QMessageBox.warning(
                self,
                "Save Study Setup",
                "Selected source chart is no longer available.",
            )
            return

        try:
            studies = panel.export_serialized_studies()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Save Study Setup",
                f"Could not serialize chart studies: {exc!r}",
            )
            return

        if not studies:
            QMessageBox.information(
                self,
                "Save Study Setup",
                "The selected chart has no studies to save.",
            )
            return

        store = self._chart_study_setup_store()
        try:
            setup = store.create_setup(
                display_name=dialog.display_name(),
                description=dialog.description(),
                created_from=panel.dataset_descriptor(),
                studies=studies,
            )
            saved = store.save_setup(setup)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Save Study Setup",
                f"Could not save study setup: {exc!r}",
            )
            return

        self._set_status(f"Saved study setup: {saved.display_name}")
        QMessageBox.information(
            self,
            "Save Study Setup",
            f"Saved study setup '{saved.display_name}'.",
        )

    def _load_study_setup_objects(self):
        store = self._chart_study_setup_store()
        setups = []
        for summary in store.list_summaries():
            try:
                setups.append(store.load_setup(summary.setup_id))
            except Exception:
                continue
        return setups

    def _load_workspace_snapshot_objects(self):
        store = self._workspace_snapshot_store()
        snapshots = []
        for summary in store.list_summaries():
            try:
                snapshots.append(store.load_snapshot(summary.snapshot_id))
            except Exception:
                continue
        return snapshots

    def _on_save_workspace_snapshot(self) -> None:
        workspace = self._workspace_widget
        if workspace is None:
            self._set_status("Historical workspace not ready")
            return

        try:
            snapshot_payload = workspace.export_workspace_snapshot_payload()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Save Workspace Snapshot",
                f"Could not collect workspace snapshot data: {exc!r}",
            )
            return

        charts = list(snapshot_payload.get("charts", []) or [])
        if not charts:
            QMessageBox.information(
                self,
                "Save Workspace Snapshot",
                "Open at least one embedded historical chart before saving a workspace snapshot.",
            )
            return

        dialog = SaveWorkspaceSnapshotDialog(
            snapshot_payload=snapshot_payload,
            detached_reserved_slot_count=workspace.detached_reserved_slot_count(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            self._set_status("Workspace snapshot save cancelled")
            return

        store = self._workspace_snapshot_store()
        try:
            snapshot = store.create_snapshot(
                display_name=dialog.display_name(),
                description=dialog.description(),
                workspace=dict(snapshot_payload.get("workspace", {}) or {}),
                charts=charts,
            )
            saved = store.save_snapshot(snapshot)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Save Workspace Snapshot",
                f"Could not save workspace snapshot: {exc!r}",
            )
            return

        self._set_status(f"Saved workspace snapshot: {saved.display_name}")
        QMessageBox.information(
            self,
            "Save Workspace Snapshot",
            f"Saved workspace snapshot '{saved.display_name}'.",
        )

    def _on_load_workspace_snapshot(self) -> None:
        workspace = self._workspace_widget
        if workspace is None:
            self._set_status("Historical workspace not ready")
            return

        snapshots = self._load_workspace_snapshot_objects()
        if not snapshots:
            QMessageBox.information(
                self,
                "Load Workspace Snapshot",
                "No saved workspace snapshots were found.",
            )
            return

        def compatibility_provider(snapshot, load_mode: str) -> PresetCompatibilityReport:
            return evaluate_workspace_snapshot_compatibility(
                snapshot,
                workspace=workspace,
                core_bridge=self._core,
                load_mode=load_mode,
            )

        dialog = LoadWorkspaceSnapshotDialog(
            snapshots=snapshots,
            current_chart_count=workspace.chart_count(),
            available_slot_count=workspace.available_embedded_slot_count(),
            detached_reserved_slot_count=workspace.detached_reserved_slot_count(),
            compatibility_provider=compatibility_provider,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            self._set_status("Workspace snapshot load cancelled")
            return

        store = self._workspace_snapshot_store()
        try:
            snapshot = store.load_snapshot(dialog.selected_snapshot_id())
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Load Workspace Snapshot",
                f"Could not load workspace snapshot: {exc!r}",
            )
            return

        charts = [dict(chart) for chart in snapshot.charts]
        load_mode = dialog.load_mode()
        compatibility_report = compatibility_provider(snapshot, load_mode)
        if not compatibility_report.can_load:
            QMessageBox.warning(
                self,
                "Load Workspace Snapshot",
                "Selected workspace snapshot cannot be loaded:\n\n"
                + format_compatibility_report(compatibility_report),
            )
            return
        if compatibility_report.status == PRESET_STATUS_WARNING:
            QMessageBox.warning(
                self,
                "Load Workspace Snapshot",
                "Selected workspace snapshot will load with warnings:\n\n"
                + format_compatibility_report(compatibility_report),
            )

        try:
            workspace.load_workspace_snapshot_charts(charts, mode=load_mode)
            workspace.set_visualization_mode(
                str(
                    snapshot.workspace.get(
                        "visualization_mode",
                        HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4,
                    )
                    or HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4
                )
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Load Workspace Snapshot",
                f"Could not start workspace snapshot load: {exc!r}",
            )
            return

        self._sync_view_mode_controls()
        self._set_status(
            f"Loading workspace snapshot '{snapshot.display_name}' "
            f"({len(charts)} chart(s))"
        )
        QMessageBox.information(
            self,
            "Load Workspace Snapshot",
            f"Workspace snapshot '{snapshot.display_name}' is loading. "
            "Studies and viewport state restore after each chart opens.",
        )

    def _on_load_study_setup(self) -> None:
        chart_options = self._chart_options()
        if not chart_options:
            QMessageBox.information(
                self,
                "Load Study Setup",
                "Open a historical chart before loading a study setup.",
            )
            return

        setups = self._load_study_setup_objects()
        if not setups:
            QMessageBox.information(
                self,
                "Load Study Setup",
                "No saved study setups were found.",
            )
            return

        def compatibility_provider(setup, position: int, load_mode: str) -> PresetCompatibilityReport:
            return evaluate_study_setup_compatibility(
                setup,
                target_panel=self._panel_for_chart_position(position),
                load_mode=load_mode,
            )

        dialog = LoadStudySetupDialog(
            setups=setups,
            chart_options=chart_options,
            compatibility_provider=compatibility_provider,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            self._set_status("Study setup load cancelled")
            return

        store = self._chart_study_setup_store()
        try:
            setup = store.load_setup(dialog.selected_setup_id())
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                f"Could not load study setup: {exc!r}",
            )
            return

        studies = [dict(study) for study in setup.studies]
        panel = self._panel_for_chart_position(dialog.selected_target_chart_position())
        if panel is None:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                "Selected target chart is no longer available.",
            )
            return

        compatibility_report = compatibility_provider(
            setup,
            dialog.selected_target_chart_position(),
            dialog.load_mode(),
        )
        if not compatibility_report.can_load:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                "Selected setup cannot be loaded:\n\n"
                + format_compatibility_report(compatibility_report),
            )
            return
        if compatibility_report.status == PRESET_STATUS_WARNING:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                "Selected setup will load with warnings:\n\n"
                + format_compatibility_report(compatibility_report),
            )

        try:
            report = panel.apply_serialized_study_setup(
                studies,
                mode=dialog.load_mode(),
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                f"Could not apply study setup: {exc!r}",
            )
            return

        applied_count = int(report.get("applied_count", 0) or 0)
        errors = list(report.get("errors", []) or [])
        if errors:
            QMessageBox.warning(
                self,
                "Load Study Setup",
                f"Applied {applied_count} study/studies with errors:\n"
                + "\n".join(str(error) for error in errors[:8]),
            )
            return

        self._set_status(
            f"Loaded study setup '{setup.display_name}' "
            f"({applied_count} study/studies)"
        )
        QMessageBox.information(
            self,
            "Load Study Setup",
            f"Loaded study setup '{setup.display_name}' "
            f"onto the selected chart.",
        )

    def _on_open_dataset_placeholder(self) -> None:
        self._set_status("Open Dataset clicked")
        self._show_placeholder_message(
            title="Open Dataset",
            text="Dataset loading is currently handled through File → New Chart.",
        )

    def _on_tile_subwindows_placeholder(self) -> None:
        self._set_status("Tile Subwindows clicked")
        self._show_placeholder_message(
            title="Tile Subwindows",
            text="Embedded historical workspace tiling is now managed automatically.",
        )

    def _on_open_chart_placeholder(self) -> None:
        self._set_status("Open Historical Chart clicked")
        self._show_placeholder_message(
            title="Open Historical Chart",
            text="Use File → New Chart to create a new embedded historical chart.",
        )

    def _on_refresh_placeholder(self) -> None:
        self._set_status("Refresh clicked")
        self._show_placeholder_message(
            title="Refresh",
            text="Refresh behavior will be implemented later.",
        )

    def _set_status(self, message: str) -> None:
        if self._status_bar is not None:
            self._status_bar.showMessage(message)

    def _show_placeholder_message(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)
