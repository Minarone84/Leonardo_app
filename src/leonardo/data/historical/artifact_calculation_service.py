from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Mapping

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.artifact_result_conversion import result_to_save_dataframe
from leonardo.data.historical.dataset_service import require_ohlcv_dataset_loadable
from leonardo.data.historical.derived_store_csv import DerivedCsvStore, DerivedKind
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
    build_source_ohlcv_provenance_snapshot,
)
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.historical.utc_dependency_sources import prepare_utc_peak_trough_dependencies
from leonardo.data.naming import MarketId, canonicalize
from leonardo.financial_tools.constructs.constructs import Constructs, ConstructRequest
from leonardo.financial_tools.execution_context import ToolExecutionContext
from leonardo.financial_tools.ft_naming import build_construct_instance_key_from_params
from leonardo.financial_tools.indicators.indicators import Indicators, IndicatorRequest
from leonardo.financial_tools.oscillators.oscillators import Oscillators, OscillatorRequest


ToolType = Literal["indicator", "oscillator", "construct"]


@dataclass(frozen=True)
class ArtifactCalculationResult:
    """Result returned by the save-only artifact calculation service."""

    tool_type: ToolType
    tool_key: str
    tool_title: str
    instance_key: str
    market: MarketId
    saved_path: Path
    metadata_path: Path
    row_count: int
    column_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "instance_key": self.instance_key,
            "exchange": self.market.exchange,
            "market_type": self.market.market_type,
            "symbol": self.market.symbol,
            "timeframe": self.market.timeframe,
            "saved_path": str(self.saved_path),
            "metadata_path": str(self.metadata_path),
            "row_count": int(self.row_count),
            "column_count": int(self.column_count),
        }


