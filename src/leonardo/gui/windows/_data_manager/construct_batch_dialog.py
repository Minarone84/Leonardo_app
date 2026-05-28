from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.windows._data_manager.dialog_geometry import (
    apply_data_manager_dialog_initial_size,
)


_BACKEND_PLACEHOLDER_TOOLTIP = "Construct batch backend planner is not implemented yet."


class ConstructBatchBuilderDialog(QDialog):
    """
    GUI shell for the future Data Manager Construct Batch Builder.

    The dialog exposes the intended batch workflow structure without planning
    recipes, saving recipe collections, calculating artifacts, or mutating
    Analysis Databases. Backend-dependent actions remain disabled until a later
    data-layer implementation owns those responsibilities.
    """

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
            "Construct batch workflows are prepared here for future backend "
            "planning. This shell does not create recipes, calculate artifacts, "
            "or modify Analysis Databases.",
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
        body.addLayout(right, 1)

        left.addWidget(self._build_mode_group())
        left.addWidget(self._build_construct_group())
        left.addWidget(self._build_unary_group())
        right.addWidget(self._build_delta_group())
        right.addWidget(self._build_parameters_group())
        right.addWidget(self._build_preflight_group(), 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)

        self._preview_plan_button = self._disabled_action_button("Preview Plan")
        self._save_recipes_button = self._disabled_action_button("Save Recipes")
        self._save_collection_button = self._disabled_action_button("Save as Collection")
        self._calculate_artifacts_button = self._disabled_action_button(
            "Calculate Artifacts"
        )
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

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("Construct batch mode", self)
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel("Unary source expansion", group))
        layout.addWidget(QLabel("Binary delta expansion", group))
        note = QLabel(
            "Topology-template constructs such as braids, braid_instability, "
            "trap_area, and dynamic_binning remain future structured-template "
            "workflows.",
            group,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return group

    def _build_construct_group(self) -> QGroupBox:
        group = QGroupBox("Construct selection", self)
        layout = QVBoxLayout(group)
        self._construct_list = QListWidget(group)
        for name in (
            "derivative",
            "angle",
            "percent_span_angle",
            "angle_momentum",
            "delta",
        ):
            QListWidgetItem(name, self._construct_list)
        layout.addWidget(self._construct_list)
        return group

    def _build_unary_group(self) -> QGroupBox:
        group = QGroupBox("Unary workflow placeholder", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        self._source_group_combo = QComboBox(group)
        self._source_group_combo.addItems(
            (
                "All indicators",
                "All oscillators",
                "All constructs",
                "Selected saved artifact columns",
            )
        )
        self._source_group_combo.setEnabled(False)
        self._source_group_combo.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addRow("Source group", self._source_group_combo)

        self._source_preview = QPlainTextEdit(group)
        self._source_preview.setReadOnly(True)
        self._source_preview.setPlainText("Source preview placeholder")
        self._source_preview.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addRow("Source preview", self._source_preview)
        return group

    def _build_delta_group(self) -> QGroupBox:
        group = QGroupBox("Binary delta workflow placeholder", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)

        fixed_source = QComboBox(group)
        fixed_source.addItem("Fixed source placeholder")
        fixed_source.setEnabled(False)
        fixed_source.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addRow("Fixed source", fixed_source)

        fixed_role = QComboBox(group)
        fixed_role.addItems(("minuend", "subtrahend"))
        fixed_role.setEnabled(False)
        fixed_role.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addRow("Fixed role", fixed_role)

        variable_source = QComboBox(group)
        variable_source.addItem("Variable source group placeholder")
        variable_source.setEnabled(False)
        variable_source.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addRow("Variable source group", variable_source)

        explanation = QLabel("delta = minuend - subtrahend", group)
        explanation.setWordWrap(True)
        layout.addRow("Direction", explanation)
        return group

    def _build_parameters_group(self) -> QGroupBox:
        group = QGroupBox("Parameters placeholder", self)
        layout = QVBoxLayout(group)
        for text in (
            "derivative order",
            "angle momentum window",
            "percent span windows",
            "delta mode absolute/percent",
        ):
            label = QLabel(text, group)
            label.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
            layout.addWidget(label)
        return group

    def _build_preflight_group(self) -> QGroupBox:
        group = QGroupBox("Preflight placeholder", self)
        layout = QVBoxLayout(group)
        self._preflight_preview = QPlainTextEdit(group)
        self._preflight_preview.setReadOnly(True)
        self._preflight_preview.setPlainText(
            "\n".join(
                (
                    "planned recipes",
                    "blocked sources",
                    "estimated outputs",
                    "timestamp alignment status",
                    "common timestamp range",
                )
            )
        )
        self._preflight_preview.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        layout.addWidget(self._preflight_preview, 1)
        return group

    def _disabled_action_button(self, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setEnabled(False)
        button.setToolTip(_BACKEND_PLACEHOLDER_TOOLTIP)
        return button
