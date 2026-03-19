from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
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
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows.historical_workspace_widget import HistoricalWorkspaceWidget


class HistoricalChartSelectionDialog(QDialog):
    """
    Dialog used to select a historical dataset path in a guided order:

    Exchange -> Market Type -> Asset -> Timeframe

    Data source:
    <project_root>/data/historical
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

        self._historical_root = Path(__file__).resolve().parents[4] / "data" / "historical"

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

        if not self._historical_root.exists() or not self._historical_root.is_dir():
            self._set_info_text("Historical root folder not found.")
            return

        exchange_folders = self._list_child_directories(self._historical_root)
        for folder_name in exchange_folders:
            display_name = self._capitalize_first_letter(folder_name)
            self._exchange_combo.addItem(display_name, folder_name)

        self._set_info_text("Select an exchange to continue.")

    def _populate_market_types(self, exchange_name: str) -> None:
        if self._market_type_combo is None:
            return

        exchange_path = self._historical_root / exchange_name
        self._reset_combo(self._market_type_combo, placeholder="")
        self._reset_combo(self._asset_combo, placeholder="")
        self._reset_combo(self._timeframe_combo, placeholder="")

        market_type_folders = self._list_child_directories(exchange_path)
        for folder_name in market_type_folders:
            self._market_type_combo.addItem(folder_name, folder_name)

        self._market_type_combo.setEnabled(self._market_type_combo.count() > 1)
        if self._asset_combo is not None:
            self._asset_combo.setEnabled(False)
        if self._timeframe_combo is not None:
            self._timeframe_combo.setEnabled(False)

        self._update_load_button_state()
        self._set_info_text("Select a market type.")

    def _populate_assets(self, exchange_name: str, market_type_name: str) -> None:
        if self._asset_combo is None:
            return

        asset_root = self._historical_root / exchange_name / market_type_name
        self._reset_combo(self._asset_combo, placeholder="")
        self._reset_combo(self._timeframe_combo, placeholder="")

        asset_folders = self._list_valid_asset_directories(asset_root)
        for folder_name in asset_folders:
            self._asset_combo.addItem(folder_name, folder_name)

        self._asset_combo.setEnabled(self._asset_combo.count() > 1)
        if self._timeframe_combo is not None:
            self._timeframe_combo.setEnabled(False)

        self._update_load_button_state()
        self._set_info_text("Select an asset.")

    def _populate_timeframes(
        self,
        exchange_name: str,
        market_type_name: str,
        asset_name: str,
    ) -> None:
        if self._timeframe_combo is None:
            return

        asset_path = self._historical_root / exchange_name / market_type_name / asset_name
        self._reset_combo(self._timeframe_combo, placeholder="")

        timeframe_folders = self._list_valid_timeframe_directories(asset_path)
        for folder_name in timeframe_folders:
            self._timeframe_combo.addItem(folder_name, folder_name)

        self._timeframe_combo.setEnabled(self._timeframe_combo.count() > 1)
        self._update_load_button_state()
        self._set_info_text("Select a timeframe.")

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
        candles_file = self._find_candles_file()

        if candles_file is None:
            QMessageBox.warning(
                self,
                "Load Data",
                "candles file not found",
            )
            return

        self._selected_exchange = self._current_data(self._exchange_combo)
        self._selected_market_type = self._current_data(self._market_type_combo)
        self._selected_asset = self._current_data(self._asset_combo)
        self._selected_timeframe = self._current_data(self._timeframe_combo)

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

    def _find_candles_file(self) -> Optional[Path]:
        selection_path = self._selected_timeframe_path()
        if selection_path is None:
            return None

        ohlcv_path = selection_path / "ohlcv"
        if not ohlcv_path.exists() or not ohlcv_path.is_dir():
            return None

        for child in sorted(ohlcv_path.iterdir(), key=lambda item: item.name.lower()):
            if child.is_file() and child.stem.lower() == "candles":
                return child

        for child in sorted(ohlcv_path.iterdir(), key=lambda item: item.name.lower()):
            if child.is_file() and child.name.lower().startswith("candles"):
                return child

        return None

    def _selected_timeframe_path(self) -> Optional[Path]:
        exchange_name = self._current_data(self._exchange_combo)
        market_type_name = self._current_data(self._market_type_combo)
        asset_name = self._current_data(self._asset_combo)
        timeframe_name = self._current_data(self._timeframe_combo)

        if not exchange_name or not market_type_name or not asset_name or not timeframe_name:
            return None

        return (
            self._historical_root
            / exchange_name
            / market_type_name
            / asset_name
            / timeframe_name
        )

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

    def _list_valid_asset_directories(self, path: Path) -> list[str]:
        if not path.exists() or not path.is_dir():
            return []

        valid_assets: list[str] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            if self._list_valid_timeframe_directories(child):
                valid_assets.append(child.name)

        return valid_assets

    def _list_valid_timeframe_directories(self, path: Path) -> list[str]:
        if not path.exists() or not path.is_dir():
            return []

        valid_timeframes: list[str] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            if (child / "ohlcv").is_dir():
                valid_timeframes.append(child.name)

        return valid_timeframes

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

    @staticmethod
    def _list_child_directories(path: Path) -> list[str]:
        if not path.exists() or not path.is_dir():
            return []

        return sorted(
            [child.name for child in path.iterdir() if child.is_dir()],
            key=str.lower,
        )


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

        self._action_new_chart: Optional[QAction] = None
        self._action_close: Optional[QAction] = None
        self._action_placeholder_tile: Optional[QAction] = None
        self._action_placeholder_open_chart: Optional[QAction] = None
        self._action_placeholder_open_dataset: Optional[QAction] = None
        self._action_placeholder_refresh: Optional[QAction] = None

        self._workspace_widget: Optional[HistoricalWorkspaceWidget] = None

        self._build_ui()

    def workspace_widget(self) -> Optional[HistoricalWorkspaceWidget]:
        return self._workspace_widget

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

        action_open_chart = QAction("Open Historical Chart", self)
        action_open_chart.triggered.connect(self._on_open_chart_placeholder)
        self._action_placeholder_open_chart = action_open_chart
        menu_historical.addAction(action_open_chart)

        action_refresh = QAction("Refresh", self)
        action_refresh.triggered.connect(self._on_refresh_placeholder)
        self._action_placeholder_refresh = action_refresh
        menu_historical.addAction(action_refresh)

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        status_bar.setSizeGripEnabled(False)
        status_bar.showMessage("Historical Data Manager ready")
        self.setStatusBar(status_bar)
        self._status_bar = status_bar

    def _build_central_widget(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Historical Data Manager", root)
        title.setAlignment(Qt.AlignCenter)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title.setStyleSheet(
            """
            QLabel {
                font-size: 20px;
                font-weight: 600;
                padding: 8px;
            }
            """
        )

        subtitle = QLabel(
            "This window manages embedded historical chart sessions.\n"
            "Use File → New Chart to load up to 4 historical charts inside the workspace.",
            root,
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            """
            QLabel {
                font-size: 13px;
                color: #C8C8C8;
                padding: 8px;
            }
            """
        )

        workspace_widget = HistoricalWorkspaceWidget(
            core_bridge=self._core,
            window_manager=self._window_manager,
            parent=root,
        )
        self._workspace_widget = workspace_widget

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(workspace_widget, 1)

        self.setCentralWidget(root)

    def _on_new_chart(self) -> None:
        if self._workspace_widget is None:
            self._set_status("Historical workspace not ready")
            return

        if not self._workspace_widget.can_add_chart():
            self._workspace_widget.warn_max_charts()
            self._set_status("Maximum of 4 historical charts reached")
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
            self._set_status("Maximum of 4 historical charts reached")
            return

        exchange_display = exchange[:1].upper() + exchange[1:] if exchange else exchange
        self._set_status(
            f"Embedded chart loaded: {exchange_display}_{market_type}_{symbol}_{timeframe}"
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
