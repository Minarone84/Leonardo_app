from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Literal

import pandas as pd

from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.naming import MarketId, canonicalize

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

BackfillItemStatus = Literal["created", "restored_corrupt", "skipped_existing", "failed"]

_DERIVED_STORAGE_FAMILIES = {"indicators", "oscillators", "constructs"}
_STORAGE_TO_ARTIFACT_FAMILY = {
    "ohlcv": "ohlcv",
    "indicators": "indicator",
    "oscillators": "oscillator",
    "constructs": "construct",
}
_NON_FEATURE_COLUMNS = {"ts_ms", "time", "timeframe"}


@dataclass(frozen=True)
class ArtifactMetadataBackfillItem:
    csv_path: Path
    metadata_path: Path
    status: BackfillItemStatus
    detail: str = ""


@dataclass(frozen=True)
class ArtifactMetadataBackfillReport:
    items: tuple[ArtifactMetadataBackfillItem, ...] = ()

    @property
    def scanned_csv_count(self) -> int:
        return len(self.items)

    @property
    def created_count(self) -> int:
        return self._count("created")

    @property
    def restored_corrupt_count(self) -> int:
        return self._count("restored_corrupt")

    @property
    def skipped_existing_count(self) -> int:
        return self._count("skipped_existing")

    @property
    def failed_count(self) -> int:
        return self._count("failed")

    @property
    def created_paths(self) -> tuple[Path, ...]:
        return tuple(item.metadata_path for item in self.items if item.status in {"created", "restored_corrupt"})

    @property
    def failed_paths(self) -> tuple[Path, ...]:
        return tuple(item.csv_path for item in self.items if item.status == "failed")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(item.detail for item in self.items if item.detail and item.status in {"failed", "restored_corrupt"})

    def _count(self, status: BackfillItemStatus) -> int:
        return sum(1 for item in self.items if item.status == status)


@dataclass(frozen=True)
class _CsvArtifactContext:
    market: MarketId
    storage_family: str
    artifact_family: str
    partition_dir: Path
    csv_path: Path


