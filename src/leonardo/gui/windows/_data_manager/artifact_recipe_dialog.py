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
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.dialog_geometry import (
    apply_data_manager_dialog_initial_width,
)


class ArtifactRecipeDialog(QDialog):
    """Small Data Manager dialog for one-at-a-time artifact recipes.

    This dialog only lists recipes and emits user intent. It does not calculate
    tools, save artifacts, own recipe semantics, or mutate chart/session state.
    """

    load_requested = Signal(object)  # ArtifactRecipe
    calculate_requested = Signal(object)  # ArtifactRecipe
    create_collection_requested = Signal(object, object, object)  # tuple[ArtifactRecipe, ...], display_name, description
    recipe_deleted = Signal(object)  # recipe_id str
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
        self._store = ArtifactRecipeStore(historical_root=self._historical_root)

        self.setWindowTitle("Saved Artifact Recipes")
        self.setMinimumSize(960, 560)
        apply_data_manager_dialog_initial_width(
            self,
            default_width=1080,
            default_height=640,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        context = QLabel(
            (
                "Recipes for "
                f"{market.exchange} / {market.market_type} / "
                f"{market.symbol} / {market.timeframe}\n"
                "Highlighted recipe = detail/load/calculate/delete target. "
                "Checked recipes = selected recipes for collection creation."
            ),
            self,
        )
        context.setWordWrap(True)
        root.addWidget(context)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        list_group = QGroupBox("Saved Recipes", self)
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(8, 12, 8, 8)
        list_layout.setSpacing(8)

        self._recipe_list = QListWidget(list_group)
        self._recipe_list.setMinimumWidth(480)
        self._recipe_list.setWordWrap(True)
        self._recipe_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._recipe_list.setUniformItemSizes(False)
        self._recipe_list.currentItemChanged.connect(lambda *_: self._refresh_details())
        self._recipe_list.itemChanged.connect(lambda _item: self._refresh_action_buttons())
        list_layout.addWidget(self._recipe_list, 1)

        refresh_button = QPushButton("Refresh", list_group)
        refresh_button.clicked.connect(self.refresh)
        list_layout.addWidget(refresh_button)

        body.addWidget(list_group, 5)

        detail_group = QGroupBox("Recipe Details", self)
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 12, 8, 8)
        detail_layout.setSpacing(8)

        self._detail_label = QLabel("Select a recipe.", detail_group)
        self._detail_label.setMinimumWidth(380)
        self._detail_label.setWordWrap(True)
        detail_layout.addWidget(self._detail_label, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        detail_layout.addLayout(action_row)

        self._load_button = QPushButton("Load Highlighted Recipe", detail_group)
        self._load_button.clicked.connect(self._load_selected)
        action_row.addWidget(self._load_button)

        self._calculate_button = QPushButton("Calculate Highlighted Recipe", detail_group)
        self._calculate_button.clicked.connect(self._calculate_selected)
        action_row.addWidget(self._calculate_button)

        self._delete_button = QPushButton("Delete Highlighted Recipe", detail_group)
        self._delete_button.clicked.connect(self._delete_selected)
        action_row.addWidget(self._delete_button)

        self._create_collection_button = QPushButton("Create Collection from Checked Recipes...", detail_group)
        self._create_collection_button.clicked.connect(self._create_collection_from_checked)
        action_row.addWidget(self._create_collection_button)

        body.addWidget(detail_group, 4)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self.refresh()

    def refresh(self) -> None:
        self._recipe_list.blockSignals(True)
        self._recipe_list.clear()

        summaries = self._store.list_recipes(market=self._market)
        for summary in summaries:
            label = f"{summary.display_name}\n{summary.recipe_id}"
            item = QListWidgetItem(label, self._recipe_list)
            item.setData(Qt.ItemDataRole.UserRole, summary.recipe_id)
            item.setToolTip(str(summary.recipe_path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)

        self._recipe_list.blockSignals(False)
        self._refresh_details()
        self.status_message.emit(f"Loaded {len(summaries)} artifact recipe(s)")

    def _selected_recipe_id(self) -> str:
        item = self._recipe_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "").strip()

    def _selected_recipe(self) -> ArtifactRecipe | None:
        recipe_id = self._selected_recipe_id()
        if not recipe_id:
            return None

        try:
            return self._store.load_recipe(
                market=self._market,
                recipe_id=recipe_id,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Recipe Load Failed",
                f"Failed to load recipe: {exc!r}",
            )
            return None

    def _refresh_details(self) -> None:
        recipe = self._selected_recipe()
        self._refresh_action_buttons()

        if recipe is None:
            self._detail_label.setText("Select a recipe.")
            return

        output_text = ", ".join(recipe.output_names[:6]) if recipe.output_names else "(none)"
        if len(recipe.output_names) > 6:
            output_text += f", ... {len(recipe.output_names) - 6} more"

        input_text = "\n".join(
            f"  - {key}: {value}"
            for key, value in sorted(recipe.input_bindings.items())
        )
        if not input_text:
            input_text = "  - none"

        param_text = "\n".join(
            f"  - {key}: {value}"
            for key, value in sorted(recipe.params.items())
        )
        if not param_text:
            param_text = "  - none"

        self._detail_label.setText(
            "\n".join(
                [
                    f"Name: {recipe.display_name}",
                    f"Recipe ID: {recipe.recipe_id}",
                    f"Tool: {recipe.tool_title} ({recipe.tool_type}/{recipe.tool_key})",
                    f"Outputs: {output_text}",
                    "Inputs:",
                    input_text,
                    "Parameters:",
                    param_text,
                ]
            )
        )

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

    def _checked_recipes(self) -> tuple[ArtifactRecipe, ...]:
        recipes: list[ArtifactRecipe] = []
        for recipe_id in self._checked_recipe_ids():
            try:
                recipes.append(
                    self._store.load_recipe(
                        market=self._market,
                        recipe_id=recipe_id,
                    )
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Recipe Load Failed",
                    f"Failed to load recipe for collection: {exc!r}",
                )
                return ()
        return tuple(recipes)

    def _refresh_action_buttons(self) -> None:
        has_selected_recipe = bool(self._selected_recipe_id())
        self._load_button.setEnabled(has_selected_recipe)
        self._calculate_button.setEnabled(has_selected_recipe)
        self._delete_button.setEnabled(has_selected_recipe)
        self._create_collection_button.setEnabled(bool(self._checked_recipe_ids()))

    def _create_collection_from_checked(self) -> None:
        recipes = self._checked_recipes()
        if not recipes:
            QMessageBox.warning(
                self,
                "Recipe Collection",
                "Check one or more recipes before creating a collection.",
            )
            return

        default_name = f"{self._market.symbol}_{self._market.timeframe}_recipe_collection"
        display_name, accepted = QInputDialog.getText(
            self,
            "Create Recipe Collection",
            "Collection name",
            text=default_name,
        )
        if not accepted:
            return

        display_name = str(display_name or "").strip()
        if not display_name:
            QMessageBox.warning(
                self,
                "Recipe Collection",
                "Enter a collection name before saving.",
            )
            return

        description, accepted = QInputDialog.getMultiLineText(
            self,
            "Recipe Collection Description",
            "Description (optional)",
            "",
        )
        if not accepted:
            description = ""

        self.create_collection_requested.emit(
            recipes,
            display_name,
            str(description or "").strip(),
        )
        self.status_message.emit(
            f"Creating recipe collection '{display_name}' from {len(recipes)} recipe(s)"
        )

    def _load_selected(self) -> None:
        recipe = self._selected_recipe()
        if recipe is None:
            return

        self.load_requested.emit(recipe)
        self.status_message.emit(f"Loaded artifact recipe: {recipe.display_name}")

    def _calculate_selected(self) -> None:
        recipe = self._selected_recipe()
        if recipe is None:
            return

        self.calculate_requested.emit(recipe)
        self.status_message.emit(f"Calculating artifact recipe: {recipe.display_name}")

    def _delete_selected(self) -> None:
        recipe = self._selected_recipe()
        if recipe is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Artifact Recipe",
            (
                f"Delete recipe '{recipe.display_name}'?\n\n"
                "This deletes only the recipe JSON, not any saved artifacts."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self._store.delete_recipe(
                market=self._market,
                recipe_id=recipe.recipe_id,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Recipe Delete Failed",
                f"Failed to delete recipe: {exc!r}",
            )
            return

        self.recipe_deleted.emit(recipe.recipe_id)
        self.status_message.emit(f"Deleted artifact recipe: {recipe.display_name}")
        self.refresh()
