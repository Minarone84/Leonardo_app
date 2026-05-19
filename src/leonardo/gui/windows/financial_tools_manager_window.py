from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data.historical.derived_store_csv import DerivedArtifactRef, DerivedCsvStore
from leonardo.data.historical.paths import default_historical_root
from leonardo.data.naming import canonicalize
from leonardo.financial_tools.ft_naming import (
    build_binding_slug_from_params,
    build_construct_instance_key_from_params,
)
from leonardo.financial_tools.ft_specs import (
    ToolSpec,
    build_default_params,
    format_output_names,
    format_output_signals,
    get_construct_specs,
    get_indicator_specs,
    get_oscillator_specs,
)


class FinancialToolsManagerWindow(QDialog):
    """
    UI-only manager window for financial tools.

    Responsibilities in this phase:
    - Let the user choose a tool type (indicator / oscillator / construct)
    - Let the user choose a specific tool from that type
    - Dynamically build a parameter form from the tool spec
    - Show a scrollable list of saved instances of the same tool family
    - Expose Apply / Save intents via signals

    Important:
    - This window does NOT compute tools.
    - This window does NOT save files itself.
    - This window does NOT mutate the chart directly.
    - It only gathers user intent and emits structured requests.
    """

    apply_requested = Signal(dict)
    save_requested = Signal(dict)
    recipe_requested = Signal(dict)

    TOOL_TYPE_ITEMS = (
        ("", "Select tool type"),
        ("indicator", "Indicator"),
        ("oscillator", "Oscillator"),
        ("construct", "Construct"),
    )

    UNARY_SOURCE_FAMILY_ITEMS = (
        ("default", "Default Source"),
        ("indicator", "Indicator Sources"),
        ("oscillator", "Oscillator Sources"),
        ("construct", "Construct Sources"),
    )

    DEFAULT_UNARY_SOURCE_OPTIONS = (
        ("Open", "open"),
        ("High", "high"),
        ("Low", "low"),
        ("Close", "close"),
        ("Volume", "volume"),
    )

    NON_SELECTABLE_ARTIFACT_COLUMNS = {
        "time",
        "timeframe",
        "ts_ms",
        "vwap_color",
    }

    UTC_FRACTAL_CHOICES = (3, 5, 7, 9, 11)
    UTC_BREAK_MODE_CHOICES = (
        ("Close", "close"),
        ("Wick", "wick"),
        ("Hybrid", "hybrid"),
    )

    def __init__(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        source_options_provider: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
        historical_root: Optional[Path] = None,
        save_only: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._exchange = str(exchange)
        self._market_type = str(market_type)
        self._symbol = str(symbol)
        self._timeframe = str(timeframe)
        self._historical_root = Path(historical_root) if historical_root is not None else default_historical_root()
        self._save_only = bool(save_only)

        self._current_spec: Optional[ToolSpec] = None
        self._param_editors: Dict[str, QWidget] = {}
        self._saved_refs: List[DerivedArtifactRef] = []
        self._source_options_provider = source_options_provider

        self._source_family_editors: Dict[str, QComboBox] = {}
        self._source_value_editors: Dict[str, QComboBox] = {}

        self.setWindowTitle("Artifact Calculator" if self._save_only else "Financial Tool Manager")
        self.setModal(False)
        self.resize(820, 560)

        self.setStyleSheet(
            """
            QDialog {
                background-color: rgb(18, 18, 22);
                color: rgb(220, 220, 230);
            }
            QLabel {
                color: rgb(210, 210, 220);
            }
            QGroupBox {
                border: 1px solid rgb(58, 58, 66);
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: rgb(22, 22, 28);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px 0 4px;
                color: rgb(220, 220, 230);
            }
            QComboBox, QListWidget, QLineEdit {
                background-color: rgb(30, 30, 36);
                color: rgb(230, 230, 240);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 4px 6px;
            }
            QPushButton {
                color: rgb(230, 230, 240);
                background-color: rgb(40, 40, 48);
                border: 1px solid rgb(68, 68, 78);
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:disabled {
                color: rgb(130, 130, 140);
                background-color: rgb(30, 30, 36);
                border: 1px solid rgb(50, 50, 58);
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QCheckBox {
                color: rgb(230, 230, 240);
                spacing: 8px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_context_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        body.addLayout(left_col, 3)

        right_col = QVBoxLayout()
        right_col.setSpacing(10)
        body.addLayout(right_col, 2)

        left_col.addWidget(self._build_selection_group())
        left_col.addWidget(self._build_configuration_group(), 1)
        left_col.addWidget(self._build_action_row())

        right_col.addWidget(self._build_saved_instances_group(), 1)

        self._populate_tool_type_combo()
        self._set_form_placeholder("Select a tool type and then a tool to configure.")
        self._refresh_buttons()
        self._populate_saved_instances(None)

    # ------------------------------------------------------------------
    # Public preload/edit API
    # ------------------------------------------------------------------

    def load_study_for_edit(
        self,
        *,
        tool_type: str,
        tool_key: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Preload the window with an existing study configuration so the user can
        edit it without re-selecting tool type, tool, and parameter values.

        Returns True on success, False if the requested tool could not be loaded.
        """
        normalized_type = str(tool_type).strip().lower()
        normalized_key = str(tool_key).strip().lower()
        param_values = dict(params or {})

        if not normalized_type or not normalized_key:
            return False

        if not self._set_combo_value(self._tool_type_combo, normalized_type):
            return False

        self._on_tool_type_changed()

        if not self._set_combo_value(self._tool_combo, normalized_key):
            return False

        self._on_tool_changed()

        if self._current_spec is None:
            return False

        self._apply_param_values_to_form(param_values)

        self._status_label.setText(
            f"Loaded for edit: {self._current_spec.title}"
        )
        return True

    def load_payload_for_recipe(self, payload: Dict[str, Any]) -> bool:
        """Preload this form from a saved artifact recipe payload.

        The payload remains a financial-tool intent dictionary. Loading it only
        updates UI controls; it does not calculate, save, apply, or mutate chart
        state.
        """
        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        params = dict(payload.get("params", {}) or {})

        return self.load_study_for_edit(
            tool_type=tool_type,
            tool_key=tool_key,
            params=params,
        )

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------

    def _build_context_header(self) -> QWidget:
        box = QFrame(self)
        box.setFrameShape(QFrame.StyledPanel)
        box.setStyleSheet(
            """
            QFrame {
                border: 1px solid rgb(52, 52, 60);
                background-color: rgb(24, 24, 28);
                border-radius: 6px;
            }
            """
        )

        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        title_text = "Data Manager Dataset Context" if self._save_only else "Historical Chart Context"
        title = QLabel(title_text, box)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        exchange_display = self._exchange[:1].upper() + self._exchange[1:] if self._exchange else self._exchange
        dataset_text = (
            f"Exchange: {exchange_display}   |   "
            f"Market type: {self._market_type}   |   "
            f"Asset: {self._symbol}   |   "
            f"Timeframe: {self._timeframe}"
        )
        self._context_label = QLabel(dataset_text, box)
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        return box

    def _build_selection_group(self) -> QGroupBox:
        group = QGroupBox("Tool Selection", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(8)

        self._tool_type_combo = QComboBox(group)
        self._tool_type_combo.currentIndexChanged.connect(self._on_tool_type_changed)
        layout.addRow("Tool Type", self._tool_type_combo)

        self._tool_combo = QComboBox(group)
        self._tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        layout.addRow("Tool", self._tool_combo)

        return group

    def _build_configuration_group(self) -> QGroupBox:
        group = QGroupBox("Configuration", self)

        outer = QVBoxLayout(group)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(8)

        self._inputs_summary_label = QLabel("", group)
        self._inputs_summary_label.setWordWrap(True)
        outer.addWidget(self._inputs_summary_label)

        self._behavior_summary_label = QLabel("", group)
        self._behavior_summary_label.setWordWrap(True)
        outer.addWidget(self._behavior_summary_label)

        self._output_preview_label = QLabel("", group)
        self._output_preview_label.setWordWrap(True)
        outer.addWidget(self._output_preview_label)

        self._instance_key_preview_label = QLabel("", group)
        self._instance_key_preview_label.setWordWrap(True)
        outer.addWidget(self._instance_key_preview_label)

        self._form_scroll = QScrollArea(group)
        self._form_scroll.setWidgetResizable(True)
        self._form_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._form_host = QWidget(self._form_scroll)
        self._form_layout = QFormLayout(self._form_host)
        self._form_layout.setContentsMargins(6, 6, 6, 6)
        self._form_layout.setSpacing(8)

        self._form_scroll.setWidget(self._form_host)
        outer.addWidget(self._form_scroll, 1)

        return group

    def _build_action_row(self) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._status_label = QLabel("No tool selected.", row)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label, 1)

        layout.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self._apply_button = QPushButton("Apply", row)
        self._apply_button.clicked.connect(self._on_apply_clicked)
        self._apply_button.setVisible(not self._save_only)
        layout.addWidget(self._apply_button)

        self._recipe_button = QPushButton("Save Recipe", row)
        self._recipe_button.clicked.connect(self._on_recipe_clicked)
        self._recipe_button.setVisible(self._save_only)
        layout.addWidget(self._recipe_button)

        self._save_button = QPushButton(
            "Save Artifact" if self._save_only else "Save",
            row,
        )
        self._save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_button)

        return row

    def _build_saved_instances_group(self) -> QGroupBox:
        group = QGroupBox("Saved Instances", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(8)

        self._saved_hint_label = QLabel("", group)
        self._saved_hint_label.setWordWrap(True)
        layout.addWidget(self._saved_hint_label)

        self._saved_list = QListWidget(group)
        self._saved_list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self._saved_list, 1)

        return group

    # ------------------------------------------------------------------
    # Population / state
    # ------------------------------------------------------------------

    def _populate_tool_type_combo(self) -> None:
        self._tool_type_combo.blockSignals(True)
        self._tool_type_combo.clear()
        for value, label in self.TOOL_TYPE_ITEMS:
            self._tool_type_combo.addItem(label, value)
        self._tool_type_combo.blockSignals(False)

        self._tool_combo.clear()
        self._tool_combo.addItem("Select tool", "")

    def _populate_tool_combo(self, tool_type: str) -> None:
        self._tool_combo.blockSignals(True)
        self._tool_combo.clear()
        self._tool_combo.addItem("Select tool", "")

        if tool_type == "indicator":
            specs = get_indicator_specs()
        elif tool_type == "oscillator":
            specs = get_oscillator_specs()
        elif tool_type == "construct":
            specs = get_construct_specs()
        else:
            specs = {}

        for key, spec in sorted(specs.items(), key=lambda item: item[1].title.lower()):
            self._tool_combo.addItem(spec.title, key)

        self._tool_combo.blockSignals(False)

    def _get_selected_tool_type(self) -> str:
        return str(self._tool_type_combo.currentData() or "")

    def _get_selected_tool_key(self) -> str:
        return str(self._tool_combo.currentData() or "")

    def _lookup_current_spec(self) -> Optional[ToolSpec]:
        tool_type = self._get_selected_tool_type()
        tool_key = self._get_selected_tool_key()

        if not tool_type or not tool_key:
            return None

        if tool_type == "indicator":
            return get_indicator_specs().get(tool_key)
        if tool_type == "oscillator":
            return get_oscillator_specs().get(tool_key)
        if tool_type == "construct":
            return get_construct_specs().get(tool_key)
        return None

    def _clear_form(self) -> None:
        self._param_editors.clear()
        self._source_family_editors.clear()
        self._source_value_editors.clear()

        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)

    def _set_form_placeholder(self, text: str) -> None:
        self._clear_form()
        self._inputs_summary_label.setText("")
        self._behavior_summary_label.setText("")
        self._output_preview_label.setText("")
        self._instance_key_preview_label.setText("")
        placeholder = QLabel(text, self._form_host)
        placeholder.setWordWrap(True)
        self._form_layout.addRow(placeholder)

    def _make_param_editor(self, param, default_value: Any) -> QWidget:
        dtype = str(param.dtype)

        if dtype == "bool":
            editor = QCheckBox(self._form_host)
            editor.setChecked(bool(default_value))
            return editor

        if param.choices:
            editor = QComboBox(self._form_host)
            selected_index = 0
            for idx, choice in enumerate(param.choices):
                editor.addItem(str(choice), choice)
                if choice == default_value:
                    selected_index = idx
            editor.setCurrentIndex(selected_index)
            return editor

        editor = QLineEdit(self._form_host)
        if default_value is not None:
            editor.setText(str(default_value))

        if dtype == "int":
            validator = QIntValidator(editor)
            if param.minimum is not None:
                validator.setBottom(int(param.minimum))
            if param.maximum is not None:
                validator.setTop(int(param.maximum))
            editor.setValidator(validator)

        elif dtype == "float":
            validator = QDoubleValidator(editor)
            validator.setNotation(QDoubleValidator.StandardNotation)
            if param.minimum is not None:
                validator.setBottom(float(param.minimum))
            if param.maximum is not None:
                validator.setTop(float(param.maximum))
            editor.setValidator(validator)

        return editor

    def _connect_param_editor_preview(self, editor: QWidget) -> None:
        if isinstance(editor, QCheckBox):
            editor.stateChanged.connect(lambda _=None: self._refresh_live_preview())
        elif isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(lambda _=None: self._refresh_live_preview())
        elif isinstance(editor, QLineEdit):
            editor.textChanged.connect(lambda _=None: self._refresh_live_preview())

    def _is_utc_spec(self, spec: ToolSpec) -> bool:
        return str(spec.kind).strip().lower() == "indicator" and str(spec.key).strip().lower() == "universal_trend_classifier"

    def _make_utc_fractal_combo(self, default_value: Any) -> QComboBox:
        editor = QComboBox(self._form_host)
        default_text = str(default_value if default_value is not None else "").strip()
        selected_index = 0
        for idx, value in enumerate(self.UTC_FRACTAL_CHOICES):
            editor.addItem(str(value), value)
            if str(value) == default_text:
                selected_index = idx
        editor.setCurrentIndex(selected_index)
        return editor

    def _make_utc_break_mode_combo(self, default_value: Any) -> QComboBox:
        editor = QComboBox(self._form_host)
        default_text = str(default_value or "close").strip().lower()
        selected_index = 0
        for idx, (label, value) in enumerate(self.UTC_BREAK_MODE_CHOICES):
            editor.addItem(label, value)
            if value == default_text:
                selected_index = idx
        editor.setCurrentIndex(selected_index)
        return editor

    def _fractal_window_from_column_name(self, value: Any) -> Optional[int]:
        text = str(value or "").strip().lower()
        for prefix in ("peak_fractal_", "trough_fractal_"):
            if text.startswith(prefix):
                suffix = text[len(prefix):]
                if suffix.isdigit():
                    window = int(suffix)
                    if window in self.UTC_FRACTAL_CHOICES:
                        return window
        return None

    def _add_utc_param_rows(self, spec: ToolSpec, visible_params: List[Any], defaults: Dict[str, Any]) -> None:
        rendered: set[str] = set()

        def add_editor(name: str, label: str, editor: QWidget) -> None:
            self._connect_param_editor_preview(editor)
            self._param_editors[name] = editor
            self._form_layout.addRow(label, editor)
            rendered.add(name)

        def add_trend_editor(default_value: Any) -> None:
            if "trend_fractal_window" in rendered or "fractal_window" in rendered:
                return
            editor = self._make_utc_fractal_combo(default_value)
            self._connect_param_editor_preview(editor)
            self._param_editors["fractal_window"] = editor
            self._param_editors["trend_fractal_window"] = editor
            self._form_layout.addRow("Up/Down Trend Fractal", editor)
            rendered.update({"fractal_window", "trend_fractal_window"})

        def add_range_editor(default_value: Any) -> None:
            if "range_fractal_window" in rendered:
                return
            add_editor("range_fractal_window", "Range Trend Fractal", self._make_utc_fractal_combo(default_value))

        def add_break_mode_editor(default_value: Any) -> None:
            if "hr_break_mode" in rendered:
                return
            add_editor("hr_break_mode", "Range Break Mode", self._make_utc_break_mode_combo(default_value))

        for param in visible_params:
            name = str(param.name)
            if name in {
                "peak_column",
                "trough_column",
                "trend_peak_column",
                "trend_trough_column",
                "range_peak_column",
                "range_trough_column",
            }:
                continue

            default_value = defaults.get(name, param.default)
            if name in {"fractal_window", "trend_fractal_window"}:
                add_trend_editor(defaults.get("trend_fractal_window", defaults.get("fractal_window", default_value)))
                continue
            if name == "range_fractal_window":
                add_range_editor(defaults.get("range_fractal_window", default_value if default_value is not None else 3))
                continue
            if name == "hr_break_mode":
                add_break_mode_editor(default_value)
                continue

            editor = self._make_param_editor(param, default_value)
            tooltip_parts = []
            if param.description:
                tooltip_parts.append(param.description)
            if param.minimum is not None or param.maximum is not None:
                tooltip_parts.append(
                    f"Range: {param.minimum if param.minimum is not None else '-inf'} "
                    f"to {param.maximum if param.maximum is not None else '+inf'}"
                )
            if tooltip_parts:
                editor.setToolTip("\n".join(tooltip_parts))
            add_editor(name, param.label or name, editor)

        add_trend_editor(defaults.get("trend_fractal_window", defaults.get("fractal_window", 5)))
        add_range_editor(defaults.get("range_fractal_window", 3))
        add_break_mode_editor(defaults.get("hr_break_mode", "close"))

    def _construct_form_variant(self, spec: ToolSpec) -> str:
        if spec.kind != "construct":
            return ""
        return str(spec.form_variant or "").strip().lower()

    def _structured_binding_param_names(self, spec: ToolSpec) -> set[str]:
        """
        Return the parameter names that are owned by structured construct input widgets
        rather than by generic parameter editors.

        This keeps runtime/source truth centralized:
        if a construct uses structured source roles, those roles must be gathered
        from dedicated source selectors and must not remain exposed as free-form text
        inputs in the generic parameter area.
        """
        variant = self._construct_form_variant(spec)

        if variant == "construct_unary_source":
            return {"source"}

        if variant == "construct_fs":
            # Keep backward-tolerant suppression of left/right if they still exist
            # in any transitional spec path, but do not expose them as canonical UI.
            return {"fast", "slow", "left", "right"}

        if variant == "construct_fms":
            return {"fast", "mid", "slow"}

        if variant == "construct_multi_source":
            return {"source_columns"}

        return set()

    def _add_param_rows(
        self,
        spec: ToolSpec,
        *,
        skip_param_names: Optional[set[str]] = None,
    ) -> None:
        """
        Add generic parameter editors for a spec, excluding any parameter names that
        are already owned by dedicated structured-input widgets.

        This preserves the spec-driven form model while preventing duplicate or stale
        UI controls for construct source roles.
        """
        defaults = build_default_params(spec)
        skip = set(skip_param_names or set())

        visible_params = [param for param in spec.params if param.name not in skip]

        if self._is_utc_spec(spec):
            self._add_utc_param_rows(spec, visible_params, defaults)
            return

        if not visible_params:
            label = QLabel("This tool currently has no additional configurable parameters.", self._form_host)
            label.setWordWrap(True)
            self._form_layout.addRow(label)
            return

        for param in visible_params:
            default_value = defaults.get(param.name, param.default)
            editor = self._make_param_editor(param, default_value)

            tooltip_parts = []
            if param.description:
                tooltip_parts.append(param.description)
            if param.minimum is not None or param.maximum is not None:
                tooltip_parts.append(
                    f"Range: {param.minimum if param.minimum is not None else '-inf'} "
                    f"to {param.maximum if param.maximum is not None else '+inf'}"
                )
            if tooltip_parts:
                editor.setToolTip("\n".join(tooltip_parts))

            self._connect_param_editor_preview(editor)

            self._param_editors[param.name] = editor
            self._form_layout.addRow(param.label or param.name, editor)

    def _add_source_selector_row(self, *, role_name: str, role_label: str) -> None:
        """
        Add a structured source selector consisting of:
        - source family
        - source series within that family

        This is the canonical UI path for construct source roles.
        """
        source_family_combo = QComboBox(self._form_host)

        allowed_families: Optional[set[str]] = None
        spec = self._current_spec
        if spec is not None and spec.kind == "construct":
            construct_io = getattr(spec, "construct_io", None)
            if construct_io is not None:
                allowed_families = {
                    str(family).strip().lower()
                    for family in getattr(construct_io, "allowed_source_families", ())
                    if str(family).strip()
                }

        for family_key, family_label in self.UNARY_SOURCE_FAMILY_ITEMS:
            normalized_family = "ohlc" if family_key == "default" else str(family_key).strip().lower()
            if allowed_families is not None and normalized_family not in allowed_families:
                continue
            source_family_combo.addItem(family_label, family_key)

        source_value_combo = QComboBox(self._form_host)

        self._source_family_editors[role_name] = source_family_combo
        self._source_value_editors[role_name] = source_value_combo

        source_family_combo.currentIndexChanged.connect(
            lambda _=None, current_role=role_name: self._on_source_family_changed(current_role)
        )
        source_value_combo.currentIndexChanged.connect(lambda _=None: self._refresh_live_preview())

        self._form_layout.addRow(f"{role_label} Family", source_family_combo)
        self._form_layout.addRow(role_label, source_value_combo)

        initial_family_kind = str(source_family_combo.currentData() or "default")
        self._populate_source_value_combo(role_name, initial_family_kind)

    def _infer_multi_source_role_names(self, spec: ToolSpec) -> list[str]:
        """
        Infer how many structured source selectors should be shown for a
        construct_multi_source form.

        The current UI remains intentionally conservative:
        - it derives the count from the default/source_columns payload shape
        - if nothing explicit is declared, it shows one canonical source selector

        This keeps the UI aligned with current runtime/spec truth without introducing
        unrelated dynamic-form machinery.
        """
        defaults = build_default_params(spec)
        raw_value = defaults.get("source_columns", [])

        parts: list[str] = []

        if isinstance(raw_value, str):
            parts = [p.strip() for p in raw_value.split(",") if p.strip()]
        else:
            try:
                parts = [str(v).strip() for v in raw_value if str(v).strip()]
            except Exception:
                if raw_value:
                    parts = [str(raw_value).strip()]

        count = max(1, len(parts))
        return [f"source_columns_{idx + 1}" for idx in range(count)]

    def _build_construct_unary_source_form(self, spec: ToolSpec) -> None:
        self._inputs_summary_label.setText(
            "Unary construct source selector. Choose a source family, then choose a series."
        )
        self._add_source_selector_row(role_name="source", role_label="Source")
        self._add_param_rows(spec, skip_param_names=self._structured_binding_param_names(spec))
        self._refresh_live_preview()

    def _build_construct_fs_form(self, spec: ToolSpec) -> None:
        self._inputs_summary_label.setText(
            "Fast/slow construct selector. Choose canonical fast and slow source series."
        )
        self._add_source_selector_row(role_name="fast", role_label="Fast")
        self._add_source_selector_row(role_name="slow", role_label="Slow")
        self._add_param_rows(spec, skip_param_names=self._structured_binding_param_names(spec))
        self._refresh_live_preview()

    def _build_construct_fms_form(self, spec: ToolSpec) -> None:
        self._inputs_summary_label.setText(
            "Fast/mid/slow construct selector. Choose canonical fast, mid, and slow source series."
        )
        self._add_source_selector_row(role_name="fast", role_label="Fast")
        self._add_source_selector_row(role_name="mid", role_label="Mid")
        self._add_source_selector_row(role_name="slow", role_label="Slow")
        self._add_param_rows(spec, skip_param_names=self._structured_binding_param_names(spec))
        self._refresh_live_preview()

    def _build_construct_multi_source_form(self, spec: ToolSpec) -> None:
        self._inputs_summary_label.setText(
            "Multi-source construct selector. Choose the canonical ordered source series."
        )

        for idx, role_name in enumerate(self._infer_multi_source_role_names(spec), start=1):
            self._add_source_selector_row(role_name=role_name, role_label=f"Source {idx}")

        self._add_param_rows(spec, skip_param_names=self._structured_binding_param_names(spec))
        self._refresh_live_preview()

    def _set_structured_source_value(self, role_name: str, source_value: str) -> bool:
        normalized = str(source_value).strip()
        if not normalized:
            return False

        family_combo = self._source_family_editors.get(role_name)
        value_combo = self._source_value_editors.get(role_name)
        if family_combo is None or value_combo is None:
            return False

        for idx in range(family_combo.count()):
            family_combo.setCurrentIndex(idx)
            family_kind = str(family_combo.currentData() or "")
            self._populate_source_value_combo(role_name, family_kind)

            for source_idx in range(value_combo.count()):
                current_data = value_combo.itemData(source_idx)
                if isinstance(current_data, dict) and str(current_data.get("series_key", "")).strip() == normalized:
                    value_combo.setCurrentIndex(source_idx)
                    return True

        return False

    def _require_selected_source_meta(self, *, role_name: str, role_label: str) -> Dict[str, Any]:
        combo = self._source_value_editors.get(role_name)
        if combo is None:
            raise ValueError(f"{role_label} source widget is not available.")

        source_meta = combo.currentData()
        if not isinstance(source_meta, dict):
            raise ValueError(f"Please select a valid {role_label.lower()} source.")

        source_key = str(source_meta.get("series_key", "")).strip()
        if not source_key:
            raise ValueError(f"Please select a valid {role_label.lower()} source.")

        return dict(source_meta)


    def _normalized_construct_source_family(self, source_meta: Dict[str, Any]) -> str:
        """
        Normalize UI source-family values into the construct-IO vocabulary.

        UI uses:
        - default
        - indicator
        - oscillator
        - construct

        Construct I/O metadata uses:
        - ohlc
        - indicator
        - oscillator
        - construct
        """
        family = str(source_meta.get("family", "")).strip().lower()
        if family == "default":
            return "ohlc"
        return family

    def _validate_construct_input_compatibility(
        self,
        *,
        spec: ToolSpec,
        binding_meta: Dict[str, Any],
    ) -> None:
        """
        Validate structured construct inputs against construct I/O metadata and
        the current chart-facing construct rules.

        This check is intentionally applied only at payload-build time so the
        existing form-building flow stays unchanged while invalid source mixes are
        prevented before apply/save.
        """
        if spec.kind != "construct":
            return

        construct_io = getattr(spec, "construct_io", None)
        if construct_io is None:
            return

        selected_sources: list[Dict[str, Any]] = []

        for value in binding_meta.values():
            if isinstance(value, dict):
                selected_sources.append(value)
            elif isinstance(value, list):
                selected_sources.extend(item for item in value if isinstance(item, dict))

        if not selected_sources:
            return

        normalized_families = {
            self._normalized_construct_source_family(source_meta)
            for source_meta in selected_sources
        }

        allowed_families = {
            str(family).strip().lower()
            for family in getattr(construct_io, "allowed_source_families", ())
            if str(family).strip()
        }
        if allowed_families:
            invalid_families = sorted(normalized_families - allowed_families)
            if invalid_families:
                raise ValueError(
                    f"{spec.title} does not accept source families: {', '.join(invalid_families)}."
                )

        source_compatibility = str(
            getattr(construct_io, "source_compatibility", "mixed_numeric") or "mixed_numeric"
        ).strip().lower()

        if source_compatibility == "same_family" and len(normalized_families) > 1:
            raise ValueError(f"{spec.title} requires all inputs to belong to the same source family.")

        if source_compatibility == "same_oscillator_type":
            non_oscillator_families = sorted(family for family in normalized_families if family != "oscillator")
            if non_oscillator_families:
                raise ValueError(f"{spec.title} requires oscillator inputs only.")

            oscillator_tool_keys = {
                str(source_meta.get("tool_key", "")).strip().lower()
                for source_meta in selected_sources
                if self._normalized_construct_source_family(source_meta) == "oscillator"
            }
            oscillator_tool_keys.discard("")
            if len(oscillator_tool_keys) > 1:
                raise ValueError(f"{spec.title} requires all oscillator inputs to be of the same type.")

        # Current chart-facing delta policy:
        # - indicator vs indicator is allowed
        # - OHLC vs indicator is allowed
        # - oscillator vs oscillator is allowed
        # - oscillator vs OHLC / indicator is not allowed
        if spec.key == "delta" and "oscillator" in normalized_families and len(normalized_families) > 1:
            raise ValueError(
                "Delta does not support mixing oscillator inputs with OHLC or indicator inputs."
            )

        # Current chart-facing trap-area policy:
        # - indicator / OHLC mixes are allowed
        # - oscillator inputs must not be mixed with non-oscillator inputs
        # - multi-oscillator trap-area inputs must be of the same oscillator type
        if spec.key == "trap_area":
            if "oscillator" in normalized_families and len(normalized_families) > 1:
                raise ValueError(
                    "Trap Area does not support mixing oscillator inputs with OHLC or indicator inputs."
                )

            oscillator_tool_keys = {
                str(source_meta.get("tool_key", "")).strip().lower()
                for source_meta in selected_sources
                if self._normalized_construct_source_family(source_meta) == "oscillator"
            }
            oscillator_tool_keys.discard("")
            if len(oscillator_tool_keys) > 1:
                raise ValueError("Trap Area requires all oscillator inputs to be of the same type.")

    def _current_params_for_preview(self) -> Dict[str, Any]:
        """
        Best-effort preview parameter collection.

        Unlike final payload building, preview collection should not raise on
        partially configured construct bindings. It should surface as much
        canonical identity as is currently knowable from the form state.
        """
        if self._current_spec is None:
            return {}

        params = self._collect_param_values()
        variant = self._construct_form_variant(self._current_spec)

        if variant == "construct_unary_source":
            combo = self._source_value_editors.get("source")
            data = combo.currentData() if combo is not None else None
            if isinstance(data, dict):
                params["source"] = str(data.get("series_key", "")).strip()

        elif variant == "construct_fs":
            for role_name in ("fast", "slow"):
                combo = self._source_value_editors.get(role_name)
                data = combo.currentData() if combo is not None else None
                if isinstance(data, dict):
                    params[role_name] = str(data.get("series_key", "")).strip()

        elif variant == "construct_fms":
            for role_name in ("fast", "mid", "slow"):
                combo = self._source_value_editors.get(role_name)
                data = combo.currentData() if combo is not None else None
                if isinstance(data, dict):
                    params[role_name] = str(data.get("series_key", "")).strip()

        elif variant == "construct_multi_source":
            values: list[str] = []
            for role_name in self._infer_multi_source_role_names(self._current_spec):
                combo = self._source_value_editors.get(role_name)
                data = combo.currentData() if combo is not None else None
                if isinstance(data, dict):
                    value = str(data.get("series_key", "")).strip()
                    if value:
                        values.append(value)
            if values:
                params["source_columns"] = values

        return params

    def _build_behavior_summary_text(self, spec: ToolSpec, params: Dict[str, Any]) -> str:
        behavior = spec.behavior
        if behavior is None:
            return ""

        try:
            signals = format_output_signals(spec, params)
        except Exception:
            signals = tuple()

        renderable_count = sum(1 for sig in signals if sig.renderable)
        usable_count = sum(1 for sig in signals if sig.analysis_usable)

        parts = [
            f"Mode: {behavior.output_mode}",
            f"Structure: {spec.output.structure}",
            f"Renderable: {'yes' if behavior.chart_renderable else 'no'}",
        ]

        if signals:
            parts.append(f"Signals: {len(signals)}")
            parts.append(f"Renderable signals: {renderable_count}")
            parts.append(f"Analysis-usable signals: {usable_count}")

        return " | ".join(parts)

    def _build_output_preview_text(self, spec: ToolSpec, params: Dict[str, Any]) -> str:
        try:
            names = format_output_names(spec, params)
            signals = format_output_signals(spec, params)
        except Exception as e:
            return f"Expected outputs: unavailable ({e!r})"

        if not names:
            if spec.output.accepts_empty_render_output:
                return "Expected outputs: non-visual / analysis-only"
            return "Expected outputs: none"

        signal_map = {sig.name: sig for sig in signals}
        renderable_count = sum(1 for sig in signals if sig.renderable)
        usable_count = sum(1 for sig in signals if sig.analysis_usable)

        preview_limit = 4
        lines = [
            (
                "Expected outputs: "
                f"{len(names)} total | {renderable_count} rendered | {usable_count} usable"
            )
        ]

        preview_names = list(names[:preview_limit])
        for name in preview_names:
            sig = signal_map.get(name)
            if sig is None:
                lines.append(f"  - {name}")
                continue

            qualifiers: list[str] = []
            qualifiers.append("rendered" if sig.renderable else "non-rendered")
            qualifiers.append("usable" if sig.analysis_usable else "non-usable")
            qualifiers.append(sig.signal_type)
            lines.append(f"  - {name} [{', '.join(qualifiers)}]")

        remaining = max(0, len(names) - len(preview_names))
        if remaining > 0:
            lines.append(f"  - ... {remaining} more output(s)")

        return "\n".join(lines)

    def _build_instance_key_preview_text(self, spec: ToolSpec, params: Dict[str, Any]) -> str:
        if spec.kind != "construct":
            return ""

        try:
            binding_slug = build_binding_slug_from_params(
                construct_key=spec.key,
                params=params,
            )
            instance_key = build_construct_instance_key_from_params(
                construct_key=spec.key,
                params=params,
                exclude_param_keys={"source", "source_column", "source_columns", "left", "right", "fast", "mid", "slow"},
            )
        except Exception as e:
            return f"Instance identity: unavailable ({e!r})"

        return (
            f"Canonical binding: {binding_slug}\n"
            f"Instance key: {instance_key}"
        )

    def _refresh_live_preview(self) -> None:
        spec = self._current_spec
        if spec is None:
            self._behavior_summary_label.setText("")
            self._output_preview_label.setText("")
            self._instance_key_preview_label.setText("")
            return

        params = self._current_params_for_preview()
        self._behavior_summary_label.setText(
            self._build_behavior_summary_text(spec, params)
        )
        self._output_preview_label.setText(
            self._build_output_preview_text(spec, params)
        )
        self._instance_key_preview_label.setText(
            self._build_instance_key_preview_text(spec, params)
        )

    def _build_form_for_spec(self, spec: ToolSpec) -> None:
        self._clear_form()

        if spec.kind == "construct":
            variant = self._construct_form_variant(spec)

            if variant == "construct_unary_source":
                self._build_construct_unary_source_form(spec)
                return

            if variant == "construct_fs":
                self._build_construct_fs_form(spec)
                return

            if variant == "construct_fms":
                self._build_construct_fms_form(spec)
                return

            if variant == "construct_multi_source":
                self._build_construct_multi_source_form(spec)
                return

        if spec.data_inputs:
            inputs_text = ", ".join(inp.label or inp.name for inp in spec.data_inputs)
            self._inputs_summary_label.setText(f"Required market inputs: {inputs_text}")
        else:
            self._inputs_summary_label.setText("Required market inputs: none")

        self._add_param_rows(spec)
        self._refresh_live_preview()

    def _list_temporary_source_options(self, family_kind: str) -> list[dict[str, Any]]:
        provider = self._source_options_provider
        if provider is None:
            return []

        try:
            raw_options = provider(str(family_kind).strip().lower())
        except Exception:
            return []

        options: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        for entry in raw_options or []:
            if not isinstance(entry, dict):
                continue

            projection_key = str(entry.get("projection_key", "")).strip()
            series_key = str(entry.get("series_key", "")).strip()
            display_name = str(entry.get("display_name", "")).strip()
            if not projection_key or not series_key or not display_name:
                continue

            dedupe_key = (projection_key, str(entry.get("tool_key", "")).strip(), series_key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            normalized = dict(entry)
            normalized.setdefault("family", family_kind)
            normalized.setdefault("instance_key", projection_key)
            normalized.setdefault("artifact_path", "")
            normalized.setdefault("column_name", series_key)
            normalized.setdefault("source_kind", "temporary")
            options.append(normalized)

        options.sort(key=lambda item: item["display_name"].lower())
        return options

    def _list_saved_source_options(self, family_kind: str) -> list[dict[str, Any]]:
        market = canonicalize(
            self._exchange,
            self._market_type,
            self._symbol,
            self._timeframe,
        )
        store = DerivedCsvStore(historical_root=self._historical_root)

        if family_kind == "indicator":
            spec_map = get_indicator_specs()
            storage_kind = "indicators"
        elif family_kind == "oscillator":
            spec_map = get_oscillator_specs()
            storage_kind = "oscillators"
        elif family_kind == "construct":
            spec_map = get_construct_specs()
            storage_kind = "constructs"
        else:
            return []

        options: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        for tool_key, spec in sorted(spec_map.items(), key=lambda item: item[1].title.lower()):
            try:
                refs = store.list_instances(
                    market=market,
                    kind=storage_kind,
                    tool_key=tool_key,
                )
            except Exception:
                continue

            for ref in refs:
                for column_name in self._read_selectable_columns_from_artifact(Path(ref.path)):
                    dedupe_key = (str(ref.path), tool_key, column_name)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    display_name = f"Saved · {ref.instance_key}  ->  {column_name}"
                    options.append(
                        {
                            "family": family_kind,
                            "series_key": column_name,
                            "display_name": display_name,
                            "instance_key": ref.instance_key,
                            "artifact_path": str(ref.path),
                            "tool_key": tool_key,
                            "tool_title": spec.title,
                            "column_name": column_name,
                            "source_kind": "saved",
                        }
                    )

        options.sort(key=lambda item: item["display_name"].lower())
        return options

    def _list_available_source_options(self, family_kind: str) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        for entry in self._list_temporary_source_options(family_kind):
            dedupe_key = (
                str(entry.get("source_kind", "temporary")).strip(),
                str(entry.get("projection_key", "")).strip(),
                str(entry.get("series_key", "")).strip(),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            options.append(entry)

        for entry in self._list_saved_source_options(family_kind):
            dedupe_key = (
                str(entry.get("source_kind", "saved")).strip(),
                str(entry.get("artifact_path", "")).strip(),
                str(entry.get("series_key", "")).strip(),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            options.append(entry)

        options.sort(key=lambda item: item["display_name"].lower())
        return options

    def _read_selectable_columns_from_artifact(self, path: Path) -> list[str]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                header = handle.readline().strip()
        except Exception:
            return []

        if not header:
            return []

        columns = [col.strip() for col in header.split(",") if col.strip()]
        selectable = [
            col
            for col in columns
            if col not in self.NON_SELECTABLE_ARTIFACT_COLUMNS
        ]
        return selectable

    def _populate_source_value_combo(self, role_name: str, family_kind: str) -> None:
        combo = self._source_value_editors.get(role_name)
        if combo is None:
            return

        combo.blockSignals(True)
        combo.clear()

        if family_kind == "default":
            for display_name, series_key in self.DEFAULT_UNARY_SOURCE_OPTIONS:
                combo.addItem(
                    display_name,
                    {
                        "family": "default",
                        "series_key": series_key,
                        "display_name": display_name,
                        "instance_key": "",
                        "artifact_path": "",
                        "tool_key": "",
                        "tool_title": "",
                        "column_name": series_key,
                        "source_kind": "default",
                    },
                )
        else:
            options = self._list_available_source_options(family_kind)
            if not options:
                combo.addItem(
                    f"No {family_kind} sources found",
                    None,
                )
            else:
                for option in options:
                    combo.addItem(option["display_name"], option)

        combo.blockSignals(False)

    def _on_source_family_changed(self, role_name: str) -> None:
        family_combo = self._source_family_editors.get(role_name)
        if family_combo is None:
            return

        family_kind = str(family_combo.currentData() or "default")
        self._populate_source_value_combo(role_name, family_kind)

        spec = self._current_spec
        if spec is not None and spec.kind == "construct":
            construct_io = getattr(spec, "construct_io", None)
            compatibility = (
                str(getattr(construct_io, "source_compatibility", "mixed_numeric") or "mixed_numeric")
                .strip()
                .lower()
                if construct_io is not None
                else "mixed_numeric"
            )
            if compatibility == "same_family":
                for other_role_name, other_family_combo in self._source_family_editors.items():
                    if other_role_name == role_name:
                        continue
                    if str(other_family_combo.currentData() or "") == family_kind:
                        self._populate_source_value_combo(other_role_name, family_kind)
                        continue
                    for idx in range(other_family_combo.count()):
                        if str(other_family_combo.itemData(idx) or "") == family_kind:
                            other_family_combo.blockSignals(True)
                            other_family_combo.setCurrentIndex(idx)
                            other_family_combo.blockSignals(False)
                            self._populate_source_value_combo(other_role_name, family_kind)
                            break

        self._refresh_live_preview()

    def _set_unary_source_value(self, role_name: str, source_value: str) -> bool:
        normalized = str(source_value).strip()
        if not normalized:
            return False

        family_combo = self._source_family_editors.get(role_name)
        value_combo = self._source_value_editors.get(role_name)
        if family_combo is None or value_combo is None:
            return False

        for idx in range(family_combo.count()):
            family_combo.setCurrentIndex(idx)
            family_kind = str(family_combo.currentData() or "")
            self._populate_source_value_combo(role_name, family_kind)

            for source_idx in range(value_combo.count()):
                current_data = value_combo.itemData(source_idx)
                if isinstance(current_data, dict) and str(current_data.get("series_key", "")).strip() == normalized:
                    value_combo.setCurrentIndex(source_idx)
                    return True

        return False

    def _populate_saved_instances(self, spec: Optional[ToolSpec]) -> None:
        self._saved_list.clear()
        self._saved_refs = []

        if spec is None:
            self._saved_hint_label.setText(
                "Saved tools of the selected family will appear here."
            )
            return

        try:
            if spec.kind == "indicator":
                kind = "indicators"
            elif spec.kind == "oscillator":
                kind = "oscillators"
            elif spec.kind == "construct":
                kind = "constructs"
            else:
                self._saved_hint_label.setText(
                    f"Saved instances for: {spec.title}\n"
                    f"Unsupported tool kind: {spec.kind}"
                )
                return

            market = canonicalize(
                self._exchange,
                self._market_type,
                self._symbol,
                self._timeframe,
            )
            store = DerivedCsvStore(historical_root=self._historical_root)
            refs = store.list_instances(
                market=market,
                kind=kind,
                tool_key=spec.key,
            )
            self._saved_refs = refs

            if not refs:
                self._saved_hint_label.setText(
                    f"Saved instances for: {spec.title}\n"
                    "No saved instances found for this dataset."
                )
                return

            self._saved_hint_label.setText(
                f"Saved instances for: {spec.title}\n"
                f"Found {len(refs)} saved instance(s) for this dataset."
            )

            for ref in refs:
                item = QListWidgetItem(ref.instance_key, self._saved_list)
                item.setToolTip(str(ref.path))

        except Exception as e:
            self._saved_hint_label.setText(
                f"Saved instances for: {spec.title}\n"
                f"Failed to list saved instances: {e!r}"
            )

    def _refresh_buttons(self) -> None:
        has_spec = self._current_spec is not None

        self._apply_button.setEnabled(has_spec and not self._save_only)
        self._recipe_button.setEnabled(has_spec and self._save_only)
        self._save_button.setEnabled(has_spec)

        if not has_spec:
            self._status_label.setText("No tool selected.")
        elif self._save_only:
            self._status_label.setText(
                f"Ready to save recipe or artifact: {self._current_spec.title}"
            )
        else:
            self._status_label.setText(
                f"Ready to apply or save: {self._current_spec.title}"
            )

    def _set_combo_value(self, combo: QComboBox, value: Any) -> bool:
        target = str(value).strip().lower()
        if not target:
            return False

        for idx in range(combo.count()):
            current = str(combo.itemData(idx) or "").strip().lower()
            if current == target:
                combo.setCurrentIndex(idx)
                return True

        return False

    def _apply_param_values_to_form(self, params: Dict[str, Any]) -> None:
        if self._current_spec is None:
            return

        if self._is_utc_spec(self._current_spec):
            params = dict(params)
            if "trend_fractal_window" in params and "fractal_window" not in params:
                params["fractal_window"] = params.get("trend_fractal_window")
            if "range_fractal_window" not in params:
                range_from_peak = self._fractal_window_from_column_name(params.get("range_peak_column"))
                range_from_trough = self._fractal_window_from_column_name(params.get("range_trough_column"))
                legacy_peak = self._fractal_window_from_column_name(params.get("peak_column"))
                legacy_trough = self._fractal_window_from_column_name(params.get("trough_column"))
                inferred = range_from_peak or range_from_trough or legacy_peak or legacy_trough
                if inferred is not None:
                    params["range_fractal_window"] = inferred

        variant = self._construct_form_variant(self._current_spec)

        if variant == "construct_unary_source":
            source_value = params.get("source")
            if source_value is not None:
                self._set_structured_source_value("source", str(source_value))

        elif variant == "construct_fs":
            fast_value = params.get("fast", params.get("left"))
            slow_value = params.get("slow", params.get("right"))

            if fast_value is not None:
                self._set_structured_source_value("fast", str(fast_value))
            if slow_value is not None:
                self._set_structured_source_value("slow", str(slow_value))

        elif variant == "construct_fms":
            for role_name in ("fast", "mid", "slow"):
                value = params.get(role_name)
                if value is not None:
                    self._set_structured_source_value(role_name, str(value))

        elif variant == "construct_multi_source":
            raw_value = params.get("source_columns", [])
            if isinstance(raw_value, str):
                parts = [p.strip() for p in raw_value.split(",") if p.strip()]
            else:
                try:
                    parts = [str(v).strip() for v in raw_value if str(v).strip()]
                except Exception:
                    parts = [str(raw_value).strip()] if raw_value else []

            role_names = self._infer_multi_source_role_names(self._current_spec)
            for role_name, source_value in zip(role_names, parts, strict=False):
                self._set_structured_source_value(role_name, source_value)

        for param in self._current_spec.params:
            name = param.name
            if name not in params:
                continue

            editor = self._param_editors.get(name)
            if editor is None:
                continue

            value = params[name]

            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
                continue

            if isinstance(editor, QComboBox):
                matched = False
                for idx in range(editor.count()):
                    if editor.itemData(idx) == value:
                        editor.setCurrentIndex(idx)
                        matched = True
                        break
                if not matched:
                    for idx in range(editor.count()):
                        if str(editor.itemData(idx)) == str(value):
                            editor.setCurrentIndex(idx)
                            break
                continue

            if isinstance(editor, QLineEdit):
                editor.setText("" if value is None else str(value))
                continue

        if self._is_utc_spec(self._current_spec):
            for name in ("trend_fractal_window", "range_fractal_window", "hr_break_mode"):
                if name not in params:
                    continue
                editor = self._param_editors.get(name)
                if isinstance(editor, QComboBox):
                    self._set_combo_value(editor, params[name])

        self._refresh_live_preview()

    # ------------------------------------------------------------------
    # Data extraction / existence checks
    # ------------------------------------------------------------------

    def _collect_param_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}

        if self._current_spec is None:
            return values

        for param in self._current_spec.params:
            name = param.name
            editor = self._param_editors.get(name)

            if editor is None:
                values[name] = param.default
                continue

            if isinstance(editor, QCheckBox):
                values[name] = bool(editor.isChecked())
                continue

            if isinstance(editor, QComboBox):
                values[name] = editor.currentData()
                continue

            if isinstance(editor, QLineEdit):
                raw = editor.text().strip()

                if raw == "":
                    values[name] = param.default
                    continue

                if param.dtype == "int":
                    values[name] = int(raw)
                elif param.dtype == "float":
                    values[name] = float(raw)
                elif param.dtype == "bool":
                    values[name] = raw.lower() in {"1", "true", "yes", "on"}
                else:
                    values[name] = raw
                continue

            values[name] = param.default

        if self._current_spec is not None and self._is_utc_spec(self._current_spec):
            # UTC consumes Peaks & Troughs columns injected upstream. The UI
            # exposes fractal selections only; it no longer asks users for raw
            # peak/trough column names or lets peak and trough use mismatched
            # fractal windows.
            for raw_column_param in (
                "peak_column",
                "trough_column",
                "trend_peak_column",
                "trend_trough_column",
                "range_peak_column",
                "range_trough_column",
            ):
                values.pop(raw_column_param, None)

            trend_editor = self._param_editors.get("trend_fractal_window") or self._param_editors.get("fractal_window")
            if isinstance(trend_editor, QComboBox):
                trend_window = int(trend_editor.currentData())
                values["fractal_window"] = trend_window
                values["trend_fractal_window"] = trend_window

            range_editor = self._param_editors.get("range_fractal_window")
            if isinstance(range_editor, QComboBox):
                values["range_fractal_window"] = int(range_editor.currentData())

            break_mode_editor = self._param_editors.get("hr_break_mode")
            if isinstance(break_mode_editor, QComboBox):
                values["hr_break_mode"] = str(break_mode_editor.currentData() or "close")

        return values

    def _collect_input_bindings(self) -> tuple[Dict[str, Any], Dict[str, Any]]:
        bindings: Dict[str, Any] = {}
        binding_meta: Dict[str, Any] = {}

        if self._current_spec is None:
            return bindings, binding_meta

        variant = self._construct_form_variant(self._current_spec)
        if not variant:
            return bindings, binding_meta

        if variant == "construct_unary_source":
            source_meta = self._require_selected_source_meta(role_name="source", role_label="Source")
            bindings["source"] = str(source_meta["series_key"]).strip()
            binding_meta["source"] = source_meta
            self._validate_construct_input_compatibility(spec=self._current_spec, binding_meta=binding_meta)
            return bindings, binding_meta

        if variant == "construct_fs":
            for role_name, role_label in (("fast", "Fast"), ("slow", "Slow")):
                source_meta = self._require_selected_source_meta(role_name=role_name, role_label=role_label)
                bindings[role_name] = str(source_meta["series_key"]).strip()
                binding_meta[role_name] = source_meta
            self._validate_construct_input_compatibility(spec=self._current_spec, binding_meta=binding_meta)
            return bindings, binding_meta

        if variant == "construct_fms":
            for role_name, role_label in (("fast", "Fast"), ("mid", "Mid"), ("slow", "Slow")):
                source_meta = self._require_selected_source_meta(role_name=role_name, role_label=role_label)
                bindings[role_name] = str(source_meta["series_key"]).strip()
                binding_meta[role_name] = source_meta
            self._validate_construct_input_compatibility(spec=self._current_spec, binding_meta=binding_meta)
            return bindings, binding_meta

        if variant == "construct_multi_source":
            source_values: list[str] = []
            source_meta_list: list[Dict[str, Any]] = []

            for idx, role_name in enumerate(self._infer_multi_source_role_names(self._current_spec), start=1):
                source_meta = self._require_selected_source_meta(
                    role_name=role_name,
                    role_label=f"Source {idx}",
                )
                source_values.append(str(source_meta["series_key"]).strip())
                source_meta_list.append(source_meta)

            bindings["source_columns"] = source_values
            binding_meta["source_columns"] = source_meta_list
            self._validate_construct_input_compatibility(spec=self._current_spec, binding_meta=binding_meta)
            return bindings, binding_meta

        return bindings, binding_meta

    def _build_payload(self) -> Optional[Dict[str, Any]]:
        if self._current_spec is None:
            return None

        params = self._collect_param_values()
        input_bindings, input_binding_meta = self._collect_input_bindings()

        # Structured binding bridge:
        # runtime construct calculation still consumes source-role values through params.
        # The UI remains the canonical collector of those roles, then mirrors them into
        # params for the current compute layer contract.
        for key, value in input_bindings.items():
            params[key] = value

        return {
            "tool_type": self._current_spec.kind,
            "tool_key": self._current_spec.key,
            "tool_title": self._current_spec.title,
            "exchange": self._exchange,
            "market_type": self._market_type,
            "symbol": self._symbol,
            "timeframe": self._timeframe,
            "params": params,
            "input_bindings": input_bindings,
            "input_binding_meta": input_binding_meta,
            "required_inputs": [inp.name for inp in self._current_spec.data_inputs],
            "output_names": list(format_output_names(self._current_spec, params)),
            "output_signals": [
                {
                    "name": sig.name,
                    "signal_type": sig.signal_type,
                    "renderable": sig.renderable,
                    "analysis_usable": sig.analysis_usable,
                    "default_visible": sig.default_visible,
                    "label": sig.label,
                    "description": sig.description,
                }
                for sig in format_output_signals(self._current_spec, params)
            ],
        }

    def _build_instance_key(self, tool_key: str, params: Dict[str, Any]) -> str:
        """
        Must stay aligned with HistoricalChartController._build_instance_key().

        Canonical construct identity is now delegated to ft_naming.py so that
        UI preview, save checks, and persistence all consume the same naming-layer
        source of truth.
        """
        return build_construct_instance_key_from_params(
            construct_key=tool_key,
            params=params,
            exclude_param_keys={"source", "source_column", "source_columns", "left", "right", "fast", "mid", "slow"},
        )

    def _storage_kind_from_tool_type(self, tool_type: str) -> str:
        if tool_type == "indicator":
            return "indicators"
        if tool_type == "oscillator":
            return "oscillators"
        if tool_type == "construct":
            return "constructs"
        raise ValueError(f"Unsupported tool type: {tool_type}")

    def _save_target_exists(self, payload: Dict[str, Any]) -> bool:
        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        params = payload.get("params", {}) or {}

        if not tool_type or not tool_key:
            return False

        market = canonicalize(
            self._exchange,
            self._market_type,
            self._symbol,
            self._timeframe,
        )
        kind = self._storage_kind_from_tool_type(tool_type)
        instance_key = self._build_instance_key(tool_key, params)

        store = DerivedCsvStore(historical_root=self._historical_root)
        return store.exists(
            market=market,
            kind=kind,  # type: ignore[arg-type]
            tool_key=tool_key,
            instance_key=instance_key,
        )

    def _build_save_confirmation_text(self, payload: Dict[str, Any]) -> str:
        exchange_display = self._exchange[:1].upper() + self._exchange[1:] if self._exchange else self._exchange
        tool_type = str(payload.get("tool_type", "")).strip().capitalize()
        tool_title = str(payload.get("tool_title", "")).strip()
        params = payload.get("params", {}) or {}
        input_bindings = payload.get("input_bindings", {}) or {}

        lines = [
            f"Exchange: {exchange_display}",
            f"Market type: {self._market_type}",
            f"Asset: {self._symbol}",
            f"Timeframe: {self._timeframe}",
            f"Tool type: {tool_type}",
            f"Tool: {tool_title}",
            "",
            "Inputs:",
        ]

        if input_bindings:
            for key in sorted(input_bindings.keys()):
                lines.append(f"  - {key}: {input_bindings[key]}")
        else:
            lines.append("  - none")

        lines.extend(
            [
                "",
                "Parameters / metadata:",
            ]
        )

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

        if self._current_spec is not None:
            lines.extend(
                [
                    "",
                    "Behavior / output summary:",
                    f"  - {self._build_behavior_summary_text(self._current_spec, params)}",
                    "",
                ]
            )

            output_preview = self._build_output_preview_text(self._current_spec, params)
            for line in output_preview.splitlines():
                lines.append(line)

            instance_preview = self._build_instance_key_preview_text(self._current_spec, params)
            if instance_preview:
                lines.extend([""])
                for line in instance_preview.splitlines():
                    lines.append(line)

        return "\n".join(lines)

    def _confirm_save(self, payload: Dict[str, Any]) -> bool:
        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Financial Tool Save")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Review the financial tool before saving.")
        msg.setInformativeText(self._build_save_confirmation_text(payload))
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Save)
        return msg.exec() == int(QMessageBox.StandardButton.Save)

    def _confirm_overwrite(self, payload: Dict[str, Any]) -> bool:
        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_type_display = tool_type.capitalize() if tool_type else "Financial tool"

        msg = QMessageBox(self)
        msg.setWindowTitle("Financial Tool Already Exists")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f"This {tool_type} already exists for the selected dataset.")
        msg.setInformativeText(
            self._build_save_confirmation_text(payload)
            + "\n\nWould you like to proceed anyway?"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        save_button = msg.button(QMessageBox.StandardButton.Save)
        if save_button is not None:
            save_button.setText(f"Save {tool_type_display} Anyway")
        return msg.exec() == int(QMessageBox.StandardButton.Save)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tool_type_changed(self) -> None:
        tool_type = self._get_selected_tool_type()
        self._populate_tool_combo(tool_type)
        self._current_spec = None
        self._set_form_placeholder("Select a tool from the second dropdown.")
        self._populate_saved_instances(None)
        self._refresh_buttons()

    def _on_tool_changed(self) -> None:
        self._current_spec = self._lookup_current_spec()

        if self._current_spec is None:
            self._set_form_placeholder("Select a tool to configure.")
            self._populate_saved_instances(None)
            self._refresh_buttons()
            return

        self._build_form_for_spec(self._current_spec)
        self._populate_saved_instances(self._current_spec)
        self._refresh_buttons()

    def _on_apply_clicked(self) -> None:
        if self._save_only:
            return

        try:
            payload = self._build_payload()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Tool Configuration", str(e))
            return

        if payload is None:
            return

        self.apply_requested.emit(payload)

    def _on_recipe_clicked(self) -> None:
        if not self._save_only:
            return

        try:
            payload = self._build_payload()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Tool Configuration", str(e))
            return

        if payload is None:
            return

        self.recipe_requested.emit(payload)

    def _on_save_clicked(self) -> None:
        try:
            payload = self._build_payload()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Tool Configuration", str(e))
            return

        if payload is None:
            return

        try:
            exists = self._save_target_exists(payload)
        except Exception:
            exists = False

        if exists:
            if not self._confirm_overwrite(payload):
                return
        else:
            if not self._confirm_save(payload):
                return

        self.save_requested.emit(payload)

        # Save is currently handled synchronously through the panel/controller chain.
        # Refresh immediately so newly persisted instances appear in the list.
        self._populate_saved_instances(self._current_spec)