from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QGridLayout, QPushButton, QSizePolicy

from leonardo.gui.windows._data_manager.analysis_database_builder_widget import AnalysisDatabaseBuilderWidget
from leonardo.gui.windows._data_manager.dataframe_preview_widget import DataFramePreviewWidget
from leonardo.gui.windows._data_manager.dataset_selector_widget import (
    DatasetSelectorWidget,
    _dataset_label,
    _options_from_loadability_reports,
)
from leonardo.gui.windows._data_manager.metadata_tools_widget import MetadataToolsWidget
from leonardo.gui.windows.data_manager_window import DataManagerWindow


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo"
DATA_MANAGER = SRC / "gui" / "windows" / "_data_manager"
WINDOWS = SRC / "gui" / "windows"
CORE_BRIDGE = SRC / "gui" / "core_bridge.py"

_QAPP: QApplication | None = None


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _loadability_report(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str,
    loadable: bool,
    validation_status: str,
    csv_path: str = "",
    reason: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        dataset_id=SimpleNamespace(
            exchange="bybit",
            market_type="linear",
            symbol=symbol,
            timeframe=timeframe,
        ),
        loadable=loadable,
        validation_status=validation_status,
        reason=reason,
        csv_path=csv_path,
        metadata_path=f"{csv_path}.meta.json" if csv_path else "",
    )


class _FakeDatasetCore:
    def __init__(self, reports: list[SimpleNamespace]) -> None:
        self._reports = reports

    def list_historical_ohlcv_dataset_loadabilities(self) -> list[SimpleNamespace]:
        return list(self._reports)

    def historical_dataset_loadability(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> SimpleNamespace:
        for report in self._reports:
            dataset_id = report.dataset_id
            if (
                dataset_id.exchange == exchange
                and dataset_id.market_type == market_type
                and dataset_id.symbol == symbol
                and dataset_id.timeframe == timeframe
            ):
                return report
        raise KeyError((exchange, market_type, symbol, timeframe))


def test_dataset_selector_options_keep_all_core_reports_and_label_statuses() -> None:
    reports = [
        _loadability_report(timeframe="1m", loadable=True, validation_status="ok"),
        _loadability_report(symbol="ETHUSDT", timeframe="1m", loadable=True, validation_status="modified"),
        _loadability_report(symbol="XRPUSDT", timeframe="1m", loadable=False, validation_status="error"),
    ]

    options = _options_from_loadability_reports(reports)

    assert [option.market.symbol for option in options] == ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    assert [option.loadable for option in options] == [True, True, False]
    assert [_dataset_label(option) for option in options] == [
        "bybit / linear / BTCUSDT / 1m - OK",
        "bybit / linear / ETHUSDT / 1m - Modified",
        "bybit / linear / XRPUSDT / 1m - Error",
    ]


def test_dataset_selector_hierarchy_shows_all_timeframe_statuses_and_styles_invalid(tmp_path: Path) -> None:
    _qapp()
    reports = [
        _loadability_report(timeframe="1m", loadable=True, validation_status="ok"),
        _loadability_report(timeframe="5m", loadable=True, validation_status="modified"),
        _loadability_report(timeframe="15m", loadable=False, validation_status="warning"),
        _loadability_report(timeframe="1h", loadable=False, validation_status="error"),
        _loadability_report(timeframe="4h", loadable=False, validation_status="unknown"),
        _loadability_report(timeframe="1d", loadable=False, validation_status="not_validated"),
    ]
    widget = DatasetSelectorWidget(
        historical_root=tmp_path,
        core_bridge=_FakeDatasetCore(reports),  # type: ignore[arg-type]
    )

    exchange = widget.findChild(QComboBox, "dataset_exchange_combo")
    market_type = widget.findChild(QComboBox, "dataset_market_type_combo")
    symbol = widget.findChild(QComboBox, "dataset_symbol_combo")
    timeframe = widget.findChild(QComboBox, "dataset_timeframe_combo")
    assert exchange is not None
    assert market_type is not None
    assert symbol is not None
    assert timeframe is not None

    assert widget.current_market() is None
    exchange.setCurrentIndex(exchange.findText("bybit"))
    assert widget.current_market() is None
    market_type.setCurrentIndex(market_type.findText("linear"))
    assert widget.current_market() is None
    symbol.setCurrentIndex(symbol.findText("BTCUSDT"))
    assert widget.current_market() is None

    labels = [timeframe.itemText(index) for index in range(timeframe.count())]
    assert "1m - OK" in labels
    assert "5m - Modified" in labels
    assert "15m - Warning" in labels
    assert "1h - Error" in labels
    assert "4h - Unknown" in labels
    assert "1d - Not validated" in labels

    timeframe.setCurrentIndex(timeframe.findText("15m - Warning"))
    selected = widget.current_market()
    assert selected is not None
    assert selected.timeframe == "15m"
    assert widget.current_loadability().loadable is False  # type: ignore[union-attr]
    assert "color: #b00020" in timeframe.styleSheet()
    assert "font-weight: 700" in timeframe.styleSheet()

    preview_button = next(
        button
        for button in widget.findChildren(QPushButton)
        if button.text() == "Preview OHLCV"
    )
    assert preview_button.isEnabled()


def test_data_manager_dataset_selector_uses_core_all_status_catalog_not_raw_storage() -> None:
    path = DATA_MANAGER / "dataset_selector_widget.py"
    source = _source(path)

    assert "list_historical_ohlcv_dataset_loadabilities" in source
    assert "historical_dataset_loadability" in source
    assert "No OHLCV datasets available" in source
    assert "OHLCV / Timeframe" in source
    assert "DatasetSelectorOption" in source
    assert "currentData()" in source
    assert "root.glob" not in source
    assert "ohlcv/candles.csv" not in source
    assert "candles.meta" not in source
    assert "json.load" not in source
    assert "read_text" not in source
    assert "LOADABLE_OHLCV_VALIDATION_STATUSES" not in source


def test_data_manager_window_passes_core_bridge_to_selector_and_checks_preview_loadability() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)
    preview_source = _function_source(path, "_preview_current_ohlcv")

    assert "core_bridge=self._core" in source
    assert "historical_dataset_loadability" in source
    assert "_loadability_csv_path" in preview_source
    assert "Previewing non-loadable OHLCV candles in read-only mode" in preview_source
    assert "HistoricalPaths" not in source
    assert "CsvOHLCVStore" not in source


