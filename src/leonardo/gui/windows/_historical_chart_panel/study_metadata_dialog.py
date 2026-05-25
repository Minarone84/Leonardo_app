from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.chart.studies import (
    STUDY_DATASET_ROLE_BRAID,
    STUDY_DATASET_ROLE_CORE_GEOGRAPHY,
    STUDY_DATASET_ROLE_EXPERIMENTAL,
    STUDY_DATASET_ROLE_HELPER_DEPENDENCY,
    STUDY_DATASET_ROLE_PEAKS_TROUGHS,
    STUDY_DATASET_ROLE_SUPPORTING_CONSTRUCT,
    STUDY_DATASET_ROLE_SUPPORTING_INDICATOR,
    STUDY_DATASET_ROLE_SUPPORTING_OSCILLATOR,
    STUDY_DATASET_ROLE_UNSPECIFIED,
    STUDY_DATASET_ROLE_UTC,
    STUDY_DATASET_ROLE_VISUAL_ONLY,
    STUDY_DATASET_ROLE_VOLUME,
    StudyUserMetadata,
    normalize_study_dataset_role,
)


_ROLE_LABELS: tuple[tuple[str, str], ...] = (
    ("Unspecified", STUDY_DATASET_ROLE_UNSPECIFIED),
    ("Core geography", STUDY_DATASET_ROLE_CORE_GEOGRAPHY),
    ("Volume", STUDY_DATASET_ROLE_VOLUME),
    ("Braid", STUDY_DATASET_ROLE_BRAID),
    ("Peaks & Troughs", STUDY_DATASET_ROLE_PEAKS_TROUGHS),
    ("UTC", STUDY_DATASET_ROLE_UTC),
    ("Supporting indicator", STUDY_DATASET_ROLE_SUPPORTING_INDICATOR),
    ("Supporting oscillator", STUDY_DATASET_ROLE_SUPPORTING_OSCILLATOR),
    ("Supporting construct", STUDY_DATASET_ROLE_SUPPORTING_CONSTRUCT),
    ("Helper dependency", STUDY_DATASET_ROLE_HELPER_DEPENDENCY),
    ("Experimental", STUDY_DATASET_ROLE_EXPERIMENTAL),
    ("Visual only", STUDY_DATASET_ROLE_VISUAL_ONLY),
)


class StudyMetadataDialog(QDialog):
    """
    Edit semantic user metadata for one chart-local study instance.

    The dialog owns editing intent only. It does not change computation,
    rendering, style, or study persistence directly.
    """

    def __init__(
        self,
        *,
        display_name: str,
        current_metadata: StudyUserMetadata,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Study Metadata")
        self.setModal(True)

        metadata = (
            current_metadata
            if isinstance(current_metadata, StudyUserMetadata)
            else StudyUserMetadata()
        )

        self._title = QLabel(str(display_name).strip() or "Study", self)
        self._important_check = QCheckBox("Important", self)
        self._important_check.setChecked(bool(metadata.important))

        self._role_combo = QComboBox(self)
        for label, value in _ROLE_LABELS:
            self._role_combo.addItem(label, value)
        self._set_current_role(metadata.dataset_role)

        self._description_edit = QPlainTextEdit(self)
        self._description_edit.setPlainText(metadata.description)
        self._description_edit.setPlaceholderText("Human-readable purpose or export context")
        self._description_edit.setMinimumHeight(90)

        form = QFormLayout()
        form.addRow("", self._important_check)
        form.addRow("Dataset role", self._role_combo)
        form.addRow("Description", self._description_edit)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def user_metadata(self) -> StudyUserMetadata:
        """
        Return the accepted dialog values as normalized study user metadata.
        """

        role = self._role_combo.currentData()
        return StudyUserMetadata(
            important=self._important_check.isChecked(),
            description=self._description_edit.toPlainText().strip(),
            dataset_role=normalize_study_dataset_role(role),
        )

    def _set_current_role(self, value: object) -> None:
        role = normalize_study_dataset_role(value)
        for index in range(self._role_combo.count()):
            if self._role_combo.itemData(index) == role:
                self._role_combo.setCurrentIndex(index)
                return
        self._role_combo.setCurrentIndex(0)
