from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
)

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.data_manager_construct_batch_execution_service import (
    ConstructBatchExecutionItemResult,
    ConstructBatchExecutionReport,
)
from leonardo.data.historical.data_manager_construct_batch_persistence import (
    ConstructBatchPersistenceReport,
)
from leonardo.gui.windows._data_manager import dialog_geometry as dm_dialog_geometry
from leonardo.gui.windows._data_manager.saved_artifact_columns import SavedArtifactColumn
from leonardo.gui.windows._data_manager.construct_batch_dialog import (
    ConstructBatchBuilderDialog,
)
from leonardo.gui.windows._data_manager.tool_calculation_widget import (
    _DataManagerFinancialToolsWindow,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo"
DATA_MANAGER = SRC / "gui" / "windows" / "_data_manager"
WINDOWS = SRC / "gui" / "windows"

_QAPP: QApplication | None = None


def _qapp() -> QApplication:
    global _QAPP
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    _QAPP = QApplication([])
    return _QAPP


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _FakeScreen:
    def availableGeometry(self) -> QRect:
        return QRect(10, 20, 2000, 1200)


def _set_combo_value(combo, value: str) -> None:
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
    raise AssertionError(f"Combo value not found: {value!r}")


def _write_csv(path: Path, timestamps: tuple[int, ...], column_name: str) -> Path:
    lines = ["ts_ms," + column_name]
    lines.extend(f"{ts},{idx + 1}.0" for idx, ts in enumerate(timestamps))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_ohlcv(root: Path) -> Path:
    path = root / "bybit" / "linear" / "BTCUSDT" / "1m" / "ohlcv" / "candles.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "ts_ms,open,high,low,close,volume\n"
        "1000,1,2,0.5,1.5,10\n"
        "2000,2,3,1.5,2.5,20\n"
        "3000,3,4,2.5,3.5,30\n",
        encoding="utf-8",
    )
    return path


def _saved_column(
    root: Path,
    *,
    family: str = "indicators",
    column_name: str = "rsi_14",
) -> SavedArtifactColumn:
    path = _write_csv(root / f"{column_name}.csv", (1000, 2000, 3000), column_name)
    return SavedArtifactColumn(
        family=family,
        tool_key=column_name.split("_", 1)[0],
        tool_title=column_name.split("_", 1)[0].upper(),
        instance_key=column_name,
        column_name=column_name,
        path=path,
        analysis_usable=True,
        renderable=True,
    )


class _FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[str, ...]]] = []

    def execute_selected_artifacts(self, *, plan, selected_item_ids):
        selected_ids = tuple(selected_item_ids)
        self.calls.append((plan, selected_ids))
        persistence_report = ConstructBatchPersistenceReport(
            batch_kind=plan.batch_kind,
            construct_key=plan.construct_key,
            selected_count=len(selected_ids),
            saved_recipe_count=len(selected_ids),
            reused_recipe_count=0,
            skipped_count=0,
            blocked_count=0,
            failed_count=0,
            collection_saved=False,
            collection_id=None,
            collection_name=None,
            results=(),
        )
        results = tuple(
            ConstructBatchExecutionItemResult(
                item_id=item_id,
                status="completed",
                display_name=f"Result {index}",
                recipe_id=f"recipe_{index}",
                recipe_hash=f"hash_{index}",
                reason="Artifact recipe executed.",
                artifact_path=f"artifact_{index}.csv",
                execution_attempted=True,
            )
            for index, item_id in enumerate(selected_ids)
        )
        return ConstructBatchExecutionReport(
            report_id="test_report",
            plan_id=plan.plan_id,
            batch_kind=plan.batch_kind,
            construct_key=plan.construct_key,
            started_at_utc="2026-05-28T00:00:00Z",
            finished_at_utc="2026-05-28T00:00:01Z",
            selected_count=len(selected_ids),
            saved_recipe_count=len(selected_ids),
            reused_recipe_count=0,
            persisted_recipe_count=len(selected_ids),
            execution_attempted_count=len(selected_ids),
            completed_count=len(selected_ids),
            skipped_count=0,
            blocked_count=0,
            failed_count=0,
            cancelled=False,
            results=results,
            persistence_report=persistence_report,
        )


