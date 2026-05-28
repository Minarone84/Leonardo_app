from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.data.historical.analysis_database_contracts import market_to_dict
from leonardo.data.historical.recipe_collection_database_planner import (
    RecipeCollectionDatabaseBlockedItem,
    RecipeCollectionDatabaseComponentPreview,
    RecipeCollectionDatabasePlan,
    RecipeCollectionDatabaseWarning,
)
from leonardo.gui.windows._data_manager.recipe_collection_database_dialog import (
    RecipeCollectionDatabaseDialog,
)
from leonardo.data.naming import canonicalize


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


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _collection():
    return SimpleNamespace(
        collection_id="arc__test",
        display_name="Collection Pack",
        market=_market(),
        recipe_snapshots=(SimpleNamespace(),),
    )


def _database():
    return SimpleNamespace(
        database_id="adb__existing",
        display_name="Existing Database",
        status="draft",
        market=_market(),
    )


def _component(
    *,
    recipe_index: int = 1,
    tool_key: str = "rsi",
    db_column_name: str = "oscillators_rsi_test_rsi_14",
) -> RecipeCollectionDatabaseComponentPreview:
    return RecipeCollectionDatabaseComponentPreview(
        component_id=f"component:{recipe_index}",
        recipe_index=recipe_index,
        recipe_id=f"recipe_{recipe_index}",
        recipe_hash=f"hash_{recipe_index}",
        tool_type="oscillator",
        tool_key=tool_key,
        storage_family="oscillators",
        instance_key=f"{tool_key}_test",
        artifact_relpath=f"oscillators/{tool_key}_test.csv",
        artifact_filename=f"{tool_key}_test.csv",
        artifact_fingerprint="abc123",
        source_preview={
            "source_id": f"oscillators__{tool_key}__test",
            "family": "oscillators",
            "tool_key": tool_key,
        },
        column_previews=(
            {
                "role": "feature",
                "selected": True,
                "source_family": "oscillators",
                "source_id": f"oscillators__{tool_key}__test",
                "source_column_name": "rsi_14",
                "db_column_name": db_column_name,
            },
        ),
        metadata={"artifact_uid": f"artifact_{recipe_index}"},
    )


def _blocker() -> RecipeCollectionDatabaseBlockedItem:
    return RecipeCollectionDatabaseBlockedItem(
        blocker_id="blocker:2:artifact_missing",
        recipe_index=2,
        recipe_id="recipe_2",
        tool_key="ema",
        status="missing",
        reason="artifact_missing",
        message="Expected artifact is missing.",
        metadata={},
    )


def _warning() -> RecipeCollectionDatabaseWarning:
    return RecipeCollectionDatabaseWarning(
        code="blocked_plan_items_skipped",
        message="Blocked plan items are excluded.",
        metadata={},
    )


def _geography_report(*, complete: bool = False) -> dict[str, object]:
    return {
        "complete": complete,
        "present_keys": ["volume_artifact"],
        "missing_keys": ["ohlc_base", "braids", "peaks_troughs", "utc"],
        "warnings": [
            {
                "code": "semantic_volume_duplication",
                "message": "Volume duplication risk.",
            }
        ],
    }


def _plan(
    *,
    resolved_components: tuple[RecipeCollectionDatabaseComponentPreview, ...] | None = None,
    blocked_items: tuple[RecipeCollectionDatabaseBlockedItem, ...] = (),
    warnings: tuple[RecipeCollectionDatabaseWarning, ...] = (),
    duplicate_columns: tuple[str, ...] = (),
) -> RecipeCollectionDatabasePlan:
    components = (_component(),) if resolved_components is None else resolved_components
    return RecipeCollectionDatabasePlan(
        plan_id="rcdb_plan__test",
        created_at_utc="2026-05-26T00:00:00Z",
        collection_id="arc__test",
        collection_display_name="Collection Pack",
        market=market_to_dict(_market()),
        source_database_id=None,
        resolved_components=components,
        blocked_items=blocked_items,
        warnings=warnings,
        duplicate_columns=duplicate_columns,
        geography_report=_geography_report(),
        summary={
            "total_recipes": len(components) + len(blocked_items),
            "resolved": len(components),
            "blocked": len(blocked_items),
            "warnings": len(warnings),
            "duplicate_columns": len(duplicate_columns),
        },
        metadata={},
    )


