from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict

import pandas as pd

from leonardo.financial_tools.ft_naming import build_construct_instance_key_from_params
from leonardo.financial_tools.ft_specs import ToolSpec, format_output_signals
from leonardo.gui.chart.model import Series as ChartSeries
from leonardo.gui.historical_chart.session import AppliedStudyProjection, StoredStudyLine


class HistoricalChartProjectionMixin:
    def _serialize_behavior_spec(self, spec: ToolSpec) -> Dict[str, Any]:
        return {
            "output_mode": spec.behavior.output_mode,
            "chart_renderable": bool(spec.behavior.chart_renderable),
            "supports_style": bool(spec.behavior.supports_style),
            "supports_pane_layout": bool(spec.behavior.supports_pane_layout),
            "supports_last_value": bool(spec.behavior.supports_last_value),
        }

    def _resolve_runtime_output_signals(self, *, spec: ToolSpec, params: Dict[str, Any], result) -> list[Any]:
        output_names = self._extract_runtime_output_names(result, spec=spec)
        effective_params = dict(getattr(result, "params", params) or params)

        try:
            resolved_signals = list(format_output_signals(spec, effective_params))
        except Exception:
            resolved_signals = list(spec.output.signals)

        if not output_names:
            return resolved_signals

        return [signal for signal in resolved_signals if signal.name in output_names]

    def _signal_can_drive_style_rules(self, signal: Any) -> bool:
        """Return whether a resolved output signal may drive chart-local style.

        The contract layer owns this metadata.  The boolean-analysis fallback is
        intentionally non-rendering: it only preserves resident-local state for
        downstream style modules when transitional spec objects do not yet expose
        ``can_drive_style_rules`` directly.
        """
        if bool(getattr(signal, "can_drive_style_rules", False)):
            return True

        value_type = str(getattr(signal, "value_type", "") or "").strip().lower()
        return bool(getattr(signal, "analysis_usable", False)) and value_type == "boolean"

    def _serialized_signal_can_drive_style_rules(self, signal: Any) -> bool:
        return self._signal_can_drive_style_rules(signal)

    def _signal_can_be_temporary_construct_source(self, signal: Any) -> bool:
        """Return whether a non-renderable output may remain chainable.

        Renderability and temporary-source eligibility are separate contracts:
        renderable outputs may become chart series, while non-renderable
        analysis-usable outputs may be retained as full-dataset source truth for
        later construct inputs.  This helper deliberately does not make any
        analysis-usable output renderable.
        """
        return bool(getattr(signal, "analysis_usable", False))

    def _serialized_signal_can_be_temporary_construct_source(self, signal: Any) -> bool:
        return self._signal_can_be_temporary_construct_source(signal)

    def _serialize_output_spec(self, spec: ToolSpec, *, result, params: Dict[str, Any]) -> Dict[str, Any]:
        output_names = self._extract_runtime_output_names(result, spec=spec)
        resolved_signals = self._resolve_runtime_output_signals(
            spec=spec,
            params=params,
            result=result,
        )
        return {
            "structure": spec.output.structure,
            "output_names": output_names,
            "accepts_empty_render_output": bool(spec.output.accepts_empty_render_output),
            "signals": [
                {
                    "name": signal.name,
                    "signal_type": signal.signal_type,
                    "renderable": signal.renderable,
                    "analysis_usable": signal.analysis_usable,
                    "default_visible": signal.default_visible,
                    "label": signal.label,
                    "description": signal.description,
                    "semantic_role": getattr(signal, "semantic_role", ""),
                    "value_type": getattr(signal, "value_type", ""),
                    "can_drive_style_rules": self._serialized_signal_can_drive_style_rules(signal),
                    "temporary_source_usable": (
                        (not bool(signal.renderable))
                        and self._serialized_signal_can_be_temporary_construct_source(signal)
                    ),
                }
                for signal in resolved_signals
            ],
        }

    def _build_param_signature(self, params: Dict[str, Any]) -> str:
        if not params:
            return "default"

        parts: list[str] = []
        for key in sorted(params.keys()):
            val = params[key]
            parts.append(f"{key}={val}")
        return ",".join(parts)

    def _build_instance_key(self, tool_key: str, params: Dict[str, Any]) -> str:
        """
        Build a deterministic construct instance key using the shared naming system.

        Canonical binding resolution is centralized in ft_naming.py so that
        controller persistence, UI preview, and save-target checks all use the
        same construct identity contract.
        """
        return build_construct_instance_key_from_params(
            construct_key=tool_key,
            params=params,
            exclude_param_keys={
                "source",
                "source_column",
                "source_columns",
                "left",
                "right",
                "fast",
                "mid",
                "slow",
            },
        )

    def _align_line_to_canonical_timeline(self, *, line_values: pd.Series, result) -> pd.Series:
        """Align one runtime study line to the canonical chart-session timeline."""
        canonical_timeline = list(self._session.timeline_ts_ms)
        if not canonical_timeline:
            return line_values.copy()

        canonical_index = pd.Index(canonical_timeline, name="ts_ms")
        series = line_values.copy()

        if len(series) == len(canonical_index):
            return pd.Series(series.to_numpy(copy=True), index=canonical_index)

        result_time = getattr(result, "time", None)
        result_timeline = self._coerce_timeline_values(result_time)
        if result_timeline and len(result_timeline) == len(series):
            aligned = pd.Series(
                series.to_numpy(copy=True),
                index=pd.Index(result_timeline, name="ts_ms"),
            )
            return aligned.reindex(canonical_index)

        try:
            series_index_values = [int(value) for value in series.index.tolist()]
        except Exception:
            series_index_values = []

        if series_index_values and len(series_index_values) == len(series):
            aligned = pd.Series(
                series.to_numpy(copy=True),
                index=pd.Index(series_index_values, name="ts_ms"),
            )
            return aligned.reindex(canonical_index)

        raise ValueError(
            "Runtime study output cannot be aligned to the canonical chart timeline."
        )

    def _build_projection_key(self, *, tool_key: str, params: Dict[str, Any]) -> str:
        """Build a deterministic controller-local study projection key."""
        return self._build_instance_key(tool_key, params)

    def _build_projected_series_list(
        self,
        *,
        study: AppliedStudyProjection,
    ) -> list[ChartSeries]:
        """Project a stored full-dataset study into the current resident window."""
        projected: list[ChartSeries] = []
        for line in study.full_lines:
            values = self._extract_resident_values(line.values)
            projected.append(
                ChartSeries(
                    key=self._build_series_key(
                        tool_key=study.tool_key,
                        params=study.params,
                        line_key=line.key,
                    ),
                    title=self._build_series_title(
                        tool_title=study.tool_title,
                        params=study.params,
                        line_title=line.title,
                    ),
                    values=values,
                )
            )
        return projected

    def _build_projected_style_driver_series_list(
        self,
        *,
        study: AppliedStudyProjection,
    ) -> list[ChartSeries]:
        """Project non-renderable style-driver state into the resident window.

        These series are not chart render series.  They are resident-local state
        payloads for panel-owned style modules such as UTC background regions.
        """
        projected: list[ChartSeries] = []
        for line in study.full_style_driver_lines:
            values = self._extract_resident_values_raw(line.values)
            projected.append(
                ChartSeries(
                    key=self._build_series_key(
                        tool_key=study.tool_key,
                        params=study.params,
                        line_key=line.key,
                    ),
                    title=self._build_series_title(
                        tool_title=study.tool_title,
                        params=study.params,
                        line_title=line.title,
                    ),
                    values=values,
                )
            )
        return projected

    def _store_applied_study_projection(
        self,
        *,
        projection_key: str,
        result,
        spec: ToolSpec,
        tool_type: str,
        tool_key: str,
        tool_title: str,
        effective_params: Dict[str, Any],
    ) -> AppliedStudyProjection:
        """Store full-dataset study truth and refresh its resident projection.

        Strict renderability rule
        -------------------------
        Only runtime outputs explicitly resolved as ``renderable=True`` may be
        retained as controller-owned chart-study lines.

        Non-renderable outputs that are explicitly style-driver-capable are
        retained separately as controller-owned state-driver truth.  They never
        become chart series; they are projected only so the panel can derive
        chart-local visual regions from the current resident slice.

        Non-renderable outputs that are analysis-usable are also retained as
        full-dataset temporary source truth for construct chaining.  They are
        not projected into renderer-facing payloads.
        """
        resolved_signals = self._resolve_runtime_output_signals(
            spec=spec,
            params=effective_params,
            result=result,
        )
        renderable_signal_names = {
            str(signal.name).strip()
            for signal in resolved_signals
            if bool(signal.renderable) and str(signal.name).strip()
        }
        style_driver_signal_names = {
            str(signal.name).strip()
            for signal in resolved_signals
            if (
                (not bool(signal.renderable))
                and self._signal_can_drive_style_rules(signal)
                and str(signal.name).strip()
            )
        }
        analysis_source_signal_names = {
            str(signal.name).strip()
            for signal in resolved_signals
            if (
                (not bool(signal.renderable))
                and self._signal_can_be_temporary_construct_source(signal)
                and str(signal.name).strip()
            )
        }
        signals_by_name = {
            str(signal.name).strip(): signal
            for signal in resolved_signals
            if str(signal.name).strip()
        }

        full_lines: list[StoredStudyLine] = []
        full_style_driver_lines: list[StoredStudyLine] = []
        full_analysis_source_lines: list[StoredStudyLine] = []
        for line in list(getattr(result, 'lines', []) or []):
            line_key = str(getattr(line, 'key', '') or '').strip()
            if not line_key:
                continue

            signal = signals_by_name.get(line_key)
            stored_line = StoredStudyLine(
                key=line_key,
                title=str(getattr(line, 'title', line_key) or line_key),
                values=self._align_line_to_canonical_timeline(
                    line_values=line.values,
                    result=result,
                ),
                renderable=bool(getattr(signal, "renderable", False)) if signal is not None else False,
                analysis_usable=bool(getattr(signal, "analysis_usable", False)) if signal is not None else False,
                can_drive_style_rules=(
                    self._signal_can_drive_style_rules(signal) if signal is not None else False
                ),
                signal_type=str(getattr(signal, "signal_type", "") or "") if signal is not None else "",
                semantic_role=str(getattr(signal, "semantic_role", "") or "") if signal is not None else "",
                value_type=str(getattr(signal, "value_type", "") or "") if signal is not None else "",
            )

            if line_key in renderable_signal_names:
                full_lines.append(stored_line)
            else:
                if line_key in style_driver_signal_names:
                    full_style_driver_lines.append(stored_line)
                if line_key in analysis_source_signal_names:
                    full_analysis_source_lines.append(stored_line)

        accepts_empty_render_output = bool(spec.output.accepts_empty_render_output)
        if bool(spec.behavior.chart_renderable) and not full_lines and not accepts_empty_render_output:
            raise ValueError(
                f"Tool '{tool_key}' did not produce any renderable outputs for chart apply. "
                "Only outputs declared renderable=True may become chart series; "
                "the tool spec must set accepts_empty_render_output=True only when "
                "an empty render payload is intentional."
            )

        study = AppliedStudyProjection(
            projection_key=projection_key,
            tool_type=tool_type,
            tool_key=tool_key,
            tool_title=tool_title,
            display_name=getattr(result, 'title', tool_title) or tool_title,
            params=dict(effective_params),
            behavior=self._serialize_behavior_spec(spec),
            output={
                **self._serialize_output_spec(spec, result=result, params=effective_params),
                "renderable_signal_names": sorted(renderable_signal_names),
                "style_driver_signal_names": sorted(style_driver_signal_names),
                "analysis_source_signal_names": sorted(analysis_source_signal_names),
            },
            full_lines=full_lines,
            full_style_driver_lines=full_style_driver_lines,
            full_analysis_source_lines=full_analysis_source_lines,
        )
        study.projected_series_list = self._build_projected_series_list(study=study)
        study.projected_style_driver_series_list = self._build_projected_style_driver_series_list(study=study)
        self._session.studies_by_projection_key[projection_key] = study
        return study

    def _refresh_all_study_projections(self) -> None:
        """Rebuild resident-local projections for all controller-owned studies."""
        for study in self._session.studies_by_projection_key.values():
            study.projected_series_list = self._build_projected_series_list(study=study)
            study.projected_style_driver_series_list = (
                self._build_projected_style_driver_series_list(study=study)
            )

    def list_available_construct_source_options(self, *, family_kind: str) -> list[Dict[str, Any]]:
        """Return current chart-session source options for construct input selection."""
        normalized_family = str(family_kind).strip().lower()
        if normalized_family not in {"indicator", "oscillator", "construct"}:
            return []

        options: list[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for study in self._session.studies_by_projection_key.values():
            if str(study.tool_type).strip().lower() != normalized_family:
                continue

            source_lines = list(study.full_lines) + list(
                getattr(study, "full_analysis_source_lines", []) or []
            )
            for line in source_lines:
                line_key = str(line.key).strip()
                if not line_key or line_key in {"time", "timeframe", "ts_ms", "vwap_color"}:
                    continue

                dedupe_key = (study.projection_key, line_key)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                display_name = (
                    f"Current Chart · {study.tool_title} "
                    f"[{self._build_param_signature(study.params)}]  ->  {line_key}"
                )
                options.append(
                    {
                        "family": normalized_family,
                        "source_kind": "temporary",
                        "series_key": line_key,
                        "display_name": display_name,
                        "instance_key": study.projection_key,
                        "artifact_path": "",
                        "tool_key": study.tool_key,
                        "tool_title": study.tool_title,
                        "column_name": line_key,
                        "projection_key": study.projection_key,
                        "renderable": bool(getattr(line, "renderable", False)),
                        "analysis_usable": bool(getattr(line, "analysis_usable", False)),
                        "temporary_source_role": (
                            "renderable" if bool(getattr(line, "renderable", False)) else "analysis"
                        ),
                    }
                )

        options.sort(key=lambda item: item["display_name"].lower())
        return options

    def get_projected_study_payloads(self) -> list[Dict[str, Any]]:
        """Return the current resident-local study payload snapshot.

        The controller owns full-study truth and rebuilds resident-local
        projections whenever the resident window changes. Downstream panel /
        workspace code may either pull this snapshot on demand or consume the
        `projected_studies_refreshed` signal emitted after slice application.
        """
        payloads: list[Dict[str, Any]] = []
        for study in self._session.studies_by_projection_key.values():
            payloads.append(
                {
                    'study_projection_key': study.projection_key,
                    'tool_type': study.tool_type,
                    'tool_key': study.tool_key,
                    'tool_title': study.tool_title,
                    'display_name': study.display_name,
                    'params': dict(study.params),
                    'series_list': list(study.projected_series_list),
                    'style_driver_series_list': list(study.projected_style_driver_series_list),
                    'behavior': dict(study.behavior),
                    'output': dict(study.output),
                }
            )
        return payloads

    def _build_series_key(self, *, tool_key: str, params: Dict[str, Any], line_key: str) -> str:
        param_sig = self._build_param_signature(params)
        return f"{tool_key}|{param_sig}|{line_key}"

    def _build_series_title(self, *, tool_title: str, params: Dict[str, Any], line_title: str) -> str:
        param_sig = self._build_param_signature(params)
        return f"{tool_title} [{param_sig}] · {line_title}"

    def _resident_bounds_for_full_series(self, full_len: int) -> tuple[int, int]:
        """
        Resolve safe resident-slice bounds against a full-series length.

        The chart session owns ``resident_base_index`` / ``resident_size``.
        This helper turns that controller-owned resident window state into a
        clamped slice interval that can safely trim a full series into
        resident-local render values.
        """
        if full_len <= 0 or self._session.resident_size <= 0:
            return (0, 0)

        start = max(0, int(self._session.resident_base_index))
        end = start + max(0, int(self._session.resident_size))

        start = min(start, full_len)
        end = min(max(start, end), full_len)
        return start, end

    def _extract_resident_values(self, series: pd.Series) -> list[float]:
        """
        Convert a full-dataset series into resident-local values.

        This is the core alignment fix for the chart pipeline.

        Before this update, full-length series were being passed into the chart
        layer while the renderers indexed them as resident-local arrays. That
        caused overlays/oscillators to desync from candles whenever the resident
        slice did not start at global index 0.

        After this update:
        - computation still runs on the full dataset
        - the controller trims each emitted line to the active resident slice
        - renderers receive only resident-local arrays, which matches their
          indexing model exactly
        """
        start, end = self._resident_bounds_for_full_series(len(series))
        if start == end:
            return []

        sliced = series.iloc[start:end]
        return [
            float(v) if pd.notna(v) else float("nan")
            for v in sliced.tolist()
        ]

    def _extract_resident_values_raw(self, series: pd.Series) -> list[Any]:
        """Convert a full-dataset non-renderable state series into resident-local values."""
        start, end = self._resident_bounds_for_full_series(len(series))
        if start == end:
            return []

        sliced = series.iloc[start:end]
        values: list[Any] = []
        for value in sliced.tolist():
            try:
                if pd.isna(value):
                    values.append(False)
                    continue
            except Exception:
                pass

            if hasattr(value, "item"):
                try:
                    value = value.item()
                except Exception:
                    pass

            values.append(value)
        return values

    def _build_apply_payload(
        self,
        result,
        *,
        spec: ToolSpec,
        tool_type: str,
        tool_key: str,
        tool_title: str,
        params: Dict[str, Any],
        source_payload: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        effective_params = dict(getattr(result, "params", params) or params)
        projection_key = self._build_projection_key(tool_key=tool_key, params=effective_params)
        study = self._store_applied_study_projection(
            projection_key=projection_key,
            result=result,
            spec=spec,
            tool_type=tool_type,
            tool_key=tool_key,
            tool_title=tool_title,
            effective_params=effective_params,
        )
        source_payload = source_payload or {}
        raw_input_bindings = source_payload.get("input_bindings", {}) or {}
        input_bindings = dict(raw_input_bindings) if isinstance(raw_input_bindings, Mapping) else {}
        raw_input_binding_meta = source_payload.get("input_binding_meta", {}) or {}
        input_binding_meta = (
            dict(raw_input_binding_meta)
            if isinstance(raw_input_binding_meta, Mapping)
            else {}
        )
        raw_required_inputs = source_payload.get("required_inputs", ()) or ()
        required_inputs = (
            list(raw_required_inputs)
            if isinstance(raw_required_inputs, (list, tuple))
            else []
        )
        raw_saved_artifact_ref = source_payload.get("saved_artifact_ref")
        saved_artifact_ref = (
            dict(raw_saved_artifact_ref)
            if isinstance(raw_saved_artifact_ref, Mapping)
            else None
        )
        source_kind = str(source_payload.get("source_kind", "temporary") or "temporary").strip().lower()

        return {
            "study_projection_key": projection_key,
            "tool_type": study.tool_type,
            "tool_key": study.tool_key,
            "tool_title": study.tool_title,
            "display_name": study.display_name,
            "params": dict(study.params),
            "series_list": list(study.projected_series_list),
            "style_driver_series_list": list(study.projected_style_driver_series_list),
            "behavior": dict(study.behavior),
            "output": dict(study.output),
            "input_bindings": input_bindings,
            "input_binding_meta": input_binding_meta,
            "required_inputs": required_inputs,
            "saved_artifact_ref": saved_artifact_ref,
            "source_kind": source_kind,
        }

    def _result_to_dataframe(self, result) -> pd.DataFrame:
        df = pd.DataFrame(index=result.index)

        if getattr(result, "time", None) is not None:
            df["time"] = result.time
        if getattr(result, "timeframe", None) is not None:
            df["timeframe"] = result.timeframe

        for line in result.lines:
            series = line.values.reindex(result.index)
            if pd.api.types.is_numeric_dtype(series):
                df[line.key] = series.astype("float32")
            else:
                df[line.key] = series

        if "time" not in df.columns:
            if "ts_ms" in df.columns:
                df["time"] = df["ts_ms"]
            else:
                df["time"] = list(range(len(df)))

        if "timeframe" not in df.columns:
            df["timeframe"] = self._timeframe

        return df.reset_index(drop=True)

    def _construct_result_to_dataframe_for_save(self, result) -> pd.DataFrame:
        """
        Convert a construct result into a persistable dataframe.

        Supported construct save shapes in this phase:
        1. renderable construct lines -> save through standard result dataframe path
        2. non-visual labeled row metadata -> save labeled_rows as a dataframe

        This keeps construct save semantics aligned with the construct family,
        where not every construct is analysis-only.
        """
        if getattr(result, "lines", None):
            return self._result_to_dataframe(result)

        metadata = dict(getattr(result, "metadata", {}) or {})
        labeled_rows = metadata.get("labeled_rows")

        if labeled_rows:
            result_df = pd.DataFrame(labeled_rows)
            if result_df.empty:
                raise ValueError("Construct labeled_rows is empty.")
            return result_df

        raise ValueError(
            "Construct produced neither renderable lines nor labeled_rows for save."
        )

    def _extract_runtime_output_names(self, result, *, spec: ToolSpec) -> list[str]:
        """
        Prefer runtime-emitted output names whenever runtime lines exist.

        This keeps output identity grounded in runtime truth rather than in any older
        spec-side formatting/template assumptions. For non-visual outputs, fall back
        to the spec metadata as a descriptive contract surface.
        """
        runtime_lines = list(getattr(result, "lines", []) or [])
        if runtime_lines:
            return [str(line.key) for line in runtime_lines]

        raw_names = list(getattr(spec.output, "output_names", []) or [])
        return [str(name) for name in raw_names]