def _dialog(
    tmp_path: Path,
    *,
    columns: list[SavedArtifactColumn] | None = None,
    execution_service: object | None = None,
) -> ConstructBatchBuilderDialog:
    from leonardo.data.naming import canonicalize

    return ConstructBatchBuilderDialog(
        historical_root=tmp_path,
        market=canonicalize("bybit", "linear", "BTCUSDT", "1m"),
        source_loader=lambda **_kwargs: list(columns or [_saved_column(tmp_path)]),
        execution_service=execution_service,
    )


def test_data_manager_popup_uses_sixty_percent_available_width_and_height(monkeypatch) -> None:
    _qapp()
    dialog = QDialog()
    dialog.setMinimumSize(900, 620)
    monkeypatch.setattr(
        dm_dialog_geometry,
        "_screen_for_dialog",
        lambda _dialog: _FakeScreen(),
    )

    dm_dialog_geometry.apply_data_manager_dialog_initial_size(
        dialog,
        default_width=900,
        default_height=620,
    )

    assert dialog.width() == 1200
    assert dialog.height() == 720
    assert dialog.x() == 10 + (2000 - 1200) // 2
    assert dialog.y() == 20 + (1200 - 720) // 2

    tool_source = _source(DATA_MANAGER / "tool_calculation_widget.py")
    geometry_source = _source(DATA_MANAGER / "dialog_geometry.py")
    assert "apply_data_manager_dialog_initial_size" in tool_source
    assert "default_width=900" in tool_source
    assert "default_height=620" in tool_source
    assert "DATA_MANAGER_DIALOG_INITIAL_HEIGHT_RATIO = 0.60" in geometry_source
    assert "availableGeometry()" in geometry_source


def test_construct_batch_button_is_data_manager_save_only_and_construct_scoped(
    tmp_path: Path,
) -> None:
    _qapp()
    window = _DataManagerFinancialToolsWindow(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        historical_root=tmp_path,
        save_only=True,
    )
    try:
        button = window._construct_batch_button

        assert button.text() == "Construct Batch..."
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "indicator")
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "oscillator")
        assert button.isHidden()

        _set_combo_value(window._tool_type_combo, "construct")
        assert not button.isHidden()
        assert button.isEnabled()
    finally:
        window.close()


def test_construct_batch_button_opens_dialog_with_backend_context(tmp_path: Path) -> None:
    _qapp()
    window = _DataManagerFinancialToolsWindow(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        historical_root=tmp_path,
        save_only=True,
    )
    try:
        _set_combo_value(window._tool_type_combo, "construct")
        window._construct_batch_button.click()

        assert isinstance(window._construct_batch_dialog, ConstructBatchBuilderDialog)
        assert window._construct_batch_dialog._historical_root == tmp_path
    finally:
        if window._construct_batch_dialog is not None:
            window._construct_batch_dialog.close()
        window.close()


