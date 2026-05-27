from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtWidgets import QDialog

from leonardo.gui.chart.model import OverlayFill, Series, SeriesStyle
from leonardo.gui.chart.panes.contracts import PaneBackgroundRegion
from leonardo.gui.chart.study_style_defaults import (
    build_default_background_region_styles,
    build_default_overlay_fills,
    get_signal_style_defaults,
    get_study_style_defaults,
)
from leonardo.gui.chart.study_style_resolver import resolve_study_render_state
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_OSCILLATOR,
    PANE_TARGET_PRICE,
    StudyFillStyle,
    StudySignalStyle,
)
from leonardo.gui.windows._historical_chart_panel.study_style_dialog import StudyStyleDialog


def _coerce_values_list(raw: object) -> Sequence[float]:
    """Return an immutable-by-contract sequence without cloning hot-path buffers."""
    if raw is None:
        return []
    if hasattr(raw, "__len__") and hasattr(raw, "__getitem__"):
        return raw  # type: ignore[return-value]
    try:
        return list(raw)  # type: ignore[arg-type]
    except Exception:
        return []


class HistoricalChartPanelStyleMixin:
    """Panel-owned helper methods extracted from HistoricalChartPanel.

    This mixin has no durable state of its own. It operates on the
    HistoricalChartPanel instance that owns the chart-local study session.
    """

    def _line_key_from_render_key(self, render_key: str) -> str:
        text = str(render_key).strip()
        if not text:
            return ""
        return text.rsplit("|", 1)[-1].strip()

    def _chart_local_render_key_for_study(
        self,
        *,
        study_instance_id: str,
        render_key: str,
    ) -> str:
        """
        Return a chart-local render key unique to one study instance.

        Controller-owned projected series keys identify computation truth, but
        the panel owns chart-local study identity. Widening renderer-facing
        keys into chart-local identity prevents duplicate same-config studies
        from colliding inside workspace/model render state while preserving the
        tool key as the first segment and the emitted signal key as the last.
        """
        resolved_instance_id = str(study_instance_id).strip()
        raw_key = str(render_key).strip()
        if not resolved_instance_id or not raw_key:
            return raw_key

        instance_token = f"|{resolved_instance_id}|"
        if instance_token in raw_key:
            return raw_key

        if "|" not in raw_key:
            return f"{raw_key}|{resolved_instance_id}|{raw_key}"

        head, line_key = raw_key.rsplit("|", 1)
        return f"{head}|{resolved_instance_id}|{line_key}"

    def _chart_local_series_list_for_study(
        self,
        *,
        study_instance_id: str,
        series_list: List[Series],
    ) -> List[Series]:
        """Namespace one resident-local series payload into chart-local identity."""
        resolved_study_id = str(study_instance_id).strip()
        if not resolved_study_id:
            return [
                Series(
                    key=str(getattr(series, "key", "") or ""),
                    title=str(getattr(series, "title", "") or ""),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
                for series in series_list
            ]

        chart_local_series: List[Series] = []
        for series in series_list:
            raw_key = str(getattr(series, "key", "") or "").strip()
            if not raw_key:
                continue

            chart_local_series.append(
                Series(
                    key=self._chart_local_render_key_for_study(
                        study_instance_id=resolved_study_id,
                        render_key=raw_key,
                    ),
                    title=str(getattr(series, "title", "") or raw_key),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
            )

        return chart_local_series

    def _chart_local_style_driver_series_list_for_study(
        self,
        *,
        study_instance_id: str,
        style_driver_series_list: List[Series],
    ) -> List[Series]:
        """Namespace resident-local style-driver state without making it renderable."""
        resolved_study_id = str(study_instance_id).strip()
        chart_local_series: List[Series] = []

        for series in style_driver_series_list:
            raw_key = str(getattr(series, "key", "") or "").strip()
            if not raw_key:
                continue

            chart_local_series.append(
                Series(
                    key=(
                        self._chart_local_render_key_for_study(
                            study_instance_id=resolved_study_id,
                            render_key=raw_key,
                        )
                        if resolved_study_id
                        else raw_key
                    ),
                    title=str(getattr(series, "title", "") or raw_key),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
            )

        return chart_local_series

    def _defaults_study_key_for_tool_key(self, tool_key: str) -> str:
        normalized = str(tool_key).strip().lower()
        if normalized == "tdirsi":
            return "tdi"
        if normalized == "utc":
            return "universal_trend_classifier"
        return normalized

    def _is_volume_mean_line_key(self, *, defaults_study_key: str, line_key: str) -> bool:
        """Return whether a signal key should use the Volume mean line default."""
        return (
            str(defaults_study_key).strip().lower() == "volume"
            and str(line_key).strip().startswith("volume_mean_")
        )

    def _current_workspace_series_for_render_key(
        self,
        *,
        study: ChartStudyInstance,
        render_key: str,
    ) -> Optional[Series]:
        """
        Return the currently applied workspace/model series for one render key.

        This helper is used only for chart-local style seeding and style reapply.
        It does not compute anything and it does not mutate model state.

        Important:
        For managed overlay studies, workspace may already have applied static
        defaults before the panel persists chart-local study state. Reading the
        series back from the model allows the panel to persist the actual
        resolved defaults instead of neutral compatibility placeholders.
        """
        normalized_render_key = str(render_key).strip()
        if not normalized_render_key:
            return None

        if study.pane_target == PANE_TARGET_OSCILLATOR:
            try:
                return self._workspace.model.oscillator(normalized_render_key)
            except Exception:
                return None

        try:
            return self._workspace.model.overlays().get(normalized_render_key)
        except Exception:
            return None

    def _default_signal_style_for_line_key(
        self,
        *,
        defaults_study_key: str,
        line_key: str,
        show_label: bool,
        show_value: bool,
    ) -> Optional[StudySignalStyle]:
        """
        Resolve the canonical default signal style for one emitted line key.

        Static defaults belong to study_style_defaults.py. This helper keeps the
        panel aligned with that contract instead of inventing neutral fallback
        styles locally.
        """
        resolved_defaults_study_key = str(defaults_study_key).strip().lower()
        resolved_line_key = str(line_key).strip()
        if not resolved_defaults_study_key or not resolved_line_key:
            return None

        signal_defaults = get_signal_style_defaults(
            study_key=resolved_defaults_study_key,
            signal_name=resolved_line_key,
        )
        if signal_defaults is None:
            return None

        return StudySignalStyle(
            color=str(getattr(signal_defaults, "color", "") or "").strip(),
            line_width=max(1, int(getattr(signal_defaults, "line_width", 1) or 1)),
            line_style=str(getattr(signal_defaults, "line_style", "solid") or "solid"),
            visible=bool(getattr(signal_defaults, "visible", True)),
            show_label=bool(show_label),
            show_value=bool(show_value),
            render_mode=str(getattr(signal_defaults, "render_mode", "line") or "line"),
            marker_shape=str(getattr(signal_defaults, "marker_shape", "") or ""),
            marker_size=int(getattr(signal_defaults, "marker_size", 0) or 0),
            marker_text=str(getattr(signal_defaults, "marker_text", "") or ""),
            marker_text_color=str(getattr(signal_defaults, "marker_text_color", "") or ""),
            marker_offset_px=int(getattr(signal_defaults, "marker_offset_px", 0) or 0),
        )

    def _seed_study_style_from_series_and_defaults(
        self,
        *,
        study: ChartStudyInstance,
        series_list: List[Series],
    ) -> ChartStudyInstance:
        """
        Persist chart-local static defaults into ChartStudyInstance.style.

        Why this exists
        ---------------
        study_style_defaults.py is the single source of truth for static study
        defaults. The panel is responsible for applying those defaults at
        apply-time *and* persisting them into the study state so later style
        reapply does not fall back to neutral compatibility placeholders.

        Important contract
        ------------------
        - no computation occurs here
        - no values are recomputed or reindexed
        - this method only persists resolved chart-local visual defaults
        """
        if not series_list:
            return study

        defaults_study_key = self._defaults_study_key_for_tool_key(study.computation.tool_key)
        updated_style = study.style
        touched = False

        # Map original apply payload series by render key so we can fall back to
        # their metadata when a workspace/model series is not yet available.
        input_series_by_key = {
            str(series.key).strip(): series
            for series in series_list
            if str(series.key).strip()
        }

        render_keys = list(getattr(study.runtime, "render_keys", []) or [])
        if not render_keys:
            render_keys = list(input_series_by_key.keys())

        for render_key in render_keys:
            line_key = self._line_key_from_render_key(render_key)
            if not line_key:
                continue

            canonical_signal_style: Optional[StudySignalStyle] = None
            if self._is_volume_mean_line_key(
                defaults_study_key=defaults_study_key,
                line_key=line_key,
            ):
                canonical_signal_style = self._default_signal_style_for_line_key(
                    defaults_study_key=defaults_study_key,
                    line_key=line_key,
                    show_label=bool(updated_style.show_label),
                    show_value=bool(updated_style.show_value),
                )

            # Preserve existing chart-local per-signal style on edit/reapply.
            # Missing line keys are still seeded below so new outputs inherit the
            # canonical default pipeline.
            if line_key in updated_style.signal_styles:
                if canonical_signal_style is not None:
                    existing_signal_style = updated_style.signal_styles[line_key]
                    corrected_signal_style = existing_signal_style
                    if (
                        str(getattr(corrected_signal_style, "render_mode", "") or "").strip().lower()
                        != "line"
                    ):
                        corrected_signal_style = replace(corrected_signal_style, render_mode="line")
                    if not str(getattr(corrected_signal_style, "color", "") or "").strip():
                        corrected_signal_style = replace(
                            corrected_signal_style,
                            color=canonical_signal_style.color,
                        )
                    if corrected_signal_style != existing_signal_style:
                        updated_style = updated_style.with_signal_style(
                            line_key,
                            style=corrected_signal_style,
                        )
                        touched = True
                continue

            seeded_signal_style: Optional[StudySignalStyle] = canonical_signal_style

            # Prefer the style currently present on the applied workspace/model
            # series because that already reflects any static default resolution
            # performed downstream during the first apply.
            if seeded_signal_style is None:
                workspace_series = self._current_workspace_series_for_render_key(
                    study=study,
                    render_key=render_key,
                )
                source_series = workspace_series or input_series_by_key.get(render_key)
                source_style_obj = getattr(source_series, "style", None) if source_series is not None else None
            else:
                source_style_obj = None
            if source_style_obj is not None:
                resolved_color = str(getattr(source_style_obj, "color", "") or "").strip()
                resolved_width = max(1, int(getattr(source_style_obj, "line_width", 1) or 1))
                resolved_line_style = str(getattr(source_style_obj, "line_style", "solid") or "solid")
                resolved_visible = bool(getattr(source_style_obj, "visible", True))
                resolved_render_mode = str(getattr(source_style_obj, "render_mode", "line") or "line")
                resolved_marker_shape = str(getattr(source_style_obj, "marker_shape", "") or "")
                resolved_marker_size = int(getattr(source_style_obj, "marker_size", 0) or 0)
                resolved_marker_text = str(getattr(source_style_obj, "marker_text", "") or "")
                resolved_marker_text_color = str(getattr(source_style_obj, "marker_text_color", "") or "")
                resolved_marker_offset_px = int(getattr(source_style_obj, "marker_offset_px", 0) or 0)

                # Persist only materially resolved style state. Neutral
                # compatibility values must not become fake sources of truth.
                if (
                    resolved_color
                    or resolved_width != 1
                    or resolved_line_style != "solid"
                    or resolved_visible is not True
                    or resolved_render_mode != "line"
                    or resolved_marker_shape
                    or resolved_marker_size != 0
                    or resolved_marker_text
                    or resolved_marker_text_color
                    or resolved_marker_offset_px != 0
                ):
                    seeded_signal_style = StudySignalStyle(
                        color=resolved_color,
                        line_width=resolved_width,
                        line_style=resolved_line_style,
                        visible=resolved_visible,
                        show_label=bool(updated_style.show_label),
                        show_value=bool(updated_style.show_value),
                        render_mode=resolved_render_mode,
                        marker_shape=resolved_marker_shape,
                        marker_size=resolved_marker_size,
                        marker_text=resolved_marker_text,
                        marker_text_color=resolved_marker_text_color,
                        marker_offset_px=resolved_marker_offset_px,
                    )

            # If the applied series does not yet carry a concrete style, fall
            # back to the canonical defaults file directly.
            if seeded_signal_style is None:
                seeded_signal_style = self._default_signal_style_for_line_key(
                    defaults_study_key=defaults_study_key,
                    line_key=line_key,
                    show_label=bool(updated_style.show_label),
                    show_value=bool(updated_style.show_value),
                )

            if seeded_signal_style is None:
                continue

            updated_style = updated_style.with_signal_style(line_key, style=seeded_signal_style)
            touched = True

        if study.pane_target == PANE_TARGET_PRICE:
            default_fills = build_default_overlay_fills(
                study_instance_id=study.instance_id,
                study_key=defaults_study_key,
                series_list=series_list,
            )
            for fill in default_fills:
                fill_id = str(getattr(fill, "fill_id", "") or "").strip()
                if "|fill|" in fill_id:
                    fill_id = fill_id.split("|fill|", 1)[-1].strip()
                if not fill_id:
                    continue

                signal_a = self._line_key_from_render_key(fill.series_a)
                signal_b = self._line_key_from_render_key(fill.series_b)
                if not signal_a or not signal_b:
                    continue

                existing_fill_style = updated_style.fill_styles.get(fill_id)
                if existing_fill_style is not None:
                    if (
                        str(getattr(existing_fill_style, "signal_a", "") or "").strip() != signal_a
                        or str(getattr(existing_fill_style, "signal_b", "") or "").strip() != signal_b
                    ):
                        updated_style = updated_style.with_fill_style(
                            fill_id,
                            fill_style=existing_fill_style.merged(
                                {
                                    "signal_a": signal_a,
                                    "signal_b": signal_b,
                                }
                            ),
                        )
                        touched = True
                    continue

                updated_style = updated_style.with_fill_style(
                    fill_id,
                    fill_style=StudyFillStyle(
                        fill_id=fill_id,
                        signal_a=signal_a,
                        signal_b=signal_b,
                        color=str(getattr(fill, "color", None) or "").strip(),
                        opacity=float(getattr(fill, "opacity", 0.12)),
                        visible=bool(getattr(fill, "visible", True)),
                    ),
                )
                touched = True

        if not touched:
            return study

        updated_study = study.with_style(updated_style)
        self._study_registry.add(updated_study)
        return updated_study




    def _signal_names_for_study(self, study: ChartStudyInstance) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()

        for render_key in study.runtime.render_keys:
            line_key = self._line_key_from_render_key(render_key)
            if not line_key or line_key in seen:
                continue
            seen.add(line_key)
            names.append(line_key)

        return names

    def _default_fill_specs_for_signal_names(self, signal_names: List[str]) -> List[Dict[str, Any]]:
        signal_set = {str(name).strip() for name in signal_names if str(name).strip()}
        specs: List[Dict[str, Any]] = []

        if {"bb_upper_band", "bb_lower_band"}.issubset(signal_set):
            specs.append(
                {
                    "fill_id": "bb_band",
                    "title": "Fill: BB Band",
                    "signal_a": "bb_upper_band",
                    "signal_b": "bb_lower_band",
                }
            )

        if {"fast_vwap", "slow_vwap"}.issubset(signal_set):
            specs.append(
                {
                    "fill_id": "hck_band",
                    "title": "Fill: HCK Band",
                    "signal_a": "fast_vwap",
                    "signal_b": "slow_vwap",
                }
            )

        return specs

    def _editable_fill_specs_for_study(self, study: ChartStudyInstance) -> List[Dict[str, Any]]:
        signal_names = self._signal_names_for_study(study)
        signal_set = {str(name).strip() for name in signal_names if str(name).strip()}
        specs: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for fill_id, fill_style in study.style.fill_styles.items():
            resolved_fill_id = str(getattr(fill_style, "fill_id", "") or fill_id).strip()
            signal_a = str(getattr(fill_style, "signal_a", "")).strip()
            signal_b = str(getattr(fill_style, "signal_b", "")).strip()
            if not resolved_fill_id or resolved_fill_id in seen:
                continue
            if signal_a not in signal_set or signal_b not in signal_set:
                continue
            seen.add(resolved_fill_id)

            specs.append(
                {
                    "fill_id": resolved_fill_id,
                    "title": f"Fill: {resolved_fill_id}",
                    "signal_a": signal_a,
                    "signal_b": signal_b,
                }
            )

        for spec in self._default_fill_specs_for_signal_names(signal_names):
            fill_id = str(spec["fill_id"]).strip()
            if fill_id in seen:
                continue
            seen.add(fill_id)
            specs.append(spec)

        return specs

    def _series_key_by_signal_name(self, series_list: List[Series]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for series in series_list:
            signal_name = self._line_key_from_render_key(series.key)
            if signal_name and signal_name not in mapping:
                mapping[signal_name] = series.key
        return mapping

    def _series_by_signal_name(self, series_list: List[Series]) -> Dict[str, Series]:
        mapping: Dict[str, Series] = {}
        for series in series_list:
            signal_name = self._line_key_from_render_key(str(getattr(series, "key", "") or ""))
            if signal_name and signal_name not in mapping:
                mapping[signal_name] = series
        return mapping

    def _truthy_style_driver_value(self, value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        try:
            numeric = float(value)
        except Exception:
            return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
        if numeric != numeric:
            return False
        return numeric != 0.0

    def _background_region_module_regions(self, study: ChartStudyInstance) -> List[Dict[str, Any]]:
        module_state = self._style_module_state_by_key(study, "background_regions")
        if module_state is None or not bool(getattr(module_state, "enabled", True)):
            return []

        config = getattr(module_state, "config", {}) or {}
        if not isinstance(config, dict):
            return []

        raw_regions = config.get("regions", []) or []
        if not isinstance(raw_regions, list):
            return []

        regions: List[Dict[str, Any]] = []
        for raw_region in raw_regions:
            if isinstance(raw_region, dict):
                regions.append(dict(raw_region))
        return regions

    def _study_uses_background_regions(self, study: ChartStudyInstance) -> bool:
        return bool(self._background_region_module_regions(study))

    def _build_background_regions_for_study(
        self,
        *,
        study: ChartStudyInstance,
        style_driver_series_list: List[Series],
    ) -> List[PaneBackgroundRegion]:
        """Resolve boolean style-driver state runs into explicit price-pane regions."""
        if study.pane_target != PANE_TARGET_PRICE:
            return []

        region_specs = self._background_region_module_regions(study)
        if not region_specs or not style_driver_series_list:
            return []

        series_by_signal = self._series_by_signal_name(style_driver_series_list)
        regions: List[PaneBackgroundRegion] = []

        for region_spec in region_specs:
            driver_signal = str(region_spec.get("driver_signal", "") or "").strip()
            if not driver_signal:
                continue

            driver_series = series_by_signal.get(driver_signal)
            if driver_series is None:
                continue

            values = _coerce_values_list(getattr(driver_series, "values", None))
            if not values:
                continue

            region_key = str(region_spec.get("region_key", driver_signal) or driver_signal).strip()
            color = region_spec.get("color", None)
            try:
                opacity = float(region_spec.get("opacity", 0.08) or 0.0)
            except Exception:
                opacity = 0.08
            visible = bool(region_spec.get("visible", True))
            label = str(region_spec.get("label", region_key) or region_key)

            run_start: Optional[int] = None
            last_index = len(values) - 1
            for idx, value in enumerate(values):
                active = self._truthy_style_driver_value(value)
                if active and run_start is None:
                    run_start = idx

                if run_start is not None and ((not active) or idx == last_index):
                    run_end = idx if active and idx == last_index else idx - 1
                    if run_end >= run_start:
                        regions.append(
                            PaneBackgroundRegion(
                                region_id=(
                                    f"{study.instance_id}|background|"
                                    f"{region_key}|{run_start}-{run_end}"
                                ),
                                start_index=int(run_start),
                                end_index=int(run_end),
                                color=str(color) if color is not None else None,
                                opacity=max(0.0, min(1.0, opacity)),
                                visible=visible,
                                source_signal=driver_signal,
                                label=label,
                            )
                        )
                    run_start = None

        return regions

    def _apply_background_regions_for_study(
        self,
        *,
        study: ChartStudyInstance,
        background_regions: List[PaneBackgroundRegion],
    ) -> None:
        if study.pane_target != PANE_TARGET_PRICE:
            return
        if not hasattr(self._workspace, "apply_overlay_background_regions"):
            return

        try:
            self._workspace.apply_overlay_background_regions(
                study_instance_id=study.instance_id,
                background_regions=background_regions,
            )
        except Exception:
            return

    def _build_overlay_fill_descriptors_for_study(
        self,
        *,
        study: ChartStudyInstance,
        series_list: List[Series],
    ) -> Optional[List[OverlayFill]]:
        if study.pane_target != PANE_TARGET_PRICE:
            return None
        if not series_list:
            return None
        if not study.style.fill_styles:
            return None

        series_key_by_signal = self._series_key_by_signal_name(series_list)
        fill_descriptors: List[OverlayFill] = []

        for fill_id, fill_style in study.style.fill_styles.items():
            resolved_fill_id = str(getattr(fill_style, "fill_id", "") or fill_id).strip()
            if not resolved_fill_id:
                continue

            signal_a = str(getattr(fill_style, "signal_a", "")).strip()
            signal_b = str(getattr(fill_style, "signal_b", "")).strip()
            if not signal_a or not signal_b:
                continue

            series_a_key = series_key_by_signal.get(signal_a)
            series_b_key = series_key_by_signal.get(signal_b)
            if not series_a_key or not series_b_key:
                continue

            fill_descriptors.append(
                OverlayFill(
                    fill_id=resolved_fill_id,
                    series_a=series_a_key,
                    series_b=series_b_key,
                    color=getattr(fill_style, "color", None),
                    opacity=float(getattr(fill_style, "opacity", 0.15)),
                    visible=bool(getattr(fill_style, "visible", True)),
                )
            )

        return fill_descriptors

    def _chart_local_overlay_fill_id(
        self,
        *,
        study_instance_id: str,
        fill_id: str,
    ) -> str:
        """
        Return a chart-local overlay fill id unique to one study instance.

        Fill styles store canonical semantic ids such as ``bb_band`` or
        ``hck_band`` so style editing and module targeting stay stable. The
        workspace/model layer, however, needs chart-local fill identity so
        duplicate same-config overlay studies do not collide during reapply,
        removal, or projected refresh.
        """
        resolved_study_id = str(study_instance_id).strip()
        resolved_fill_id = str(fill_id).strip()
        if not resolved_study_id or not resolved_fill_id:
            return resolved_fill_id
        if "|fill|" in resolved_fill_id:
            return resolved_fill_id
        return f"{resolved_study_id}|fill|{resolved_fill_id}"

    def _chart_local_overlay_fill_descriptors_for_study(
        self,
        *,
        study: ChartStudyInstance,
        fill_descriptors: Optional[List[OverlayFill]],
    ) -> Optional[List[OverlayFill]]:
        if fill_descriptors is None:
            return None

        chart_local_fill_descriptors: List[OverlayFill] = []
        for fill in fill_descriptors:
            chart_local_fill_id = self._chart_local_overlay_fill_id(
                study_instance_id=study.instance_id,
                fill_id=str(getattr(fill, "fill_id", "") or ""),
            )
            if not chart_local_fill_id:
                continue

            chart_local_fill_descriptors.append(
                OverlayFill(
                    fill_id=chart_local_fill_id,
                    series_a=str(getattr(fill, "series_a", "") or "").strip(),
                    series_b=str(getattr(fill, "series_b", "") or "").strip(),
                    color=getattr(fill, "color", None),
                    opacity=float(getattr(fill, "opacity", 0.15)),
                    visible=bool(getattr(fill, "visible", True)),
                )
            )

        return chart_local_fill_descriptors

    def _resolved_signal_style_for_render_key(
        self,
        *,
        study: ChartStudyInstance,
        render_key: str,
        existing_series: Optional[Series],
    ) -> SeriesStyle:
        """
        Resolve the effective chart-local signal style for one render key.

        Resolution order
        ----------------
        1. existing applied series style, when present
        2. non-neutral global compatibility fields from StudyDisplayStyle
        3. explicit per-signal overrides from StudyDisplayStyle.signal_styles

        This keeps the legacy/global style layer as a compatibility fallback
        without letting neutral compatibility values erase already resolved
        study defaults that are present on the current series.
        """
        line_key = self._line_key_from_render_key(render_key)
        signal_style: Optional[StudySignalStyle] = study.style.signal_styles.get(line_key)
        defaults_study_key = self._defaults_study_key_for_tool_key(study.computation.tool_key)
        volume_mean_default_style: Optional[StudySignalStyle] = None
        if self._is_volume_mean_line_key(
            defaults_study_key=defaults_study_key,
            line_key=line_key,
        ):
            volume_mean_default_style = self._default_signal_style_for_line_key(
                defaults_study_key=defaults_study_key,
                line_key=line_key,
                show_label=bool(getattr(study.style, "show_label", True)),
                show_value=bool(getattr(study.style, "show_value", True)),
            )
            if signal_style is None:
                signal_style = volume_mean_default_style

        existing_style = getattr(existing_series, "style", None) if existing_series is not None else None

        color = ""
        line_width = 1
        line_style = "solid"
        visible = True
        render_mode = "line"
        marker_shape = ""
        marker_size = 0
        marker_text = ""
        marker_text_color = ""
        marker_offset_px = 0

        if existing_style is not None:
            color = str(getattr(existing_style, "color", "") or "").strip()
            line_width = max(1, int(getattr(existing_style, "line_width", 1) or 1))
            line_style = str(getattr(existing_style, "line_style", "solid") or "solid")
            visible = bool(getattr(existing_style, "visible", True))
            render_mode = str(getattr(existing_style, "render_mode", "line") or "line")
            marker_shape = str(getattr(existing_style, "marker_shape", "") or "")
            marker_size = int(getattr(existing_style, "marker_size", 0) or 0)
            marker_text = str(getattr(existing_style, "marker_text", "") or "")
            marker_text_color = str(getattr(existing_style, "marker_text_color", "") or "")
            marker_offset_px = int(getattr(existing_style, "marker_offset_px", 0) or 0)

        global_color = str(getattr(study.style, "color", "") or "").strip()
        global_line_width = max(1, int(getattr(study.style, "line_width", 1) or 1))
        global_line_style = str(getattr(study.style, "line_style", "solid") or "solid")
        global_visible = bool(getattr(study.style, "visible", True))

        if global_color:
            color = global_color
        if global_line_width != 1 or existing_style is None:
            line_width = global_line_width
        if global_line_style != "solid" or existing_style is None:
            line_style = global_line_style
        if (global_visible is not True) or existing_style is None:
            visible = global_visible

        if signal_style is not None:
            signal_color = str(getattr(signal_style, "color", "") or "").strip()
            if signal_color:
                color = signal_color

            line_width_value = getattr(signal_style, "line_width", None)
            if line_width_value is not None:
                line_width = max(1, int(line_width_value or line_width))

            line_style_value = getattr(signal_style, "line_style", None)
            if line_style_value is not None:
                line_style = str(line_style_value or line_style)

            visible = bool(getattr(signal_style, "visible", visible))

            render_mode_value = getattr(signal_style, "render_mode", None)
            if render_mode_value is not None:
                render_mode = str(render_mode_value or render_mode)

            marker_shape_value = getattr(signal_style, "marker_shape", None)
            if marker_shape_value is not None:
                marker_shape = str(marker_shape_value)

            marker_size_value = getattr(signal_style, "marker_size", None)
            if marker_size_value is not None:
                marker_size = int(marker_size_value)

            marker_text_value = getattr(signal_style, "marker_text", None)
            if marker_text_value is not None:
                marker_text = str(marker_text_value)

            marker_text_color_value = getattr(signal_style, "marker_text_color", None)
            if marker_text_color_value is not None:
                marker_text_color = str(marker_text_color_value)

            marker_offset_px_value = getattr(signal_style, "marker_offset_px", None)
            if marker_offset_px_value is not None:
                marker_offset_px = int(marker_offset_px_value)

        if volume_mean_default_style is not None:
            if not color:
                color = volume_mean_default_style.color
            render_mode = "line"

        return SeriesStyle(
            color=color,
            line_width=max(1, int(line_width)),
            line_style=line_style,
            visible=visible,
            render_mode=render_mode,
            marker_shape=marker_shape or None,
            marker_size=max(0, int(marker_size)),
            marker_text=marker_text,
            marker_text_color=marker_text_color or None,
            marker_offset_px=int(marker_offset_px),
        )

    def _study_has_style_module(self, study: ChartStudyInstance, module_key: str) -> bool:
        resolved_module_key = str(module_key).strip()
        if not resolved_module_key:
            return False

        for module in getattr(study.style, "style_modules", []) or []:
            if str(getattr(module, "module_key", "")).strip() == resolved_module_key:
                return True
        return False

    def _style_module_state_by_key(
        self,
        study: ChartStudyInstance,
        module_key: str,
    ) -> Optional[object]:
        resolved_module_key = str(module_key).strip()
        if not resolved_module_key:
            return None

        for module in getattr(study.style, "style_modules", []) or []:
            if str(getattr(module, "module_key", "")).strip() == resolved_module_key:
                return module
        return None

    def _style_module_condition_scope(
        self,
        study: ChartStudyInstance,
        module_key: str,
    ) -> str:
        module_state = self._style_module_state_by_key(study, module_key)
        if module_state is None or not bool(getattr(module_state, "enabled", True)):
            return ""

        config = getattr(module_state, "config", {}) or {}
        if not isinstance(config, dict):
            return ""

        condition = config.get("condition", {}) or {}
        if not isinstance(condition, dict):
            return ""

        return str(condition.get("scope", "") or "").strip().lower()

    def _study_uses_hck_historical_segmentation(self, study: ChartStudyInstance) -> bool:
        tool_key = str(getattr(study.computation, "tool_key", "")).strip().lower()
        if tool_key != "hck" or not study.is_renderable():
            return False

        return (
            self._style_module_condition_scope(study, "conditional_line_color") == "historical"
            or self._style_module_condition_scope(study, "conditional_fill_color") == "historical"
        )

    def _updated_study_with_resolved_render_keys(
        self,
        study: ChartStudyInstance,
        series_list: List[Series],
    ) -> ChartStudyInstance:
        resolved_render_keys = [
            str(getattr(series, "key", "") or "").strip()
            for series in series_list
            if str(getattr(series, "key", "") or "").strip()
        ]
        if not resolved_render_keys:
            return study

        if list(getattr(study.runtime, "render_keys", []) or []) == resolved_render_keys:
            return study

        updated = study.with_runtime(
            replace(
                study.runtime,
                render_keys=list(resolved_render_keys),
            )
        )
        self._study_registry.add(updated)
        return updated

    def _seed_default_style_modules_for_study(self, study: ChartStudyInstance) -> ChartStudyInstance:
        """
        Seed default chart-local style modules for studies that benefit from
        immediate visual state derivation after apply.

        Current phase:
        - HCK gets historical segmented line/fill color modules
        - Universal Trend Classifier gets state-driven background regions
        """
        tool_key = str(getattr(study.computation, "tool_key", "")).strip().lower()
        if not study.is_renderable():
            return study

        updated = study

        if tool_key in {"universal_trend_classifier", "utc"} and not self._study_has_style_module(updated, "background_regions"):
            region_defaults = build_default_background_region_styles(
                self._defaults_study_key_for_tool_key(tool_key)
            )
            if region_defaults:
                updated = updated.with_style(
                    updated.style.upsert_style_module(
                        "background_regions",
                        enabled=True,
                        config_patch={
                            "regions": [
                                {
                                    "region_key": str(default.region_key),
                                    "driver_signal": str(default.driver_signal),
                                    "color": default.color,
                                    "opacity": float(default.opacity),
                                    "visible": bool(default.visible),
                                    "label": str(default.label or default.region_key),
                                }
                                for default in region_defaults
                            ]
                        },
                    )
                )

        if tool_key != "hck":
            if updated is not study:
                self._study_registry.add(updated)
            return updated

        if not self._study_has_style_module(updated, "conditional_line_color"):
            updated = updated.with_style(
                updated.style.upsert_style_module(
                    "conditional_line_color",
                    enabled=True,
                    config_patch={
                        "condition": {
                            "lhs_signal": "fast_vwap",
                            "operator": "gt",
                            "rhs_signal": "slow_vwap",
                            "scope": "historical",
                        },
                        "targets": [
                            {
                                "signal": "fast_vwap",
                                "true_color": "#22C55E",
                                "false_color": "#EF4444",
                            },
                            {
                                "signal": "slow_vwap",
                                "true_color": "#22C55E",
                                "false_color": "#EF4444",
                            },
                        ],
                    },
                )
            )

        if not self._study_has_style_module(updated, "conditional_fill_color"):
            updated = updated.with_style(
                updated.style.upsert_style_module(
                    "conditional_fill_color",
                    enabled=True,
                    config_patch={
                        "condition": {
                            "lhs_signal": "fast_vwap",
                            "operator": "gt",
                            "rhs_signal": "slow_vwap",
                            "scope": "historical",
                        },
                        "target_fill_id": "hck_band",
                        "true_color": "#22C55E",
                        "false_color": "#EF4444",
                        "true_opacity": 0.08,
                        "false_opacity": 0.08,
                    },
                )
            )

        if updated is not study:
            self._study_registry.add(updated)

        return updated

    def _on_price_pane_study_style_requested(self, render_key: str) -> None:
        normalized = str(render_key).strip()
        if not normalized:
            self._on_error("Cannot style study: empty identifier.")
            return

        study = self._study_registry.get(normalized)
        if study is None:
            study = self._find_study_by_render_key(normalized)

        if study is None:
            self._on_error(
                f"Cannot style study: identifier '{normalized}' is not registered."
            )
            return

        dialog = StudyStyleDialog(
            display_name=study.display_name,
            current_style=study.style,
            signal_names=self._signal_names_for_study(study),
            fill_specs=self._editable_fill_specs_for_study(study),
            defaults_study_key=self._defaults_study_key_for_tool_key(study.computation.tool_key),
            parent=self,
        )
        dialog.apply_requested.connect(
            lambda: self._apply_style_dialog_patch(
                instance_id=study.instance_id,
                dialog=dialog,
            )
        )
        if dialog.exec() != int(QDialog.Accepted):
            return

        self._apply_style_dialog_patch(
            instance_id=study.instance_id,
            dialog=dialog,
        )

    def _on_oscillator_pane_study_style_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot style oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot style oscillator study: unknown instance_id '{normalized_id}'.")
            return

        dialog = StudyStyleDialog(
            display_name=study.display_name,
            current_style=study.style,
            signal_names=self._signal_names_for_study(study),
            fill_specs=[],
            defaults_study_key=self._defaults_study_key_for_tool_key(study.computation.tool_key),
            parent=self,
        )
        dialog.apply_requested.connect(
            lambda: self._apply_style_dialog_patch(
                instance_id=study.instance_id,
                dialog=dialog,
            )
        )
        if dialog.exec() != int(QDialog.Accepted):
            return

        self._apply_style_dialog_patch(
            instance_id=study.instance_id,
            dialog=dialog,
        )

    def _apply_style_dialog_patch(
        self,
        *,
        instance_id: str,
        dialog: StudyStyleDialog,
    ) -> None:
        try:
            patch = dialog.style_patch()
            self._apply_study_style_patch(instance_id, patch)
        except Exception as exc:
            self._on_error(f"Cannot apply style: {exc!r}")

    def _apply_study_style_patch(self, instance_id: str, patch: Dict[str, Any]) -> None:
        study = self._study_registry.get(instance_id)
        if study is None:
            self._on_error(f"Cannot apply style: unknown instance_id '{instance_id}'.")
            return

        if not self._study_is_renderable(study):
            self._on_error(f"Cannot apply style: study '{study.display_name}' is non-visual.")
            return

        global_patch = patch
        signal_patches: Dict[str, Dict[str, Any]] = {}
        fill_patches: Dict[str, Dict[str, Any]] = {}
        module_patches: Dict[str, Dict[str, Any]] = {}
        peaks_troughs_group_patch: Dict[str, Any] = {}

        if isinstance(patch, dict) and "global_patch" in patch:
            raw_global_patch = patch.get("global_patch", {}) or {}
            raw_signal_patches = patch.get("signal_patches", {}) or {}
            raw_fill_patches = patch.get("fill_patches", {}) or {}
            raw_module_patches = patch.get("module_patches", {}) or {}

            global_patch = dict(raw_global_patch) if isinstance(raw_global_patch, dict) else {}

            if isinstance(raw_signal_patches, dict):
                signal_patches = {
                    str(signal_name).strip(): dict(signal_patch)
                    for signal_name, signal_patch in raw_signal_patches.items()
                    if str(signal_name).strip() and isinstance(signal_patch, dict)
                }

            if isinstance(raw_fill_patches, dict):
                fill_patches = {
                    str(fill_id).strip(): dict(fill_patch)
                    for fill_id, fill_patch in raw_fill_patches.items()
                    if str(fill_id).strip() and isinstance(fill_patch, dict)
                }

            if isinstance(raw_module_patches, dict):
                module_patches = {
                    str(module_key).strip(): dict(module_patch)
                    for module_key, module_patch in raw_module_patches.items()
                    if str(module_key).strip() and isinstance(module_patch, dict)
                }

            raw_peaks_troughs_group_patch = patch.get("peaks_troughs_group_patch", {}) or {}
            if isinstance(raw_peaks_troughs_group_patch, dict):
                peaks_troughs_group_patch = dict(raw_peaks_troughs_group_patch)

        new_style = study.style.merged(global_patch)

        for signal_name, signal_patch in signal_patches.items():
            signal_name_key = str(signal_name).strip()
            current_signal_style = new_style.signal_styles.get(signal_name_key, StudySignalStyle())
            merged_signal_style = current_signal_style.merged(signal_patch)
            new_style = new_style.with_signal_style(signal_name_key, style=merged_signal_style)

        if study.computation.tool_key == "peaks_troughs" and peaks_troughs_group_patch:
            peak_offset_px = max(0, int(peaks_troughs_group_patch.get("peak_offset_px", 0) or 0))
            trough_offset_px = max(0, int(peaks_troughs_group_patch.get("trough_offset_px", 0) or 0))
            defaults_study_key = self._defaults_study_key_for_tool_key(study.computation.tool_key)

            for signal_name in self._signal_names_for_study(study):
                normalized_signal_name = str(signal_name).strip().lower()
                current_signal_style = new_style.signal_styles.get(normalized_signal_name)
                if current_signal_style is None:
                    current_signal_style = self._default_signal_style_for_line_key(
                        defaults_study_key=defaults_study_key,
                        line_key=normalized_signal_name,
                        show_label=bool(new_style.show_label),
                        show_value=bool(new_style.show_value),
                    ) or StudySignalStyle()

                if normalized_signal_name.startswith("peak_"):
                    new_style = new_style.with_signal_style(
                        normalized_signal_name,
                        style=replace(
                            current_signal_style,
                            marker_offset_px=-peak_offset_px,
                        ),
                    )
                elif normalized_signal_name.startswith("trough_"):
                    new_style = new_style.with_signal_style(
                        normalized_signal_name,
                        style=replace(
                            current_signal_style,
                            marker_offset_px=trough_offset_px,
                        ),
                    )

        for fill_id, fill_patch in fill_patches.items():
            new_style = new_style.with_fill_style(fill_id, patch=fill_patch)

        for module_key, module_patch in module_patches.items():
            enabled = bool(module_patch.get("enabled", True))
            config_patch = module_patch.get("config_patch", {}) or {}
            if not isinstance(config_patch, dict):
                config_patch = {}

            new_style = new_style.upsert_style_module(
                module_key,
                enabled=enabled,
                config_patch=config_patch,
            )

        updated_study = replace(study, style=new_style)
        self._study_registry.add(updated_study)

        updated_study = self._reapply_study_render_series(updated_study, force_surface_static_reset=True)

        self._on_error(
            f"Updated style for study '{updated_study.display_name}' "
            f"(color={updated_study.style.color}, "
            f"width={updated_study.style.line_width}, "
            f"line_style={updated_study.style.line_style}, "
            f"signal_overrides={len(updated_study.style.signal_styles)}, "
            f"fill_overrides={len(updated_study.style.fill_styles)}, "
            f"module_overrides={len(getattr(updated_study.style, 'style_modules', []) or [])})."
        )

    def _resolved_render_state_for_study(
        self,
        *,
        study: ChartStudyInstance,
        series_list: List[Series],
    ) -> tuple[List[Series], Optional[List[OverlayFill]]]:
        """Resolve the final chart-local render state for one study payload.

        The panel owns chart-local style truth. Whenever resident-local study
        projections are refreshed, the panel must therefore resolve the final
        styled series/fill payload *before* workspace applies it, instead of
        letting workspace paint a raw payload and then repaint a styled version.
        """
        if not self._study_is_renderable(study) or not series_list:
            return ([], None)

        styled_series_list: List[Series] = []
        for series in series_list:
            render_key = str(getattr(series, "key", "") or "").strip()
            if not render_key:
                continue

            existing_series = self._current_workspace_series_for_render_key(
                study=study,
                render_key=render_key,
            ) or series

            effective_style = self._resolved_signal_style_for_render_key(
                study=study,
                render_key=render_key,
                existing_series=existing_series,
            )
            styled_series_list.append(
                Series(
                    key=str(series.key),
                    title=str(series.title),
                    values=series.values,
                    style=effective_style,
                )
            )

        if not styled_series_list:
            return ([], None)

        initial_fill_descriptors = None
        if study.pane_target == PANE_TARGET_PRICE:
            initial_fill_descriptors = self._build_overlay_fill_descriptors_for_study(
                study=study,
                series_list=styled_series_list,
            )

        resolved_series_list, resolved_fill_descriptors = resolve_study_render_state(
            study=study,
            series_list=styled_series_list,
            fill_descriptors=initial_fill_descriptors,
        )

        if study.pane_target == PANE_TARGET_PRICE:
            resolved_fill_descriptors = self._chart_local_overlay_fill_descriptors_for_study(
                study=study,
                fill_descriptors=resolved_fill_descriptors,
            )
        return (
            resolved_series_list,
            self._chart_local_overlay_fill_descriptors_for_study(
                study=study,
                fill_descriptors=resolved_fill_descriptors,
            ),
        )


    def _force_surface_static_reset_for_study(self, study: ChartStudyInstance) -> None:
        """Force the renderer static-scene cache to rebuild on the next paint.

        Style edits are visual-only but still require a full static-scene rebuild
        so cached pixmaps do not keep painting stale pens. This helper keeps the
        change localized to the style-reapply path.
        """
        try:
            pane_target = str(getattr(study, "pane_target", "") or "").strip().lower()
        except Exception:
            pane_target = ""

        surface = None

        if pane_target == PANE_TARGET_OSCILLATOR:
            pane = None
            if hasattr(self._workspace, "oscillator_pane_for_study"):
                try:
                    pane = self._workspace.oscillator_pane_for_study(study.instance_id)
                except Exception:
                    pane = None
            if pane is not None:
                surface = getattr(pane, "_surface", None)
        else:
            price_pane = getattr(self._workspace, "_price", None)
            if price_pane is not None:
                surface = getattr(price_pane, "_surface", None)

        if surface is None:
            return

        try:
            if hasattr(surface, "_static_pixmap"):
                setattr(surface, "_static_pixmap", None)
            if hasattr(surface, "_static_pixmap_key"):
                setattr(surface, "_static_pixmap_key", None)
            if hasattr(surface, "_static_rebuild_scheduled"):
                setattr(surface, "_static_rebuild_scheduled", False)
            if hasattr(surface, "update"):
                surface.update()
        except Exception:
            return



    def _reapply_study_render_series(
        self,
        study: ChartStudyInstance,
        *,
        source_series_list: Optional[List[Series]] = None,
        source_style_driver_series_list: Optional[List[Series]] = None,
        force_surface_static_reset: bool = False,
    ) -> ChartStudyInstance:
        if not self._study_is_renderable(study):
            return study

        current_series_list: List[Series] = []
        if source_series_list:
            current_series_list = [
                Series(
                    key=str(getattr(series, "key", "") or ""),
                    title=str(getattr(series, "title", "") or ""),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
                for series in source_series_list
                if str(getattr(series, "key", "") or "").strip()
            ]

        current_style_driver_series_list: List[Series] = []
        if source_style_driver_series_list:
            current_style_driver_series_list = self._chart_local_style_driver_series_list_for_study(
                study_instance_id=study.instance_id,
                style_driver_series_list=[
                    Series(
                        key=str(getattr(series, "key", "") or ""),
                        title=str(getattr(series, "title", "") or ""),
                        values=_coerce_values_list(getattr(series, "values", None)),
                        style=getattr(series, "style", None),
                    )
                    for series in source_style_driver_series_list
                    if str(getattr(series, "key", "") or "").strip()
                ],
            )

        if not current_style_driver_series_list and hasattr(self, "_projected_chart_local_style_driver_series_list_for_study"):
            try:
                current_style_driver_series_list = self._projected_chart_local_style_driver_series_list_for_study(study)  # type: ignore[attr-defined]
            except Exception:
                current_style_driver_series_list = []

        if not current_series_list and self._study_uses_hck_historical_segmentation(study):
            current_series_list = self._projected_chart_local_series_list_for_study(study)

        if not current_series_list:
            for render_key in study.runtime.render_keys:
                existing_series = None
                if study.pane_target == PANE_TARGET_OSCILLATOR:
                    existing_series = self._workspace.model.oscillator(render_key)
                else:
                    existing_series = self._workspace.model.overlays().get(render_key)

                if existing_series is None:
                    continue

                current_series_list.append(
                    Series(
                        key=existing_series.key,
                        title=existing_series.title,
                        values=existing_series.values,
                        style=existing_series.style,
                    )
                )

        resolved_series_list, resolved_fill_descriptors = self._resolved_render_state_for_study(
            study=study,
            series_list=current_series_list,
        )

        if not resolved_series_list:
            return study

        updated_study = self._updated_study_with_resolved_render_keys(
            study,
            resolved_series_list,
        )

        background_regions = self._build_background_regions_for_study(
            study=updated_study,
            style_driver_series_list=current_style_driver_series_list,
        )

        if updated_study.pane_target == PANE_TARGET_PRICE:
            # Always hand off an explicit region payload for price-pane studies.
            # An empty list clears stale regions owned by the same study.
            self._apply_background_regions_for_study(
                study=updated_study,
                background_regions=background_regions,
            )

        if updated_study.pane_target == PANE_TARGET_OSCILLATOR:
            if hasattr(self._workspace, "apply_oscillator_study"):
                try:
                    self._workspace.apply_oscillator_study(
                        study_instance_id=updated_study.instance_id,
                        title=updated_study.display_name,
                        series_list=resolved_series_list,
                    )
                    self._connect_oscillator_pane_signals_for_study(updated_study.instance_id)
                    self._apply_oscillator_visual_policy_for_study(updated_study)
                    if force_surface_static_reset:
                        self._force_surface_static_reset_for_study(updated_study)
                    return updated_study
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study reapply fallback engaged for "
                        f"'{updated_study.display_name}': {e!r}"
                    )

            for styled_series in resolved_series_list:
                self._workspace.apply_oscillator_series(styled_series)
            if force_surface_static_reset:
                self._force_surface_static_reset_for_study(updated_study)
            return updated_study

        if hasattr(self._workspace, "apply_overlay_study"):
            try:
                self._workspace.apply_overlay_study(
                    study_instance_id=updated_study.instance_id,
                    title=updated_study.display_name,
                    series_list=resolved_series_list,
                    fill_descriptors=resolved_fill_descriptors,
                )
                if force_surface_static_reset:
                    self._force_surface_static_reset_for_study(updated_study)
                return updated_study
            except Exception as e:
                self._on_error(
                    f"Managed overlay study reapply fallback engaged for "
                    f"'{updated_study.display_name}': {e!r}"
                )

        for styled_series in resolved_series_list:
            self._workspace.apply_overlay_series(styled_series)

        if force_surface_static_reset:
            self._force_surface_static_reset_for_study(updated_study)

        return updated_study
