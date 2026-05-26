from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FinancialToolApplyProgressDialog(QDialog):
    """
    Present Financial Tools Apply preflight details and synchronous progress state.

    The dialog owns only user confirmation and status display. Financial tool
    calculation, study registration, and persistence decisions remain in the
    chart controller and chart panel apply path.
    """

    apply_requested = Signal()

    def __init__(
        self,
        *,
        tool_title: str,
        dataset_label: str,
        input_bar_count: Optional[int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Study")
        self.setModal(True)
        self.setMinimumWidth(420)

        title = str(tool_title or "").strip() or "Selected study"
        dataset = str(dataset_label or "").strip() or "Current chart"
        bar_text = (
            f"Input bars to process: {int(input_bar_count)}"
            if input_bar_count is not None
            else "Input bars to process: unknown"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self._tool_label = QLabel(f"Study: {title}", self)
        self._tool_label.setWordWrap(True)
        root.addWidget(self._tool_label)

        self._dataset_label = QLabel(f"Target: {dataset}", self)
        self._dataset_label.setWordWrap(True)
        root.addWidget(self._dataset_label)

        self._bar_count_label = QLabel(bar_text, self)
        self._bar_count_label.setWordWrap(True)
        root.addWidget(self._bar_count_label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("Ready")
        root.addWidget(self._progress)

        self._status_label = QLabel("Review the Apply target before starting.", self)
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self._apply_button = QPushButton("Apply", self)
        self._apply_button.clicked.connect(self.apply_requested.emit)
        button_row.addWidget(self._apply_button)

        self._cancel_button = QPushButton("Cancel Apply", self)
        self._cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self._cancel_button)

        self._ok_button = QPushButton("OK", self)
        self._ok_button.setEnabled(False)
        self._ok_button.clicked.connect(self.accept)
        button_row.addWidget(self._ok_button)

        root.addLayout(button_row)

    def start_applying(self) -> None:
        """Switch the dialog into non-cancellable synchronous apply state."""
        self._apply_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("Applying...")
        self._ok_button.setEnabled(False)
        self._progress.setRange(0, 0)
        self._progress.setFormat("Applying")
        self._status_label.setText("Applying study to the current chart...")

    def mark_success(self, message: str) -> None:
        """Show completed Apply state and enable dialog dismissal."""
        self._apply_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("Applied")
        self._ok_button.setEnabled(True)
        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._progress.setFormat("Complete")
        self._status_label.setText(str(message or "Study applied."))

    def mark_failure(self, message: str) -> None:
        """Show failed Apply state and enable dialog dismissal."""
        self._apply_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("Apply failed")
        self._ok_button.setEnabled(True)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("Failed")
        self._status_label.setText(str(message or "Apply failed."))
