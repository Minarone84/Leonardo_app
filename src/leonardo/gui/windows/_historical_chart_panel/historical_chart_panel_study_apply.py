from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtWidgets import QApplication

from leonardo.gui.chart.model import Series
from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_OSCILLATOR,
    PANE_TARGET_PRICE,
    STUDY_FAMILY_CONSTRUCT,
    STUDY_FAMILY_INDICATOR,
    STUDY_FAMILY_OSCILLATOR,
    STUDY_SOURCE_TEMPORARY,
    StudyComputationConfig,
)
from leonardo.gui.windows._historical_chart_panel.apply_progress_dialog import (
    FinancialToolApplyProgressDialog,
)

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



class HistoricalChartPanelStudyApplyMixin:
    """Panel-owned helper methods extracted from HistoricalChartPanel.

    This mixin has no durable state of its own. It operates on the
    HistoricalChartPanel instance that owns the chart-local study session.
    """

    def _normalize_study_family(self, tool_type: str) -> str:
        normalized = str(tool_type).strip().lower()
        if normalized == STUDY_FAMILY_INDICATOR:
            return STUDY_FAMILY_INDICATOR
        if normalized == STUDY_FAMILY_OSCILLATOR:
            return STUDY_FAMILY_OSCILLATOR
        if normalized == STUDY_FAMILY_CONSTRUCT:
            return STUDY_FAMILY_CONSTRUCT
        return normalized

    def _extract_behavior(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("behavior", {}) or {}
        if not isinstance(raw, dict):
            raw = {}

        output_mode = str(raw.get("output_mode", "")).strip().lower()
        if output_mode not in {"overlay", "oscillator-pane", "non-visual"}:
            family = self._normalize_study_family(str(payload.get("tool_type", "")))
            if family == STUDY_FAMILY_OSCILLATOR:
                output_mode = "oscillator-pane"
            else:
                output_mode = "overlay"

        chart_renderable = raw.get("chart_renderable", output_mode != "non-visual")
        supports_style = raw.get("supports_style", bool(chart_renderable))
        supports_pane_layout = raw.get("supports_pane_layout", output_mode == "oscillator-pane")
        supports_last_value = raw.get("supports_last_value", bool(chart_renderable))

        return {
            "output_mode": output_mode,
            "chart_renderable": bool(chart_renderable),
            "supports_style": bool(supports_style),
            "supports_pane_layout": bool(supports_pane_layout),
            "supports_last_value": bool(supports_last_value),
        }

    def _extract_output(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("output", {}) or {}
        if not isinstance(raw, dict):
            raw = {}

        output_names = raw.get("output_names", []) or []
        if not isinstance(output_names, list):
            output_names = list(output_names) if isinstance(output_names, tuple) else []

        structure = str(raw.get("structure", "")).strip().lower()
        if not structure:
            structure = "line-series"

        return {
            "structure": structure,
            "output_names": [str(name) for name in output_names],
            "accepts_empty_render_output": bool(raw.get("accepts_empty_render_output", False)),
        }

    def _pane_target_for_output_mode(self, output_mode: str) -> Optional[str]:
        normalized = str(output_mode).strip().lower()
        if normalized == "oscillator-pane":
            return PANE_TARGET_OSCILLATOR
        if normalized == "overlay":
            return PANE_TARGET_PRICE
        return None

    def _study_is_renderable(self, study: ChartStudyInstance) -> bool:
        return bool(study.runtime.render_keys)

    def _remove_study_rendered_series(self, study: ChartStudyInstance) -> None:
        if not self._study_is_renderable(study):
            return

        if study.pane_target == PANE_TARGET_OSCILLATOR:
            if hasattr(self._workspace, "remove_oscillator_study"):
                try:
                    self._workspace.remove_oscillator_study(study.instance_id)
                    self._cleanup_oscillator_pane_signal_tracking()
                    return
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study removal fallback engaged for "
                        f"'{study.display_name}': {e!r}"
                    )

        if study.pane_target == PANE_TARGET_PRICE:
            if hasattr(self._workspace, "remove_overlay_study"):
                try:
                    self._workspace.remove_overlay_study(study.instance_id)
                    self._cleanup_oscillator_pane_signal_tracking()
                    return
                except Exception as e:
                    self._on_error(
                        f"Managed overlay study removal fallback engaged for "
                        f"'{study.display_name}': {e!r}"
                    )

        for render_key in study.runtime.render_keys:
            if study.pane_target == PANE_TARGET_OSCILLATOR:
                self._workspace.remove_oscillator_series(render_key)
            else:
                self._workspace.remove_overlay_series(render_key)

        self._cleanup_oscillator_pane_signal_tracking()

    def _on_price_pane_study_remove_requested(self, action_id: str) -> None:
        """Handle remove requests coming from the PricePane overlay card.

        Managed overlay rows should emit study_instance_id.
        Legacy/unmanaged rows may still emit a render key.
        """
        normalized_id = str(action_id).strip()
        if not normalized_id:
            self._on_error("Cannot remove study: empty action id.")
            return

        study = self._study_registry.get(normalized_id) or self._find_study_by_render_key(normalized_id)
        if study is None:
            self._on_error(
                "Cannot remove study: action id '"
                + normalized_id
                + "' is not registered (instance_id or render key)."
            )
            return

        self.remove_study_instance(study.instance_id)

    def _on_price_pane_study_edit_requested(self, action_id: str) -> None:
        """Handle edit requests coming from the PricePane overlay card."""
        normalized_id = str(action_id).strip()
        if not normalized_id:
            self._on_error("Cannot edit study: empty action id.")
            return

        study = self._study_registry.get(normalized_id) or self._find_study_by_render_key(normalized_id)
        if study is None:
            self._on_error(
                "Cannot edit study: action id '"
                + normalized_id
                + "' is not registered (instance_id or render key)."
            )
            return

        self._open_study_for_edit(study)

    def _on_oscillator_pane_study_edit_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot edit oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot edit oscillator study: unknown instance_id '{normalized_id}'.")
            return

        self._open_study_for_edit(study)

    def _open_study_for_edit(self, study: ChartStudyInstance) -> None:
        self._editing_study_instance_id = study.instance_id

        manager = self._ensure_financial_tools_manager_window()

        dataset_changed = (
            getattr(manager, "_exchange", "") != self._exchange
            or getattr(manager, "_market_type", "") != self._market_type
            or getattr(manager, "_symbol", "") != self._symbol
            or getattr(manager, "_timeframe", "") != self._timeframe
        )

        if dataset_changed:
            manager = self._recreate_financial_tools_manager_window()

        preload_ok = False
        if hasattr(manager, "load_study_for_edit"):
            try:
                preload_ok = bool(
                    manager.load_study_for_edit(
                        tool_type=study.computation.family,
                        tool_key=study.computation.tool_key,
                        params=study.computation.params,
                    )
                )
            except Exception as e:
                self._on_error(f"Study preload failed for '{study.display_name}': {e!r}")

        manager.show()
        manager.raise_()
        manager.activateWindow()

        if preload_ok:
            self._on_error(
                "Study edit preloaded for "
                f"'{study.display_name}' "
                f"(tool_key={study.computation.tool_key}, params={study.computation.params})."
            )
        else:
            self._on_error(
                "Study edit opened without preload for "
                f"'{study.display_name}' "
                f"(tool_key={study.computation.tool_key}, params={study.computation.params})."
            )

    def _on_oscillator_pane_study_remove_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot remove oscillator study: empty instance_id.")
            return

        study = self._study_registry.get(normalized_id)
        if study is None:
            self._on_error(f"Cannot remove oscillator study: unknown instance_id '{normalized_id}'.")
            return

        self.remove_study_instance(study.instance_id)

    def _on_oscillator_pane_move_up_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot move oscillator pane up: empty instance_id.")
            return

        if hasattr(self._workspace, "move_oscillator_pane_up"):
            try:
                moved = bool(self._workspace.move_oscillator_pane_up(normalized_id))
            except Exception as e:
                self._on_error(f"Oscillator pane move up failed: {e!r}")
                return

            if moved:
                study = self._study_registry.get(normalized_id)
                if study is not None:
                    self._on_error(f"Moved oscillator pane up for '{study.display_name}'.")
            return

        self._on_error("Oscillator pane move up is not available on the current workspace.")

    def _on_oscillator_pane_move_down_requested(self, instance_id: str) -> None:
        normalized_id = str(instance_id).strip()
        if not normalized_id:
            self._on_error("Cannot move oscillator pane down: empty instance_id.")
            return

        if hasattr(self._workspace, "move_oscillator_pane_down"):
            try:
                moved = bool(self._workspace.move_oscillator_pane_down(normalized_id))
            except Exception as e:
                self._on_error(f"Oscillator pane move down failed: {e!r}")
                return

            if moved:
                study = self._study_registry.get(normalized_id)
                if study is not None:
                    self._on_error(f"Moved oscillator pane down for '{study.display_name}'.")
            return

        self._on_error("Oscillator pane move down is not available on the current workspace.")

    def _financial_tool_apply_title(self, payload: dict) -> str:
        title = str(payload.get("tool_title", "") or "").strip()
        if title:
            return title

        tool_key = str(payload.get("tool_key", "") or "").strip()
        return tool_key or "Selected study"

    def _financial_tool_apply_dataset_label(self) -> str:
        dataset_title = getattr(self, "dataset_title", None)
        if callable(dataset_title):
            try:
                label = str(dataset_title()).strip()
                if label:
                    return label
            except Exception:
                pass

        dataset_key = getattr(self, "dataset_key", None)
        if callable(dataset_key):
            try:
                label = str(dataset_key()).strip()
                if label:
                    return label
            except Exception:
                pass

        return "Current chart"

    def _financial_tool_apply_input_bar_count(self) -> Optional[int]:
        controller = getattr(self, "_controller", None)
        if controller is None:
            return None

        count_provider = getattr(controller, "current_input_bar_count", None)
        if not callable(count_provider):
            return None

        try:
            count = count_provider()
        except Exception:
            return None

        if count is None:
            return None

        try:
            return max(0, int(count))
        except Exception:
            return None

    def _make_financial_tool_apply_dialog(
        self,
        payload: dict,
    ) -> FinancialToolApplyProgressDialog:
        return FinancialToolApplyProgressDialog(
            tool_title=self._financial_tool_apply_title(payload),
            dataset_label=self._financial_tool_apply_dataset_label(),
            input_bar_count=self._financial_tool_apply_input_bar_count(),
            parent=self,
        )

    def _execute_financial_tool_apply_with_dialog(
        self,
        payload: dict,
        dialog: FinancialToolApplyProgressDialog,
    ) -> None:
        state = {"succeeded": False, "error": ""}

        def _mark_success(_payload: dict) -> None:
            state["succeeded"] = True

        def _mark_error(message: str) -> None:
            state["error"] = str(message)

        success_signal = getattr(self._controller, "apply_succeeded", None)
        error_signal = getattr(self._controller, "error", None)

        try:
            if success_signal is not None:
                success_signal.connect(_mark_success)
            if error_signal is not None:
                error_signal.connect(_mark_error)

            self._controller.apply_financial_tool(payload)
        except Exception as e:
            self._editing_study_instance_id = None
            state["error"] = f"Financial tool apply failed: {e!r}"
            self._on_error(state["error"])
        finally:
            if success_signal is not None:
                try:
                    success_signal.disconnect(_mark_success)
                except Exception:
                    pass
            if error_signal is not None:
                try:
                    error_signal.disconnect(_mark_error)
                except Exception:
                    pass

        if state["succeeded"] and not state["error"]:
            dialog.mark_success(f"Applied {self._financial_tool_apply_title(payload)}.")
            return

        dialog.mark_failure(state["error"] or "Financial tool apply did not report success.")

    def _on_financial_tools_apply_requested(self, payload: dict) -> None:
        dialog = self._make_financial_tool_apply_dialog(payload)
        self._active_apply_progress_dialog = dialog

        apply_started = False

        def _start_apply() -> None:
            nonlocal apply_started
            if apply_started:
                return

            apply_started = True
            dialog.start_applying()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
            self._execute_financial_tool_apply_with_dialog(payload, dialog)

        dialog.apply_requested.connect(_start_apply)
        try:
            dialog.exec()
        finally:
            try:
                dialog.apply_requested.disconnect(_start_apply)
            except Exception:
                pass
            if getattr(self, "_active_apply_progress_dialog", None) is dialog:
                self._active_apply_progress_dialog = None

    def _on_financial_tools_save_requested(self, payload: dict) -> None:
        try:
            self._controller.save_financial_tool(payload)
        except Exception as e:
            self._on_error(f"Financial tool save failed: {e!r}")

    def _normalize_output_structure(self, structure: str, *, chart_renderable: bool) -> str:
        normalized = str(structure or "").strip().lower()
        if not normalized:
            return "line-series" if chart_renderable else "analysis-only"
        return normalized

    def _series_has_render_key(self, series: Series) -> bool:
        return bool(str(getattr(series, "key", "") or "").strip())

    def _series_list_has_resident_values(self, series_list: List[Series]) -> bool:
        """Return True when a payload contains at least one keyed resident value.

        This keeps empty render payload handling in the panel, where
        chart-local study lifecycle is owned, without moving renderability
        semantics into workspace or render surfaces.
        """
        for series in series_list:
            if not self._series_has_render_key(series):
                continue

            values = getattr(series, "values", None)
            if values is None:
                continue

            try:
                if len(values) > 0:  # type: ignore[arg-type]
                    return True
            except Exception:
                try:
                    iterator = iter(values)  # type: ignore[arg-type]
                    next(iterator)
                    return True
                except Exception:
                    continue

        return False

    def _validate_apply_payload_contract(
        self,
        *,
        tool_key: str,
        output_mode: str,
        chart_renderable: bool,
        output_structure: str,
        accepts_empty_render_output: bool,
        series_list: List[Series],
    ) -> Optional[str]:
        normalized_mode = str(output_mode).strip().lower()
        normalized_structure = self._normalize_output_structure(
            output_structure,
            chart_renderable=chart_renderable,
        )

        if normalized_structure not in self._KNOWN_OUTPUT_STRUCTURES:
            return (
                f"Financial tool apply failed: unsupported output structure "
                f"'{normalized_structure}' for tool '{tool_key}'."
            )

        if normalized_mode == "non-visual" and chart_renderable:
            return (
                f"Financial tool apply failed: tool '{tool_key}' declared non-visual "
                "output_mode but chart_renderable=True."
            )

        if normalized_structure in self._NON_RENDERABLE_OUTPUT_STRUCTURES:
            if chart_renderable:
                return (
                    f"Financial tool apply failed: tool '{tool_key}' declared "
                    f"output structure '{normalized_structure}' but chart_renderable=True."
                )
            if normalized_mode != "non-visual":
                return (
                    f"Financial tool apply failed: tool '{tool_key}' declared "
                    f"output structure '{normalized_structure}' but output_mode='{normalized_mode}'."
                )
            if series_list and not accepts_empty_render_output:
                return (
                    f"Financial tool apply failed: tool '{tool_key}' declared "
                    f"non-renderable output structure '{normalized_structure}' but returned render series."
                )

        if normalized_structure in self._RENDERABLE_OUTPUT_STRUCTURES and not chart_renderable:
            if not accepts_empty_render_output:
                return (
                    f"Financial tool apply failed: tool '{tool_key}' declared renderable "
                    f"output structure '{normalized_structure}' but chart_renderable=False."
                )

        if chart_renderable and not self._series_list_has_resident_values(series_list):
            if not accepts_empty_render_output:
                return (
                    "Financial tool apply failed: renderable study returned no "
                    "resident-local render payload for the current chart slice."
                )

        if not chart_renderable and not accepts_empty_render_output and not series_list:
            return (
                "Financial tool apply failed: non-visual output was not declared "
                "as a valid empty-render result."
            )

        return None

    def _apply_series_list_to_workspace(
        self,
        *,
        output_mode: str,
        output_structure: str,
        series_list: List[Series],
        study_instance_id: Optional[str] = None,
        display_name: str = "",
    ) -> List[str]:
        render_keys: List[str] = []

        normalized_mode = str(output_mode).strip().lower()
        normalized_structure = self._normalize_output_structure(
            output_structure,
            chart_renderable=(normalized_mode != "non-visual"),
        )

        if normalized_mode == "non-visual":
            return render_keys

        if normalized_structure == "analysis-only":
            return render_keys

        if normalized_mode == "oscillator-pane" and study_instance_id:
            if hasattr(self._workspace, "apply_oscillator_study"):
                try:
                    self._workspace.apply_oscillator_study(
                        study_instance_id=study_instance_id,
                        title=str(display_name).strip(),
                        series_list=series_list,
                    )
                    render_keys.extend([series.key for series in series_list])
                    self._connect_oscillator_pane_signals_for_study(study_instance_id)
                    return render_keys
                except Exception as e:
                    self._on_error(
                        f"Managed oscillator study apply fallback engaged for "
                        f"{display_name or study_instance_id!r}: {e!r}"
                    )

        if normalized_mode == "overlay" and study_instance_id:
            if hasattr(self._workspace, "apply_overlay_study"):
                try:
                    self._workspace.apply_overlay_study(
                        study_instance_id=study_instance_id,
                        title=str(display_name).strip(),
                        series_list=series_list,
                    )
                    render_keys.extend([series.key for series in series_list])
                    return render_keys
                except Exception as e:
                    self._on_error(
                        f"Managed overlay study apply fallback engaged for "
                        f"{display_name or study_instance_id!r}: {e!r}"
                    )

        for series in series_list:
            if normalized_mode == "oscillator-pane":
                self._workspace.apply_oscillator_series(series)
            else:
                self._workspace.apply_overlay_series(series)
            render_keys.append(series.key)

        return render_keys

    def _register_applied_study(
        self,
        *,
        family: str,
        output_mode: str,
        supports_last_value: bool,
        tool_key: str,
        display_name: str,
        params: Dict[str, Any],
        render_keys: List[str],
        series_list: List[Series],
        instance_id: Optional[str] = None,
        source_kind: str = STUDY_SOURCE_TEMPORARY,
        input_bindings: Optional[Mapping[str, Any]] = None,
        input_binding_meta: Optional[Mapping[str, Any]] = None,
        required_inputs: Optional[Sequence[Any]] = None,
        saved_artifact_ref: Optional[Mapping[str, Any]] = None,
    ) -> ChartStudyInstance:
        last_value = None
        if supports_last_value:
            for series in series_list:
                if series.values:
                    candidate = series.values[-1]
                    try:
                        if candidate == candidate:
                            last_value = float(candidate)
                            break
                    except Exception:
                        continue

        study = ChartStudyInstance(
            instance_id=instance_id or uuid.uuid4().hex,
            dataset_id=self.dataset_key(),
            pane_target=self._pane_target_for_output_mode(output_mode),
            display_name=str(display_name).strip() or tool_key,
            computation=StudyComputationConfig(
                family=family,
                tool_key=tool_key,
                params=dict(params),
                source_kind=str(source_kind).strip().lower() or STUDY_SOURCE_TEMPORARY,
                input_bindings=dict(input_bindings or {}),
                input_binding_meta=dict(input_binding_meta or {}),
                required_inputs=tuple(required_inputs or ()),
                saved_artifact_ref=dict(saved_artifact_ref) if saved_artifact_ref is not None else None,
            ),
            runtime=ChartStudyRuntimeState(
                last_value=last_value,
                render_keys=list(render_keys),
            ),
        )
        self._study_registry.add(study)
        return study

    def _consume_edited_study_if_needed(
        self,
        *,
        next_pane_target: Optional[str],
        next_chart_renderable: bool,
        next_has_render_payload: bool,
    ) -> Optional[ChartStudyInstance]:
        """Return the study currently being edited and preserve its chart-local identity.

        Computation edits must route back through the controller, but they should
        not silently destroy the chart-local study instance when the apply
        succeeds. Reusing the existing instance_id keeps chart-local identity,
        style state, pane order, and oscillator pane ownership stable across an
        edit/reapply cycle.

        Old rendered payload is removed eagerly only when the replacement can no
        longer reuse the same managed workspace path safely, for example when the
        study becomes non-visual, returns no render payload, or changes pane
        target.
        """
        if not self._editing_study_instance_id:
            return None

        instance_id = self._editing_study_instance_id
        self._editing_study_instance_id = None

        existing = self._study_registry.get(instance_id)
        if existing is None:
            return None

        existing_pane_target = (
            str(existing.pane_target).strip().lower()
            if existing.pane_target is not None
            else None
        )
        resolved_next_pane_target = (
            str(next_pane_target).strip().lower()
            if next_pane_target is not None
            else None
        )

        if self._study_is_renderable(existing) and (
            not bool(next_chart_renderable)
            or not bool(next_has_render_payload)
            or existing_pane_target != resolved_next_pane_target
        ):
            self._remove_study_rendered_series(existing)

        return existing

    def _on_financial_tools_apply_succeeded(self, payload: dict) -> None:
        if not payload:
            self._editing_study_instance_id = None
            return

        family = self._normalize_study_family(str(payload.get("tool_type", "")))
        behavior = self._extract_behavior(payload)
        output = self._extract_output(payload)

        output_mode = str(behavior["output_mode"])
        chart_renderable = bool(behavior["chart_renderable"])
        supports_last_value = bool(behavior["supports_last_value"])
        output_structure = self._normalize_output_structure(
            str(output.get("structure", "")),
            chart_renderable=chart_renderable,
        )
        accepts_empty_render_output = bool(output["accepts_empty_render_output"])

        tool_key = str(payload.get("tool_key", "")).strip().lower()
        projection_key = str(payload.get("study_projection_key", "")).strip()
        display_name = str(payload.get("display_name", payload.get("tool_title", tool_key))).strip()
        params = dict(payload.get("params", {}) or {})
        source_kind = str(payload.get("source_kind", STUDY_SOURCE_TEMPORARY) or STUDY_SOURCE_TEMPORARY).strip()
        raw_input_bindings = payload.get("input_bindings", {}) or {}
        input_bindings = dict(raw_input_bindings) if isinstance(raw_input_bindings, Mapping) else {}
        raw_input_binding_meta = payload.get("input_binding_meta", {}) or {}
        input_binding_meta = (
            dict(raw_input_binding_meta)
            if isinstance(raw_input_binding_meta, Mapping)
            else {}
        )
        raw_required_inputs = payload.get("required_inputs", ()) or ()
        required_inputs = (
            tuple(raw_required_inputs)
            if isinstance(raw_required_inputs, (list, tuple))
            else ()
        )
        raw_saved_artifact_ref = payload.get("saved_artifact_ref")
        saved_artifact_ref = (
            dict(raw_saved_artifact_ref)
            if isinstance(raw_saved_artifact_ref, Mapping)
            else None
        )
        series_list = list(payload.get("series_list", []) or [])
        style_driver_series_list = list(payload.get("style_driver_series_list", []) or [])

        if not tool_key:
            self._editing_study_instance_id = None
            self._on_error("Financial tool apply failed: missing tool_key.")
            return

        validation_error = self._validate_apply_payload_contract(
            tool_key=tool_key,
            output_mode=output_mode,
            chart_renderable=chart_renderable,
            output_structure=output_structure,
            accepts_empty_render_output=accepts_empty_render_output,
            series_list=series_list,
        )
        if validation_error:
            self._editing_study_instance_id = None
            self._on_error(validation_error)
            return

        next_pane_target = self._pane_target_for_output_mode(output_mode)
        next_has_render_payload = bool(
            chart_renderable and self._series_list_has_resident_values(series_list)
        )
        edited_study = self._consume_edited_study_if_needed(
            next_pane_target=next_pane_target,
            next_chart_renderable=chart_renderable,
            next_has_render_payload=next_has_render_payload,
        )

        provisional_instance_id = (
            edited_study.instance_id if edited_study is not None else uuid.uuid4().hex
        )
        chart_local_series_list = self._chart_local_series_list_for_study(
            study_instance_id=provisional_instance_id,
            series_list=series_list,
        ) if chart_renderable else [
            Series(
                key=str(getattr(series, "key", "") or ""),
                title=str(getattr(series, "title", "") or ""),
                values=_coerce_values_list(getattr(series, "values", None)),
                style=getattr(series, "style", None),
            )
            for series in series_list
            if str(getattr(series, "key", "") or "").strip()
        ]
        chart_local_style_driver_series_list = self._chart_local_style_driver_series_list_for_study(
            study_instance_id=provisional_instance_id,
            style_driver_series_list=[
                Series(
                    key=str(getattr(series, "key", "") or ""),
                    title=str(getattr(series, "title", "") or ""),
                    values=_coerce_values_list(getattr(series, "values", None)),
                    style=getattr(series, "style", None),
                )
                for series in style_driver_series_list
                if str(getattr(series, "key", "") or "").strip()
            ],
        )
        render_keys: List[str] = []

        if chart_renderable and next_has_render_payload:
            render_keys = self._apply_series_list_to_workspace(
                output_mode=output_mode,
                output_structure=output_structure,
                series_list=chart_local_series_list,
                study_instance_id=provisional_instance_id,
                display_name=display_name,
            )

        study = self._register_applied_study(
            family=family,
            output_mode=output_mode,
            supports_last_value=supports_last_value,
            tool_key=tool_key,
            display_name=display_name,
            params=params,
            render_keys=render_keys,
            series_list=chart_local_series_list,
            instance_id=provisional_instance_id,
            source_kind=source_kind,
            input_bindings=input_bindings,
            input_binding_meta=input_binding_meta,
            required_inputs=required_inputs,
            saved_artifact_ref=saved_artifact_ref,
        )
        if edited_study is not None:
            study = study.with_style(edited_study.style).with_user_metadata(
                edited_study.user_metadata
            )
            self._study_registry.add(study)

        self._register_study_projection_key(
            instance_id=study.instance_id,
            projection_key=projection_key,
        )

        seeded_study = self._seed_study_style_from_series_and_defaults(
            study=study,
            series_list=chart_local_series_list,
        )
        seeded_study = self._seed_default_style_modules_for_study(seeded_study)

        # Persist resolved defaults and any seeded modules into chart-local study state.
        self._study_registry.add(seeded_study)

        if chart_renderable and next_has_render_payload:
            seeded_study = self._reapply_study_render_series(
                seeded_study,
                source_series_list=chart_local_series_list,
                source_style_driver_series_list=chart_local_style_driver_series_list,
            )

            # Persist any render-key resync or style-resolver expansion.
            self._study_registry.add(seeded_study)

        if output_mode == "oscillator-pane" and chart_renderable and next_has_render_payload:
            self._connect_oscillator_pane_signals_for_study(seeded_study.instance_id)
            self._apply_oscillator_visual_policy_for_study(seeded_study)

        self._on_error(
            f"Applied {seeded_study.computation.family} study '{seeded_study.display_name}' "
            f"to chart session (output_mode={output_mode}, structure={output_structure})."
        )
