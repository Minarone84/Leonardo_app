from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QShowEvent
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
    QInputDialog,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.data.chart_presets.notebook_store import (
    DEFAULT_POI_MARKER_OFFSET,
    HistoricalNotebookStore,
    notebook_chart_key,
)
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
from leonardo.gui.windows._historical_data_manager.notebook_window import (
    HistoricalNotebookWindow,
)
from leonardo.gui.windows._historical_data_manager.notebook_manager_dialog import (
    HistoricalNotebookManagerDialog,
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
        self._menu_notes: Optional[QMenu] = None

        # Single menu-bar corner widget used to keep quick actions and the
        # view-mode label on the same row as File / Window / Notes.
        #
        # This replaces the old separate toolbar row, which consumed vertical
        # chart space. The quick buttons still reuse the same QAction objects
        # as the File menu, so there is no duplicated command logic.
        self._menu_bar_corner_widget: Optional[QWidget] = None

        self._action_new_chart: Optional[QAction] = None
        self._action_save_study_setup: Optional[QAction] = None
        self._action_load_study_setup: Optional[QAction] = None
        self._action_save_workspace_snapshot: Optional[QAction] = None
        self._action_load_workspace_snapshot: Optional[QAction] = None
        self._action_pan_anchor: Optional[QAction] = None
        self._action_close: Optional[QAction] = None
        self._action_placeholder_tile: Optional[QAction] = None
        self._action_placeholder_open_dataset: Optional[QAction] = None
        self._action_create_notebook: Optional[QAction] = None
        self._action_notebook_manager: Optional[QAction] = None
        self._action_save_notebook: Optional[QAction] = None
        self._action_load_notebook: Optional[QAction] = None
        self._action_open_assigned_notebook: Optional[QAction] = None
        self._action_view_mode_scroll_4: Optional[QAction] = None
        self._action_view_mode_fit_8: Optional[QAction] = None
        self._view_mode_action_group: Optional[QActionGroup] = None
        self._view_mode_label: Optional[QLabel] = None

        self._workspace_widget: Optional[HistoricalWorkspaceWidget] = None
        self._notebook_window: Optional[HistoricalNotebookWindow] = None
        self._current_workspace_notebook_ref: Optional[dict[str, Any]] = None
        self._applying_notebook_poi_markers: bool = False
        self._syncing_pan_anchor: bool = False
        self._shown_maximized_once: bool = False
        self._is_closing: bool = False

        self._build_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._shown_maximized_once:
            return
        self._shown_maximized_once = True
        self.showMaximized()

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
        menu_notes = menu_bar.addMenu("Notes")

        self._menu_file = menu_file
        self._menu_window = menu_window
        self._menu_notes = menu_notes

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

        action_pan_anchor = QAction("Pan Anchor", self, checkable=True)
        action_pan_anchor.setToolTip(
            "Synchronize horizontal panning across all active historical charts."
        )
        action_pan_anchor.setStatusTip(
            "Synchronize horizontal panning across all active historical charts."
        )
        action_pan_anchor.setChecked(False)
        action_pan_anchor.toggled.connect(self._on_pan_anchor_toggled)
        self._action_pan_anchor = action_pan_anchor
        menu_window.addAction(action_pan_anchor)

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

        action_create_notebook = QAction("Create New Notebook", self)
        action_create_notebook.setToolTip("Create a chart-analysis notebook for the current workspace.")
        action_create_notebook.setStatusTip("Create a chart-analysis notebook for the current workspace.")
        action_create_notebook.triggered.connect(self._on_create_notebook)
        self._action_create_notebook = action_create_notebook
        menu_notes.addAction(action_create_notebook)

        action_open_assigned_notebook = QAction("Open Notebook", self)
        action_open_assigned_notebook.setToolTip(
            "No notebook assigned to the current workspace snapshot."
        )
        action_open_assigned_notebook.setStatusTip(
            "No notebook assigned to the current workspace snapshot."
        )
        action_open_assigned_notebook.setEnabled(False)
        action_open_assigned_notebook.triggered.connect(self._on_open_assigned_notebook)
        self._action_open_assigned_notebook = action_open_assigned_notebook
        menu_notes.addAction(action_open_assigned_notebook)

        action_notebook_manager = QAction("Notebook Manager...", self)
        action_notebook_manager.setToolTip("Manage saved notebooks and workspace snapshot assignments.")
        action_notebook_manager.setStatusTip("Manage saved notebooks and workspace snapshot assignments.")
        action_notebook_manager.triggered.connect(self._on_open_notebook_manager)
        self._action_notebook_manager = action_notebook_manager
        menu_notes.addAction(action_notebook_manager)

        action_save_notebook = QAction("Save Notebook", self)
        action_save_notebook.setToolTip("Save the active historical notebook.")
        action_save_notebook.setStatusTip("Save the active historical notebook.")
        action_save_notebook.triggered.connect(self._on_save_notebook)
        self._action_save_notebook = action_save_notebook
        menu_notes.addAction(action_save_notebook)

        action_load_notebook = QAction("Load Notebook", self)
        action_load_notebook.setToolTip("Load a saved historical notebook.")
        action_load_notebook.setStatusTip("Load a saved historical notebook.")
        action_load_notebook.triggered.connect(self._on_load_notebook)
        self._action_load_notebook = action_load_notebook
        menu_notes.addAction(action_load_notebook)

        # Keep quick preset/snapshot actions on the same row as the menu bar.
        #
        # Qt supports only one TopRightCorner widget, and the view-mode label
        # already lived there. So instead of creating a second toolbar row, we
        # build one compact corner widget that contains:
        #
        #   Open Notebook | Save Study | Load Study | Save Workspace | Load Workspace | Pan Anchor | View label
        #
        # Each button still uses the same QAction object that is already in a
        # standard menu. This preserves one command source and avoids duplicated
        # business logic.
        self._build_menu_bar_corner_widget(menu_bar)

    def _build_menu_bar_corner_widget(self, menu_bar: QMenuBar) -> None:
        """Build the compact right-side widget for the menu-bar row.

        This widget replaces the old separate Study Setups toolbar.

        Ownership rules:
        - The standard menus still own the full user-facing command names.
        - The compact buttons reuse the exact same QAction objects.
        - The view-mode label remains owned by this window and is still updated
          by _sync_view_mode_controls().
        - No chart/preset/save/load business logic is duplicated here.
        """
        corner_widget = QWidget(menu_bar)
        corner_widget.setObjectName("historicalDataManagerMenuBarCornerWidget")

        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 6, 0)
        corner_layout.setSpacing(4)

        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_open_assigned_notebook,
                text="Notebook",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )

        # Study Setup quick actions.
        #
        # These are intentionally short labels because they live in the menu
        # bar row. The full action names remain available in the File menu.
        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_save_study_setup,
                text="Save Study",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            )
        )
        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_load_study_setup,
                text="Load Study",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )

        # Workspace Snapshot quick actions.
        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_save_workspace_snapshot,
                text="Save Workspace",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            )
        )
        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_load_workspace_snapshot,
                text="Load Workspace",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )

        corner_layout.addWidget(
            self._make_menu_bar_action_button(
                action=self._action_pan_anchor,
                text="Pan Anchor",
                icon=self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight),
            )
        )

        # The view-mode label used to be the only menu-bar corner widget.
        # Now it lives inside the combined corner widget, after the quick
        # action buttons, so the UI keeps one top row instead of two.
        view_mode_label = QLabel(corner_widget)
        view_mode_label.setObjectName("historicalDataManagerViewModeLabel")
        view_mode_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        view_mode_label.setStyleSheet(
            self._view_mode_label_stylesheet(HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4)
        )
        self._view_mode_label = view_mode_label
        corner_layout.addWidget(view_mode_label)

        self._menu_bar_corner_widget = corner_widget
        menu_bar.setCornerWidget(corner_widget, Qt.TopRightCorner)

    def _make_menu_bar_action_button(
        self,
        *,
        action: Optional[QAction],
        text: str,
        icon,
    ) -> QToolButton:
        """Create one compact menu-bar button backed by an existing QAction.

        The important part is setDefaultAction(action):
        the button and the menu item trigger the same QAction, which means
        the same slot, same enabled state, same tooltip/status tip, and no
        duplicate save/load logic.
        """
        button = QToolButton(self)
        button.setObjectName(f"historicalDataManagerQuickActionButton_{text.replace(' ', '')}")
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setFixedHeight(24)

        if action is not None:
            button.setDefaultAction(action)

            # The QAction keeps the full File-menu label, while the button gets
            # a shorter label so it can fit inside the menu-bar row.
            button.setText(text)

            if not icon.isNull():
                button.setIcon(icon)

        return button

    def _view_mode_label_stylesheet(self, mode: str) -> str:
        """Return the compact high-contrast style for the view-mode badge.

        The label lives inside the menu-bar corner widget, so the style must
        improve readability without increasing the top-bar height into a second
        accidental toolbar. Mode truth stays in HistoricalWorkspaceWidget; this
        helper only maps the active mode to visual treatment.
        """
        base_style = (
            "QLabel#historicalDataManagerViewModeLabel { "
            "font-size: 13px; "
            "font-weight: bold; "
            "padding: 2px 8px; "
            "border-radius: 5px; "
            "border: 1px solid %s; "
            "background-color: %s; "
            "color: %s; "
            "}"
        )

        if mode == HistoricalWorkspaceWidget.VIEW_MODE_FIT_8:
            return base_style % (
                "rgb(120, 185, 120)",
                "rgb(215, 245, 215)",
                "rgb(190, 95, 0)",
            )

        return base_style % (
            "rgb(115, 170, 215)",
            "rgb(210, 235, 255)",
            "rgb(170, 20, 30)",
        )

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
        workspace_widget.chart_horizontal_pan_requested.connect(
            self._on_pan_anchor_panel_panned
        )

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

    def _on_pan_anchor_toggled(self, checked: bool) -> None:
        if checked:
            self._set_status("Pan Anchor enabled.")
        else:
            self._set_status("Pan Anchor disabled.")

    def _on_pan_anchor_panel_panned(self, panel_obj: object) -> None:
        action = self._action_pan_anchor
        if action is None or not action.isChecked():
            return

        if self._syncing_pan_anchor:
            return

        source_panel = panel_obj
        panels = self._active_historical_chart_panels()
        if not any(panel is source_panel for panel in panels):
            return

        center_timestamp = getattr(source_panel, "current_center_timestamp_ms", None)
        if not callable(center_timestamp):
            return

        ts_ms = center_timestamp()
        if not isinstance(ts_ms, int):
            return

        self._syncing_pan_anchor = True
        try:
            for panel in panels:
                if panel is source_panel:
                    continue
                recenter = getattr(panel, "center_on_timestamp_ms", None)
                if callable(recenter):
                    recenter(int(ts_ms))
        finally:
            self._syncing_pan_anchor = False

    def _active_historical_chart_panels(self) -> list[object]:
        workspace = self._workspace_widget
        if workspace is None:
            return []

        panels = getattr(workspace, "list_active_chart_panels", None)
        if callable(panels):
            return list(panels())

        return [panel for _position, panel in workspace.list_embedded_chart_panels()]

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
            self._view_mode_label.setStyleSheet(self._view_mode_label_stylesheet(mode))

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

    def _notebook_store_root(self) -> Path:
        return Path(self._ctx.config.runtime.data_dir) / "chart_presets" / "notebooks"

    def _notebook_store(self) -> HistoricalNotebookStore:
        return HistoricalNotebookStore(self._notebook_store_root())

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
                notebook_store=self._notebook_store(),
            )

        dialog = LoadWorkspaceSnapshotDialog(
            snapshots=snapshots,
            current_chart_count=workspace.chart_count(),
            available_slot_count=workspace.available_embedded_slot_count(),
            detached_reserved_slot_count=workspace.detached_reserved_slot_count(),
            compatibility_provider=compatibility_provider,
            delete_snapshot=self._workspace_snapshot_store().delete_snapshot,
            snapshots_loader=self._load_workspace_snapshot_objects,
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
        self._set_current_workspace_notebook_ref(snapshot.notebook_ref)
        notebook_notice = self._open_notebook_ref_from_snapshot(snapshot.notebook_ref)
        self._set_status(
            f"Loading workspace snapshot '{snapshot.display_name}' "
            f"({len(charts)} chart(s))"
        )
        message = (
            f"Workspace snapshot '{snapshot.display_name}' is loading. "
            "Studies and viewport state restore after each chart opens."
        )
        if notebook_notice:
            message += f"\n\n{notebook_notice}"
        QMessageBox.information(
            self,
            "Load Workspace Snapshot",
            message,
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
            delete_setup=self._chart_study_setup_store().delete_setup,
            setups_loader=self._load_study_setup_objects,
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

    def _ensure_notebook_window(self) -> HistoricalNotebookWindow:
        if self._notebook_window is None:
            notebook_window = HistoricalNotebookWindow(parent=self)
            notebook_window.refresh_requested.connect(self._refresh_notebook_from_workspace)
            notebook_window.save_requested.connect(self._on_save_notebook)
            notebook_window.load_requested.connect(self._on_load_notebook)
            notebook_window.assign_requested.connect(self._on_open_notebook_manager)
            notebook_window.goto_requested.connect(self._on_notebook_goto_requested)
            notebook_window.close_save_requested.connect(
                self._on_notebook_close_save_requested
            )
            notebook_window.poi_markers_changed.connect(
                self._on_notebook_poi_markers_changed
            )
            notebook_window.poi_overlay_requested.connect(
                self._on_notebook_poi_overlay_requested
            )
            notebook_window.destroyed.connect(self._on_notebook_window_destroyed)
            self._notebook_window = notebook_window
        return self._notebook_window

    def _on_create_notebook(self) -> None:
        """Open the historical notebook editor and bind current workspace charts."""
        notebook_window = self._ensure_notebook_window()

        self._refresh_notebook_from_workspace()
        notebook_window.show()
        notebook_window.raise_()
        notebook_window.activateWindow()
        self._set_status("Notebook window opened")

    def _on_open_notebook_manager(self) -> None:
        dialog = HistoricalNotebookManagerDialog(
            notebook_store=self._notebook_store(),
            workspace_snapshot_store=self._workspace_snapshot_store(),
            parent=self,
        )
        dialog.notebook_deleted.connect(self._on_notebook_deleted)
        if dialog.exec() != QDialog.Accepted:
            self._set_status("Notebook manager closed")
            return

        notebook_id = dialog.selected_open_notebook_id()
        if notebook_id:
            self._open_notebook_by_id(notebook_id, title="Notebook Manager")

    def _on_notebook_deleted(self, notebook_id: str) -> None:
        deleted_id = str(notebook_id or "").strip()
        if not deleted_id:
            return

        notebook_ref = self._current_workspace_notebook_ref
        if isinstance(notebook_ref, Mapping):
            current_ref_id = str(notebook_ref.get("notebook_id", "") or "").strip()
            if current_ref_id == deleted_id:
                self._set_current_workspace_notebook_ref(None)

        notebook_window = self._notebook_window
        if notebook_window is None or notebook_window.notebook_id() != deleted_id:
            return

        self._clear_notebook_poi_markers()
        notebook_window.reset_notebook(
            status="Deleted notebook was removed from the editor.",
            suppress_next_close_autosave=True,
        )
        notebook_window.close()
        self._set_status("Deleted open notebook; notebook editor was reset")

    def _refresh_notebook_from_workspace(self) -> None:
        """Refresh the notebook editor from the current embedded chart list."""
        if self._notebook_window is None:
            return
        self._notebook_window.refresh_from_chart_options(self._chart_options())
        self._apply_notebook_poi_markers()

    def _set_current_workspace_notebook_ref(
        self,
        notebook_ref: Mapping[str, Any] | None,
    ) -> None:
        if isinstance(notebook_ref, Mapping):
            resolved = dict(notebook_ref)
            notebook_id = str(resolved.get("notebook_id", "") or "").strip()
            self._current_workspace_notebook_ref = resolved if notebook_id else None
        else:
            self._current_workspace_notebook_ref = None
        self._sync_open_assigned_notebook_action()

    def _sync_open_assigned_notebook_action(self) -> None:
        action = self._action_open_assigned_notebook
        if action is None:
            return

        notebook_ref = self._current_workspace_notebook_ref
        notebook_id = ""
        if isinstance(notebook_ref, Mapping):
            notebook_id = str(notebook_ref.get("notebook_id", "") or "").strip()

        enabled = bool(notebook_id)
        action.setEnabled(enabled)
        if enabled:
            action.setToolTip("Open the notebook assigned to the current workspace snapshot.")
            action.setStatusTip("Open the notebook assigned to the current workspace snapshot.")
        else:
            action.setToolTip("No notebook assigned to the current workspace snapshot.")
            action.setStatusTip("No notebook assigned to the current workspace snapshot.")

    def _on_open_assigned_notebook(self) -> None:
        notebook_ref = self._current_workspace_notebook_ref
        if not isinstance(notebook_ref, Mapping) or not str(notebook_ref.get("notebook_id", "") or "").strip():
            self._sync_open_assigned_notebook_action()
            QMessageBox.information(
                self,
                "Open Notebook",
                "No notebook is assigned to the current workspace snapshot.",
            )
            return

        notice = self._open_notebook_ref_from_snapshot(notebook_ref)
        if not notice:
            self._set_current_workspace_notebook_ref(None)
            QMessageBox.warning(
                self,
                "Open Notebook",
                "The assigned notebook reference is invalid.",
            )
            return

        if notice.startswith("Assigned notebook could not be loaded"):
            QMessageBox.warning(self, "Open Notebook", notice)
            return

        self._set_status(notice)

    def _on_notebook_window_destroyed(self, *_args: Any) -> None:
        """Forget the notebook window reference after Qt destroys the window."""
        self._clear_notebook_poi_markers()
        self._notebook_window = None

    def _on_save_notebook(
        self,
        _checked: bool = False,
        *,
        show_success_message: bool = True,
    ) -> bool:
        notebook_window = self._ensure_notebook_window()
        previous_marker_id = notebook_window.notebook_id() or "__unsaved_notebook__"
        self._refresh_notebook_from_workspace()
        store = self._notebook_store()

        try:
            if notebook_window.notebook_id():
                notebook = notebook_window.current_notebook()
                saved = store.save_notebook(notebook, overwrite=True)
            else:
                saved = store.save_notebook(
                    store.create_notebook(
                        display_name=notebook_window.display_name(),
                        description=notebook_window.description(),
                        annotation_settings=notebook_window.annotation_settings_payload(),
                        chart_entries=notebook_window.chart_entries_payload(),
                    )
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Save Notebook",
                f"Could not save notebook: {exc!r}",
            )
            return False

        notebook_window.mark_saved(saved)
        if previous_marker_id != saved.notebook_id:
            self._clear_notebook_poi_markers(previous_marker_id)
        self._apply_notebook_poi_markers()
        self._set_status(f"Saved notebook: {saved.display_name}")
        if show_success_message:
            QMessageBox.information(
                self,
                "Save Notebook",
                f"Saved notebook '{saved.display_name}'.",
            )
        return True

    def _on_notebook_close_save_requested(self, event: object) -> None:
        if self._on_save_notebook(show_success_message=False):
            accept = getattr(event, "accept", None)
            if callable(accept):
                accept()
            return

        ignore = getattr(event, "ignore", None)
        if callable(ignore):
            ignore()

    def _on_load_notebook(self) -> None:
        store = self._notebook_store()
        summaries = store.list_summaries()
        if not summaries:
            QMessageBox.information(
                self,
                "Load Notebook",
                "No saved historical notebooks were found.",
            )
            return

        labels = [
            f"{summary.display_name} ({summary.chart_count} chart tab(s))"
            for summary in summaries
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "Load Notebook",
            "Notebook:",
            labels,
            0,
            False,
        )
        if not accepted:
            self._set_status("Notebook load cancelled")
            return

        index = labels.index(selected)
        self._open_notebook_by_id(summaries[index].notebook_id, title="Load Notebook")

    def _open_notebook_by_id(
        self,
        notebook_id: str,
        *,
        title: str,
        assigned_snapshot_label: str | None = None,
    ) -> bool:
        try:
            notebook = self._notebook_store().load_notebook(notebook_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                title,
                f"Could not load notebook: {exc!r}",
            )
            return False

        notebook_window = self._ensure_notebook_window()
        notebook_window.set_notebook(
            notebook,
            assigned_snapshot_label=assigned_snapshot_label,
        )
        self._refresh_notebook_from_workspace()
        notebook_window.show()
        notebook_window.raise_()
        notebook_window.activateWindow()
        self._set_status(f"Loaded notebook: {notebook.display_name}")
        return True

    def _on_notebook_goto_requested(self, chart_key: str, ts_ms: int) -> None:
        self._set_status(f"Notebook Go To requested for {chart_key} at {int(ts_ms)}")
        panel = self._panel_for_notebook_chart_key(chart_key)
        if panel is None:
            self._set_status(f"Notebook Go To failed: chart not active for {chart_key}")
            QMessageBox.information(
                self,
                "Notebook Go To",
                "The notebook chart is not currently active in this workspace.",
            )
            return

        navigate = getattr(panel, "center_on_notebook_timestamp", None)
        if not callable(navigate) or not navigate(int(ts_ms)):
            self._set_status(
                f"Notebook Go To failed: chart timeline is not ready for {chart_key}"
            )
            QMessageBox.warning(
                self,
                "Notebook Go To",
                "Could not center the chart on the requested notebook date.",
            )
            return

        self._set_status(f"Notebook Go To centered {chart_key} at {int(ts_ms)}")

    def _on_notebook_poi_markers_changed(self) -> None:
        if self._applying_notebook_poi_markers:
            return
        self._apply_notebook_poi_markers()

    def _on_notebook_poi_overlay_requested(self, _checked: bool) -> None:
        if self._applying_notebook_poi_markers:
            return
        self._apply_notebook_poi_markers()

    def _panel_for_notebook_chart_key(self, chart_key: str):
        workspace = self._workspace_widget
        if workspace is None:
            return None
        target_key = str(chart_key or "").strip().lower()
        for _position, panel in workspace.list_embedded_chart_panels():
            dataset = panel.dataset_descriptor()
            if notebook_chart_key(dataset) == target_key:
                return panel
        return None

    def _apply_notebook_poi_markers(self) -> None:
        if self._applying_notebook_poi_markers:
            return

        notebook_window = self._notebook_window
        workspace = self._workspace_widget
        if workspace is None or notebook_window is None:
            return

        self._applying_notebook_poi_markers = True
        try:
            notebook_id = notebook_window.notebook_id() or "__unsaved_notebook__"
            poi_markers_by_key = notebook_window.poi_markers_by_chart_key()
            pt_markers_by_key = notebook_window.pt_markers_by_chart_key()
            marker_offsets = notebook_window.annotation_marker_offsets()
            poi_marker_offset = int(
                marker_offsets.get(
                    "poi_marker_offset",
                    DEFAULT_POI_MARKER_OFFSET,
                )
            )
            enabled = notebook_window.poi_markers_enabled()
            for _position, panel in workspace.list_embedded_chart_panels():
                chart_key = notebook_chart_key(panel.dataset_descriptor())
                if not enabled:
                    panel.clear_notebook_poi_markers(notebook_id)
                    clear_pt_markers = getattr(panel, "clear_notebook_pt_markers", None)
                    if callable(clear_pt_markers):
                        clear_pt_markers(notebook_id)
                    continue
                panel.set_notebook_poi_markers(
                    notebook_id,
                    poi_markers_by_key.get(chart_key, []),
                    marker_offset_px=poi_marker_offset,
                )
                set_pt_markers = getattr(panel, "set_notebook_pt_markers", None)
                if callable(set_pt_markers):
                    set_pt_markers(
                        notebook_id,
                        pt_markers_by_key.get(chart_key, []),
                    )
        finally:
            self._applying_notebook_poi_markers = False

    def _clear_notebook_poi_markers(self, notebook_id: str | None = None) -> None:
        workspace = self._workspace_widget
        if workspace is None:
            return
        for _position, panel in workspace.list_embedded_chart_panels():
            clear_markers = getattr(panel, "clear_notebook_poi_markers", None)
            if callable(clear_markers):
                clear_markers(notebook_id)
            clear_pt_markers = getattr(panel, "clear_notebook_pt_markers", None)
            if callable(clear_pt_markers):
                clear_pt_markers(notebook_id)

    def _open_notebook_ref_from_snapshot(
        self,
        notebook_ref: Mapping[str, Any] | None,
    ) -> str:
        if not isinstance(notebook_ref, Mapping):
            return ""

        notebook_id = str(notebook_ref.get("notebook_id", "") or "").strip()
        if not notebook_id:
            return ""

        try:
            notebook = self._notebook_store().load_notebook(notebook_id)
        except Exception as exc:
            return f"Assigned notebook could not be loaded: {exc!r}"

        notebook_window = self._ensure_notebook_window()
        notebook_window.set_notebook(
            notebook,
            assigned_snapshot_label=str(notebook_ref.get("display_name", "") or ""),
        )
        self._refresh_notebook_from_workspace()
        notebook_window.show()
        notebook_window.raise_()
        notebook_window.activateWindow()
        return f"Assigned notebook '{notebook.display_name}' was opened."

    def _set_status(self, message: str) -> None:
        if self._status_bar is not None:
            self._status_bar.showMessage(message)

    def _show_placeholder_message(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)
