from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Literal, Mapping

from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    market_from_dict,
    market_to_dict,
)
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.naming import MarketId

ARTIFACT_RECIPE_COLLECTION_SCHEMA_VERSION = 1
ARTIFACT_RECIPE_COLLECTION_TYPE = "artifact_recipe_collection"
ARTIFACT_RECIPE_COLLECTION_DATASET_DIR = "artifact_recipe_collections"

_COLLECTION_ID_RE = re.compile(r"^[a-z0-9_]+$")
_RECIPE_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_UNDERSCORE_RE = re.compile(r"_+")


@dataclass(frozen=True)
class ArtifactRecipeDependencyEdge:
    """Stored dependency metadata between two recipe snapshots.

    The collection store persists dependency intent only. It does not execute
    recipes, sort a dependency graph, calculate artifacts, or rebuild databases.
    """

    from_recipe_id: str
    to_recipe_id: str
    reason: str = ""
    required_columns: tuple[str, ...] = ()
    source_family: str | None = None
    source_artifact_uid: str | None = None

    def __post_init__(self) -> None:
        _validate_recipe_id(self.from_recipe_id)
        _validate_recipe_id(self.to_recipe_id)
        if self.from_recipe_id == self.to_recipe_id:
            raise ValueError("Artifact recipe dependency edge cannot point to itself")
        object.__setattr__(
            self,
            "required_columns",
            tuple(str(item) for item in self.required_columns),
        )
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(
            self,
            "source_family",
            None if self.source_family is None else str(self.source_family),
        )
        object.__setattr__(
            self,
            "source_artifact_uid",
            None if self.source_artifact_uid is None else str(self.source_artifact_uid),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_recipe_id": self.from_recipe_id,
            "to_recipe_id": self.to_recipe_id,
            "reason": self.reason,
            "required_columns": list(self.required_columns),
        }
        if self.source_family is not None:
            data["source_family"] = self.source_family
        if self.source_artifact_uid is not None:
            data["source_artifact_uid"] = self.source_artifact_uid
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactRecipeDependencyEdge":
        return cls(
            from_recipe_id=str(data.get("from_recipe_id", "")),
            to_recipe_id=str(data.get("to_recipe_id", "")),
            reason=str(data.get("reason", "") or ""),
            required_columns=tuple(
                str(item) for item in data.get("required_columns", ()) or ()
            ),  # type: ignore[arg-type]
            source_family=(
                None
                if data.get("source_family") is None
                else str(data.get("source_family"))
            ),
            source_artifact_uid=(
                None
                if data.get("source_artifact_uid") is None
                else str(data.get("source_artifact_uid"))
            ),
        )


