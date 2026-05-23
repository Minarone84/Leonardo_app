from __future__ import annotations

from pathlib import Path


def test_main_window_exposes_historical_menu_for_ohlcv_maintenance() -> None:
    source = Path("src/leonardo/gui/main_window.py").read_text(encoding="utf-8")

    assert 'mb.addMenu("Historical")' in source
    assert 'mb.addMenu("menu3")' not in source
    assert "Menu3" not in source
    assert "historical_menu.addAction(self._act_open_ohlcv_maintenance)" in source
    assert 'QAction("Historical Download Manager", self)' in source
    assert 'QAction("OHLCV Maintenance...", self)' in source
    assert 'QAction("Historical Data Manager", self)' in source
    assert "self._act_open_ohlcv_maintenance.triggered.connect(self._open_ohlcv_maintenance)" in source
    assert "self._act_open_ohlcv_maintenance.setEnabled(True)" in source


def test_main_window_routes_ohlcv_maintenance_menu_through_window_manager() -> None:
    source = Path("src/leonardo/gui/main_window.py").read_text(encoding="utf-8")

    assert "def _open_ohlcv_maintenance(self) -> None:" in source
    assert "wm.open_ohlcv_maintenance(parent=self)" in source
    assert "OHLCVMaintenanceWindow" not in source