def test_construct_batch_builder_modes_and_disabled_calculation(tmp_path: Path) -> None:
    _qapp()
    dialog = _dialog(tmp_path)
    try:
        text = "\n".join(
            [label.text() for label in dialog.findChildren(QLabel)]
            + [edit.toPlainText() for edit in dialog.findChildren(QPlainTextEdit)]
            + [dialog._mode_combo.itemText(index) for index in range(dialog._mode_combo.count())]
            + [dialog._construct_combo.itemText(index) for index in range(dialog._construct_combo.count())]
        )

        for expected in (
            "Unary source expansion",
            "delta = minuend - subtrahend",
            "derivative",
            "angle",
            "percent_span_angle",
            "angle_momentum",
        ):
            assert expected in text

        assert {
            dialog._construct_combo.itemData(index)
            for index in range(dialog._construct_combo.count())
        } == {"derivative", "angle", "percent_span_angle", "angle_momentum"}
        _set_combo_value(dialog._mode_combo, "delta")
        assert dialog._construct_combo.count() == 1
        assert dialog._construct_combo.itemData(0) == "delta"

        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        assert buttons["Preview Plan"].isEnabled()
        assert not buttons["Save Recipes"].isEnabled()
        assert not buttons["Save as Collection"].isEnabled()
        assert not buttons["Calculate Artifacts"].isEnabled()
        assert "does not modify Analysis Databases" in buttons["Calculate Artifacts"].toolTip()
        assert buttons["Close"].isEnabled()
        for unsupported in ("braids", "braid_instability", "trap_area", "dynamic_binning"):
            assert unsupported not in {
                dialog._construct_combo.itemData(index)
                for index in range(dialog._construct_combo.count())
            }
    finally:
        dialog.close()