class _FakePlanner:
    def __init__(self, plan: RecipeCollectionDatabasePlan) -> None:
        self.plan = plan
        self.calls: list[tuple[object, bool]] = []

    def plan_collection_components(
        self,
        collection: object,
        *,
        include_geography_report: bool = True,
    ) -> RecipeCollectionDatabasePlan:
        self.calls.append((collection, include_geography_report))
        return self.plan


class _FakeService:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.extend_calls: list[dict[str, object]] = []

    def create_database_from_plan(self, plan: object, **kwargs):
        self.create_calls.append({"plan": plan, **kwargs})
        return _apply_report(
            status="created",
            operation="create",
            database_id="adb__created",
            display_name=str(kwargs["display_name"]),
        )

    def extend_database_from_plan(self, plan: object, **kwargs):
        self.extend_calls.append({"plan": plan, **kwargs})
        return _apply_report(
            status="extended",
            operation="extend",
            database_id=str(kwargs["database_id"]),
            display_name="Existing Database",
        )


class _FakeCollectionStore:
    def __init__(self, summaries: list[SimpleNamespace] | None = None) -> None:
        self.summaries = summaries if summaries is not None else [
            SimpleNamespace(
                collection_id="arc__test",
                display_name="Collection Pack",
                recipe_count=1,
            )
        ]
        self.calls: list[object] = []

    def list_collections(self, *, market: object):
        self.calls.append(market)
        return list(self.summaries)

    def load_collection(self, *, market: object, collection_id: str):
        self.calls.append((market, collection_id))
        if collection_id != "arc__test":
            raise FileNotFoundError(collection_id)
        return _collection()


def _apply_report(
    *,
    status: str,
    operation: str,
    database_id: str,
    display_name: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        report_id="rcdb_apply__test",
        operation=operation,
        status=status,
        database_id=database_id,
        display_name=display_name,
        added_source_count=1,
        added_column_count=1,
        skipped_component_count=0,
        blockers=(),
        warnings=(),
        geography_report=_geography_report(complete=True),
    )


def _dialog(
    tmp_path: Path,
    *,
    plan: RecipeCollectionDatabasePlan | None = None,
    service: _FakeService | None = None,
    collection_store: _FakeCollectionStore | None = None,
) -> tuple[RecipeCollectionDatabaseDialog, _FakePlanner, _FakeService, _FakeCollectionStore]:
    _qapp()
    planner = _FakePlanner(plan or _plan())
    service = service or _FakeService()
    collection_store = collection_store or _FakeCollectionStore()
    dialog = RecipeCollectionDatabaseDialog(
        historical_root=tmp_path,
        target_database=_database(),  # type: ignore[arg-type]
        planner=planner,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        collection_store=collection_store,  # type: ignore[arg-type]
    )
    return dialog, planner, service, collection_store


def test_dialog_resolves_collection_and_displays_plan(tmp_path: Path) -> None:
    plan = _plan(blocked_items=(_blocker(),), warnings=(_warning(),))
    dialog, planner, _service, _store = _dialog(tmp_path, plan=plan)
    try:
        assert planner.calls == [(_collection(), True)]
        assert dialog._component_table.rowCount() == 1
        assert dialog._blocked_table.rowCount() == 1
        assert "blocked_plan_items_skipped" in dialog._plan_text.toPlainText()
        assert "volume_artifact" in dialog._plan_text.toPlainText()
        assert "semantic_volume_duplication" in dialog._plan_text.toPlainText()
    finally:
        dialog.close()


def test_dialog_is_extend_only_and_shows_selected_database(tmp_path: Path) -> None:
    dialog, _planner, service, _store = _dialog(tmp_path)
    try:
        assert dialog.windowTitle() == "Extend Analysis Database from Collection"
        assert "Target database: Existing Database" in dialog._target_label.text()
        assert dialog.selected_database_id() == "adb__existing"
        assert dialog.selected_collection_id() == "arc__test"
        assert not hasattr(dialog, "_create_button")
        assert not hasattr(dialog, "_name_edit")
        assert not hasattr(dialog, "_raw_volume_combo")
        assert service.create_calls == []
    finally:
        dialog.close()


