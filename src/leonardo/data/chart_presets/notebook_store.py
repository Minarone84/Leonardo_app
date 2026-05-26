from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping


HISTORICAL_NOTEBOOK_SCHEMA_VERSION = 1
HISTORICAL_NOTEBOOK_OBJECT_TYPE = "historical_workspace_notebook"

_NOTEBOOK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_DATASET_IDENTITY_KEYS = ("exchange", "market_type", "symbol", "timeframe")
_VALID_TRADE_DIRECTIONS = {"", "Long", "Short"}
_VALID_TRADE_OUTCOMES = {"", "Good", "Bad"}
DEFAULT_POI_MARKER_OFFSET = 28
DEFAULT_PT_LONG_MARKER_OFFSET = 56
DEFAULT_PT_SHORT_MARKER_OFFSET = 56


@dataclass(frozen=True)
class HistoricalNotebook:
    """Durable Historical Workspace notebook payload.

    A notebook stores chart-specific analysis text, trade rows, and points of
    interest keyed by dataset identity. It does not store live chart positions
    as identity, widget objects, study state, renderer payloads, or marker
    render state.
    """

    schema_version: int
    object_type: str
    notebook_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    chart_entries: tuple[dict[str, Any], ...]
    annotation_settings: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != HISTORICAL_NOTEBOOK_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported historical notebook schema_version: {self.schema_version}"
            )
        if self.object_type != HISTORICAL_NOTEBOOK_OBJECT_TYPE:
            raise ValueError(
                f"Unsupported historical notebook object_type: {self.object_type!r}"
            )

        notebook_id = str(self.notebook_id or "").strip()
        _validate_notebook_id(notebook_id)

        display_name = str(self.display_name or "").strip()
        if not display_name:
            raise ValueError("Historical notebook display_name is required")

        chart_entries = tuple(
            _json_clone(dict(entry), field_name=f"chart_entries[{idx}]")
            for idx, entry in enumerate(self.chart_entries or ())
        )
        _validate_chart_entries_payload(chart_entries)
        annotation_settings = normalize_notebook_annotation_settings(
            self.annotation_settings
        )

        object.__setattr__(self, "notebook_id", notebook_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "created_at_ms", int(self.created_at_ms))
        object.__setattr__(self, "updated_at_ms", int(self.updated_at_ms))
        object.__setattr__(self, "chart_entries", chart_entries)
        object.__setattr__(self, "annotation_settings", annotation_settings)
        object.__setattr__(
            self,
            "content_hash",
            build_historical_notebook_content_hash(self.to_dict()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "object_type": self.object_type,
            "notebook_id": self.notebook_id,
            "content_hash": self.content_hash,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
            "annotation_settings": dict(self.annotation_settings or {}),
            "chart_entries": [dict(entry) for entry in self.chart_entries],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalNotebook":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            object_type=str(data.get("object_type", "")),
            notebook_id=str(data.get("notebook_id", "")),
            content_hash=str(data.get("content_hash", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "") or ""),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
            annotation_settings=normalize_notebook_annotation_settings(
                data.get("annotation_settings", {})
            ),
            chart_entries=tuple(
                dict(entry) for entry in data.get("chart_entries", ()) or ()
            ),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class HistoricalNotebookSummary:
    """List-view metadata for a persisted historical notebook."""

    notebook_id: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    chart_count: int
    note_count: int
    trade_count: int
    poi_count: int
    chart_summaries: tuple[dict[str, Any], ...]
    path: Path

    @classmethod
    def from_notebook(
        cls,
        notebook: HistoricalNotebook,
        *,
        path: Path,
    ) -> "HistoricalNotebookSummary":
        chart_summaries: list[dict[str, Any]] = []
        note_count = 0
        trade_count = 0
        poi_count = 0
        for entry in notebook.chart_entries:
            dataset = _dict_or_empty(entry.get("dataset"))
            notes = _sequence_or_empty(entry.get("notes"))
            trades = _sequence_or_empty(entry.get("trades"))
            points = _sequence_or_empty(entry.get("points_of_interest"))
            note_count += len(notes)
            trade_count += len(trades)
            poi_count += len(points)
            chart_summaries.append(
                {
                    "chart_key": str(entry.get("chart_key", "") or ""),
                    "exchange": str(dataset.get("exchange", "") or ""),
                    "market_type": str(dataset.get("market_type", "") or ""),
                    "symbol": str(dataset.get("symbol", "") or ""),
                    "timeframe": str(dataset.get("timeframe", "") or ""),
                    "last_seen_position": entry.get("last_seen_position"),
                    "note_count": len(notes),
                    "trade_count": len(trades),
                    "poi_count": len(points),
                }
            )

        return cls(
            notebook_id=notebook.notebook_id,
            display_name=notebook.display_name,
            description=notebook.description,
            created_at_ms=notebook.created_at_ms,
            updated_at_ms=notebook.updated_at_ms,
            chart_count=len(notebook.chart_entries),
            note_count=note_count,
            trade_count=trade_count,
            poi_count=poi_count,
            chart_summaries=tuple(chart_summaries),
            path=Path(path),
        )


class HistoricalNotebookStore:
    """Persist historical notebook JSON files under an injected root.

    The store owns durable JSON persistence only. It does not import Qt, inspect
    live chart widgets, compute studies, apply annotations, or render markers.
    Callers provide prepared notebook payloads and the configured storage root.
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def ensure_root_dir(self) -> Path:
        self._root_dir.mkdir(parents=True, exist_ok=True)
        return self._root_dir

    def notebook_path(self, notebook_id: str) -> Path:
        resolved_notebook_id = str(notebook_id or "").strip()
        _validate_notebook_id(resolved_notebook_id)
        return self._root_dir / f"{resolved_notebook_id}.json"

    def notebook_exists(self, notebook_id: str) -> bool:
        return self.notebook_path(notebook_id).exists()

    def display_name_exists(
        self,
        display_name: str,
        *,
        exclude_notebook_id: str | None = None,
    ) -> bool:
        target_name = str(display_name or "").strip().casefold()
        if not target_name:
            return False
        excluded_id = str(exclude_notebook_id or "").strip()
        for summary in self.list_summaries():
            if excluded_id and summary.notebook_id == excluded_id:
                continue
            if summary.display_name.casefold() == target_name:
                return True
        return False

    def create_notebook(
        self,
        *,
        display_name: str,
        description: str = "",
        chart_entries: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        annotation_settings: Mapping[str, Any] | None = None,
        notebook_id: str | None = None,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
    ) -> HistoricalNotebook:
        resolved_notebook_id = str(notebook_id or uuid.uuid4().hex).strip()
        _validate_notebook_id(resolved_notebook_id)

        if self.display_name_exists(
            display_name,
            exclude_notebook_id=resolved_notebook_id,
        ):
            raise ValueError(
                f"Historical notebook display_name already exists: {display_name!r}"
            )

        now_ms = int(time.time() * 1000)
        created = int(created_at_ms) if created_at_ms is not None else now_ms
        updated = int(updated_at_ms) if updated_at_ms is not None else created

        return HistoricalNotebook(
            schema_version=HISTORICAL_NOTEBOOK_SCHEMA_VERSION,
            object_type=HISTORICAL_NOTEBOOK_OBJECT_TYPE,
            notebook_id=resolved_notebook_id,
            content_hash="",
            display_name=display_name,
            description=description,
            created_at_ms=created,
            updated_at_ms=updated,
            annotation_settings=normalize_notebook_annotation_settings(
                annotation_settings
            ),
            chart_entries=tuple(dict(entry) for entry in (chart_entries or ())),
        )

    def save_notebook(
        self,
        notebook: HistoricalNotebook,
        *,
        overwrite: bool = False,
    ) -> HistoricalNotebook:
        persisted = HistoricalNotebook.from_dict(notebook.to_dict())
        path = self.notebook_path(persisted.notebook_id)

        if path.exists() and not overwrite:
            raise FileExistsError(f"Historical notebook already exists: {path}")
        if self.display_name_exists(
            persisted.display_name,
            exclude_notebook_id=persisted.notebook_id,
        ):
            raise ValueError(
                f"Historical notebook display_name already exists: {persisted.display_name!r}"
            )

        self._atomic_write_json(persisted.to_dict(), path)
        return persisted

    def update_notebook(
        self,
        *,
        notebook_id: str,
        display_name: str,
        description: str = "",
        chart_entries: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
        annotation_settings: Mapping[str, Any] | None = None,
    ) -> HistoricalNotebook:
        """Replace an existing notebook while preserving its storage identity.

        The selected notebook must already exist. The method preserves the
        original ``notebook_id`` and ``created_at_ms``, advances
        ``updated_at_ms``, recomputes the content hash through the notebook
        contract, and persists the replacement through the normal atomic
        overwrite path.
        """
        existing = self.load_notebook(notebook_id)
        updated = self.create_notebook(
            display_name=display_name,
            description=description,
            chart_entries=chart_entries,
            annotation_settings=annotation_settings,
            notebook_id=existing.notebook_id,
            created_at_ms=existing.created_at_ms,
            updated_at_ms=max(int(time.time() * 1000), existing.updated_at_ms + 1),
        )
        return self.save_notebook(updated, overwrite=True)

    def load_notebook(self, notebook_id: str) -> HistoricalNotebook:
        path = self.notebook_path(notebook_id)
        if not path.exists():
            raise FileNotFoundError(f"Historical notebook not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return notebook_from_payload(json.load(handle))

    def list_summaries(self) -> list[HistoricalNotebookSummary]:
        root = self.ensure_root_dir()
        summaries: list[HistoricalNotebookSummary] = []
        for path in sorted(root.glob("*.json")):
            try:
                notebook = self.load_notebook(path.stem)
            except Exception:
                continue
            summaries.append(
                HistoricalNotebookSummary.from_notebook(notebook, path=path)
            )
        summaries.sort(key=lambda item: (item.display_name.lower(), item.notebook_id))
        return summaries

    def delete_notebook(self, notebook_id: str) -> bool:
        path = self.notebook_path(notebook_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _atomic_write_json(self, data: dict[str, Any], target_path: Path) -> None:
        self.ensure_root_dir()
        tmp_path: Path | None = None
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="historical_notebook_",
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

        try:
            os.replace(tmp_path, target_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise


def notebook_to_payload(notebook: HistoricalNotebook) -> dict[str, Any]:
    return notebook.to_dict()


def notebook_from_payload(payload: Mapping[str, Any]) -> HistoricalNotebook:
    errors = validate_historical_notebook_payload(payload)
    if errors:
        raise ValueError("Invalid historical notebook: " + "; ".join(errors))
    return HistoricalNotebook.from_dict(payload)


def validate_historical_notebook_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping."]

    schema_version = _int_value(payload.get("schema_version"), 0)
    if schema_version != HISTORICAL_NOTEBOOK_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {schema_version}")

    if str(payload.get("object_type", "") or "") != HISTORICAL_NOTEBOOK_OBJECT_TYPE:
        errors.append("object_type must be historical_workspace_notebook.")

    notebook_id = str(payload.get("notebook_id", "") or "").strip()
    if not notebook_id:
        errors.append("notebook_id is required.")
    else:
        try:
            _validate_notebook_id(notebook_id)
        except ValueError as exc:
            errors.append(str(exc))

    if not str(payload.get("display_name", "") or "").strip():
        errors.append("display_name is required.")

    if not isinstance(payload.get("description", ""), str):
        errors.append("description must be a string.")

    if not isinstance(payload.get("created_at_ms"), int):
        errors.append("created_at_ms must be an integer.")
    if not isinstance(payload.get("updated_at_ms"), int):
        errors.append("updated_at_ms must be an integer.")

    if "annotation_settings" in payload:
        try:
            normalize_notebook_annotation_settings(payload.get("annotation_settings"))
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))

    chart_entries = payload.get("chart_entries", [])
    try:
        _validate_chart_entries_payload(chart_entries)
    except ValueError as exc:
        errors.append(str(exc))

    try:
        _require_json_serializable(payload, field_name="historical notebook")
    except TypeError as exc:
        errors.append(str(exc))

    return errors


def build_historical_notebook_content_hash(
    notebook_payload: Mapping[str, Any],
) -> str:
    content = dict(notebook_payload)
    content.pop("content_hash", None)
    normalized = _normalize_for_hash(content)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def notebook_chart_key(dataset: Mapping[str, Any]) -> str:
    """Return the durable dataset-identity key for a notebook chart entry."""
    return "|".join(
        str(dataset.get(key, "") or "").strip().lower()
        for key in _DATASET_IDENTITY_KEYS
    )


def normalize_notebook_chart_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe notebook chart entry with expected row containers."""
    dataset = _dict_or_empty(entry.get("dataset"))
    chart_key = str(entry.get("chart_key", "") or "").strip()
    if not chart_key:
        chart_key = notebook_chart_key(dataset)

    normalized = {
        "chart_key": chart_key,
        "dataset": {key: str(dataset.get(key, "") or "") for key in _DATASET_IDENTITY_KEYS},
        "last_seen_position": entry.get("last_seen_position"),
        "notes": [dict(row) for row in _sequence_or_empty(entry.get("notes"))],
        "trades": [dict(row) for row in _sequence_or_empty(entry.get("trades"))],
        "points_of_interest": [
            dict(row) for row in _sequence_or_empty(entry.get("points_of_interest"))
        ],
    }
    _validate_chart_entry(normalized, field_name="chart_entry")
    return _json_clone(normalized, field_name="chart_entry")


def normalize_notebook_annotation_settings(
    settings: Mapping[str, Any] | None,
) -> dict[str, int]:
    """Return validated notebook-level runtime annotation settings."""
    raw = {} if settings is None else _dict_or_empty(settings)
    return {
        "poi_marker_offset": _annotation_offset_value(
            raw.get("poi_marker_offset"),
            DEFAULT_POI_MARKER_OFFSET,
        ),
        "pt_long_marker_offset": _annotation_offset_value(
            raw.get("pt_long_marker_offset", raw.get("pt_marker_offset")),
            DEFAULT_PT_LONG_MARKER_OFFSET,
        ),
        "pt_short_marker_offset": _annotation_offset_value(
            raw.get("pt_short_marker_offset", raw.get("pt_marker_offset")),
            DEFAULT_PT_SHORT_MARKER_OFFSET,
        ),
    }


def _validate_notebook_id(notebook_id: str) -> None:
    value = str(notebook_id or "").strip()
    if not value or not _NOTEBOOK_ID_RE.fullmatch(value):
        raise ValueError(f"Invalid historical notebook_id: {notebook_id!r}")


def _validate_chart_entries_payload(chart_entries: Any) -> None:
    if not isinstance(chart_entries, (list, tuple)):
        raise ValueError("chart_entries must be a sequence.")
    for idx, entry in enumerate(chart_entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"chart_entries[{idx}] must be a mapping.")
        _validate_chart_entry(entry, field_name=f"chart_entries[{idx}]")


def _validate_chart_entry(entry: Mapping[str, Any], *, field_name: str) -> None:
    chart_key = str(entry.get("chart_key", "") or "").strip()
    if not chart_key:
        raise ValueError(f"{field_name}.chart_key is required.")

    dataset = entry.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError(f"{field_name}.dataset must be a mapping.")
    for key in _DATASET_IDENTITY_KEYS:
        if not str(dataset.get(key, "") or "").strip():
            raise ValueError(f"{field_name}.dataset.{key} is required.")

    if notebook_chart_key(dataset) != chart_key.lower():
        raise ValueError(f"{field_name}.chart_key must match dataset identity.")

    for rows_name in ("notes", "trades", "points_of_interest"):
        rows = entry.get(rows_name, [])
        if rows is None:
            continue
        if not isinstance(rows, (list, tuple)):
            raise ValueError(f"{field_name}.{rows_name} must be a sequence.")
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"{field_name}.{rows_name}[{row_index}] must be a mapping.")
            _validate_row_payload(
                row,
                rows_name=rows_name,
                field_name=f"{field_name}.{rows_name}[{row_index}]",
            )


def _validate_row_payload(
    row: Mapping[str, Any],
    *,
    rows_name: str,
    field_name: str,
) -> None:
    if not str(row.get("row_id", "") or "").strip():
        raise ValueError(f"{field_name}.row_id is required.")
    if "ts_ms" in row and row.get("ts_ms") is not None and not isinstance(row.get("ts_ms"), int):
        raise ValueError(f"{field_name}.ts_ms must be an integer or null.")

    if rows_name == "trades":
        direction = str(row.get("direction", "") or "").strip()
        if direction not in _VALID_TRADE_DIRECTIONS:
            raise ValueError(f"{field_name}.direction must be Long or Short.")
        outcome = str(row.get("outcome", "") or "").strip()
        if outcome not in _VALID_TRADE_OUTCOMES:
            raise ValueError(f"{field_name}.outcome must be Good or Bad.")


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected JSON object; got {type(value).__name__}")
    return dict(value)


def _sequence_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"Expected JSON sequence; got {type(value).__name__}")
    return list(value)


def _int_value(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _annotation_offset_value(value: Any, default: int) -> int:
    return max(0, min(240, _int_value(value, default)))


def _json_clone(value: Any, *, field_name: str) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _require_json_serializable(value: Any, *, field_name: str) -> None:
    try:
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_for_hash(value[key])
            for key in sorted(value.keys(), key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


__all__ = [
    "DEFAULT_POI_MARKER_OFFSET",
    "DEFAULT_PT_LONG_MARKER_OFFSET",
    "DEFAULT_PT_SHORT_MARKER_OFFSET",
    "HISTORICAL_NOTEBOOK_OBJECT_TYPE",
    "HISTORICAL_NOTEBOOK_SCHEMA_VERSION",
    "HistoricalNotebook",
    "HistoricalNotebookStore",
    "HistoricalNotebookSummary",
    "build_historical_notebook_content_hash",
    "normalize_notebook_annotation_settings",
    "normalize_notebook_chart_entry",
    "notebook_chart_key",
    "notebook_from_payload",
    "notebook_to_payload",
    "validate_historical_notebook_payload",
]
