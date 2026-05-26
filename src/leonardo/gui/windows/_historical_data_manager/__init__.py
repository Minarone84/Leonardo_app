from __future__ import annotations

from leonardo.gui.windows._historical_data_manager.study_setup_dialogs import (
    LoadStudySetupDialog,
    SaveStudySetupDialog,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_dialogs import (
    LoadWorkspaceSnapshotDialog,
    SaveWorkspaceSnapshotDialog,
)
from leonardo.gui.windows._historical_data_manager.notebook_window import (
    HistoricalNotebookWindow,
)
from leonardo.gui.windows._historical_data_manager.notebook_dialogs import (
    SaveNotebookDialog,
)
from leonardo.gui.windows._historical_data_manager.notebook_manager_dialog import (
    HistoricalNotebookManagerDialog,
)
from leonardo.gui.windows._historical_data_manager.study_environment_manager_dialog import (
    StudyEnvironmentManagerDialog,
)
from leonardo.gui.windows._historical_data_manager.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotManagerDialog,
)
from leonardo.gui.windows._historical_data_manager.preset_compatibility import (
    PRESET_STATUS_BROKEN,
    PRESET_STATUS_READY,
    PRESET_STATUS_WARNING,
    PresetCompatibilityIssue,
    PresetCompatibilityReport,
    evaluate_study_setup_compatibility,
    evaluate_workspace_snapshot_compatibility,
    format_compatibility_report,
)

__all__ = [
    "HistoricalNotebookWindow",
    "HistoricalNotebookManagerDialog",
    "LoadStudySetupDialog",
    "LoadWorkspaceSnapshotDialog",
    "PRESET_STATUS_BROKEN",
    "PRESET_STATUS_READY",
    "PRESET_STATUS_WARNING",
    "PresetCompatibilityIssue",
    "PresetCompatibilityReport",
    "SaveNotebookDialog",
    "SaveStudySetupDialog",
    "SaveWorkspaceSnapshotDialog",
    "StudyEnvironmentManagerDialog",
    "WorkspaceSnapshotManagerDialog",
    "evaluate_study_setup_compatibility",
    "evaluate_workspace_snapshot_compatibility",
    "format_compatibility_report",
]