def test_extend_calls_service_with_selected_database_id(tmp_path: Path) -> None:
    dialog, _planner, service, _store = _dialog(tmp_path)
    reports: list[object] = []
    dialog.database_changed.connect(lambda report: reports.append(report))
    try:
        assert dialog.selected_database_id() == "adb__existing"
        dialog._confirm_extension = lambda _plan: True  # type: ignore[method-assign]

        dialog._extend_database()

        assert service.extend_calls[0]["database_id"] == "adb__existing"
        assert reports
        assert "Status: extended" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_extend_confirmation_cancel_prevents_service_call(tmp_path: Path) -> None:
    dialog, _planner, service, _store = _dialog(tmp_path)
    try:
        dialog._confirm_extension = lambda _plan: False  # type: ignore[method-assign]

        dialog._extend_database()

        assert service.extend_calls == []
        assert "canceled" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_no_resolved_components_disables_apply_and_does_not_call_service(
    tmp_path: Path,
) -> None:
    dialog, _planner, service, _store = _dialog(
        tmp_path,
        plan=_plan(resolved_components=(), blocked_items=(_blocker(),)),
    )
    try:
        assert dialog._extend_button.isEnabled() is False

        dialog._extend_database()

        assert service.create_calls == []
        assert service.extend_calls == []
        assert "No current artifacts can be used" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_duplicate_columns_disable_apply_and_are_displayed(tmp_path: Path) -> None:
    dialog, _planner, service, _store = _dialog(
        tmp_path,
        plan=_plan(duplicate_columns=("duplicate_column",)),
    )
    try:
        assert dialog._extend_button.isEnabled() is False
        assert "duplicate_column" in dialog._plan_text.toPlainText()

        dialog._extend_database()

        assert service.create_calls == []
        assert "duplicate planned database columns" in dialog._report_text.toPlainText()
    finally:
        dialog.close()


def test_recipe_collection_database_entry_point_and_boundaries() -> None:
    collection_source = (DATA_MANAGER / "artifact_recipe_collection_dialog.py").read_text(
        encoding="utf-8"
    )
    widget_source = (DATA_MANAGER / "tool_calculation_widget.py").read_text(
        encoding="utf-8"
    )
    database_list_source = (DATA_MANAGER / "analysis_database_list_widget.py").read_text(
        encoding="utf-8"
    )
    window_source = (ROOT / "src" / "leonardo" / "gui" / "windows" / "data_manager_window.py").read_text(
        encoding="utf-8"
    )
    dialog_source = (DATA_MANAGER / "recipe_collection_database_dialog.py").read_text(
        encoding="utf-8"
    )

    assert "database_create_extend_requested" not in collection_source
    assert '"Create/Extend Database..."' not in collection_source
    assert "RecipeCollectionDatabaseDialog" not in widget_source

    assert '"Extend Database from Collection..."' in database_list_source
    assert "collection_extend_requested = Signal(object)" in database_list_source
    assert "collection_extend_requested.emit(manifest)" in database_list_source
    assert "self._database_list.collection_extend_requested.connect(" in window_source
    assert "RecipeCollectionDatabaseDialog" in window_source

    assert "RecipeCollectionDatabasePlanner" in dialog_source
    assert "RecipeCollectionDatabaseService" in dialog_source
    assert "target_database" in dialog_source
    assert "Confirm Database Extension" in dialog_source
    assert "apply_data_manager_dialog_initial_width" in dialog_source
    assert "default_width=1240" in dialog_source
    assert "default_height=760" in dialog_source
    assert "self.resize(1240, 760)" not in dialog_source
    assert "extend_database_from_plan(" in dialog_source
    assert "create_database_from_plan(" not in dialog_source
    assert "Create Draft Database" not in dialog_source
    assert "New database name" not in dialog_source
    assert "AnalysisDatasetGeographyPolicy" not in dialog_source
    assert "SavedArtifactColumn" not in dialog_source
    assert "materialize_database" not in dialog_source
    assert "calculate_and_save" not in dialog_source
    assert "execute_update_plan" not in dialog_source
    assert "save_manifest(" not in dialog_source
