from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "leonardo" / "gui" / "chart"
PANES = SRC / "panes"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_policy_module():
    path = SRC / "overlay_display_policy.py"
    spec = importlib.util.spec_from_file_location("overlay_display_policy_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_overlay_row_uses_compact_buttons_and_value_toggle() -> None:
    source = _source(PANES / "overlay_rows.py")

    assert 'setText("Style")' not in source
    assert 'setText("Edit")' not in source
    assert "_value_toggle_btn = QToolButton" in source
    assert "value_toggled = Signal(str, bool)" in source
    assert "_value_toggle_btn.setCheckable(True)" in source


def test_price_pane_uses_pane_local_value_expansion_state() -> None:
    source = _source(PANES / "price_pane.py")

    assert "_overlay_values_expanded_by_row_key: dict[str, bool]" in source
    assert "def _on_overlay_row_value_toggled" in source
    assert "policy.values_allowed" in source
    assert "policy.values_default_expanded" in source
    assert "expanded=expanded" in source
    assert 'fragments.append(f"{self._series_tail_label(series.title)}: {value_text}")' not in source
    assert 'row_text = f"{series.title}: {value_text}"' not in source


def test_overlay_display_policy_declares_compact_study_policies() -> None:
    source = _source(SRC / "overlay_display_policy.py")

    for token in (
        "peaks_troughs",
        "universal_trend_classifier",
        "strategy",
        "bb",
        "hck",
        "P/T",
        "UTC",
        "STR",
        "BB",
        "HCK",
    ):
        assert token in source


def test_overlay_display_policy_hides_event_and_large_raw_values() -> None:
    policy_module = _load_policy_module()

    peaks = policy_module.build_overlay_study_display_policy(
        title="Peaks & Troughs",
        render_keys=["peaks_troughs|study|peak_fractal_3"],
    )
    assert peaks.compact_label == "P/T"
    assert peaks.values_allowed is False

    utc = policy_module.build_overlay_study_display_policy(
        title="Universal Trend Classifier",
        render_keys=["universal_trend_classifier|study|hr_start_marker"],
    )
    assert utc.compact_label == "UTC"
    assert utc.values_allowed is False

    strategy = policy_module.build_overlay_study_display_policy(
        title="Strategy",
        render_keys=["strategy|study|st_ema_1", "strategy|study|st_bb_upper_band"],
    )
    assert strategy.compact_label == "STR"
    assert strategy.values_allowed is True
    assert strategy.values_default_expanded is False


def test_compact_signal_labels_cover_strategy_sub_outputs() -> None:
    policy_module = _load_policy_module()

    assert policy_module.compact_signal_label("bb", "bb_upper_band") == "U"
    assert policy_module.compact_signal_label("bb", "bb_middle") == "M"
    assert policy_module.compact_signal_label("bb", "bb_lower_band") == "L"
    assert policy_module.compact_signal_label("hck", "fast_vwap") == "F"
    assert policy_module.compact_signal_label("hck", "slow_vwap") == "S"
    assert policy_module.compact_signal_label("strategy", "st_bb_upper_band") == "U"
    assert policy_module.compact_signal_label("strategy", "st_bb_middle") == "M"
    assert policy_module.compact_signal_label("strategy", "st_bb_lower_band") == "L"
    assert policy_module.compact_signal_label("strategy", "st_fast_vwap") == "F"
    assert policy_module.compact_signal_label("strategy", "st_slow_vwap") == "S"
    assert policy_module.compact_signal_label("strategy", "st_ema_1") == "E1"
    assert policy_module.compact_signal_label("strategy", "st_sma_6") == "S6"
    assert policy_module.compact_signal_label("strategy", "st_vwap_color") == ""