class ArtifactMetadataBackfill:
    """Restore missing or unreadable ``.meta.json`` sidecars for historical CSV artifacts.

    This utility is intentionally not part of the normal write path. It exists
    to restore metadata when sidecars are missing or unreadable. Valid existing
    sidecars are skipped by default and are never refreshed in-place; to rebuild
    valid metadata, delete the sidecar first and run the backfill.
    """

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    def backfill_market(
        self,
        market: MarketId,
        *,
        restore_corrupt: bool = True,
    ) -> ArtifactMetadataBackfillReport:
        partition = self._paths.partition_dir(market)
        return self._backfill_paths(self._iter_csv_paths_for_partition(partition), restore_corrupt=restore_corrupt)

    def backfill_all(self, *, restore_corrupt: bool = True) -> ArtifactMetadataBackfillReport:
        return self._backfill_paths(self._iter_all_csv_paths(), restore_corrupt=restore_corrupt)

    def restore_csv_metadata(
        self,
        csv_path: Path,
        *,
        restore_corrupt: bool = True,
    ) -> ArtifactMetadataBackfillItem:
        return self._restore_one(Path(csv_path), restore_corrupt=restore_corrupt)

    def _backfill_paths(self, paths: Iterable[Path], *, restore_corrupt: bool) -> ArtifactMetadataBackfillReport:
        items = tuple(self._restore_one(path, restore_corrupt=restore_corrupt) for path in sorted(set(Path(p) for p in paths)))
        return ArtifactMetadataBackfillReport(items=items)

    def _restore_one(self, csv_path: Path, *, restore_corrupt: bool) -> ArtifactMetadataBackfillItem:
        metadata_path = metadata_path_for_csv(csv_path)
        if metadata_path.exists():
            if self._is_valid_existing_metadata(metadata_path):
                return ArtifactMetadataBackfillItem(
                    csv_path=csv_path,
                    metadata_path=metadata_path,
                    status="skipped_existing",
                    detail="valid metadata sidecar already exists",
                )
            if not restore_corrupt:
                return ArtifactMetadataBackfillItem(
                    csv_path=csv_path,
                    metadata_path=metadata_path,
                    status="failed",
                    detail="metadata sidecar exists but is unreadable; restore_corrupt=False",
                )
            status: BackfillItemStatus = "restored_corrupt"
        else:
            status = "created"

        try:
            context = self._context_from_csv_path(csv_path)
            manifest = self._build_manifest(context)
            self._atomic_write_json(manifest.to_dict(), metadata_path)
            return ArtifactMetadataBackfillItem(
                csv_path=csv_path,
                metadata_path=metadata_path,
                status=status,
                detail="metadata restored from existing CSV artifact",
            )
        except Exception as exc:
            return ArtifactMetadataBackfillItem(
                csv_path=csv_path,
                metadata_path=metadata_path,
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )

    def _iter_csv_paths_for_partition(self, partition_dir: Path) -> Iterable[Path]:
        if not partition_dir.exists():
            return ()
        paths: list[Path] = []
        ohlcv = partition_dir / "ohlcv" / "candles.csv"
        if ohlcv.exists():
            paths.append(ohlcv)
        for family in sorted(_DERIVED_STORAGE_FAMILIES):
            family_dir = partition_dir / family
            if family_dir.exists():
                paths.extend(family_dir.glob("*.csv"))
        return tuple(paths)

    def _iter_all_csv_paths(self) -> Iterable[Path]:
        root = self._historical_root
        if not root.exists():
            return ()
        paths: list[Path] = []
        paths.extend(root.glob("*/*/*/*/ohlcv/candles.csv"))
        for family in sorted(_DERIVED_STORAGE_FAMILIES):
            paths.extend(root.glob(f"*/*/*/*/{family}/*.csv"))
        return tuple(paths)

    def _is_valid_existing_metadata(self, metadata_path: Path) -> bool:
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                HistoricalCsvArtifactManifest.from_dict(json.load(handle))
            return True
        except Exception:
            return False

    def _context_from_csv_path(self, csv_path: Path) -> _CsvArtifactContext:
        rel = Path(csv_path).resolve().relative_to(self._historical_root.resolve())
        parts = rel.parts
        if len(parts) < 6:
            raise ValueError(f"CSV path is not inside a historical market partition: {csv_path}")

        exchange, market_type, symbol, timeframe, storage_family = parts[:5]
        market = canonicalize(exchange, market_type, symbol, timeframe)
        if storage_family == "ohlcv":
            if len(parts) != 6 or parts[5] != "candles.csv":
                raise ValueError(f"Unsupported OHLCV CSV path: {csv_path}")
        elif storage_family in _DERIVED_STORAGE_FAMILIES:
            if len(parts) != 6 or not parts[5].lower().endswith(".csv"):
                raise ValueError(f"Unsupported derived artifact CSV path: {csv_path}")
        else:
            raise ValueError(f"Unsupported historical CSV storage family: {storage_family!r}")

        return _CsvArtifactContext(
            market=market,
            storage_family=storage_family,
            artifact_family=_STORAGE_TO_ARTIFACT_FAMILY[storage_family],
            partition_dir=self._paths.partition_dir(market),
            csv_path=Path(csv_path),
        )

    def _build_manifest(self, context: _CsvArtifactContext) -> HistoricalCsvArtifactManifest:
        dataframe = pd.read_csv(context.csv_path)
        if dataframe.empty:
            raise ValueError("Cannot restore metadata for an empty CSV artifact.")
        if "ts_ms" not in dataframe.columns:
            raise ValueError("Metadata restore requires a canonical 'ts_ms' column; CSV data was not modified.")

        dataframe = dataframe.copy()
        dataframe["ts_ms"] = pd.to_numeric(dataframe["ts_ms"], errors="raise").astype("int64")
        duplicate_ts = bool(dataframe["ts_ms"].duplicated().any())
        monotonic_ts = bool(dataframe["ts_ms"].is_monotonic_increasing)
        timeline_status = "verified" if (not duplicate_ts and monotonic_ts) else "error"
        validation_status = "ok" if timeline_status == "verified" else "error"
        validation_notes: list[str] = []
        if duplicate_ts:
            validation_notes.append("duplicate ts_ms values detected during metadata restore")
        if not monotonic_ts:
            validation_notes.append("ts_ms values are not monotonically increasing during metadata restore")

        stat = context.csv_path.stat()
        now_ms = int(time.time() * 1000)
        artifact_id = self._artifact_id_for_context(context)
        artifact_uid = build_artifact_uid(
            market=context.market,
            artifact_family=context.artifact_family,
            artifact_id=artifact_id,
        )

        return HistoricalCsvArtifactManifest(
            schema_version=ARTIFACT_METADATA_SCHEMA_VERSION,
            artifact_type=HISTORICAL_CSV_ARTIFACT_TYPE,
            identity=ArtifactIdentity(
                unique_id=new_unique_id(),
                artifact_family=context.artifact_family,  # type: ignore[arg-type]
                storage_family=context.storage_family,  # type: ignore[arg-type]
                artifact_id=artifact_id,
                artifact_uid=artifact_uid,
            ),
            market=context.market,
            files=metadata_files_from_csv(csv_path=context.csv_path, partition_dir=context.partition_dir),
            time_range=ArtifactTimeRange.from_ts_ms(
                first_ts_ms=int(dataframe["ts_ms"].min()),
                last_ts_ms=int(dataframe["ts_ms"].max()),
            ),
            shape=ArtifactShape(
                row_count=int(len(dataframe)),
                column_count=int(len(dataframe.columns)),
                columns=tuple(str(column) for column in dataframe.columns),
            ),
            columns=self._column_metadata_for_context(context=context, dataframe=dataframe),
            tool=None if context.artifact_family == "ohlcv" else self._tool_metadata_for_context(context=context),
            lineage=ArtifactLineage.from_timestamps(
                created_at_ms=int(stat.st_mtime * 1000),
                updated_at_ms=now_ms,
                created_by="leonardo_metadata_restore",
                source_artifacts=(),
            ),
            fingerprint=ArtifactFingerprint.from_file_stat(
                size_bytes=int(stat.st_size),
                modified_at_ms=int(stat.st_mtime * 1000),
            ),
            quality=ArtifactQuality(
                timeline_status=timeline_status,  # type: ignore[arg-type]
                monotonic_ts_ms=monotonic_ts,
                duplicate_ts_ms=duplicate_ts,
                validation_status=validation_status,  # type: ignore[arg-type]
                validation_notes=tuple(validation_notes),
                metadata=(
                    ArtifactMetadataEntry(
                        namespace="system",
                        key="restored_metadata",
                        value=True,
                        description="Metadata sidecar was restored from an existing CSV artifact.",
                    ),
                ),
            ),
            metadata=(
                ArtifactMetadataEntry(
                    namespace="system",
                    key="metadata_restore_only",
                    value=True,
                    description="This sidecar was created only to restore missing or unreadable metadata.",
                ),
            ),
        )

    def _artifact_id_for_context(self, context: _CsvArtifactContext) -> str:
        if context.artifact_family == "ohlcv":
            return build_artifact_id(artifact_family="ohlcv")
        tool_key, instance_key, _status = self._tool_identity_from_filename(context=context)
        return build_artifact_id(
            artifact_family=context.artifact_family,
            tool_key=tool_key,
            instance_key=instance_key,
        )

    def _tool_metadata_for_context(self, *, context: _CsvArtifactContext) -> ArtifactToolMetadata:
        tool_key, instance_key, tool_identity_status = self._tool_identity_from_filename(context=context)
        try:
            from leonardo.financial_tools.tool_contracts.registry import get_contract

            contract = get_contract(tool_key)
            tool = ArtifactToolMetadata.from_tool_contract(
                contract=contract,
                instance_key=instance_key,
                params={},
                params_status="unknown",
                bindings={},
                bindings_status="unknown",
            )
            return ArtifactToolMetadata(
                family=tool.family,
                tool_key=tool.tool_key,
                tool_title=tool.tool_title,
                description=tool.description,
                instance_key=tool.instance_key,
                tool_identity_status=tool_identity_status,  # type: ignore[arg-type]
                params=tool.params,
                params_status=tool.params_status,
                param_contracts=tool.param_contracts,
                bindings=tool.bindings,
                bindings_status=tool.bindings_status,
                data_inputs=tool.data_inputs,
                output=tool.output,
                output_signals=tool.output_signals,
                behavior=tool.behavior,
                construct_io=tool.construct_io,
                oscillator_visual=tool.oscillator_visual,
                contract_version=tool.contract_version,
                form_variant=tool.form_variant,
                metadata=tool.metadata,
            )
        except Exception:
            return ArtifactToolMetadata(
                family=context.artifact_family,  # type: ignore[arg-type]
                tool_key=tool_key,
                tool_title=tool_key,
                instance_key=instance_key,
                tool_identity_status=tool_identity_status,  # type: ignore[arg-type]
                params={},
                params_status="unknown",
                bindings={},
                bindings_status="unknown",
            )

    def _tool_identity_from_filename(self, *, context: _CsvArtifactContext) -> tuple[str, str, str]:
        stem = context.csv_path.stem.strip().lower()
        if context.storage_family in {"indicators", "oscillators"}:
            if "__" not in stem:
                return "unknown", stem or "unknown", "unknown"
            tool_key = stem.split("__", 1)[0].strip() or "unknown"
            return tool_key, stem, "inferred"

        if context.storage_family == "constructs":
            known_key = self._known_construct_key_from_stem(stem)
            if known_key is not None:
                return known_key, stem, "inferred"
            return "unknown", stem or "unknown", "unknown"

        return "unknown", stem or "unknown", "unknown"

    def _known_construct_key_from_stem(self, stem: str) -> str | None:
        try:
            from leonardo.financial_tools.tool_contracts.registry import tool_keys_by_family

            keys = sorted(tool_keys_by_family("construct"), key=len, reverse=True)
        except Exception:
            return None
        for key in keys:
            if stem == key or stem.startswith(f"{key}__"):
                return key
        return None

    def _column_metadata_for_context(
        self,
        *,
        context: _CsvArtifactContext,
        dataframe: pd.DataFrame,
    ) -> tuple[ArtifactColumnMetadata, ...]:
        if context.artifact_family == "ohlcv":
            return self._ohlcv_column_metadata(dataframe)

        tool_key, _instance_key, tool_identity_status = self._tool_identity_from_filename(context=context)
        signal_by_name = self._output_signal_metadata_by_name(tool_key=tool_key) if tool_identity_status != "unknown" else {}
        columns: list[ArtifactColumnMetadata] = []
        for column in dataframe.columns:
            name = str(column)
            dtype = str(dataframe[column].dtype)
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
                base = ArtifactColumnMetadata.from_output_signal(name=name, signal=signal)
                columns.append(
                    ArtifactColumnMetadata(
                        name=base.name,
                        role=base.role,
                        dtype=dtype,
                        selectable=base.selectable,
                        analysis_usable=base.analysis_usable,
                        renderable=base.renderable,
                        label=base.label,
                        description=base.description,
                        semantic_role=base.semantic_role,
                        value_type=base.value_type,
                        signal_type=base.signal_type,
                        default_visible=base.default_visible,
                        can_drive_style_rules=base.can_drive_style_rules,
                        metadata=base.metadata,
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
                    value_type="numeric" if pd.api.types.is_numeric_dtype(dataframe[column]) else "categorical",
                )
            )
        return tuple(columns)

    def _ohlcv_column_metadata(self, dataframe: pd.DataFrame) -> tuple[ArtifactColumnMetadata, ...]:
        meta_by_name = {
            "ts_ms": ArtifactColumnMetadata(
                name="ts_ms",
                role="primary_key",
                dtype=str(dataframe["ts_ms"].dtype),
                selectable=False,
                analysis_usable=True,
                renderable=False,
                label="Timestamp",
                semantic_role="primary_key",
                value_type="int",
            ),
            "open": ArtifactColumnMetadata(name="open", role="base", dtype=str(dataframe["open"].dtype), analysis_usable=True, renderable=True, label="Open", semantic_role="open"),
            "high": ArtifactColumnMetadata(name="high", role="base", dtype=str(dataframe["high"].dtype), analysis_usable=True, renderable=True, label="High", semantic_role="high"),
            "low": ArtifactColumnMetadata(name="low", role="base", dtype=str(dataframe["low"].dtype), analysis_usable=True, renderable=True, label="Low", semantic_role="low"),
            "close": ArtifactColumnMetadata(name="close", role="base", dtype=str(dataframe["close"].dtype), analysis_usable=True, renderable=True, label="Close", semantic_role="close"),
            "volume": ArtifactColumnMetadata(name="volume", role="base", dtype=str(dataframe["volume"].dtype), analysis_usable=True, renderable=False, label="Volume", semantic_role="volume"),
        }
        return tuple(meta_by_name[name] for name in dataframe.columns if name in meta_by_name)

    def _output_signal_metadata_by_name(self, *, tool_key: str) -> dict[str, object]:
        try:
            from leonardo.financial_tools.ft_naming import get_tool_signal_names
            from leonardo.financial_tools.tool_contracts.registry import get_contract

            contract = get_contract(tool_key)
            params = dict(contract.default_params())
            if contract.family == "construct" and contract.construct_io is not None:
                binding = contract.construct_io.input_binding
                if binding == "unary_source":
                    params.setdefault("source", "close")
                elif binding == "fast_slow":
                    params.setdefault("fast", "ema_9")
                    params.setdefault("slow", "ema_21")
                elif binding == "fast_mid_slow":
                    params.setdefault("fast", "ema_9")
                    params.setdefault("mid", "ema_13")
                    params.setdefault("slow", "ema_21")
                elif binding == "multi_source":
                    params.setdefault("source_columns", "close")
            resolver_family, _, resolver_key = contract.output.naming_resolver.partition(":")  # type: ignore[union-attr]
            names = tuple(get_tool_signal_names(resolver_family, resolver_key, **params))
            signals = tuple(getattr(contract.output, "signals", ()) or ())  # type: ignore[union-attr]
            if len(names) == len(signals):
                return {str(name): signal for name, signal in zip(names, signals)}
        except Exception:
            pass
        return {}

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="artifact_metadata_restore_",
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
