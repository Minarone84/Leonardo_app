from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

import pandas as pd

from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import HistoricalDatasetService


class HistoricalChartDataAccessMixin:
    def _get_historical_dataset_service(self) -> HistoricalDatasetService | None:
        """Resolve HistoricalDatasetService through explicit AppContext lookup."""
        if self._is_disposed:
            return None

        ctx = getattr(self._core, "context", None)
        if ctx is None:
            self.error.emit("CoreBridge context is unavailable.")
            return None

        get_service = getattr(ctx, "get_service", None)
        if callable(get_service):
            try:
                return get_service(SVC_HISTORICAL_DATASET, HistoricalDatasetService)
            except KeyError:
                self.error.emit("HistoricalDatasetService not registered in AppContext.")
                return None
            except TypeError as e:
                self.error.emit(f"HistoricalDatasetService type mismatch: {e!r}")
                return None

        services = getattr(ctx, "services", None)
        if isinstance(services, dict):
            svc = services.get(SVC_HISTORICAL_DATASET)
            if isinstance(svc, HistoricalDatasetService):
                return svc

        self.error.emit(
            "HistoricalDatasetService not available via explicit AppContext service lookup."
        )
        return None

    def _invoke_service_method(self, method: Any, *args) -> Any:
        result = method(*args)
        if inspect.isawaitable(result):
            fut = self._core.submit(result)
            return fut.result()
        return result

    def _call_required_service_method(
        self,
        svc: HistoricalDatasetService,
        method_name: str,
        *args,
    ) -> Any:
        """Call one explicit HistoricalDatasetService public API.

        The dataset service now owns the public timeline/columns/dataframe
        boundary. Controller data access should fail loudly when that boundary
        is missing instead of probing legacy method names or reading private
        service storage.
        """
        method = getattr(svc, method_name, None)
        if not callable(method):
            raise RuntimeError(
                "HistoricalDatasetService is missing required public API "
                f"'{method_name}'."
            )
        return self._invoke_service_method(method, *args)

    def _coerce_timeline_values(self, raw: Any) -> list[int]:
        if raw is None:
            return []

        values: Any = raw
        if isinstance(raw, pd.DataFrame):
            if "ts_ms" not in raw.columns:
                return []
            values = raw["ts_ms"].tolist()
        elif isinstance(raw, dict):
            values = raw.get("ts_ms", [])
        elif isinstance(raw, pd.Series):
            values = raw.tolist()
        elif hasattr(raw, "tolist") and not isinstance(raw, (str, bytes)):
            try:
                values = raw.tolist()
            except Exception:
                values = raw

        try:
            return [int(ts) for ts in list(values)]
        except Exception:
            return []

    def _extract_dataset_columns_from_service(
        self,
        svc: HistoricalDatasetService,
    ) -> Optional[Dict[str, Any]]:
        if self._dataset is None:
            return None

        columns_payload = self._call_required_service_method(
            svc,
            "get_dataset_columns",
            self._dataset,
        )
        if not isinstance(columns_payload, dict):
            raise RuntimeError(
                "HistoricalDatasetService.get_dataset_columns() did not return a column mapping."
            )

        return dict(columns_payload)

    def _populate_session_truth_from_service(self, svc: HistoricalDatasetService) -> None:
        if self._dataset is None:
            raise RuntimeError("No historical dataset is currently open.")

        timeline_ts_ms = self._coerce_timeline_values(
            self._call_required_service_method(
                svc,
                "get_timeline_ts_ms",
                self._dataset,
            )
        )

        if not timeline_ts_ms:
            raise RuntimeError(
                "HistoricalDatasetService.get_timeline_ts_ms() returned an empty canonical "
                "dataset timeline for the open chart session."
            )

        existing_count = self._session.dataset_count
        if existing_count is not None and int(existing_count) != len(timeline_ts_ms):
            raise ValueError(
                "HistoricalDatasetService timeline length does not match the open dataset "
                f"count ({len(timeline_ts_ms)} != {existing_count})."
            )

        self._session.set_timeline(timeline_ts_ms)

    def _normalize_full_dataset_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize a full historical dataframe before financial-tool computation.

        This method intentionally hardens the controller-side contract by
        enforcing:
        - required OHLCV columns
        - numeric coercion for core price/volume fields
        - stable timestamp ordering
        - duplicate timestamp rejection
        - canonical timeline alignment against the open chart session
        - normalized passthrough columns used by downstream tool families
        """
        if df.empty:
            return df

        required_cols = ["ts_ms", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Full candles dataset missing required columns: {missing}")

        out = df.copy()

        try:
            out["ts_ms"] = pd.to_numeric(out["ts_ms"], errors="raise").astype("int64")
            for column_name in ("open", "high", "low", "close", "volume"):
                out[column_name] = pd.to_numeric(out[column_name], errors="raise").astype("float64")
        except Exception as exc:
            raise ValueError(
                "Full candles dataset contains non-numeric values in required OHLCV columns."
            ) from exc

        out = out.sort_values("ts_ms", kind="stable").reset_index(drop=True)

        duplicated_mask = out["ts_ms"].duplicated(keep=False)
        if bool(duplicated_mask.any()):
            duplicate_preview = out.loc[duplicated_mask, "ts_ms"].head(10).tolist()
            raise ValueError(
                "Full candles dataset contains duplicate ts_ms values. "
                f"Example duplicates: {duplicate_preview}"
            )

        ts_diffs = out["ts_ms"].diff()
        if bool((ts_diffs.dropna() <= 0).any()):
            raise ValueError("Full candles dataset ts_ms must be strictly increasing.")

        normalized_timeline = out["ts_ms"].astype("int64").tolist()
        if self._session.dataset_count is not None and len(normalized_timeline) != int(self._session.dataset_count):
            raise ValueError(
                "Full candles dataset row count does not match the chart session dataset count. "
                f"({len(normalized_timeline)} != {self._session.dataset_count})"
            )

        if self._session.timeline_ts_ms:
            if normalized_timeline != self._session.timeline_ts_ms:
                raise ValueError(
                    "Full candles dataset timeline does not match the chart session canonical timeline."
                )
        else:
            # Safety net only. Refill logic is expected to rely on the timeline
            # primed from Core at dataset-open time, not on lazy apply/save paths.
            self._session.set_timeline(normalized_timeline)

        out["time"] = out["ts_ms"]
        out["timeframe"] = self._timeframe
        out["Volume"] = out["volume"]
        return out

    def _build_dataframe_from_service_columns(self, columns: Dict[str, Any]) -> pd.DataFrame:
        required_cols = ("ts_ms", "open", "high", "low", "close", "volume")
        missing = [column_name for column_name in required_cols if column_name not in columns]
        if missing:
            raise ValueError(
                "HistoricalDatasetService columns payload is missing required candles columns: "
                f"{missing}"
            )

        extracted: Dict[str, list[Any]] = {
            column_name: list(columns[column_name])
            for column_name in required_cols
        }
        lengths = {len(values) for values in extracted.values()}
        if len(lengths) > 1:
            raise ValueError(
                "HistoricalDatasetService columns payload contains mismatched column lengths."
            )

        return pd.DataFrame(extracted)

    def _load_full_dataset_dataframe(self) -> pd.DataFrame:
        """
        Load the full historical dataframe for compute/save operations.

        Preferred resolution order:
        1. controller session cache (canonical truth for this chart session)
        2. explicit HistoricalDatasetService.get_full_dataframe() public API
        3. explicit HistoricalDatasetService.get_dataset_columns() fallback only
           if a non-dataframe payload is returned

        The controller must not reconstruct candles.csv paths, probe legacy
        service method names, or reach into HistoricalDatasetService private
        storage.
        """
        if self._dataset is None:
            raise RuntimeError("No historical dataset is currently open.")

        cached_df = self._session.get_cached_full_dataset_dataframe()
        if cached_df is not None:
            return cached_df

        svc = self._get_historical_dataset_service()
        if svc is None:
            raise RuntimeError(
                "HistoricalDatasetService not available via explicit AppContext service lookup."
            )

        raw_df = self._call_required_service_method(
            svc,
            "get_full_dataframe",
            self._dataset,
        )

        dataframe: Optional[pd.DataFrame] = None
        if isinstance(raw_df, pd.DataFrame):
            dataframe = raw_df.copy(deep=True)
        elif isinstance(raw_df, dict):
            dataframe = self._build_dataframe_from_service_columns(raw_df)

        if dataframe is None:
            columns = self._extract_dataset_columns_from_service(svc)
            if columns is None:
                raise RuntimeError(
                    "HistoricalDatasetService did not expose a full-dataset dataframe or loaded "
                    "dataset columns for the open chart session."
                )

            dataframe = self._build_dataframe_from_service_columns(columns)

        normalized_df = self._normalize_full_dataset_dataframe(dataframe)
        self._session.cache_full_dataset_dataframe(normalized_df)

        cached = self._session.get_cached_full_dataset_dataframe()
        if cached is None:
            raise RuntimeError("Failed to cache the canonical full historical dataframe.")
        return cached
