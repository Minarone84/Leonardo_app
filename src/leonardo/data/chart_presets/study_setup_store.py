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


CHART_STUDY_SETUP_SCHEMA_VERSION = 1
CHART_STUDY_SETUP_OBJECT_TYPE = "chart_study_setup"

_SETUP_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ChartStudySetup:
    """Durable chart-local study setup payload.

    A chart study setup stores user-facing setup metadata and serialized study
    intent/style payloads. It does not store chart slots, viewport state,
    computed arrays, render keys, renderer caches, or widget identities.
    """

    schema_version: int
    object_type: str
    setup_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    created_from: dict[str, Any]
    studies: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if self.schema_version != CHART_STUDY_SETUP_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported chart study setup schema_version: {self.schema_version}"
            )
        if self.object_type != CHART_STUDY_SETUP_OBJECT_TYPE:
            raise ValueError(
                f"Unsupported chart study setup object_type: {self.object_type!r}"
            )

        setup_id = str(self.setup_id or "").strip()
        _validate_setup_id(setup_id)

        display_name = str(self.display_name or "").strip()
        if not display_name:
            raise ValueError("Chart study setup display_name is required")

        created_from = _json_clone(
            dict(self.created_from or {}),
            field_name="created_from",
        )
        studies = tuple(
            _json_clone(dict(study), field_name=f"studies[{idx}]")
            for idx, study in enumerate(self.studies or ())
        )
        if not studies:
            raise ValueError("Chart study setup requires at least one study")
        for idx, study in enumerate(studies):
            _validate_study_payload(study, field_name=f"studies[{idx}]")

        object.__setattr__(self, "setup_id", setup_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "created_at_ms", int(self.created_at_ms))
        object.__setattr__(self, "updated_at_ms", int(self.updated_at_ms))
        object.__setattr__(self, "created_from", created_from)
        object.__setattr__(self, "studies", studies)
        object.__setattr__(
            self,
            "content_hash",
            build_chart_study_setup_content_hash(self.to_dict()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "object_type": self.object_type,
            "setup_id": self.setup_id,
            "content_hash": self.content_hash,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
            "created_from": dict(self.created_from),
            "studies": [dict(study) for study in self.studies],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartStudySetup":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            object_type=str(data.get("object_type", "")),
            setup_id=str(data.get("setup_id", "")),
            content_hash=str(data.get("content_hash", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "") or ""),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
            created_from=_dict_or_empty(data.get("created_from")),
            studies=tuple(
                dict(study) for study in data.get("studies", ()) or ()
            ),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ChartStudySetupSummary:
    """List-view metadata for a persisted chart study setup."""

    setup_id: str
    display_name: str
    description: str
    created_at_ms: int
    updated_at_ms: int
    created_from: dict[str, Any]
    study_count: int
    tool_keys: tuple[str, ...]
    study_titles: tuple[str, ...]
    path: Path

    @classmethod
    def from_setup(
        cls,
        setup: ChartStudySetup,
        *,
        path: Path,
    ) -> "ChartStudySetupSummary":
        tool_keys = tuple(
            str(study.get("tool_key", "") or "").strip()
            for study in setup.studies
            if str(study.get("tool_key", "") or "").strip()
        )
        study_titles = tuple(
            str(study.get("display_name", "") or "").strip()
            for study in setup.studies
            if str(study.get("display_name", "") or "").strip()
        )
        return cls(
            setup_id=setup.setup_id,
            display_name=setup.display_name,
            description=setup.description,
            created_at_ms=setup.created_at_ms,
            updated_at_ms=setup.updated_at_ms,
            created_from=dict(setup.created_from),
            study_count=len(setup.studies),
            tool_keys=tool_keys,
            study_titles=study_titles,
            path=Path(path),
        )


class ChartStudySetupStore:
    """Persist chart study setup JSON files under an injected root directory.

    The store owns durable JSON persistence only. It does not inspect live chart
    registries, apply studies, compute tools, or construct GUI objects. Callers
    provide already-serialized study payloads and the configured storage root.
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def ensure_root_dir(self) -> Path:
        self._root_dir.mkdir(parents=True, exist_ok=True)
        return self._root_dir

    def setup_path(self, setup_id: str) -> Path:
        resolved_setup_id = str(setup_id or "").strip()
        _validate_setup_id(resolved_setup_id)
        return self._root_dir / f"{resolved_setup_id}.json"

    def setup_exists(self, setup_id: str) -> bool:
        return self.setup_path(setup_id).exists()

    def display_name_exists(
        self,
        display_name: str,
        *,
        exclude_setup_id: str | None = None,
    ) -> bool:
        target_name = str(display_name or "").strip().casefold()
        if not target_name:
            return False
        excluded_id = str(exclude_setup_id or "").strip()
        for summary in self.list_summaries():
            if excluded_id and summary.setup_id == excluded_id:
                continue
            if summary.display_name.casefold() == target_name:
                return True
        return False

    def create_setup(
        self,
        *,
        display_name: str,
        description: str = "",
        created_from: Mapping[str, Any] | None = None,
        studies: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
        setup_id: str | None = None,
        created_at_ms: int | None = None,
        updated_at_ms: int | None = None,
    ) -> ChartStudySetup:
        resolved_setup_id = str(setup_id or uuid.uuid4().hex).strip()
        _validate_setup_id(resolved_setup_id)

        if self.display_name_exists(display_name, exclude_setup_id=resolved_setup_id):
            raise ValueError(
                f"Chart study setup display_name already exists: {display_name!r}"
            )

        now_ms = int(time.time() * 1000)
        created = int(created_at_ms) if created_at_ms is not None else now_ms
        updated = int(updated_at_ms) if updated_at_ms is not None else created

        return ChartStudySetup(
            schema_version=CHART_STUDY_SETUP_SCHEMA_VERSION,
            object_type=CHART_STUDY_SETUP_OBJECT_TYPE,
            setup_id=resolved_setup_id,
            content_hash="",
            display_name=display_name,
            description=description,
            created_at_ms=created,
            updated_at_ms=updated,
            created_from=dict(created_from or {}),
            studies=tuple(dict(study) for study in studies),
        )

    def save_setup(
        self,
        setup: ChartStudySetup,
        *,
        overwrite: bool = False,
    ) -> ChartStudySetup:
        persisted = ChartStudySetup.from_dict(setup.to_dict())
        path = self.setup_path(persisted.setup_id)

        if path.exists() and not overwrite:
            raise FileExistsError(f"Chart study setup already exists: {path}")
        if self.display_name_exists(
            persisted.display_name,
            exclude_setup_id=persisted.setup_id,
        ):
            raise ValueError(
                "Chart study setup display_name already exists: "
                f"{persisted.display_name!r}"
            )

        self._atomic_write_json(persisted.to_dict(), path)
        return persisted

    def update_setup(
        self,
        *,
        setup_id: str,
        display_name: str,
        description: str = "",
        created_from: Mapping[str, Any] | None = None,
        studies: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    ) -> ChartStudySetup:
        """Replace an existing study setup while preserving its storage identity.

        The selected setup must already exist. The method preserves the original
        ``setup_id`` and ``created_at_ms``, advances ``updated_at_ms``,
        recomputes the content hash through the setup contract, and persists the
        replacement through the normal atomic overwrite path.
        """
        existing = self.load_setup(setup_id)
        updated = self.create_setup(
            display_name=display_name,
            description=description,
            created_from=dict(created_from or {}),
            studies=studies,
            setup_id=existing.setup_id,
            created_at_ms=existing.created_at_ms,
            updated_at_ms=max(int(time.time() * 1000), existing.updated_at_ms + 1),
        )
        return self.save_setup(updated, overwrite=True)

    def load_setup(self, setup_id: str) -> ChartStudySetup:
        path = self.setup_path(setup_id)
        if not path.exists():
            raise FileNotFoundError(f"Chart study setup not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return setup_from_payload(json.load(handle))

    def list_summaries(self) -> list[ChartStudySetupSummary]:
        root = self.ensure_root_dir()
        summaries: list[ChartStudySetupSummary] = []
        for path in sorted(root.glob("*.json")):
            try:
                setup = self.load_setup(path.stem)
            except Exception:
                continue
            summaries.append(ChartStudySetupSummary.from_setup(setup, path=path))
        summaries.sort(key=lambda item: (item.display_name.lower(), item.setup_id))
        return summaries

    def delete_setup(self, setup_id: str) -> bool:
        path = self.setup_path(setup_id)
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
            prefix="chart_study_setup_",
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


def setup_to_payload(setup: ChartStudySetup) -> dict[str, Any]:
    return setup.to_dict()


def setup_from_payload(payload: Mapping[str, Any]) -> ChartStudySetup:
    errors = validate_chart_study_setup_payload(payload)
    if errors:
        raise ValueError("Invalid chart study setup: " + "; ".join(errors))
    return ChartStudySetup.from_dict(payload)


def validate_chart_study_setup_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping."]

    schema_version = _int_value(payload.get("schema_version"), 0)
    if schema_version != CHART_STUDY_SETUP_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {schema_version}")

    if str(payload.get("object_type", "") or "") != CHART_STUDY_SETUP_OBJECT_TYPE:
        errors.append("object_type must be chart_study_setup.")

    setup_id = str(payload.get("setup_id", "") or "").strip()
    if not setup_id:
        errors.append("setup_id is required.")
    else:
        try:
            _validate_setup_id(setup_id)
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

    created_from = payload.get("created_from", {})
    if not isinstance(created_from, Mapping):
        errors.append("created_from must be a mapping.")

    studies = payload.get("studies", [])
    if not isinstance(studies, (list, tuple)):
        errors.append("studies must be a sequence.")
    elif not studies:
        errors.append("studies must contain at least one study.")
    else:
        for idx, study in enumerate(studies):
            if not isinstance(study, Mapping):
                errors.append(f"studies[{idx}] must be a mapping.")
                continue
            try:
                _validate_study_payload(study, field_name=f"studies[{idx}]")
            except ValueError as exc:
                errors.append(str(exc))

    try:
        _require_json_serializable(payload, field_name="chart study setup")
    except TypeError as exc:
        errors.append(str(exc))

    return errors


def build_chart_study_setup_content_hash(setup_payload: Mapping[str, Any]) -> str:
    content = dict(setup_payload)
    content.pop("content_hash", None)
    normalized = _normalize_for_hash(content)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_setup_id(setup_id: str) -> None:
    value = str(setup_id or "").strip()
    if not value or not _SETUP_ID_RE.fullmatch(value):
        raise ValueError(f"Invalid chart study setup_id: {setup_id!r}")


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
    "CHART_STUDY_SETUP_OBJECT_TYPE",
    "CHART_STUDY_SETUP_SCHEMA_VERSION",
    "ChartStudySetup",
    "ChartStudySetupStore",
    "ChartStudySetupSummary",
    "build_chart_study_setup_content_hash",
    "setup_from_payload",
    "setup_to_payload",
    "validate_chart_study_setup_payload",
]