class ArtifactCalculationService:
    """Save-only financial-tool artifact calculator for historical datasets.

    This service is intentionally independent from the historical chart
    controller. It owns full-dataset artifact calculation for Data Manager-style
    workflows and persists through ``DerivedCsvStore``. It does not apply
    studies, create chart-local state, touch panes, or emit renderer payloads.
    """

    _EXCLUDED_BINDING_PARAM_KEYS = {
        "source",
        "source_column",
        "source_columns",
        "left",
        "right",
        "fast",
        "mid",
        "slow",
    }

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)
        self._store = DerivedCsvStore(historical_root=self._historical_root)

    def calculate_and_save(self, payload: Mapping[str, Any]) -> ArtifactCalculationResult:
        """Calculate one financial-tool artifact and persist it.

        ``payload`` is the same structured save intent emitted by the financial
        tool form. Parameters and construct bindings supplied by the UI are
        passed through to the metadata sidecar as explicit calculation intent.
        """
        if not payload:
            raise ValueError("Cannot calculate artifact from an empty payload.")

        tool_type = self._normalize_tool_type(payload.get("tool_type"))
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key
        params = dict(payload.get("params", {}) or {})
        input_bindings = dict(payload.get("input_bindings", {}) or {})

        if not tool_key:
            raise ValueError("Artifact calculation payload is missing tool_key.")

        market = self._market_from_payload(payload)
        full_df = self._load_full_dataset_dataframe(market)
        source_ohlcv_snapshot = build_source_ohlcv_provenance_snapshot(
            historical_root=self._historical_root,
            market=market,
        )

        if tool_type == "construct":
            full_df = self._resolve_construct_sources_into_dataframe(
                df=full_df,
                payload=payload,
            )

        if tool_type == "indicator" and tool_key == "universal_trend_classifier":
            full_df = self._inject_utc_peak_trough_sources(
                df=full_df,
                market=market,
                params=dict(params),
            )

        result = self._calculate_result(
            tool_type=tool_type,
            tool_key=tool_key,
            df=full_df,
            params=params,
        )
        result_df = result_to_save_dataframe(result, default_timeframe=market.timeframe)
        instance_key = self._build_instance_key(tool_key=tool_key, params=params)
        kind = self._kind_from_tool_type(tool_type)

        saved_path = self._store.save_dataframe(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
            df=result_df,
            params=params,
            params_status="explicit",
            bindings=input_bindings,
            bindings_status="explicit" if input_bindings else "unknown",
            metadata=(self._source_ohlcv_metadata_entry(source_ohlcv_snapshot),),
            source_artifacts=tuple(self._lineage_source_artifacts(payload)),
        )

        saved_df = pd.read_csv(saved_path)
        return ArtifactCalculationResult(
            tool_type=tool_type,
            tool_key=tool_key,
            tool_title=tool_title,
            instance_key=instance_key,
            market=market,
            saved_path=saved_path,
            metadata_path=metadata_path_for_csv(saved_path),
            row_count=int(len(saved_df)),
            column_count=int(len(saved_df.columns)),
        )

    def _normalize_tool_type(self, raw_tool_type: Any) -> ToolType:
        value = str(raw_tool_type or "").strip().lower()
        if value not in {"indicator", "oscillator", "construct"}:
            raise ValueError(f"Unsupported artifact calculation tool_type: {raw_tool_type!r}")
        return value  # type: ignore[return-value]

    def _market_from_payload(self, payload: Mapping[str, Any]) -> MarketId:
        try:
            return canonicalize(
                exchange=str(payload.get("exchange", "")),
                market_type=str(payload.get("market_type", "")),
                symbol=str(payload.get("symbol", "")),
                timeframe=str(payload.get("timeframe", "")),
            )
        except Exception as exc:
            raise ValueError(f"Invalid artifact calculation market identity: {exc!r}") from exc

    def _load_full_dataset_dataframe(self, market: MarketId) -> pd.DataFrame:
        ohlcv_path = CsvOHLCVStore().file_path(self._paths.ohlcv_dir(market))
        require_ohlcv_dataset_loadable(
            historical_root=self._historical_root,
            market=market,
            context="Data Manager artifact calculation",
        )
        if not ohlcv_path.exists():
            raise FileNotFoundError(f"OHLCV candles file not found: {ohlcv_path}")

        df = pd.read_csv(ohlcv_path)
        if df.empty:
            raise ValueError(f"OHLCV candles file is empty: {ohlcv_path}")
        return self._normalize_full_dataset_dataframe(df=df, market=market)

    def _source_ohlcv_metadata_entry(
        self,
        snapshot: dict[str, object],
    ) -> ArtifactMetadataEntry:
        return ArtifactMetadataEntry(
            namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
            key=SOURCE_OHLCV_PROVENANCE_KEY,
            value=snapshot,
            label="Source OHLCV provenance",
            description="Accepted OHLCV source snapshot used for this calculation.",
            tags=("source_ohlcv", "lineage"),
            searchable=False,
            identity_affecting=False,
        )

    def _normalize_full_dataset_dataframe(self, *, df: pd.DataFrame, market: MarketId) -> pd.DataFrame:
        required_cols = ["ts_ms", "open", "high", "low", "close", "volume"]
        missing = [column_name for column_name in required_cols if column_name not in df.columns]
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

        if bool((out["ts_ms"].diff().dropna() <= 0).any()):
            raise ValueError("Full candles dataset ts_ms must be strictly increasing.")

        out["time"] = out["ts_ms"]
        out["timeframe"] = market.timeframe
        out["Volume"] = out["volume"]
        return out

    def _calculate_result(
        self,
        *,
        tool_type: ToolType,
        tool_key: str,
        df: pd.DataFrame,
        params: Mapping[str, Any],
    ) -> Any:
        context = ToolExecutionContext(environment="historical")
        if tool_type == "indicator":
            return Indicators.calculate(
                IndicatorRequest(name=tool_key, data=df, params=params, context=context)
            )
        if tool_type == "oscillator":
            return Oscillators.calculate(
                OscillatorRequest(name=tool_key, data=df, params=params, context=context)
            )
        if tool_type == "construct":
            return Constructs.calculate(
                ConstructRequest(name=tool_key, data=df, params=dict(params), context=context)
            )
        raise ValueError(f"Unsupported artifact calculation tool_type: {tool_type}")

    def _resolve_construct_sources_into_dataframe(
        self,
        *,
        df: pd.DataFrame,
        payload: Mapping[str, Any],
    ) -> pd.DataFrame:
        input_binding_meta = payload.get("input_binding_meta", {}) or {}
        if not isinstance(input_binding_meta, dict) or not input_binding_meta:
            return df

        out = df.copy()
        for role_name, role_meta in input_binding_meta.items():
            if isinstance(role_meta, dict):
                out = self._inject_source_meta_into_dataframe(
                    df=out,
                    source_meta=role_meta,
                    role_name=str(role_name),
                )
                continue

            if isinstance(role_meta, list):
                for idx, entry in enumerate(role_meta):
                    if not isinstance(entry, dict):
                        raise ValueError(
                            f"Invalid source metadata entry for role '{role_name}[{idx}]'."
                        )
                    out = self._inject_source_meta_into_dataframe(
                        df=out,
                        source_meta=entry,
                        role_name=f"{role_name}[{idx}]",
                    )
                continue

            raise ValueError(f"Unsupported source metadata payload for role '{role_name}'.")

        return out

    def _inject_source_meta_into_dataframe(
        self,
        *,
        df: pd.DataFrame,
        source_meta: Mapping[str, Any],
        role_name: str,
    ) -> pd.DataFrame:
        family = str(source_meta.get("family", "default")).strip().lower()
        source_kind = str(source_meta.get("source_kind", "saved")).strip().lower()
        column_name = str(source_meta.get("column_name", "")).strip()
        artifact_path = str(source_meta.get("artifact_path", "")).strip()

        if family == "default":
            return df

        if source_kind == "temporary":
            raise ValueError(
                f"Temporary chart-session sources are not available in the Data Manager save-only workflow "
                f"for role '{role_name}'."
            )

        if not column_name:
            raise ValueError(f"Invalid source metadata for role '{role_name}'.")

        if column_name in df.columns:
            return df

        if not artifact_path:
            raise ValueError(f"Invalid source metadata for role '{role_name}'.")

        path = Path(artifact_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Source artifact not found for role '{role_name}': {path}")

        src_df = pd.read_csv(path)
        if src_df.empty:
            raise ValueError(f"Source artifact is empty for role '{role_name}': {path}")

        if column_name not in src_df.columns:
            raise ValueError(f"Column '{column_name}' not found in artifact for role '{role_name}': {path}")

        return self._merge_source_dataframe_column(
            df=df,
            src_df=src_df,
            column_name=column_name,
            role_name=role_name,
            source_label=str(path),
        )

    def _merge_source_dataframe_column(
        self,
        *,
        df: pd.DataFrame,
        src_df: pd.DataFrame,
        column_name: str,
        role_name: str,
        source_label: str,
    ) -> pd.DataFrame:
        out = df.copy()

        join_key = None
        if "ts_ms" in out.columns and "ts_ms" in src_df.columns:
            join_key = "ts_ms"
        elif "time" in out.columns and "time" in src_df.columns:
            join_key = "time"

        if join_key is None:
            raise ValueError(
                f"Source '{column_name}' for role '{role_name}' cannot be aligned safely. "
                "A shared join key ('ts_ms' or 'time') is required."
            )

        if bool(src_df[join_key].duplicated(keep=False).any()):
            raise ValueError(
                f"Source data for role '{role_name}' contains duplicate join-key values "
                f"for '{join_key}', so deterministic alignment is impossible."
            )

        merged = out.merge(
            src_df[[join_key, column_name]],
            on=join_key,
            how="left",
            sort=False,
            validate="many_to_one",
        )

        if column_name not in merged.columns:
            raise ValueError(
                f"Failed to merge source '{column_name}' for role '{role_name}' from '{source_label}'."
            )

        out[column_name] = merged[column_name].values
        return out

    def _inject_utc_peak_trough_sources(
        self,
        *,
        df: pd.DataFrame,
        market: MarketId,
        params: Mapping[str, Any],
    ) -> pd.DataFrame:
        return prepare_utc_peak_trough_dependencies(
            df=df,
            historical_root=self._historical_root,
            market=market,
            params=params,
            expected_instance_key=self._expected_peaks_troughs_instance_key(),
        )

    def _expected_peaks_troughs_instance_key(self) -> str:
        try:
            return self._build_instance_key(tool_key="peaks_troughs", params={})
        except Exception:
            return ""

    def _build_instance_key(self, *, tool_key: str, params: Mapping[str, Any]) -> str:
        return build_construct_instance_key_from_params(
            construct_key=tool_key,
            params=dict(params),
            exclude_param_keys=self._EXCLUDED_BINDING_PARAM_KEYS,
        )

    def _kind_from_tool_type(self, tool_type: ToolType) -> DerivedKind:
        if tool_type == "indicator":
            return "indicators"
        if tool_type == "oscillator":
            return "oscillators"
        if tool_type == "construct":
            return "constructs"
        raise ValueError(f"Unsupported artifact calculation tool_type: {tool_type}")

    def _lineage_source_artifacts(self, payload: Mapping[str, Any]) -> Iterable[dict[str, str]]:
        input_binding_meta = payload.get("input_binding_meta", {}) or {}
        if not isinstance(input_binding_meta, dict):
            return ()

        sources: list[dict[str, str]] = []

        def add_source(meta: Mapping[str, Any]) -> None:
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
            elif isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict):
                        add_source(entry)
        return tuple(sources)