def test_data_manager_invalid_dataset_selection_enters_safe_mode_and_preview_remains_read_only(tmp_path: Path) -> None:
    _qapp()
    warning_csv = tmp_path / "warning.csv"
    reports = [
        _loadability_report(
            timeframe="1m",
            loadable=True,
            validation_status="ok",
            csv_path=str(tmp_path / "ok.csv"),
        ),
        _loadability_report(
            timeframe="15m",
            loadable=False,
            validation_status="warning",
            csv_path=str(warning_csv),
            reason="Warning OHLCV is not loadable.",
        ),
    ]
    ctx = SimpleNamespace(
        config=SimpleNamespace(runtime=SimpleNamespace(data_dir=str(tmp_path)))
    )
    window = DataManagerWindow(
        ctx=ctx,  # type: ignore[arg-type]
        core_bridge=_FakeDatasetCore(reports),  # type: ignore[arg-type]
    )

    selector = window._dataset_selector
    selector._exchange_combo.setCurrentIndex(selector._exchange_combo.findText("bybit"))
    selector._market_type_combo.setCurrentIndex(selector._market_type_combo.findText("linear"))
    selector._symbol_combo.setCurrentIndex(selector._symbol_combo.findText("BTCUSDT"))
    selector._timeframe_combo.setCurrentIndex(selector._timeframe_combo.findText("15m - Warning"))

    assert window._tool_calculation.isEnabled() is False
    assert window._analysis_builder.isEnabled() is False
    assert window._database_list.isEnabled() is False
    assert window._metadata_tools.isEnabled() is False
    assert window._artifact_selector.isEnabled() is False
    assert window._preview.isEnabled() is True

    captured: list[tuple[object, str]] = []
    window._preview.load_csv_path = lambda path, title="DataFrame": captured.append((path, title))  # type: ignore[method-assign]
    window._preview_current_ohlcv()

    assert captured == [(warning_csv, "OHLCV - bybit / linear / BTCUSDT / 15m")]
    assert "non-loadable OHLCV candles" in window.statusBar().currentMessage()

    selector._timeframe_combo.setCurrentIndex(selector._timeframe_combo.findText("1m - OK"))

    assert window._tool_calculation.isEnabled() is True
    assert window._analysis_builder.isEnabled() is True
    assert window._database_list.isEnabled() is True
    assert window._metadata_tools.isEnabled() is True
    assert window._artifact_selector.isEnabled() is True


