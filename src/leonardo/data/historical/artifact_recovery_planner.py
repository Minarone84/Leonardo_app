from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import (
    HistoricalCsvArtifactManifest,
)
from leonardo.data.historical.artifact_metadata_naming import (
    artifact_family_for_storage_family,
    metadata_path_for_csv,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe
from leonardo.data.historical.derived_store_csv import DerivedKind, DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.naming import MarketId
from leonardo.financial_tools.ft_naming import build_construct_instance_key_from_params


ArtifactRecoveryStatus = Literal[
    "up_to_date",
    "missing",
    "stale",
    "freshness_unknown",
    "blocked",
]

ToolType = Literal["indicator", "oscillator", "construct"]

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


@dataclass(frozen=True)
class ArtifactRecoveryItemReport:
    """Read-only recovery status for one recipe snapshot.

    The report intentionally describes planner state only. It does not execute
    recipes, repair metadata, write artifacts, rebuild Analysis Databases, or
    own financial-tool calculation semantics.
    """

    recipe_id: str
    recipe_index: int
    display_name: str
    tool_type: ToolType
    tool_key: str
    expected_kind: DerivedKind
    expected_instance_key: str
    expected_csv_path: Path
    expected_metadata_path: Path
    expected_output_names: tuple[str, ...]
    status: ArtifactRecoveryStatus
    can_recalculate: bool
    existing_csv: bool
    existing_metadata: bool
    stale_reasons: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def needs_recovery(self) -> bool:
        return self.status in {"missing", "stale", "freshness_unknown", "blocked"}

    @property
    def actionable(self) -> bool:
        return self.needs_recovery and self.can_recalculate

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_index": int(self.recipe_index),
            "display_name": self.display_name,
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "expected_kind": self.expected_kind,
            "expected_instance_key": self.expected_instance_key,
            "expected_csv_path": str(self.expected_csv_path),
            "expected_metadata_path": str(self.expected_metadata_path),
            "expected_output_names": list(self.expected_output_names),
            "status": self.status,
            "can_recalculate": bool(self.can_recalculate),
            "needs_recovery": self.needs_recovery,
            "actionable": self.actionable,
            "existing_csv": bool(self.existing_csv),
            "existing_metadata": bool(self.existing_metadata),
            "stale_reasons": list(self.stale_reasons),
            "blocked_reasons": list(self.blocked_reasons),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ArtifactRecoveryReport:
    """Read-only recovery plan for one recipe collection."""

    market: MarketId
    collection_id: str
    collection_display_name: str
    requested_recipe_ids: tuple[str, ...]
    items: tuple[ArtifactRecoveryItemReport, ...]

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def up_to_date_count(self) -> int:
        return self._count_status("up_to_date")

    @property
    def missing_count(self) -> int:
        return self._count_status("missing")

    @property
    def stale_count(self) -> int:
        return self._count_status("stale")

    @property
    def freshness_unknown_count(self) -> int:
        return self._count_status("freshness_unknown")

    @property
    def blocked_count(self) -> int:
        return self._count_status("blocked")

    @property
    def recalculable_count(self) -> int:
        return sum(1 for item in self.items if item.can_recalculate)

    @property
    def actionable_count(self) -> int:
        return sum(1 for item in self.items if item.actionable)

    @property
    def actionable_recipe_ids(self) -> tuple[str, ...]:
        return tuple(item.recipe_id for item in self.items if item.actionable)

    @property
    def success(self) -> bool:
        return all(item.status == "up_to_date" for item in self.items)

    def to_dict(self) -> dict[str, object]:
        return {
            "market": {
                "exchange": self.market.exchange,
                "market_type": self.market.market_type,
                "symbol": self.market.symbol,
                "timeframe": self.market.timeframe,
            },
            "collection_id": self.collection_id,
            "collection_display_name": self.collection_display_name,
            "requested_recipe_ids": list(self.requested_recipe_ids),
            "total_count": self.total_count,
            "up_to_date_count": self.up_to_date_count,
            "missing_count": self.missing_count,
            "stale_count": self.stale_count,
            "freshness_unknown_count": self.freshness_unknown_count,
            "blocked_count": self.blocked_count,
            "recalculable_count": self.recalculable_count,
            "actionable_count": self.actionable_count,
            "actionable_recipe_ids": list(self.actionable_recipe_ids),
            "success": self.success,
            "items": [item.to_dict() for item in self.items],
        }

    def _count_status(self, status: ArtifactRecoveryStatus) -> int:
        return sum(1 for item in self.items if item.status == status)


class ArtifactRecoveryPlanner:
    """Build read-only recovery plans for artifact recipe collections.

    Ownership boundaries:
    - this planner inspects artifact/metadata/source availability only;
    - ``ArtifactRecipeExecutor`` owns execution order and execution reporting;
    - ``ArtifactCalculationService`` owns full-dataset calculation and save;
    - ``DerivedCsvStore`` owns CSV + metadata persistence;
    - Analysis Database stores own database materialization/rebuild semantics.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        derived_store: DerivedCsvStore | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)
        self._derived_store = derived_store or DerivedCsvStore(
            historical_root=self._historical_root
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )

    def plan_collection_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        selected_recipe_ids: Iterable[str] | None = None,
    ) -> ArtifactRecoveryReport:
        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.plan_collection(
            collection,
            selected_recipe_ids=selected_recipe_ids,
        )

    def plan_collection(
        self,
        collection: ArtifactRecipeCollection,
        *,
        selected_recipe_ids: Iterable[str] | None = None,
    ) -> ArtifactRecoveryReport:
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError("plan_collection() expects an ArtifactRecipeCollection instance")

        selected_ids = self._normalize_selected_recipe_ids(
            collection=collection,
            selected_recipe_ids=selected_recipe_ids,
        )
        selected_set = set(selected_ids)

        items: list[ArtifactRecoveryItemReport] = []
        for recipe_index, recipe in enumerate(collection.recipe_snapshots):
            if recipe.recipe_id not in selected_set:
                continue
            items.append(self._plan_recipe(recipe=recipe, recipe_index=recipe_index))

        return ArtifactRecoveryReport(
            market=collection.market,
            collection_id=collection.collection_id,
            collection_display_name=collection.display_name,
            requested_recipe_ids=selected_ids,
            items=tuple(items),
        )

    def expected_instance_key(self, recipe: ArtifactRecipe) -> str:
        return self._expected_instance_key(recipe=recipe)

    def _plan_recipe(
        self,
        *,
        recipe: ArtifactRecipe,
        recipe_index: int,
    ) -> ArtifactRecoveryItemReport:
        kind = self._kind_from_tool_type(recipe.tool_type)
        expected_instance_key = self._expected_instance_key(recipe=recipe)
        expected_csv_path = self._expected_csv_path(
            market=recipe.market,
            kind=kind,
            instance_key=expected_instance_key,
        )
        expected_metadata_path = metadata_path_for_csv(expected_csv_path)

        existing_csv = expected_csv_path.exists()
        existing_metadata = expected_metadata_path.exists()
        blocked_reasons = self._recalculation_blockers(recipe=recipe)
        can_recalculate = not blocked_reasons
        status, stale_reasons, notes = self._artifact_status(
            recipe=recipe,
            kind=kind,
            expected_instance_key=expected_instance_key,
            expected_csv_path=expected_csv_path,
            expected_metadata_path=expected_metadata_path,
            existing_csv=existing_csv,
            existing_metadata=existing_metadata,
        )

        if status != "up_to_date" and blocked_reasons:
            notes = (*notes, f"Artifact status before recalculation blockers: {status}.")
            status = "blocked"

        return ArtifactRecoveryItemReport(
            recipe_id=recipe.recipe_id,
            recipe_index=recipe_index,
            display_name=recipe.display_name,
            tool_type=recipe.tool_type,
            tool_key=recipe.tool_key,
            expected_kind=kind,
            expected_instance_key=expected_instance_key,
            expected_csv_path=expected_csv_path,
            expected_metadata_path=expected_metadata_path,
            expected_output_names=tuple(recipe.output_names),
            status=status,
            can_recalculate=can_recalculate,
            existing_csv=existing_csv,
            existing_metadata=existing_metadata,
            stale_reasons=stale_reasons,
            blocked_reasons=blocked_reasons,
            notes=notes,
        )

    def _artifact_status(
        self,
        *,
        recipe: ArtifactRecipe,
        kind: DerivedKind,
        expected_instance_key: str,
        expected_csv_path: Path,
        expected_metadata_path: Path,
        existing_csv: bool,
        existing_metadata: bool,
    ) -> tuple[ArtifactRecoveryStatus, tuple[str, ...], tuple[str, ...]]:
        if not existing_csv:
            return "missing", (), (f"Expected artifact CSV is missing: {expected_csv_path}",)

        csv_columns, csv_error = self._read_csv_columns(expected_csv_path)
        if csv_error:
            return "freshness_unknown", (), (csv_error,)

        if not existing_metadata:
            return (
                "freshness_unknown",
                (),
                (f"Expected metadata sidecar is missing: {expected_metadata_path}",),
            )

        manifest = self._derived_store.load_metadata_manifest(expected_csv_path)
        if manifest is None:
            return (
                "freshness_unknown",
                (),
                (f"Expected metadata sidecar could not be loaded: {expected_metadata_path}",),
            )

        stale_reasons = self._metadata_mismatch_reasons(
            recipe=recipe,
            kind=kind,
            expected_instance_key=expected_instance_key,
            expected_csv_path=expected_csv_path,
            csv_columns=csv_columns,
            manifest=manifest,
        )
        if stale_reasons:
            return "stale", stale_reasons, ()

        freshness_notes = self._freshness_unknown_reasons(
            expected_csv_path=expected_csv_path,
            manifest=manifest,
        )
        if freshness_notes:
            return "freshness_unknown", (), freshness_notes

        return "up_to_date", (), ()

    def _metadata_mismatch_reasons(
        self,
        *,
        recipe: ArtifactRecipe,
        kind: DerivedKind,
        expected_instance_key: str,
        expected_csv_path: Path,
        csv_columns: tuple[str, ...],
        manifest: HistoricalCsvArtifactManifest,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        expected_artifact_family = artifact_family_for_storage_family(kind)

        if manifest.market != recipe.market:
            reasons.append("Metadata market does not match recipe market.")
        if manifest.identity.storage_family != kind:
            reasons.append(
                f"Metadata storage_family {manifest.identity.storage_family!r} does not match expected {kind!r}."
            )
        if manifest.identity.artifact_family != expected_artifact_family:
            reasons.append(
                "Metadata artifact_family "
                f"{manifest.identity.artifact_family!r} does not match expected {expected_artifact_family!r}."
            )
        if manifest.tool is None:
            reasons.append("Metadata tool section is missing.")
        else:
            if str(manifest.tool.tool_key).strip().lower() != recipe.tool_key:
                reasons.append(
                    f"Metadata tool_key {manifest.tool.tool_key!r} does not match recipe tool_key {recipe.tool_key!r}."
                )
            if str(manifest.tool.instance_key).strip() != expected_instance_key:
                reasons.append(
                    "Metadata instance_key "
                    f"{manifest.tool.instance_key!r} does not match expected {expected_instance_key!r}."
                )
            if not _normalized_json_equal(manifest.tool.params, recipe.params):
                reasons.append("Metadata params do not match recipe params.")
            if recipe.input_bindings and not _normalized_json_equal(
                manifest.tool.bindings,
                recipe.input_bindings,
            ):
                reasons.append("Metadata bindings do not match recipe input_bindings.")

        missing_csv_outputs = [
            output_name
            for output_name in recipe.output_names
            if output_name not in csv_columns
        ]
        if missing_csv_outputs:
            reasons.append(f"CSV is missing expected output columns: {missing_csv_outputs}")

        missing_metadata_outputs = [
            output_name
            for output_name in recipe.output_names
            if output_name not in manifest.shape.columns
        ]
        if missing_metadata_outputs:
            reasons.append(
                f"Metadata shape is missing expected output columns: {missing_metadata_outputs}"
            )

        expected_csv_name = expected_csv_path.name
        if manifest.files.csv_filename != expected_csv_name:
            reasons.append(
                f"Metadata csv_filename {manifest.files.csv_filename!r} does not match expected {expected_csv_name!r}."
            )

        return tuple(reasons)

    def _freshness_unknown_reasons(
        self,
        *,
        expected_csv_path: Path,
        manifest: HistoricalCsvArtifactManifest,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        try:
            stat = expected_csv_path.stat()
        except OSError as exc:
            return (f"Could not stat expected CSV for freshness check: {exc}",)

        current_size = int(stat.st_size)
        if manifest.fingerprint.size_bytes is not None and manifest.fingerprint.size_bytes != current_size:
            notes.append(
                "CSV file size differs from metadata fingerprint; exact freshness is unknown."
            )

        # mtime precision can vary by platform/filesystem. Treat large drift as
        # unknown rather than stale because the planner does not own content hash
        # computation and current sidecars do not store recipe hashes.
        if manifest.fingerprint.modified_at_ms is not None:
            current_mtime_ms = int(stat.st_mtime * 1000)
            if abs(current_mtime_ms - int(manifest.fingerprint.modified_at_ms)) > 2000:
                notes.append(
                    "CSV modified time differs from metadata fingerprint; exact freshness is unknown."
                )

        if manifest.fingerprint.sha256_status not in {"computed", "not_computed"}:
            notes.append(
                f"Metadata fingerprint sha256_status is {manifest.fingerprint.sha256_status!r}."
            )

        return tuple(notes)

    def _recalculation_blockers(self, *, recipe: ArtifactRecipe) -> tuple[str, ...]:
        blockers: list[str] = []
        ohlcv_path = CsvOHLCVStore().file_path(self._paths.ohlcv_dir(recipe.market))
        if not ohlcv_path.exists():
            blockers.append(f"Missing OHLCV candles file required for recalculation: {ohlcv_path}")

        for role_name, source_meta in self._iter_source_metadata(recipe.input_binding_meta):
            blockers.extend(
                self._source_metadata_blockers(
                    role_name=role_name,
                    source_meta=source_meta,
                )
            )

        if recipe.tool_type == "indicator" and recipe.tool_key == "universal_trend_classifier":
            blockers.extend(self._utc_dependency_blockers(recipe=recipe))

        return tuple(blockers)

    def _source_metadata_blockers(
        self,
        *,
        role_name: str,
        source_meta: Mapping[str, Any],
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        family = str(source_meta.get("family", "default")).strip().lower()
        source_kind = str(source_meta.get("source_kind", "saved")).strip().lower()
        column_name = str(source_meta.get("column_name", "")).strip()
        artifact_path = str(source_meta.get("artifact_path", "")).strip()

        if family == "default":
            return ()

        if source_kind == "temporary":
            blockers.append(
                f"Role {role_name!r} uses a temporary chart-session source, which is not available for save-only recovery."
            )
            return tuple(blockers)

        if not column_name:
            blockers.append(f"Role {role_name!r} is missing a source column_name.")
        if not artifact_path:
            blockers.append(f"Role {role_name!r} is missing a source artifact_path.")
            return tuple(blockers)

        path = Path(artifact_path).expanduser()
        if not path.exists():
            blockers.append(f"Source artifact for role {role_name!r} was not found: {path}")
            return tuple(blockers)

        columns, error = self._read_csv_columns(path)
        if error:
            blockers.append(f"Source artifact for role {role_name!r} is unreadable: {error}")
            return tuple(blockers)

        if column_name and column_name not in columns:
            blockers.append(
                f"Source artifact for role {role_name!r} is missing required column {column_name!r}: {path}"
            )

        join_key = "ts_ms" if "ts_ms" in columns else "time" if "time" in columns else ""
        if not join_key:
            blockers.append(
                f"Source artifact for role {role_name!r} cannot be aligned safely; 'ts_ms' or 'time' is required: {path}"
            )
        elif self._csv_join_key_has_duplicates(path=path, join_key=join_key):
            blockers.append(
                f"Source artifact for role {role_name!r} contains duplicate {join_key!r} values: {path}"
            )

        return tuple(blockers)

    def _utc_dependency_blockers(self, *, recipe: ArtifactRecipe) -> tuple[str, ...]:
        required_columns = self._utc_peak_trough_columns(recipe.params)
        refs = self._list_peaks_troughs_artifacts(market=recipe.market)
        if not refs:
            return (
                "Universal Trend Classifier requires a saved Peaks & Troughs indicator artifact for this dataset/timeframe.",
            )

        expected_default_instance = self._expected_instance_key_for(
            tool_key="peaks_troughs",
            params={},
        )
        selected = None
        for ref in refs:
            if str(ref.get("instance_key", "")).strip() == expected_default_instance:
                selected = ref
                break
        if selected is None:
            if len(refs) == 1:
                selected = refs[0]
            else:
                available = ", ".join(str(ref.get("instance_key", "")) for ref in refs)
                return (
                    "Multiple saved Peaks & Troughs artifacts were found, but no canonical default instance could be selected. "
                    f"Available instances: {available}",
                )

        path = Path(str(selected.get("path", ""))).expanduser()
        columns, error = self._read_csv_columns(path)
        if error:
            return (f"Saved Peaks & Troughs artifact is unreadable: {error}",)

        missing = [column for column in required_columns if column not in columns]
        if missing:
            return (
                "Saved Peaks & Troughs artifact does not contain columns required by UTC: "
                f"{missing}",
            )
        return ()

    def _list_peaks_troughs_artifacts(self, *, market: MarketId) -> list[dict[str, object]]:
        indicator_dir = self._paths.dataset_dir(market, "indicators")
        if not indicator_dir.exists():
            return []

        refs: list[dict[str, object]] = []
        for path in sorted(indicator_dir.glob("*.csv")):
            manifest = self._derived_store.load_metadata_manifest(path)
            if manifest is None or manifest.market != market or manifest.tool is None:
                continue
            if str(manifest.tool.tool_key).strip().lower() != "peaks_troughs":
                continue
            refs.append(
                {
                    "path": path,
                    "instance_key": manifest.tool.instance_key or path.stem,
                }
            )
        return refs

    def _expected_instance_key(self, *, recipe: ArtifactRecipe) -> str:
        return self._expected_instance_key_for(
            tool_key=recipe.tool_key,
            params=recipe.params,
        )

    def _expected_instance_key_for(
        self,
        *,
        tool_key: str,
        params: Mapping[str, Any],
    ) -> str:
        return build_construct_instance_key_from_params(
            construct_key=tool_key,
            params=dict(params),
            exclude_param_keys=_EXCLUDED_BINDING_PARAM_KEYS,
        )

    def _expected_csv_path(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        instance_key: str,
    ) -> Path:
        # Use HistoricalPaths.dataset_dir instead of DerivedCsvStore.resolve_path
        # because the planner is read-only and must not create missing folders.
        return self._paths.dataset_dir(market, kind) / f"{instance_key}.csv"

    def _kind_from_tool_type(self, tool_type: str) -> DerivedKind:
        value = str(tool_type or "").strip().lower()
        if value == "indicator":
            return "indicators"
        if value == "oscillator":
            return "oscillators"
        if value == "construct":
            return "constructs"
        raise ValueError(f"Unsupported recovery tool_type: {tool_type!r}")

    def _normalize_selected_recipe_ids(
        self,
        *,
        collection: ArtifactRecipeCollection,
        selected_recipe_ids: Iterable[str] | None,
    ) -> tuple[str, ...]:
        collection_ids = tuple(recipe.recipe_id for recipe in collection.recipe_snapshots)
        collection_id_set = set(collection_ids)
        if selected_recipe_ids is None:
            return collection_ids

        requested: list[str] = []
        for raw_recipe_id in selected_recipe_ids:
            recipe_id = str(raw_recipe_id or "").strip()
            if not recipe_id:
                raise ValueError("selected_recipe_ids must not contain empty recipe ids")
            if recipe_id not in collection_id_set:
                raise ValueError(f"Selected recipe id is not in collection: {recipe_id}")
            if recipe_id not in requested:
                requested.append(recipe_id)

        if not requested:
            raise ValueError("selected_recipe_ids must include at least one recipe id")

        requested_set = set(requested)
        return tuple(recipe_id for recipe_id in collection_ids if recipe_id in requested_set)

    def _read_csv_columns(self, path: Path) -> tuple[tuple[str, ...], str]:
        try:
            df = pd.read_csv(path, nrows=0)
        except Exception as exc:
            return (), f"Could not read CSV header from {path}: {type(exc).__name__}: {exc}"
        return tuple(str(column) for column in df.columns), ""

    def _csv_join_key_has_duplicates(self, *, path: Path, join_key: str) -> bool:
        try:
            values = pd.read_csv(path, usecols=[join_key])[join_key]
        except Exception:
            return False
        return bool(values.duplicated(keep=False).any())

    def _iter_source_metadata(
        self,
        input_binding_meta: Mapping[str, Any],
    ) -> Iterable[tuple[str, Mapping[str, Any]]]:
        for role_name, role_meta in (input_binding_meta or {}).items():
            if isinstance(role_meta, Mapping):
                yield str(role_name), role_meta
                continue
            if isinstance(role_meta, list):
                for index, entry in enumerate(role_meta):
                    if isinstance(entry, Mapping):
                        yield f"{role_name}[{index}]", entry

    def _utc_peak_trough_columns_for_purpose(
        self,
        params: Mapping[str, Any],
        *,
        purpose: str,
    ) -> tuple[str, str]:
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

    def _utc_peak_trough_columns(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        columns: list[str] = []
        for purpose in ("trend", "range"):
            for column_name in self._utc_peak_trough_columns_for_purpose(params, purpose=purpose):
                if column_name not in columns:
                    columns.append(column_name)
        return tuple(columns)


def _normalized_json_equal(left: Any, right: Any) -> bool:
    return _normalize_for_compare(left) == _normalize_for_compare(right)


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_for_compare(value[key]) for key in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_compare(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value
