from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.model import Series, SeriesStyle
from leonardo.gui.chart.panes import OscillatorPane
from leonardo.gui.chart._workspace.workspace_state import OscillatorPaneState, OscillatorSpec


class WorkspaceOscillatorMixin:
    def add_oscillator(self, spec: OscillatorSpec) -> None:
        """
        Compatibility wrapper for older single-series oscillator calls.

        Final point-C rule in this workspace is that oscillator pane ownership
        flows through one managed pane registry only. This method therefore
        resolves the model series and forwards it into apply_oscillator_study()
        instead of creating a second pane-ownership track.
        """
        normalized_key = str(spec.key).strip()
        if not normalized_key:
            return

        series = self._model.oscillator(normalized_key)
        if series is None:
            return

        self.apply_oscillator_study(
            study_instance_id=normalized_key,
            title=str(spec.title).strip() or series.title,
            series_list=[series],
        )

    def remove_oscillator(self, key: str) -> None:
        """Compatibility wrapper for older single-series oscillator removal.

        Older callers may still address a pane by its single render key. Managed
        oscillator ownership now flows through the study/pane registry, so this
        method first removes the managed pane when present and falls back to
        removing the model series only when no pane ownership exists.
        """
        normalized_key = str(key).strip()
        if not normalized_key:
            return

        if normalized_key in self._study_to_pane_id:
            self.remove_oscillator_study(normalized_key)
            return

        self._model.remove_oscillator(normalized_key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()

    def clear_oscillators(self) -> None:
        """Remove all managed oscillator panes and oscillator render series."""
        self._capture_managed_pane_heights()

        for pane_id in list(self._oscillator_pane_order):
            pane = self._oscillator_panes_by_id.pop(pane_id, None)
            if pane is not None:
                self._remove_widget(pane)
                pane.deleteLater()

        self._oscillator_states_by_id.clear()
        self._oscillator_pane_order.clear()
        self._study_to_pane_id.clear()

        osc_view = (
            self._model.oscillators_view()
            if hasattr(self._model, "oscillators_view")
            else self._model.oscillators()
        )
        for key in list(osc_view.keys()):
            self._model.remove_oscillator(key)

        self._refresh_oscillator_pane_capabilities()
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._apply_default_sizes(force=True)

    def apply_oscillator_series(self, series: Series) -> None:
        """
        Compatibility wrapper for older single-series oscillator calls.

        Workspace keeps the public API surface, but routes the call into the
        managed oscillator-study path so pane ownership remains singular and
        explicit.
        """
        normalized_key = str(series.key).strip()
        if not normalized_key:
            return

        self.apply_oscillator_study(
            study_instance_id=normalized_key,
            title=str(series.title).strip() or normalized_key,
            series_list=[series],
        )

    def remove_oscillator_series(self, key: str) -> None:
        """
        Remove an oscillator series.

        This method supports both:
        - legacy series-level panes
        - managed study-level panes containing the series
        """
        normalized_key = str(key).strip()
        pane_id = self._pane_id_for_render_key(normalized_key)
        if pane_id:
            state = self._oscillator_states_by_id.get(pane_id)
            if state is not None:
                self.remove_oscillator_study(state.study_instance_id)
        else:
            self.remove_oscillator(normalized_key)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()

    def apply_oscillator_study(
        self,
        *,
        study_instance_id: str,
        title: str,
        series_list: List[Series],
    ) -> None:
        """
        Apply or replace a managed oscillator study.

        One study maps to one pane in this phase.
        A study may contain multiple render series.

        Compatibility note:
        legacy single-series oscillator entry points now route into this same
        managed-pane path so workspace owns oscillator panes through one
        registry only.
        """
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        # Normalize inputs defensively, but avoid rebuilding Series wrappers
        # on the hot path. Series is a frozen dataclass and is treated as an
        # immutable transport container by contract in the GUI layer.
        normalized_series: List[Series] = []
        for series in series_list:
            if (
                isinstance(series, Series)
                and hasattr(series.values, "__len__")
                and hasattr(series.values, "__getitem__")
            ):
                normalized_series.append(series)
                continue

            key = str(getattr(series, "key", "") or "").strip()
            title = str(getattr(series, "title", "") or "").strip() or key
            raw_values = getattr(series, "values", None)
            if raw_values is None:
                values = []
            elif hasattr(raw_values, "__len__") and hasattr(raw_values, "__getitem__"):
                values = raw_values
            else:
                try:
                    values = list(raw_values)
                except Exception:
                    values = []
            raw_style = getattr(series, "style", None)
            style = raw_style if isinstance(raw_style, SeriesStyle) else SeriesStyle()

            if not key:
                continue

            normalized_series.append(
                Series(
                    key=key,
                    title=title,
                    values=values,
                    style=style,
                )
            )

        if not normalized_series:
            return

        render_keys = [series.key for series in normalized_series]
        render_key_set = set(render_keys)

        pane_id = self._study_to_pane_id.get(normalized_study_id)
        if pane_id is None:
            pane_id = normalized_study_id
            self._study_to_pane_id[normalized_study_id] = pane_id

        state = self._oscillator_states_by_id.get(pane_id)
        if state is not None:
            for old_render_key in state.render_keys:
                if old_render_key not in render_key_set:
                    self._model.remove_oscillator(old_render_key)

        for series in normalized_series:
            self._model.set_oscillator(series)

        if state is None:
            state = OscillatorPaneState(
                pane_id=pane_id,
                study_instance_id=normalized_study_id,
                title=str(title).strip() or normalized_series[0].title,
                render_keys=list(render_keys),
            )
            self._oscillator_states_by_id[pane_id] = state
        else:
            state.title = str(title).strip() or normalized_series[0].title
            state.render_keys = list(render_keys)
            state.study_instance_id = normalized_study_id

        if pane_id not in self._oscillator_pane_order:
            self._oscillator_pane_order.append(pane_id)

        pane = self._oscillator_panes_by_id.get(pane_id)
        if pane is None:
            pane = OscillatorPane(
                title=state.title,
                viewport=self._viewport,
                crosshair=self._crosshair,
                study_instance_id=normalized_study_id,
                series_list=normalized_series,
                visual_policy=state.visual_policy,
                view_state=state.view_state,
                parent=self,
            )
            self._oscillator_panes_by_id[pane_id] = pane
            self._splitter.addWidget(pane)

        self._refresh_oscillator_pane_capabilities()
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._apply_default_sizes(force=True)

    def remove_oscillator_study(self, study_instance_id: str) -> None:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        pane_id = self._study_to_pane_id.pop(normalized_study_id, None)
        if pane_id is None:
            return

        self._capture_managed_pane_heights()

        state = self._oscillator_states_by_id.pop(pane_id, None)
        pane = self._oscillator_panes_by_id.pop(pane_id, None)

        if state is not None:
            for render_key in state.render_keys:
                self._model.remove_oscillator(render_key)

        if pane_id in self._oscillator_pane_order:
            self._oscillator_pane_order.remove(pane_id)

        if pane is not None:
            self._remove_widget(pane)
            pane.deleteLater()

        self._refresh_oscillator_pane_capabilities()
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._apply_default_sizes(force=True)

    def move_oscillator_pane_up(self, study_instance_id: str) -> bool:
        return self._move_oscillator_pane(study_instance_id, direction=-1)

    def move_oscillator_pane_down(self, study_instance_id: str) -> bool:
        return self._move_oscillator_pane(study_instance_id, direction=1)

    def oscillator_pane_for_study(self, study_instance_id: str) -> Optional[OscillatorPane]:
        pane_id = self._study_to_pane_id.get(str(study_instance_id).strip())
        if pane_id is None:
            return None
        return self._oscillator_panes_by_id.get(pane_id)

    def set_oscillator_pane_visual_policy(
        self,
        *,
        study_instance_id: str,
        policy: Optional[Dict[str, Any]],
    ) -> None:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        pane_id = self._study_to_pane_id.get(normalized_study_id)
        if pane_id is None:
            return

        state = self._oscillator_states_by_id.get(pane_id)
        if state is None:
            return

        normalized_policy = dict(policy or {})
        state.visual_policy = normalized_policy

        pane = self._oscillator_panes_by_id.get(pane_id)
        if pane is not None:
            self._sync_managed_oscillator_pane_contract(
                pane=pane,
                state=state,
                resident_base_index=self._resident_base_index(),
            )

    def set_oscillator_pane_view_state(
        self,
        *,
        study_instance_id: str,
        view_state: Optional[Dict[str, Any]],
    ) -> None:
        """Persist pane-owned view state for one managed oscillator pane.

        This method preserves the canonical workspace-owned mapping object for
        the managed oscillator pane. Renderer-side gesture write-back must land
        in that same mapping, so workspace updates mutate the existing dict in
        place instead of rebinding it to a new owner.
        """
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        pane_id = self._study_to_pane_id.get(normalized_study_id)
        if pane_id is None:
            return

        state = self._oscillator_states_by_id.get(pane_id)
        if state is None:
            return

        self._replace_mapping_contents(state.view_state, view_state)

        pane = self._oscillator_panes_by_id.get(pane_id)
        if pane is not None:
            self._sync_managed_oscillator_pane_contract(
                pane=pane,
                state=state,
                resident_base_index=self._resident_base_index(),
            )

    def oscillator_pane_view_state(self, *, study_instance_id: str) -> Dict[str, Any]:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return {}

        pane_id = self._study_to_pane_id.get(normalized_study_id)
        if pane_id is None:
            return {}

        state = self._oscillator_states_by_id.get(pane_id)
        if state is None:
            return {}

        return dict(state.view_state)

    def _series_is_visible(self, series: Series) -> bool:
        """Return whether one oscillator render series currently participates visually."""
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return True
        try:
            return bool(getattr(style_obj, "visible", True))
        except Exception:
            return True

    def _oscillator_policy_bounds(
        self,
        visual_policy: Mapping[str, Any],
    ) -> Optional[tuple[float, float]]:
        """Return explicit oscillator bounds from pane visual policy when valid.

        Workspace owns oscillator pane contract generation. When the pane policy
        declares fixed bounds, workspace must resolve that vertical contract
        here instead of leaving the renderer to reinterpret policy semantics.
        """
        range_mode = str(visual_policy.get("range_mode", "") or "").strip().lower()
        if range_mode not in {"fixed", "fixed_bounds"}:
            return None

        raw_bounds = visual_policy.get("bounds")
        if not isinstance(raw_bounds, (list, tuple)) or len(raw_bounds) != 2:
            return None

        try:
            lo = float(raw_bounds[0])
            hi = float(raw_bounds[1])
        except Exception:
            return None

        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            return None
        return (lo, hi)

    def _oscillator_policy_reference_values(
        self,
        visual_policy: Mapping[str, Any],
    ) -> List[float]:
        """Return finite policy-derived values relevant to oscillator scaling.

        Policy guide levels and threshold boundaries are pane-interpretation
        inputs. When workspace auto-resolves oscillator y-range, those values
        must be included here so pane-local guides remain visible without
        moving range ownership back into the renderer.
        """
        values: List[float] = []

        raw_levels = visual_policy.get("levels", []) or []
        if isinstance(raw_levels, list):
            for level in raw_levels:
                if not isinstance(level, Mapping):
                    continue
                if not bool(level.get("visible", True)):
                    continue
                try:
                    numeric = float(level.get("value"))
                except Exception:
                    continue
                if math.isfinite(numeric):
                    values.append(numeric)

        threshold_policy = visual_policy.get("threshold_line_color")
        if isinstance(threshold_policy, Mapping):
            for key in ("lower_value", "upper_value", "neutral_value"):
                try:
                    numeric = float(threshold_policy.get(key))
                except Exception:
                    continue
                if math.isfinite(numeric):
                    values.append(numeric)

        return values

    def _resolved_oscillator_y_range(
        self,
        *,
        state: OscillatorPaneState,
        resident_base_index: int,
    ) -> tuple[float, float]:
        """Resolve the explicit workspace-owned y-range for one oscillator pane.

        Ownership rule:
        - workspace owns durable vertical contract truth
        - panes hand that explicit contract into renderers
        - renderers execute against the supplied contract only

        Resolution order:
        1. fixed bounds declared by pane visual policy
        2. auto-fit finite visible oscillator values + policy reference values
        3. auto-fit finite resident oscillator values + policy reference values
        4. fallback default range
        """
        fixed_bounds = self._oscillator_policy_bounds(state.visual_policy)
        if fixed_bounds is not None:
            return fixed_bounds

        start = int(getattr(self._viewport, "start", 0))
        end = int(getattr(self._viewport, "end", 0))
        policy_values = self._oscillator_policy_reference_values(state.visual_policy)

        # ------------------------------------------------------------------
        # Resolved y-range cache
        #
        # Multi-chart scenarios amplify any O(N) scans. Viewport camera motion
        # often produces the same resolved y-range for an oscillator pane, so
        # cache the last resolution keyed by:
        # - viewport window
        # - resident alignment
        # - pane visual policy
        # - series identity (values-list identity + visibility)
        # ------------------------------------------------------------------

        def _policy_cache_key(policy: Mapping[str, Any]) -> tuple[Any, ...]:
            if not policy:
                return ()
            items: List[tuple[str, Any]] = []
            for k in sorted(policy.keys()):
                v = policy.get(k)
                if isinstance(v, (int, float, str, bool)) or v is None:
                    items.append((k, v))
                elif isinstance(v, (list, tuple)):
                    items.append((k, tuple(v)))
                elif isinstance(v, dict):
                    try:
                        items.append((k, tuple(sorted(v.items()))))
                    except Exception:
                        items.append((k, repr(v)))
                else:
                    items.append((k, repr(v)))
            return tuple(items)

        # ------------------------------------------------------------------
        # Cache-key robustness note:
        #
        # The intended contract is that series.values are immutable buffers
        # replaced by reference on updates. The cache key therefore includes
        # values identity. As a guardrail, include a cheap fingerprint so an
        # accidental in-place mutation does not leave the cache stale.
        # ------------------------------------------------------------------

        def _fp_token(raw: object) -> object:
            try:
                v = float(raw)
            except Exception:
                return "nan"
            if math.isnan(v):
                return "nan"
            if math.isinf(v):
                return "inf" if v > 0 else "-inf"
            return v

        def _values_fingerprint(values: Sequence[object]) -> tuple[object, ...]:
            try:
                nvals = len(values)
            except Exception:
                return ()
            if nvals <= 0:
                return ()
            idxs = {0, nvals - 1, nvals // 2}
            if nvals >= 4:
                idxs.add(nvals // 4)
                idxs.add((3 * nvals) // 4)
            try:
                return tuple(_fp_token(values[i]) for i in sorted(idxs))
            except Exception:
                return ()

        series_key_parts: List[tuple[Any, ...]] = []
        for series in self._managed_oscillator_series_for_state(state):
            if not self._series_is_visible(series):
                continue
            values = getattr(series, "values", None)
            if values is None:
                continue
            try:
                nvals = len(values)
            except Exception:
                continue
            if nvals <= 0:
                continue
            series_key_parts.append(
                (
                    str(getattr(series, "key", "")),
                    int(nvals),
                    int(id(values)),
                    _values_fingerprint(values),
                )
            )

        cache_key: tuple[Any, ...] = (
            int(start),
            int(end),
            int(resident_base_index),
            _policy_cache_key(state.visual_policy),
            tuple(series_key_parts),
        )

        cached_range = getattr(state, "_y_range_cache_value", None)
        if getattr(state, "_y_range_cache_key", None) == cache_key and isinstance(cached_range, tuple):
            try:
                lo_c, hi_c = float(cached_range[0]), float(cached_range[1])
                return (lo_c, hi_c)
            except Exception:
                pass

        def _store_cache(result: tuple[float, float]) -> tuple[float, float]:
            try:
                state._y_range_cache_key = cache_key
                state._y_range_cache_value = (float(result[0]), float(result[1]))
            except Exception:
                pass
            return (float(result[0]), float(result[1]))

        def apply_policy(lo: Optional[float], hi: Optional[float]) -> tuple[Optional[float], Optional[float]]:
            r_lo = lo
            r_hi = hi
            for v in policy_values:
                if not math.isfinite(v):
                    continue
                if r_lo is None or v < r_lo:
                    r_lo = v
                if r_hi is None or v > r_hi:
                    r_hi = v
            return r_lo, r_hi

        def normalize(lo: Optional[float], hi: Optional[float]) -> Optional[tuple[float, float]]:
            if lo is None or hi is None:
                return None
            if not math.isfinite(lo) or not math.isfinite(hi):
                return None
            if hi <= lo:
                return (float(lo), float(lo) + 1.0)
            return (float(lo), float(hi))

        visible_lo: Optional[float] = None
        visible_hi: Optional[float] = None
        resident_lo: Optional[float] = None
        resident_hi: Optional[float] = None

        for series in self._managed_oscillator_series_for_state(state):
            if not self._series_is_visible(series):
                continue

            values = getattr(series, "values", None)
            if not isinstance(values, list) or not values:
                continue

            # Prefer visible-window extrema.
            local_start = start - resident_base_index
            local_end = end - resident_base_index
            if local_end > 0 and local_start < len(values):
                lo_i = max(0, local_start)
                hi_i = min(len(values), local_end)
                for i in range(lo_i, hi_i):
                    try:
                        numeric = float(values[i])
                    except Exception:
                        continue
                    if not math.isfinite(numeric):
                        continue
                    if visible_lo is None or numeric < visible_lo:
                        visible_lo = numeric
                    if visible_hi is None or numeric > visible_hi:
                        visible_hi = numeric

            # Only fall back to resident scan when nothing visible exists yet.
            if visible_lo is not None and visible_hi is not None:
                continue

            for raw in values:
                try:
                    numeric = float(raw)
                except Exception:
                    continue
                if not math.isfinite(numeric):
                    continue
                if resident_lo is None or numeric < resident_lo:
                    resident_lo = numeric
                if resident_hi is None or numeric > resident_hi:
                    resident_hi = numeric

        visible_lo, visible_hi = apply_policy(visible_lo, visible_hi)
        resolved = normalize(visible_lo, visible_hi)
        if resolved is not None:
            return _store_cache(resolved)

        resident_lo, resident_hi = apply_policy(resident_lo, resident_hi)
        resolved = normalize(resident_lo, resident_hi)
        if resolved is not None:
            return _store_cache(resolved)

        # If we have only policy values, those might have populated lo/hi above.
        # Otherwise, return a neutral default range.
        return _store_cache((0.0, 1.0))

    def _push_all_managed_oscillator_view_states(
        self,
        *,
        resident_base_index: Optional[int] = None,
    ) -> None:
        """Refresh only the viewport-dependent y-range contract for oscillator panes.

        Viewport movement changes what portion of each resident-local oscillator
        series is visible, which can change the resolved y-range. The pane's
        series membership, policy, and resident alignment do not change here, so
        workspace updates only the shared view-state mapping instead of replaying
        the full pane contract.
        """
        resolved_base_index = (
            self._resident_base_index()
            if resident_base_index is None
            else int(resident_base_index)
        )

        for pane_id in self._oscillator_pane_order:
            pane = self._oscillator_panes_by_id.get(pane_id)
            state = self._oscillator_states_by_id.get(pane_id)
            if pane is None or state is None:
                continue

            lo, hi = self._resolved_oscillator_y_range(
                state=state,
                resident_base_index=resolved_base_index,
            )
            state.view_state["y_lo"] = float(lo)
            state.view_state["y_hi"] = float(hi)
            pane.apply_view_state_contract(state.view_state)

    def _sync_all_managed_oscillator_pane_contracts(
        self,
        *,
        resident_base_index: Optional[int] = None,
    ) -> None:
        """Push explicit contract state into every managed oscillator pane.

        Workspace owns this fan-out step so viewport-dependent y-range
        resolution, pane policy, pane state, and resident alignment all stay in
        one ownership layer.
        """
        resolved_base_index = (
            self._resident_base_index()
            if resident_base_index is None
            else int(resident_base_index)
        )

        for pane_id in self._oscillator_pane_order:
            pane = self._oscillator_panes_by_id.get(pane_id)
            state = self._oscillator_states_by_id.get(pane_id)
            if pane is None or state is None:
                continue
            self._sync_managed_oscillator_pane_contract(
                pane=pane,
                state=state,
                resident_base_index=resolved_base_index,
            )

    def _managed_oscillator_series_for_state(self, state: OscillatorPaneState) -> List[Series]:
        """Resolve the current model-backed series list for one managed pane."""
        series_list: List[Series] = []
        for render_key in state.render_keys:
            series = self._model.oscillator(render_key)
            if series is not None:
                series_list.append(series)
        return series_list

    def _sync_managed_oscillator_pane_contract(
        self,
        *,
        pane: OscillatorPane,
        state: OscillatorPaneState,
        resident_base_index: int,
    ) -> None:
        """Push explicit workspace-owned pane state into one managed oscillator pane.

        Managed oscillator panes should not infer responsibility from the model,
        workspace order, or renderer internals. Workspace owns the pane's study
        identity, title, series projection, visual policy, view state, resolved
        y-range contract, and resident alignment, and pushes those inputs
        through this single contract method.
        """
        series_list = self._managed_oscillator_series_for_state(state)
        lo, hi = self._resolved_oscillator_y_range(
            state=state,
            resident_base_index=resident_base_index,
        )
        state.view_state["y_lo"] = float(lo)
        state.view_state["y_hi"] = float(hi)

        # OscillatorPane must consume the full workspace-owned contract in one handoff.
        pane.apply_workspace_contract(
            study_instance_id=state.study_instance_id,
            title=state.title,
            series_list=series_list,
            visual_policy=state.visual_policy,
            view_state=state.view_state,
            resident_base_index=resident_base_index,
        )  # type: ignore[attr-defined]
        return

    def _pane_id_for_render_key(self, render_key: str) -> Optional[str]:
        normalized_key = str(render_key).strip()
        if not normalized_key:
            return None

        for pane_id, state in self._oscillator_states_by_id.items():
            if normalized_key in state.render_keys:
                return pane_id
        return None

    def _capture_managed_pane_heights(self) -> None:
        widgets = self._current_splitter_widget_order()
        sizes = self._splitter.sizes()

        if len(widgets) != len(sizes):
            return

        for widget, size in zip(widgets, sizes, strict=True):
            for pane_id, pane in self._oscillator_panes_by_id.items():
                if pane is widget:
                    state = self._oscillator_states_by_id.get(pane_id)
                    if state is not None:
                        state.preferred_height = max(120, int(size))
                    break

    def _move_oscillator_pane(self, study_instance_id: str, direction: int) -> bool:
        pane_id = self._study_to_pane_id.get(str(study_instance_id).strip())
        if pane_id is None:
            return False

        try:
            index = self._oscillator_pane_order.index(pane_id)
        except ValueError:
            return False

        new_index = index + int(direction)
        if new_index < 0 or new_index >= len(self._oscillator_pane_order):
            return False

        self._capture_managed_pane_heights()

        self._oscillator_pane_order[index], self._oscillator_pane_order[new_index] = (
            self._oscillator_pane_order[new_index],
            self._oscillator_pane_order[index],
        )

        self._rebuild_splitter_layout()
        self._refresh_oscillator_pane_capabilities()
        return True

    def _rebuild_splitter_layout(self) -> None:
        current_widgets = self._current_splitter_widget_order()
        current_sizes = self._splitter.sizes()
        widget_sizes: Dict[QWidget, int] = {}

        if len(current_widgets) == len(current_sizes):
            for widget, size in zip(current_widgets, current_sizes, strict=True):
                widget_sizes[widget] = int(size)

        widgets: List[QWidget] = [self._price]
        self._push_price_render_payload()

        if self._volume is not None:
            widgets.append(self._volume)

        for pane_id in self._oscillator_pane_order:
            pane = self._oscillator_panes_by_id.get(pane_id)
            if pane is not None:
                widgets.append(pane)

        for index, widget in enumerate(widgets):
            self._splitter.insertWidget(index, widget)

        sizes: List[int] = []
        for widget in widgets:
            size = widget_sizes.get(widget)
            if size is not None and size > 0:
                sizes.append(size)
                continue

            if widget is self._price:
                sizes.append(800)
            elif widget is self._volume:
                sizes.append(200)
            else:
                pane_id_for_widget = None
                for pane_id, pane in self._oscillator_panes_by_id.items():
                    if pane is widget:
                        pane_id_for_widget = pane_id
                        break

                if pane_id_for_widget is not None:
                    state = self._oscillator_states_by_id.get(pane_id_for_widget)
                    sizes.append(state.preferred_height if state is not None else 220)
                else:
                    sizes.append(220)

        if sizes:
            self._splitter.setSizes(sizes)

    def _refresh_oscillator_pane_capabilities(self) -> None:
        total = len(self._oscillator_pane_order)
        for index, pane_id in enumerate(self._oscillator_pane_order):
            pane = self._oscillator_panes_by_id.get(pane_id)
            if pane is None:
                continue
            pane.set_move_capabilities(
                can_move_up=index > 0,
                can_move_down=index < (total - 1),
            )