def test_core_bridge_exposes_data_manager_ohlcv_loadability_catalog_boundary() -> None:
    source = _source(CORE_BRIDGE)

    assert "def list_historical_ohlcv_dataset_loadabilities" in source
    assert "list_dataset_loadabilities()" in source
    assert "def list_loadable_historical_ohlcv_datasets" in source
    assert "list_loadable_dataset_loadabilities()" in source
    assert "LOADABLE_OHLCV_VALIDATION_STATUSES" not in source


def test_analysis_database_feature_builder_helper_is_gui_owned_shared_mapper() -> None:
    """Saved artifact column -> manifest feature mapping is shared GUI helper code.

    The mapper consumes Data Manager ``SavedArtifactColumn`` objects, so it is
    intentionally GUI-owned. It may be reused by recipe-creation/component-edit
    UI, but Database Builder must still not consume it for rebuild.
    """
    helper_path = DATA_MANAGER / "analysis_database_feature_builder.py"
    helper_source = _source(helper_path)
    helper_function = _function_source(helper_path, "build_manifest_features_from_saved_columns")

    assert "SavedArtifactColumn" in helper_source
    assert "saved_artifact_columns import SavedArtifactColumn" in helper_source
    assert "AnalysisFeatureSource" in helper_source
    assert "AnalysisDatabaseColumn" in helper_source
    assert "build_feature_source_id" in helper_source
    assert "build_database_column_name" in helper_source
    assert "AnalysisDatabaseStore" not in helper_source
    assert "materialize_database" not in helper_source
    assert "rebuild_database_with_features" not in helper_source
    assert "selected_columns: Sequence[SavedArtifactColumn]" in helper_function


def test_database_seed_creator_imports_shared_feature_builder_helper() -> None:
    """Seed creation may use the shared mapper; it should not define it locally."""
    path = DATA_MANAGER / "analysis_database_builder_widget.py"
    source = _source(path)

    assert "analysis_database_feature_builder import" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "def build_manifest_features_from_saved_columns" not in source
    assert "def _build_feature_source" not in source
    assert "build_feature_source_id" not in source
    assert "build_database_column_name" not in source


def test_database_seed_creator_name_and_description_span_full_width(tmp_path: Path) -> None:
    _qapp()
    widget = AnalysisDatabaseBuilderWidget(historical_root=tmp_path)

    root = widget.layout()
    assert isinstance(root, QGridLayout)

    form_layout: QFormLayout | None = None
    form_position: tuple[int, int, int, int] | None = None
    for index in range(root.count()):
        item = root.itemAt(index)
        layout = item.layout() if item is not None else None
        if isinstance(layout, QFormLayout):
            form_layout = layout
            form_position = root.getItemPosition(index)
            break

    assert form_layout is not None
    assert form_position == (1, 0, 1, 2)
    assert form_layout.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapAllRows
    assert widget._name_edit.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert widget._description_edit.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert widget._description_edit.acceptRichText() is False
    assert widget._description_edit.minimumHeight() == 72
    assert widget._description_edit.maximumHeight() == 72


