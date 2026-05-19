from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from leonardo.common.chart_messages import ChartPatch, ChartSnapshot
from leonardo.common.market_types import Candle
from leonardo.gui.chart.model import OverlayFill, Series
from leonardo.gui.chart.panes.contracts import PaneBackgroundRegion


def _coerce_values_list(raw: object) -> Sequence[float]:
    """Return an immutable-by-contract sequence without cloning hot-path buffers.

    Rendering hot-path performance depends on avoiding repeated O(N) list copies
    across multi-chart study apply/reapply. Values are treated as
    immutable-by-contract downstream and may be lazy Sequence implementations.
    """
    if raw is None:
        return []
    if hasattr(raw, "__len__") and hasattr(raw, "__getitem__"):
        return raw  # type: ignore[return-value]
    try:
        return list(raw)  # type: ignore[arg-type]
    except Exception:
        return []


def _coerce_background_region(raw: object) -> Optional[PaneBackgroundRegion]:
    if isinstance(raw, PaneBackgroundRegion):
        region_id = str(raw.region_id).strip()
        if not region_id:
            return None
        if int(raw.end_index) < int(raw.start_index):
            return None
        return PaneBackgroundRegion(
            region_id=region_id,
            start_index=int(raw.start_index),
            end_index=int(raw.end_index),
            color=raw.color,
            opacity=float(raw.opacity),
            visible=bool(raw.visible),
            source_signal=str(raw.source_signal),
            label=str(raw.label),
        )

    region_id = str(getattr(raw, "region_id", "") or "").strip()
    if not region_id:
        return None

    try:
        start_index = int(getattr(raw, "start_index"))
        end_index = int(getattr(raw, "end_index"))
    except Exception:
        return None

    if end_index < start_index:
        return None

    return PaneBackgroundRegion(
        region_id=region_id,
        start_index=start_index,
        end_index=end_index,
        color=getattr(raw, "color", None),
        opacity=float(getattr(raw, "opacity", 0.08)),
        visible=bool(getattr(raw, "visible", True)),
        source_signal=str(getattr(raw, "source_signal", "") or ""),
        label=str(getattr(raw, "label", "") or ""),
    )


def _coerce_background_regions(raw_regions: object) -> List[PaneBackgroundRegion]:
    if raw_regions is None:
        return []

    try:
        iterable = list(raw_regions)  # type: ignore[arg-type]
    except Exception:
        return []

    regions: List[PaneBackgroundRegion] = []
    for raw_region in iterable:
        region = _coerce_background_region(raw_region)
        if region is not None:
            regions.append(region)
    return regions


