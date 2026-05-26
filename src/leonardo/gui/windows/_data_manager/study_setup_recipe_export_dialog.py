"""Dialog for persisting recipe definitions from saved chart Study Environments."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.chart_presets.study_setup_store import (
    ChartStudySetup,
    ChartStudySetupStore,
)
from leonardo.data.historical.artifact_recipe_store import market_to_dict
from leonardo.data.historical.study_setup_recipe_export_planner import (
    STUDY_EXPORT_STATUS_EXPORTABLE,
    StudyRecipeExportCandidate,
    StudySetupRecipeExportPersistenceReport,
    StudySetupRecipeExportPersistenceService,
    StudySetupRecipeExportPlan,
    StudySetupRecipeExportPlanner,
)
from leonardo.data.naming import MarketId


class StudySetupRecipeExportDialog(QDialog):
    """Data Manager dialog for exporting saved Study Environments to recipe definitions.

    The dialog owns user selection and report display only. Study classification,
    recipe payload construction, and persistence remain delegated to the B1/B2
    data-layer services.
    """

    recipes_persisted = Signal(object)  # StudySetupRecipeExportPersistenceReport
    status_message = Signal(str)

    def __init__(
        self,
        *,
        historical_root: Path,
        study_setup_root: Path,
        target_market: MarketId | None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._study_setup_root = Path(study_setup_root)
        self._target_market = target_market
        self._setup_store = ChartStudySetupStore(self._study_setup_root)
        self._planner = StudySetupRecipeExportPlanner(
            historical_root=self._historical_root,
        )
        self._persister = StudySetupRecipeExportPersistenceService(
            historical_root=self._historical_root,
        )
        self._current_plan: StudySetupRecipeExportPlan | None = None

        self.setWindowTitle("Create Recipes from Study Environment")
        self.resize(1220, 740)
        self.setMinimumSize(1080, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        context = QLabel(
            (
                "Select a saved Study Environment, preview exportability, then save "
                "recipe definitions. This does not calculate artifacts."
            ),
            self,
        )
        context.setWordWrap(True)
        root.addWidget(context)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        setup_group = QGroupBox("Saved Study Environments", self)
        setup_layout = QVBoxLayout(setup_group)
        setup_layout.setContentsMargins(8, 12, 8, 8)
        setup_layout.setSpacing(8)

        self._setup_list = QListWidget(setup_group)
        self._setup_list.setMinimumWidth(360)
        self._setup_list.setWordWrap(True)
        self._setup_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._setup_list.currentItemChanged.connect(lambda *_: self._refresh_plan())
        setup_layout.addWidget(self._setup_list, 1)

        self._refresh_setups_button = QPushButton("Refresh Environments", setup_group)
        self._refresh_setups_button.clicked.connect(self.refresh_setups)
        setup_layout.addWidget(self._refresh_setups_button)

        body.addWidget(setup_group, 3)

        detail_group = QGroupBox("Export Plan", self)
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 12, 8, 8)
        detail_layout.setSpacing(8)

        self._setup_summary = QLabel("Select a saved Study Environment.", detail_group)
        self._setup_summary.setWordWrap(True)
        detail_layout.addWidget(self._setup_summary)

        option_row = QHBoxLayout()
        option_row.setSpacing(8)
        detail_layout.addLayout(option_row)

        self._important_only_check = QCheckBox("Important studies only", detail_group)
        self._important_only_check.stateChanged.connect(lambda *_: self._refresh_plan())
        option_row.addWidget(self._important_only_check)

        self._refresh_plan_button = QPushButton("Refresh Plan", detail_group)
        self._refresh_plan_button.clicked.connect(self._refresh_plan)
        option_row.addWidget(self._refresh_plan_button)
        option_row.addStretch(1)

        self._candidate_table = QTableWidget(0, 7, detail_group)
        self._candidate_table.setHorizontalHeaderLabels(
            [
                "Select",
                "Study",
                "Tool",
                "Role",
                "Important",
                "Status",
                "Reason / Warnings",
            ]
        )
        self._candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._candidate_table.setWordWrap(True)
        self._candidate_table.itemChanged.connect(lambda _item: self._refresh_buttons())
        header = self._candidate_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        detail_layout.addWidget(self._candidate_table, 3)

        self._plan_text = QPlainTextEdit(detail_group)
        self._plan_text.setReadOnly(True)
        self._plan_text.setMinimumHeight(150)
        detail_layout.addWidget(self._plan_text, 1)

        collection_row = QHBoxLayout()
        collection_row.setSpacing(8)
        detail_layout.addLayout(collection_row)

        self._save_collection_check = QCheckBox("Save as recipe collection", detail_group)
        self._save_collection_check.stateChanged.connect(
            lambda *_: self._refresh_buttons()
        )
        collection_row.addWidget(self._save_collection_check)

        self._collection_name_edit = QLineEdit(detail_group)
        self._collection_name_edit.setPlaceholderText("Collection display name")
        collection_row.addWidget(self._collection_name_edit, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        detail_layout.addLayout(action_row)

        self._save_selected_button = QPushButton("Save Selected Recipes", detail_group)
        self._save_selected_button.clicked.connect(self._save_selected)
        action_row.addWidget(self._save_selected_button)

        self._save_all_button = QPushButton("Save All Exportable", detail_group)
        self._save_all_button.clicked.connect(self._save_all_exportable)
        action_row.addWidget(self._save_all_button)

        body.addWidget(detail_group, 7)

        self._report_text = QPlainTextEdit(self)
        self._report_text.setReadOnly(True)
        self._report_text.setMaximumHeight(150)
        self._report_text.setPlaceholderText("Persistence report appears here.")
        root.addWidget(self._report_text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self.refresh_setups()

    def refresh_setups(self) -> None:
        """Reload saved Study Environments from the configured preset store."""

        selected_setup_id = self.selected_setup_id()
        self._setup_list.blockSignals(True)
        self._setup_list.clear()

        summaries = self._setup_store.list_summaries()
        selected_row = 0
        for row, summary in enumerate(summaries):
            label = (
                f"{summary.display_name}\n"
                f"{_market_text(summary.created_from)} - "
                f"{summary.study_count} study/studies"
            )
            item = QListWidgetItem(label, self._setup_list)
            item.setData(Qt.ItemDataRole.UserRole, summary.setup_id)
            item.setToolTip(
                "\n".join(
                    [
                        f"Environment ID: {summary.setup_id}",
                        f"Description: {summary.description or '(none)'}",
                        f"Path: {summary.path}",
                    ]
                )
            )
            if summary.setup_id == selected_setup_id:
                selected_row = row

        if summaries:
            self._setup_list.setCurrentRow(selected_row)

        self._setup_list.blockSignals(False)
        self._refresh_plan()
        self.status_message.emit(f"Loaded {len(summaries)} saved Study Environment(s)")

    def selected_setup_id(self) -> str:
        """Return the currently highlighted Study Environment id."""

        item = self._setup_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def checked_candidate_ids(self) -> tuple[str, ...]:
        """Return export candidate ids checked for persistence."""

        candidate_ids: list[str] = []
        for row in range(self._candidate_table.rowCount()):
            item = self._candidate_table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            candidate_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if candidate_id:
                candidate_ids.append(candidate_id)
        return tuple(candidate_ids)

    def _selected_setup(self) -> ChartStudySetup | None:
        setup_id = self.selected_setup_id()
        if not setup_id:
            return None
        try:
            return self._setup_store.load_setup(setup_id)
        except Exception as exc:
            self._set_report_text(f"Failed to load Study Environment: {exc!r}")
            return None

    def _refresh_plan(self) -> None:
        setup = self._selected_setup()
        if setup is None:
            self._current_plan = None
            self._setup_summary.setText("Select a saved Study Environment.")
            self._fill_candidates(())
            self._plan_text.setPlainText("")
            self._refresh_buttons()
            return

        target_market = self._target_market_for_setup(setup)
        try:
            plan = self._planner.plan_study_setup_export(
                setup,
                important_only=self._important_only_check.isChecked(),
                target_market=target_market,
            )
        except Exception as exc:
            self._current_plan = None
            self._setup_summary.setText(self._setup_summary_text(setup))
            self._fill_candidates(())
            self._plan_text.setPlainText(f"Failed to build export plan: {exc!r}")
            self._refresh_buttons()
            return

        self._current_plan = plan
        self._setup_summary.setText(self._setup_summary_text(setup))
        self._fill_candidates(plan.candidates)
        self._plan_text.setPlainText(_plan_text_for(plan))
        self._report_text.clear()
        self._refresh_collection_defaults(plan)
        self._refresh_buttons()
        self.status_message.emit(f"Study Environment export plan ready: {setup.display_name}")

    def _target_market_for_setup(self, setup: ChartStudySetup) -> dict[str, str] | None:
        if _has_complete_market(setup.created_from):
            return None
        if self._target_market is None:
            return None
        return market_to_dict(self._target_market)

    def _fill_candidates(
        self,
        candidates: tuple[StudyRecipeExportCandidate, ...],
    ) -> None:
        self._candidate_table.blockSignals(True)
        self._candidate_table.setRowCount(0)

        for row, candidate in enumerate(candidates):
            self._candidate_table.insertRow(row)
            selectable = (
                candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
                and candidate.recipe_payload is not None
            )

            select_item = QTableWidgetItem("")
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if selectable:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                select_item.setCheckState(Qt.CheckState.Checked)
            else:
                select_item.setCheckState(Qt.CheckState.Unchecked)
            select_item.setFlags(flags)
            select_item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            self._candidate_table.setItem(row, 0, select_item)

            values = (
                candidate.study_display_name,
                f"{candidate.family}/{candidate.tool_key}",
                candidate.dataset_role,
                "yes" if candidate.important else "no",
                candidate.status,
                _candidate_reason_text(candidate),
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self._candidate_table.setItem(row, column, item)

        self._candidate_table.resizeRowsToContents()
        self._candidate_table.blockSignals(False)

    def _refresh_collection_defaults(self, plan: StudySetupRecipeExportPlan) -> None:
        draft = plan.collection_draft
        collection_available = draft is not None
        self._save_collection_check.setEnabled(collection_available)
        if not collection_available:
            self._save_collection_check.setChecked(False)
            self._collection_name_edit.setText("")
        elif not self._collection_name_edit.text().strip():
            self._collection_name_edit.setText(draft.display_name)
        self._collection_name_edit.setEnabled(
            collection_available and self._save_collection_check.isChecked()
        )

    def _refresh_buttons(self) -> None:
        plan = self._current_plan
        has_plan = plan is not None
        checked_count = len(self.checked_candidate_ids()) if has_plan else 0
        exportable_count = len(self._exportable_candidate_ids()) if has_plan else 0
        collection_available = bool(has_plan and plan.collection_draft is not None)

        self._save_selected_button.setEnabled(checked_count > 0)
        self._save_all_button.setEnabled(exportable_count > 0)
        self._save_collection_check.setEnabled(collection_available)
        self._collection_name_edit.setEnabled(
            collection_available and self._save_collection_check.isChecked()
        )

    def _exportable_candidate_ids(self) -> tuple[str, ...]:
        plan = self._current_plan
        if plan is None:
            return ()
        return tuple(
            candidate.candidate_id
            for candidate in plan.candidates
            if candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
            and candidate.recipe_payload is not None
        )

    def _save_selected(self) -> None:
        candidate_ids = self.checked_candidate_ids()
        if not candidate_ids:
            self._set_report_text("Select one or more exportable candidates to save.")
            self.status_message.emit("No Study Environment export candidates selected")
            return
        self._persist(candidate_ids)

    def _save_all_exportable(self) -> None:
        if not self._exportable_candidate_ids():
            self._set_report_text("The current plan has no exportable candidates.")
            self.status_message.emit("No exportable Study Environment candidates")
            return
        self._persist(None)

    def _persist(self, candidate_ids: tuple[str, ...] | None) -> None:
        plan = self._current_plan
        if plan is None:
            self._set_report_text("Preview an export plan before saving recipes.")
            return

        save_collection = self._save_collection_check.isChecked()
        if save_collection and plan.collection_draft is None:
            self._set_report_text("The current plan does not include a collection draft.")
            return

        try:
            report = self._persister.persist_export_plan(
                plan,
                selected_candidate_ids=candidate_ids,
                save_collection=save_collection,
                collection_display_name=self._collection_name_edit.text(),
                overwrite_recipes=True,
                overwrite_collection=True,
            )
        except Exception as exc:
            message = f"Failed to persist Study Environment recipes: {exc!r}"
            self._set_report_text(message)
            self.status_message.emit(message)
            QMessageBox.critical(self, "Study Environment Export Failed", message)
            return

        self._set_report_text(_persistence_report_text(report))
        self.recipes_persisted.emit(report)
        self.status_message.emit(_persistence_status_line(report))

    def _setup_summary_text(self, setup: ChartStudySetup) -> str:
        return "\n".join(
            [
                f"Name: {setup.display_name}",
                f"Environment ID: {setup.setup_id}",
                f"Description: {setup.description or '(none)'}",
                f"Created from: {_market_text(setup.created_from)}",
                f"Studies: {len(setup.studies)}",
            ]
        )

    def _set_report_text(self, text: str) -> None:
        self._report_text.setPlainText(text)


def _has_complete_market(data: Mapping[str, Any]) -> bool:
    return all(
        str(data.get(key, "") or "").strip()
        for key in ("exchange", "market_type", "symbol", "timeframe")
    )


def _market_text(data: Mapping[str, Any]) -> str:
    parts = [
        str(data.get("exchange", "") or "").strip(),
        str(data.get("market_type", "") or "").strip(),
        str(data.get("symbol", "") or "").strip(),
        str(data.get("timeframe", "") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or "Unknown dataset"


def _candidate_reason_text(candidate: StudyRecipeExportCandidate) -> str:
    parts: list[str] = []
    parts.extend(candidate.reasons)
    parts.extend(candidate.warnings)
    parts.extend(candidate.dependency_notes)
    return "; ".join(parts) or ""


def _plan_text_for(plan: StudySetupRecipeExportPlan) -> str:
    lines = [
        f"Plan ID: {plan.plan_id}",
        f"Important only: {plan.important_only}",
        f"Source market: {_market_text(plan.source_market or {})}",
        "",
        "Summary:",
    ]
    for key, value in sorted(plan.summary.items()):
        lines.append(f"- {key}: {value}")

    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in plan.warnings)

    if plan.blockers:
        lines.extend(["", "Blockers:"])
        for blocker in plan.blockers:
            lines.append(f"- {blocker.reason}: {blocker.message}")

    draft = plan.collection_draft
    if draft is not None:
        lines.extend(
            [
                "",
                "Collection draft:",
                f"- Name: {draft.display_name}",
                f"- Recipes: {len(draft.recipe_payloads)}",
            ]
        )
        if draft.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  {warning}" for warning in draft.warnings)
    else:
        lines.extend(["", "Collection draft: none"])

    return "\n".join(lines)


def _persistence_report_text(report: StudySetupRecipeExportPersistenceReport) -> str:
    lines = [
        f"Report ID: {report.report_id}",
        f"Plan ID: {report.plan_id}",
        "",
        "Summary:",
    ]
    for key, value in sorted(report.summary.items()):
        lines.append(f"- {key}: {value}")
    if report.saved_recipe_ids:
        lines.extend(["", "Saved recipe IDs:"])
        lines.extend(f"- {recipe_id}" for recipe_id in report.saved_recipe_ids)
    if report.saved_collection_id:
        lines.extend(["", f"Saved collection ID: {report.saved_collection_id}"])
    if report.results:
        lines.extend(["", "Candidate results:"])
        for result in report.results:
            detail = f"{result.candidate_id}: {result.status} - {result.message}"
            if result.error:
                detail += f" Error: {result.error}"
            lines.append(f"- {detail}")
    if report.blockers:
        lines.extend(["", "Blockers:"])
        lines.extend(f"- {blocker.reason}: {blocker.message}" for blocker in report.blockers)
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _persistence_status_line(report: StudySetupRecipeExportPersistenceReport) -> str:
    return (
        "Study Environment recipe export: "
        f"{report.summary.get('saved', 0)} saved, "
        f"{report.summary.get('failed', 0)} failed, "
        f"{report.summary.get('blocked', 0)} blocked"
    )
