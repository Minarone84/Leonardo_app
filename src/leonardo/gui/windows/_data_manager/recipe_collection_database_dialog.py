"""Dialog for extending existing Analysis Databases from recipe collections."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest
from leonardo.data.historical.artifact_recipe_collection_store import ArtifactRecipeCollection
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.recipe_collection_database_planner import (
    RecipeCollectionDatabasePlan,
    RecipeCollectionDatabasePlanner,
)
from leonardo.data.historical.recipe_collection_database_service import (
    RecipeCollectionDatabaseApplyReport,
    RecipeCollectionDatabaseService,
)


class RecipeCollectionDatabaseDialog(QDialog):
    """Extend an existing Analysis Database from resolved collection artifacts.

    The dialog owns user intent and display state. Artifact resolution is
    delegated to ``RecipeCollectionDatabasePlanner`` and manifest extension is
    delegated to ``RecipeCollectionDatabaseService``. The dialog does not create
    databases, calculate artifacts, execute recipes, materialize dataframes, or
    construct Analysis Database component objects directly.
    """

    database_changed = Signal(object)  # RecipeCollectionDatabaseApplyReport
    status_message = Signal(str)

    def __init__(
        self,
        *,
        historical_root: Path,
        target_database: AnalysisDatabaseManifest,
        collection: ArtifactRecipeCollection | None = None,
        planner: RecipeCollectionDatabasePlanner | None = None,
        service: RecipeCollectionDatabaseService | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._target_database = target_database
        self._current_collection: ArtifactRecipeCollection | None = None
        self._planner = planner or RecipeCollectionDatabasePlanner(
            historical_root=self._historical_root,
        )
        self._service = service or RecipeCollectionDatabaseService(
            historical_root=self._historical_root,
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root,
        )
        self._current_plan: RecipeCollectionDatabasePlan | None = None

        self.setWindowTitle("Extend Analysis Database from Collection")
        self.resize(1240, 760)
        self.setMinimumSize(1080, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        context = QLabel(
            (
                "Select a saved recipe collection, resolve its current saved "
                "artifacts, then extend the selected Analysis Database. This "
                "does not create a database, calculate artifacts, execute "
                "recipes, or build dataframe.csv."
            ),
            self,
        )
        context.setWordWrap(True)
        root.addWidget(context)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        plan_group = QGroupBox("Collection Resolution Plan", self)
        plan_layout = QVBoxLayout(plan_group)
        plan_layout.setContentsMargins(8, 12, 8, 8)
        plan_layout.setSpacing(8)

        self._target_label = QLabel(self._target_database_text(), plan_group)
        self._target_label.setWordWrap(True)
        plan_layout.addWidget(self._target_label)

        selection_form = QFormLayout()
        selection_form.setSpacing(8)
        plan_layout.addLayout(selection_form)

        self._collection_combo = QComboBox(plan_group)
        self._collection_combo.currentIndexChanged.connect(lambda *_: self.refresh_plan())
        selection_form.addRow("Recipe collection", self._collection_combo)

        self._collection_label = QLabel("Select a recipe collection to resolve.", plan_group)
        self._collection_label.setWordWrap(True)
        plan_layout.addWidget(self._collection_label)

        self._refresh_plan_button = QPushButton("Refresh Plan", plan_group)
        self._refresh_plan_button.clicked.connect(self.refresh_plan)
        plan_layout.addWidget(self._refresh_plan_button, 0, Qt.AlignmentFlag.AlignLeft)

        self._component_table = QTableWidget(0, 5, plan_group)
        self._component_table.setHorizontalHeaderLabels(
            ["Tool", "Instance", "Artifact", "Columns", "Status"]
        )
        self._component_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._component_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._component_table.setWordWrap(True)
        component_header = self._component_table.horizontalHeader()
        component_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        component_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        component_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        component_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        component_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        plan_layout.addWidget(self._component_table, 3)

        self._blocked_table = QTableWidget(0, 5, plan_group)
        self._blocked_table.setHorizontalHeaderLabels(
            ["Recipe", "Tool", "Status", "Reason", "Message"]
        )
        self._blocked_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._blocked_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._blocked_table.setWordWrap(True)
        blocked_header = self._blocked_table.horizontalHeader()
        blocked_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        blocked_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        blocked_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        blocked_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        blocked_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        plan_layout.addWidget(self._blocked_table, 2)

        self._plan_text = QPlainTextEdit(plan_group)
        self._plan_text.setReadOnly(True)
        self._plan_text.setMinimumHeight(140)
        plan_layout.addWidget(self._plan_text, 1)

        body.addWidget(plan_group, 7)

        action_group = QGroupBox("Database Extension", self)
        action_layout = QVBoxLayout(action_group)
        action_layout.setContentsMargins(8, 12, 8, 8)
        action_layout.setSpacing(8)

        self._extend_button = QPushButton("Extend Database", action_group)
        self._extend_button.clicked.connect(self._extend_database)
        action_layout.addWidget(self._extend_button)

        self._report_text = QPlainTextEdit(action_group)
        self._report_text.setReadOnly(True)
        self._report_text.setPlaceholderText("Extension report appears here.")
        action_layout.addWidget(self._report_text, 1)

        body.addWidget(action_group, 4)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._load_collection_choices(
            preselect_collection_id="" if collection is None else collection.collection_id
        )
        if collection is not None and not self.selected_collection_id():
            self._collection_combo.addItem(
                _collection_summary_label(collection),
                collection.collection_id,
            )
            self._collection_combo.setCurrentIndex(self._collection_combo.count() - 1)
        self.refresh_plan()

    def refresh_plan(self) -> None:
        """Resolve the selected collection through the C2 planner."""

        collection = self._selected_collection()
        self._current_collection = collection
        if collection is None:
            self._current_plan = None
            self._collection_label.setText("Select a recipe collection to resolve.")
            self._fill_components(())
            self._fill_blocked_items(())
            self._plan_text.clear()
            self._report_text.clear()
            self._refresh_action_buttons()
            return

        self._collection_label.setText(self._collection_summary_text(collection))
        try:
            plan = self._planner.plan_collection_components(
                collection,
                include_geography_report=True,
            )
        except Exception as exc:
            self._current_plan = None
            self._fill_components(())
            self._fill_blocked_items(())
            self._plan_text.setPlainText(f"Failed to resolve recipe collection: {exc!r}")
            self._refresh_action_buttons()
            return

        self._current_plan = plan
        self._fill_components(plan.resolved_components)
        self._fill_blocked_items(plan.blocked_items)
        self._plan_text.setPlainText(_plan_text_for(plan))
        self._report_text.clear()
        self._refresh_action_buttons()
        self.status_message.emit(
            f"Recipe collection database plan ready: {plan.collection_display_name}"
        )

    def selected_database_id(self) -> str:
        """Return the selected Analysis Database id for extension."""

        return str(getattr(self._target_database, "database_id", "") or "").strip()

    def selected_collection_id(self) -> str:
        """Return the currently selected recipe collection id."""

        value = self._collection_combo.currentData()
        return str(value or "").strip()

    def _extend_database(self) -> None:
        plan = self._current_plan
        if plan is None:
            self._set_report_text("Resolve the recipe collection before extending a database.")
            return
        if not self._plan_can_apply(plan):
            self._set_report_text(_blocked_apply_text(plan))
            return

        database_id = self.selected_database_id()
        if not database_id:
            self._set_report_text("Select an existing Analysis Database before extending.")
            self._refresh_action_buttons()
            return

        if not self._confirm_extension(plan):
            self._set_report_text("Database extension canceled.")
            return

        try:
            report = self._service.extend_database_from_plan(
                plan,
                database_id=database_id,
            )
        except Exception as exc:
            message = f"Failed to extend database: {exc!r}"
            self._set_report_text(message)
            self.status_message.emit(message)
            QMessageBox.critical(self, "Analysis Database Extend Failed", message)
            return

        self._handle_apply_report(report)

    def _confirm_extension(self, plan: RecipeCollectionDatabasePlan) -> bool:
        collection = self._current_collection
        collection_name = (
            "(unknown collection)"
            if collection is None
            else str(getattr(collection, "display_name", "") or collection.collection_id)
        )
        warnings = len(tuple(plan.warnings or ()))
        if plan.geography_report:
            warnings += len(tuple(plan.geography_report.get("warnings", ()) or ()))

        message = "\n".join(
            [
                f"Extend Analysis Database '{self._target_database.display_name}'?",
                "",
                f"Database ID: {self._target_database.database_id}",
                f"Recipe collection: {collection_name}",
                f"Components to add: {len(plan.resolved_components)}",
                f"Warnings: {warnings}",
                "",
                "This updates the database draft/components only.",
                "It does not materialize dataframe.csv.",
            ]
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Confirm Database Extension")
        box.setText(message)
        extend_button = box.addButton("Extend", QMessageBox.ButtonRole.AcceptRole)
        cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is extend_button

    def _handle_apply_report(self, report: RecipeCollectionDatabaseApplyReport) -> None:
        self._set_report_text(_apply_report_text(report))
        status = str(getattr(report, "status", ""))
        display_name = str(getattr(report, "display_name", "") or "analysis database")
        self.status_message.emit(f"Recipe collection database {status}: {display_name}")
        if status == "extended":
            self.database_changed.emit(report)

    def _fill_components(self, components: Iterable[object]) -> None:
        self._component_table.setRowCount(0)
        for row, component in enumerate(tuple(components)):
            self._component_table.insertRow(row)
            column_names = [
                _dict_value(column, "db_column_name")
                or _dict_value(column, "source_column_name")
                for column in getattr(component, "column_previews", ()) or ()
            ]
            values = (
                f"{getattr(component, 'tool_type', '')}/{getattr(component, 'tool_key', '')}",
                str(getattr(component, "instance_key", "") or ""),
                str(
                    getattr(component, "artifact_relpath", "")
                    or getattr(component, "artifact_filename", "")
                    or ""
                ),
                ", ".join(name for name in column_names if name) or "(none)",
                "current",
            )
            for column, value in enumerate(values):
                self._component_table.setItem(row, column, _readonly_item(value))
        self._component_table.resizeRowsToContents()

    def _fill_blocked_items(self, items: Iterable[object]) -> None:
        self._blocked_table.setRowCount(0)
        for row, item in enumerate(tuple(items)):
            self._blocked_table.insertRow(row)
            values = (
                "" if getattr(item, "recipe_index", None) is None else str(getattr(item, "recipe_index")),
                str(getattr(item, "tool_key", "") or ""),
                str(getattr(item, "status", "") or ""),
                str(getattr(item, "reason", "") or ""),
                str(getattr(item, "message", "") or ""),
            )
            for column, value in enumerate(values):
                self._blocked_table.setItem(row, column, _readonly_item(value))
        self._blocked_table.resizeRowsToContents()

    def _load_collection_choices(self, *, preselect_collection_id: str = "") -> None:
        selected_id = str(preselect_collection_id or self.selected_collection_id()).strip()
        self._collection_combo.blockSignals(True)
        self._collection_combo.clear()
        try:
            summaries = self._collection_store.list_collections(
                market=self._target_database.market,
            )
        except Exception as exc:
            self._collection_combo.addItem(f"Failed to load collections: {exc!r}", "")
            self._collection_combo.blockSignals(False)
            return

        if not summaries:
            self._collection_combo.addItem("No saved recipe collections found", "")
            self._collection_combo.blockSignals(False)
            return

        selected_row = 0
        for row, summary in enumerate(summaries):
            collection_id = str(getattr(summary, "collection_id", "") or "")
            self._collection_combo.addItem(_collection_summary_label(summary), collection_id)
            if collection_id == selected_id:
                selected_row = row
        self._collection_combo.setCurrentIndex(selected_row)
        self._collection_combo.blockSignals(False)

    def _selected_collection(self) -> ArtifactRecipeCollection | None:
        collection_id = self.selected_collection_id()
        if not collection_id:
            return None
        try:
            return self._collection_store.load_collection(
                market=self._target_database.market,
                collection_id=collection_id,
            )
        except Exception as exc:
            self._set_report_text(f"Failed to load recipe collection: {exc!r}")
            return None

    def _refresh_action_buttons(self) -> None:
        plan = self._current_plan
        can_apply = bool(plan is not None and self._plan_can_apply(plan))
        self._extend_button.setEnabled(can_apply and bool(self.selected_database_id()))

    def _plan_can_apply(self, plan: RecipeCollectionDatabasePlan) -> bool:
        return (
            bool(plan.resolved_components)
            and not bool(plan.duplicate_columns)
            and not bool(plan.blocked_items)
        )

    def _target_database_text(self) -> str:
        market = getattr(self._target_database, "market", None)
        market_text = (
            "Unknown dataset"
            if market is None
            else (
                f"{market.exchange} / {market.market_type} / "
                f"{market.symbol} / {market.timeframe}"
            )
        )
        return "\n".join(
            [
                f"Target database: {self._target_database.display_name}",
                f"Database ID: {self._target_database.database_id}",
                f"Status: {self._target_database.status}",
                f"Dataset: {market_text}",
            ]
        )

    def _collection_summary_text(self, collection: ArtifactRecipeCollection) -> str:
        market = getattr(collection, "market", None)
        market_text = (
            "Unknown dataset"
            if market is None
            else (
                f"{market.exchange} / {market.market_type} / "
                f"{market.symbol} / {market.timeframe}"
            )
        )
        return "\n".join(
            [
                f"Collection: {getattr(collection, 'display_name', '(unnamed)')}",
                f"Collection ID: {getattr(collection, 'collection_id', '(unknown)')}",
                f"Dataset: {market_text}",
            ]
        )

    def _set_report_text(self, text: str) -> None:
        self._report_text.setPlainText(text)


def _readonly_item(value: object) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value or ""))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


def _dict_value(data: object, key: str) -> str:
    if isinstance(data, Mapping):
        return str(data.get(key, "") or "")
    return str(getattr(data, key, "") or "")


def _collection_summary_label(summary: object) -> str:
    recipe_count = getattr(summary, "recipe_count", None)
    if recipe_count is None and hasattr(summary, "recipe_snapshots"):
        recipe_count = len(tuple(getattr(summary, "recipe_snapshots", ()) or ()))
    recipes = "unknown recipe count" if recipe_count is None else f"{recipe_count} recipe(s)"
    return (
        f"{getattr(summary, 'display_name', '(unnamed)')} - "
        f"{getattr(summary, 'collection_id', '(unknown)')} - {recipes}"
    )


def _plan_text_for(plan: RecipeCollectionDatabasePlan) -> str:
    lines = [
        f"Plan ID: {plan.plan_id}",
        f"Collection: {plan.collection_display_name}",
        f"Collection ID: {plan.collection_id}",
        f"Source database ID: {plan.source_database_id or '(none)'}",
        "",
        "Summary:",
    ]
    for key, value in sorted(plan.summary.items()):
        lines.append(f"- {key}: {value}")

    if plan.duplicate_columns:
        lines.extend(["", "Duplicate planned database columns:"])
        lines.extend(f"- {name}" for name in plan.duplicate_columns)

    if plan.warnings:
        lines.extend(["", "Warnings:"])
        for warning in plan.warnings:
            lines.append(
                f"- {getattr(warning, 'code', 'warning')}: {getattr(warning, 'message', '')}"
            )

    lines.extend(["", "Geography:", _geography_text(plan.geography_report)])
    if plan.blocked_items and plan.resolved_components:
        lines.extend(
            [
                "",
                "Blocked items must be resolved before extending the selected database. Use Plan Updates from the recipe collection controls to update missing or stale artifacts.",
            ]
        )
    if not plan.resolved_components:
        lines.extend(
            [
                "",
                "No current artifacts can be used. Run Plan Updates or recovery before extending database components.",
            ]
        )
    return "\n".join(lines)


def _blocked_apply_text(plan: RecipeCollectionDatabasePlan) -> str:
    if plan.duplicate_columns:
        return "Resolve duplicate planned database columns before extending a database."
    if not plan.resolved_components:
        return "No current artifacts can be used. Run Plan Updates or recovery first."
    if plan.blocked_items:
        return "Resolve blocked recipe collection plan items before extending a database."
    return "The current plan cannot be applied."


def _apply_report_text(report: RecipeCollectionDatabaseApplyReport) -> str:
    lines = [
        f"Report ID: {getattr(report, 'report_id', '')}",
        f"Operation: {getattr(report, 'operation', '')}",
        f"Status: {getattr(report, 'status', '')}",
        f"Database ID: {getattr(report, 'database_id', None) or '(none)'}",
        f"Display name: {getattr(report, 'display_name', None) or '(none)'}",
        f"Added sources: {getattr(report, 'added_source_count', 0)}",
        f"Added columns: {getattr(report, 'added_column_count', 0)}",
        f"Skipped components: {getattr(report, 'skipped_component_count', 0)}",
    ]

    blockers = tuple(getattr(report, "blockers", ()) or ())
    if blockers:
        lines.extend(["", "Blockers:"])
        lines.extend(
            f"- {getattr(blocker, 'code', 'blocked')}: {getattr(blocker, 'message', '')}"
            for blocker in blockers
        )

    warnings = tuple(getattr(report, "warnings", ()) or ())
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(
            f"- {getattr(warning, 'code', 'warning')}: {getattr(warning, 'message', '')}"
            for warning in warnings
        )

    lines.extend(["", "Geography:", _geography_text(getattr(report, "geography_report", None))])
    return "\n".join(lines)


def _geography_text(report: Mapping[str, Any] | None) -> str:
    if not report:
        return "Geography report unavailable."

    complete = bool(report.get("complete"))
    present = tuple(str(item) for item in report.get("present_keys", ()) or ())
    missing = tuple(str(item) for item in report.get("missing_keys", ()) or ())
    lines = [
        f"Complete: {'yes' if complete else 'no'}",
        f"Present: {', '.join(present) if present else '(none)'}",
        f"Missing: {', '.join(missing) if missing else '(none)'}",
    ]
    warnings = tuple(report.get("warnings", ()) or ())
    if warnings:
        lines.append("Warnings:")
        for warning in warnings:
            if isinstance(warning, Mapping):
                code = str(warning.get("code", "warning"))
                message = str(warning.get("message", ""))
            else:
                code = str(getattr(warning, "code", "warning"))
                message = str(getattr(warning, "message", ""))
            lines.append(f"- {code}: {message}")
    return "\n".join(lines)
