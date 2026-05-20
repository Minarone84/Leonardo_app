from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseManifest
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.analysis_database_feature_builder import (
    build_manifest_features_from_saved_columns,
)
from leonardo.gui.windows._data_manager.button_rack import make_button_rack
from leonardo.gui.windows._data_manager.saved_artifact_selector_widget import SavedArtifactColumn


class AnalysisDatabaseBuilderWidget(QGroupBox):
    """Create draft Analysis Database manifests from selected saved artifacts.

    This widget creates durable draft manifests only. It does not materialize
    merged dataframes, compute financial tools, apply chart-local studies, or
    touch pane/render state.
    """

    draft_saved = Signal(object)  # AnalysisDatabaseManifest
    status_message = Signal(str)

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Database seed creator", parent)
        self._historical_root = Path(historical_root)
        self._store = AnalysisDatabaseStore(historical_root=self._historical_root)
        self._market: Optional[MarketId] = None
        self._name_prefix = ""
        self._selected_columns: list[SavedArtifactColumn] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        content = QVBoxLayout()
        content.setSpacing(8)
        root.addLayout(content, 1)

        self._summary = QLabel("Select a dataset and saved artifact columns to prepare an analysis database.", self)
        self._summary.setWordWrap(True)
        content.addWidget(self._summary)

        form = QFormLayout()
        form.setSpacing(8)
        content.addLayout(form)

        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("Example: BTCUSDT_30m_trend_pack")
        self._name_edit.textChanged.connect(self._refresh_state)
        form.addRow("Database name", self._name_edit)

        self._description_edit = QTextEdit(self)
        self._description_edit.setPlaceholderText("Optional user description for this analysis database.")
        self._description_edit.setAcceptRichText(False)
        self._description_edit.setFixedHeight(72)
        form.addRow("Description", self._description_edit)

        self._include_volume = QCheckBox("Include volume", self)
        self._include_volume.setChecked(True)

        self._button = QPushButton("Save Draft Manifest", self)
        self._button.setEnabled(False)
        self._button.clicked.connect(self._save_draft_manifest)

        base_action_row = QHBoxLayout()
        base_action_row.setSpacing(8)
        base_action_row.addWidget(QLabel("Base columns", self))
        base_action_row.addWidget(self._include_volume)
        base_action_row.addStretch(1)
        content.addLayout(base_action_row, 0)

        self._base_policy = QLabel("Locked by contract: ts_ms, open, high, low, close. Volume is selectable.", self)
        self._base_policy.setWordWrap(True)
        content.addWidget(self._base_policy)
        content.addStretch(1)

        root.addLayout(make_button_rack(self._button), 0)

    def set_market(self, market: Optional[MarketId]) -> None:
        previous_prefix = self._name_prefix
        self._market = market
        self._name_prefix = "" if market is None else self._store.default_display_name_prefix(market=market)
        self._seed_name_prefix(previous_prefix=previous_prefix)
        self._refresh_state()

    def set_selected_columns(self, columns: Sequence[object]) -> None:
        self._selected_columns = [column for column in columns if isinstance(column, SavedArtifactColumn)]
        self._refresh_state()

    def _refresh_state(self) -> None:
        if self._market is None:
            self._summary.setText("Select a dataset and saved artifact columns to prepare an analysis database.")
            self._button.setEnabled(False)
            return

        display_name = self._name_edit.text().strip()
        name_error = self._display_name_error(display_name)
        name_ready = bool(display_name) and name_error == ""
        selected_count = len(self._selected_columns)
        name_hint = "Database names cannot contain spaces." if not name_error else name_error
        self._summary.setText(
            "Selected dataset: "
            f"{self._market.exchange} / {self._market.market_type} / {self._market.symbol} / {self._market.timeframe}\n"
            f"Selected artifact columns: {selected_count}\n\n"
            f"Default database-name prefix: {self._name_prefix}\n"
            f"Name policy: {name_hint}\n\n"
            "Save Draft Manifest will persist the current selection and description. "
            "It will not create dataframe.csv yet."
        )
        self._button.setEnabled(name_ready)

    def _save_draft_manifest(self) -> None:
        if self._market is None:
            QMessageBox.warning(self, "Analysis Database", "Select a dataset before saving a draft database.")
            return

        display_name = self._name_edit.text().strip()
        if not display_name:
            QMessageBox.warning(self, "Analysis Database", "Enter a database name before saving a draft database.")
            return
        try:
            display_name = self._store.validate_database_display_name(display_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Analysis Database", str(exc))
            return

        try:
            feature_sources, feature_columns = build_manifest_features_from_saved_columns(
                historical_root=self._historical_root,
                market=self._market,
                selected_columns=self._selected_columns,
            )
            manifest = self._store.build_draft_manifest(
                market=self._market,
                display_name=display_name,
                user_description=self._description_edit.toPlainText().strip(),
                include_volume=self._include_volume.isChecked(),
                feature_sources=feature_sources,
                feature_columns=feature_columns,
            )
            self._store.save_manifest(manifest, overwrite=False)
        except FileExistsError as exc:
            QMessageBox.warning(self, "Analysis Database", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Analysis Database", f"Failed to save draft manifest:\n{exc!r}")
            return

        message = f"Draft analysis database saved: {manifest.display_name}"
        self.status_message.emit(message)
        self.draft_saved.emit(manifest)
        self._refresh_state()

    def _seed_name_prefix(self, *, previous_prefix: str) -> None:
        current = self._name_edit.text().strip()
        should_replace = not current or (bool(previous_prefix) and current == previous_prefix)
        if self._market is None:
            if should_replace:
                with QSignalBlocker(self._name_edit):
                    self._name_edit.clear()
            return
        if should_replace:
            with QSignalBlocker(self._name_edit):
                self._name_edit.setText(self._name_prefix)
                self._name_edit.setCursorPosition(len(self._name_prefix))

    def _display_name_error(self, display_name: str) -> str:
        try:
            self._store.validate_database_display_name(display_name)
        except ValueError as exc:
            return str(exc)
        return ""
