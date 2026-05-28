from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.data_manager_construct_batch_execution_service import (
    ConstructBatchExecutionReport,
    DataManagerConstructBatchExecutionService,
)
from leonardo.data.historical.data_manager_construct_batch_persistence import (
    ConstructBatchPersistenceReport,
    DataManagerConstructBatchPersistenceService,
)
from leonardo.data.historical.data_manager_construct_batch_planner import (
    ConstructBatchPlan,
    ConstructBatchPlanItem,
    ConstructBatchSourceRef,
    ConstructDeltaBatchIntent,
    ConstructUnaryBatchIntent,
    DataManagerConstructBatchPlanner,
)
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.dialog_geometry import (
    apply_data_manager_dialog_initial_size,
)
from leonardo.gui.windows._data_manager.saved_artifact_columns import (
    SavedArtifactColumn,
    load_saved_artifact_columns,
)


_PLAN_ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_PLAN_ITEM_STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
_PERSISTABLE_STATUSES = {"planned", "existing_recipe"}
_UNARY_CONSTRUCTS = ("derivative", "angle", "percent_span_angle", "angle_momentum")
_SOURCE_GROUPS = (
    ("indicators", "All saved indicators"),
    ("oscillators", "All saved oscillators"),
    ("constructs", "All saved constructs"),
)
_ARTIFACT_CALC_DISABLED_TOOLTIP = (
    "Persist or reuse selected construct recipes, then calculate and save their "
    "artifacts. This does not modify Analysis Databases."
)


