from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "src" / "leonardo" / "gui" / "windows"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_historical_workspace_view_mode_state_is_not_local_combo_owned() -> None:
    source = _source(WINDOWS / "historical_workspace_widget.py")

    assert "visualization_mode_changed = Signal(str)" in source
    assert "def visualization_mode_label" in source
    assert "self.visualization_mode_changed.emit(mode)" in source
    assert "_view_mode_combo" not in source
    assert "root.addLayout(mode_layout)" not in source


def test_historical_data_manager_window_menu_owns_view_mode_actions_and_label() -> None:
    source = _source(WINDOWS / "historical_data_manager_window.py")

    assert "QActionGroup" in source
    assert "_build_menu_bar_corner_widget" in source
    assert "historicalDataManagerViewModeLabel" in source
    assert "menu_bar.setCornerWidget(corner_widget, Qt.TopRightCorner)" in source
    assert "_action_view_mode_scroll_4" in source
    assert "_action_view_mode_fit_8" in source
    assert "workspace_widget.visualization_mode_changed.connect" in source
    assert "HistoricalWorkspaceWidget.VIEW_MODE_SCROLL_4" in source
    assert "HistoricalWorkspaceWidget.VIEW_MODE_FIT_8" in source
    assert "menu_bar.setCornerWidget(view_mode_label, Qt.TopRightCorner)" not in source


def test_view_mode_label_uses_dynamic_high_contrast_badge_style() -> None:
    source = _source(WINDOWS / "historical_data_manager_window.py")

    assert "def _view_mode_label_stylesheet" in source
    assert "font-size: 13px" in source
    assert "font-weight: bold" in source
    assert "border-radius: 5px" in source
    assert "rgb(210, 235, 255)" in source
    assert "rgb(170, 20, 30)" in source
    assert "rgb(215, 245, 215)" in source
    assert "rgb(190, 95, 0)" in source
    assert "self._view_mode_label.setStyleSheet(self._view_mode_label_stylesheet(mode))" in source
