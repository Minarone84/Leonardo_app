from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout

from leonardo.common.market_types import ChartPatch, ChartSnapshot, Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.model import ChartModel, Series
from leonardo.gui.chart.panes import PricePane, VolumePane, OscillatorPane
from leonardo.gui.chart.crosshair import Crosshair


@dataclass(frozen=True)
class OscillatorSpec:
    key: str
    title: str


@dataclass
class OscillatorPaneState:
    pane_id: str
    study_instance_id: str
    title: str
    render_keys: List[str]
    preferred_height: int = 220


class ChartWorkspaceWidget(QWidget):
    """
    Central chart workspace: price pane + optional volume + optional oscillator panes.
    Shared viewport + shared data owned here (via ChartModel).

    apply_snapshot/apply_patch are GUI-thread entry points for core market data updates.
    """

    request_start_feed = Signal()
    request_stop_feed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._crosshair = Crosshair()

        # ---- Shared data (owned by the model) ----
        self._model = ChartModel(candles=[], volume=[])

        # ---- Shared viewport ----
        self._viewport = ChartViewport(total_count=0, visible_count=1)

        # ---- Layout ----
        self._splitter = QSplitter(Qt.Vertical, self)
        self._splitter.setChildrenCollapsible(False)

        self._price = PricePane(
            viewport=self._viewport,
            model=self._model,
            crosshair=self._crosshair,
            parent=self,
        )
        self._splitter.addWidget(self._price)

        # Optional panes (not shown by default)
        self._volume: Optional[VolumePane] = None

        # Legacy compatibility map: series key -> pane
        # This is ONLY for legacy one-series-per-pane oscillator flows.
        self._oscillators: Dict[str, OscillatorPane] = {}

        # Managed oscillator pane state
        self._oscillator_panes_by_id: Dict[str, OscillatorPane] = {}
        self._oscillator_states_by_id: Dict[str, OscillatorPaneState] = {}
        self._oscillator_pane_order: List[str] = []
        self._study_to_pane_id: Dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._splitter)

        self._apply_default_sizes(force=True)

    # -------- Public API (MainWindow / controller calls these) --------

    def set_asset_label(self, text: str) -> None:
        self._price.set_asset_label(text)

    def set_studies_labels(self, indicators: List[str], oscillators: List[str]) -> None:
        self._price.set_studies(indicators=indicators, oscillators=oscillators)
        self._refresh_price_pane()

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)

        self._viewport.set_anchor_zoom_enabled(enabled)
        self._viewport.set_future_padding(0 if enabled else 50)
        self._refresh_price_pane()

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

    def add_oscillator(self, spec: OscillatorSpec) -> None:
        """
        Legacy compatibility path.

        Create a pane for an already-existing oscillator series in the model.
        This remains series-based and should be avoided by new code.
        """
        if spec.key in self._oscillators:
            return

        series = self._model.oscillator(spec.key)
        if series is None:
            return

        pane = OscillatorPane(
            title=series.title,
            viewport=self._viewport,
            crosshair=self._crosshair,
            values=series.values,
            parent=self,
        )
        self._oscillators[spec.key] = pane
        self._splitter.addWidget(pane)
        self._refresh_aux_pane_bindings()
        self._apply_default_sizes(force=True)

    def remove_oscillator(self, key: str) -> None:
        pane = self._oscillators.pop(key, None)
        if pane is None:
            return

        self._capture_managed_pane_heights()
        self._remove_widget(pane)
        pane.deleteLater()
        self._model.remove_oscillator(key)
        self._apply_default_sizes(force=True)

    def clear_oscillators(self) -> None:
        self._capture_managed_pane_heights()

        # Remove legacy panes only. Managed panes are owned separately below.
        legacy_panes = self._legacy_oscillator_panes_in_order()
        self._oscillators.clear()

        for pane in legacy_panes:
            self._remove_widget(pane)
            pane.deleteLater()

        # Remove managed panes once, through managed ownership only.
        for pane_id in list(self._oscillator_pane_order):
            pane = self._oscillator_panes_by_id.pop(pane_id, None)
            if pane is not None:
                self._remove_widget(pane)
                pane.deleteLater()

        self._oscillator_states_by_id.clear()
        self._oscillator_pane_order.clear()
        self._study_to_pane_id.clear()

        for key in list(self._model.oscillators().keys()):
            self._model.remove_oscillator(key)

        self._apply_default_sizes(force=True)

    def clear_overlays(self) -> None:
        for key in list(self._model.overlays().keys()):
            self._model.remove_overlay(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def clear_financial_tools(self) -> None:
        self.clear_overlays()
        self.clear_oscillators()

    def apply_overlay_series(self, series: Series) -> None:
        """
        Apply or replace a price overlay series in the chart model.
        """
        self._model.set_overlay(series)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def remove_overlay_series(self, key: str) -> None:
        """
        Remove a price overlay series from the chart model.
        """
        self._model.remove_overlay(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def apply_oscillator_series(self, series: Series) -> None:
        """
        Legacy compatibility path.

        Apply or replace an oscillator series and ensure its pane exists.
        New code should prefer apply_oscillator_study().
        """
        self._model.set_oscillator(series)

        if series.key in self._oscillators:
            pane = self._oscillators[series.key]
            if hasattr(pane, "set_values"):
                try:
                    pane.set_values(series.values)
                except Exception:
                    pass
        else:
            pane = OscillatorPane(
                title=series.title,
                viewport=self._viewport,
                crosshair=self._crosshair,
                values=series.values,
                parent=self,
            )
            self._oscillators[series.key] = pane
            self._splitter.addWidget(pane)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._apply_default_sizes(force=True)

    def remove_oscillator_series(self, key: str) -> None:
        """
        Remove an oscillator series.

        This method supports both:
        - legacy series-level panes
        - managed study-level panes containing the series
        """
        pane_id = self._pane_id_for_render_key(key)
        if pane_id:
            state = self._oscillator_states_by_id.get(pane_id)
            if state is not None:
                self.remove_oscillator_study(state.study_instance_id)
        else:
            self.remove_oscillator(key)

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
        """
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return

        normalized_series = [
            Series(
                key=str(series.key),
                title=str(series.title),
                values=list(series.values),
                style=series.style,
            )
            for series in series_list
        ]
        if not normalized_series:
            return

        for series in normalized_series:
            self._model.set_oscillator(series)

        pane_id = self._study_to_pane_id.get(normalized_study_id)
        if pane_id is None:
            pane_id = normalized_study_id
            self._study_to_pane_id[normalized_study_id] = pane_id

        render_keys = [series.key for series in normalized_series]
        state = self._oscillator_states_by_id.get(pane_id)

        if state is None:
            state = OscillatorPaneState(
                pane_id=pane_id,
                study_instance_id=normalized_study_id,
                title=str(title).strip() or normalized_series[0].title,
                render_keys=list(render_keys),
            )
            self._oscillator_states_by_id[pane_id] = state
            self._oscillator_pane_order.append(pane_id)

            pane = OscillatorPane(
                title=state.title,
                viewport=self._viewport,
                crosshair=self._crosshair,
                study_instance_id=normalized_study_id,
                series_list=normalized_series,
                parent=self,
            )
            self._oscillator_panes_by_id[pane_id] = pane
            self._splitter.addWidget(pane)
        else:
            state.title = str(title).strip() or normalized_series[0].title
            state.render_keys = list(render_keys)
            state.study_instance_id = normalized_study_id

            pane = self._oscillator_panes_by_id[pane_id]
            pane.set_study_instance_id(normalized_study_id)
            pane.set_title(state.title)
            pane.set_series_list(normalized_series)

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

    @property
    def viewport(self) -> ChartViewport:
        return self._viewport

    @property
    def model(self) -> ChartModel:
        return self._model

    # -------- core → GUI chart update API --------

    def apply_snapshot(self, snapshot: ChartSnapshot) -> None:
        candles = list(snapshot.candles)

        self.set_asset_label(f"{snapshot.symbol} · {snapshot.timeframe}")

        if not candles:
            self._model.set_candles([])
            self._model.set_volume([])
            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(0)  # type: ignore[attr-defined]
            return

        self._model.set_candles(candles)
        self._model.set_volume([float(c.volume) for c in candles])

        if hasattr(self._model, "set_resident_base_index"):
            try:
                self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(self._model, "resident_base_index"):
            try:
                setattr(self._model, "resident_base_index", 0)
            except Exception:
                pass

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

        n = len(candles)
        if hasattr(self._viewport, "set_total_count"):
            self._viewport.set_total_count(n)  # type: ignore[attr-defined]

    def apply_historical_slice(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        resident_base_index: int,
        dataset_total: int,
    ) -> None:
        """
        Historical-mode apply path.

        Unlike apply_snapshot(), the viewport total represents the full dataset
        size, while the model stores only the currently resident slice.
        """
        self.set_asset_label(f"{symbol} · {timeframe}")

        if not candles:
            self._model.set_candles([])
            self._model.set_volume([])
            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(int(resident_base_index))  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", int(resident_base_index))
                except Exception:
                    pass

            if hasattr(self._viewport, "set_total_count_preserve_position"):
                self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
            elif hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
            return

        self._model.set_candles(candles)
        self._model.set_volume([float(c.volume) for c in candles])

        if hasattr(self._model, "set_resident_base_index"):
            try:
                self._model.set_resident_base_index(int(resident_base_index))  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(self._model, "resident_base_index"):
            try:
                setattr(self._model, "resident_base_index", int(resident_base_index))
            except Exception:
                pass

        if hasattr(self._viewport, "set_total_count_preserve_position"):
            self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
        elif hasattr(self._viewport, "set_total_count"):
            self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def apply_patch(self, patch: ChartPatch) -> None:
        self.set_asset_label(f"{patch.symbol} · {patch.timeframe}")

        if patch.op == "append":
            self._model.append_candle(patch.candle, maxlen=200)

            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(len(self._model.candles))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
        else:
            self._model.update_last_candle(patch.candle)

            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()

    # -------- Internal helpers --------

    def _apply_default_sizes(self, *, force: bool = False) -> None:
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

        for _ in self._legacy_oscillator_panes_in_order():
            sizes.append(220)

        if len(sizes) == 1:
            sizes = [1000]

        self._splitter.setSizes(sizes)

    def _remove_widget(self, w: QWidget) -> None:
        w.setParent(None)
        w.hide()

    def _refresh_studies_labels(self) -> None:
        overlay_titles = [s.title for s in self._model.overlays().values()]
        oscillator_titles = [s.title for s in self._model.oscillators().values()]
        self.set_studies_labels(overlay_titles, oscillator_titles)

    def _refresh_price_pane(self) -> None:
        """
        Force the price pane to repaint after candle/overlay/study changes.

        This is intentionally explicit because overlay series can be present in
        the model and in the study labels while still not becoming visible until
        the pane is repainted.
        """
        if hasattr(self._price, "update"):
            try:
                self._price.update()  # type: ignore[attr-defined]
            except Exception:
                pass

        if hasattr(self._price, "repaint"):
            try:
                self._price.repaint()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _refresh_aux_pane_bindings(self) -> None:
        """
        Keep auxiliary panes bound to the model's current series objects and
        resident base index.
        """
        resident_base_index = 0
        if hasattr(self._model, "resident_base_index"):
            try:
                resident_base_index = int(self._model.resident_base_index)
            except Exception:
                resident_base_index = 0

        if self._volume is not None:
            if hasattr(self._volume, "set_candles"):
                try:
                    self._volume.set_candles(self._model.candles)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if hasattr(self._volume, "set_volume"):
                try:
                    self._volume.set_volume(self._model.volume)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if hasattr(self._volume, "set_resident_base_index"):
                try:
                    self._volume.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass

        for key, pane in self._oscillators.items():
            series = self._model.oscillator(key)
            if series is not None:
                if hasattr(pane, "set_values"):
                    try:
                        pane.set_values(series.values)  # type: ignore[attr-defined]
                    except Exception:
                        pass

            if hasattr(pane, "set_resident_base_index"):
                try:
                    pane.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass

        for pane_id in self._oscillator_pane_order:
            pane = self._oscillator_panes_by_id.get(pane_id)
            state = self._oscillator_states_by_id.get(pane_id)
            if pane is None or state is None:
                continue

            series_list: List[Series] = []
            for render_key in state.render_keys:
                series = self._model.oscillator(render_key)
                if series is not None:
                    series_list.append(series)

            if series_list:
                if hasattr(pane, "set_series_list"):
                    try:
                        pane.set_series_list(series_list)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                elif hasattr(pane, "set_values"):
                    try:
                        pane.set_values(series_list[0].values)  # type: ignore[attr-defined]
                    except Exception:
                        pass

            if hasattr(pane, "set_resident_base_index"):
                try:
                    pane.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass

    def _pane_id_for_render_key(self, render_key: str) -> Optional[str]:
        normalized_key = str(render_key).strip()
        if not normalized_key:
            return None

        for pane_id, state in self._oscillator_states_by_id.items():
            if normalized_key in state.render_keys:
                return pane_id
        return None

    def _legacy_oscillator_panes_in_order(self) -> List[OscillatorPane]:
        ordered: List[OscillatorPane] = []
        seen: set[int] = set()

        for pane in self._oscillators.values():
            marker = id(pane)
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append(pane)

        return ordered

    def _current_splitter_widget_order(self) -> List[QWidget]:
        widgets: List[QWidget] = []
        for index in range(self._splitter.count()):
            widget = self._splitter.widget(index)
            if widget is not None:
                widgets.append(widget)
        return widgets

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
        if self._volume is not None:
            widgets.append(self._volume)

        for pane_id in self._oscillator_pane_order:
            pane = self._oscillator_panes_by_id.get(pane_id)
            if pane is not None:
                widgets.append(pane)

        for pane in self._legacy_oscillator_panes_in_order():
            if pane not in widgets:
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
            if hasattr(pane, "set_move_capabilities"):
                try:
                    pane.set_move_capabilities(
                        can_move_up=index > 0,
                        can_move_down=index < (total - 1),
                    )
                except Exception:
                    pass