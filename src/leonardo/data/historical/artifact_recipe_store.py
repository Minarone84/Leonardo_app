from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Literal, Mapping

from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.naming import MarketId, canonicalize

ARTIFACT_RECIPE_SCHEMA_VERSION = 1
ARTIFACT_RECIPE_TYPE = "artifact_recipe"
ARTIFACT_RECIPE_DATASET_DIR = "artifact_recipes"
ARTIFACT_RECIPE_METADATA_NAMESPACE = "artifact_recipe"

ArtifactRecipeToolType = Literal["indicator", "oscillator", "construct"]

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_UNDERSCORE_RE = re.compile(r"_+")
_RECIPE_ID_RE = re.compile(r"^[a-z0-9_]+$")


def market_to_dict(market: MarketId) -> dict[str, str]:
    return {
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
    }


def market_from_dict(data: Mapping[str, object]) -> MarketId:
    return canonicalize(
        str(data.get("exchange", "")),
        str(data.get("market_type", "")),
        str(data.get("symbol", "")),
        str(data.get("timeframe", "")),
    )


def slugify_recipe_segment(
    value: object,
    *,
    fallback: str = "recipe",
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


def build_artifact_recipe_hash(recipe_payload: Mapping[str, Any]) -> str:
    normalized = _normalize_for_hash(recipe_payload)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_artifact_recipe_hash_short(recipe_hash: str) -> str:
    raw = str(recipe_hash).strip().lower()
    if len(raw) < 8:
        raise ValueError("recipe_hash must contain at least 8 hexadecimal characters")
    return f"h{raw[:8]}"


def build_artifact_recipe_id(
    *,
    tool_type: str,
    tool_key: str,
    recipe_hash: str,
) -> str:
    family_slug = slugify_recipe_segment(tool_type, fallback="tool", max_length=48)
    tool_slug = slugify_recipe_segment(tool_key, fallback="tool", max_length=96)
    return (
        f"ar__{family_slug}__{tool_slug}__"
        f"{build_artifact_recipe_hash_short(recipe_hash)}"
    )


@dataclass(frozen=True)
class ArtifactRecipe:
    """Reusable full-dataset financial-tool calculation recipe.

    A recipe is an instruction set for reproducing an artifact. It is not the
    saved CSV artifact itself and it is not an adjacent ``.meta.json`` sidecar.
    """

    schema_version: int
    recipe_type: Literal["artifact_recipe"]
    recipe_id: str
    recipe_hash: str
    recipe_hash_short: str
    display_name: str
    market: MarketId
    tool_type: ArtifactRecipeToolType
    tool_key: str
    tool_title: str
    params: dict[str, Any]
    input_bindings: dict[str, Any]
    input_binding_meta: dict[str, Any]
    required_inputs: tuple[str, ...]
    output_names: tuple[str, ...]
    output_signals: tuple[dict[str, Any], ...]
    created_at_ms: int
    updated_at_ms: int

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_RECIPE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported artifact recipe schema_version: {self.schema_version}"
            )
        if self.recipe_type != ARTIFACT_RECIPE_TYPE:
            raise ValueError(
                f"Unsupported artifact recipe_type: {self.recipe_type!r}"
            )
        _validate_recipe_id(self.recipe_id)
        if self.tool_type not in {"indicator", "oscillator", "construct"}:
            raise ValueError(
                f"Unsupported artifact recipe tool_type: {self.tool_type!r}"
            )
        if not self.tool_key:
            raise ValueError("Artifact recipe tool_key is required")
        if not self.recipe_hash or not self.recipe_hash_short:
            raise ValueError("Artifact recipe hash fields are required")

        _require_json_serializable(self.params, field_name="recipe.params")
        _require_json_serializable(
            self.input_bindings,
            field_name="recipe.input_bindings",
        )
        _require_json_serializable(
            self.input_binding_meta,
            field_name="recipe.input_binding_meta",
        )
        _require_json_serializable(
            list(self.output_signals),
            field_name="recipe.output_signals",
        )

        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "input_bindings", dict(self.input_bindings))
        object.__setattr__(self, "input_binding_meta", dict(self.input_binding_meta))
        object.__setattr__(
            self,
            "required_inputs",
            tuple(str(item) for item in self.required_inputs),
        )
        object.__setattr__(
            self,
            "output_names",
            tuple(str(item) for item in self.output_names),
        )
        object.__setattr__(
            self,
            "output_signals",
            tuple(dict(item) for item in self.output_signals),
        )

    def to_payload(self) -> dict[str, Any]:
        """Return the payload shape consumed by ArtifactCalculationService."""
        return {
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "exchange": self.market.exchange,
            "market_type": self.market.market_type,
            "symbol": self.market.symbol,
            "timeframe": self.market.timeframe,
            "params": dict(self.params),
            "input_bindings": dict(self.input_bindings),
            "input_binding_meta": dict(self.input_binding_meta),
            "required_inputs": list(self.required_inputs),
            "output_names": list(self.output_names),
            "output_signals": [dict(item) for item in self.output_signals],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "recipe_type": self.recipe_type,
            "recipe_id": self.recipe_id,
            "recipe_hash": self.recipe_hash,
            "recipe_hash_short": self.recipe_hash_short,
            "display_name": self.display_name,
            "market": market_to_dict(self.market),
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "params": dict(self.params),
            "input_bindings": dict(self.input_bindings),
            "input_binding_meta": dict(self.input_binding_meta),
            "required_inputs": list(self.required_inputs),
            "output_names": list(self.output_names),
            "output_signals": [dict(item) for item in self.output_signals],
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactRecipe":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            recipe_type=str(data.get("recipe_type", "")),  # type: ignore[arg-type]
            recipe_id=str(data.get("recipe_id", "")),
            recipe_hash=str(data.get("recipe_hash", "")),
            recipe_hash_short=str(data.get("recipe_hash_short", "")),
            display_name=str(data.get("display_name", "")),
            market=market_from_dict(dict(data.get("market", {}) or {})),  # type: ignore[arg-type]
            tool_type=str(data.get("tool_type", "indicator")),  # type: ignore[arg-type]
            tool_key=str(data.get("tool_key", "")),
            tool_title=str(data.get("tool_title", "")),
            params=_dict_or_empty(data.get("params")),
            input_bindings=_dict_or_empty(data.get("input_bindings")),
            input_binding_meta=_dict_or_empty(data.get("input_binding_meta")),
            required_inputs=tuple(
                str(item) for item in data.get("required_inputs", ()) or ()
            ),  # type: ignore[arg-type]
            output_names=tuple(
                str(item) for item in data.get("output_names", ()) or ()
            ),  # type: ignore[arg-type]
            output_signals=tuple(
                dict(item) for item in data.get("output_signals", ()) or ()
            ),  # type: ignore[arg-type]
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
        )


