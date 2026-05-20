from __future__ import annotations

from typing import Any, Dict, List, Optional

from leonardo.gui.chart.studies import ChartStudyInstance, PANE_TARGET_OSCILLATOR
from leonardo.gui.chart.study_style_defaults import get_study_style_defaults
from leonardo.financial_tools.ft_specs import get_oscillator_visual_spec


class HistoricalChartPanelOscillatorPolicyMixin:
    """Panel-owned helper methods extracted from HistoricalChartPanel.

    This mixin has no durable state of its own. It operates on the
    HistoricalChartPanel instance that owns the chart-local study session.
    """

    def _build_default_oscillator_levels_from_spec(
        self,
        guide_levels: Any,
    ) -> List[Dict[str, Any]]:
        """
        Translate declarative oscillator guide-level metadata from ft_specs into
        chart-local pane visual policy entries.

        Spec remains semantic-only. Concrete line colors/styles stay downstream
        in the chart layer.
        """
        if not isinstance(guide_levels, (list, tuple)):
            return []

        levels: List[Dict[str, Any]] = []

        for guide_level in guide_levels:
            try:
                value = float(getattr(guide_level, "value"))
            except Exception:
                continue

            kind = str(getattr(guide_level, "kind", "")).strip().lower()
            visible = bool(getattr(guide_level, "visible", True))

            if kind == "overbought":
                color = "#EF4444"
            elif kind == "oversold":
                color = "#22C55E"
            else:
                color = "#94A3B8"

            levels.append(
                {
                    "value": value,
                    "color": color,
                    "line_style": "dashed",
                    "line_width": 1,
                    "visible": visible,
                }
            )

        return levels

    def _build_default_oscillator_threshold_color_policy_from_spec(
        self,
        *,
        tool_key: str,
        visual_spec: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Translate bounded single-line oscillator semantics into chart-local
        threshold-based line-color policy.

        This remains downstream visual policy. Spec provides the semantic guide
        levels, while the panel decides whether to seed runtime threshold color
        behavior for the current chart context.
        """
        normalized_tool_key = str(tool_key).strip().lower()
        if normalized_tool_key not in {"rsi", "arsi", "mfi"}:
            return None

        guide_levels = getattr(visual_spec, "guide_levels", ()) or ()
        lower_value: Optional[float] = None
        upper_value: Optional[float] = None
        neutral_value: Optional[float] = None

        for guide_level in guide_levels:
            kind = str(getattr(guide_level, "kind", "")).strip().lower()
            try:
                value = float(getattr(guide_level, "value"))
            except Exception:
                continue

            if kind == "oversold":
                lower_value = value
            elif kind == "overbought":
                upper_value = value
            elif kind == "center":
                neutral_value = value

        if lower_value is None or upper_value is None:
            return None

        if neutral_value is None:
            neutral_value = (lower_value + upper_value) / 2.0

        return {
            "target_signal": "__primary__",
            "lower_value": lower_value,
            "upper_value": upper_value,
            "neutral_value": neutral_value,
            "oversold_color": "#22C55E",
            "neutral_color": "#94A3B8",
            "overbought_color": "#EF4444",
        }

    def _line_key_from_oscillator_render_key(self, render_key: str) -> str:
        text = str(render_key).strip()
        if not text:
            return ""
        return text.rsplit("|", 1)[-1].strip()

    def _tdirsi_band_fill_signal_names_for_study(
        self,
        study: ChartStudyInstance,
    ) -> Optional[tuple[str, str]]:
        upper_signal = ""
        lower_signal = ""

        for render_key in getattr(study.runtime, "render_keys", []) or []:
            line_key = self._line_key_from_oscillator_render_key(str(render_key))
            if not line_key:
                continue
            if not upper_signal and line_key.startswith("tdirsi_up_"):
                upper_signal = line_key
            elif not lower_signal and line_key.startswith("tdirsi_dn_"):
                lower_signal = line_key

        if upper_signal and lower_signal:
            return (upper_signal, lower_signal)
        return None

    def _default_oscillator_visual_policy_for_study(
        self,
        study: ChartStudyInstance,
    ) -> Optional[Dict[str, Any]]:
        """
        Return default oscillator visual policy from declarative oscillator
        metadata defined in ft_specs.

        Spec declares semantic defaults such as bounds/range mode and guide
        levels. The panel translates those semantics into chart-local pane
        policy without moving rendering behavior into the spec layer.
        """
        if study.pane_target != PANE_TARGET_OSCILLATOR:
            return None

        tool_key = str(getattr(study.computation, "tool_key", "")).strip().lower()
        visual_spec = get_oscillator_visual_spec(tool_key)
        if visual_spec is None:
            return None

        policy: Dict[str, Any] = {}

        range_mode = str(getattr(visual_spec, "range_mode", "") or "").strip().lower()
        bounds = getattr(visual_spec, "bounds", None)

        if range_mode in {"fixed", "fixed_bounds"}:
            policy["range_mode"] = "fixed_bounds"
            if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                try:
                    ymin = float(bounds[0])
                    ymax = float(bounds[1])
                except Exception:
                    ymin = None
                    ymax = None

                if ymin is not None and ymax is not None and ymax > ymin:
                    policy["bounds"] = (ymin, ymax)
        elif range_mode:
            policy["range_mode"] = range_mode

        levels = self._build_default_oscillator_levels_from_spec(
            getattr(visual_spec, "guide_levels", ()),
        )
        if levels:
            policy["levels"] = levels

        threshold_color_policy = self._build_default_oscillator_threshold_color_policy_from_spec(
            tool_key=tool_key,
            visual_spec=visual_spec,
        )
        if threshold_color_policy:
            policy["threshold_line_color"] = threshold_color_policy

        if tool_key == "tdirsi":
            defaults = get_study_style_defaults("tdi")
            fill_defaults = list(getattr(defaults, "fill_defaults", []) or [])
            band_signal_names = self._tdirsi_band_fill_signal_names_for_study(study)

            if fill_defaults and band_signal_names is not None:
                policy.setdefault("fills", [])
                series_a, series_b = band_signal_names

                for fill_def in fill_defaults:
                    fill_key = str(getattr(fill_def, "fill_key", "")).strip().lower()
                    if fill_key not in {"tdi_band", "tdi_band_short"}:
                        continue

                    signal_a_role = str(getattr(fill_def, "signal_a_role", "")).strip()
                    signal_b_role = str(getattr(fill_def, "signal_b_role", "")).strip()
                    if not signal_a_role or not signal_b_role:
                        continue

                    if any(
                        existing_fill.get("series_a") == series_a
                        and existing_fill.get("series_b") == series_b
                        for existing_fill in policy["fills"]
                        if isinstance(existing_fill, dict)
                    ):
                        continue

                    policy["fills"].append(
                        {
                            "series_a": series_a,
                            "series_b": series_b,
                            "color": getattr(fill_def, "color", None),
                            "opacity": float(getattr(fill_def, "opacity", 0.10)),
                            "visible": bool(getattr(fill_def, "visible", True)),
                        }
                    )

        return policy or None

    def _apply_oscillator_visual_policy_for_study(
        self,
        study: ChartStudyInstance,
    ) -> None:
        """
        Push chart-local oscillator visual policy into the workspace pane
        when supported by the current workspace implementation.
        """
        policy = self._default_oscillator_visual_policy_for_study(study)
        if not policy:
            return

        if hasattr(self._workspace, "set_oscillator_pane_visual_policy"):
            try:
                self._workspace.set_oscillator_pane_visual_policy(
                    study_instance_id=study.instance_id,
                    policy=policy,
                )
            except Exception as e:
                self._on_error(
                    f"Oscillator visual policy apply failed for "
                    f"'{study.display_name}': {e!r}"
                )
