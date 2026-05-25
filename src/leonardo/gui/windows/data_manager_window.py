from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from leonardo.core.context import AppContext
from leonardo.data.naming import MarketId
from leonardo.gui.core_bridge import CoreBridge
from leonardo.gui.windows._data_manager.analysis_database_builder_widget import AnalysisDatabaseBuilderWidget
from leonardo.gui.windows._data_manager.analysis_database_build_dialog import AnalysisDatabaseBuildDialog
from leonardo.gui.windows._data_manager.analysis_database_component_dialog import AnalysisDatabaseComponentDialog
from leonardo.gui.windows._data_manager.analysis_database_list_widget import AnalysisDatabaseListWidget
from leonardo.gui.windows._data_manager.dataframe_preview_widget import DataFramePreviewWidget
from leonardo.gui.windows._data_manager.dataset_selector_widget import DatasetSelectorWidget
from leonardo.gui.windows._data_manager.metadata_tools_widget import MetadataToolsWidget
from leonardo.gui.windows._data_manager.saved_artifact_selector_widget import SavedArtifactSelectorWidget
from leonardo.gui.windows._data_manager.tool_calculation_widget import ToolCalculationWidget


class DataManagerWindow(QMainWindow):
    """Top-level window for analysis-database preparation workflows.

    This window is dataset/artifact oriented. It must not create chart-local
    studies, own pane/render state, or apply financial tools to charts.
    """

    def __init__(
        self,
        *,
        ctx: AppContext,
        core_bridge: CoreBridge,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self._ctx = ctx
        self._core = core_bridge
        self._historical_root = self._resolve_historical_root(ctx)
        self._selected_market: Optional[MarketId] = None

        self.setObjectName("data_manager_window")
        self.setWindowTitle("Leonardo - Data Manager")
        self.resize(1280, 820)
        self._apply_data_manager_style()

        self.setStatusBar(QStatusBar(self))
        self.setCentralWidget(self._build_central_widget())
        self.statusBar().showMessage("Data Manager ready")

    def _resolve_historical_root(self, ctx: AppContext) -> Path:
        data_dir = getattr(getattr(ctx, "config", None), "runtime", None)
        root = getattr(data_dir, "data_dir", "data")
        return Path(root) / "historical"

    def _apply_data_manager_style(self) -> None:
        font = self.font()
        point_size = font.pointSize()
        target_point_size: Optional[int] = None
        if point_size > 0:
            target_point_size = point_size + 2
            font.setPointSize(target_point_size)
            self.setFont(font)

        font_size_rule = ""
        if target_point_size is not None:
            font_size_rule = f"#data_manager_window QWidget {{ font-size: {target_point_size}pt; }}"

        self.setStyleSheet(
            font_size_rule
            + """
            #data_manager_window QGroupBox {
                font-weight: 700;
            }
            #data_manager_window QGroupBox::title {
                font-weight: 700;
            }
            #data_manager_window QGroupBox QLabel,
            #data_manager_window QGroupBox QPushButton,
            #data_manager_window QGroupBox QComboBox,
            #data_manager_window QGroupBox QLineEdit,
            #data_manager_window QGroupBox QTextEdit,
            #data_manager_window QGroupBox QPlainTextEdit,
            #data_manager_window QGroupBox QListWidget,
            #data_manager_window QGroupBox QTableView,
            #data_manager_window QGroupBox QCheckBox {
                font-weight: 400;
            }
            """
        )

    def _build_central_widget(self) -> QWidget:
        root_widget = QWidget(self)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._dataset_selector = DatasetSelectorWidget(
            historical_root=self._historical_root,
            core_bridge=self._core,
            parent=root_widget,
        )
        self._artifact_selector = SavedArtifactSelectorWidget(
            historical_root=self._historical_root,
            parent=root_widget,
        )
        self._metadata_tools = MetadataToolsWidget(
            historical_root=self._historical_root,
            parent=root_widget,
        )
        self._tool_calculation = ToolCalculationWidget(
            historical_root=self._historical_root,
            parent=root_widget,
        )
        self._analysis_builder = AnalysisDatabaseBuilderWidget(
            historical_root=self._historical_root,
            parent=root_widget,
        )
        self._database_list = AnalysisDatabaseListWidget(
            historical_root=self._historical_root,
            parent=root_widget,
        )
        self._preview = DataFramePreviewWidget(parent=root_widget)

        self._dataset_selector.dataset_changed.connect(self._on_dataset_changed)
        self._dataset_selector.preview_ohlcv_requested.connect(self._preview_current_ohlcv)
        self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)
        self._artifact_selector.preview_requested.connect(self._preview.load_csv_path)
        self._analysis_builder.draft_saved.connect(self._on_analysis_draft_saved)
        self._analysis_builder.status_message.connect(self.statusBar().showMessage)
        self._metadata_tools.status_message.connect(self.statusBar().showMessage)
        self._tool_calculation.artifact_saved.connect(self._on_tool_artifact_saved)
        self._tool_calculation.database_rebuilt.connect(self._on_recovery_database_rebuilt)
        self._tool_calculation.update_execution_finished.connect(self._on_update_execution_finished)
        self._tool_calculation.preview_requested.connect(self._preview.load_csv_path)
        self._tool_calculation.status_message.connect(self.statusBar().showMessage)
        self._database_list.database_materialized.connect(self._on_analysis_database_materialized)
        self._database_list.build_requested.connect(self._on_database_build_requested)
        self._database_list.component_edit_requested.connect(self._on_database_component_edit_requested)
        self._database_list.preview_requested.connect(self._preview.load_csv_path)
        self._database_list.status_message.connect(self.statusBar().showMessage)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        root.addLayout(top_row, 1)

        top_row.addWidget(self._dataset_selector, 1)
        top_row.addWidget(self._tool_calculation, 1)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(12)
        root.addLayout(middle_row, 4)
        middle_row.addWidget(self._preview, 1)
        middle_row.addWidget(self._artifact_selector, 1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        root.addLayout(bottom_row, 7)

        lower_left_col = QVBoxLayout()
        lower_left_col.setSpacing(12)
        bottom_row.addLayout(lower_left_col, 1)
        lower_left_col.addWidget(self._metadata_tools, 1)
        lower_left_col.addWidget(self._analysis_builder, 1)

        bottom_row.addWidget(self._database_list, 2)

        self._on_dataset_changed(self._dataset_selector.current_market())
        return root_widget

    def _on_dataset_changed(self, market: object) -> None:
        selected_market = market if isinstance(market, MarketId) else None
        loadability = self._dataset_selector.current_loadability()
        workflow_market = (
            selected_market
            if selected_market is not None
            and loadability is not None
            and self._loadability_is_loadable(loadability)
            else None
        )
        self._selected_market = selected_market
        self._apply_dataset_selection_state(workflow_market=workflow_market)
        if selected_market is None:
            self._preview.clear()
            self.statusBar().showMessage("No dataset selected")
            return
        if workflow_market is None:
            self._preview.clear()
            reason = self._loadability_reason(loadability)
            self.statusBar().showMessage(
                reason or "Selected OHLCV dataset is available for read-only preview only"
            )
            return

        self.statusBar().showMessage("Dataset selected for Data Manager")

    def _apply_dataset_selection_state(self, *, workflow_market: Optional[MarketId]) -> None:
        workflow_enabled = workflow_market is not None
        self._artifact_selector.set_build_selection_mode(False)
        self._artifact_selector.set_market(workflow_market)
        self._metadata_tools.set_market(workflow_market)
        self._tool_calculation.set_market(workflow_market)
        self._analysis_builder.set_market(workflow_market)
        self._database_list.set_market(workflow_market)

        self._artifact_selector.setEnabled(workflow_enabled)
        self._metadata_tools.setEnabled(workflow_enabled)
        self._tool_calculation.setEnabled(workflow_enabled)
        self._analysis_builder.setEnabled(workflow_enabled)
        self._database_list.setEnabled(workflow_enabled)

    def _on_database_build_requested(self, manifest: object) -> None:
        if not hasattr(manifest, "database_id"):
            self.statusBar().showMessage("Select an analysis database before building")
            return

        dialog = AnalysisDatabaseBuildDialog(
            historical_root=self._historical_root,
            manifest=manifest,
            parent=self,
        )
        dialog.database_materialized.connect(self._on_build_dialog_database_materialized)
        dialog.status_message.connect(self.statusBar().showMessage)
        dialog.exec()

    def _on_build_dialog_database_materialized(self, manifest: object) -> None:
        self._database_list.refresh()
        display_name = getattr(manifest, "display_name", "analysis database")
        self.statusBar().showMessage(f"Analysis database built: {display_name}")

    def _on_database_component_edit_requested(self, manifest: object) -> None:
        if not hasattr(manifest, "database_id"):
            self.statusBar().showMessage("Select an analysis database before editing components")
            return

        dialog = AnalysisDatabaseComponentDialog(
            historical_root=self._historical_root,
            manifest=manifest,
            parent=self,
        )
        dialog.components_changed.connect(self._on_analysis_database_components_changed)
        dialog.status_message.connect(self.statusBar().showMessage)
        dialog.exec()

    def _on_analysis_database_components_changed(self, report: object) -> None:
        self._database_list.refresh()
        manifest = getattr(report, "manifest", None)
        display_name = getattr(manifest, "display_name", "analysis database")
        self.statusBar().showMessage(f"Analysis database components updated: {display_name}")

    def _preview_current_ohlcv(self) -> None:
        market = self._selected_market
        if market is None:
            self.statusBar().showMessage("No dataset selected")
            return

        loadability = self._dataset_selector.current_loadability()
        if loadability is None:
            try:
                loadability = self._dataset_loadability(market)
            except Exception as exc:
                self._preview.clear()
                self.statusBar().showMessage(f"Could not verify selected OHLCV dataset: {exc!r}")
                return

        ohlcv_path = self._loadability_csv_path(loadability)
        if ohlcv_path is None:
            self._preview.clear()
            self.statusBar().showMessage("Selected OHLCV dataset cannot be previewed from the catalog")
            return
        title = f"OHLCV - {market.exchange} / {market.market_type} / {market.symbol} / {market.timeframe}"
        self._preview.load_csv_path(ohlcv_path, title)
        if self._loadability_is_loadable(loadability):
            self.statusBar().showMessage("Previewing OHLCV candles")
        else:
            self.statusBar().showMessage("Previewing non-loadable OHLCV candles in read-only mode")

    def _dataset_loadability(self, market: MarketId) -> object:
        return self._core.historical_dataset_loadability(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
        )

    @staticmethod
    def _loadability_is_loadable(loadability: object) -> bool:
        if isinstance(loadability, Mapping):
            return bool(loadability.get("loadable"))
        return bool(getattr(loadability, "loadable", False))

    @staticmethod
    def _loadability_reason(loadability: object) -> str:
        if isinstance(loadability, Mapping):
            value = loadability.get("reason")
        else:
            value = getattr(loadability, "reason", "")
        return str(value or "").strip()

    @staticmethod
    def _loadability_csv_path(loadability: object) -> Optional[Path]:
        if isinstance(loadability, Mapping):
            value = loadability.get("csv_path")
        else:
            value = getattr(loadability, "csv_path", "")
        text = str(value or "").strip()
        return Path(text) if text else None

    def _on_analysis_draft_saved(self, manifest: object) -> None:
        self._database_list.refresh()
        display_name = getattr(manifest, "display_name", "analysis database")
        self.statusBar().showMessage(f"Draft analysis database saved: {display_name}")

    def _on_tool_artifact_saved(self, result: object) -> None:
        self._artifact_selector.refresh()
        tool_type = getattr(result, "tool_type", "artifact")
        instance_key = getattr(result, "instance_key", "")
        label = f"{tool_type} artifact"
        if instance_key:
            label = f"{label}: {instance_key}"
        self.statusBar().showMessage(f"Saved {label}")

    def _on_analysis_database_materialized(self, manifest: object) -> None:
        display_name = getattr(manifest, "display_name", "analysis database")
        self.statusBar().showMessage(f"Analysis database materialized: {display_name}")

    def _on_recovery_database_rebuilt(self, report: object) -> None:
        self._database_list.refresh()
        manifest = getattr(report, "manifest", None)
        display_name = getattr(manifest, "display_name", "linked analysis database")
        self.statusBar().showMessage(f"Linked analysis database rebuilt: {display_name}")

    def _on_update_execution_finished(self, report: object) -> None:
        self._artifact_selector.refresh()
        self._database_list.refresh()
        completed = getattr(report, "completed_action_ids", ())
        self.statusBar().showMessage(
            f"Data Manager update completed {len(tuple(completed))} action(s)"
        )