class WorkspaceApplyMixin:

    def reapply_projected_studies(self, payloads: List[Dict[str, Any]]) -> None:
        """
        Reapply controller-projected resident-local studies without recomputation.

        This is the workspace-side bridge for historical resident-slice changes.

        The controller owns:
        - full-dataset study truth
        - current resident-local study projections

        The workspace owns:
        - rendered study application state
        - pane ownership
        - overlay grouping
        - pane-local visual policy

        This method accepts the controller's current projected payloads and
        reapplies them into the workspace/model while preserving existing pane
        ownership and avoiding any viewport mutation.
        """
        normalized_entries: List[Dict[str, Any]] = []

        for payload in payloads:
            if not isinstance(payload, dict):
                continue

            study_instance_id = self._projected_study_id_from_payload(payload)
            if not study_instance_id:
                continue

            title = (
                str(payload.get("display_name", "")).strip()
                or str(payload.get("tool_title", "")).strip()
                or str(payload.get("tool_key", "")).strip()
                or study_instance_id
            )

            raw_series_list = payload.get("series_list", []) or []
            normalized_series: List[Series] = []
            for series in raw_series_list:
                key = str(getattr(series, "key", "") or "").strip()
                if not key:
                    continue
                normalized_series.append(
                    Series(
                        key=key,
                        title=str(getattr(series, "title", "") or key),
                        values=_coerce_values_list(getattr(series, "values", None)),
                        style=getattr(series, "style", None),
                    )
                )

            if not normalized_series:
                continue

            fill_descriptors_provided = "fill_descriptors" in payload
            normalized_fill_descriptors: Optional[List[OverlayFill]] = None
            if fill_descriptors_provided:
                normalized_fill_descriptors = []
                raw_fill_descriptors = payload.get("fill_descriptors", [])
                if isinstance(raw_fill_descriptors, list):
                    fills: List[OverlayFill] = []
                    for fill in raw_fill_descriptors:
                        fill_id = str(getattr(fill, "fill_id", "") or "").strip()
                        series_a = str(getattr(fill, "series_a", "") or "").strip()
                        series_b = str(getattr(fill, "series_b", "") or "").strip()
                        if not fill_id or not series_a or not series_b:
                            continue
                        fills.append(
                            OverlayFill(
                                fill_id=fill_id,
                                series_a=series_a,
                                series_b=series_b,
                                color=getattr(fill, "color", None),
                                opacity=float(getattr(fill, "opacity", 0.15)),
                                visible=bool(getattr(fill, "visible", True)),
                            )
                        )
                    normalized_fill_descriptors = fills

            background_regions_provided = "background_regions" in payload
            normalized_background_regions: Optional[List[PaneBackgroundRegion]] = None
            if background_regions_provided:
                normalized_background_regions = _coerce_background_regions(
                    payload.get("background_regions", [])
                )

            normalized_entries.append(
                {
                    "study_instance_id": study_instance_id,
                    "title": title,
                    "series_list": normalized_series,
                    "fill_descriptors": normalized_fill_descriptors,
                    "fill_descriptors_provided": fill_descriptors_provided,
                    "background_regions": normalized_background_regions,
                    "background_regions_provided": background_regions_provided,
                    "target": self._infer_projected_study_target(
                        study_instance_id=study_instance_id,
                        payload=payload,
                    ),
                }
            )

        desired_ids = {
            str(entry["study_instance_id"]).strip()
            for entry in normalized_entries
            if str(entry["study_instance_id"]).strip()
        }

        with self._workspace_update_batch():
            self._prune_managed_projected_studies(desired_ids)

            for entry in normalized_entries:
                study_instance_id = str(entry["study_instance_id"])
                title = str(entry["title"])
                series_list = list(entry["series_list"])
                target = str(entry["target"]).strip().lower()

                if target == "oscillator":
                    self.apply_oscillator_study(
                        study_instance_id=study_instance_id,
                        title=title,
                        series_list=series_list,
                    )
                    continue

                fill_descriptors_provided = bool(entry.get("fill_descriptors_provided", False))
                fill_descriptors = entry.get("fill_descriptors")
                if fill_descriptors is None and not fill_descriptors_provided:
                    fill_descriptors = self._snapshot_overlay_fill_descriptors(study_instance_id)
                self.apply_overlay_study(
                    study_instance_id=study_instance_id,
                    title=title,
                    series_list=series_list,
                    fill_descriptors=fill_descriptors,
                )

                if bool(entry.get("background_regions_provided", False)):
                    self.apply_overlay_background_regions(
                        study_instance_id=study_instance_id,
                        background_regions=list(entry.get("background_regions") or []),
                    )

    def _projected_study_id_from_payload(self, payload: Dict[str, Any]) -> str:
        return (
            str(payload.get("study_instance_id", "")).strip()
            or str(payload.get("study_projection_key", "")).strip()
        )

    def _infer_projected_study_target(
        self,
        *,
        study_instance_id: str,
        payload: Dict[str, Any],
    ) -> str:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return "overlay"

        if normalized_study_id in self._study_to_pane_id:
            return "oscillator"

        if normalized_study_id in self._overlay_states_by_id:
            return "overlay"

        tool_type = str(payload.get("tool_type", "")).strip().lower()
        if tool_type == "oscillator":
            return "oscillator"

        return "overlay"

    def _prune_managed_projected_studies(self, desired_ids: set[str]) -> None:
        for study_instance_id in list(self._overlay_states_by_id.keys()):
            if study_instance_id not in desired_ids:
                self.remove_overlay_study(study_instance_id)

        for study_instance_id in list(self._study_to_pane_id.keys()):
            if study_instance_id not in desired_ids:
                self.remove_oscillator_study(study_instance_id)

    def _snapshot_overlay_fill_descriptors(
        self,
        study_instance_id: str,
    ) -> Optional[List[OverlayFill]]:
        normalized_study_id = str(study_instance_id).strip()
        if not normalized_study_id:
            return None

        state = self._overlay_states_by_id.get(normalized_study_id)
        if state is None or not state.fill_ids:
            return None

        fill_lookup: Dict[str, OverlayFill] = {}
        if hasattr(self._model, "overlay_fills"):
            try:
                fills = self._model.overlay_fills()  # type: ignore[attr-defined]
            except Exception:
                fills = None
            if isinstance(fills, list):
                fill_lookup = {
                    str(getattr(fill, "fill_id", "") or "").strip(): fill
                    for fill in fills
                    if str(getattr(fill, "fill_id", "") or "").strip()
                }

        if not fill_lookup:
            fill_map: Any = getattr(self._model, "_overlay_fills", None)
            if isinstance(fill_map, dict):
                fill_lookup = dict(fill_map)

        if not fill_lookup:
            return None

        descriptors: List[OverlayFill] = []
        for fill_id in state.fill_ids:
            fill = fill_lookup.get(fill_id)
            if fill is None:
                continue

            resolved_fill_id = str(getattr(fill, "fill_id", fill_id) or "").strip()
            series_a = str(getattr(fill, "series_a", "") or "").strip()
            series_b = str(getattr(fill, "series_b", "") or "").strip()
            if not resolved_fill_id or not series_a or not series_b:
                continue

            descriptors.append(
                OverlayFill(
                    fill_id=resolved_fill_id,
                    series_a=series_a,
                    series_b=series_b,
                    color=str(getattr(fill, "color", "") or ""),
                    opacity=float(getattr(fill, "opacity", 0.0)),
                    visible=bool(getattr(fill, "visible", True)),
                )
            )

        return descriptors or None

    def apply_snapshot(self, snapshot: ChartSnapshot) -> None:
        candles = list(snapshot.candles)

        self.set_asset_label(f"{snapshot.symbol} · {snapshot.timeframe}")

        with self._workspace_update_batch():
            if hasattr(self._viewport, "set_domain_padding"):
                try:
                    self._viewport.set_domain_padding(left_pad=0, right_pad=0)  # type: ignore[attr-defined]
                except Exception:
                    pass

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

        with self._workspace_update_batch():
            if hasattr(self._viewport, "set_domain_padding"):
                try:
                    self._viewport.set_domain_padding(
                        left_pad=self.HISTORICAL_LEFT_DOMAIN_PAD,
                        right_pad=self.HISTORICAL_RIGHT_DOMAIN_PAD,
                    )  # type: ignore[attr-defined]
                except Exception:
                    pass

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
        """
        Apply a live chart patch without truncating chart truth.

        Workflow-plan rule for this phase:
        - pan/zoom must never cause effective data loss
        - the viewport must behave like a viewport, not like a retention policy
        - workspace must therefore not cap the canonical/live base OHLC layer for
          convenience during append operations

        Historical resident slicing remains a controller/session concern.
        Realtime retention policy, if any, must also live above this workspace
        layer rather than being smuggled into the chart model through a GUI-side
        maxlen.
        """
        self.set_asset_label(f"{patch.symbol} · {patch.timeframe}")

        with self._workspace_update_batch():
            if hasattr(self._viewport, "set_domain_padding"):
                try:
                    self._viewport.set_domain_padding(left_pad=0, right_pad=0)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if patch.op == "append":
                # IMPORTANT:
                # Do not truncate here. A GUI-side maxlen turns the viewport into an
                # accidental data-retention policy and violates the chart contract.
                self._model.append_candle(patch.candle)
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

            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(len(self._model.candles))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
