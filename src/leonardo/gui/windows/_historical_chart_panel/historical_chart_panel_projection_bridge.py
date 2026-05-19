from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from leonardo.gui.chart.model import Series
from leonardo.gui.chart.studies import ChartStudyInstance, PANE_TARGET_OSCILLATOR, PANE_TARGET_PRICE


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


class HistoricalChartPanelProjectionBridgeMixin:

    """Panel-owned helper methods extracted from HistoricalChartPanel.

    This mixin has no durable state of its own. It operates on the
    HistoricalChartPanel instance that owns the chart-local study session.
    """

    def _projected_chart_local_series_list_for_study(
        self,
        study: ChartStudyInstance,
    ) -> List[Series]:
        """Return the current projected base payload for one chart-local study.

        Historical segmented studies must re-resolve from controller-projected
        base series rather than from already segmented workspace render state.
        """
        projection_key = self._study_projection_key_by_instance_id.get(
            str(study.instance_id).strip(),
            "",
        )

        raw_payloads = list(self._controller.get_projected_study_payloads() or [])
        candidate_payloads: List[Dict[str, Any]] = []

        if projection_key:
            candidate_payloads = [
                payload
                for payload in raw_payloads
                if isinstance(payload, dict)
                and str(payload.get("study_projection_key", "")).strip() == projection_key
            ]

        if not candidate_payloads:
            for payload in raw_payloads:
                if not isinstance(payload, dict):
                    continue
                if study in self._registry_studies_for_projected_payload(payload):
                    candidate_payloads.append(payload)

        if not candidate_payloads:
            return []

        payload = candidate_payloads[0]
        normalized_series_list: List[Series] = []
        for series in list(payload.get("series_list", []) or []):
            key = str(getattr(series, "key", "") or "").strip()
            if not key:
                continue
            normalized_series_list.append(
                Series(
                    key=key,
                    title=str(getattr(series, "title", "") or key),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
            )

        if not normalized_series_list:
            return []

        return self._chart_local_series_list_for_study(
            study_instance_id=study.instance_id,
            series_list=normalized_series_list,
        )

    def _projected_chart_local_style_driver_series_list_for_study(
        self,
        study: ChartStudyInstance,
    ) -> List[Series]:
        """Return current projected non-renderable style-driver state for one study.

        The controller owns resident-local projection truth.  The panel maps that
        state onto chart-local study identity without turning it into render
        series.
        """
        projection_key = self._study_projection_key_by_instance_id.get(
            str(study.instance_id).strip(),
            "",
        )

        raw_payloads = list(self._controller.get_projected_study_payloads() or [])
        candidate_payloads: List[Dict[str, Any]] = []

        if projection_key:
            candidate_payloads = [
                payload
                for payload in raw_payloads
                if isinstance(payload, dict)
                and str(payload.get("study_projection_key", "")).strip() == projection_key
            ]

        if not candidate_payloads:
            for payload in raw_payloads:
                if not isinstance(payload, dict):
                    continue
                if study in self._registry_studies_for_projected_payload(payload):
                    candidate_payloads.append(payload)

        if not candidate_payloads:
            return []

        payload = candidate_payloads[0]
        normalized_series_list: List[Series] = []
        for series in list(payload.get("style_driver_series_list", []) or []):
            key = str(getattr(series, "key", "") or "").strip()
            if not key:
                continue
            normalized_series_list.append(
                Series(
                    key=key,
                    title=str(getattr(series, "title", "") or key),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
            )

        if not normalized_series_list:
            return []

        return self._chart_local_style_driver_series_list_for_study(
            study_instance_id=study.instance_id,
            style_driver_series_list=normalized_series_list,
        )

    def _matching_registry_studies_for_projected_payload(
        self,
        payload: Dict[str, Any],
    ) -> List[ChartStudyInstance]:
        """
        Return all chart-local studies that share one controller projection.

        Controller-owned projection keys identify computation truth, not chart-
        local style ownership. Multiple chart-local studies may legitimately
        share one projection when the user applies the same study config more
        than once. The panel must therefore preserve *all* matching chart-local
        studies instead of collapsing the refresh to one first-match entry.
        """
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        if not tool_key:
            return []

        family = self._normalize_study_family(str(payload.get("tool_type", "")))
        params = dict(payload.get("params", {}) or {})

        behavior = self._extract_behavior(payload)
        pane_target = self._pane_target_for_output_mode(str(behavior["output_mode"]))

        matches: List[ChartStudyInstance] = []
        for study in self._study_registry.list_all():
            if str(study.computation.tool_key).strip().lower() != tool_key:
                continue
            if self._normalize_study_family(str(study.computation.family)) != family:
                continue
            if dict(study.computation.params) != params:
                continue
            if study.pane_target != pane_target:
                continue
            matches.append(study)

        if len(matches) <= 1:
            return matches

        display_name = str(payload.get("display_name", payload.get("tool_title", ""))).strip()
        if display_name:
            exact_name_matches = [
                study
                for study in matches
                if str(study.display_name).strip() == display_name
            ]
            if exact_name_matches:
                return exact_name_matches

        return matches

    def _match_registry_study_for_projected_payload(
        self,
        payload: Dict[str, Any],
    ) -> Optional[ChartStudyInstance]:
        matches = self._matching_registry_studies_for_projected_payload(payload)
        return matches[0] if matches else None

    def _registry_studies_for_projected_payload(
        self,
        payload: Dict[str, Any],
    ) -> List[ChartStudyInstance]:
        projection_key = str(payload.get("study_projection_key", "")).strip()
        if projection_key:
            explicit_matches = [
                study
                for study in self._study_registry.list_all()
                if self._study_projection_key_by_instance_id.get(str(study.instance_id).strip())
                == projection_key
            ]
            if explicit_matches:
                return explicit_matches

        return self._matching_registry_studies_for_projected_payload(payload)

    def _build_workspace_projected_payloads_from_controller(self) -> List[Dict[str, Any]]:
        """
        Translate controller-owned projected payloads into workspace reapply
        payloads anchored to chart-local study instance ids.

        The workspace bridge must receive stable chart-local ids so managed pane
        ownership and overlay grouping remain coherent across resident-slice
        changes. Raw controller projection keys are not sufficient because the
        panel owns study lifecycle and style identity.
        """
        raw_payloads = list(self._controller.get_projected_study_payloads() or [])
        translated: List[Dict[str, Any]] = []

        for payload in raw_payloads:
            if not isinstance(payload, dict):
                continue

            studies = self._registry_studies_for_projected_payload(payload)
            if not studies:
                self._on_error(
                    "Projected study refresh skipped because no chart-local registry "
                    f"entry matched study_projection_key='{payload.get('study_projection_key', '')}' "
                    f"tool_key='{payload.get('tool_key', '')}' "
                    f"params={payload.get('params', {})}."
                )
                continue

            normalized_series_list: List[Series] = []
            for series in list(payload.get("series_list", []) or []):
                key = str(getattr(series, "key", "") or "").strip()
                if not key:
                    continue
                normalized_series_list.append(
                    Series(
                        key=key,
                        title=str(getattr(series, "title", "") or key),
                        values=_coerce_values_list(getattr(series, "values", None)),
                        style=getattr(series, "style", None),
                    )
                )

            normalized_style_driver_series_list: List[Series] = []
            for series in list(payload.get("style_driver_series_list", []) or []):
                key = str(getattr(series, "key", "") or "").strip()
                if not key:
                    continue
                normalized_style_driver_series_list.append(
                    Series(
                        key=key,
                        title=str(getattr(series, "title", "") or key),
                        values=_coerce_values_list(getattr(series, "values", None)),
                        style=getattr(series, "style", None),
                    )
                )

            for study in studies:
                translated_payload = dict(payload)
                translated_payload["study_instance_id"] = study.instance_id
                translated_payload["display_name"] = study.display_name

                chart_local_series_list = self._chart_local_series_list_for_study(
                    study_instance_id=study.instance_id,
                    series_list=normalized_series_list,
                )
                chart_local_style_driver_series_list = self._chart_local_style_driver_series_list_for_study(
                    study_instance_id=study.instance_id,
                    style_driver_series_list=normalized_style_driver_series_list,
                )
                resolved_series_list, resolved_fill_descriptors = self._resolved_render_state_for_study(
                    study=study,
                    series_list=chart_local_series_list,
                )
                updated_study = self._updated_study_with_resolved_render_keys(
                    study,
                    resolved_series_list,
                )
                if updated_study is not study:
                    # Projection refresh may expand or resync renderer-facing
                    # payload keys (e.g., historical segmented studies). The
                    # registry must track those chart-local render keys so
                    # later style edits can resolve the correct series.
                    self._study_registry.add(updated_study)
                study = updated_study
                translated_payload["series_list"] = resolved_series_list
                if resolved_fill_descriptors is not None:
                    translated_payload["fill_descriptors"] = resolved_fill_descriptors
                else:
                    translated_payload.pop("fill_descriptors", None)

                translated_payload["style_driver_series_list"] = chart_local_style_driver_series_list
                if updated_study.pane_target == PANE_TARGET_PRICE:
                    translated_payload["background_regions"] = self._build_background_regions_for_study(
                        study=updated_study,
                        style_driver_series_list=chart_local_style_driver_series_list,
                    )

                translated.append(translated_payload)

        return translated

    def _refresh_rendered_studies_from_controller_projection(self) -> None:
        """
        Reapply current controller-projected resident-local studies into the
        workspace from final chart-local render state.

        Refresh order
        -------------
        1. controller provides current resident-local study projections
        2. panel maps them onto chart-local study ids
        3. panel resolves final chart-local style/fill state once
        4. workspace reapplies that final resident-local render payload once
        5. panel restores pane-local oscillator policy and signal wiring

        This keeps historical slice refresh aligned with the ownership model:
        controller truth -> panel lifecycle/style -> workspace panes.
        """
        if not hasattr(self._workspace, "reapply_projected_studies"):
            return

        translated_payloads = self._build_workspace_projected_payloads_from_controller()

        try:
            # Always call the workspace bridge, even for an empty payload set.
            # Workspace is responsible for pruning managed rendered studies that
            # are no longer present after a resident-slice refresh.
            self._workspace.reapply_projected_studies(translated_payloads)
        except Exception as e:
            self._on_error(f"Projected study workspace reapply failed: {e!r}")
            return

        for payload in translated_payloads:
            study_instance_id = str(payload.get("study_instance_id", "")).strip()
            if not study_instance_id:
                continue

            study = self._study_registry.get(study_instance_id)
            if study is None or not study.is_renderable():
                continue

            if study.pane_target == PANE_TARGET_OSCILLATOR:
                self._connect_oscillator_pane_signals_for_study(study.instance_id)
                self._apply_oscillator_visual_policy_for_study(study)

        self._cleanup_oscillator_pane_signal_tracking()

