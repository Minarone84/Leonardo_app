from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.artifact_calculation_service import (
    ArtifactCalculationResult,
    ArtifactCalculationService,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_executor import (
    ArtifactRecipeExecutionReport,
    ArtifactRecipeExecutor,
)
from leonardo.data.historical.artifact_recovery_database_rebuilder import (
    ArtifactRecoveryDatabaseRebuildReport,
    ArtifactRecoveryDatabaseRebuilder,
)
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryPlanner,
    ArtifactRecoveryReport,
)
from leonardo.data.historical.artifact_recovery_regenerator import (
    ArtifactRecoveryRegenerationReport,
    ArtifactRecoveryRegenerator,
)
from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.artifact_recipe_collection_dialog import (
    ArtifactRecipeCollectionDialog,
)
from leonardo.gui.windows._data_manager.artifact_recipe_dialog import (
    ArtifactRecipeDialog,
)
from leonardo.gui.windows.financial_tools_manager_window import (
    FinancialToolsManagerWindow,
)


class ToolCalculationWidget(QGroupBox):
    """Save-only financial-tool artifact calculation area for Data Manager.

    This widget gathers user intent through the existing financial-tool form and
    delegates durable artifact calculation to ``ArtifactCalculationService``.
    Artifact recipe persistence is delegated to ``ArtifactRecipeStore``. It must
    not apply chart-local studies, create pane state, or touch renderers.
    """

    artifact_saved = Signal(object)  # ArtifactCalculationResult
    database_rebuilt = Signal(object)  # ArtifactRecoveryDatabaseRebuildReport
    preview_requested = Signal(object, str)  # Path, title
    status_message = Signal(str)

    def __init__(
        self,
        *,
        historical_root: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("Calculate and Save Tool Outputs", parent)
        self._historical_root = Path(historical_root)
        self._market: Optional[MarketId] = None
        self._tool_window: Optional[FinancialToolsManagerWindow] = None
        self._recipe_dialog: Optional[ArtifactRecipeDialog] = None
        self._collection_dialog: Optional[ArtifactRecipeCollectionDialog] = None
        self._service = ArtifactCalculationService(
            historical_root=self._historical_root
        )
        self._recipe_store = ArtifactRecipeStore(
            historical_root=self._historical_root
        )
        self._collection_store = ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )
        self._recipe_executor = ArtifactRecipeExecutor(
            historical_root=self._historical_root,
            calculation_service=self._service,
        )
        self._recovery_planner = ArtifactRecoveryPlanner(
            historical_root=self._historical_root,
            collection_store=self._collection_store,
        )
        self._recovery_regenerator = ArtifactRecoveryRegenerator(
            historical_root=self._historical_root,
            planner=self._recovery_planner,
            executor=self._recipe_executor,
            collection_store=self._collection_store,
        )
        self._database_rebuilder = ArtifactRecoveryDatabaseRebuilder(
            historical_root=self._historical_root,
            planner=self._recovery_planner,
            collection_store=self._collection_store,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        self._description = QLabel(
            "Calculate one full-dataset financial-tool artifact for the selected "
            "dataset. This is save-only: it does not apply chart studies or touch "
            "panes/renderers.",
            self,
        )
        self._description.setWordWrap(True)
        root.addWidget(self._description)

        self._selected_dataset = QLabel("Selected dataset: none", self)
        self._selected_dataset.setWordWrap(True)
        root.addWidget(self._selected_dataset)
        root.addStretch(1)

        self._button = QPushButton("Calculate and Save Artifact", self)
        self._button.setEnabled(False)
        self._button.clicked.connect(lambda: self._open_tool_window())

        self._recipes_button = QPushButton("Saved Recipes...", self)
        self._recipes_button.setEnabled(False)
        self._recipes_button.clicked.connect(self._open_recipe_dialog)

        self._collections_button = QPushButton("Saved Recipe Collections...", self)
        self._collections_button.setEnabled(False)
        self._collections_button.clicked.connect(self._open_collection_dialog)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self._button)
        button_row.addWidget(self._recipes_button)
        button_row.addWidget(self._collections_button)
        button_row.addStretch(1)
        root.addLayout(button_row, 0)

    def set_market(self, market: Optional[MarketId]) -> None:
        self._market = market

        enabled = market is not None
        self._button.setEnabled(enabled)
        self._recipes_button.setEnabled(enabled)
        self._collections_button.setEnabled(enabled)

        if market is None:
            self._selected_dataset.setText("Selected dataset: none")
            return

        self._selected_dataset.setText(
            "Selected dataset: "
            f"{market.exchange} / {market.market_type} / "
            f"{market.symbol} / {market.timeframe}"
        )

    def _activate_existing_window(self, widget: Optional[QWidget]) -> bool:
        if widget is None:
            return False
        try:
            if not widget.isVisible():
                widget.show()
            widget.raise_()
            widget.activateWindow()
            return True
        except RuntimeError:
            return False

    def _open_tool_window(self) -> Optional[FinancialToolsManagerWindow]:
        market = self._market
        if market is None:
            self.status_message.emit(
                "Select a dataset before calculating an artifact"
            )
            return None

        if self._activate_existing_window(self._tool_window):
            return self._tool_window
        self._tool_window = None

        window = FinancialToolsManagerWindow(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            historical_root=self._historical_root,
            save_only=True,
            parent=self.window(),
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.save_requested.connect(self._save_requested)
        window.recipe_requested.connect(self._recipe_requested)
        window.destroyed.connect(self._on_tool_window_destroyed)

        self._tool_window = window
        window.show()

        self.status_message.emit(
            "Configure a financial tool, then click Save Recipe or Save Artifact"
        )
        return window

    def _on_tool_window_destroyed(self, _obj: object = None) -> None:
        self._tool_window = None

    def _open_recipe_dialog(self) -> None:
        market = self._market
        if market is None:
            self.status_message.emit("Select a dataset before opening saved recipes")
            return

        if self._activate_existing_window(self._recipe_dialog):
            return
        self._recipe_dialog = None

        dialog = ArtifactRecipeDialog(
            historical_root=self._historical_root,
            market=market,
            parent=self.window(),
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.load_requested.connect(self._load_recipe_requested)
        dialog.calculate_requested.connect(self._calculate_recipe_requested)
        dialog.create_collection_requested.connect(self._create_collection_requested)
        dialog.recipe_deleted.connect(
            lambda _recipe_id: self.status_message.emit("Artifact recipe deleted")
        )
        dialog.status_message.connect(self.status_message.emit)
        dialog.destroyed.connect(self._on_recipe_dialog_destroyed)

        self._recipe_dialog = dialog
        dialog.show()

    def _on_recipe_dialog_destroyed(self, _obj: object = None) -> None:
        self._recipe_dialog = None

    def _open_collection_dialog(self) -> None:
        market = self._market
        if market is None:
            self.status_message.emit("Select a dataset before opening recipe collections")
            return

        if self._activate_existing_window(self._collection_dialog):
            return
        self._collection_dialog = None

        dialog = ArtifactRecipeCollectionDialog(
            historical_root=self._historical_root,
            market=market,
            parent=self.window(),
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.execute_requested.connect(self._execute_collection_requested)
        dialog.recovery_plan_requested.connect(self._recovery_plan_requested)
        dialog.recovery_regeneration_requested.connect(self._recovery_regeneration_requested)
        dialog.database_rebuild_requested.connect(self._database_rebuild_requested)
        dialog.collection_deleted.connect(
            lambda _collection_id: self.status_message.emit("Artifact recipe collection deleted")
        )
        dialog.status_message.connect(self.status_message.emit)
        dialog.destroyed.connect(self._on_collection_dialog_destroyed)

        self._collection_dialog = dialog
        dialog.show()

    def _on_collection_dialog_destroyed(self, _obj: object = None) -> None:
        self._collection_dialog = None

    def _recipe_requested(self, payload: object) -> None:
        if not isinstance(payload, dict):
            QMessageBox.warning(
                self,
                "Invalid Recipe",
                "The financial-tool recipe payload is invalid.",
            )
            return

        try:
            recipe = self._recipe_store.save_recipe(payload, overwrite=True)
        except Exception as exc:
            message = f"Failed to save artifact recipe: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Artifact Recipe Save Failed", message)
            return

        if self._recipe_dialog is not None:
            self._recipe_dialog.refresh()

        message = f"Saved artifact recipe: {recipe.display_name}"
        self.status_message.emit(message)
        QMessageBox.information(self, "Artifact Recipe Saved", message)

    def _create_collection_requested(
        self,
        recipes_obj: object,
        display_name_obj: object,
        description_obj: object,
    ) -> None:
        market = self._market
        if market is None:
            self.status_message.emit("Select a dataset before creating a recipe collection")
            return
        if not isinstance(recipes_obj, (list, tuple)):
            QMessageBox.warning(
                self,
                "Invalid Recipe Collection",
                "The recipe collection payload is invalid.",
            )
            return

        recipes = tuple(recipe for recipe in recipes_obj if isinstance(recipe, ArtifactRecipe))
        if not recipes:
            QMessageBox.warning(
                self,
                "Recipe Collection",
                "Select one or more saved recipes before creating a collection.",
            )
            return

        display_name = str(display_name_obj or "").strip()
        description = str(description_obj or "").strip()
        try:
            collection = self._collection_store.build_collection(
                market=market,
                display_name=display_name,
                description=description,
                recipes=recipes,
            )
            saved = self._collection_store.save_collection(collection, overwrite=True)
        except Exception as exc:
            message = f"Failed to save recipe collection: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Recipe Collection Save Failed", message)
            return

        if self._collection_dialog is not None:
            self._collection_dialog.refresh()

        message = (
            f"Saved recipe collection: {saved.display_name} "
            f"({len(saved.recipe_snapshots)} recipe(s))"
        )
        self.status_message.emit(message)
        QMessageBox.information(self, "Recipe Collection Saved", message)

    def _load_recipe_requested(self, recipe_obj: object) -> None:
        if not isinstance(recipe_obj, ArtifactRecipe):
            return

        window = self._open_tool_window()
        if window is None:
            return

        if not window.load_payload_for_recipe(recipe_obj.to_payload()):
            QMessageBox.warning(
                self,
                "Recipe Load Failed",
                "Could not load this recipe into the tool form.",
            )
            return

        self.status_message.emit(
            f"Loaded artifact recipe: {recipe_obj.display_name}"
        )

    def _calculate_recipe_requested(self, recipe_obj: object) -> None:
        if not isinstance(recipe_obj, ArtifactRecipe):
            return

        self._save_requested(recipe_obj.to_payload())

    def _execute_collection_requested(self, collection_obj: object, selected_recipe_ids_obj: object) -> None:
        if not isinstance(collection_obj, ArtifactRecipeCollection):
            return

        selected_recipe_ids = self._normalize_selected_recipe_ids(selected_recipe_ids_obj)

        try:
            report = self._recipe_executor.execute_collection(
                collection_obj,
                selected_recipe_ids=selected_recipe_ids,
                continue_on_error=False,
            )
        except Exception as exc:
            message = f"Failed to calculate recipe collection: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Recipe Collection Calculation Failed", message)
            return

        self._handle_collection_execution_report(report)

    def _normalize_selected_recipe_ids(self, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple, set)):
            recipe_ids = tuple(str(item).strip() for item in value if str(item).strip())
            return recipe_ids or None
        recipe_id = str(value or "").strip()
        return (recipe_id,) if recipe_id else None

    def _recovery_plan_requested(self, collection_obj: object, selected_recipe_ids_obj: object) -> None:
        if not isinstance(collection_obj, ArtifactRecipeCollection):
            return

        selected_recipe_ids = self._normalize_selected_recipe_ids(selected_recipe_ids_obj)
        try:
            report = self._recovery_planner.plan_collection(
                collection_obj,
                selected_recipe_ids=selected_recipe_ids,
            )
        except Exception as exc:
            message = f"Failed to build artifact recovery plan: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Artifact Recovery Plan Failed", message)
            return

        message = self._recovery_report_summary(report)
        self.status_message.emit(self._recovery_report_status_line(report))
        QMessageBox.information(self, "Artifact Recovery Status", message)

    def _recovery_regeneration_requested(self, collection_obj: object, selected_recipe_ids_obj: object) -> None:
        if not isinstance(collection_obj, ArtifactRecipeCollection):
            return

        selected_recipe_ids = self._normalize_selected_recipe_ids(selected_recipe_ids_obj)
        try:
            report = self._recovery_regenerator.regenerate_collection(
                collection_obj,
                selected_recipe_ids=selected_recipe_ids,
                continue_on_error=False,
                replan_after=True,
            )
        except Exception as exc:
            message = f"Failed to recover actionable artifacts: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Artifact Recovery Failed", message)
            return

        self._handle_recovery_regeneration_report(report)

    def _database_rebuild_requested(self, collection_obj: object) -> None:
        if not isinstance(collection_obj, ArtifactRecipeCollection):
            return

        try:
            report = self._database_rebuilder.rebuild_for_collection(collection_obj)
        except Exception as exc:
            message = f"Failed to rebuild linked Analysis Database: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Analysis Database Rebuild Failed", message)
            return

        self._handle_database_rebuild_report(report)

    def _handle_collection_execution_report(self, report: ArtifactRecipeExecutionReport) -> None:
        last_result: ArtifactCalculationResult | None = None
        failed_lines: list[str] = []

        for item in report.item_reports:
            if item.succeeded and isinstance(item.result, ArtifactCalculationResult):
                last_result = item.result
                self.artifact_saved.emit(item.result)
            elif item.failed:
                failed_lines.append(f"- {item.display_name}: {item.error_text}")

        summary = (
            "Recipe collection calculation finished: "
            f"{report.succeeded_count} succeeded, "
            f"{report.failed_count} failed, "
            f"{report.skipped_count} skipped."
        )
        self.status_message.emit(summary)

        if last_result is not None:
            title = (
                f"{last_result.tool_type.capitalize()} · {last_result.tool_title} · "
                f"{last_result.instance_key}"
            )
            self.preview_requested.emit(Path(last_result.saved_path), title)

        if report.failed_count or report.skipped_count:
            details = "\n".join(failed_lines[:8])
            if len(failed_lines) > 8:
                details += f"\n... {len(failed_lines) - 8} more failure(s)"
            QMessageBox.warning(
                self,
                "Recipe Collection Calculation Finished",
                summary + (f"\n\n{details}" if details else ""),
            )
            return

        QMessageBox.information(
            self,
            "Recipe Collection Calculated",
            summary,
        )

    def _handle_recovery_regeneration_report(self, report: ArtifactRecoveryRegenerationReport) -> None:
        last_result, failed_lines = self._emit_execution_artifacts(report.execution_report)
        summary = self._regeneration_report_summary(report, failed_lines=failed_lines)
        self.status_message.emit(self._regeneration_report_status_line(report))

        if last_result is not None:
            title = (
                f"{last_result.tool_type.capitalize()} · {last_result.tool_title} · "
                f"{last_result.instance_key}"
            )
            self.preview_requested.emit(Path(last_result.saved_path), title)

        if report.success:
            QMessageBox.information(self, "Artifact Recovery Complete", summary)
            return

        QMessageBox.warning(self, "Artifact Recovery Finished", summary)

    def _emit_execution_artifacts(
        self,
        report: ArtifactRecipeExecutionReport | None,
    ) -> tuple[ArtifactCalculationResult | None, list[str]]:
        if report is None:
            return None, []

        last_result: ArtifactCalculationResult | None = None
        failed_lines: list[str] = []
        for item in report.item_reports:
            if item.succeeded and isinstance(item.result, ArtifactCalculationResult):
                last_result = item.result
                self.artifact_saved.emit(item.result)
            elif item.failed:
                failed_lines.append(f"- {item.display_name}: {item.error_text}")
        return last_result, failed_lines

    def _handle_database_rebuild_report(self, report: ArtifactRecoveryDatabaseRebuildReport) -> None:
        summary = self._database_rebuild_report_summary(report)
        if report.rebuilt:
            self.database_rebuilt.emit(report)
            display_name = getattr(report.manifest, "display_name", "linked analysis database")
            self.status_message.emit(f"Rebuilt linked Analysis Database: {display_name}")
            QMessageBox.information(self, "Analysis Database Rebuilt", summary)
            return

        if report.skipped:
            self.status_message.emit("Linked Analysis Database rebuild skipped")
            QMessageBox.information(self, "Analysis Database Rebuild Skipped", summary)
            return

        self.status_message.emit(f"Linked Analysis Database rebuild {report.status}")
        QMessageBox.warning(self, "Analysis Database Rebuild Not Completed", summary)

    def _recovery_report_status_line(self, report: ArtifactRecoveryReport) -> str:
        return (
            "Recovery status: "
            f"{report.up_to_date_count} up to date, "
            f"{report.actionable_count} actionable, "
            f"{report.blocked_count} blocked"
        )

    def _recovery_report_summary(self, report: ArtifactRecoveryReport) -> str:
        lines = [
            f"Collection: {report.collection_display_name}",
            f"Collection ID: {report.collection_id}",
            "",
            f"Total recipes checked: {report.total_count}",
            f"Up to date: {report.up_to_date_count}",
            f"Missing: {report.missing_count}",
            f"Stale: {report.stale_count}",
            f"Freshness unknown: {report.freshness_unknown_count}",
            f"Blocked: {report.blocked_count}",
            f"Actionable: {report.actionable_count}",
        ]
        if report.actionable_recipe_ids:
            lines.extend(["", "Actionable recipe IDs:"])
            lines.extend(f"- {recipe_id}" for recipe_id in report.actionable_recipe_ids[:8])
            if len(report.actionable_recipe_ids) > 8:
                lines.append(f"... {len(report.actionable_recipe_ids) - 8} more")

        item_lines = self._recovery_item_lines(report)
        if item_lines:
            lines.extend(["", "Item status:", *item_lines])
        return "\n".join(lines)

    def _recovery_item_lines(self, report: ArtifactRecoveryReport) -> list[str]:
        lines: list[str] = []
        for item in report.items[:12]:
            detail = ""
            if item.blocked_reasons:
                detail = f" — {item.blocked_reasons[0]}"
            elif item.stale_reasons:
                detail = f" — {item.stale_reasons[0]}"
            elif item.notes:
                detail = f" — {item.notes[0]}"
            action = "actionable" if item.actionable else "not actionable"
            lines.append(f"- {item.display_name}: {item.status} ({action}){detail}")
        if len(report.items) > 12:
            lines.append(f"... {len(report.items) - 12} more item(s)")
        return lines

    def _regeneration_report_status_line(self, report: ArtifactRecoveryRegenerationReport) -> str:
        return (
            "Recovery regeneration: "
            f"{report.succeeded_count} succeeded, "
            f"{report.failed_count} failed, "
            f"{report.skipped_count} skipped"
        )

    def _regeneration_report_summary(
        self,
        report: ArtifactRecoveryRegenerationReport,
        *,
        failed_lines: list[str],
    ) -> str:
        lines = [
            f"Collection ID: {report.collection_id}",
            "",
            f"Requested recipes: {len(report.requested_recipe_ids)}",
            f"Actionable recipes: {len(report.actionable_recipe_ids)}",
            f"Non-actionable recipes: {len(report.non_actionable_recipe_ids)}",
            f"Execution attempted: {report.execution_attempted}",
            f"Succeeded: {report.succeeded_count}",
            f"Failed: {report.failed_count}",
            f"Skipped: {report.skipped_count}",
        ]
        post = report.post_recovery_report
        if post is not None:
            lines.extend(
                [
                    "",
                    "Post-recovery status:",
                    f"Up to date: {post.up_to_date_count}",
                    f"Missing: {post.missing_count}",
                    f"Stale: {post.stale_count}",
                    f"Freshness unknown: {post.freshness_unknown_count}",
                    f"Blocked: {post.blocked_count}",
                ]
            )
        if failed_lines:
            lines.extend(["", "Failures:", *failed_lines[:8]])
            if len(failed_lines) > 8:
                lines.append(f"... {len(failed_lines) - 8} more failure(s)")
        return "\n".join(lines)

    def _database_rebuild_report_summary(self, report: ArtifactRecoveryDatabaseRebuildReport) -> str:
        lines = [
            f"Collection ID: {report.collection_id}",
            f"Source database ID: {report.source_database_id or '(none)'}",
            f"Status: {report.status}",
        ]
        if report.manifest is not None:
            lines.extend(
                [
                    f"Database name: {report.manifest.display_name}",
                    f"Database status: {report.manifest.status}",
                ]
            )
        if report.skipped_reason:
            lines.extend(["", report.skipped_reason])
        if report.blocked_reasons:
            lines.extend(["", "Blocked reasons:", *[f"- {reason}" for reason in report.blocked_reasons]])
        if report.error_text:
            lines.extend(["", f"Error: {report.error_text}"])
        return "\n".join(lines)

    def _save_requested(self, payload: object) -> None:
        if not isinstance(payload, dict):
            QMessageBox.warning(
                self,
                "Invalid Artifact Save",
                "The financial-tool save payload is invalid.",
            )
            return

        try:
            result = self._service.calculate_and_save(payload)
        except Exception as exc:
            message = f"Failed to calculate/save artifact: {exc!r}"
            self.status_message.emit(message)
            QMessageBox.critical(self, "Artifact Save Failed", message)
            return

        self._emit_success(result)

    def _emit_success(self, result: ArtifactCalculationResult) -> None:
        title = (
            f"{result.tool_type.capitalize()} · {result.tool_title} · "
            f"{result.instance_key}"
        )
        message = f"Saved {result.tool_type} artifact: {result.saved_path}"

        self.status_message.emit(message)
        self.artifact_saved.emit(result)
        self.preview_requested.emit(Path(result.saved_path), title)

        QMessageBox.information(self, "Artifact Saved", message)