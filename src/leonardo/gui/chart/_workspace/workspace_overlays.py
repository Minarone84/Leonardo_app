from __future__ import annotations

from typing import Any, Dict, List, Optional

from leonardo.gui.chart.model import OverlayFill, Series
from leonardo.gui.chart.panes import ManagedOverlayRowProjection
from leonardo.gui.chart.panes.contracts import PaneBackgroundRegion
from leonardo.gui.chart.study_style_defaults import (
    apply_default_styles_to_series_list,
    build_default_overlay_fills,
)
from leonardo.gui.chart._workspace.workspace_state import OverlayStudyState


class WorkspaceOverlayMixin:
    def clear_overlays(self) -> None:
        for state in list(self._overlay_states_by_id.values()):
            for fill_id in state.fill_ids:
                self._model.remove_overlay_fill(fill_id)

        self._overlay_states_by_id.clear()
        self._overlay_render_key_to_study_id.clear()
        background_store = getattr(self, "_overlay_background_regions_by_id", None)
        if isinstance(background_store, dict):
            background_store.clear()

        overlays_view = (
            self._model.overlays_view()
            if hasattr(self._model, "overlays_view")
            else self._model.overlays()
        )
        for key in list(overlays_view.keys()):
            self._model.remove_overlay(key)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._push_price_overlay_projection()
        self._refresh_price_pane()

    def apply_overlay_series(self, series: Series) -> None:
        """
        Apply or replace a price overlay series in the chart model.
        """
        self._model.set_overlay(series)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._push_price_overlay_projection()
        self._refresh_price_pane()

    def apply_overlay_study(
        self,
        *,
        study_instance_id: str,
        title: str,
        series_list: List[Series],
        fill_descriptors: Optional[List[OverlayFill]] = None,
    ) -> None:
        """
        Apply or replace a managed overlay study.

        One study maps to one logical overlay study entry.
        A study may contain multiple overlay render series.

        `fill_descriptors` is optional:
        - None  -> use centralized default fill policy
        - list  -> use the provided fill descriptors as-is (normalized)

        Replacement rule:
        when a managed overlay study is reapplied, workspace must remove any old
        render keys and fill descriptors that no longer belong to that study.
        Otherwise stale overlay ownership would linger in the model and leak into
        the explicit price-render payload.
        """
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        normalized_series = [
            Series(
                key=str(series.key),
                title=str(series.title),
                values=series.values,
                style=series.style,
            )
            for series in series_list
        ]
        if not normalized_series:
            return

        study_key = self._study_key_from_series_list(normalized_series)
        normalized_series = apply_default_styles_to_series_list(
            study_key=study_key,
            series_list=normalized_series,
        )
        render_keys = [series.key for series in normalized_series]
        render_key_set = set(render_keys)

        existing_state = self._overlay_states_by_id.get(normalized_study_id)
        if existing_state is not None:
            for old_render_key in existing_state.render_keys:
                self._overlay_render_key_to_study_id.pop(old_render_key, None)
                if old_render_key not in render_key_set:
                    self._model.remove_overlay(old_render_key)
            for fill_id in existing_state.fill_ids:
                self._model.remove_overlay_fill(fill_id)

        for series in normalized_series:
            self._model.set_overlay(series)

        if fill_descriptors is None:
            resolved_fill_descriptors = build_default_overlay_fills(
                study_instance_id=normalized_study_id,
                study_key=study_key,
                series_list=normalized_series,
            )
        else:
            resolved_fill_descriptors = [
                OverlayFill(
                    fill_id=str(fill.fill_id).strip(),
                    series_a=str(fill.series_a).strip(),
                    series_b=str(fill.series_b).strip(),
                    color=fill.color,
                    opacity=float(fill.opacity),
                    visible=bool(fill.visible),
                )
                for fill in fill_descriptors
                if str(fill.fill_id).strip()
                and str(fill.series_a).strip()
                and str(fill.series_b).strip()
            ]

        fill_ids = [fill.fill_id for fill in resolved_fill_descriptors]

        self._overlay_states_by_id[normalized_study_id] = OverlayStudyState(
            study_instance_id=normalized_study_id,
            title=str(title).strip() or normalized_series[0].title,
            render_keys=list(render_keys),
            fill_ids=list(fill_ids),
        )

        for render_key in render_keys:
            self._overlay_render_key_to_study_id[render_key] = normalized_study_id

        for fill in resolved_fill_descriptors:
            self._model.set_overlay_fill(fill)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._push_price_overlay_projection()
        self._refresh_price_pane()

    def _overlay_background_region_store(self) -> Dict[str, List[PaneBackgroundRegion]]:
        store = getattr(self, "_overlay_background_regions_by_id", None)
        if not isinstance(store, dict):
            store = {}
            setattr(self, "_overlay_background_regions_by_id", store)
        return store

    def apply_overlay_background_regions(
        self,
        *,
        study_instance_id: str,
        background_regions: List[PaneBackgroundRegion],
    ) -> None:
        """Apply or clear explicit background-region payload for one overlay study.

        Workspace owns this payload as pane-contract state.  It is intentionally
        separate from overlay render series and overlay fills so background
        regions never influence autoscale and never become chart series.
        """
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        normalized_regions: List[PaneBackgroundRegion] = []
        for region in list(background_regions or []):
            region_id = str(getattr(region, "region_id", "") or "").strip()
            if not region_id:
                continue
            try:
                start_index = int(getattr(region, "start_index"))
                end_index = int(getattr(region, "end_index"))
            except Exception:
                continue
            if end_index < start_index:
                continue

            normalized_regions.append(
                PaneBackgroundRegion(
                    region_id=region_id,
                    start_index=start_index,
                    end_index=end_index,
                    color=getattr(region, "color", None),
                    opacity=float(getattr(region, "opacity", 0.08)),
                    visible=bool(getattr(region, "visible", True)),
                    source_signal=str(getattr(region, "source_signal", "") or ""),
                    label=str(getattr(region, "label", "") or ""),
                )
            )

        store = self._overlay_background_region_store()
        if normalized_regions:
            store[normalized_study_id] = normalized_regions
        else:
            store.pop(normalized_study_id, None)

        self._refresh_aux_pane_bindings()
        self._refresh_price_pane()

    def remove_overlay_series(self, key: str) -> None:
        """
        Remove a price overlay series from the chart model.

        This method supports both:
        - legacy series-level overlays
        - managed study-level overlays containing the series
        """
        study_instance_id = self._overlay_render_key_to_study_id.get(str(key).strip())
        if study_instance_id:
            self.remove_overlay_study(study_instance_id)
            return

        self._model.remove_overlay(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._push_price_overlay_projection()
        self._refresh_price_pane()

    def remove_overlay_study(self, study_instance_id: str) -> None:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        state = self._overlay_states_by_id.pop(normalized_study_id, None)
        if state is None:
            return

        self._overlay_background_region_store().pop(normalized_study_id, None)

        for fill_id in state.fill_ids:
            self._model.remove_overlay_fill(fill_id)

        for render_key in state.render_keys:
            self._overlay_render_key_to_study_id.pop(render_key, None)
            self._model.remove_overlay(render_key)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._push_price_overlay_projection()
        self._refresh_price_pane()

    def _study_key_from_series_list(self, series_list: List[Series]) -> str:
        if not series_list:
            return ""

        first_key = str(series_list[0].key).strip()
        if not first_key:
            return ""

        return first_key.split("|", 1)[0].strip().lower()

    def _refresh_studies_labels(self) -> None:
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(labels=True)
            return

        managed_overlay_titles = [
            state.title
            for state in self._overlay_states_by_id.values()
        ]

        unmanaged_overlay_titles = [
            series.title
            for key, series in (self._model.overlays_view() if hasattr(self._model, "overlays_view") else self._model.overlays()).items()
            if key not in self._overlay_render_key_to_study_id
        ]

        overlay_titles = managed_overlay_titles + unmanaged_overlay_titles
        oscillator_titles = [s.title for s in (self._model.oscillators_view() if hasattr(self._model, "oscillators_view") else self._model.oscillators()).values()]
        self._price.set_studies(overlay_titles, oscillator_titles)

    def _price_overlay_row_projection_payload(
        self,
    ) -> tuple[List[ManagedOverlayRowProjection], Dict[str, str]]:
        rows = [
            ManagedOverlayRowProjection(
                study_instance_id=state.study_instance_id,
                title=state.title,
                render_keys=list(state.render_keys),
            )
            for state in self._overlay_states_by_id.values()
        ]
        return rows, dict(self._overlay_render_key_to_study_id)

    def _push_price_overlay_projection(self) -> None:
        """
        Push explicit managed-overlay projection into the price pane.

        This keeps pane rendering driven by visualization-only projection data
        instead of private workspace-state introspection.
        """
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(contracts=True)
            return

        rows, render_key_to_study_id = self._price_overlay_row_projection_payload()
        self._price.set_managed_overlay_row_projection(
            rows,
            render_key_to_study_id=render_key_to_study_id,
        )

    def _price_overlay_series_payload(self) -> List[Series]:
        """Return the explicit overlay-series payload for the price renderer.

        This method returns a list because it is part of the pane/renderer contract.
        For hot-path iteration (autoscale), prefer `_iter_price_overlay_series()`.
        """
        overlays = self._model.overlays_view() if hasattr(self._model, "overlays_view") else self._model.overlays()
        try:
            return list(overlays.values())
        except Exception:
            return []

    def _price_overlay_fill_payload(self) -> List[OverlayFill]:
        """Return the explicit overlay-fill payload for the price renderer."""
        fills_view = (
            self._model.overlay_fills_view()
            if hasattr(self._model, "overlay_fills_view")
            else {fill.fill_id: fill for fill in self._model.overlay_fills()}
        )
        try:
            return list(fills_view.values())
        except Exception:
            return []

    def _price_overlay_background_regions_payload(self) -> List[PaneBackgroundRegion]:
        """Return explicit background-region payloads for active price overlays."""
        store = getattr(self, "_overlay_background_regions_by_id", None)
        if not isinstance(store, dict):
            return []

        active_ids = set(self._overlay_states_by_id.keys())
        regions: List[PaneBackgroundRegion] = []
        for study_instance_id, study_regions in list(store.items()):
            if study_instance_id not in active_ids:
                store.pop(study_instance_id, None)
                continue
            regions.extend(list(study_regions or []))
        return regions

    def _iter_price_overlay_series(self):
        """Yield overlay series without allocating a payload list.

        This exists for hot paths (autoscale, visible-range scans). Callers must
        treat the yielded series objects as read-only.
        """
        overlays_view = self._model.overlays_view() if hasattr(self._model, "overlays_view") else self._model.overlays()
        try:
            return overlays_view.values()
        except Exception:
            return []