def test_preview_plan_builds_unary_plan_without_persistence(tmp_path: Path) -> None:
    _qapp()
    column = _saved_column(tmp_path, family="indicators", column_name="rsi_14")
    dialog = _dialog(tmp_path, columns=[column])
    try:
        _set_combo_value(dialog._mode_combo, "unary")
        _set_combo_value(dialog._construct_combo, "derivative")
        _set_combo_value(dialog._unary_source_group_combo, "indicators")

        dialog._preview_plan_button.click()

        assert dialog._latest_plan is not None
        assert dialog._latest_plan.batch_kind == "unary"
        assert dialog._latest_plan.planned_count == 1
        assert dialog._plan_table.rowCount() == 1
        assert dialog._plan_table.item(0, 1).text() == "planned"
        assert dialog._plan_table.item(0, 0).checkState() == Qt.CheckState.Checked
        assert dialog._save_recipes_button.isEnabled()
        assert dialog._calculate_artifacts_button.isEnabled()
        assert ArtifactRecipeStore(historical_root=tmp_path).list_recipes(
            market=_market_from_dialog(dialog)
        ) == []
        assert "Planned: 1" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_preview_plan_builds_delta_plan_with_close_fixed_source(tmp_path: Path) -> None:
    _qapp()
    _write_ohlcv(tmp_path)
    column = _saved_column(tmp_path, family="indicators", column_name="rsi_14")
    dialog = _dialog(tmp_path, columns=[column])
    try:
        _set_combo_value(dialog._mode_combo, "delta")
        _set_combo_value(dialog._variable_source_group_combo, "indicators")
        _set_combo_value(dialog._fixed_role_combo, "minuend")

        dialog._preview_plan_button.click()

        assert dialog._latest_plan is not None
        assert dialog._latest_plan.batch_kind == "delta"
        assert dialog._latest_plan.planned_count == 1
        item = dialog._latest_plan.items[0]
        assert item.role_bindings["minuend"] == "close"
        assert item.role_bindings["subtrahend"] == "rsi_14"
        assert "delta = minuend - subtrahend" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_blocked_plan_items_are_not_selectable_for_persistence(tmp_path: Path) -> None:
    _qapp()
    missing_column = SavedArtifactColumn(
        family="indicators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="missing",
        column_name="missing",
        path=tmp_path / "missing.csv",
        analysis_usable=True,
        renderable=True,
    )
    dialog = _dialog(tmp_path, columns=[missing_column])
    try:
        dialog._preview_plan_button.click()

        assert dialog._latest_plan is not None
        assert dialog._latest_plan.blocked_count == 1
        select_item = dialog._plan_table.item(0, 0)
        assert not bool(select_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert not dialog._save_recipes_button.isEnabled()
        assert not dialog._calculate_artifacts_button.isEnabled()
    finally:
        dialog.close()


def test_calculate_artifacts_uses_execution_service_and_terminal_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _qapp()
    column = _saved_column(tmp_path, family="indicators", column_name="rsi_14")
    execution_service = _FakeExecutionService()
    dialog = _dialog(
        tmp_path,
        columns=[column],
        execution_service=execution_service,
    )
    messages: list[object] = []
    dialog.execution_finished.connect(messages.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        assert not dialog._calculate_artifacts_button.isEnabled()

        dialog._preview_plan_button.click()
        assert dialog._calculate_artifacts_button.isEnabled()

        dialog._calculate_artifacts_button.click()

        assert len(execution_service.calls) == 1
        plan, selected_ids = execution_service.calls[0]
        assert plan is dialog._latest_plan
        assert selected_ids == (dialog._latest_plan.items[0].item_id,)
        assert messages
        report_text = dialog._report_text.toPlainText()
        assert "Construct batch artifact calculation report" in report_text
        assert "Completed: 1" in report_text
        assert "Failed: 0" in report_text
        assert "Analysis Databases modified: 0" in report_text
    finally:
        dialog.close()


def test_save_recipes_and_collection_use_persistence_service(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    column = _saved_column(tmp_path, family="indicators", column_name="rsi_14")
    dialog = _dialog(tmp_path, columns=[column])
    messages: list[object] = []
    dialog.persistence_finished.connect(messages.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    try:
        dialog._preview_plan_button.click()
        dialog._save_recipes_button.click()

        assert messages
        assert messages[-1].saved_recipe_count == 1
        assert messages[-1].collection_saved is False

        dialog._collection_name_edit.setText("Construct Batch Pack")
        assert dialog._save_collection_button.isEnabled()
        dialog._save_collection_button.click()

        assert messages[-1].collection_saved is True
        assert messages[-1].reused_recipe_count == 1
        collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
            market=_market_from_dialog(dialog),
            collection_id=messages[-1].collection_id,
        )
        assert collection.display_name == "Construct Batch Pack"
        assert [recipe.recipe_id for recipe in collection.recipe_snapshots] == [
            messages[-1].results[0].recipe_id
        ]
    finally:
        dialog.close()


def test_construct_batch_gui_shell_keeps_backend_boundaries() -> None:
    dialog_source = _source(DATA_MANAGER / "construct_batch_dialog.py")
    tool_source = _source(DATA_MANAGER / "tool_calculation_widget.py")

    assert "ConstructBatchBuilderDialog" in tool_source
    assert "Construct Batch..." in tool_source
    assert "Construct Batch" not in _source(WINDOWS / "financial_tools_manager_window.py")
    assert "Construct Batch" not in _source(WINDOWS / "historical_chart_panel.py")

    allowed_dialog_tokens = (
        "DataManagerConstructBatchPlanner",
        "DataManagerConstructBatchPersistenceService",
        "DataManagerConstructBatchExecutionService",
        "load_saved_artifact_columns",
    )
    for token in allowed_dialog_tokens:
        assert token in dialog_source

    forbidden_dialog_tokens = (
        "ArtifactRecipeStore",
        "ArtifactRecipeCollectionStore",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "ArtifactRecoveryRegenerator",
        "AnalysisDatabaseStore",
        "DataManagerSelectedUpdateService",
        "DataManagerUpdateService",
        "write_text",
        "write_bytes",
        "json.dump",
        "open(",
        "to_csv",
        "save_manifest",
        "materialize_database",
    )
    for token in forbidden_dialog_tokens:
        assert token not in dialog_source


def _market_from_dialog(dialog: ConstructBatchBuilderDialog):
    from leonardo.data.naming import canonicalize

    assert dialog._market is not None
    return canonicalize(
        dialog._market.exchange,
        dialog._market.market_type,
        dialog._market.symbol,
        dialog._market.timeframe,
    )
