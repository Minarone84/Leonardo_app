from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, List, Literal, Optional

import pandas as pd

from leonardo.data.historical.paths import DatasetType, HistoricalPaths
from leonardo.data.naming import MarketId

from .artifact_metadata_contracts import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    HISTORICAL_CSV_ARTIFACT_TYPE,
    ArtifactColumnMetadata,
    ArtifactFiles,
    ArtifactFingerprint,
    ArtifactIdentity,
    ArtifactLineage,
    ArtifactMetadataEntry,
    ArtifactQuality,
    ArtifactShape,
    ArtifactTimeRange,
    ArtifactToolMetadata,
    HistoricalCsvArtifactManifest,
    metadata_files_from_csv,
)
from .artifact_metadata_naming import (
    build_artifact_id,
    build_artifact_uid,
    metadata_path_for_csv,
    new_unique_id,
)


DerivedKind = Literal["indicators", "oscillators", "constructs"]

_KIND_TO_ARTIFACT_FAMILY: dict[str, str] = {
    "indicators": "indicator",
    "oscillators": "oscillator",
    "constructs": "construct",
}

_NON_FEATURE_COLUMNS = {"ts_ms", "time", "timeframe"}


@dataclass(frozen=True)
class DerivedArtifactRef:
    """
    Metadata reference for one persisted derived artifact.
    """
    kind: DerivedKind
    tool_key: str
    instance_key: str
    filename: str
    path: Path