@dataclass(frozen=True)
class ArtifactRecipeCollection:
    """Partition-local reusable collection of artifact calculation recipes.

    The collection embeds ordered recipe snapshots so it remains reproducible
    even if a single recipe JSON is deleted or later rewritten. This is durable
    persistence metadata only; execution planning belongs to a later layer.
    """

    schema_version: int
    collection_type: Literal["artifact_recipe_collection"]
    collection_id: str
    collection_hash: str
    collection_hash_short: str
    display_name: str
    description: str
    market: MarketId
    recipe_snapshots: tuple[ArtifactRecipe, ...]
    dependency_edges: tuple[ArtifactRecipeDependencyEdge, ...]
    source_database_id: str | None
    metadata: dict[str, Any]
    created_at_ms: int
    updated_at_ms: int

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_RECIPE_COLLECTION_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported artifact recipe collection schema_version: "
                f"{self.schema_version}"
            )
        if self.collection_type != ARTIFACT_RECIPE_COLLECTION_TYPE:
            raise ValueError(
                "Unsupported artifact recipe collection_type: "
                f"{self.collection_type!r}"
            )
        _validate_collection_id(self.collection_id)
        if not self.collection_hash or not self.collection_hash_short:
            raise ValueError("Artifact recipe collection hash fields are required")
        display_name = str(self.display_name or "").strip()
        if not display_name:
            raise ValueError("Artifact recipe collection display_name is required")
        if not self.recipe_snapshots:
            raise ValueError("Artifact recipe collection requires at least one recipe")

        recipes = tuple(self.recipe_snapshots)
        recipe_ids: set[str] = set()
        for recipe in recipes:
            if not isinstance(recipe, ArtifactRecipe):
                raise TypeError("recipe_snapshots must contain ArtifactRecipe objects")
            if recipe.market != self.market:
                raise ValueError(
                    "Artifact recipe collection contains a recipe from a different market"
                )
            if recipe.recipe_id in recipe_ids:
                raise ValueError(
                    f"Duplicate artifact recipe in collection: {recipe.recipe_id}"
                )
            recipe_ids.add(recipe.recipe_id)

        edges = tuple(self.dependency_edges)
        for edge in edges:
            if not isinstance(edge, ArtifactRecipeDependencyEdge):
                raise TypeError(
                    "dependency_edges must contain ArtifactRecipeDependencyEdge objects"
                )
            if edge.from_recipe_id not in recipe_ids:
                raise ValueError(
                    "Artifact recipe collection dependency references unknown "
                    f"from_recipe_id: {edge.from_recipe_id}"
                )
            if edge.to_recipe_id not in recipe_ids:
                raise ValueError(
                    "Artifact recipe collection dependency references unknown "
                    f"to_recipe_id: {edge.to_recipe_id}"
                )

        _require_json_serializable(self.metadata, field_name="collection.metadata")

        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "recipe_snapshots", recipes)
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(
            self,
            "source_database_id",
            None if self.source_database_id is None else str(self.source_database_id),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema_version": int(self.schema_version),
            "collection_type": self.collection_type,
            "collection_id": self.collection_id,
            "collection_hash": self.collection_hash,
            "collection_hash_short": self.collection_hash_short,
            "display_name": self.display_name,
            "description": self.description,
            "market": market_to_dict(self.market),
            "recipe_snapshots": [recipe.to_dict() for recipe in self.recipe_snapshots],
            "dependency_edges": [edge.to_dict() for edge in self.dependency_edges],
            "metadata": dict(self.metadata),
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
        }
        if self.source_database_id is not None:
            data["source_database_id"] = self.source_database_id
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactRecipeCollection":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            collection_type=str(data.get("collection_type", "")),  # type: ignore[arg-type]
            collection_id=str(data.get("collection_id", "")),
            collection_hash=str(data.get("collection_hash", "")),
            collection_hash_short=str(data.get("collection_hash_short", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "") or ""),
            market=market_from_dict(dict(data.get("market", {}) or {})),  # type: ignore[arg-type]
            recipe_snapshots=tuple(
                ArtifactRecipe.from_dict(dict(item))
                for item in data.get("recipe_snapshots", ()) or ()
            ),  # type: ignore[arg-type]
            dependency_edges=tuple(
                ArtifactRecipeDependencyEdge.from_dict(dict(item))
                for item in data.get("dependency_edges", ()) or ()
            ),  # type: ignore[arg-type]
            source_database_id=(
                None
                if data.get("source_database_id") is None
                else str(data.get("source_database_id"))
            ),
            metadata=_dict_or_empty(data.get("metadata")),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
        )


@dataclass(frozen=True)
class ArtifactRecipeCollectionSummary:
    collection_id: str
    display_name: str
    description: str
    market: MarketId
    recipe_count: int
    collection_hash_short: str
    source_database_id: str | None
    created_at_ms: int
    updated_at_ms: int
    collection_path: Path

    @classmethod
    def from_collection(
        cls,
        collection: ArtifactRecipeCollection,
        *,
        collection_path: Path,
    ) -> "ArtifactRecipeCollectionSummary":
        return cls(
            collection_id=collection.collection_id,
            display_name=collection.display_name,
            description=collection.description,
            market=collection.market,
            recipe_count=len(collection.recipe_snapshots),
            collection_hash_short=collection.collection_hash_short,
            source_database_id=collection.source_database_id,
            created_at_ms=collection.created_at_ms,
            updated_at_ms=collection.updated_at_ms,
            collection_path=Path(collection_path),
        )


