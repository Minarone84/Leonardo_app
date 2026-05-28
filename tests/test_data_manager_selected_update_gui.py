from __future__ import annotations

import ast
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseSummary
from leonardo.data.historical.data_manager_selected_update_service import (
    SelectedAnalysisDatabaseUpdateRef,
    SelectedArtifactUpdatePlan,
    SelectedArtifactUpdatePlanItem,
    SelectedArtifactUpdateRef,
    SelectedDatabaseUpdatePlan,
    SelectedDatabaseUpdatePlanItem,
    SelectedUpdateAction,
    SelectedUpdateExecutionItemResult,
    SelectedUpdateExecutionReport,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.saved_artifact_columns import SavedArtifactColumn


ROOT = Path(__file__).resolve().parents[1]
DATA_MANAGER = ROOT / "src" / "leonardo" / "gui" / "windows" / "_data_manager"

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


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {function_name!r} not found in {path}")


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in tuple(self._callbacks):
            callback()


class _AutoConfirmDialog:
    instances: list["_AutoConfirmDialog"] = []

    def __init__(
        self,
        *,
        title: str,
        summary: str,
        item_names: object,
        confirm_label: str,
        parent: object = None,
    ) -> None:
        self.title = title
        self.summary = summary
        self.item_names = tuple(item_names)
        self.confirm_label = confirm_label
        self.parent = parent
        self.confirmed = _FakeSignal()
        self.running_messages: list[str] = []
        self.terminal_reports: list[str] = []
        _AutoConfirmDialog.instances.append(self)

    def exec(self) -> int:
        self.confirmed.emit()
        return QDialog.Accepted

    def set_running(self, message: str) -> None:
        self.running_messages.append(message)

    def set_terminal_report(self, report_text: str) -> None:
        self.terminal_reports.append(report_text)


class _FakeSelectedUpdateService:
    def __init__(self, *, historical_root: Path) -> None:
        self.historical_root = historical_root
        self.artifact_plan: SelectedArtifactUpdatePlan | None = None
        self.database_plan: SelectedDatabaseUpdatePlan | None = None
        self.execution_report = _execution_report(
            plan_id="plan",
            action_id="action",
        )
        self.artifact_refs: tuple[SelectedArtifactUpdateRef, ...] = ()
        self.database_refs: tuple[SelectedAnalysisDatabaseUpdateRef, ...] = ()
        self.artifact_execute_action_ids: tuple[str, ...] = ()
        self.database_execute_action_ids: tuple[str, ...] = ()

    def plan_artifact_updates(
        self,
        refs: tuple[SelectedArtifactUpdateRef, ...],
    ) -> SelectedArtifactUpdatePlan:
        self.artifact_refs = tuple(refs)
        assert self.artifact_plan is not None
        return self.artifact_plan

    def execute_artifact_update_plan(
        self,
        plan: SelectedArtifactUpdatePlan,
        *,
        selected_action_ids: tuple[str, ...],
    ) -> SelectedUpdateExecutionReport:
        self.artifact_execute_action_ids = tuple(selected_action_ids)
        return replace(self.execution_report, plan_id=plan.plan_id)

    def plan_database_updates(
        self,
        refs: tuple[SelectedAnalysisDatabaseUpdateRef, ...],
    ) -> SelectedDatabaseUpdatePlan:
        self.database_refs = tuple(refs)
        assert self.database_plan is not None
        return self.database_plan

    def execute_database_update_plan(
        self,
        plan: SelectedDatabaseUpdatePlan,
        *,
        selected_action_ids: tuple[str, ...],
    ) -> SelectedUpdateExecutionReport:
        self.database_execute_action_ids = tuple(selected_action_ids)
        return replace(self.execution_report, plan_id=plan.plan_id)


def test_saved_artifact_select_all_and_deselect_all(monkeypatch, tmp_path: Path) -> None:
    widget, _service, _columns = _artifact_widget(monkeypatch, tmp_path)

    widget.select_all_artifacts()
    assert _checked_count(widget._list) == 2
    assert widget._check_update_button.isEnabled()

    widget.deselect_all_artifacts()
    assert _checked_count(widget._list) == 0
    assert not widget._check_update_button.isEnabled()
    assert not widget._update_selected_button.isEnabled()


def test_saved_artifact_check_update_marks_service_statuses(monkeypatch, tmp_path: Path) -> None:
    widget, service, columns = _artifact_widget(monkeypatch, tmp_path)
    service.artifact_plan = _artifact_plan(columns)

    widget.select_all_artifacts()
    widget._check_selected_artifact_updates()

    assert [ref.artifact_path for ref in service.artifact_refs] == [columns[0].path, columns[1].path]
    assert widget._list.item(0).text().startswith("[OLD]")
    assert widget._list.item(1).text().startswith("[CURRENT]")
    assert widget._update_selected_button.isEnabled()
    assert "old" in _AutoConfirmDialog.instances[-1].terminal_reports[-1]


def test_saved_artifact_update_executes_only_checked_old_action(monkeypatch, tmp_path: Path) -> None:
    widget, service, columns = _artifact_widget(monkeypatch, tmp_path)
    service.artifact_plan = _artifact_plan(columns)

    widget.select_all_artifacts()
    widget._check_selected_artifact_updates()
    widget._update_selected_artifacts()

    assert service.artifact_execute_action_ids == ("regenerate:old-rsi",)
    assert not widget._update_selected_button.isEnabled()


def test_database_select_all_deselect_all_and_existing_single_row_gates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    widget, _service, _summaries = _database_widget(monkeypatch, tmp_path)

    widget._list.item(0).setCheckState(Qt.Checked)
    assert widget._rebuild_button.isEnabled()
    assert not widget._build_button.isEnabled()

    widget.select_all_databases()
    assert _checked_count(widget._list) == 2
    assert not widget._rebuild_button.isEnabled()
    assert not widget._build_button.isEnabled()
    assert widget._check_update_button.isEnabled()

    widget.deselect_all_databases()
    assert _checked_count(widget._list) == 0
    assert not widget._check_update_button.isEnabled()


def test_database_check_update_marks_old_and_draft_without_old_draft(
    monkeypatch,
    tmp_path: Path,
) -> None:
    widget, service, summaries = _database_widget(monkeypatch, tmp_path)
    service.database_plan = _database_plan()

    widget.select_all_databases()
    widget._check_selected_database_updates()

    assert [ref.database_id for ref in service.database_refs] == [summaries[0].database_id, summaries[1].database_id]
    assert widget._list.item(0).text().startswith("[OLD]")
    assert widget._list.item(1).text().startswith("[DRAFT]")
    assert widget._update_selected_button.isEnabled()


def test_database_update_executes_only_checked_old_action(monkeypatch, tmp_path: Path) -> None:
    widget, service, _summaries = _database_widget(monkeypatch, tmp_path)
    service.database_plan = _database_plan()

    widget.select_all_databases()
    widget._check_selected_database_updates()
    widget._update_selected_databases()

    assert service.database_execute_action_ids == ("rebuild:old-db",)
    assert not widget._update_selected_button.isEnabled()


def test_selected_update_dialog_terminal_state_enables_ok() -> None:
    _qapp()
    from leonardo.gui.windows._data_manager.selected_update_dialog import SelectedUpdateDialog

    dialog = SelectedUpdateDialog(
        title="Check Update",
        summary="Selected items: 1",
        item_names=("Example",),
        confirm_label="Check Update",
    )

    assert not dialog._ok_button.isEnabled()
    dialog.set_running("Running")
    assert not dialog._ok_button.isEnabled()
    assert not dialog._cancel_button.isEnabled()
    dialog.set_terminal_report("Done")
    assert dialog._ok_button.isEnabled()
    assert not dialog._cancel_button.isEnabled()


def test_selected_update_gui_boundaries() -> None:
    artifact_path = DATA_MANAGER / "saved_artifact_selector_widget.py"
    database_path = DATA_MANAGER / "analysis_database_list_widget.py"
    selected_dialog_path = DATA_MANAGER / "selected_update_dialog.py"

    artifact_source = _source(artifact_path)
    database_source = _source(database_path)
    dialog_source = _source(selected_dialog_path)
    combined = artifact_source + database_source + dialog_source

    assert "DataManagerSelectedUpdateService" in combined
    assert "plan_artifact_updates" in artifact_source
    assert "execute_artifact_update_plan" in artifact_source
    assert "plan_database_updates" in database_source
    assert "execute_database_update_plan" in database_source
    assert "source_ohlcv" not in combined
    assert "ArtifactRecoveryRegenerator" not in combined
    assert "ArtifactRecipeExecutor" not in combined
    assert "write_text" not in combined
    assert "json.dump" not in combined
    assert "to_csv" not in combined
    assert "save_manifest" not in combined
    assert "materialize_database" not in _function_source(database_path, "_run_database_update_execution")


def _artifact_widget(monkeypatch, tmp_path: Path):
    _qapp()
    from leonardo.gui.windows._data_manager import saved_artifact_selector_widget as module

    _AutoConfirmDialog.instances.clear()
    columns = (
        _saved_column("old-rsi", tmp_path / "old-rsi.csv"),
        _saved_column("current-rsi", tmp_path / "current-rsi.csv"),
    )
    monkeypatch.setattr(module, "load_saved_artifact_columns", lambda **_kwargs: list(columns))
    monkeypatch.setattr(module, "DataManagerSelectedUpdateService", _FakeSelectedUpdateService)
    monkeypatch.setattr(module, "SelectedUpdateDialog", _AutoConfirmDialog)

    widget = module.SavedArtifactSelectorWidget(historical_root=tmp_path)
    widget.set_market(_market())
    return widget, widget._selected_update_service, columns


def _database_widget(monkeypatch, tmp_path: Path):
    _qapp()
    from leonardo.gui.windows._data_manager import analysis_database_list_widget as module

    _AutoConfirmDialog.instances.clear()
    summaries = (
        _summary("old-db", "Old database", "materialized", 10, tmp_path),
        _summary("draft-db", "Draft database", "draft", None, tmp_path),
    )

    class _FakeAnalysisDatabaseStore:
        def __init__(self, *, historical_root: Path) -> None:
            self.historical_root = historical_root

        def list_databases(self, *, market: MarketId) -> list[AnalysisDatabaseSummary]:
            return list(summaries)

    monkeypatch.setattr(module, "AnalysisDatabaseStore", _FakeAnalysisDatabaseStore)
    monkeypatch.setattr(module, "DataManagerSelectedUpdateService", _FakeSelectedUpdateService)
    monkeypatch.setattr(module, "SelectedUpdateDialog", _AutoConfirmDialog)

    widget = module.AnalysisDatabaseListWidget(historical_root=tmp_path)
    widget.set_market(_market())
    return widget, widget._selected_update_service, summaries


def _market() -> MarketId:
    return MarketId(exchange="bybit", market_type="linear", symbol="BTCUSDT", timeframe="1h")


def _saved_column(instance_key: str, path: Path) -> SavedArtifactColumn:
    return SavedArtifactColumn(
        family="indicators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key=instance_key,
        column_name=f"{instance_key}_value",
        path=path,
    )


def _summary(
    database_id: str,
    display_name: str,
    status: str,
    row_count: int | None,
    tmp_path: Path,
) -> AnalysisDatabaseSummary:
    return AnalysisDatabaseSummary(
        database_id=database_id,
        display_name=display_name,
        status=status,
        market=_market(),
        user_description="",
        generated_summary="",
        studies_used_summary="",
        row_count=row_count,
        column_count=3 if row_count is not None else None,
        feature_count=2,
        created_at_ms=None,
        updated_at_ms=None,
        manifest_path=tmp_path / database_id / "manifest.json",
    )


def _artifact_plan(columns: tuple[SavedArtifactColumn, ...]) -> SelectedArtifactUpdatePlan:
    old_item = SelectedArtifactUpdatePlanItem(
        item_id="artifact:old-rsi",
        family="indicators",
        display_name="Old RSI",
        status="old",
        actionable=True,
        reason="Source OHLCV drifted.",
        expected_action_label="Regenerate artifact",
        metadata={"artifact_path": columns[0].path},
    )
    current_item = SelectedArtifactUpdatePlanItem(
        item_id="artifact:current-rsi",
        family="indicators",
        display_name="Current RSI",
        status="current",
        actionable=False,
        reason="Artifact is current.",
        metadata={"artifact_path": columns[1].path},
    )
    action = SelectedUpdateAction(
        action_id="regenerate:old-rsi",
        action_type="regenerate_artifact",
        item_id=old_item.item_id,
        item_type="artifact",
        label="Regenerate Old RSI",
        reason="Source OHLCV drifted.",
    )
    return SelectedArtifactUpdatePlan(
        plan_id="artifact-plan",
        created_at_utc="now",
        items=(old_item, current_item),
        actions=(action,),
        warnings=(),
        blockers=(),
        summary={"total_items": 2, "old": 1, "current": 1, "actions": 1},
    )


def _database_plan() -> SelectedDatabaseUpdatePlan:
    old_item = SelectedDatabaseUpdatePlanItem(
        item_id="analysis_database:old-db",
        database_id="old-db",
        display_name="Old database",
        status="old",
        actionable=True,
        reason="Materialization source drifted.",
        materialized=True,
        expected_action_label="Rebuild database",
    )
    draft_item = SelectedDatabaseUpdatePlanItem(
        item_id="analysis_database:draft-db",
        database_id="draft-db",
        display_name="Draft database",
        status="draft",
        actionable=False,
        reason="Database is not materialized.",
        materialized=False,
    )
    action = SelectedUpdateAction(
        action_id="rebuild:old-db",
        action_type="rebuild_analysis_database",
        item_id=old_item.item_id,
        item_type="analysis_database",
        label="Rebuild Old database",
        reason="Materialization source drifted.",
    )
    return SelectedDatabaseUpdatePlan(
        plan_id="database-plan",
        created_at_utc="now",
        items=(old_item, draft_item),
        actions=(action,),
        warnings=(),
        blockers=(),
        summary={"total_items": 2, "old": 1, "draft": 1, "actions": 1},
    )


def _execution_report(*, plan_id: str, action_id: str) -> SelectedUpdateExecutionReport:
    result = SelectedUpdateExecutionItemResult(
        action_id=action_id,
        action_type="test",
        item_id="item",
        status="completed",
        message="completed",
        started_at_utc="start",
        finished_at_utc="finish",
    )
    return SelectedUpdateExecutionReport(
        report_id="report",
        plan_id=plan_id,
        started_at_utc="start",
        finished_at_utc="finish",
        requested_action_ids=(action_id,),
        completed_action_ids=(action_id,),
        skipped_action_ids=(),
        failed_action_ids=(),
        blocked_action_ids=(),
        results=(result,),
        summary={"requested": 1, "completed": 1},
    )


def _checked_count(list_widget) -> int:
    return sum(
        1
        for row in range(list_widget.count())
        if list_widget.item(row).checkState() == Qt.Checked
    )
