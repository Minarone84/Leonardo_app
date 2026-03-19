from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Iterator, List, Optional


STUDY_FAMILY_INDICATOR = "indicator"
STUDY_FAMILY_OSCILLATOR = "oscillator"
STUDY_FAMILY_CONSTRUCT = "construct"

STUDY_SOURCE_TEMPORARY = "temporary"
STUDY_SOURCE_SAVED_LINKED = "saved-linked"
STUDY_SOURCE_SAVED_LOADED = "saved-loaded"

STUDY_RUNTIME_ACTIVE = "active"
STUDY_RUNTIME_HIDDEN = "hidden"
STUDY_RUNTIME_UPDATING = "updating"
STUDY_RUNTIME_ERROR = "error"

PANE_TARGET_PRICE = "price"
PANE_TARGET_OSCILLATOR = "oscillator"


@dataclass(frozen=True)
class StudyComputationConfig:
    family: str
    tool_key: str
    params: Dict[str, Any] = field(default_factory=dict)
    source_kind: str = STUDY_SOURCE_TEMPORARY
    artifact_path: Optional[str] = None
    saved_artifact_name: Optional[str] = None

    def with_params(self, params: Dict[str, Any]) -> "StudyComputationConfig":
        return replace(self, params=dict(params))


@dataclass(frozen=True)
class StudyDisplayStyle:
    color: str = "#3B82F6"
    line_width: int = 2
    line_style: str = "solid"
    visible: bool = True
    show_label: bool = True
    show_value: bool = True

    def merged(self, patch: Dict[str, Any]) -> "StudyDisplayStyle":
        updates: Dict[str, Any] = {}
        for key in ("color", "line_width", "line_style", "visible", "show_label", "show_value"):
            if key in patch:
                updates[key] = patch[key]
        if not updates:
            return self
        return replace(self, **updates)


@dataclass(frozen=True)
class ChartStudyRuntimeState:
    last_value: Optional[float] = None
    selected: bool = False
    status: str = STUDY_RUNTIME_ACTIVE
    error_text: Optional[str] = None
    render_keys: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChartStudyInstance:
    instance_id: str
    dataset_id: str
    pane_target: str
    display_name: str
    computation: StudyComputationConfig
    style: StudyDisplayStyle = field(default_factory=StudyDisplayStyle)
    runtime: ChartStudyRuntimeState = field(default_factory=ChartStudyRuntimeState)

    def with_display_name(self, display_name: str) -> "ChartStudyInstance":
        return replace(self, display_name=str(display_name).strip() or self.display_name)

    def with_computation(self, computation: StudyComputationConfig) -> "ChartStudyInstance":
        return replace(self, computation=computation)

    def with_style(self, style: StudyDisplayStyle) -> "ChartStudyInstance":
        return replace(self, style=style)

    def with_runtime(self, runtime: ChartStudyRuntimeState) -> "ChartStudyInstance":
        return replace(self, runtime=runtime)


class ChartStudyRegistry:
    """
    Chart-session-local registry of displayed study instances.

    This object is intentionally GUI-agnostic and persistence-agnostic.
    It only tracks which studies currently belong to a chart session,
    their order, and their current chart-local definitions.
    """

    def __init__(self) -> None:
        self._items: Dict[str, ChartStudyInstance] = {}
        self._order: List[str] = []

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, instance_id: object) -> bool:
        if not isinstance(instance_id, str):
            return False
        return instance_id in self._items

    def __iter__(self) -> Iterator[ChartStudyInstance]:
        for instance_id in self._order:
            item = self._items.get(instance_id)
            if item is not None:
                yield item

    def clear(self) -> None:
        self._items.clear()
        self._order.clear()

    def ids(self) -> List[str]:
        return list(self._order)

    def list_all(self) -> List[ChartStudyInstance]:
        return list(iter(self))

    def list_for_pane(self, pane_target: str) -> List[ChartStudyInstance]:
        pane = str(pane_target).strip().lower()
        return [item for item in self if item.pane_target == pane]

    def get(self, instance_id: str) -> Optional[ChartStudyInstance]:
        return self._items.get(instance_id)

    def add(self, study: ChartStudyInstance, *, replace_existing: bool = True) -> ChartStudyInstance:
        instance_id = str(study.instance_id).strip()
        if not instance_id:
            raise ValueError("ChartStudyInstance.instance_id must not be empty.")

        existing = self._items.get(instance_id)
        if existing is not None and not replace_existing:
            raise ValueError(f"Study instance already exists: {instance_id}")

        self._items[instance_id] = study
        if existing is None:
            self._order.append(instance_id)
        return study

    def remove(self, instance_id: str) -> Optional[ChartStudyInstance]:
        removed = self._items.pop(instance_id, None)
        if removed is None:
            return None
        try:
            self._order.remove(instance_id)
        except ValueError:
            pass
        return removed

    def update_style(self, instance_id: str, patch: Dict[str, Any]) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_style(study.style.merged(patch))
        self._items[instance_id] = updated
        return updated

    def update_inputs(
        self,
        instance_id: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None,
        source_kind: Optional[str] = None,
        artifact_path: Optional[str] = None,
        saved_artifact_name: Optional[str] = None,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        computation = study.computation

        if params is not None:
            computation = computation.with_params(params)
        if source_kind is not None:
            computation = replace(computation, source_kind=source_kind)
        if artifact_path is not None:
            computation = replace(computation, artifact_path=artifact_path)
        if saved_artifact_name is not None:
            computation = replace(computation, saved_artifact_name=saved_artifact_name)

        updated = study.with_computation(computation)
        if display_name is not None:
            updated = updated.with_display_name(display_name)

        self._items[instance_id] = updated
        return updated

    def update_runtime(
        self,
        instance_id: str,
        *,
        last_value: Optional[float] = None,
        selected: Optional[bool] = None,
        status: Optional[str] = None,
        error_text: Optional[str] = None,
        render_keys: Optional[List[str]] = None,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        runtime = study.runtime

        if last_value is not None:
            runtime = replace(runtime, last_value=last_value)
        if selected is not None:
            runtime = replace(runtime, selected=bool(selected))
        if status is not None:
            runtime = replace(runtime, status=status)
        if error_text is not None:
            runtime = replace(runtime, error_text=error_text)
        if render_keys is not None:
            runtime = replace(runtime, render_keys=list(render_keys))

        updated = study.with_runtime(runtime)
        self._items[instance_id] = updated
        return updated

    def select_only(self, instance_id: Optional[str]) -> List[ChartStudyInstance]:
        selected_id = str(instance_id).strip() if instance_id else ""
        updated_items: List[ChartStudyInstance] = []

        for current_id in list(self._order):
            study = self._items[current_id]
            should_select = bool(selected_id) and current_id == selected_id
            if study.runtime.selected == should_select:
                updated_items.append(study)
                continue

            updated = study.with_runtime(replace(study.runtime, selected=should_select))
            self._items[current_id] = updated
            updated_items.append(updated)

        return updated_items

    def require(self, instance_id: str) -> ChartStudyInstance:
        study = self.get(instance_id)
        if study is None:
            raise KeyError(f"Unknown study instance: {instance_id}")
        return study

    def replace_all(self, studies: Iterable[ChartStudyInstance]) -> None:
        self.clear()
        for study in studies:
            self.add(study)