def test_database_builder_no_longer_consumes_saved_artifact_selection() -> None:
    """Database Builder must rebuild from its own manifest only.

    Creating a database recipe from checked artifact columns belongs to the
    Database seed creator. The database list/build widget must not keep the old
    two-phase artifact replacement flow alive, because rebuild means
    materialize the selected existing database by database_id.
    """
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    tree = _tree(path)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name.split(".")[0])

    assert "build_manifest_features_from_saved_columns" not in imported_names
    assert "SavedArtifactColumn" not in imported_names
    assert "set_selected_artifact_columns" not in source
    assert "Build / Rebuild Selected Database" not in source
    assert "artifact_selection_started" not in source
    assert "artifact_selection_finished" not in source
    assert "_artifact_selection_phase" not in source
    assert "rebuild_database_with_features" not in source


def test_database_builder_build_and_rebuild_buttons_use_existing_manifest_recipe() -> None:
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    build_source = _function_source(path, "_build_selected")
    rebuild_source = _function_source(path, "_rebuild_selected")
    materialize_source = _function_source(path, "_materialize_checked_manifest")

    assert "Build Selected Database" in source
    assert "Rebuild Selected Database" in source
    assert "Build / Rebuild Selected Database" not in source

    assert "_single_checked_manifest" in build_source
    assert "build_requested.emit(manifest)" in build_source
    assert "already materialized" in build_source
    assert "materialize_database" not in build_source

    assert "_single_checked_manifest" in rebuild_source
    assert "_materialize_checked_manifest" in rebuild_source
    assert "not materialized yet" in rebuild_source

    assert "materialize_database" in materialize_source
    assert "database_id=manifest.database_id" in materialize_source
    assert "build_draft_manifest" not in materialize_source
    assert "save_manifest" not in materialize_source
    assert "rebuild_database_with_features" not in materialize_source


def test_data_manager_wires_saved_artifacts_only_to_seed_creator() -> None:
    """Checked saved artifacts should feed draft creation, not database rebuild."""
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "self._artifact_selector.selection_changed.connect(self._analysis_builder.set_selected_columns)" in source
    assert "self._artifact_selector.selection_changed.connect(self._on_saved_artifact_selection_changed)" not in source
    assert "self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)" not in source
    assert "artifact_selection_started" not in source
    assert "artifact_selection_finished" not in source
    assert "_on_database_artifact_selection_started" not in source
    assert "_on_database_artifact_selection_finished" not in source
    assert "_on_artifact_selection_exit_requested" not in source


def test_saved_artifact_preview_uses_exactly_one_checked_artifact() -> None:
    path = DATA_MANAGER / "saved_artifact_selector_widget.py"
    source = _source(path)
    preview_source = _function_source(path, "_preview_selected_artifact")
    button_source = _function_source(path, "_refresh_preview_button")

    assert "Preview Selected Artifact" in source
    assert "_single_checked_column" in preview_source
    assert "_single_checked_column() is not None" in button_source
    assert "currentItem" not in preview_source
    assert "_current_column" not in source


def test_dataframe_preview_adds_readable_timestamps_without_mutating_source_csv() -> None:
    path = DATA_MANAGER / "dataframe_preview_widget.py"
    source = _source(path)
    prepare_source = _function_source(path, "_prepare_preview_dataframe")

    assert "ts_utc" in source
    assert "ts_rome" in source
    assert "out = dataframe.copy()" in prepare_source
    assert "out.insert" in prepare_source
    assert "drop(columns=[\"time\"])" in source


