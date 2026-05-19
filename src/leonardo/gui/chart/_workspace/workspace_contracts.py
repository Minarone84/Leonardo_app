from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.panes import VolumePane


class WorkspaceContractMixin:
    def set_volume_enabled(self, enabled: bool) -> None:
        if enabled and self._volume is None:
            self._volume = VolumePane(
                viewport=self._viewport,
                crosshair=self._crosshair,
                candles=self._model.candles,
                volume=self._model.volume,
                parent=self,
            )
            self._splitter.addWidget(self._volume)
            self._refresh_aux_pane_bindings()
            self._apply_default_sizes(force=True)
        elif not enabled and self._volume is not None:
            self._capture_managed_pane_heights()
            self._remove_widget(self._volume)
            self._volume.deleteLater()
            self._volume = None
            self._apply_default_sizes(force=True)

    def clear_financial_tools(self) -> None:
        self.clear_overlays()
        self.clear_oscillators()

    def _apply_default_sizes(self, *, force: bool = False) -> None:
        if self._workspace_update_depth > 0:
            if force:
                self._defer_workspace_refresh(sizes=True)
            return

        widgets = self._current_splitter_widget_order()
        current_sizes = self._splitter.sizes()

        if not force and len(current_sizes) == len(widgets):
            all_positive = all(int(size) > 0 for size in current_sizes)
            if sum(current_sizes) > 0 and all_positive:
                return

        sizes = [800]
        if self._volume:
            sizes.append(200)

        for pane_id in self._oscillator_pane_order:
            state = self._oscillator_states_by_id.get(pane_id)
            sizes.append(state.preferred_height if state is not None else 220)

        if len(sizes) == 1:
            sizes = [1000]

        self._splitter.setSizes(sizes)

    def _remove_widget(self, w: QWidget) -> None:
        w.setParent(None)
        w.hide()

    def _resident_base_index(self) -> int:
        """Return the current resident-base index from the chart model."""
        if hasattr(self._model, "resident_base_index"):
            try:
                return int(self._model.resident_base_index)
            except Exception:
                return 0
        return 0

    def _on_viewport_changed(self) -> None:
        """Refresh viewport-dependent pane contracts after camera changes.

        Viewport owns horizontal camera state only. Whenever that camera changes,
        workspace must reconcile any visible-range-dependent pane contracts here
        instead of leaving renderers to rediscover vertical truth from their own
        local data.
        """
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(contracts=True)
            return

        self._sync_price_pane_contract()

        # Volume is an auxiliary pane but still depends on the shared viewport
        # camera for horizontal mapping. Workspace triggers a repaint here so
        # the volume surface does not subscribe directly to viewport signals.
        if self._volume is not None:
            try:
                self._volume.refresh_viewport()  # type: ignore[attr-defined]
            except Exception:
                try:
                    self._volume.update()
                except Exception:
                    pass

        self._push_all_managed_oscillator_view_states(
            resident_base_index=self._resident_base_index(),
        )

    def _refresh_price_pane(self) -> None:
        """Schedule a price-pane repaint from the final coherent workspace state."""
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(price=True)
            return

        self._price.update()

    def _refresh_aux_pane_bindings(self) -> None:
        """
        Keep auxiliary panes bound to the model's current series objects and
        resident base index.

        Workspace owns explicit rebinding of pane inputs after data/model
        changes. Oscillator panes are refreshed only through the managed pane
        contract path so pane ownership does not split across multiple update
        mechanisms.
        """
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(contracts=True)
            return

        resident_base_index = self._resident_base_index()

        self._sync_price_pane_contract()

        if self._volume is not None:
            self._sync_volume_pane_contract(resident_base_index)

        self._sync_all_managed_oscillator_pane_contracts(
            resident_base_index=resident_base_index,
        )

    def _sync_price_pane_contract(self) -> None:
        """Push the full workspace-owned price-pane contract to PricePane.

        Workspace owns both:
        - visualization-only overlay-row projection for the pane card UI
        - the explicit render contract consumed by the price renderer

        The render contract now includes the current resident OHLC slice,
        resident-base alignment, resolved price y-range, and explicit overlay
        series/fill payloads required by the renderer.
        """
        if self._workspace_update_depth > 0:
            self._defer_workspace_refresh(contracts=True)
            return

        lo, hi = self._resolved_price_y_range()
        self._price_state.view_state["y_lo"] = float(lo)
        self._price_state.view_state["y_hi"] = float(hi)

        rows, render_key_to_study_id = self._price_overlay_row_projection_payload()
        overlay_series_payload = self._price_overlay_series_payload()
        overlay_fill_payload = self._price_overlay_fill_payload()
        overlay_background_regions_payload = self._price_overlay_background_regions_payload()
        resident_base_index = self._resident_base_index()

        # PricePane must consume the full workspace-owned contract in one handoff.
        # Setter-cascade fallbacks are intentionally not supported in this build.
        self._price.apply_workspace_contract(
            candles=self._model.candles,
            resident_base_index=resident_base_index,
            view_state=self._price_state.view_state,
            rows=rows,
            render_key_to_study_id=render_key_to_study_id,
            overlay_series_payload=overlay_series_payload,
            overlay_fill_payload=overlay_fill_payload,
            overlay_background_regions_payload=overlay_background_regions_payload,
        )  # type: ignore[attr-defined]
        return

    def _sync_volume_pane_contract(self, resident_base_index: int) -> None:
        """Push the current volume-pane render inputs explicitly.

        VolumePane is a straightforward auxiliary consumer of chart-session x
        alignment and resident-local OHLC/volume data. Workspace owns the bind
        step and keeps that responsibility here instead of spreading it across
        callers.
        """
        if self._volume is None:
            return

        # VolumePane must consume the full workspace-owned contract in one handoff.
        self._volume.apply_contract(
            candles=self._model.candles,
            volume=self._model.volume,
            resident_base_index=resident_base_index,
        )  # type: ignore[attr-defined]
        return

    def _current_splitter_widget_order(self) -> List[QWidget]:
        widgets: List[QWidget] = []
        for index in range(self._splitter.count()):
            widget = self._splitter.widget(index)
            if widget is not None:
                widgets.append(widget)
        return widgets
