from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.naming import MarketId


class ArtifactRecipeCollectionDialog(QDialog):
    """Data Manager dialog for saved artifact recipe collections.

    The dialog lists persisted recipe collections and emits execution intent.
    It does not calculate tools, save artifacts, own recipe semantics, or touch
    chart/session/pane/render state.
    """

    execute_requested = Signal(object, object)  # ArtifactRecipeCollection, tuple[str, ...] | None
    recovery_plan_requested = Signal(object, object)  # ArtifactRecipeCollection, tuple[str, ...] | None
    recovery_regeneration_requested = Signal(object, object)  # ArtifactRecipeCollection, tuple[str, ...] | None
    database_rebuild_requested = Signal(object)  # ArtifactRecipeCollection
    database_create_extend_requested = Signal(object)  # ArtifactRecipeCollection
    update_plan_requested = Signal(object, object)  # ArtifactRecipeCollection, tuple[str, ...] | None
    collection_deleted = Signal(object)  # collection_id str
    status_message = Signal(str)

    def __init__(
        self,
        *,
        historical_root: Path,
        market: MarketId,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._historical_root = Path(historical_root)
        self._market = market
        self._store = ArtifactRecipeCollectionStore(historical_root=self._historical_root)
        self._current_collection: ArtifactRecipeCollection | None = None

        self.setWindowTitle("Saved Artifact Recipe Collections")
        self.resize(1180, 700)
        self.setMinimumSize(1040, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        context = QLabel(
            (
                "Recipe collections for "
                f"{market.exchange} / {market.market_type} / "
                f"{market.symbol} / {market.timeframe}\n"
                "Highlighted collection = detail/action target. "
                "Checked recipes = selected subset for checked-recipe and recovery actions; "
                "leave recipes unchecked to target the full collection where offered."
            ),
            self,
        )
        context.setWordWrap(True)
        root.addWidget(context)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        collection_group = QGroupBox("Saved Collections", self)
        collection_layout = QVBoxLayout(collection_group)
        collection_layout.setContentsMargins(8, 12, 8, 8)
        collection_layout.setSpacing(8)

        self._collection_list = QListWidget(collection_group)
        self._collection_list.setMinimumWidth(460)
        self._collection_list.setWordWrap(True)
        self._collection_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._collection_list.setUniformItemSizes(False)
        self._collection_list.currentItemChanged.connect(lambda *_: self._refresh_collection_details())
        collection_layout.addWidget(self._collection_list, 1)

        refresh_button = QPushButton("Refresh", collection_group)
        refresh_button.clicked.connect(self.refresh)
        collection_layout.addWidget(refresh_button)

        body.addWidget(collection_group, 4)

        detail_group = QGroupBox("Collection Details", self)
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 12, 8, 8)
        detail_layout.setSpacing(8)

        self._detail_text = QPlainTextEdit(detail_group)
        self._detail_text.setMinimumWidth(420)
        self._detail_text.setReadOnly(True)
        self._detail_text.setPlaceholderText("Select a collection to inspect it.")
        detail_layout.addWidget(self._detail_text, 1)

        self._recipe_hint_label = QLabel(
            "Check recipes to select a subset. Highlighting a row only focuses details; it does not select it for batch actions.",
            detail_group,
        )
        self._recipe_hint_label.setWordWrap(True)
        detail_layout.addWidget(self._recipe_hint_label)

        self._recipe_list = QListWidget(detail_group)
        self._recipe_list.setMinimumHeight(260)
        self._recipe_list.setWordWrap(True)
        self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._recipe_list.setUniformItemSizes(False)
        self._recipe_list.itemChanged.connect(lambda _item: self._refresh_action_buttons())
        detail_layout.addWidget(self._recipe_list, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        detail_layout.addLayout(action_row)

        self._execute_selected_button = QPushButton("Calculate Checked Recipes", detail_group)
        self._execute_selected_button.setToolTip("Executes only recipes with checked boxes.")
        self._execute_selected_button.clicked.connect(self._execute_checked_recipes)
        action_row.addWidget(self._execute_selected_button)

        self._execute_all_button = QPushButton("Calculate All Recipes", detail_group)
        self._execute_all_button.setToolTip("Executes every recipe in the highlighted collection, regardless of checkbox state.")
        self._execute_all_button.clicked.connect(self._execute_all_recipes)
        action_row.addWidget(self._execute_all_button)

        self._delete_button = QPushButton("Delete Collection", detail_group)
        self._delete_button.clicked.connect(self._delete_selected_collection)
        action_row.addWidget(self._delete_button)

        recovery_row = QHBoxLayout()
        recovery_row.setSpacing(8)
        detail_layout.addLayout(recovery_row)

        self._recovery_plan_button = QPushButton("Check Recovery Status", detail_group)
        self._recovery_plan_button.setToolTip("Checks checked recipes; if none are checked, checks the full highlighted collection.")
        self._recovery_plan_button.clicked.connect(self._check_recovery_status)
        recovery_row.addWidget(self._recovery_plan_button)

        self._recover_actionable_button = QPushButton("Recover Actionable Artifacts", detail_group)
        self._recover_actionable_button.setToolTip("Regenerates only planner-actionable recipes from the checked subset, or from the full collection when none are checked.")
        self._recover_actionable_button.clicked.connect(self._recover_actionable_artifacts)
        recovery_row.addWidget(self._recover_actionable_button)

        self._rebuild_database_button = QPushButton("Rebuild Linked Database", detail_group)
        self._rebuild_database_button.setToolTip("Asks the data layer to rebuild the Analysis Database linked to the highlighted collection.")
        self._rebuild_database_button.clicked.connect(self._rebuild_linked_database)
        recovery_row.addWidget(self._rebuild_database_button)

        self._update_plan_button = QPushButton("Plan Updates...", detail_group)
        self._update_plan_button.setToolTip("Builds a recipe-collection update plan through the Data Manager update service.")
        self._update_plan_button.clicked.connect(self._plan_updates)
        recovery_row.addWidget(self._update_plan_button)

        self._create_database_button = QPushButton("Create/Extend Database...", detail_group)
        self._create_database_button.setToolTip("Resolves current collection artifacts before creating or extending a draft Analysis Database manifest.")
        self._create_database_button.clicked.connect(self._create_extend_database)
        recovery_row.addWidget(self._create_database_button)

        body.addWidget(detail_group, 5)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self.refresh()

    def refresh(self) -> None:
        self._collection_list.clear()
        self._recipe_list.clear()
        self._detail_text.clear()
        self._current_collection = None

        summaries = self._store.list_collections(market=self._market)
        for summary in summaries:
            label = (
                f"{summary.display_name}\n"
                f"{summary.collection_id} · {summary.recipe_count} recipe(s)"
            )
            item = QListWidgetItem(label, self._collection_list)
            item.setData(Qt.ItemDataRole.UserRole, summary.collection_id)
            item.setToolTip(str(summary.collection_path))

        if summaries:
            self._collection_list.setCurrentRow(0)
        else:
            self._detail_text.setPlainText("No saved recipe collections found for this dataset.")

        self._refresh_action_buttons()
        self.status_message.emit(f"Loaded {len(summaries)} artifact recipe collection(s)")

    def _selected_collection_id(self) -> str:
        item = self._collection_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _selected_collection(self) -> ArtifactRecipeCollection | None:
        collection_id = self._selected_collection_id()
        if not collection_id:
            return None

        try:
            return self._store.load_collection(
                market=self._market,
                collection_id=collection_id,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Collection Load Failed",
                f"Failed to load recipe collection: {exc!r}",
            )
            return None

    def _refresh_collection_details(self) -> None:
        collection = self._selected_collection()
        self._current_collection = collection

        self._recipe_list.blockSignals(True)
        self._recipe_list.clear()

        if collection is None:
            self._detail_text.setPlainText("Select a collection to inspect it.")
            self._recipe_list.blockSignals(False)
            self._refresh_action_buttons()
            return

        self._detail_text.setPlainText(self._collection_details(collection))
        for index, recipe in enumerate(collection.recipe_snapshots, start=1):
            outputs = ", ".join(recipe.output_names[:3]) if recipe.output_names else "no outputs"
            if len(recipe.output_names) > 3:
                outputs += f", ... {len(recipe.output_names) - 3} more"
            label = (
                f"{index}. {recipe.display_name}\n"
                f"{recipe.recipe_id} · {recipe.tool_type}/{recipe.tool_key} · {outputs}"
            )
            item = QListWidgetItem(label, self._recipe_list)
            item.setData(Qt.ItemDataRole.UserRole, recipe.recipe_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)

        self._recipe_list.blockSignals(False)
        self._refresh_action_buttons()
        self.status_message.emit(f"Selected recipe collection: {collection.display_name}")

    def _checked_recipe_ids(self) -> tuple[str, ...]:
        recipe_ids: list[str] = []
        for row in range(self._recipe_list.count()):
            item = self._recipe_list.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            recipe_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if recipe_id:
                recipe_ids.append(recipe_id)
        return tuple(recipe_ids)

    def _execute_checked_recipes(self) -> None:
        collection = self._current_collection
        if collection is None:
            return

        recipe_ids = self._checked_recipe_ids()
        if not recipe_ids:
            QMessageBox.warning(
                self,
                "Recipe Collection",
                "Check one or more recipes before calculating selected recipes.",
            )
            return

        self.execute_requested.emit(collection, recipe_ids)
        self.status_message.emit(
            f"Calculating {len(recipe_ids)} recipe(s) from collection: {collection.display_name}"
        )

    def _execute_all_recipes(self) -> None:
        collection = self._current_collection
        if collection is None:
            return

        answer = QMessageBox.question(
            self,
            "Calculate Recipe Collection",
            (
                f"Calculate all {len(collection.recipe_snapshots)} recipe(s) in "
                f"'{collection.display_name}'?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.execute_requested.emit(collection, None)
        self.status_message.emit(f"Calculating full recipe collection: {collection.display_name}")

    def _selected_recovery_recipe_ids(self) -> tuple[str, ...] | None:
        checked = self._checked_recipe_ids()
        return checked or None

    def _check_recovery_status(self) -> None:
        collection = self._current_collection
        if collection is None:
            return

        selected_recipe_ids = self._selected_recovery_recipe_ids()
        self.recovery_plan_requested.emit(collection, selected_recipe_ids)
        if selected_recipe_ids:
            self.status_message.emit(
                f"Checking recovery status for {len(selected_recipe_ids)} checked recipe(s)"
            )
        else:
            self.status_message.emit(
                f"Checking recovery status for full collection: {collection.display_name}"
            )

    def _recover_actionable_artifacts(self) -> None:
        collection = self._current_collection
        if collection is None:
            return

        selected_recipe_ids = self._selected_recovery_recipe_ids()
        target_label = (
            f"{len(selected_recipe_ids)} checked recipe(s)"
            if selected_recipe_ids
            else f"all {len(collection.recipe_snapshots)} recipe(s)"
        )
        answer = QMessageBox.question(
            self,
            "Recover Actionable Artifacts",
            (
                f"Plan recovery and regenerate actionable artifacts for {target_label} "
                f"in '{collection.display_name}'?\n\n"
                "Only recipes reported as actionable by the recovery planner will be executed."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.recovery_regeneration_requested.emit(collection, selected_recipe_ids)
        self.status_message.emit(f"Recovering actionable artifacts for: {collection.display_name}")

    def _rebuild_linked_database(self) -> None:
        collection = self._current_collection
        if collection is None:
            return
        if not collection.source_database_id:
            QMessageBox.warning(
                self,
                "Rebuild Linked Database",
                "This recipe collection is not linked to an Analysis Database.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Rebuild Linked Analysis Database",
            (
                f"Rebuild linked Analysis Database '{collection.source_database_id}' "
                f"from collection '{collection.display_name}'?\n\n"
                "The data layer will verify recovered artifacts before materializing dataframe.csv."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.database_rebuild_requested.emit(collection)
        self.status_message.emit(
            f"Rebuilding linked Analysis Database: {collection.source_database_id}"
        )

    def _plan_updates(self) -> None:
        collection = self._current_collection
        if collection is None:
            QMessageBox.information(
                self,
                "Data Manager Update",
                "Select a recipe collection before planning updates.",
            )
            return

        selected_recipe_ids = self._selected_recovery_recipe_ids()
        self.update_plan_requested.emit(collection, selected_recipe_ids)
        if selected_recipe_ids:
            self.status_message.emit(
                f"Planning updates for {len(selected_recipe_ids)} checked recipe(s)"
            )
        else:
            self.status_message.emit(
                f"Planning updates for full collection: {collection.display_name}"
            )

    def _create_extend_database(self) -> None:
        collection = self._current_collection
        if collection is None:
            QMessageBox.information(
                self,
                "Analysis Database",
                "Select a recipe collection before creating or extending a database.",
            )
            return

        self.database_create_extend_requested.emit(collection)
        self.status_message.emit(
            f"Opening Analysis Database draft workflow for: {collection.display_name}"
        )

    def _delete_selected_collection(self) -> None:
        collection = self._current_collection
        if collection is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Recipe Collection",
            (
                f"Delete recipe collection '{collection.display_name}'?\n\n"
                "This deletes only the collection JSON, not individual recipe JSON files "
                "and not saved artifacts."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._store.delete_collection(
                market=self._market,
                collection_id=collection.collection_id,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Collection Delete Failed",
                f"Failed to delete recipe collection: {exc!r}",
            )
            return

        self.collection_deleted.emit(collection.collection_id)
        self.status_message.emit(f"Deleted recipe collection: {collection.display_name}")
        self.refresh()

    def _refresh_action_buttons(self) -> None:
        has_collection = self._current_collection is not None
        checked_count = len(self._checked_recipe_ids()) if has_collection else 0
        has_linked_database = bool(
            has_collection and getattr(self._current_collection, "source_database_id", None)
        )
        self._execute_selected_button.setEnabled(has_collection and checked_count > 0)
        self._execute_all_button.setEnabled(has_collection)
        self._delete_button.setEnabled(has_collection)
        self._recovery_plan_button.setEnabled(has_collection)
        self._recover_actionable_button.setEnabled(has_collection)
        self._rebuild_database_button.setEnabled(has_linked_database)
        self._update_plan_button.setEnabled(has_collection)
        self._create_database_button.setEnabled(has_collection)

    def _collection_details(self, collection: ArtifactRecipeCollection) -> str:
        source_database = collection.source_database_id or "(none)"
        dependency_lines = [
            f"- {edge.from_recipe_id} -> {edge.to_recipe_id}: {edge.reason or '(no reason)'}"
            for edge in collection.dependency_edges
        ]
        if not dependency_lines:
            dependency_lines = ["(none)"]

        recipe_lines = [
            f"- {recipe.display_name} ({recipe.tool_type}/{recipe.tool_key})"
            for recipe in collection.recipe_snapshots
        ]

        return "\n".join(
            [
                f"Name: {collection.display_name}",
                f"Collection ID: {collection.collection_id}",
                f"Hash: {collection.collection_hash_short}",
                f"Recipes: {len(collection.recipe_snapshots)}",
                f"Source database ID: {source_database}",
                f"Description: {collection.description or '(none)'}",
                "",
                "Recipes:",
                "\n".join(recipe_lines) if recipe_lines else "(none)",
                "",
                "Dependency metadata:",
                "\n".join(dependency_lines),
            ]
        )
