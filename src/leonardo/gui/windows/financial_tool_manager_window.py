from __future__ import annotations

from typing import Any, Dict, List, Optional

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
from leonardo.financial_tools.specs import (
    ToolSpec,
    build_default_params,
    get_construct_specs,
    get_indicator_specs,
    get_oscillator_specs,
)


class FinancialToolManagerWindow(QDialog):
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

    TOOL_TYPE_ITEMS = (
        ("", "Select tool type"),
        ("indicator", "Indicator"),
        ("oscillator", "Oscillator"),
        ("construct", "Construct"),
    )

    def __init__(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._exchange = str(exchange)
        self._market_type = str(market_type)
        self._symbol = str(symbol)
        self._timeframe = str(timeframe)

        self._current_spec: Optional[ToolSpec] = None
        self._param_editors: Dict[str, QWidget] = {}
        self._saved_refs: List[DerivedArtifactRef] = []

        self.setWindowTitle("Financial Tool Manager")
        self.setModal(False)
        self.resize(760, 520)

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

        title = QLabel("Historical Chart Context", box)
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
        layout.addWidget(self._apply_button)

        self._save_button = QPushButton("Save", row)
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

        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)

    def _set_form_placeholder(self, text: str) -> None:
        self._clear_form()
        self._inputs_summary_label.setText("")
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

    def _build_form_for_spec(self, spec: ToolSpec) -> None:
        self._clear_form()

        if spec.data_inputs:
            inputs_text = ", ".join(inp.label or inp.name for inp in spec.data_inputs)
            self._inputs_summary_label.setText(f"Required market inputs: {inputs_text}")
        else:
            self._inputs_summary_label.setText("Required market inputs: none")

        defaults = build_default_params(spec)

        if not spec.params:
            label = QLabel("This tool currently has no configurable parameters.", self._form_host)
            label.setWordWrap(True)
            self._form_layout.addRow(label)
            return

        for param in spec.params:
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

            self._param_editors[param.name] = editor
            self._form_layout.addRow(param.label or param.name, editor)

    def _populate_saved_instances(self, spec: Optional[ToolSpec]) -> None:
        self._saved_list.clear()
        self._saved_refs = []

        if spec is None:
            self._saved_hint_label.setText(
                "Saved tools of the selected family will appear here."
            )
            return

        if spec.kind == "construct":
            self._saved_hint_label.setText(
                f"Saved instances for: {spec.title}\n"
                "Construct persistence is not implemented yet."
            )
            QListWidgetItem("No saved constructs yet.", self._saved_list)
            return

        try:
            kind = "indicators" if spec.kind == "indicator" else "oscillators"
            market = canonicalize(
                self._exchange,
                self._market_type,
                self._symbol,
                self._timeframe,
            )
            store = DerivedCsvStore(historical_root=default_historical_root())
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
        can_save = has_spec and self._current_spec.kind != "construct"

        self._apply_button.setEnabled(has_spec)
        self._save_button.setEnabled(can_save)

        if not has_spec:
            self._status_label.setText("No tool selected.")
        elif self._current_spec.kind == "construct":
            self._status_label.setText(
                f"{self._current_spec.title} (Construct) — apply supported, save not yet available"
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

        return values

    def _build_payload(self) -> Optional[Dict[str, Any]]:
        if self._current_spec is None:
            return None

        return {
            "tool_type": self._current_spec.kind,
            "tool_key": self._current_spec.key,
            "tool_title": self._current_spec.title,
            "exchange": self._exchange,
            "market_type": self._market_type,
            "symbol": self._symbol,
            "timeframe": self._timeframe,
            "params": self._collect_param_values(),
            "required_inputs": [inp.name for inp in self._current_spec.data_inputs],
            "output_names": list(self._current_spec.output_names),
        }

    def _build_instance_key(self, params: Dict[str, Any]) -> str:
        """
        Must match HistoricalChartController._build_instance_key().
        """
        if not params:
            return "default"

        parts: list[str] = []
        for key in sorted(params.keys()):
            val = str(params[key]).strip().lower()
            val = val.replace(" ", "-")
            val = val.replace("=", "-")
            val = val.replace(",", "-")
            parts.append(f"{key}-{val}")
        return "__".join(parts)

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
        instance_key = self._build_instance_key(params)

        store = DerivedCsvStore(historical_root=default_historical_root())
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

        lines = [
            f"Exchange: {exchange_display}",
            f"Market type: {self._market_type}",
            f"Asset: {self._symbol}",
            f"Timeframe: {self._timeframe}",
            f"Tool type: {tool_type}",
            f"Tool: {tool_title}",
            "",
            "Parameters / metadata:",
        ]

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

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
        payload = self._build_payload()
        if payload is None:
            return
        self.apply_requested.emit(payload)

    def _on_save_clicked(self) -> None:
        payload = self._build_payload()
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