def artifact_recipe_metadata_entries(recipe: ArtifactRecipe) -> tuple[ArtifactMetadataEntry, ...]:
    """
    Build non-identity artifact sidecar metadata for a saved recipe.

    The entries link a persisted artifact to the reusable recipe that can
    reproduce it. They do not affect artifact identity, file naming, or recipe
    identity.
    """
    return (
        ArtifactMetadataEntry(
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_id",
            value=recipe.recipe_id,
            value_type="string",
            label="Source artifact recipe ID",
            description="Reusable artifact recipe saved for this artifact.",
            tags=("artifact_recipe", "lineage"),
            searchable=True,
            identity_affecting=False,
        ),
        ArtifactMetadataEntry(
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_hash",
            value=recipe.recipe_hash,
            value_type="string",
            label="Source artifact recipe hash",
            description="Stable hash of the reusable artifact recipe.",
            tags=("artifact_recipe", "lineage"),
            searchable=True,
            identity_affecting=False,
        ),
        ArtifactMetadataEntry(
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_hash_short",
            value=recipe.recipe_hash_short,
            value_type="string",
            label="Source artifact recipe short hash",
            description="Short stable hash of the reusable artifact recipe.",
            tags=("artifact_recipe", "lineage"),
            searchable=True,
            identity_affecting=False,
        ),
    )


