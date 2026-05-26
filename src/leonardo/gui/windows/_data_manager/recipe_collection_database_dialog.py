"""Dialog for creating or extending draft Analysis Databases from collections."""

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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.analysis_database_contracts import market_from_dict
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_recipe_collection_store import ArtifactRecipeCollection
from leonardo.data.historical.recipe_collection_database_planner import (
    RecipeCollectionDatabasePlan,
    RecipeCollectionDatabasePlanner,
)
from leonardo.data.historical.recipe_collection_database_service import (
    RecipeCollectionDatabaseApplyReport,
    RecipeCollectionDatabaseService,
)


class RecipeCollectionDatabaseDialog(QDialog):
    """Apply resolved recipe collection artifacts to draft database manifests.

    The dialog owns user intent and display state. Artifact resolution is
    delegated to ``RecipeCollectionDatabasePlanner`` and manifest creation or
    extension is delegated to ``RecipeCollectionDatabaseService``. The dialog
    does not calculate artifacts, execute recipes, materialize dataframes, or
    construct Analysis Database component objects directly.
    """

    database_changed = Signal(object)  # RecipeCollectionDatabaseApplyReport
    status_message = Signal(str)

    def __init__(
        self,
        *,
        historical_root: Path,
        collection: ArtifactRecipeCollection,
        planner: RecipeCollectionDatabasePlanner | None = None,
        service: RecipeCollectionDatabaseService | None = None,
        database_store: AnalysisDatabaseStore | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._collection = collection
        self._planner = planner or RecipeCollectionDatabasePlanner(
            historical_root=self._historical_root,
        )
        self._service = service or RecipeCollectionDatabaseService(
            historical_root=self._historical_root,
        )
        self._database_store = database_store or AnalysisDatabaseStore(
            historical_root=self._historical_root,
        )
        self._current_plan: RecipeCollectionDatabasePlan | None = None

        self.setWindowTitle("Create or Extend Analysis Database")
        self.resize(1240, 760)
        self.setMinimumSize(1080, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        context = QLabel(
            (
                "Resolve current saved artifacts from the selected recipe "
                "collection, then create or extend a draft Analysis Database "
                "manifest. This does not calculate artifacts or build dataframe.csv."
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

        self._collection_label = QLabel(self._collection_summary_text(), plan_group)
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

        action_group = QGroupBox("Draft Database Action", self)
        action_layout = QVBoxLayout(action_group)
        action_layout.setContentsMargins(8, 12, 8, 8)
        action_layout.setSpacing(8)

        create_form = QFormLayout()
        create_form.setSpacing(8)
        action_layout.addLayout(create_form)

        self._name_edit = QLineEdit(action_group)
        self._name_edit.setPlaceholderText("Database display name")
        self._name_edit.setText(_default_database_name(collection))
        self._name_edit.textChanged.connect(lambda *_: self._refresh_action_buttons())
        create_form.addRow("New database name", self._name_edit)

        self._description_edit = QPlainTextEdit(action_group)
        self._description_edit.setPlaceholderText("Optional database description.")
        self._description_edit.setFixedHeight(72)
        create_form.addRow("Description", self._description_edit)

        self._raw_volume_combo = QComboBox(action_group)
        self._raw_volume_combo.addItem("Auto", "auto")
        self._raw_volume_combo.addItem("Include", "include")
        self._raw_volume_combo.addItem("Exclude", "exclude")
        create_form.addRow("Raw OHLCV volume", self._raw_volume_combo)

        self._create_button = QPushButton("Create Draft Database", action_group)
        self._create_button.clicked.connect(self._create_database)
        action_layout.addWidget(self._create_button)

        action_layout.addSpacing(8)

        self._database_combo = QComboBox(action_group)
        self._database_combo.currentIndexChanged.connect(
            lambda *_: self._refresh_action_buttons()
        )
        create_form.addRow("Existing database", self._database_combo)

        self._extend_button = QPushButton("Extend Database", action_group)
        self._extend_button.clicked.connect(self._extend_database)
        action_layout.addWidget(self._extend_button)

        self._report_text = QPlainTextEdit(action_group)
        self._report_text.setReadOnly(True)
        self._report_text.setPlaceholderText("Create/extend report appears here.")
        action_layout.addWidget(self._report_text, 1)

        body.addWidget(action_group, 4)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self.refresh_plan()

    def refresh_plan(self) -> None:
        """Resolve the selected collection through the C2 planner."""

        try:
            plan = self._planner.plan_collection_components(
                self._collection,
                include_geography_report=True,
            )
        except Exception as exc:
            self._current_plan = None
            self._fill_components(())
            self._fill_blocked_items(())
            self._plan_text.setPlainText(f"Failed to resolve recipe collection: {exc!r}")
            self._database_combo.clear()
            self._refresh_action_buttons()
            return

        self._current_plan = plan
        self._fill_components(plan.resolved_components)
        self._fill_blocked_items(plan.blocked_items)
        self._plan_text.setPlainText(_plan_text_for(plan))
        self._load_database_choices(plan)
        self._report_text.clear()
        self._refresh_action_buttons()
        self.status_message.emit(
            f"Recipe collection database plan ready: {plan.collection_display_name}"
        )

    def selected_database_id(self) -> str:
        """Return the selected Analysis Database id for extension."""

        value = self._database_combo.currentData()
        return str(value or "").strip()

    def _create_database(self) -> None:
        plan = self._current_plan
        if plan is None:
            self._set_report_text("Resolve the recipe collection before creating a database.")
            return
        if not self._plan_can_apply(plan):
            self._set_report_text(_blocked_apply_text(plan))
            return

        display_name = self._name_edit.text().strip()
        if not display_name:
            self._set_report_text("Enter a database display name before creating a draft.")
            self._refresh_action_buttons()
            return

        try:
            report = self._service.create_database_from_plan(
                plan,
                display_name=display_name,
                description=self._description_edit.toPlainText().strip(),
                include_raw_volume=self._include_raw_volume_value(),
            )
        except Exception as exc:
            message = f"Failed to create draft database: {exc!r}"
            self._set_report_text(message)
            self.status_message.emit(message)
            QMessageBox.critical(self, "Analysis Database Create Failed", message)
            return

        self._handle_apply_report(report)

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

    def _handle_apply_report(self, report: RecipeCollectionDatabaseApplyReport) -> None:
        self._set_report_text(_apply_report_text(report))
        status = str(getattr(report, "status", ""))
        display_name = str(getattr(report, "display_name", "") or "analysis database")
        self.status_message.emit(f"Recipe collection database {status}: {display_name}")
        if status in {"created", "extended"}:
            self.database_changed.emit(report)
            self._load_database_choices(self._current_plan)

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

    def _load_database_choices(self, plan: RecipeCollectionDatabasePlan | None) -> None:
        selected_id = self.selected_database_id()
        self._database_combo.blockSignals(True)
        self._database_combo.clear()

        market = _market_from_plan(plan)
        if market is None:
            self._database_combo.addItem("Plan market unavailable", "")
            self._database_combo.blockSignals(False)
            return

        try:
            summaries = self._database_store.list_databases(market=market)
        except Exception as exc:
            self._database_combo.addItem(f"Failed to load databases: {exc!r}", "")
            self._database_combo.blockSignals(False)
            return

        if not summaries:
            self._database_combo.addItem("No existing Analysis Databases found", "")
            self._database_combo.blockSignals(False)
            return

        selected_row = 0
        for row, summary in enumerate(summaries):
            database_id = str(getattr(summary, "database_id", "") or "")
            self._database_combo.addItem(_database_summary_label(summary), database_id)
            if database_id == selected_id:
                selected_row = row
        self._database_combo.setCurrentIndex(selected_row)
        self._database_combo.blockSignals(False)

    def _refresh_action_buttons(self) -> None:
        plan = self._current_plan
        can_apply = bool(plan is not None and self._plan_can_apply(plan))
        has_name = bool(self._name_edit.text().strip())
        has_database = bool(self.selected_database_id())
        self._create_button.setEnabled(can_apply and has_name)
        self._extend_button.setEnabled(can_apply and has_database)

    def _plan_can_apply(self, plan: RecipeCollectionDatabasePlan) -> bool:
        return bool(plan.resolved_components) and not bool(plan.duplicate_columns)

    def _include_raw_volume_value(self) -> bool | None:
        value = str(self._raw_volume_combo.currentData() or "auto")
        if value == "include":
            return True
        if value == "exclude":
            return False
        return None

    def _collection_summary_text(self) -> str:
        market = getattr(self._collection, "market", None)
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
                f"Collection: {getattr(self._collection, 'display_name', '(unnamed)')}",
                f"Collection ID: {getattr(self._collection, 'collection_id', '(unknown)')}",
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


def _market_from_plan(plan: RecipeCollectionDatabasePlan | None) -> object | None:
    if plan is None or plan.market is None:
        return None
    try:
        return market_from_dict(dict(plan.market))
    except Exception:
        return None


def _database_summary_label(summary: object) -> str:
    row_count = getattr(summary, "row_count", None)
    rows = "draft" if row_count is None else f"{row_count} rows"
    return (
        f"{getattr(summary, 'display_name', '(unnamed)')} - "
        f"{getattr(summary, 'status', 'unknown')} - "
        f"{getattr(summary, 'feature_count', 0)} feature(s) - {rows}"
    )


def _default_database_name(collection: object) -> str:
    market = getattr(collection, "market", None)
    prefix = ""
    if market is not None:
        prefix = f"{market.symbol}_{market.timeframe}_"
    return f"{prefix}{_safe_token(getattr(collection, 'display_name', 'collection_database'))}_database"


def _safe_token(value: object) -> str:
    text = str(value or "").strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    token = "_".join(part for part in "".join(chars).split("_") if part)
    return token or "collection"


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
                "Blocked items are excluded. Use Plan Updates from the recipe collection controls to update missing or stale artifacts.",
            ]
        )
    if not plan.resolved_components:
        lines.extend(
            [
                "",
                "No current artifacts can be used. Run Plan Updates or recovery before creating database components.",
            ]
        )
    return "\n".join(lines)


def _blocked_apply_text(plan: RecipeCollectionDatabasePlan) -> str:
    if plan.duplicate_columns:
        return "Resolve duplicate planned database columns before creating or extending a database."
    if not plan.resolved_components:
        return "No current artifacts can be used. Run Plan Updates or recovery first."
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
