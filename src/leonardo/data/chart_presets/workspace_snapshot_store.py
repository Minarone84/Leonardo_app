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


HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION = 1
HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE = "historical_workspace_snapshot"

HISTORICAL_WORKSPACE_VISUALIZATION_MODES = frozenset({"scroll_4", "fit_8"})

_SNAPSHOT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_DATASET_IDENTITY_KEYS = ("exchange", "market_type", "symbol", "timeframe")


@dataclass(frozen=True)
class HistoricalWorkspaceSnapshot:
    """Durable Historical Data Manager workspace snapshot payload.

    A workspace snapshot stores user-facing metadata and prepared chart payloads
    for future workspace restoration. It does not store live chart sessions,
    resident OHLC arrays, computed study arrays, renderer caches, or Qt object
    identities.
    """

    schema_version: int
    object_type: str
    snapshot_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    workspace: dict[str, Any]
    charts: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if self.schema_version != HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported historical workspace snapshot schema_version: "
                f"{self.schema_version}"
            )
        if self.object_type != HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE:
            raise ValueError(
                "Unsupported historical workspace snapshot object_type: "
                f"{self.object_type!r}"
            )

        snapshot_id = str(self.snapshot_id or "").strip()
        _validate_snapshot_id(snapshot_id)

        display_name = str(self.display_name or "").strip()
        if not display_name:
            raise ValueError("Historical workspace snapshot display_name is required")

        workspace = _json_clone(
            dict(self.workspace or {}),
            field_name="workspace",
        )
        _validate_workspace_payload(workspace)

        charts = tuple(
            _json_clone(dict(chart), field_name=f"charts[{idx}]")
            for idx, chart in enumerate(self.charts or ())
        )
        _validate_charts_payload(charts)

        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "created_at_ms", int(self.created_at_ms))
        object.__setattr__(self, "updated_at_ms", int(self.updated_at_ms))
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "charts", charts)
        object.__setattr__(
            self,
            "content_hash",
            build_historical_workspace_snapshot_content_hash(self.to_dict()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "object_type": self.object_type,
            "snapshot_id": self.snapshot_id,
            "content_hash": self.content_hash,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
            "workspace": dict(self.workspace),
            "charts": [dict(chart) for chart in self.charts],
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "HistoricalWorkspaceSnapshot":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            object_type=str(data.get("object_type", "")),
            snapshot_id=str(data.get("snapshot_id", "")),
            content_hash=str(data.get("content_hash", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "") or ""),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
            workspace=_dict_or_empty(data.get("workspace")),
            charts=tuple(
                dict(chart) for chart in data.get("charts", ()) or ()
            ),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class HistoricalWorkspaceSnapshotSummary:
    """List-view metadata for a persisted historical workspace snapshot."""

    snapshot_id: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    workspace: dict[str, Any]
    chart_count: int
    study_count: int
    chart_summaries: tuple[dict[str, Any], ...]
    path: Path

    @classmethod
    def from_snapshot(
        cls,
        snapshot: HistoricalWorkspaceSnapshot,
        *,
        path: Path,
    ) -> "HistoricalWorkspaceSnapshotSummary":
        chart_summaries: list[dict[str, Any]] = []
        study_count = 0
        for chart in snapshot.charts:
            dataset = _dict_or_empty(chart.get("dataset"))
            studies = chart.get("studies", []) or []
            chart_study_count = len(studies) if isinstance(studies, list) else 0
            study_count += chart_study_count
            chart_summaries.append(
                {
                    "position": int(chart.get("position", 0)),
                    "exchange": str(dataset.get("exchange", "") or ""),
                    "market_type": str(dataset.get("market_type", "") or ""),
                    "symbol": str(dataset.get("symbol", "") or ""),
                    "timeframe": str(dataset.get("timeframe", "") or ""),
                    "study_count": chart_study_count,
                }
            )

        return cls(
            snapshot_id=snapshot.snapshot_id,
            display_name=snapshot.display_name,
            description=snapshot.description,
            created_at_ms=snapshot.created_at_ms,
            updated_at_ms=snapshot.updated_at_ms,
            workspace=dict(snapshot.workspace),
            chart_count=len(snapshot.charts),
            study_count=study_count,
            chart_summaries=tuple(chart_summaries),
            path=Path(path),
        )


class HistoricalWorkspaceSnapshotStore:
    """Persist historical workspace snapshot JSON files under an injected root.

    The store owns durable JSON persistence only. It does not inspect live
    workspace widgets, open charts, apply studies, compute financial tools, or
    construct GUI objects. Callers provide already-prepared snapshot payloads
    and the configured storage root.
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def ensure_root_dir(self) -> Path:
        self._root_dir.mkdir(parents=True, exist_ok=True)
        return self._root_dir

    def snapshot_path(self, snapshot_id: str) -> Path:
        resolved_snapshot_id = str(snapshot_id or "").strip()
        _validate_snapshot_id(resolved_snapshot_id)
        return self._root_dir / f"{resolved_snapshot_id}.json"

    def snapshot_exists(self, snapshot_id: str) -> bool:
        return self.snapshot_path(snapshot_id).exists()

    def display_name_exists(
        self,
        display_name: str,
        *,
        exclude_snapshot_id: str | None = None,
    ) -> bool:
        target_name = str(display_name or "").strip().casefold()
        if not target_name:
            return False
        excluded_id = str(exclude_snapshot_id or "").strip()
        for summary in self.list_summaries():
            if excluded_id and summary.snapshot_id == excluded_id:
                continue
            if summary.display_name.casefold() == target_name:
                return True
        return False

    def create_snapshot(
        self,
        *,
        display_name: str,
        description: str = "",
        workspace: Mapping[str, Any],
        charts: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
        snapshot_id: str | None = None,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
    ) -> HistoricalWorkspaceSnapshot:
        resolved_snapshot_id = str(snapshot_id or uuid.uuid4().hex).strip()
        _validate_snapshot_id(resolved_snapshot_id)

        if self.display_name_exists(
            display_name,
            exclude_snapshot_id=resolved_snapshot_id,
        ):
            raise ValueError(
                "Historical workspace snapshot display_name already exists: "
                f"{display_name!r}"
            )

        now_ms = int(time.time() * 1000)
        created = int(created_at_ms) if created_at_ms is not None else now_ms
        updated = int(updated_at_ms) if updated_at_ms is not None else created

        return HistoricalWorkspaceSnapshot(
            schema_version=HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
            object_type=HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE,
            snapshot_id=resolved_snapshot_id,
            content_hash="",
            display_name=display_name,
            description=description,
            created_at_ms=created,
            updated_at_ms=updated,
            workspace=dict(workspace),
            charts=tuple(dict(chart) for chart in charts),
        )

    def save_snapshot(
        self,
        snapshot: HistoricalWorkspaceSnapshot,
        *,
        overwrite: bool = False,
    ) -> HistoricalWorkspaceSnapshot:
        persisted = HistoricalWorkspaceSnapshot.from_dict(snapshot.to_dict())
        path = self.snapshot_path(persisted.snapshot_id)

        if path.exists() and not overwrite:
            raise FileExistsError(f"Historical workspace snapshot already exists: {path}")
        if self.display_name_exists(
            persisted.display_name,
            exclude_snapshot_id=persisted.snapshot_id,
        ):
            raise ValueError(
                "Historical workspace snapshot display_name already exists: "
                f"{persisted.display_name!r}"
            )

        self._atomic_write_json(persisted.to_dict(), path)
        return persisted

    def load_snapshot(self, snapshot_id: str) -> HistoricalWorkspaceSnapshot:
        path = self.snapshot_path(snapshot_id)
        if not path.exists():
            raise FileNotFoundError(f"Historical workspace snapshot not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return snapshot_from_payload(json.load(handle))

    def list_summaries(self) -> list[HistoricalWorkspaceSnapshotSummary]:
        root = self.ensure_root_dir()
        summaries: list[HistoricalWorkspaceSnapshotSummary] = []
        for path in sorted(root.glob("*.json")):
            try:
                snapshot = self.load_snapshot(path.stem)
            except Exception:
                continue
            summaries.append(
                HistoricalWorkspaceSnapshotSummary.from_snapshot(
                    snapshot,
                    path=path,
                )
            )
        summaries.sort(key=lambda item: (item.display_name.lower(), item.snapshot_id))
        return summaries

    def delete_snapshot(self, snapshot_id: str) -> bool:
        path = self.snapshot_path(snapshot_id)
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
            prefix="historical_workspace_snapshot_",
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


def snapshot_to_payload(snapshot: HistoricalWorkspaceSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


def snapshot_from_payload(
    payload: Mapping[str, Any],
) -> HistoricalWorkspaceSnapshot:
    errors = validate_historical_workspace_snapshot_payload(payload)
    if errors:
        raise ValueError(
            "Invalid historical workspace snapshot: " + "; ".join(errors)
        )
    return HistoricalWorkspaceSnapshot.from_dict(payload)


def validate_historical_workspace_snapshot_payload(
    payload: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping."]

    schema_version = _int_value(payload.get("schema_version"), 0)
    if schema_version != HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {schema_version}")

    if (
        str(payload.get("object_type", "") or "")
        != HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE
    ):
        errors.append("object_type must be historical_workspace_snapshot.")

    snapshot_id = str(payload.get("snapshot_id", "") or "").strip()
    if not snapshot_id:
        errors.append("snapshot_id is required.")
    else:
        try:
            _validate_snapshot_id(snapshot_id)
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

    workspace = payload.get("workspace", {})
    if not isinstance(workspace, Mapping):
        errors.append("workspace must be a mapping.")
    else:
        try:
            _validate_workspace_payload(workspace)
        except ValueError as exc:
            errors.append(str(exc))

    charts = payload.get("charts", [])
    if not isinstance(charts, (list, tuple)):
        errors.append("charts must be a sequence.")
    else:
        try:
            _validate_charts_payload(charts)
        except ValueError as exc:
            errors.append(str(exc))

    try:
        _require_json_serializable(
            payload,
            field_name="historical workspace snapshot",
        )
    except TypeError as exc:
        errors.append(str(exc))

    return errors


def build_historical_workspace_snapshot_content_hash(
    snapshot_payload: Mapping[str, Any],
) -> str:
    content = dict(snapshot_payload)
    content.pop("content_hash", None)
    normalized = _normalize_for_hash(content)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_snapshot_id(snapshot_id: str) -> None:
    value = str(snapshot_id or "").strip()
    if not value or not _SNAPSHOT_ID_RE.fullmatch(value):
        raise ValueError(f"Invalid historical workspace snapshot_id: {snapshot_id!r}")


def _validate_workspace_payload(workspace: Mapping[str, Any]) -> None:
    mode = str(workspace.get("visualization_mode", "") or "").strip()
    if mode not in HISTORICAL_WORKSPACE_VISUALIZATION_MODES:
        raise ValueError(
            "workspace.visualization_mode must be one of: "
            + ", ".join(sorted(HISTORICAL_WORKSPACE_VISUALIZATION_MODES))
        )


def _validate_charts_payload(charts: Any) -> None:
    if not isinstance(charts, (list, tuple)):
        raise ValueError("charts must be a sequence.")
    if not charts:
        raise ValueError("charts must contain at least one chart.")
    if len(charts) > 8:
        raise ValueError("charts must contain at most 8 charts.")

    positions: set[int] = set()
    for idx, chart in enumerate(charts):
        if not isinstance(chart, Mapping):
            raise ValueError(f"charts[{idx}] must be a mapping.")
        position = chart.get("position")
        if isinstance(position, bool) or not isinstance(position, int):
            raise ValueError(f"charts[{idx}].position must be an integer.")
        if position < 1 or position > 8:
            raise ValueError(f"charts[{idx}].position must be between 1 and 8.")
        if position in positions:
            raise ValueError(f"Duplicate chart position: {position}")
        positions.add(position)

        dataset = chart.get("dataset")
        if not isinstance(dataset, Mapping):
            raise ValueError(f"charts[{idx}].dataset must be a mapping.")
        for key in _DATASET_IDENTITY_KEYS:
            if not str(dataset.get(key, "") or "").strip():
                raise ValueError(f"charts[{idx}].dataset.{key} is required.")

        viewport = chart.get("viewport", {})
        if viewport is not None and not isinstance(viewport, Mapping):
            raise ValueError(f"charts[{idx}].viewport must be a mapping.")

        price_view_state = chart.get("price_view_state", {})
        if price_view_state is not None and not isinstance(price_view_state, Mapping):
            raise ValueError(f"charts[{idx}].price_view_state must be a mapping.")

        studies = chart.get("studies", [])
        if studies is None:
            studies = []
        if not isinstance(studies, (list, tuple)):
            raise ValueError(f"charts[{idx}].studies must be a sequence.")
        for study_index, study in enumerate(studies):
            if not isinstance(study, Mapping):
                raise ValueError(
                    f"charts[{idx}].studies[{study_index}] must be a mapping."
                )
            _validate_study_payload(
                study,
                field_name=f"charts[{idx}].studies[{study_index}]",
            )


def _validate_study_payload(study: Mapping[str, Any], *, field_name: str) -> None:
    if not str(study.get("family", "") or "").strip():
        raise ValueError(f"{field_name}.family is required")
    if not str(study.get("tool_key", "") or "").strip():
        raise ValueError(f"{field_name}.tool_key is required")
    if "params" not in study:
        raise ValueError(f"{field_name}.params is required")
    if not isinstance(study.get("params"), Mapping):
        raise ValueError(f"{field_name}.params must be a mapping")
    if "style" not in study:
        raise ValueError(f"{field_name}.style is required")
    if not isinstance(study.get("style"), Mapping):
        raise ValueError(f"{field_name}.style must be a mapping")


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected JSON object; got {type(value).__name__}")
    return dict(value)


def _int_value(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


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
    "HISTORICAL_WORKSPACE_SNAPSHOT_OBJECT_TYPE",
    "HISTORICAL_WORKSPACE_SNAPSHOT_SCHEMA_VERSION",
    "HISTORICAL_WORKSPACE_VISUALIZATION_MODES",
    "HistoricalWorkspaceSnapshot",
    "HistoricalWorkspaceSnapshotStore",
    "HistoricalWorkspaceSnapshotSummary",
    "build_historical_workspace_snapshot_content_hash",
    "snapshot_from_payload",
    "snapshot_to_payload",
    "validate_historical_workspace_snapshot_payload",
]
