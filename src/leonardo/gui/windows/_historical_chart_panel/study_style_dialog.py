from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.chart.study_style_defaults import get_study_style_defaults
from leonardo.gui.chart.studies import (
    StudyDisplayStyle,
    StudyFillStyle,
    StudySignalStyle,
)


class StudyStyleDialog(QDialog):
    """
    Chart-local style editor.

    This dialog remains display-only and does not touch computation parameters.

    In this phase it supports:
        - per-signal style overrides for multi-signal studies
    - static fill style overrides for managed overlay fills
    - HCK conditional module styling overrides
    """

    def __init__(
        self,
        *,
        display_name: str,
        current_style: StudyDisplayStyle,
        signal_names: Optional[List[str]] = None,
        fill_specs: Optional[List[Dict[str, Any]]] = None,
        defaults_study_key: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Study Style - {display_name}")
        self.setModal(True)
        self.resize(760, 520)

        self._current_style = current_style
        self._defaults_study_key = str(defaults_study_key).strip().lower()
        self._signal_names = [
            str(name).strip()
            for name in (signal_names or [])
            if str(name).strip()
        ]
        self._fill_specs = [
            {
                "fill_id": str(spec.get("fill_id", "")).strip(),
                "title": str(spec.get("title", "")).strip(),
                "signal_a": str(spec.get("signal_a", "")).strip(),
                "signal_b": str(spec.get("signal_b", "")).strip(),
            }
            for spec in (fill_specs or [])
            if str(spec.get("fill_id", "")).strip()
        ]

        self._initial_signal_style_keys = set(current_style.signal_styles.keys())
        self._initial_fill_style_keys = set(current_style.fill_styles.keys())
        self._hck_module_controls: Optional[Dict[str, QWidget]] = None
        self._peaks_troughs_position_controls: Optional[Dict[str, QWidget]] = None

        self.setStyleSheet(
            """
            QDialog {
                background-color: rgb(18, 18, 22);
                color: rgb(220, 220, 230);
            }
            QLabel {
                color: rgb(210, 210, 220);
            }
            QComboBox, QLineEdit {
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
            QCheckBox {
                color: rgb(220, 220, 230);
            }
            QFrame[section="true"] {
                border: 1px solid rgb(52, 52, 60);
                border-radius: 6px;
                background-color: rgb(22, 22, 28);
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget(scroll_area)
        scroll_layout = QGridLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setHorizontalSpacing(10)
        scroll_layout.setVerticalSpacing(10)

        scroll_area.setWidget(scroll_content)
        root.addWidget(scroll_area, 1)

        sections: List[QWidget] = []

        self._signal_controls: Dict[str, Dict[str, QWidget]] = {}
        if self._signal_names:
            for signal_name in self._signal_names:
                effective = self._effective_signal_style(signal_name)
                controls = self._build_style_controls(
                    color=str(effective.color or "").strip(),
                    line_width=int(effective.line_width),
                    line_style=str(effective.line_style or "solid"),
                    visible=bool(effective.visible),
                    parent=self,
                )
                self._signal_controls[signal_name] = controls

                section = self._build_style_section_frame(
                    title=f"Signal: {signal_name}",
                    controls=controls,
                    parent=self,
                )
                sections.append(section)

        self._fill_controls: Dict[str, Dict[str, QWidget]] = {}
        if self._fill_specs:
            for fill_spec in self._fill_specs:
                fill_id = fill_spec["fill_id"]
                effective = self._effective_fill_style(fill_spec)

                controls = self._build_fill_controls(
                    color=str(effective.color or "").strip(),
                    opacity=float(effective.opacity),
                    visible=bool(effective.visible),
                    parent=self,
                )
                self._fill_controls[fill_id] = controls

                section = self._build_fill_section_frame(
                    title=fill_spec["title"] or fill_id,
                    fill_spec=fill_spec,
                    controls=controls,
                    parent=self,
                )
                sections.append(section)

        if self._is_peaks_troughs_style_dialog():
            peak_offset_px, trough_offset_px = self._extract_peaks_troughs_marker_offsets()
            self._peaks_troughs_position_controls = self._build_peaks_troughs_position_controls(
                peak_offset_px=peak_offset_px,
                trough_offset_px=trough_offset_px,
                parent=self,
            )
            peaks_troughs_section = self._build_peaks_troughs_position_section_frame(
                title="Marker Position (Peaks & Troughs)",
                controls=self._peaks_troughs_position_controls,
                parent=self,
            )
            sections.append(peaks_troughs_section)

        if self._has_hck_modules():
            hck_config = self._extract_hck_module_config()
            self._hck_module_controls = self._build_hck_controls(
                bullish_line=hck_config["bullish_line"],
                bearish_line=hck_config["bearish_line"],
                bullish_fill=hck_config["bullish_fill"],
                bearish_fill=hck_config["bearish_fill"],
                bullish_opacity=float(hck_config["bullish_opacity"]),
                bearish_opacity=float(hck_config["bearish_opacity"]),
                line_enabled=bool(hck_config["line_enabled"]),
                fill_enabled=bool(hck_config["fill_enabled"]),
                parent=self,
            )

            hck_section = self._build_hck_section_frame(
                title="Conditional Styling (HCK)",
                controls=self._hck_module_controls,
                parent=self,
            )
            sections.append(hck_section)

        for idx, section in enumerate(sections):
            row = idx // 2
            col = idx % 2
            scroll_layout.addWidget(section, row, col)

        scroll_layout.setColumnStretch(0, 1)
        scroll_layout.setColumnStretch(1, 1)
        scroll_layout.setRowStretch((len(sections) + 1) // 2, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _default_signal_style(self, signal_name: str) -> Optional[StudySignalStyle]:
        normalized_signal_name = str(signal_name).strip()
        if not self._defaults_study_key or not normalized_signal_name:
            return None

        defaults = get_study_style_defaults(self._defaults_study_key)
        signal_defaults = defaults.signal_defaults.get(normalized_signal_name)
        if signal_defaults is None:
            signal_defaults = defaults.signal_defaults.get("__primary__")

        if signal_defaults is None:
            return None

        return StudySignalStyle(
            color=str(signal_defaults.color or "").strip(),
            line_width=max(1, int(signal_defaults.line_width)),
            line_style=str(signal_defaults.line_style or "solid"),
            visible=bool(signal_defaults.visible),
            show_label=bool(getattr(self._current_style, "show_label", True)),
            show_value=bool(getattr(self._current_style, "show_value", True)),
            render_mode=str(getattr(signal_defaults, "render_mode", "line") or "line"),
            marker_shape=str(getattr(signal_defaults, "marker_shape", "") or ""),
            marker_size=int(getattr(signal_defaults, "marker_size", 0) or 0),
            marker_text=str(getattr(signal_defaults, "marker_text", "") or ""),
            marker_text_color=str(getattr(signal_defaults, "marker_text_color", "") or ""),
            marker_offset_px=int(getattr(signal_defaults, "marker_offset_px", 0) or 0),
        )

    def _default_fill_style(self, fill_spec: Dict[str, Any]) -> Optional[StudyFillStyle]:
        if not self._defaults_study_key:
            return None

        fill_id = str(fill_spec.get("fill_id", "")).strip()
        if not fill_id:
            return None

        defaults = get_study_style_defaults(self._defaults_study_key)
        fill_defaults = list(getattr(defaults, "fill_defaults", []) or [])
        for fill_default in fill_defaults:
            if str(getattr(fill_default, "fill_key", "")).strip() != fill_id:
                continue

            return StudyFillStyle(
                fill_id=fill_id,
                signal_a=str(fill_spec.get("signal_a", "")).strip(),
                signal_b=str(fill_spec.get("signal_b", "")).strip(),
                color=str(getattr(fill_default, "color", None) or "").strip(),
                opacity=float(getattr(fill_default, "opacity", 0.12)),
                visible=bool(getattr(fill_default, "visible", True)),
            )

        return None

    def _effective_signal_style(self, signal_name: str) -> StudySignalStyle:
        explicit = self._current_style.signal_styles.get(str(signal_name).strip())
        if explicit is not None:
            return explicit

        return StudySignalStyle(
            color=str(self._current_style.color or "").strip() or "#FFA500",
            line_width=max(1, int(getattr(self._current_style, "line_width", 2))),
            line_style=str(self._current_style.line_style or "solid"),
            visible=bool(getattr(self._current_style, "visible", True)),
            show_label=bool(getattr(self._current_style, "show_label", True)),
            show_value=bool(getattr(self._current_style, "show_value", True)),
            render_mode="line",
            marker_shape="",
            marker_size=0,
            marker_text="",
            marker_text_color="",
            marker_offset_px=0,
        )

    def _effective_fill_style(self, fill_spec: Dict[str, Any]) -> StudyFillStyle:
        fill_id = str(fill_spec.get("fill_id", "")).strip()
        explicit = self._current_style.fill_styles.get(fill_id)
        if explicit is not None:
            return explicit

        return StudyFillStyle(
            fill_id=fill_id,
            signal_a=str(fill_spec.get("signal_a", "")).strip(),
            signal_b=str(fill_spec.get("signal_b", "")).strip(),
            color="#3B82F6",
            opacity=0.12,
            visible=True,
        )

    def _style_modules(self) -> List[object]:
        modules = getattr(self._current_style, "style_modules", []) or []
        if isinstance(modules, list):
            return list(modules)
        return []

    def _module_by_key(self, module_key: str) -> Optional[object]:
        normalized = str(module_key).strip()
        if not normalized:
            return None

        for module in self._style_modules():
            if str(getattr(module, "module_key", "")).strip() == normalized:
                return module
        return None


    def _is_peaks_troughs_style_dialog(self) -> bool:
        return self._defaults_study_key == "peaks_troughs" and bool(self._signal_names)

    def _extract_peaks_troughs_marker_offsets(self) -> tuple[int, int]:
        peak_offset_px = 0
        trough_offset_px = 0

        for signal_name in self._signal_names:
            normalized = str(signal_name).strip().lower()
            effective = self._effective_signal_style(signal_name)
            offset_px = int(getattr(effective, "marker_offset_px", 0) or 0)

            if normalized.startswith("peak_"):
                peak_offset_px = max(peak_offset_px, abs(offset_px))
            elif normalized.startswith("trough_"):
                trough_offset_px = max(trough_offset_px, abs(offset_px))

        return peak_offset_px, trough_offset_px

    def _has_hck_modules(self) -> bool:
        return (
            self._module_by_key("conditional_line_color") is not None
            and self._module_by_key("conditional_fill_color") is not None
        )

    def _extract_hck_module_config(self) -> Dict[str, Any]:
        line_module = self._module_by_key("conditional_line_color")
        fill_module = self._module_by_key("conditional_fill_color")

        bullish_line = "#22C55E"
        bearish_line = "#EF4444"
        bullish_fill = "#22C55E"
        bearish_fill = "#EF4444"
        bullish_opacity = 0.08
        bearish_opacity = 0.08
        line_enabled = True
        fill_enabled = True

        if line_module is not None:
            line_enabled = bool(getattr(line_module, "enabled", True))
            config = getattr(line_module, "config", {}) or {}
            targets = config.get("targets", []) or []
            if isinstance(targets, list) and targets:
                first_target = targets[0]
                if isinstance(first_target, dict):
                    bullish_line = str(first_target.get("true_color", bullish_line) or bullish_line)
                    bearish_line = str(first_target.get("false_color", bearish_line) or bearish_line)

        if fill_module is not None:
            fill_enabled = bool(getattr(fill_module, "enabled", True))
            config = getattr(fill_module, "config", {}) or {}
            bullish_fill = str(config.get("true_color", bullish_fill) or bullish_fill)
            bearish_fill = str(config.get("false_color", bearish_fill) or bearish_fill)
            try:
                bullish_opacity = float(config.get("true_opacity", bullish_opacity))
            except Exception:
                bullish_opacity = 0.08
            try:
                bearish_opacity = float(config.get("false_opacity", bearish_opacity))
            except Exception:
                bearish_opacity = 0.08

        return {
            "bullish_line": bullish_line,
            "bearish_line": bearish_line,
            "bullish_fill": bullish_fill,
            "bearish_fill": bearish_fill,
            "bullish_opacity": bullish_opacity,
            "bearish_opacity": bearish_opacity,
            "line_enabled": line_enabled,
            "fill_enabled": fill_enabled,
        }

    def _build_style_controls(
        self,
        *,
        color: str,
        line_width: int,
        line_style: str,
        visible: bool,
        parent: QWidget,
    ) -> Dict[str, QWidget]:
        color_edit = QLineEdit(parent)
        color_edit.setPlaceholderText("#RRGGBB")
        color_edit.setText(str(color or "").strip())

        preset_combo = QComboBox(parent)
        preset_combo.addItem("Keep typed color", "")
        for hex_color, label in (
            ("#FFA500", "Orange"),
            ("#00C8FF", "Cyan"),
            ("#1E90FF", "Blue"),
            ("#2962FF", "Deep Blue"),
            ("#BA68C8", "Purple"),
            ("#FFD666", "Amber"),
            ("#4CAF50", "Green"),
            ("#00E676", "Neon Green"),
            ("#EF5350", "Red"),
            ("#FF1744", "Bright Red"),
            ("#FFFFFF", "White"),
            ("#B0BEC5", "Grey"),
        ):
            preset_combo.addItem(label, hex_color)
        preset_combo.currentIndexChanged.connect(
            lambda *_args, combo=preset_combo, edit=color_edit: self._on_preset_changed(combo, edit)
        )

        width_spin = QSpinBox(parent)
        width_spin.setRange(1, 8)
        width_spin.setSingleStep(1)
        width_spin.setMinimumWidth(72)
        width_spin.setValue(max(1, min(8, int(line_width))))
        
        line_style_combo = QComboBox(parent)
        line_style_combo.addItem("Solid", "solid")
        line_style_combo.addItem("Dotted", "dotted")
        line_style_combo.addItem("Dashed", "dashed")
        line_style_combo.addItem("Dash Dot", "dash_dot")
        self._set_combo_data(line_style_combo, line_style)

        visible_check = QCheckBox("Visible", parent)
        visible_check.setChecked(bool(visible))

        return {
            "color_edit": color_edit,
            "preset_combo": preset_combo,
            "width_spin": width_spin,
            "line_style_combo": line_style_combo,
            "visible_check": visible_check,
        }

    def _build_fill_controls(
        self,
        *,
        color: str,
        opacity: float,
        visible: bool,
        parent: QWidget,
    ) -> Dict[str, QWidget]:
        color_edit = QLineEdit(parent)
        color_edit.setPlaceholderText("#RRGGBB")
        color_edit.setText(str(color or "").strip())

        preset_combo = QComboBox(parent)
        preset_combo.addItem("Keep typed color", "")
        for hex_color, label in (
            ("#3B82F6", "Blue"),
            ("#60A5FA", "Light Blue"),
            ("#94A3B8", "Slate"),
            ("#22C55E", "Green"),
            ("#EF4444", "Red"),
            ("#FFFFFF", "White"),
        ):
            preset_combo.addItem(label, hex_color)
        preset_combo.currentIndexChanged.connect(
            lambda *_args, combo=preset_combo, edit=color_edit: self._on_preset_changed(combo, edit)
        )

        opacity_spin = QDoubleSpinBox(parent)
        opacity_spin.setRange(0.0, 1.0)
        opacity_spin.setDecimals(2)
        opacity_spin.setSingleStep(0.05)
        opacity_spin.setValue(max(0.0, min(1.0, float(opacity))))

        visible_check = QCheckBox("Visible", parent)
        visible_check.setChecked(bool(visible))

        return {
            "color_edit": color_edit,
            "preset_combo": preset_combo,
            "opacity_spin": opacity_spin,
            "visible_check": visible_check,
        }

    def _build_peaks_troughs_position_controls(
        self,
        *,
        peak_offset_px: int,
        trough_offset_px: int,
        parent: QWidget,
    ) -> Dict[str, QWidget]:
        above_spin = QSpinBox(parent)
        above_spin.setRange(0, 200)
        above_spin.setSingleStep(1)
        above_spin.setValue(max(0, int(peak_offset_px)))

        below_spin = QSpinBox(parent)
        below_spin.setRange(0, 200)
        below_spin.setSingleStep(1)
        below_spin.setValue(max(0, int(trough_offset_px)))

        return {
            "above_spin": above_spin,
            "below_spin": below_spin,
        }

    def _build_peaks_troughs_position_section_frame(
        self,
        *,
        title: str,
        controls: Dict[str, QWidget],
        parent: QWidget,
    ) -> QFrame:
        frame = QFrame(parent)
        frame.setProperty("section", True)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, frame)
        title_label.setStyleSheet("font-weight: 600; color: rgb(230, 230, 240);")
        layout.addWidget(title_label)

        description_label = QLabel(
            "Above applies to all peak markers. Below applies to all trough markers.",
            frame,
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: rgb(180, 180, 190);")
        layout.addWidget(description_label)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        form.addRow("Above", controls["above_spin"])
        form.addRow("Below", controls["below_spin"])

        return frame

    def _build_hck_controls(
        self,
        *,
        bullish_line: str,
        bearish_line: str,
        bullish_fill: str,
        bearish_fill: str,
        bullish_opacity: float,
        bearish_opacity: float,
        line_enabled: bool,
        fill_enabled: bool,
        parent: QWidget,
    ) -> Dict[str, QWidget]:
        bullish_line_edit = QLineEdit(parent)
        bullish_line_edit.setPlaceholderText("#RRGGBB")
        bullish_line_edit.setText(str(bullish_line or "").strip())

        bearish_line_edit = QLineEdit(parent)
        bearish_line_edit.setPlaceholderText("#RRGGBB")
        bearish_line_edit.setText(str(bearish_line or "").strip())

        bullish_fill_edit = QLineEdit(parent)
        bullish_fill_edit.setPlaceholderText("#RRGGBB")
        bullish_fill_edit.setText(str(bullish_fill or "").strip())

        bearish_fill_edit = QLineEdit(parent)
        bearish_fill_edit.setPlaceholderText("#RRGGBB")
        bearish_fill_edit.setText(str(bearish_fill or "").strip())

        bullish_opacity_spin = QDoubleSpinBox(parent)
        bullish_opacity_spin.setRange(0.0, 1.0)
        bullish_opacity_spin.setDecimals(2)
        bullish_opacity_spin.setSingleStep(0.05)
        bullish_opacity_spin.setValue(max(0.0, min(1.0, float(bullish_opacity))))

        bearish_opacity_spin = QDoubleSpinBox(parent)
        bearish_opacity_spin.setRange(0.0, 1.0)
        bearish_opacity_spin.setDecimals(2)
        bearish_opacity_spin.setSingleStep(0.05)
        bearish_opacity_spin.setValue(max(0.0, min(1.0, float(bearish_opacity))))

        line_enabled_check = QCheckBox("Enable conditional line colors", parent)
        line_enabled_check.setChecked(bool(line_enabled))

        fill_enabled_check = QCheckBox("Enable conditional fill colors", parent)
        fill_enabled_check.setChecked(bool(fill_enabled))

        return {
            "bullish_line_edit": bullish_line_edit,
            "bearish_line_edit": bearish_line_edit,
            "bullish_fill_edit": bullish_fill_edit,
            "bearish_fill_edit": bearish_fill_edit,
            "bullish_opacity_spin": bullish_opacity_spin,
            "bearish_opacity_spin": bearish_opacity_spin,
            "line_enabled_check": line_enabled_check,
            "fill_enabled_check": fill_enabled_check,
        }

    def _build_style_section_frame(
        self,
        *,
        title: str,
        controls: Dict[str, QWidget],
        parent: QWidget,
    ) -> QFrame:
        frame = QFrame(parent)
        frame.setProperty("section", True)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, frame)
        title_label.setStyleSheet("font-weight: 600; color: rgb(230, 230, 240);")
        layout.addWidget(title_label)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        form.addRow("Color", controls["color_edit"])
        form.addRow("Preset", controls["preset_combo"])
        form.addRow("Width", controls["width_spin"])
        form.addRow("Line Style", controls["line_style_combo"])
        form.addRow("", controls["visible_check"])

        return frame

    def _build_fill_section_frame(
        self,
        *,
        title: str,
        fill_spec: Dict[str, Any],
        controls: Dict[str, QWidget],
        parent: QWidget,
    ) -> QFrame:
        frame = QFrame(parent)
        frame.setProperty("section", True)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, frame)
        title_label.setStyleSheet("font-weight: 600; color: rgb(230, 230, 240);")
        layout.addWidget(title_label)

        pair_label = QLabel(
            f"{fill_spec.get('signal_a', '')} ↔ {fill_spec.get('signal_b', '')}",
            frame,
        )
        pair_label.setStyleSheet("color: rgb(180, 180, 190);")
        layout.addWidget(pair_label)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        form.addRow("Fill Color", controls["color_edit"])
        form.addRow("Preset", controls["preset_combo"])
        form.addRow("Opacity", controls["opacity_spin"])
        form.addRow("", controls["visible_check"])

        return frame

    def _build_hck_section_frame(
        self,
        *,
        title: str,
        controls: Dict[str, QWidget],
        parent: QWidget,
    ) -> QFrame:
        frame = QFrame(parent)
        frame.setProperty("section", True)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, frame)
        title_label.setStyleSheet("font-weight: 600; color: rgb(230, 230, 240);")
        layout.addWidget(title_label)

        form = QFormLayout()
        form.setSpacing(8)
        layout.addLayout(form)

        form.addRow("", controls["line_enabled_check"])
        form.addRow("Bullish Line", controls["bullish_line_edit"])
        form.addRow("Bearish Line", controls["bearish_line_edit"])
        form.addRow("", controls["fill_enabled_check"])
        form.addRow("Bullish Fill", controls["bullish_fill_edit"])
        form.addRow("Bearish Fill", controls["bearish_fill_edit"])
        form.addRow("Bullish Opacity", controls["bullish_opacity_spin"])
        form.addRow("Bearish Opacity", controls["bearish_opacity_spin"])

        return frame

    def _on_preset_changed(self, combo: QComboBox, color_edit: QLineEdit) -> None:
        preset = str(combo.currentData() or "").strip()
        if preset:
            color_edit.setText(preset)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        target = str(value or "").strip().lower()
        for idx in range(combo.count()):
            current = str(combo.itemData(idx) or "").strip().lower()
            if current == target:
                combo.setCurrentIndex(idx)
                return

    def _style_patch_from_controls(self, controls: Dict[str, QWidget]) -> Dict[str, Any]:
        color_edit = controls["color_edit"]
        width_spin = controls["width_spin"]
        line_style_combo = controls["line_style_combo"]
        visible_check = controls["visible_check"]

        return {
            "color": self._normalized_color_or_default(str(color_edit.text()).strip()),
            "line_width": int(width_spin.value()),
            "line_style": str(line_style_combo.currentData() or "solid"),
            "visible": bool(visible_check.isChecked()),
        }

    def _fill_patch_from_controls(
        self,
        *,
        fill_spec: Dict[str, Any],
        controls: Dict[str, QWidget],
    ) -> Dict[str, Any]:
        color_edit = controls["color_edit"]
        opacity_spin = controls["opacity_spin"]
        visible_check = controls["visible_check"]

        return {
            "fill_id": str(fill_spec.get("fill_id", "")).strip(),
            "signal_a": str(fill_spec.get("signal_a", "")).strip(),
            "signal_b": str(fill_spec.get("signal_b", "")).strip(),
            "color": self._normalized_color_or_default(str(color_edit.text()).strip()),
            "opacity": float(opacity_spin.value()),
            "visible": bool(visible_check.isChecked()),
        }

    def _peaks_troughs_group_patch_from_controls(self) -> Dict[str, int]:
        if self._peaks_troughs_position_controls is None:
            return {}

        controls = self._peaks_troughs_position_controls
        return {
            "peak_offset_px": int(controls["above_spin"].value()),
            "trough_offset_px": int(controls["below_spin"].value()),
        }

    def _module_patches_from_controls(self) -> Dict[str, Dict[str, Any]]:
        if self._hck_module_controls is None:
            return {}

        controls = self._hck_module_controls

        bullish_line = self._normalized_color_or_default(
            str(controls["bullish_line_edit"].text()).strip()
        )
        bearish_line = self._normalized_color_or_default(
            str(controls["bearish_line_edit"].text()).strip()
        )
        bullish_fill = self._normalized_color_or_default(
            str(controls["bullish_fill_edit"].text()).strip()
        )
        bearish_fill = self._normalized_color_or_default(
            str(controls["bearish_fill_edit"].text()).strip()
        )

        return {
            "conditional_line_color": {
                "enabled": bool(controls["line_enabled_check"].isChecked()),
                "config_patch": {
                    "targets": [
                        {
                            "signal": "fast_vwap",
                            "true_color": bullish_line,
                            "false_color": bearish_line,
                        },
                        {
                            "signal": "slow_vwap",
                            "true_color": bullish_line,
                            "false_color": bearish_line,
                        },
                    ],
                },
            },
            "conditional_fill_color": {
                "enabled": bool(controls["fill_enabled_check"].isChecked()),
                "config_patch": {
                    "true_color": bullish_fill,
                    "false_color": bearish_fill,
                    "true_opacity": float(controls["bullish_opacity_spin"].value()),
                    "false_opacity": float(controls["bearish_opacity_spin"].value()),
                },
            },
        }

    def style_patch(self) -> Dict[str, Any]:
        global_patch: Dict[str, Any] = {}
        signal_patches: Dict[str, Dict[str, Any]] = {}
        fill_patches: Dict[str, Dict[str, Any]] = {}

        signal_baseline = {
            "color": str(self._current_style.color or "").strip() or "#FFA500",
            "line_width": max(1, int(getattr(self._current_style, "line_width", 2))),
            "line_style": str(self._current_style.line_style or "solid"),
            "visible": bool(getattr(self._current_style, "visible", True)),
        }

        for signal_name, controls in self._signal_controls.items():
            signal_patch = self._style_patch_from_controls(controls)
            if signal_name in self._initial_signal_style_keys or signal_patch != signal_baseline:
                signal_patches[signal_name] = signal_patch

        fill_spec_by_id = {
            str(spec["fill_id"]).strip(): spec
            for spec in self._fill_specs
            if str(spec["fill_id"]).strip()
        }

        for fill_id, controls in self._fill_controls.items():
            fill_spec = fill_spec_by_id.get(fill_id)
            if fill_spec is None:
                continue

            fill_patch = self._fill_patch_from_controls(fill_spec=fill_spec, controls=controls)
            effective_fill = self._effective_fill_style(fill_spec)

            baseline = {
                "fill_id": effective_fill.fill_id,
                "signal_a": effective_fill.signal_a,
                "signal_b": effective_fill.signal_b,
                "color": effective_fill.color,
                "opacity": float(effective_fill.opacity),
                "visible": bool(effective_fill.visible),
            }

            if fill_id in self._initial_fill_style_keys or fill_patch != baseline:
                fill_patches[fill_id] = fill_patch

        module_patches = self._module_patches_from_controls()
        peaks_troughs_group_patch = self._peaks_troughs_group_patch_from_controls()

        return {
            "global_patch": global_patch,
            "signal_patches": signal_patches,
            "fill_patches": fill_patches,
            "module_patches": module_patches,
            "peaks_troughs_group_patch": peaks_troughs_group_patch,
        }

    def _normalized_color_or_default(self, text: str) -> str:
        value = text.strip()
        if not value:
            return "#FFA500"

        color = QColor(value)
        if color.isValid():
            return color.name().upper()

        return "#FFA500"
