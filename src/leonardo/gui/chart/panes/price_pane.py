from __future__ import annotations

from typing import Any, List, Mapping, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from leonardo.common.market_types import Candle
from leonardo.gui.chart.chart_render import ChartRenderSurface
from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.model import ChartModel, Series
from leonardo.gui.chart.overlay_display_policy import (
    OverlayStudyDisplayPolicy,
    build_overlay_study_display_policy,
    compact_signal_label,
    line_key_from_render_key,
)
from leonardo.gui.chart.viewport import ChartViewport

from .contracts import ManagedOverlayRowProjection, _shared_mutable_view_state
from .header_widgets import _HeaderInfoBlock, _PaneOverlay
from .overlay_rows import _StudyRow

class PricePane(QWidget):
    """
    Price pane.

    Final-contract intent for point C:
    - OHLC from the chart model is the canonical price truth
    - workspace owns durable price-pane view state and the pane acts as the
      explicit handoff boundary for that shared mapping plus visualization
      projection
    - the pane exposes explicit managed overlay-row projection for overlay-card
      rendering
    - the renderer is a drawing surface and must not be asked to discover pane
      grouping/registry state indirectly
    - managed study-row grouping must therefore arrive here explicitly and must
      not be inferred from hidden workspace/private state
    """

    study_style_requested = Signal(str)
    study_edit_requested = Signal(str)
    study_remove_requested = Signal(str)

    def __init__(
        self,
        viewport: ChartViewport,
        model: ChartModel,
        crosshair: Crosshair,
        *,
        view_state: Optional[Mapping[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._viewport = viewport
        self._model = model
        self._crosshair = crosshair

        self._managed_overlay_rows: List[ManagedOverlayRowProjection] = []
        self._managed_overlay_render_key_to_study_id: dict[str, str] = {}
        self._view_state: dict[str, Any] = _shared_mutable_view_state(view_state)
        self._overlay_series_payload: List[object] = []
        self._overlay_fill_payload: List[object] = []
        self._overlay_background_regions_payload: List[object] = []

        # Overlay card efficiency: cache render-key -> series mapping and avoid
        # rebuilding overlay-row text when the crosshair stays on the same bar.
        self._overlay_series_by_key: dict[str, Series] = {}
        self._overlay_series_payload_version: int = 0
        self._last_overlay_local_idx: Optional[int] = None
        self._last_overlay_candle_sig: Optional[tuple[float, float, float, float]] = None
        self._last_overlay_payload_version: int = -1

        self._surface = ChartRenderSurface(
            viewport=self._viewport,
            crosshair=self._crosshair,
            candles=self._base_price_bars(),
            parent=self,
        )

        self._overlay = _PaneOverlay(self)
        self._header = _HeaderInfoBlock(self._overlay)
        self._overlay.layout_box.addWidget(self._header)

        self._study_rows_host = QWidget(self._overlay)
        self._study_rows_layout = QVBoxLayout(self._study_rows_host)
        self._study_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._study_rows_layout.setSpacing(2)
        self._overlay.layout_box.addWidget(self._study_rows_host)

        self._study_rows: dict[str, _StudyRow] = {}
        self._asset_label_text = "ASSET · TF"
        self._last_header_line1 = ""
        self._last_row_texts: dict[str, str] = {}
        self._overlay_values_expanded_by_row_key: dict[str, bool] = {}
        self._overlay_layout_dirty = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._header.set_title(self._asset_label_text)
        self._header.set_line1("")

        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        # Workspace owns pane contract refresh. PricePane therefore does not
        # subscribe directly to model.changed; it consumes explicit workspace
        # push updates instead of acting like a second refresh coordinator.
        self._sync_surface_from_model()
        self._update_overlay()

    def apply_view_state_contract(self, view_state: Optional[Mapping[str, Any]]) -> None:
        """Apply workspace-owned view state without redefining other payloads.

        This is a narrow contract update used for viewport-driven autoscale/manual-y
        reconciliation. It preserves the shared mutable mapping so renderer gesture
        write-back lands in the same workspace-owned state object.
        """
        self._view_state = _shared_mutable_view_state(view_state)
        # Push the updated view-state through the canonical surface contract path.
        self._sync_surface_from_model()

    def view_state_snapshot(self) -> dict[str, Any]:
        return dict(self._view_state)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_overlay_geometry(force=True)

    def _refresh_overlay_geometry(self, *, force: bool = False) -> None:
        if force or self._overlay_layout_dirty:
            self._overlay.anchor_top_left()
            self._overlay_layout_dirty = False

    def set_asset_label(self, text: str) -> None:
        resolved = str(text).strip()
        if resolved == self._asset_label_text:
            return
        self._asset_label_text = resolved
        self._header.set_title(self._asset_label_text)
        self._overlay_layout_dirty = True
        self._refresh_overlay_geometry(force=True)

    def apply_workspace_contract(
        self,
        *,
        candles: List[Candle],
        resident_base_index: int,
        view_state: Optional[Mapping[str, Any]],
        rows: List[ManagedOverlayRowProjection],
        render_key_to_study_id: Optional[Mapping[str, str]],
        overlay_series_payload: Optional[List[object]],
        overlay_fill_payload: Optional[List[object]],
        overlay_background_regions_payload: Optional[List[object]] = None,
    ) -> None:
        """Apply the full workspace-owned price-pane contract in one handoff.

        Workspace owns when the canonical price-pane contract changes. The pane
        accepts the complete contract here, forwards the render-facing state to
        the surface, and refreshes its overlay card once from the final coherent
        state instead of reacting piecemeal to many intermediate updates.
        """
        self._view_state = _shared_mutable_view_state(view_state)
        self._managed_overlay_rows = [
            ManagedOverlayRowProjection(
                study_instance_id=str(row.study_instance_id).strip(),
                title=str(row.title).strip(),
                render_keys=[str(key).strip() for key in row.render_keys if str(key).strip()],
            )
            for row in rows
            if str(row.study_instance_id).strip()
        ]
        self._managed_overlay_render_key_to_study_id = {
            str(key).strip(): str(value).strip()
            for key, value in dict(render_key_to_study_id or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self._overlay_series_payload = overlay_series_payload if isinstance(overlay_series_payload, list) else list(overlay_series_payload or [])
        self._rebuild_overlay_series_cache()
        # Contract changes should always refresh the overlay card.
        self._last_overlay_local_idx = None
        self._last_overlay_candle_sig = None
        self._last_overlay_payload_version = -1
        self._overlay_fill_payload = overlay_fill_payload if isinstance(overlay_fill_payload, list) else list(overlay_fill_payload or [])
        self._overlay_background_regions_payload = (
            overlay_background_regions_payload
            if isinstance(overlay_background_regions_payload, list)
            else list(overlay_background_regions_payload or [])
        )
        self._overlay_layout_dirty = True

        if hasattr(self._surface, "apply_contract"):
            self._surface.apply_contract(
                candles=candles,
                resident_base_index=resident_base_index,
                view_state=self._view_state,
                overlay_series_payload=self._overlay_series_payload,
                overlay_fill_payload=self._overlay_fill_payload,
                overlay_background_regions_payload=self._overlay_background_regions_payload,
            )  # type: ignore[attr-defined]
        else:
            self._sync_surface_from_model()

        self._update_overlay()

    # kept for compatibility
    def set_studies(self, indicators: List[str], oscillators: List[str]) -> None:
        self._update_overlay()

    def set_managed_overlay_row_projection(
        self,
        rows: List[ManagedOverlayRowProjection],
        *,
        render_key_to_study_id: Optional[Mapping[str, str]] = None,
    ) -> None:
        """
        Set explicit managed overlay row projection for the price pane.

        This is visualization-only state. It allows the pane to render grouped
        overlay-study rows without peeking into workspace internals.
        """
        self._managed_overlay_rows = [
            ManagedOverlayRowProjection(
                study_instance_id=str(row.study_instance_id).strip(),
                title=str(row.title).strip(),
                render_keys=[str(key).strip() for key in row.render_keys if str(key).strip()],
            )
            for row in rows
            if str(row.study_instance_id).strip()
        ]
        self._managed_overlay_render_key_to_study_id = {
            str(key).strip(): str(value).strip()
            for key, value in dict(render_key_to_study_id or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self._overlay_layout_dirty = True
        self._update_overlay()

    def clear_managed_overlay_row_projection(self) -> None:
        self._managed_overlay_rows = []
        self._managed_overlay_render_key_to_study_id.clear()
        self._overlay_layout_dirty = True
        self._update_overlay()


    def _rebuild_overlay_series_cache(self) -> None:
        """Rebuild render-key -> series mapping for overlay card use.

        The price surface consumes the list payload directly. The overlay card
        needs fast lookup by render key for per-bar value display.
        """
        overlay_series_by_key: dict[str, Series] = {}
        for series in self._overlay_series_payload:
            key = str(getattr(series, "key", "") or "").strip()
            if key:
                overlay_series_by_key[key] = series  # renderer-facing payload truth
        self._overlay_series_by_key = overlay_series_by_key
        self._overlay_series_payload_version += 1

    def _base_price_bars(self) -> List[Candle]:
        if hasattr(self._model, "base_price_bars"):
            try:
                return self._model.base_price_bars
            except Exception:
                pass
        return self._model.candles

    def _sync_surface_from_model(self) -> None:
        candles = self._base_price_bars()
        resident_base_index = getattr(self._model, "resident_base_index", 0)

        # Contract-first handoff. ChartRenderSurface is the canonical price surface
        # and must consume one coherent contract rather than a setter cascade.
        self._surface.apply_contract(
            candles=candles,
            resident_base_index=resident_base_index,
            view_state=self._view_state,
            overlay_series_payload=self._overlay_series_payload,
            overlay_fill_payload=self._overlay_fill_payload,
            overlay_background_regions_payload=self._overlay_background_regions_payload,
        )

    def _global_to_local(self, global_index: int) -> Optional[int]:
        if hasattr(self._model, "global_to_local"):
            try:
                return self._model.global_to_local(global_index)
            except Exception:
                return None
        if 0 <= global_index < len(self._base_price_bars()):
            return global_index
        return None

    def _overlay_index_local(self) -> Optional[int]:
        candles: List[Candle] = self._base_price_bars()
        if not candles:
            return None

        idx = self._crosshair.index
        local = self._global_to_local(idx) if idx is not None else None
        if local is None:
            local = len(candles) - 1
        return local

    def _ensure_study_row(
        self,
        row_key: str,
        *,
        action_id: Optional[str] = None,
        values_allowed: bool = True,
        values_expanded: bool = False,
    ) -> _StudyRow:
        row = self._study_rows.get(row_key)
        if row is None:
            row = _StudyRow(row_key, parent=self._study_rows_host)
            row.style_requested.connect(self.study_style_requested)
            row.edit_requested.connect(self.study_edit_requested)
            row.remove_requested.connect(self.study_remove_requested)
            row.value_toggled.connect(self._on_overlay_row_value_toggled)
            self._study_rows_layout.addWidget(row)
            self._study_rows[row_key] = row
            self._overlay_layout_dirty = True

        row.set_action_id(action_id or row_key)
        row.set_values_allowed(values_allowed)
        row.set_values_expanded(values_expanded)
        return row

    def _clear_missing_study_rows(self, active_keys: set[str]) -> None:
        to_remove = [key for key in self._study_rows.keys() if key not in active_keys]
        for key in to_remove:
            row = self._study_rows.pop(key, None)
            self._last_row_texts.pop(key, None)
            self._overlay_values_expanded_by_row_key.pop(key, None)
            if row is not None:
                self._study_rows_layout.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
                self._overlay_layout_dirty = True

    def _on_overlay_row_value_toggled(self, row_key: str, expanded: bool) -> None:
        resolved_key = str(row_key).strip()
        if not resolved_key:
            return
        self._overlay_values_expanded_by_row_key[resolved_key] = bool(expanded)
        self._last_row_texts.pop(resolved_key, None)
        self._overlay_layout_dirty = True
        self._update_overlay()

    def _format_value_text(self, raw: object) -> str:
        try:
            numeric = float(raw)
        except Exception:
            return "—"

        if numeric != numeric:
            return "—"

        return f"{numeric:.2f}"

    def _series_tail_label(self, title: str) -> str:
        full = str(title).strip()
        if not full:
            return "Value"

        if "·" in full:
            tail = full.rsplit("·", 1)[-1].strip()
            if tail:
                return tail

        if "[" in full and "]" in full:
            tail = full.split("]", 1)[-1].strip()
            if tail:
                return tail

        return full

    def _managed_overlay_projection(self) -> tuple[List[ManagedOverlayRowProjection], dict[str, str]]:
        """Return the explicit managed overlay projection currently owned by the pane."""
        return (
            self._managed_overlay_rows,
            self._managed_overlay_render_key_to_study_id,
        )

    def _series_is_visible(self, series: Optional[Series]) -> bool:
        if series is None:
            return False
        try:
            return bool(getattr(getattr(series, "style", None), "visible", True))
        except Exception:
            return True

    def _overlay_policy(
        self,
        *,
        title: str,
        render_keys: List[str],
    ) -> OverlayStudyDisplayPolicy:
        return build_overlay_study_display_policy(
            title=title,
            render_keys=render_keys,
        )

    def _overlay_values_expanded(
        self,
        row_key: str,
        policy: OverlayStudyDisplayPolicy,
    ) -> bool:
        if not policy.values_allowed:
            self._overlay_values_expanded_by_row_key[row_key] = False
            return False
        if row_key not in self._overlay_values_expanded_by_row_key:
            self._overlay_values_expanded_by_row_key[row_key] = bool(
                policy.values_default_expanded
            )
        return bool(self._overlay_values_expanded_by_row_key.get(row_key, False))

    def _visible_series_entries(
        self,
        render_keys: List[str],
        overlay_series_by_key: Mapping[str, Series],
    ) -> List[tuple[str, Series]]:
        entries: List[tuple[str, Series]] = []
        for render_key in render_keys:
            series = overlay_series_by_key.get(render_key)
            if series is None or not self._series_is_visible(series):
                continue
            entries.append((render_key, series))
        return entries

    def _overlay_row_text(
        self,
        policy: OverlayStudyDisplayPolicy,
        *,
        entries: List[tuple[str, Series]],
        local_idx: int,
        expanded: bool,
    ) -> str:
        row_text = policy.compact_label
        if not policy.values_allowed or not expanded:
            return row_text

        fragments: List[str] = []
        for render_key, series in entries:
            value_text = self._format_value_text(float("nan"))
            if local_idx < len(series.values):
                value_text = self._format_value_text(series.values[local_idx])

            signal_label = compact_signal_label(
                policy.tool_key,
                line_key_from_render_key(render_key),
            )
            if len(entries) == 1 and not signal_label:
                fragments.append(value_text)
            elif signal_label:
                fragments.append(f"{signal_label} {value_text}")
            else:
                fragments.append(value_text)

        if fragments:
            return f"{row_text}: " + " | ".join(fragments)
        return row_text

    def _primary_visible_series_color(self, entries: List[tuple[str, Series]]) -> Optional[str]:
        for _, series in entries:
            style = getattr(series, "style", None)
            color = self._safe_overlay_label_color(getattr(style, "color", None))
            if color:
                return color
        return None

    def _safe_overlay_label_color(self, color: object) -> Optional[str]:
        resolved = str(color or "").strip()
        if not resolved.startswith("#"):
            return None
        hex_part = resolved[1:]
        if len(hex_part) not in {3, 6, 8}:
            return None
        if not all(char in "0123456789abcdefABCDEF" for char in hex_part):
            return None
        return resolved

    def _update_overlay(self) -> None:
        candles: List[Candle] = self._base_price_bars()
        if not candles:
            if self._last_header_line1 != "O: —  H: —  L: —  C: —":
                self._header.set_line1("O: —  H: —  L: —  C: —")
                self._last_header_line1 = "O: —  H: —  L: —  C: —"
            self._clear_missing_study_rows(set())
            self._last_overlay_local_idx = None
            self._last_overlay_candle_sig = None
            self._last_overlay_payload_version = -1
            self._refresh_overlay_geometry()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(candles):
            local_idx = len(candles) - 1

        c = candles[local_idx]
        header_text = f"O: {c.open:.2f}  H: {c.high:.2f}  L: {c.low:.2f}  C: {c.close:.2f}"
        if header_text != self._last_header_line1:
            self._header.set_line1(header_text)
            self._last_header_line1 = header_text

        # If the crosshair stayed on the same candle and the candle values and
        # overlay payload did not change, skip the expensive overlay-row rebuild.
        candle_sig = (float(c.open), float(c.high), float(c.low), float(c.close))
        if (
            self._last_overlay_local_idx == local_idx
            and self._last_overlay_candle_sig == candle_sig
            and self._last_overlay_payload_version == self._overlay_series_payload_version
            and not self._overlay_layout_dirty
        ):
            return

        self._last_overlay_local_idx = local_idx
        self._last_overlay_candle_sig = candle_sig
        self._last_overlay_payload_version = self._overlay_series_payload_version

        overlay_rows, overlay_render_key_to_study_id = self._managed_overlay_projection()
        overlay_series_by_key = self._overlay_series_by_key

        active_keys: set[str] = set()

        # Managed overlay studies: one row per study.
        # Action identity is the study_instance_id (render keys may drift
        # after projection refresh or style-resolver expansion).
        for row_projection in overlay_rows:
            render_keys = list(row_projection.render_keys)
            if not render_keys:
                continue

            study_instance_id = str(row_projection.study_instance_id).strip()
            if not study_instance_id:
                continue

            title = str(row_projection.title).strip() or study_instance_id
            policy = self._overlay_policy(title=title, render_keys=render_keys)
            expanded = self._overlay_values_expanded(study_instance_id, policy)
            # Source-of-truth rule: managed overlay rows consume the explicit
            # pane payload only. The overlay card must not reach into the
            # model as a second discovery path for managed series.
            entries = self._visible_series_entries(render_keys, overlay_series_by_key)
            row_text = self._overlay_row_text(
                policy,
                entries=entries,
                local_idx=local_idx,
                expanded=expanded,
            )
            active_keys.add(study_instance_id)
            row = self._ensure_study_row(
                study_instance_id,
                action_id=study_instance_id,
                values_allowed=policy.values_allowed,
                values_expanded=expanded,
            )
            row.set_label_color(self._primary_visible_series_color(entries))
            if self._last_row_texts.get(study_instance_id) != row_text:
                row.set_text(row_text)
                self._last_row_texts[study_instance_id] = row_text

        # Unmanaged overlays: keep one row per visible series not claimed by a
        # managed overlay study. These rows still consume explicit pane payload
        # truth; the overlay card must not reach into the model as a second
        # discovery path.
        for key, series in overlay_series_by_key.items():
            if key in overlay_render_key_to_study_id:
                continue
            if not self._series_is_visible(series):
                continue

            active_keys.add(key)
            policy = self._overlay_policy(title=str(series.title), render_keys=[key])
            expanded = self._overlay_values_expanded(key, policy)
            entries = [(key, series)]
            row = self._ensure_study_row(
                key,
                action_id=key,
                values_allowed=policy.values_allowed,
                values_expanded=expanded,
            )
            row.set_label_color(self._primary_visible_series_color(entries))
            row_text = self._overlay_row_text(
                policy,
                entries=entries,
                local_idx=local_idx,
                expanded=expanded,
            )
            if self._last_row_texts.get(key) != row_text:
                row.set_text(row_text)
                self._last_row_texts[key] = row_text

        self._clear_missing_study_rows(active_keys)
        self._refresh_overlay_geometry()
