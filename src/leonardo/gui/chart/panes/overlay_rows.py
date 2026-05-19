from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QHBoxLayout, QToolButton, QWidget


class _StudyRow(QWidget):
    style_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

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
        self._style_btn.setText("Style")
        self._style_btn.setToolTip("Edit display style")
        self._style_btn.clicked.connect(self._emit_style)

        self._edit_btn = QToolButton(self)
        self._edit_btn.setText("Edit")
        self._edit_btn.setToolTip("Edit computation parameters")
        self._edit_btn.clicked.connect(self._emit_edit)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("X")
        self._remove_btn.setToolTip("Remove study from chart")
        self._remove_btn.clicked.connect(self._emit_remove)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._style_btn, 0)
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

    def _emit_style(self) -> None:
        self.style_requested.emit(self._action_id)

    def _emit_edit(self) -> None:
        self.edit_requested.emit(self._action_id)

    def _emit_remove(self) -> None:
        self.remove_requested.emit(self._action_id)