def test_dataframe_preview_header_layout_keeps_clear_button_under_summary(tmp_path: Path) -> None:
    _qapp()
    path = DATA_MANAGER / "dataframe_preview_widget.py"
    source = _source(path)

    assert "button_rack import make_button_rack" not in source
    assert "make_button_rack(self._clear_button)" not in source
    assert "root = QVBoxLayout(self)" in source
    assert "preview_header.addLayout(summary_area, 2)" in source
    assert "summary_area.addWidget(self._clear_button, 0, Qt.AlignLeft)" in source
    assert "timestamp_area.setSpacing(0)" in source
    assert "timestamp_area.addWidget(self._timestamp_title, 0, Qt.AlignLeft | Qt.AlignTop)" in source
    assert "preview_header.addLayout(timestamp_area, 3)" in source
    assert "timestamp_values_row.setContentsMargins(0, 0, 0, 0)" in source

    csv_path = tmp_path / "preview.csv"
    csv_path.write_text(
        "ts_ms,open\n"
        "1585132200000,1\n"
        "1585135800000,2\n",
        encoding="utf-8",
    )
    widget = DataFramePreviewWidget(max_rows=500)
    widget.load_csv_path(csv_path, "Preview Title")

    first_visible = widget._first_timestamp_summary.text()
    last_visible = widget._last_timestamp_summary.text()
    assert first_visible.startswith("First visible:")
    assert "ts_ms:" in first_visible
    assert "UTC:" in first_visible
    assert "Europe/Rome:" in first_visible
    assert last_visible.startswith("Last visible:")
    assert "ts_ms:" in last_visible
    assert "UTC:" in last_visible
    assert "Europe/Rome:" in last_visible
    assert "Showing first 2 row(s), 4 column(s). Preview limits: 500 row(s)." in widget._summary.text()

    widget.clear()

    assert widget._model.rowCount() == 0
    assert widget._first_timestamp_summary.text() == ""
    assert widget._last_timestamp_summary.text() == ""


def test_metadata_tools_report_spans_full_width_and_uses_larger_font(tmp_path: Path) -> None:
    _qapp()
    widget = MetadataToolsWidget(historical_root=tmp_path)

    layout = widget.layout()
    assert isinstance(layout, QGridLayout)
    report_index = layout.indexOf(widget._report)
    assert report_index >= 0
    assert layout.getItemPosition(report_index) == (1, 0, 1, 2)
    assert widget._report.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding

    base_point_size = widget.font().pointSize()
    report_point_size = widget._report.font().pointSize()
    if base_point_size > 0:
        assert report_point_size == base_point_size + 1
    else:
        assert widget._report.font().pointSizeF() > widget.font().pointSizeF()

    widget._report.setPlainText("Metadata restore report\nScanned CSVs: 1")

    assert widget._report.toPlainText() == "Metadata restore report\nScanned CSVs: 1"


def test_database_builder_component_edit_is_explicit_intent_only() -> None:
    """Database Builder may expose component-edit intent, but rebuild must stay manifest-only."""
    path = DATA_MANAGER / "analysis_database_list_widget.py"
    source = _source(path)
    edit_source = _function_source(path, "_edit_components_selected")

    assert "Edit Selected Database Components" in source
    assert "component_edit_requested" in source
    assert "_single_checked_manifest" in edit_source
    assert "component_edit_requested.emit(manifest)" in edit_source
    assert "AnalysisDatabaseComponentEditor" not in source
    assert "build_manifest_features_from_saved_columns" not in source
    assert "SavedArtifactColumn" not in source
    assert "materialize_database" not in edit_source
    assert "rebuild_database_with_features" not in source


def test_component_editor_dialog_is_explicit_recipe_edit_surface() -> None:
    """The component dialog owns GUI intent and delegates recipe changes to the data-layer editor."""
    path = DATA_MANAGER / "analysis_database_component_dialog.py"
    source = _source(path)

    assert "class AnalysisDatabaseComponentDialog" in source
    assert "AnalysisDatabaseComponentEditor" in source
    assert "load_saved_artifact_columns" in source
    assert "_EXISTING_COMPONENT_BRUSH" in source
    assert "QColor" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "SavedArtifactColumn" in source
    assert "replace_components" in source
    assert "add_components" in source
    assert "remove_components" in source
    assert "components_changed" in source
    assert "materialize_database" not in source
    assert "rebuild_database_with_features" not in source