class ArtifactRecipeCollectionStore:
    """Partition-local persistence for reusable artifact recipe collections."""

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    def collection_dir(self, *, market: MarketId) -> Path:
        return self._paths.partition_dir(market) / ARTIFACT_RECIPE_COLLECTION_DATASET_DIR

    def ensure_collection_dir(self, *, market: MarketId) -> Path:
        path = self.collection_dir(market=market)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def collection_path(self, *, market: MarketId, collection_id: str) -> Path:
        _validate_collection_id(collection_id)
        return self.collection_dir(market=market) / f"{collection_id}.json"

    def build_collection(
        self,
        *,
        market: MarketId,
        display_name: str,
        recipes: Iterable[ArtifactRecipe],
        description: str = "",
        source_database_id: str | None = None,
        dependency_edges: Iterable[ArtifactRecipeDependencyEdge | Mapping[str, object]] = (),
        metadata: Mapping[str, object] | None = None,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
    ) -> ArtifactRecipeCollection:
        recipe_snapshots = tuple(recipes)
        if not recipe_snapshots:
            raise ValueError("Artifact recipe collection requires at least one recipe")
        for recipe in recipe_snapshots:
            if recipe.market != market:
                raise ValueError(
                    "Artifact recipe collection contains a recipe from a different market"
                )

        normalized_edges = tuple(_coerce_dependency_edge(edge) for edge in dependency_edges)
        identity_payload = self._identity_payload(
            market=market,
            recipes=recipe_snapshots,
            dependency_edges=normalized_edges,
        )
        collection_hash = build_artifact_recipe_collection_hash(identity_payload)
        collection_hash_short = build_artifact_recipe_collection_hash_short(collection_hash)
        collection_id = build_artifact_recipe_collection_id(collection_hash=collection_hash)

        now_ms = int(time.time() * 1000)
        return ArtifactRecipeCollection(
            schema_version=ARTIFACT_RECIPE_COLLECTION_SCHEMA_VERSION,
            collection_type=ARTIFACT_RECIPE_COLLECTION_TYPE,
            collection_id=collection_id,
            collection_hash=collection_hash,
            collection_hash_short=collection_hash_short,
            display_name=str(display_name or "").strip(),
            description=str(description or ""),
            market=market,
            recipe_snapshots=recipe_snapshots,
            dependency_edges=normalized_edges,
            source_database_id=source_database_id,
            metadata=dict(metadata or {}),
            created_at_ms=int(created_at_ms) if created_at_ms is not None else now_ms,
            updated_at_ms=int(updated_at_ms) if updated_at_ms is not None else now_ms,
        )

    def save_collection(
        self,
        collection: ArtifactRecipeCollection,
        *,
        overwrite: bool = True,
    ) -> ArtifactRecipeCollection:
        path = self.collection_path(
            market=collection.market,
            collection_id=collection.collection_id,
        )
        if path.exists() and not overwrite:
            raise FileExistsError(f"Artifact recipe collection already exists: {path}")

        persisted = collection
        if path.exists():
            try:
                existing = self.load_collection(
                    market=collection.market,
                    collection_id=collection.collection_id,
                )
                persisted = replace(
                    collection,
                    created_at_ms=existing.created_at_ms,
                    updated_at_ms=max(int(time.time() * 1000), existing.updated_at_ms),
                )
            except Exception:
                persisted = replace(
                    collection,
                    updated_at_ms=int(time.time() * 1000),
                )

        self._atomic_write_json(persisted.to_dict(), path)
        return persisted

    def load_collection(self, *, market: MarketId, collection_id: str) -> ArtifactRecipeCollection:
        path = self.collection_path(market=market, collection_id=collection_id)
        if not path.exists():
            raise FileNotFoundError(f"Artifact recipe collection not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            collection = ArtifactRecipeCollection.from_dict(json.load(handle))

        if collection.market != market:
            raise ValueError(
                "Artifact recipe collection market does not match requested partition: "
                f"{path}"
            )
        return collection

    def load_collection_path(self, path: Path) -> ArtifactRecipeCollection:
        collection_path = Path(path)
        with collection_path.open("r", encoding="utf-8") as handle:
            return ArtifactRecipeCollection.from_dict(json.load(handle))

    def list_collections(self, *, market: MarketId) -> list[ArtifactRecipeCollectionSummary]:
        root = self.collection_dir(market=market)
        if not root.exists():
            return []

        summaries: list[ArtifactRecipeCollectionSummary] = []
        for path in sorted(root.glob("*.json")):
            try:
                collection = self.load_collection_path(path)
                if collection.market != market:
                    continue
                summaries.append(
                    ArtifactRecipeCollectionSummary.from_collection(
                        collection,
                        collection_path=path,
                    )
                )
            except Exception:
                continue

        summaries.sort(key=lambda summary: (summary.display_name.lower(), summary.collection_id))
        return summaries

    def rename_collection(
        self,
        *,
        market: MarketId,
        collection_id: str,
        new_display_name: str,
    ) -> ArtifactRecipeCollection:
        collection = self.load_collection(market=market, collection_id=collection_id)
        display_name = str(new_display_name or "").strip()
        if not display_name:
            raise ValueError("Artifact recipe collection display_name is required")
        updated = replace(
            collection,
            display_name=display_name,
            updated_at_ms=int(time.time() * 1000),
        )
        return self.save_collection(updated, overwrite=True)

    def delete_collection(self, *, market: MarketId, collection_id: str) -> None:
        path = self.collection_path(market=market, collection_id=collection_id)
        if path.exists():
            path.unlink()

    def _identity_payload(
        self,
        *,
        market: MarketId,
        recipes: Iterable[ArtifactRecipe],
        dependency_edges: Iterable[ArtifactRecipeDependencyEdge],
    ) -> dict[str, object]:
        return {
            "schema_version": ARTIFACT_RECIPE_COLLECTION_SCHEMA_VERSION,
            "collection_type": ARTIFACT_RECIPE_COLLECTION_TYPE,
            "market": market_to_dict(market),
            "recipe_snapshots": [
                _semantic_recipe_snapshot(recipe)
                for recipe in recipes
            ],
            "dependency_edges": [edge.to_dict() for edge in dependency_edges],
        }

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="artifact_recipe_collection_",
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


def build_artifact_recipe_collection_hash(collection_payload: Mapping[str, Any]) -> str:
    normalized = _normalize_for_hash(collection_payload)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_artifact_recipe_collection_hash_short(collection_hash: str) -> str:
    raw = str(collection_hash).strip().lower()
    if len(raw) < 8:
        raise ValueError("collection_hash must contain at least 8 hexadecimal characters")
    return f"h{raw[:8]}"


def build_artifact_recipe_collection_id(*, collection_hash: str) -> str:
    return f"arc__{build_artifact_recipe_collection_hash_short(collection_hash)}"


def slugify_collection_segment(
    value: object,
    *,
    fallback: str = "collection",
    max_length: int = 96,
) -> str:
    raw = str(value or "").strip().lower()
    safe = _SAFE_SEGMENT_RE.sub("_", raw)
    safe = _UNDERSCORE_RE.sub("_", safe).strip("_")
    if not safe:
        safe = fallback
    if max_length > 0 and len(safe) > max_length:
        safe = safe[:max_length].rstrip("_") or fallback
    return safe


def _coerce_dependency_edge(
    value: ArtifactRecipeDependencyEdge | Mapping[str, object],
) -> ArtifactRecipeDependencyEdge:
    if isinstance(value, ArtifactRecipeDependencyEdge):
        return value
    return ArtifactRecipeDependencyEdge.from_dict(value)


def _semantic_recipe_snapshot(recipe: ArtifactRecipe) -> dict[str, object]:
    payload = recipe.to_dict()
    payload.pop("display_name", None)
    payload.pop("created_at_ms", None)
    payload.pop("updated_at_ms", None)
    return payload


def _validate_collection_id(collection_id: str) -> None:
    value = str(collection_id or "").strip()
    if not value or not _COLLECTION_ID_RE.fullmatch(value):
        raise ValueError(f"Invalid artifact recipe collection_id: {collection_id!r}")


def _validate_recipe_id(recipe_id: str) -> None:
    value = str(recipe_id or "").strip()
    if not value or not _RECIPE_ID_RE.fullmatch(value):
        raise ValueError(f"Invalid artifact recipe_id: {recipe_id!r}")


def _dict_or_empty(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object; got {type(value).__name__}")
    return dict(value)


def _require_json_serializable(value: Any, *, field_name: str) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_for_hash(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hash(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value
