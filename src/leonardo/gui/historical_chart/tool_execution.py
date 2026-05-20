from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import canonicalize
from leonardo.financial_tools.execution_context import ToolExecutionContext
from leonardo.financial_tools.constructs.constructs import Constructs, ConstructRequest
from leonardo.financial_tools.ft_specs import ToolSpec, get_tool_spec
from leonardo.financial_tools.indicators.indicators import Indicators, IndicatorRequest
from leonardo.financial_tools.oscillators.oscillators import Oscillators, OscillatorRequest


class HistoricalChartToolExecutionMixin:
    def _historical_root(self) -> Path:
        """Return the active historical data root from the Core runtime config."""
        ctx = getattr(self._core, "context", None)
        config = getattr(ctx, "config", None)
        runtime = getattr(config, "runtime", None)
        data_dir = getattr(runtime, "data_dir", "data")
        return Path(data_dir) / "historical"

    def _utc_peak_trough_columns_for_purpose(
        self,
        params: Dict[str, Any],
        *,
        purpose: str,
    ) -> tuple[str, str]:
        """Return one UTC Peaks & Troughs dependency pair.

        Trend and range are independent dependency requests.  The controller may
        load the saved Peaks & Troughs artifact once, but each detector resolves
        its own selected fractal so future changes to one detector do not
        silently change the other.
        """
        if purpose == "trend":
            window = int(params.get("trend_fractal_window", params.get("fractal_window", 5)))
            peak_column = str(
                params.get("trend_peak_column")
                or params.get("peak_column")
                or f"peak_fractal_{window}"
            ).strip()
            trough_column = str(
                params.get("trend_trough_column")
                or params.get("trough_column")
                or f"trough_fractal_{window}"
            ).strip()
        elif purpose == "range":
            window = int(params.get("range_fractal_window", 3))
            peak_column = str(params.get("range_peak_column") or f"peak_fractal_{window}").strip()
            trough_column = str(params.get("range_trough_column") or f"trough_fractal_{window}").strip()
        else:
            raise ValueError("UTC dependency purpose must be 'trend' or 'range'.")

        if not peak_column or not trough_column:
            raise ValueError(f"UTC {purpose} Peaks & Troughs dependency columns must be non-empty.")
        return peak_column, trough_column

    def _utc_peak_trough_columns(self, params: Dict[str, Any]) -> tuple[str, ...]:
        """Return all unique Peaks & Troughs columns required by UTC."""
        columns: list[str] = []
        for purpose in ("trend", "range"):
            for column_name in self._utc_peak_trough_columns_for_purpose(params, purpose=purpose):
                if column_name not in columns:
                    columns.append(column_name)
        return tuple(columns)

    def _utc_dependency_role_name(self, *, params: Dict[str, Any], column_name: str) -> str:
        trend_columns = set(self._utc_peak_trough_columns_for_purpose(params, purpose="trend"))
        range_columns = set(self._utc_peak_trough_columns_for_purpose(params, purpose="range"))
        if column_name in trend_columns and column_name in range_columns:
            purpose = "trend_range"
        elif column_name in trend_columns:
            purpose = "trend"
        elif column_name in range_columns:
            purpose = "range"
        else:
            purpose = "dependency"
        return f"universal_trend_classifier.{purpose}.{column_name}"

    def _load_saved_peaks_troughs_dataframe(self) -> pd.DataFrame:
        """Load the saved Peaks & Troughs artifact for the active historical dataset.

        File/path ownership stays in the controller/store layer. UTC receives the
        selected columns already aligned in its working dataframe and does not
        read derived artifacts directly.
        """
        market = canonicalize(
            exchange=self._exchange,
            market_type=self._market_type,
            symbol=self._symbol,
            timeframe=self._timeframe,
        )
        store = DerivedCsvStore(historical_root=self._historical_root())
        refs = store.list_instances(
            market=market,
            kind="indicators",
            tool_key="peaks_troughs",
        )
        if not refs:
            raise FileNotFoundError(
                "Universal Trend Classifier requires a saved Peaks & Troughs indicator "
                "for this dataset/timeframe before it can run."
            )

        selected_ref = None
        try:
            expected_instance_key = self._build_instance_key("peaks_troughs", {})
        except Exception:
            expected_instance_key = ""

        if expected_instance_key:
            for ref in refs:
                if str(getattr(ref, "instance_key", "")).strip() == expected_instance_key:
                    selected_ref = ref
                    break

        if selected_ref is None:
            if len(refs) == 1:
                selected_ref = refs[0]
            else:
                available = ", ".join(str(getattr(ref, "instance_key", "")) for ref in refs)
                raise ValueError(
                    "Multiple saved Peaks & Troughs artifacts were found for this dataset/timeframe, "
                    "but no canonical default instance could be selected. "
                    f"Available instances: {available}"
                )

        raw_path = str(getattr(selected_ref, "path", "")).strip()
        if not raw_path:
            raise FileNotFoundError("Saved Peaks & Troughs artifact reference has no path.")

        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Saved Peaks & Troughs artifact not found: {path}")

        src_df = pd.read_csv(path)
        if src_df.empty:
            raise ValueError(f"Saved Peaks & Troughs artifact is empty: {path}")
        return src_df

    def _inject_utc_peak_trough_sources(self, *, df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        """Inject saved Peaks & Troughs columns required by UTC.

        Trend and range dependencies are resolved independently so either
        detector can change fractal selection without changing the other.  The
        saved Peaks & Troughs artifact may still be loaded once, and duplicate
        columns are merged only once.

        Alignment is delegated to the existing deterministic source-merge helper,
        which requires a shared ``ts_ms`` or ``time`` key and rejects duplicate
        join-key values. Positional alignment remains forbidden.
        """
        required_columns = self._utc_peak_trough_columns(params)
        columns_to_inject = [column_name for column_name in required_columns if column_name not in df.columns]
        if not columns_to_inject:
            return df

        src_df = self._load_saved_peaks_troughs_dataframe()
        missing = [name for name in columns_to_inject if name not in src_df.columns]
        if missing:
            raise ValueError(
                "Saved Peaks & Troughs artifact does not contain the columns required by UTC: "
                f"{missing}"
            )

        out = df
        for column_name in columns_to_inject:
            if column_name in out.columns:
                continue
            out = self._merge_source_dataframe_column(
                df=out,
                src_df=src_df,
                column_name=column_name,
                role_name=self._utc_dependency_role_name(params=params, column_name=column_name),
                source_label="saved Peaks & Troughs artifact",
            )
        return out

    def apply_financial_tool(self, payload: Dict[str, Any]) -> None:
        """
        Apply a financial tool to the current historical chart.

        Canonical study contract for this phase
        ---------------------------------------
        - computation uses the FULL historical dataset for the open chart session
        - it does NOT persist anything to disk
        - viewport / resident-slice mechanics remain visualization-only concerns

        Construct note for this phase
        -----------------------------
        - the payload contract is behavior-aware
        - construct family dispatch is live for dummy and saved-source constructs

        Critical rendering contract
        ---------------------------
        The chart renderer must only receive resident-local values.

        Therefore this method computes on the full dataframe, but
        `_build_apply_payload()` trims every emitted renderable line to the
        current resident slice before it becomes a ChartSeries.
        """
        if self._is_disposed:
            return

        if not payload:
            self.error.emit("Empty financial tool payload.")
            return

        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key
        params = payload.get("params", {}) or {}
        context = ToolExecutionContext(environment="historical")

        if not tool_type or not tool_key:
            self.error.emit("Invalid financial tool payload: missing tool_type or tool_key.")
            return

        try:
            spec = self._resolve_tool_spec(tool_key=tool_key)
        except Exception as e:
            self.error.emit(f"Invalid financial tool payload: failed to resolve spec: {e!r}")
            return

        try:
            dcd_df = self._load_full_dataset_dataframe()
        except Exception as e:
            self.error.emit(f"Failed to load full historical dataset for apply: {e!r}")
            return

        if dcd_df.empty:
            self.error.emit("Cannot apply financial tool: full historical dataset is empty.")
            return

        if tool_type == "construct":
            try:
                dcd_df = self._resolve_construct_sources_into_dataframe(
                    df=dcd_df,
                    payload=payload,
                )
            except Exception as e:
                self.error.emit(f"Failed to resolve construct sources: {e!r}")
                return

        if tool_type == "indicator" and tool_key == "universal_trend_classifier":
            try:
                dcd_df = self._inject_utc_peak_trough_sources(
                    df=dcd_df,
                    params=dict(params),
                )
            except Exception as e:
                self.error.emit(f"Failed to resolve UTC Peaks & Troughs dependency: {e!r}")
                return

        try:
            if tool_type == "indicator":
                result = Indicators.calculate(
                    IndicatorRequest(name=tool_key, data=dcd_df, params=params, context=context)
                )
                self.apply_succeeded.emit(
                    self._build_apply_payload(
                        result,
                        spec=spec,
                        tool_type=tool_type,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        params=params,
                    )
                )
                return

            if tool_type == "oscillator":
                result = Oscillators.calculate(
                    OscillatorRequest(name=tool_key, data=dcd_df, params=params, context=context)
                )
                self.apply_succeeded.emit(
                    self._build_apply_payload(
                        result,
                        spec=spec,
                        tool_type=tool_type,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        params=params,
                    )
                )
                return

            if tool_type == "construct":
                result = Constructs.calculate(
                    ConstructRequest(name=tool_key, data=dcd_df, params=dict(params), context=context)
                )
                self.apply_succeeded.emit(
                    self._build_apply_payload(
                        result,
                        spec=spec,
                        tool_type=tool_type,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        params=params,
                    )
                )
                return

            self.error.emit(f"Unsupported financial tool type: {tool_type}")
        except Exception as e:
            self.error.emit(f"apply_financial_tool failed: {e!r}")


    def _lineage_source_artifacts_from_payload(self, payload: Dict[str, Any]) -> tuple[dict[str, str], ...]:
        """Return saved source-artifact lineage from structured construct bindings.

        The chart controller does not own artifact metadata semantics, but it can
        pass explicit source references it already received from the UI into the
        persistence boundary. Temporary chart-session sources have no durable CSV
        path and are therefore intentionally omitted from this lineage list.
        """
        input_binding_meta = payload.get("input_binding_meta", {}) or {}
        if not isinstance(input_binding_meta, dict):
            return ()

        sources: list[dict[str, str]] = []

        def add_source(meta: Dict[str, Any]) -> None:
            path = str(meta.get("artifact_path", "")).strip()
            if not path:
                return
            sources.append(
                {
                    "source_kind": str(meta.get("source_kind", "saved")).strip(),
                    "family": str(meta.get("family", "")).strip(),
                    "tool_key": str(meta.get("tool_key", "")).strip(),
                    "instance_key": str(meta.get("instance_key", "")).strip(),
                    "column_name": str(meta.get("column_name", "")).strip(),
                    "path": path,
                }
            )

        for value in input_binding_meta.values():
            if isinstance(value, dict):
                add_source(value)
                continue
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        add_source(entry)

        return tuple(sources)

    def _save_metadata_payload(self, payload: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """Build explicit metadata arguments for DerivedCsvStore.save_dataframe()."""
        input_bindings = payload.get("input_bindings", {}) or {}
        if not isinstance(input_bindings, dict):
            input_bindings = {}

        return {
            "params": dict(params),
            "params_status": "explicit",
            "bindings": dict(input_bindings),
            "bindings_status": "explicit" if input_bindings else "unknown",
            "source_artifacts": self._lineage_source_artifacts_from_payload(payload),
        }

    def save_financial_tool(self, payload: Dict[str, Any]) -> None:
        """
        Persist a financial tool result computed on the FULL canonical historical dataset.

        Save intentionally shares the same computation scope as Apply:
        - Apply computes full-dataset results and trims them for render payloads.
        - Save computes full-dataset results and persists them unchanged.
        - Viewport / resident-slice mechanics remain visualization-only concerns.
        """
        if self._is_disposed:
            return

        if not payload:
            self.error.emit("Empty financial tool payload.")
            return

        tool_type = str(payload.get("tool_type", "")).strip().lower()
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key
        params = payload.get("params", {}) or {}
        context = ToolExecutionContext(environment="historical")

        if not tool_type or not tool_key:
            self.error.emit("Invalid save payload: missing tool_type or tool_key.")
            return

        save_meta: Dict[str, Any] = {
            "tool_type": tool_type,
            "tool_title": tool_title,
            "tool_key": tool_key,
            "exchange": self._exchange,
            "market_type": self._market_type,
            "symbol": self._symbol,
            "timeframe": self._timeframe,
            "params": dict(params),
            "saved_path": "",
            "error": "",
        }

        try:
            market = canonicalize(
                exchange=self._exchange,
                market_type=self._market_type,
                symbol=self._symbol,
                timeframe=self._timeframe,
            )
        except Exception as e:
            save_meta["error"] = f"Failed to canonicalize market for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            full_df = self._load_full_dataset_dataframe()
        except Exception as e:
            save_meta["error"] = f"Failed to load full historical dataset for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        if full_df.empty:
            save_meta["error"] = "Cannot save financial tool: full historical dataset is empty."
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        if tool_type == "construct":
            try:
                full_df = self._resolve_construct_sources_into_dataframe(
                    df=full_df,
                    payload=payload,
                )
            except Exception as e:
                save_meta["error"] = f"Failed to resolve construct sources: {e!r}"
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return

        if tool_type == "indicator" and tool_key == "universal_trend_classifier":
            try:
                full_df = self._inject_utc_peak_trough_sources(
                    df=full_df,
                    params=dict(params),
                )
            except Exception as e:
                save_meta["error"] = f"Failed to resolve UTC Peaks & Troughs dependency: {e!r}"
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return

        save_metadata = self._save_metadata_payload(payload, dict(params))
        save_meta["params_status"] = save_metadata["params_status"]
        save_meta["bindings_status"] = save_metadata["bindings_status"]

        if tool_type == "construct":
            try:
                result = Constructs.calculate(
                    ConstructRequest(name=tool_key, data=full_df, params=dict(params), context=context)
                )
                kind = "constructs"
            except Exception as e:
                save_meta["error"] = f"Failed to compute construct for save: {e!r}"
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return

            try:
                result_df = self._construct_result_to_dataframe_for_save(result)
                instance_key = self._build_instance_key(tool_key, params)
                historical_root = self._historical_root()
                store = DerivedCsvStore(historical_root=historical_root)

                target_path = store.resolve_path(
                    market=market,
                    kind=kind,  # type: ignore[arg-type]
                    tool_key=tool_key,
                    instance_key=instance_key,
                )

                save_meta["historical_root"] = str(historical_root)
                save_meta["instance_key"] = instance_key
                save_meta["resolved_target_path"] = str(target_path)
                save_meta["resolved_target_parent"] = str(target_path.parent)
                save_meta["resolved_target_parent_exists_before_save"] = bool(target_path.parent.exists())

                path = store.save_dataframe(
                    market=market,
                    kind=kind,  # type: ignore[arg-type]
                    tool_key=tool_key,
                    instance_key=instance_key,
                    df=result_df,
                    **save_metadata,
                )
                save_meta["saved_path"] = str(path)

            except Exception as e:
                diagnostic_parts = [
                    f"Failed to persist construct: {e!r}",
                    f"historical_root={save_meta.get('historical_root', '<unset>')}",
                    f"instance_key={save_meta.get('instance_key', '<unset>')}",
                    f"resolved_target_path={save_meta.get('resolved_target_path', '<unset>')}",
                    f"resolved_target_parent={save_meta.get('resolved_target_parent', '<unset>')}",
                    "resolved_target_parent_exists_before_save="
                    f"{save_meta.get('resolved_target_parent_exists_before_save', '<unset>')}",
                ]
                save_meta["error"] = " | ".join(diagnostic_parts)
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return

            self.save_succeeded.emit(save_meta)
            self.error.emit(f"Saved construct {tool_key} to {path}")
            return

        try:
            if tool_type == "indicator":
                result = Indicators.calculate(
                    IndicatorRequest(name=tool_key, data=full_df, params=params, context=context)
                )
                kind = "indicators"
            elif tool_type == "oscillator":
                result = Oscillators.calculate(
                    OscillatorRequest(name=tool_key, data=full_df, params=params, context=context)
                )
                kind = "oscillators"
            else:
                save_meta["error"] = f"Unsupported save tool type: {tool_type}"
                self.save_failed.emit(save_meta)
                self.error.emit(save_meta["error"])
                return
        except Exception as e:
            save_meta["error"] = f"Failed to compute financial tool for save: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        try:
            result_df = self._result_to_dataframe(result)
            instance_key = self._build_instance_key(tool_key, params)
            historical_root = self._historical_root()
            store = DerivedCsvStore(historical_root=historical_root)

            path = store.save_dataframe(
                market=market,
                kind=kind,  # type: ignore[arg-type]
                tool_key=tool_key,
                instance_key=instance_key,
                df=result_df,
                **save_metadata,
            )
            save_meta["saved_path"] = str(path)
        except Exception as e:
            save_meta["error"] = f"Failed to persist financial tool: {e!r}"
            self.save_failed.emit(save_meta)
            self.error.emit(save_meta["error"])
            return

        self.save_succeeded.emit(save_meta)
        self.error.emit(f"Saved {tool_key} to {path}")

    def _resolve_tool_spec(self, *, tool_key: str) -> ToolSpec:
        return get_tool_spec(tool_key)