def test_data_manager_opens_component_editor_from_database_builder_intent() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "AnalysisDatabaseComponentDialog" in source
    assert "self._database_list.component_edit_requested.connect(self._on_database_component_edit_requested)" in source
    assert "dialog.components_changed.connect(self._on_analysis_database_components_changed)" in source
    assert "selected_columns=self._selected_artifact_columns" not in source
    assert "self._artifact_selector.selection_changed.connect(self._on_saved_artifact_selection_changed)" not in source
    assert "self._artifact_selector.selection_changed.connect(self._database_list.set_selected_artifact_columns)" not in source


def test_saved_artifact_selector_uses_shared_column_loader() -> None:
    path = DATA_MANAGER / "saved_artifact_selector_widget.py"
    source = _source(path)

    assert "saved_artifact_columns import" in source
    assert "load_saved_artifact_columns" in source
    assert "DerivedCsvStore" not in source
    assert "get_indicator_specs" not in source


def test_build_dialog_auto_loads_saved_artifacts_and_builds_manifest_recipe() -> None:
    path = DATA_MANAGER / "analysis_database_build_dialog.py"
    source = _source(path)

    assert "class AnalysisDatabaseBuildDialog" in source
    assert "load_saved_artifact_columns" in source
    assert "_EXISTING_COMPONENT_BRUSH" in source
    assert "QColor" in source
    assert "build_manifest_features_from_saved_columns" in source
    assert "materialize_database" in source
    assert "database_id=self._manifest.database_id" in source
    assert "AnalysisDatabaseComponentEditor" not in source
    assert "replace_components" not in source
    assert "add_components" not in source
    assert "remove_components" not in source
    assert "rebuild_database_with_features" not in source


def test_data_manager_opens_build_dialog_from_database_builder_intent() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)

    assert "AnalysisDatabaseBuildDialog" in source
    assert "self._database_list.build_requested.connect(self._on_database_build_requested)" in source
    assert "dialog.database_materialized.connect(self._on_build_dialog_database_materialized)" in source
    assert "self._database_list.refresh()" in _function_source(path, "_on_build_dialog_database_materialized")


def test_recipe_collection_dialog_exposes_update_plan_intent_only() -> None:
    path = DATA_MANAGER / "artifact_recipe_collection_dialog.py"
    source = _source(path)
    plan_source = _function_source(path, "_plan_updates")

    assert "update_plan_requested = Signal(object, object)" in source
    assert "Plan Updates..." in source
    assert "self._update_plan_button.setEnabled(has_collection)" in source
    assert "update_plan_requested.emit(collection, selected_recipe_ids)" in plan_source
    assert "DataManagerUpdateService" not in source
    assert "execute_update_plan" not in source


def test_update_plan_dialog_is_display_and_confirmation_surface() -> None:
    path = DATA_MANAGER / "update_manager_dialog.py"
    source = _source(path)

    assert "class DataManagerUpdatePlanDialog" in source
    assert "execute_selected_requested = Signal(object)" in source
    assert "execute_all_requested = Signal()" in source
    assert "selected_action_ids" in source
    assert "set_execution_report" in source
    assert "DataManagerUpdateService" not in source
    assert "ArtifactRecoveryRegenerator" not in source
    assert "ArtifactRecoveryDatabaseRebuilder" not in source
    assert "compare_source" not in source
    assert "write_text" not in source
    assert "to_csv" not in source
    assert "json.dump" not in source


def test_tool_calculation_widget_routes_update_execution_through_update_service() -> None:
    path = DATA_MANAGER / "tool_calculation_widget.py"
    source = _source(path)
    plan_source = _function_source(path, "_update_plan_requested")
    execute_source = _function_source(path, "_execute_update_plan_requested")

    assert "DataManagerUpdateService" in source
    assert "self._update_service = DataManagerUpdateService(" in source
    assert "dialog.update_plan_requested.connect(self._update_plan_requested)" in source
    assert "plan_recipe_collection_update(" in plan_source
    assert "execute_update_plan(" in execute_source
    assert "DataManagerUpdatePlanDialog" in source
    assert "update_execution_finished = Signal(object)" in source
    assert "source_ohlcv" not in source
    assert "compare_source" not in source