class ConstructBatchBuilderDialog(QDialog):
    """
    Data Manager dialog for construct batch planning, persistence, and artifact calculation.

    The dialog gathers GUI intent, delegates construct batch planning to the
    DMCB2 planner, and delegates recipe/collection persistence to the DMCB3
    service. Artifact calculation is delegated to the DMCB5 execution service;
    the dialog does not calculate artifacts directly or mutate Analysis
    Databases.
    """

    persistence_finished = Signal(object)  # ConstructBatchPersistenceReport
    execution_finished = Signal(object)  # ConstructBatchExecutionReport

    def __init__(
        self,
        *,
        historical_root: Path | None = None,
        market: MarketId | None = None,
        parent: QWidget | None = None,
        source_loader: Callable[..., list[SavedArtifactColumn]] | None = None,
        planner: DataManagerConstructBatchPlanner | None = None,
        persistence_service: DataManagerConstructBatchPersistenceService | None = None,
        execution_service: DataManagerConstructBatchExecutionService | None = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root) if historical_root is not None else None
        self._market = market
        self._source_loader = source_loader or load_saved_artifact_columns
        self._planner = planner
        self._persistence_service = persistence_service
        self._execution_service = execution_service
        self._saved_columns: list[SavedArtifactColumn] = []
        self._latest_plan: ConstructBatchPlan | None = None
        self._running = False

        if self._historical_root is not None and self._planner is None:
            self._planner = DataManagerConstructBatchPlanner(
                historical_root=self._historical_root,
            )
        if self._historical_root is not None and self._persistence_service is None:
            self._persistence_service = DataManagerConstructBatchPersistenceService(
                historical_root=self._historical_root,
            )
        if self._historical_root is not None and self._execution_service is None:
            self._execution_service = DataManagerConstructBatchExecutionService(
                historical_root=self._historical_root,
            )

        self.setWindowTitle("Construct Batch Builder")
        self.setMinimumSize(900, 620)
        apply_data_manager_dialog_initial_size(
            self,
            default_width=1100,
            default_height=720,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        intro = QLabel(
            "Build a construct batch preview plan, then save selected recipes or "
            "save them as an ordered recipe collection. Calculate Artifacts saves "
            "or reuses selected recipes before calculating artifacts. This dialog "
            "does not modify Analysis Databases.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        body.addLayout(right, 2)

        left.addWidget(self._build_mode_group())
        left.addWidget(self._build_source_group())
        left.addWidget(self._build_parameters_group())
        left.addWidget(self._build_collection_group())

        right.addWidget(self._build_plan_group(), 1)
        right.addWidget(self._build_report_group())

        action_row = QHBoxLayout()
        action_row.addStretch(1)

        self._preview_plan_button = QPushButton("Preview Plan", self)
        self._preview_plan_button.clicked.connect(self._preview_plan)
        self._save_recipes_button = QPushButton("Save Recipes", self)
        self._save_recipes_button.clicked.connect(self._save_recipes)
        self._save_collection_button = QPushButton("Save as Collection", self)
        self._save_collection_button.clicked.connect(self._save_collection)
        self._calculate_artifacts_button = QPushButton("Calculate Artifacts", self)
        self._calculate_artifacts_button.setEnabled(False)
        self._calculate_artifacts_button.setToolTip(_ARTIFACT_CALC_DISABLED_TOOLTIP)
        self._calculate_artifacts_button.clicked.connect(self._calculate_artifacts)
        self._close_button = QPushButton("Close", self)
        self._close_button.clicked.connect(self.accept)

        for button in (
            self._preview_plan_button,
            self._save_recipes_button,
            self._save_collection_button,
            self._calculate_artifacts_button,
            self._close_button,
        ):
            action_row.addWidget(button)

        root.addLayout(action_row)

        self._load_saved_sources()
        self._populate_fixed_sources()
        self._refresh_construct_mode()
        self._refresh_source_preview()
        self._refresh_buttons()

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("Construct batch mode", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        self._mode_combo = QComboBox(group)
        self._mode_combo.addItem("Unary source expansion", "unary")
        self._mode_combo.addItem("Binary delta expansion", "delta")
        self._mode_combo.currentIndexChanged.connect(self._refresh_construct_mode)
        layout.addRow("Mode", self._mode_combo)

        self._construct_combo = QComboBox(group)
        self._construct_combo.currentIndexChanged.connect(self._refresh_buttons)
        layout.addRow("Construct", self._construct_combo)

        self._unsupported_note = QLabel(
            "braids, braid_instability, trap_area, and dynamic_binning remain "
            "unsupported for generic construct batch mode.",
            group,
        )
        self._unsupported_note.setWordWrap(True)
        layout.addRow("Excluded", self._unsupported_note)
        return group

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("Sources", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        self._unary_source_group_combo = QComboBox(group)
        for value, label in _SOURCE_GROUPS:
            self._unary_source_group_combo.addItem(label, value)
        self._unary_source_group_combo.currentIndexChanged.connect(
            self._refresh_source_preview
        )
        layout.addRow("Unary source group", self._unary_source_group_combo)

        self._fixed_source_combo = QComboBox(group)
        self._fixed_source_combo.currentIndexChanged.connect(self._refresh_buttons)
        layout.addRow("Fixed source", self._fixed_source_combo)

        self._fixed_role_combo = QComboBox(group)
        self._fixed_role_combo.addItem("minuend", "minuend")
        self._fixed_role_combo.addItem("subtrahend", "subtrahend")
        layout.addRow("Fixed role", self._fixed_role_combo)

        self._variable_source_group_combo = QComboBox(group)
        for value, label in _SOURCE_GROUPS:
            self._variable_source_group_combo.addItem(label, value)
        self._variable_source_group_combo.currentIndexChanged.connect(
            self._refresh_source_preview
        )
        layout.addRow("Variable source group", self._variable_source_group_combo)

        explanation = QLabel("delta = minuend - subtrahend", group)
        explanation.setWordWrap(True)
        layout.addRow("Direction", explanation)

        self._source_preview = QPlainTextEdit(group)
        self._source_preview.setReadOnly(True)
        self._source_preview.setMaximumBlockCount(80)
        layout.addRow("Source preview", self._source_preview)
        return group

    def _build_parameters_group(self) -> QGroupBox:
        group = QGroupBox("Parameters", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        self._derivative_order_spin = QSpinBox(group)
        self._derivative_order_spin.setRange(1, 2)
        self._derivative_order_spin.setValue(1)
        layout.addRow("Derivative order", self._derivative_order_spin)

        self._angle_unit_combo = QComboBox(group)
        self._angle_unit_combo.addItem("deg", "deg")
        self._angle_unit_combo.addItem("rad", "rad")
        layout.addRow("Angle unit", self._angle_unit_combo)

        self._percent_window_spin = QSpinBox(group)
        self._percent_window_spin.setRange(2, 10000)
        self._percent_window_spin.setValue(14)
        layout.addRow("Percent span window", self._percent_window_spin)

        self._angle_momentum_n_spin = QSpinBox(group)
        self._angle_momentum_n_spin.setRange(1, 10000)
        self._angle_momentum_n_spin.setValue(3)
        layout.addRow("Angle momentum window", self._angle_momentum_n_spin)

        self._delta_mode_combo = QComboBox(group)
        self._delta_mode_combo.addItem("absolute", "abs")
        self._delta_mode_combo.addItem("percent", "pct")
        layout.addRow("Delta mode", self._delta_mode_combo)
        return group

    def _build_collection_group(self) -> QGroupBox:
        group = QGroupBox("Collection", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        self._collection_name_edit = QLineEdit(group)
        self._collection_name_edit.setPlaceholderText("Collection name")
        self._collection_name_edit.textChanged.connect(self._refresh_buttons)
        layout.addRow("Name", self._collection_name_edit)

        self._collection_description_edit = QPlainTextEdit(group)
        self._collection_description_edit.setPlaceholderText("Optional description")
        self._collection_description_edit.setMaximumHeight(80)
        layout.addRow("Description", self._collection_description_edit)
        return group

    def _build_plan_group(self) -> QGroupBox:
        group = QGroupBox("Plan", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        self._summary_label = QLabel("No plan built.", group)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._plan_table = QTableWidget(0, 5, group)
        self._plan_table.setHorizontalHeaderLabels(
            ("Select", "Status", "Candidate", "Expected outputs", "Issues")
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )
        self._plan_table.horizontalHeader().setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Stretch,
        )
        self._plan_table.itemChanged.connect(lambda _item: self._refresh_buttons())
        layout.addWidget(self._plan_table, 1)
        return group

    def _build_report_group(self) -> QGroupBox:
        group = QGroupBox("Report", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        self._report_text = QPlainTextEdit(group)
        self._report_text.setReadOnly(True)
        self._report_text.setMaximumHeight(160)
        self._report_text.setPlainText("Preview Plan has not been run.")
        layout.addWidget(self._report_text)
        return group

    def _load_saved_sources(self) -> None:
        self._saved_columns = []
        if self._historical_root is None or self._market is None:
            return
        try:
            self._saved_columns = self._source_loader(
                historical_root=self._historical_root,
                market=self._market,
            )
        except Exception as exc:
            self._report_text.setPlainText(f"Failed to load saved artifact sources: {exc!r}")
            self._saved_columns = []

    def _populate_fixed_sources(self) -> None:
        self._fixed_source_combo.blockSignals(True)
        self._fixed_source_combo.clear()
        self._fixed_source_combo.addItem("close", "__close__")
        for column in self._saved_columns:
            self._fixed_source_combo.addItem(self._column_display_name(column), column)
        self._fixed_source_combo.blockSignals(False)

    def _refresh_construct_mode(self) -> None:
        mode = self._mode()
        self._construct_combo.blockSignals(True)
        self._construct_combo.clear()
        if mode == "delta":
            self._construct_combo.addItem("delta", "delta")
        else:
            for key in _UNARY_CONSTRUCTS:
                self._construct_combo.addItem(key, key)
        self._construct_combo.blockSignals(False)

        is_delta = mode == "delta"
        for widget in (
            self._fixed_source_combo,
            self._fixed_role_combo,
            self._variable_source_group_combo,
            self._delta_mode_combo,
        ):
            widget.setEnabled(is_delta)
        self._unary_source_group_combo.setEnabled(not is_delta)
        self._refresh_source_preview()
        self._refresh_buttons()

    def _refresh_source_preview(self) -> None:
        lines = [
            f"Saved indicators: {len(self._columns_for_group('indicators'))}",
            f"Saved oscillators: {len(self._columns_for_group('oscillators'))}",
            f"Saved constructs: {len(self._columns_for_group('constructs'))}",
        ]
        if self._mode() == "delta":
            lines.append(f"Variable candidates: {len(self._variable_sources())}")
        else:
            lines.append(f"Unary candidates: {len(self._unary_sources())}")
        lines.append("Selected saved artifact columns are not wired into this dialog yet.")
        self._source_preview.setPlainText("\n".join(lines))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        if self._running:
            self._preview_plan_button.setEnabled(False)
            self._save_recipes_button.setEnabled(False)
            self._save_collection_button.setEnabled(False)
            self._calculate_artifacts_button.setEnabled(False)
            self._close_button.setEnabled(False)
            return

        self._close_button.setEnabled(True)
        has_context = (
            self._historical_root is not None
            and self._market is not None
            and self._planner is not None
        )
        self._preview_plan_button.setEnabled(has_context and bool(self._construct_key()))
        has_selected_persistable = bool(self._selected_persistable_item_ids())
        self._save_recipes_button.setEnabled(
            self._latest_plan is not None and has_selected_persistable
        )
        self._save_collection_button.setEnabled(
            self._latest_plan is not None
            and has_selected_persistable
            and bool(self._collection_name_edit.text().strip())
        )
        self._calculate_artifacts_button.setEnabled(
            self._latest_plan is not None
            and has_selected_persistable
            and self._execution_service is not None
        )
        if self._latest_plan is not None:
            self._set_plan_summary(self._latest_plan)

    def _preview_plan(self) -> None:
        if self._planner is None or self._market is None:
            self._report_text.setPlainText("Select a dataset before previewing a construct batch.")
            self._refresh_buttons()
            return

        try:
            if self._mode() == "delta":
                plan = self._planner.plan_delta_batch(self._delta_intent())
            else:
                plan = self._planner.plan_unary_batch(self._unary_intent())
        except Exception as exc:
            self._latest_plan = None
            self._plan_table.setRowCount(0)
            self._report_text.setPlainText(f"Construct batch preview failed: {exc!r}")
            self._refresh_buttons()
            QMessageBox.critical(
                self,
                "Construct Batch Preview Failed",
                f"Construct batch preview failed: {exc!r}",
            )
            return

        self._latest_plan = plan
        self._populate_plan_table(plan)
        self._set_plan_summary(plan)
        self._report_text.setPlainText(_plan_report_text(plan))
        self._refresh_buttons()

    def _save_recipes(self) -> None:
        plan = self._latest_plan
        if plan is None or self._persistence_service is None:
            return
        selected_ids = self._selected_persistable_item_ids()
        if not selected_ids:
            self._refresh_buttons()
            return
        if not self._confirm_persistence("Save Recipes", selected_ids):
            return

        report = self._persistence_service.persist_selected_recipes(
            plan=plan,
            selected_item_ids=selected_ids,
        )
        self._handle_persistence_report(report)

    def _save_collection(self) -> None:
        plan = self._latest_plan
        if plan is None or self._persistence_service is None:
            return
        selected_ids = self._selected_persistable_item_ids()
        collection_name = self._collection_name_edit.text().strip()
        if not selected_ids or not collection_name:
            self._refresh_buttons()
            return
        if not self._confirm_persistence("Save as Collection", selected_ids):
            return

        report = self._persistence_service.persist_selected_recipes_as_collection(
            plan=plan,
            selected_item_ids=selected_ids,
            collection_name=collection_name,
            collection_description=self._collection_description_edit.toPlainText().strip(),
        )
        self._handle_persistence_report(report)

    def _calculate_artifacts(self) -> None:
        plan = self._latest_plan
        if plan is None or self._execution_service is None:
            return
        selected_ids = self._selected_persistable_item_ids()
        if not selected_ids:
            self._refresh_buttons()
            return
        if not self._confirm_execution(selected_ids):
            return

        self._running = True
        self._report_text.setPlainText(
            "Calculating selected construct batch artifacts...\n"
            "Selected recipes will be saved or reused first. No Analysis Database "
            "will be modified."
        )
        self._refresh_buttons()

        try:
            report = self._execution_service.execute_selected_artifacts(
                plan=plan,
                selected_item_ids=selected_ids,
            )
        except Exception as exc:
            self._running = False
            message = f"Construct batch artifact calculation failed: {exc!r}"
            self._report_text.setPlainText(message)
            self._refresh_buttons()
            QMessageBox.critical(
                self,
                "Construct Batch Artifact Calculation Failed",
                message,
            )
            return

        self._running = False
        self._handle_execution_report(report)

    def _confirm_persistence(self, title: str, selected_ids: tuple[str, ...]) -> bool:
        plan = self._latest_plan
        if plan is None:
            return False
        selected_items = [
            item for item in plan.items if item.item_id in set(selected_ids)
        ]
        planned = sum(1 for item in selected_items if item.status == "planned")
        existing = sum(1 for item in selected_items if item.status == "existing_recipe")
        blocked = sum(1 for item in plan.items if item.status in {"blocked", "error"})
        message = (
            f"Selected persistable items: {len(selected_items)}\n"
            f"New recipes to save: {planned}\n"
            f"Existing recipes to reuse: {existing}\n"
            f"Blocked/error items not selected: {blocked}\n\n"
            "Proceed?"
        )
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_execution(self, selected_ids: tuple[str, ...]) -> bool:
        plan = self._latest_plan
        if plan is None:
            return False
        selected_set = set(selected_ids)
        selected_items = [item for item in plan.items if item.item_id in selected_set]
        planned = sum(1 for item in selected_items if item.status == "planned")
        existing = sum(1 for item in selected_items if item.status == "existing_recipe")
        blocked = sum(1 for item in plan.items if item.status in {"blocked", "error"})
        message = (
            f"Selected persistable items: {len(selected_items)}\n"
            f"New recipes to save before calculation: {planned}\n"
            f"Existing recipes to reuse before calculation: {existing}\n"
            f"Blocked/error items not selected: {blocked}\n\n"
            "Artifacts will be calculated and saved through the existing recipe "
            "execution path.\n"
            "No Analysis Database will be created, extended, built, or rebuilt.\n\n"
            "Proceed?"
        )
        answer = QMessageBox.question(
            self,
            "Calculate Construct Batch Artifacts",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _handle_persistence_report(
        self,
        report: ConstructBatchPersistenceReport,
    ) -> None:
        self._report_text.setPlainText(_persistence_report_text(report))
        self.persistence_finished.emit(report)
        self._refresh_buttons()
        if report.failed_count or report.blocked_count or report.blockers:
            QMessageBox.warning(self, "Construct Batch Persistence Finished", self._report_text.toPlainText())
        else:
            QMessageBox.information(self, "Construct Batch Persistence Complete", self._report_text.toPlainText())

    def _handle_execution_report(
        self,
        report: ConstructBatchExecutionReport,
    ) -> None:
        self._report_text.setPlainText(_execution_report_text(report))
        self.execution_finished.emit(report)
        self._refresh_buttons()
        if report.failed_count or report.blocked_count or report.blockers:
            QMessageBox.warning(
                self,
                "Construct Batch Artifact Calculation Finished",
                self._report_text.toPlainText(),
            )
        else:
            QMessageBox.information(
                self,
                "Construct Batch Artifact Calculation Complete",
                self._report_text.toPlainText(),
            )

    def _populate_plan_table(self, plan: ConstructBatchPlan) -> None:
        self._plan_table.blockSignals(True)
        self._plan_table.setRowCount(0)
        for item in plan.items:
            row = self._plan_table.rowCount()
            self._plan_table.insertRow(row)

            select_item = QTableWidgetItem("")
            select_item.setData(_PLAN_ITEM_ID_ROLE, item.item_id)
            select_item.setData(_PLAN_ITEM_STATUS_ROLE, item.status)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if item.status in _PERSISTABLE_STATUSES:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                select_item.setCheckState(Qt.CheckState.Checked)
            else:
                select_item.setCheckState(Qt.CheckState.Unchecked)
            select_item.setFlags(flags)
            self._plan_table.setItem(row, 0, select_item)

            self._plan_table.setItem(row, 1, QTableWidgetItem(item.status))
            self._plan_table.setItem(row, 2, QTableWidgetItem(item.display_name))
            self._plan_table.setItem(
                row,
                3,
                QTableWidgetItem(", ".join(item.expected_outputs)),
            )
            self._plan_table.setItem(
                row,
                4,
                QTableWidgetItem("; ".join(item.blockers or item.warnings)),
            )
        self._plan_table.blockSignals(False)

    def _set_plan_summary(self, plan: ConstructBatchPlan) -> None:
        selected_count = len(self._selected_persistable_item_ids())
        self._summary_label.setText(
            f"Candidates: {plan.total_candidate_count}; "
            f"planned: {plan.planned_count}; "
            f"existing: {plan.existing_recipe_count}; "
            f"blocked: {plan.blocked_count}; "
            f"warnings: {plan.warning_count}; "
            f"selected persistable: {selected_count}."
        )

    def _selected_persistable_item_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for row in range(self._plan_table.rowCount()):
            item = self._plan_table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            if str(item.data(_PLAN_ITEM_STATUS_ROLE) or "") not in _PERSISTABLE_STATUSES:
                continue
            item_id = str(item.data(_PLAN_ITEM_ID_ROLE) or "")
            if item_id:
                ids.append(item_id)
        return tuple(ids)

    def _unary_intent(self) -> ConstructUnaryBatchIntent:
        assert self._market is not None
        return ConstructUnaryBatchIntent(
            construct_key=self._construct_key(),
            exchange=self._market.exchange,
            market_type=self._market.market_type,
            symbol=self._market.symbol,
            timeframe=self._market.timeframe,
            sources=tuple(self._unary_sources()),
            params=self._params(),
        )

    def _delta_intent(self) -> ConstructDeltaBatchIntent:
        assert self._market is not None
        return ConstructDeltaBatchIntent(
            exchange=self._market.exchange,
            market_type=self._market.market_type,
            symbol=self._market.symbol,
            timeframe=self._market.timeframe,
            fixed_source=self._fixed_source(),
            fixed_role=str(self._fixed_role_combo.currentData() or "minuend"),  # type: ignore[arg-type]
            variable_sources=tuple(self._variable_sources()),
            params=self._params(),
        )

    def _params(self) -> dict[str, object]:
        key = self._construct_key()
        if key == "derivative":
            return {"order": int(self._derivative_order_spin.value())}
        if key == "angle":
            return {"unit": str(self._angle_unit_combo.currentData() or "deg")}
        if key == "percent_span_angle":
            return {"window": int(self._percent_window_spin.value())}
        if key == "angle_momentum":
            return {"n": int(self._angle_momentum_n_spin.value())}
        if key == "delta":
            return {"mode": str(self._delta_mode_combo.currentData() or "abs")}
        return {}

    def _unary_sources(self) -> list[ConstructBatchSourceRef]:
        return [
            self._source_ref_from_column(column)
            for column in self._columns_for_group(
                str(self._unary_source_group_combo.currentData() or "")
            )
        ]

    def _variable_sources(self) -> list[ConstructBatchSourceRef]:
        return [
            self._source_ref_from_column(column)
            for column in self._columns_for_group(
                str(self._variable_source_group_combo.currentData() or "")
            )
        ]

    def _fixed_source(self) -> ConstructBatchSourceRef:
        data = self._fixed_source_combo.currentData()
        if isinstance(data, SavedArtifactColumn):
            return self._source_ref_from_column(data)
        return self._close_source_ref()

    def _close_source_ref(self) -> ConstructBatchSourceRef:
        if self._historical_root is None or self._market is None:
            raise RuntimeError("Cannot build close source without dataset context.")
        csv_path = CsvOHLCVStore().file_path(
            HistoricalPaths(root=self._historical_root).ohlcv_dir(self._market)
        )
        return ConstructBatchSourceRef(
            source_id="ohlcv:close",
            display_name="close",
            source_family="ohlc",
            exchange=self._market.exchange,
            market_type=self._market.market_type,
            symbol=self._market.symbol,
            timeframe=self._market.timeframe,
            column_name="close",
            source_token="close",
            csv_path=csv_path,
            selectable=True,
            analysis_usable=True,
            renderable=True,
        )

    def _source_ref_from_column(
        self,
        column: SavedArtifactColumn,
    ) -> ConstructBatchSourceRef:
        if self._market is None:
            raise RuntimeError("Cannot build construct batch source without a selected market.")
        return ConstructBatchSourceRef(
            source_id=column.artifact_uid or f"{Path(column.path).as_posix()}::{column.column_name}",
            display_name=self._column_display_name(column),
            source_family=column.family,
            exchange=self._market.exchange,
            market_type=self._market.market_type,
            symbol=self._market.symbol,
            timeframe=self._market.timeframe,
            column_name=column.column_name,
            source_token=column.column_name,
            csv_path=Path(column.path),
            metadata_path=column.metadata_path,
            selectable=True,
            analysis_usable=column.analysis_usable is not False,
            renderable=column.renderable is not False,
        )

    def _columns_for_group(self, group: str) -> list[SavedArtifactColumn]:
        return [column for column in self._saved_columns if column.family == group]

    def _mode(self) -> str:
        return str(self._mode_combo.currentData() or "unary")

    def _construct_key(self) -> str:
        return str(self._construct_combo.currentData() or "")

    def _column_display_name(self, column: SavedArtifactColumn) -> str:
        family = column.family[:-1].capitalize() if column.family.endswith("s") else column.family
        return f"{family} - {column.tool_title} - {column.instance_key} -> {column.column_name}"


def _plan_report_text(plan: ConstructBatchPlan) -> str:
    lines = [
        f"Plan: {plan.batch_kind} / {plan.construct_key}",
        f"Candidates: {plan.total_candidate_count}",
        f"Planned: {plan.planned_count}",
        f"Existing recipes: {plan.existing_recipe_count}",
        f"Blocked: {plan.blocked_count}",
        f"Warnings: {plan.warning_count}",
        "",
    ]
    for item in plan.items:
        lines.append(
            f"[{item.status}] {item.display_name} :: "
            f"{', '.join(item.expected_outputs) or 'no outputs'}"
        )
        if item.blockers:
            lines.append(f"  Blockers: {'; '.join(item.blockers)}")
        if item.warnings:
            lines.append(f"  Warnings: {'; '.join(item.warnings)}")
        if item.direction:
            lines.append(f"  Direction: {item.direction}")
        alignment = item.alignment_summary
        if alignment.common_first_ts_ms is not None or alignment.common_last_ts_ms is not None:
            lines.append(
                "  Alignment: "
                f"{alignment.common_first_ts_ms} -> {alignment.common_last_ts_ms}"
            )
    return "\n".join(lines)


def _persistence_report_text(report: ConstructBatchPersistenceReport) -> str:
    lines = [
        "Construct batch persistence report",
        f"Selected: {report.selected_count}",
        f"Saved recipes: {report.saved_recipe_count}",
        f"Reused recipes: {report.reused_recipe_count}",
        f"Skipped: {report.skipped_count}",
        f"Blocked: {report.blocked_count}",
        f"Failed: {report.failed_count}",
    ]
    if report.collection_result is not None:
        collection = report.collection_result
        lines.extend(
            (
                f"Collection saved: {collection.collection_saved}",
                f"Collection id: {collection.collection_id or ''}",
                f"Collection name: {collection.collection_name or ''}",
                f"Collection recipe count: {collection.recipe_count}",
            )
        )
        if collection.blockers:
            lines.append(f"Collection blockers: {'; '.join(collection.blockers)}")
    lines.append("")
    for result in report.results:
        lines.append(
            f"[{result.status}] {result.display_name} :: "
            f"{result.recipe_id or 'no recipe id'}"
        )
        if result.blockers:
            lines.append(f"  Blockers: {'; '.join(result.blockers)}")
    return "\n".join(lines)


def _execution_report_text(report: ConstructBatchExecutionReport) -> str:
    lines = [
        "Construct batch artifact calculation report",
        f"Selected: {report.selected_count}",
        f"Saved recipes: {report.saved_recipe_count}",
        f"Reused recipes: {report.reused_recipe_count}",
        f"Execution attempted: {report.execution_attempted_count}",
        f"Completed: {report.completed_count}",
        f"Skipped: {report.skipped_count}",
        f"Blocked: {report.blocked_count}",
        f"Failed: {report.failed_count}",
        "Analysis Databases modified: 0",
        "",
    ]
    for result in report.results:
        lines.append(
            f"[{result.status}] {result.display_name} :: "
            f"{result.recipe_id or 'no recipe id'}"
        )
        if result.artifact_path:
            lines.append(f"  Artifact: {result.artifact_path}")
        if result.reason:
            lines.append(f"  Reason: {result.reason}")
        if result.blockers:
            lines.append(f"  Blockers: {'; '.join(result.blockers)}")
    return "\n".join(lines)