class DerivedCsvStore:

    _SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_dataframe(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
        df: pd.DataFrame,
        params: dict[str, Any] | None = None,
        params_status: str = "unknown",
        bindings: dict[str, Any] | None = None,
        bindings_status: str = "unknown",
        metadata: Iterable[ArtifactMetadataEntry] = (),
        source_artifacts: Iterable[Any] = (),
    ) -> Path:
        """Persist one derived financial-tool dataframe and its metadata sidecar.

        The CSV remains the tabular value artifact. The adjacent ``.meta.json``
        sidecar stores artifact identity, market identity, timestamp range,
        shape, tool metadata, lineage, fingerprint, quality, and extension
        metadata. Optional ``params`` and ``bindings`` are backwards-compatible:
        existing callers may omit them and the sidecar will honestly mark them
        as ``unknown``.
        """
        self._validate_kind(kind)
        safe_tool_key = self._sanitize_segment(tool_key)
        safe_instance_key = self._sanitize_segment(instance_key)

        if df is None or df.empty:
            raise ValueError("Cannot save an empty derived dataframe.")

        dataset_dir = self._dataset_dir(market=market, kind=kind)
        filename = self._build_filename(instance_key=safe_instance_key)
        target_path = dataset_dir / filename

        write_df = self._prepare_dataframe_for_save(df)
        self._atomic_write_csv(write_df, target_path)
        self._write_metadata_sidecar(
            market=market,
            kind=kind,
            tool_key=safe_tool_key,
            instance_key=safe_instance_key,
            df=write_df,
            target_path=target_path,
            params=dict(params or {}),
            params_status=str(params_status or "unknown"),
            bindings=dict(bindings or {}),
            bindings_status=str(bindings_status or "unknown"),
            metadata=tuple(metadata),
            source_artifacts=tuple(source_artifacts),
        )
        return target_path

    def load_dataframe(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> pd.DataFrame:
        self._validate_kind(kind)
        path = self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        )

        if not path.exists():
            raise FileNotFoundError(f"Derived artifact not found: {path}")

        return pd.read_csv(path)

    def resolve_path(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> Path:
        self._validate_kind(kind)
        safe_instance_key = self._sanitize_segment(instance_key)

        dataset_dir = self._dataset_dir(market=market, kind=kind)
        filename = self._build_filename(instance_key=safe_instance_key)
        return dataset_dir / filename

    def resolve_metadata_path(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> Path:
        return metadata_path_for_csv(
            self.resolve_path(
                market=market,
                kind=kind,
                tool_key=tool_key,
                instance_key=instance_key,
            )
        )

    def exists(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> bool:
        return self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        ).exists()

    def list_instances(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: Optional[str] = None,
    ) -> List[DerivedArtifactRef]:
        self._validate_kind(kind)
        dataset_dir = self._dataset_dir(market=market, kind=kind)
        if not dataset_dir.exists():
            return []

        safe_tool_filter = self._sanitize_segment(tool_key) if tool_key else None

        refs: List[DerivedArtifactRef] = []
        for path in sorted(dataset_dir.glob("*.csv")):
            metadata_ref = self._ref_from_metadata(path=path, kind=kind, market=market)
            if metadata_ref is not None:
                if safe_tool_filter and self._sanitize_segment(metadata_ref.tool_key) != safe_tool_filter:
                    continue
                refs.append(metadata_ref)
                continue

            if kind == "constructs":
                parsed = self._parse_construct_filename(path.name)
                if parsed is None:
                    continue

                parsed_tool_key, parsed_instance_key = parsed
                if safe_tool_filter and parsed_tool_key != safe_tool_filter:
                    continue

                refs.append(
                    DerivedArtifactRef(
                        kind=kind,
                        tool_key=parsed_tool_key,
                        instance_key=parsed_instance_key,
                        filename=path.name,
                        path=path,
                    )
                )
                continue

            parsed = self._parse_filename(path.name)
            if parsed is None:
                continue

            parsed_tool_key, parsed_instance_key = parsed
            if safe_tool_filter and parsed_tool_key != safe_tool_filter:
                continue

            refs.append(
                DerivedArtifactRef(
                    kind=kind,
                    tool_key=parsed_tool_key,
                    instance_key=parsed_instance_key,
                    filename=path.name,
                    path=path,
                )
            )

        return refs

    def load_metadata_manifest(self, path: Path) -> HistoricalCsvArtifactManifest | None:
        """Load an adjacent metadata sidecar for a CSV artifact if it is valid.

        Listing and GUI discovery prefer this metadata over filename parsing so
        source truth comes from the `.meta.json` sidecar. Missing or unreadable
        sidecars remain a legacy fallback path and do not block CSV discovery.
        """

        return self._load_existing_metadata(metadata_path_for_csv(Path(path)))

    def delete_instance(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> None:
        path = self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        )
        metadata_path = metadata_path_for_csv(path)
        if path.exists():
            path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dataset_dir(self, *, market: MarketId, kind: DerivedKind) -> Path:
        dataset_type = self._kind_to_dataset_type(kind)
        return self._paths.ensure_dataset_dir(market, dataset_type)

    def _kind_to_dataset_type(self, kind: DerivedKind) -> DatasetType:
        if kind == "indicators":
            return "indicators"
        if kind == "oscillators":
            return "oscillators"
        if kind == "constructs":
            return "constructs"
        raise ValueError(f"Unsupported derived kind: {kind}")

    def _artifact_family_for_kind(self, kind: DerivedKind) -> str:
        self._validate_kind(kind)
        return _KIND_TO_ARTIFACT_FAMILY[kind]

    def _validate_kind(self, kind: str) -> None:
        if kind not in {"indicators", "oscillators", "constructs"}:
            raise ValueError(f"Unsupported derived kind: {kind}")

    def _sanitize_segment(self, value: Any) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Empty path segment is not allowed.")

        safe = self._SAFE_SEGMENT_RE.sub("-", raw)
        safe = safe.strip(".-_")
        if not safe:
            raise ValueError(f"Could not sanitize path segment: {value!r}")

        return safe.lower()

    def _build_filename(self, *, instance_key: str) -> str:
        return f"{instance_key}.csv"

    def _parse_filename(self, filename: str) -> Optional[tuple[str, str]]:
        """
        Parse filenames of the form:
            <instance_key>.csv

        For indicators and oscillators, tool_key is derived from the
        instance_key prefix.
        """
        if not filename.lower().endswith(".csv"):
            return None

        stem = filename[:-4].strip()
        if "__" not in stem:
            return None

        parts = stem.split("__", 1)
        tool_key = parts[0]
        instance_key = stem

        if not tool_key or not instance_key:
            return None

        return tool_key, instance_key

    def _parse_construct_filename(self, filename: str) -> Optional[tuple[str, str]]:
        """
        Parse construct filenames of the form:
            <instance_key>.csv

        Important:
        - construct filenames are source-first in the current Leonardo policy
        - therefore the filename prefix is NOT a reliable tool key
        - we preserve the full stem as instance_key and return a neutral
          placeholder tool_key for UI/store reference purposes
        """
        if not filename.lower().endswith(".csv"):
            return None

        stem = filename[:-4].strip()
        if not stem:
            return None

        return "construct", stem

    def _ref_from_metadata(
        self,
        *,
        path: Path,
        kind: DerivedKind,
        market: MarketId,
    ) -> DerivedArtifactRef | None:
        manifest = self.load_metadata_manifest(path)
        if manifest is None:
            return None
        if manifest.identity.storage_family != kind:
            return None
        if manifest.market != market:
            return None
        if manifest.tool is None:
            return None

        tool_key = str(manifest.tool.tool_key).strip()
        instance_key = str(manifest.tool.instance_key or Path(path).stem).strip()
        if not tool_key or not instance_key:
            return None

        return DerivedArtifactRef(
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
            filename=Path(path).name,
            path=Path(path),
        )

    def _prepare_dataframe_for_save(self, df: pd.DataFrame) -> pd.DataFrame:
        write_df = df.copy()
        if "ts_ms" not in write_df.columns:
            if "time" not in write_df.columns:
                raise ValueError("Derived artifact dataframe must contain 'ts_ms' or timestamp-like 'time'.")
            write_df.insert(0, "ts_ms", self._coerce_time_to_ts_ms(write_df["time"]))
        else:
            write_df["ts_ms"] = pd.to_numeric(write_df["ts_ms"], errors="raise").astype("int64")
            if list(write_df.columns).index("ts_ms") != 0:
                ordered_columns = ["ts_ms", *[column for column in write_df.columns if column != "ts_ms"]]
                write_df = write_df[ordered_columns]

        self._validate_ts_ms(write_df)
        return write_df

    def _coerce_time_to_ts_ms(self, values: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(values, errors="coerce")
        if bool(numeric.notna().all()):
            max_abs = float(numeric.abs().max()) if len(numeric) else 0.0
            if max_abs >= 10_000_000_000:
                return numeric.round().astype("int64")
            if max_abs >= 10_000_000:
                return (numeric * 1000.0).round().astype("int64")
            raise ValueError(
                "Derived artifact 'time' column does not look like Unix seconds or milliseconds; "
                "cannot derive ts_ms safely."
            )

        parsed = pd.to_datetime(values, utc=True, errors="raise")
        return (parsed.astype("int64") // 1_000_000).astype("int64")

    def _validate_ts_ms(self, df: pd.DataFrame) -> None:
        if "ts_ms" not in df.columns:
            raise ValueError("Derived artifact dataframe must contain ts_ms.")
        if df["ts_ms"].isna().any():
            raise ValueError("Derived artifact dataframe contains null ts_ms values.")
        if df["ts_ms"].duplicated().any():
            raise ValueError("Derived artifact dataframe contains duplicate ts_ms values.")
        if not df["ts_ms"].is_monotonic_increasing:
            raise ValueError("Derived artifact dataframe ts_ms values must be monotonically increasing.")

    def _write_metadata_sidecar(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
        df: pd.DataFrame,
        target_path: Path,
        params: dict[str, Any],
        params_status: str,
        bindings: dict[str, Any],
        bindings_status: str,
        metadata: tuple[ArtifactMetadataEntry, ...],
        source_artifacts: tuple[Any, ...],
    ) -> None:
        metadata_path = metadata_path_for_csv(target_path)
        existing = self._load_existing_metadata(metadata_path)
        now_ms = int(time.time() * 1000)
        stat = target_path.stat()
        modified_at_ms = int(stat.st_mtime * 1000)
        artifact_family = self._artifact_family_for_kind(kind)
        artifact_id = build_artifact_id(
            artifact_family=artifact_family,
            tool_key=tool_key,
            instance_key=instance_key,
        )
        artifact_uid = build_artifact_uid(
            market=market,
            artifact_family=artifact_family,
            artifact_id=artifact_id,
        )
        unique_id = new_unique_id() if existing is None else existing.identity.unique_id
        created_at_ms = now_ms if existing is None else existing.lineage.created_at_ms

        manifest = HistoricalCsvArtifactManifest(
            schema_version=ARTIFACT_METADATA_SCHEMA_VERSION,
            artifact_type=HISTORICAL_CSV_ARTIFACT_TYPE,
            identity=ArtifactIdentity(
                unique_id=unique_id,
                artifact_family=artifact_family,  # type: ignore[arg-type]
                storage_family=kind,  # type: ignore[arg-type]
                artifact_id=artifact_id,
                artifact_uid=artifact_uid,
            ),
            market=market,
            files=self._artifact_files_for_path(market=market, target_path=target_path),
            time_range=ArtifactTimeRange.from_ts_ms(
                first_ts_ms=int(df["ts_ms"].iloc[0]),
                last_ts_ms=int(df["ts_ms"].iloc[-1]),
            ),
            shape=ArtifactShape(
                row_count=int(len(df)),
                column_count=int(len(df.columns)),
                columns=tuple(str(column) for column in df.columns),
            ),
            columns=self._build_column_metadata(df=df, tool_key=tool_key, params=params),
            tool=self._build_tool_metadata(
                artifact_family=artifact_family,
                tool_key=tool_key,
                instance_key=instance_key,
                params=params,
                params_status=params_status,
                bindings=bindings,
                bindings_status=bindings_status,
            ),
            lineage=ArtifactLineage.from_timestamps(
                created_at_ms=created_at_ms,
                updated_at_ms=now_ms,
                source_artifacts=source_artifacts,
            ),
            fingerprint=ArtifactFingerprint.from_file_stat(
                size_bytes=int(stat.st_size),
                modified_at_ms=modified_at_ms,
            ),
            quality=ArtifactQuality(
                timeline_status="verified",
                monotonic_ts_ms=True,
                duplicate_ts_ms=False,
                validation_status="not_validated",
            ),
            metadata=metadata,
        )
        self._atomic_write_json(manifest.to_dict(), metadata_path)

    def _artifact_files_for_path(self, *, market: MarketId, target_path: Path) -> ArtifactFiles:
        partition_dir = self._paths.partition_dir(market)
        return metadata_files_from_csv(csv_path=target_path, partition_dir=partition_dir)

    def _load_existing_metadata(self, metadata_path: Path) -> HistoricalCsvArtifactManifest | None:
        if not metadata_path.exists():
            return None
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                return HistoricalCsvArtifactManifest.from_dict(json.load(handle))
        except Exception:
            return None

    def _build_tool_metadata(
        self,
        *,
        artifact_family: str,
        tool_key: str,
        instance_key: str,
        params: dict[str, Any],
        params_status: str,
        bindings: dict[str, Any],
        bindings_status: str,
    ) -> ArtifactToolMetadata:
        try:
            from leonardo.financial_tools.tool_contracts.registry import get_contract

            contract = get_contract(tool_key)
            return ArtifactToolMetadata.from_tool_contract(
                contract=contract,
                instance_key=instance_key,
                params=params,
                params_status=params_status,  # type: ignore[arg-type]
                bindings=bindings,
                bindings_status=bindings_status,  # type: ignore[arg-type]
            )
        except Exception:
            return ArtifactToolMetadata(
                family=artifact_family,  # type: ignore[arg-type]
                tool_key=tool_key,
                tool_title=tool_key,
                instance_key=instance_key,
                tool_identity_status="unknown",
                params=params,
                params_status=params_status,  # type: ignore[arg-type]
                bindings=bindings,
                bindings_status=bindings_status,  # type: ignore[arg-type]
            )

    def _build_column_metadata(
        self,
        *,
        df: pd.DataFrame,
        tool_key: str,
        params: dict[str, Any],
    ) -> tuple[ArtifactColumnMetadata, ...]:
        signal_by_name = self._output_signal_metadata_by_name(tool_key=tool_key, params=params)
        columns: list[ArtifactColumnMetadata] = []
        for column in df.columns:
            name = str(column)
            dtype = str(df[column].dtype)
            if name == "ts_ms":
                columns.append(
                    ArtifactColumnMetadata(
                        name=name,
                        role="primary_key",
                        dtype=dtype,
                        selectable=False,
                        analysis_usable=True,
                        renderable=False,
                        label="Timestamp",
                        semantic_role="primary_key",
                        value_type="int",
                    )
                )
                continue
            if name in {"time", "timeframe"}:
                columns.append(
                    ArtifactColumnMetadata(
                        name=name,
                        role="utility",
                        dtype=dtype,
                        selectable=False,
                        analysis_usable=False,
                        renderable=False,
                        label=name,
                        semantic_role="metadata",
                        value_type="categorical" if name == "timeframe" else "numeric",
                    )
                )
                continue

            signal = signal_by_name.get(name)
            if signal is not None:
                column_meta = ArtifactColumnMetadata.from_output_signal(name=name, signal=signal)
                columns.append(
                    ArtifactColumnMetadata(
                        name=column_meta.name,
                        role=column_meta.role,
                        dtype=dtype,
                        selectable=column_meta.selectable,
                        analysis_usable=column_meta.analysis_usable,
                        renderable=column_meta.renderable,
                        label=column_meta.label,
                        description=column_meta.description,
                        semantic_role=column_meta.semantic_role,
                        value_type=column_meta.value_type,
                        signal_type=column_meta.signal_type,
                        default_visible=column_meta.default_visible,
                        can_drive_style_rules=column_meta.can_drive_style_rules,
                        metadata=column_meta.metadata,
                    )
                )
                continue

            columns.append(
                ArtifactColumnMetadata(
                    name=name,
                    role="feature",
                    dtype=dtype,
                    selectable=True,
                    analysis_usable=True,
                    renderable=None,
                    label=name,
                    semantic_role="primary",
                    value_type="numeric" if pd.api.types.is_numeric_dtype(df[column]) else "categorical",
                )
            )
        return tuple(columns)

    def _output_signal_metadata_by_name(self, *, tool_key: str, params: dict[str, Any]) -> dict[str, object]:
        try:
            from leonardo.financial_tools.ft_specs import format_output_signals, get_tool_spec

            spec = get_tool_spec(tool_key)
            effective_params = dict(getattr(spec, "default_params", {}) or {})
            effective_params.update(params or {})
            return {str(signal.name): signal for signal in format_output_signals(spec, effective_params)}
        except Exception:
            pass

        try:
            from leonardo.financial_tools.ft_naming import get_tool_signal_names
            from leonardo.financial_tools.tool_contracts.registry import get_contract

            contract = get_contract(tool_key)
            effective_params = dict(contract.default_params())
            effective_params.update(params or {})
            resolver_family, _, resolver_key = contract.output.naming_resolver.partition(":")  # type: ignore[union-attr]
            names = tuple(get_tool_signal_names(resolver_family, resolver_key, **effective_params))
            signals = tuple(getattr(contract.output, "signals", ()) or ())  # type: ignore[union-attr]
            if len(names) == len(signals):
                return {str(name): signal for name, signal in zip(names, signals)}
        except Exception:
            pass
        return {}

    def _atomic_write_csv(self, df: pd.DataFrame, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="derived_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                df.to_csv(tmp, index=False)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

        os.replace(tmp_path, target_path)

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="derived_metadata_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        os.replace(tmp_path, target_path)