def test_data_manager_refreshes_lists_after_update_execution() -> None:
    path = WINDOWS / "data_manager_window.py"
    source = _source(path)
    refresh_source = _function_source(path, "_on_update_execution_finished")

    assert "self._tool_calculation.update_execution_finished.connect(self._on_update_execution_finished)" in source
    assert "self._artifact_selector.refresh()" in refresh_source
    assert "self._database_list.refresh()" in refresh_source



def test_main_data_manager_widgets_use_right_side_button_racks() -> None:
    """Main Data Manager widgets should keep actions in a right-side vertical rack."""
    widget_files = (
        "dataset_selector_widget.py",
        "tool_calculation_widget.py",
        "saved_artifact_selector_widget.py",
        "analysis_database_list_widget.py",
    )
    for filename in widget_files:
        path = DATA_MANAGER / filename
        source = _source(path)
        assert "button_rack import make_button_rack" in source, filename
        assert "root = QHBoxLayout(self)" in source, filename
        assert "make_button_rack(" in source, filename

    preview_source = _source(DATA_MANAGER / "dataframe_preview_widget.py")
    assert "button_rack import make_button_rack" not in preview_source
    assert "make_button_rack(" not in preview_source
    assert "summary_area.addWidget(self._clear_button" in preview_source

    metadata_source = _source(DATA_MANAGER / "metadata_tools_widget.py")
    assert "button_rack import make_button_rack" in metadata_source
    assert "root = QGridLayout(self)" in metadata_source
    assert "root.addLayout(make_button_rack(self._restore_button), 0, 1)" in metadata_source

    seed_source = _source(DATA_MANAGER / "analysis_database_builder_widget.py")
    assert "button_rack import make_button_rack" in seed_source
    assert "root = QGridLayout(self)" in seed_source
    assert "root.addLayout(make_button_rack(self._button), 0, 1)" in seed_source

    helper_source = _source(DATA_MANAGER / "button_rack.py")
    assert "def make_button_rack" in helper_source
    assert "rack.addStretch(1)" in helper_source
    assert "rack.addWidget(button)" in helper_source


def test_data_manager_has_study_setup_recipe_export_entry_point() -> None:
    source = _source(DATA_MANAGER / "tool_calculation_widget.py")
    dialog_source = _source(DATA_MANAGER / "study_setup_recipe_export_dialog.py")

    assert "StudySetupRecipeExportDialog" in source
    assert '"Create Recipes from Study Setup..."' in source
    assert "_open_study_setup_recipe_export_dialog" in source
    assert "_study_setup_recipes_persisted" in source
    assert "self._recipe_dialog.refresh()" in source
    assert "self._collection_dialog.refresh()" in source

    assert "StudySetupRecipeExportPlanner" in dialog_source
    assert "StudySetupRecipeExportPersistenceService" in dialog_source
    assert "persist_export_plan(" in dialog_source
    assert "ArtifactRecipeExecutor" not in dialog_source
    assert "calculate_and_save" not in dialog_source
    assert "save_recipe(" not in dialog_source
    assert "save_collection(" not in dialog_source



def test_saved_recipe_dialogs_use_expanded_readable_list_areas() -> None:
    recipe_source = _source(DATA_MANAGER / "artifact_recipe_dialog.py")
    collection_source = _source(DATA_MANAGER / "artifact_recipe_collection_dialog.py")

    assert "self.resize(1080, 640)" in recipe_source
    assert "self.setMinimumSize(960, 560)" in recipe_source
    assert "self._recipe_list.setMinimumWidth(480)" in recipe_source
    assert "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in recipe_source
    assert "body.addWidget(list_group, 5)" in recipe_source

    assert "self.resize(1180, 700)" in collection_source
    assert "self.setMinimumSize(1040, 620)" in collection_source
    assert "self._collection_list.setMinimumWidth(460)" in collection_source
    assert "self._collection_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in collection_source
    assert "self._recipe_list.setMinimumHeight(260)" in collection_source
    assert "self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)" in collection_source
    assert "body.addWidget(collection_group, 4)" in collection_source
    assert "body.addWidget(detail_group, 5)" in collection_source
