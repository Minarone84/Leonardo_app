from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QHBoxLayout, QToolButton, QWidget


class _StudyRow(QWidget):
    style_requested = Signal(str)
    edit_requested = Signal(str)
    metadata_requested = Signal(str)
    remove_requested = Signal(str)
    value_toggled = Signal(str, bool)

    def __init__(
        self,
        row_key: str,
        *,
        action_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._row_key = str(row_key)
        self._action_id = str(action_id).strip() if action_id is not None else self._row_key

        self._label = QLabel("", self)

        self._style_btn = QToolButton(self)
        self._style_btn.setText("S")
        self._style_btn.setToolTip("Edit display style")
        self._style_btn.clicked.connect(self._emit_style)

        self._edit_btn = QToolButton(self)
        self._edit_btn.setText("E")
        self._edit_btn.setToolTip("Edit computation parameters")
        self._edit_btn.clicked.connect(self._emit_edit)

        self._metadata_btn = QToolButton(self)
        self._metadata_btn.setText("M")
        self._metadata_btn.setToolTip("Edit study metadata")
        self._metadata_btn.clicked.connect(self._emit_metadata)

        self._value_toggle_btn = QToolButton(self)
        self._value_toggle_btn.setText("V")
        self._value_toggle_btn.setToolTip("Show or hide current values")
        self._value_toggle_btn.setCheckable(True)
        self._value_toggle_btn.clicked.connect(self._emit_value_toggle)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("X")
        self._remove_btn.setToolTip("Remove study from chart")
        self._remove_btn.clicked.connect(self._emit_remove)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._value_toggle_btn, 0)
        layout.addWidget(self._style_btn, 0)
        layout.addWidget(self._metadata_btn, 0)
        layout.addWidget(self._edit_btn, 0)
        layout.addWidget(self._remove_btn, 0)

    @property
    def row_key(self) -> str:
        return self._row_key

    @property
    def action_id(self) -> str:
        return self._action_id

    def set_action_id(self, action_id: str) -> None:
        resolved = str(action_id).strip()
        self._action_id = resolved or self._row_key

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_label_color(self, color: Optional[str]) -> None:
        resolved = str(color or "").strip()
        if resolved:
            self._label.setStyleSheet(f"color: {resolved};")
        else:
            self._label.setStyleSheet("")

    def set_values_allowed(self, allowed: bool) -> None:
        self._value_toggle_btn.setVisible(bool(allowed))
        self._value_toggle_btn.setEnabled(bool(allowed))

    def set_values_expanded(self, expanded: bool) -> None:
        old_blocked = self._value_toggle_btn.blockSignals(True)
        try:
            self._value_toggle_btn.setChecked(bool(expanded))
        finally:
            self._value_toggle_btn.blockSignals(old_blocked)

    def _emit_style(self) -> None:
        self.style_requested.emit(self._action_id)

    def _emit_edit(self) -> None:
        self.edit_requested.emit(self._action_id)

    def _emit_metadata(self) -> None:
        self.metadata_requested.emit(self._action_id)

    def _emit_value_toggle(self, checked: bool = False) -> None:
        self.value_toggled.emit(self._row_key, self._value_toggle_btn.isChecked())

    def _emit_remove(self) -> None:
        self.remove_requested.emit(self._action_id)