@dataclass(frozen=True)
class ArtifactRecipeSummary:
    recipe_id: str
    display_name: str
    market: MarketId
    tool_type: ArtifactRecipeToolType
    tool_key: str
    tool_title: str
    output_names: tuple[str, ...]
    created_at_ms: int
    updated_at_ms: int
    recipe_path: Path

    @classmethod
    def from_recipe(
        cls,
        recipe: ArtifactRecipe,
        *,
        recipe_path: Path,
    ) -> "ArtifactRecipeSummary":
        return cls(
            recipe_id=recipe.recipe_id,
            display_name=recipe.display_name,
            market=recipe.market,
            tool_type=recipe.tool_type,
            tool_key=recipe.tool_key,
            tool_title=recipe.tool_title,
            output_names=recipe.output_names,
            created_at_ms=recipe.created_at_ms,
            updated_at_ms=recipe.updated_at_ms,
            recipe_path=Path(recipe_path),
        )


class ArtifactRecipeStore:
    """Partition-local persistence for reusable artifact calculation recipes."""

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    def recipe_dir(self, *, market: MarketId) -> Path:
        return self._paths.partition_dir(market) / ARTIFACT_RECIPE_DATASET_DIR

    def ensure_recipe_dir(self, *, market: MarketId) -> Path:
        path = self.recipe_dir(market=market)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def recipe_path(self, *, market: MarketId, recipe_id: str) -> Path:
        _validate_recipe_id(recipe_id)
        return self.recipe_dir(market=market) / f"{recipe_id}.json"

    def build_recipe_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
        existing_recipe: ArtifactRecipe | None = None,
    ) -> ArtifactRecipe:
        market = self._market_from_payload(payload)
        tool_type = self._normalize_tool_type(payload.get("tool_type"))
        tool_key = str(payload.get("tool_key", "")).strip().lower()
        tool_title = str(payload.get("tool_title", tool_key)).strip() or tool_key

        if not tool_key:
            raise ValueError("Artifact recipe payload is missing tool_key.")

        params = _dict_or_empty(payload.get("params"))
        input_bindings = _dict_or_empty(payload.get("input_bindings"))
        input_binding_meta = _dict_or_empty(payload.get("input_binding_meta"))
        required_inputs = tuple(
            str(item) for item in (payload.get("required_inputs", ()) or ())
        )
        output_names = tuple(
            str(item) for item in (payload.get("output_names", ()) or ())
        )
        output_signals = tuple(
            dict(item) for item in (payload.get("output_signals", ()) or ())
        )

        identity_payload = self._identity_payload(
            market=market,
            tool_type=tool_type,
            tool_key=tool_key,
            params=params,
            input_bindings=input_bindings,
            input_binding_meta=input_binding_meta,
            required_inputs=required_inputs,
            output_names=output_names,
            output_signals=output_signals,
        )
        recipe_hash = build_artifact_recipe_hash(identity_payload)
        recipe_hash_short = build_artifact_recipe_hash_short(recipe_hash)
        recipe_id = build_artifact_recipe_id(
            tool_type=tool_type,
            tool_key=tool_key,
            recipe_hash=recipe_hash,
        )

        now_ms = int(time.time() * 1000)
        created = (
            int(created_at_ms)
            if created_at_ms is not None
            else existing_recipe.created_at_ms
            if existing_recipe is not None
            else now_ms
        )
        updated = int(updated_at_ms) if updated_at_ms is not None else now_ms

        display_name = self._display_name_from_payload(
            payload=payload,
            tool_title=tool_title,
            output_names=output_names,
            recipe_hash_short=recipe_hash_short,
        )

        return ArtifactRecipe(
            schema_version=ARTIFACT_RECIPE_SCHEMA_VERSION,
            recipe_type=ARTIFACT_RECIPE_TYPE,
            recipe_id=recipe_id,
            recipe_hash=recipe_hash,
            recipe_hash_short=recipe_hash_short,
            display_name=display_name,
            market=market,
            tool_type=tool_type,
            tool_key=tool_key,
            tool_title=tool_title,
            params=params,
            input_bindings=input_bindings,
            input_binding_meta=input_binding_meta,
            required_inputs=required_inputs,
            output_names=output_names,
            output_signals=output_signals,
            created_at_ms=created,
            updated_at_ms=updated,
        )

    def save_recipe(
        self,
        payload: Mapping[str, Any] | ArtifactRecipe,
        *,
        overwrite: bool = True,
    ) -> ArtifactRecipe:
        if isinstance(payload, ArtifactRecipe):
            recipe = payload
        else:
            draft = self.build_recipe_from_payload(payload)
            path = self.recipe_path(market=draft.market, recipe_id=draft.recipe_id)
            existing = (
                self.load_recipe(market=draft.market, recipe_id=draft.recipe_id)
                if path.exists()
                else None
            )
            recipe = self.build_recipe_from_payload(payload, existing_recipe=existing)

        path = self.recipe_path(market=recipe.market, recipe_id=recipe.recipe_id)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Artifact recipe already exists: {path}")

        self._atomic_write_json(recipe.to_dict(), path)
        return recipe

    def load_recipe(self, *, market: MarketId, recipe_id: str) -> ArtifactRecipe:
        path = self.recipe_path(market=market, recipe_id=recipe_id)
        if not path.exists():
            raise FileNotFoundError(f"Artifact recipe not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            recipe = ArtifactRecipe.from_dict(json.load(handle))

        if recipe.market != market:
            raise ValueError(
                f"Artifact recipe market does not match requested partition: {path}"
            )
        return recipe

    def load_recipe_path(self, path: Path) -> ArtifactRecipe:
        recipe_path = Path(path)
        with recipe_path.open("r", encoding="utf-8") as handle:
            return ArtifactRecipe.from_dict(json.load(handle))

    def list_recipes(self, *, market: MarketId) -> list[ArtifactRecipeSummary]:
        root = self.recipe_dir(market=market)
        if not root.exists():
            return []

        summaries: list[ArtifactRecipeSummary] = []
        for path in sorted(root.glob("*.json")):
            try:
                recipe = self.load_recipe_path(path)
                if recipe.market != market:
                    continue
                summaries.append(
                    ArtifactRecipeSummary.from_recipe(recipe, recipe_path=path)
                )
            except Exception:
                continue

        summaries.sort(key=lambda summary: (summary.display_name.lower(), summary.recipe_id))
        return summaries

    def delete_recipe(self, *, market: MarketId, recipe_id: str) -> None:
        path = self.recipe_path(market=market, recipe_id=recipe_id)
        if path.exists():
            path.unlink()

    def _identity_payload(
        self,
        *,
        market: MarketId,
        tool_type: ArtifactRecipeToolType,
        tool_key: str,
        params: Mapping[str, Any],
        input_bindings: Mapping[str, Any],
        input_binding_meta: Mapping[str, Any],
        required_inputs: Iterable[str],
        output_names: Iterable[str],
        output_signals: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "schema_version": ARTIFACT_RECIPE_SCHEMA_VERSION,
            "recipe_type": ARTIFACT_RECIPE_TYPE,
            "market": market_to_dict(market),
            "tool_type": tool_type,
            "tool_key": tool_key,
            "params": _normalize_for_hash(dict(params)),
            "input_bindings": _normalize_for_hash(dict(input_bindings)),
            "input_binding_meta": _normalize_for_hash(dict(input_binding_meta)),
            "required_inputs": _normalize_for_hash(tuple(required_inputs)),
            "output_names": _normalize_for_hash(tuple(output_names)),
            "output_signals": _normalize_for_hash(
                tuple(dict(item) for item in output_signals)
            ),
        }

    def _display_name_from_payload(
        self,
        *,
        payload: Mapping[str, Any],
        tool_title: str,
        output_names: tuple[str, ...],
        recipe_hash_short: str,
    ) -> str:
        raw_display_name = str(payload.get("recipe_display_name", "")).strip()
        if raw_display_name:
            return raw_display_name
        if output_names:
            return f"{tool_title} · {', '.join(output_names[:3])}"
        return f"{tool_title} · {recipe_hash_short}"

    def _market_from_payload(self, payload: Mapping[str, Any]) -> MarketId:
        try:
            return canonicalize(
                exchange=str(payload.get("exchange", "")),
                market_type=str(payload.get("market_type", "")),
                symbol=str(payload.get("symbol", "")),
                timeframe=str(payload.get("timeframe", "")),
            )
        except Exception as exc:
            raise ValueError(f"Invalid artifact recipe market identity: {exc!r}") from exc

    def _normalize_tool_type(self, raw_tool_type: Any) -> ArtifactRecipeToolType:
        value = str(raw_tool_type or "").strip().lower()
        if value not in {"indicator", "oscillator", "construct"}:
            raise ValueError(f"Unsupported artifact recipe tool_type: {raw_tool_type!r}")
        return value  # type: ignore[return-value]

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="artifact_recipe_",
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
