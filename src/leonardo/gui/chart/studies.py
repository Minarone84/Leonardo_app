from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple


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

STUDY_DATASET_ROLE_UNSPECIFIED = "unspecified"
STUDY_DATASET_ROLE_CORE_GEOGRAPHY = "core_geography"
STUDY_DATASET_ROLE_VOLUME = "volume"
STUDY_DATASET_ROLE_BRAID = "braid"
STUDY_DATASET_ROLE_PEAKS_TROUGHS = "peaks_troughs"
STUDY_DATASET_ROLE_UTC = "utc"
STUDY_DATASET_ROLE_SUPPORTING_INDICATOR = "supporting_indicator"
STUDY_DATASET_ROLE_SUPPORTING_OSCILLATOR = "supporting_oscillator"
STUDY_DATASET_ROLE_SUPPORTING_CONSTRUCT = "supporting_construct"
STUDY_DATASET_ROLE_HELPER_DEPENDENCY = "helper_dependency"
STUDY_DATASET_ROLE_EXPERIMENTAL = "experimental"
STUDY_DATASET_ROLE_VISUAL_ONLY = "visual_only"

STUDY_DATASET_ROLE_VALUES: Tuple[str, ...] = (
    STUDY_DATASET_ROLE_UNSPECIFIED,
    STUDY_DATASET_ROLE_CORE_GEOGRAPHY,
    STUDY_DATASET_ROLE_VOLUME,
    STUDY_DATASET_ROLE_BRAID,
    STUDY_DATASET_ROLE_PEAKS_TROUGHS,
    STUDY_DATASET_ROLE_UTC,
    STUDY_DATASET_ROLE_SUPPORTING_INDICATOR,
    STUDY_DATASET_ROLE_SUPPORTING_OSCILLATOR,
    STUDY_DATASET_ROLE_SUPPORTING_CONSTRUCT,
    STUDY_DATASET_ROLE_HELPER_DEPENDENCY,
    STUDY_DATASET_ROLE_EXPERIMENTAL,
    STUDY_DATASET_ROLE_VISUAL_ONLY,
)


def normalize_study_dataset_role(value: object) -> str:
    """
    Normalize a persisted or user-provided study dataset role.

    Dataset roles are semantic user metadata. Unknown, empty, or missing values
    default to ``unspecified`` so older saved study payloads remain loadable.
    """

    if value is None:
        return STUDY_DATASET_ROLE_UNSPECIFIED

    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return STUDY_DATASET_ROLE_UNSPECIFIED
    if normalized in STUDY_DATASET_ROLE_VALUES:
        return normalized
    return STUDY_DATASET_ROLE_UNSPECIFIED


def normalize_study_metadata_important(value: object) -> bool:
    """
    Normalize a persisted important flag without treating arbitrary text as true.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False


@dataclass(frozen=True)
class StudyUserMetadata:
    """
    Human-authored semantic metadata attached to a chart-local study.

    The metadata is persisted with study setup and workspace snapshot payloads.
    It does not participate in computation, rendering, styling, or artifact
    identity decisions.
    """

    important: bool = False
    description: str = ""
    dataset_role: str = STUDY_DATASET_ROLE_UNSPECIFIED

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "important",
            normalize_study_metadata_important(self.important),
        )
        description = "" if self.description is None else str(self.description)
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "dataset_role",
            normalize_study_dataset_role(self.dataset_role),
        )


@dataclass(frozen=True)
class StudyComputationConfig:
    family: str
    tool_key: str
    params: Dict[str, Any] = field(default_factory=dict)
    source_kind: str = STUDY_SOURCE_TEMPORARY
    artifact_path: Optional[str] = None
    saved_artifact_name: Optional[str] = None
    input_bindings: Dict[str, Any] = field(default_factory=dict)
    input_binding_meta: Dict[str, Any] = field(default_factory=dict)
    required_inputs: Tuple[Any, ...] = field(default_factory=tuple)
    saved_artifact_ref: Optional[Dict[str, Any]] = None

    def with_params(self, params: Dict[str, Any]) -> "StudyComputationConfig":
        return replace(self, params=dict(params))


@dataclass(frozen=True)
class StudySignalStyle:
    """
    Per-signal chart-local visual style.

    This is the style container used for specific emitted signal lines inside a
    multi-signal study, for example:

    - BB middle / upper / lower
    - HCK fast_vwap / slow_vwap
    - peaks_troughs sparse event markers

    Important:
    - This is display-only state.
    - It does not alter computation.
    - It is chart-local and not persistence-oriented.
    - The field defaults are intentionally neutral compatibility values.
      They must not be treated as a source of truth for study defaults.
      Static visual defaults belong in study_style_defaults.py and should be
      seeded explicitly by the chart panel when a study is first applied.
    """
    color: str = ""
    line_width: int = 1
    line_style: str = "solid"
    visible: bool = True
    show_label: bool = True
    show_value: bool = True
    render_mode: str = "line"  # line | marker | histogram
    marker_shape: str = ""
    marker_size: int = 0
    marker_text: str = ""
    marker_text_color: str = ""
    marker_offset_px: int = 0

    def merged(self, patch: Mapping[str, Any]) -> "StudySignalStyle":
        updates: Dict[str, Any] = {}
        for key in (
            "color",
            "line_width",
            "line_style",
            "visible",
            "show_label",
            "show_value",
            "render_mode",
            "marker_shape",
            "marker_size",
            "marker_text",
            "marker_text_color",
            "marker_offset_px",
        ):
            if key in patch:
                updates[key] = patch[key]
        if not updates:
            return self
        return replace(self, **updates)


@dataclass(frozen=True)
class StudyFillStyle:
    """
    Chart-local fill configuration between two study-owned signals.

    Intended examples:
    - fill between BB upper and lower bands
    - fill between HCK fast and slow VWAP lines

    This is concrete runtime style state, not a module definition.
    More advanced conditional behavior is represented separately in style_modules.

    The field defaults are intentionally neutral compatibility values.
    Static fill defaults belong in study_style_defaults.py and should be seeded
    explicitly by the chart panel when a study is first applied.
    """
    fill_id: str
    signal_a: str
    signal_b: str
    color: str = ""
    opacity: float = 0.15
    visible: bool = True

    def merged(self, patch: Mapping[str, Any]) -> "StudyFillStyle":
        updates: Dict[str, Any] = {}
        for key in ("signal_a", "signal_b", "color", "opacity", "visible"):
            if key in patch:
                updates[key] = patch[key]
        if not updates:
            return self
        return replace(self, **updates)


@dataclass(frozen=True)
class StudyStyleModuleState:
    """
    Declarative chart-local state for one active style module instance.

    Examples:
    - conditional_line_color
    - fill_between_signals
    - directional_line_width
    - conditional_fill_color

    Important:
    - This is runtime configuration state owned by the study.
    - It is intentionally generic and UI-agnostic.
    - The rendering layer or a style resolver may interpret `config`.
    """
    module_key: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)

    def merged(self, patch: Mapping[str, Any]) -> "StudyStyleModuleState":
        updates: Dict[str, Any] = {}
        if "module_key" in patch:
            updates["module_key"] = str(patch["module_key"])
        if "enabled" in patch:
            updates["enabled"] = bool(patch["enabled"])
        if "config" in patch:
            base = dict(self.config)
            incoming = dict(patch["config"] or {})
            base.update(incoming)
            updates["config"] = base

        if not updates:
            return self
        return replace(self, **updates)


@dataclass(frozen=True)
class StudyDisplayStyle:
    """
    Top-level chart-local display style for a study instance.

    Backward-compatibility note:
    - The original single-style fields are preserved only as an internal
      fallback compatibility layer.
    - They must not be treated as a source of truth for static study defaults.
    - `signal_styles`, `fill_styles`, and `style_modules` extend the model so
      multi-signal and module-driven styling can be stored without changing
      computation or persistence behavior.
    - Static defaults must come from study_style_defaults.py and be seeded
      explicitly into chart-local study state by the chart panel.
    """
    color: str = ""
    line_width: int = 1
    line_style: str = "solid"
    visible: bool = True
    show_label: bool = True
    show_value: bool = True

    signal_styles: Dict[str, StudySignalStyle] = field(default_factory=dict)
    fill_styles: Dict[str, StudyFillStyle] = field(default_factory=dict)
    style_modules: List[StudyStyleModuleState] = field(default_factory=list)

    def merged(self, patch: Mapping[str, Any]) -> "StudyDisplayStyle":
        """
        Merge only the legacy/global study style fields.

        This preserves the original update_style() behavior so existing code does
        not accidentally mutate per-signal or module-driven state.
        """
        updates: Dict[str, Any] = {}
        for key in ("color", "line_width", "line_style", "visible", "show_label", "show_value"):
            if key in patch:
                updates[key] = patch[key]
        if not updates:
            return self
        return replace(self, **updates)

    def with_signal_style(
        self,
        signal_name: str,
        *,
        style: Optional[StudySignalStyle] = None,
        patch: Optional[Mapping[str, Any]] = None,
    ) -> "StudyDisplayStyle":
        signal_key = str(signal_name).strip()
        if not signal_key:
            raise ValueError("signal_name must not be empty.")

        signal_styles = dict(self.signal_styles)
        current = signal_styles.get(signal_key, StudySignalStyle())

        if style is not None:
            signal_styles[signal_key] = style
        elif patch is not None:
            signal_styles[signal_key] = current.merged(patch)
        else:
            signal_styles[signal_key] = current

        return replace(self, signal_styles=signal_styles)

    def without_signal_style(self, signal_name: str) -> "StudyDisplayStyle":
        signal_key = str(signal_name).strip()
        if not signal_key or signal_key not in self.signal_styles:
            return self

        signal_styles = dict(self.signal_styles)
        signal_styles.pop(signal_key, None)
        return replace(self, signal_styles=signal_styles)

    def with_fill_style(
        self,
        fill_id: str,
        *,
        fill_style: Optional[StudyFillStyle] = None,
        patch: Optional[Mapping[str, Any]] = None,
    ) -> "StudyDisplayStyle":
        resolved_fill_id = str(fill_id).strip()
        if not resolved_fill_id:
            raise ValueError("fill_id must not be empty.")

        fill_styles = dict(self.fill_styles)
        current = fill_styles.get(
            resolved_fill_id,
            StudyFillStyle(fill_id=resolved_fill_id, signal_a="", signal_b=""),
        )

        if fill_style is not None:
            fill_styles[resolved_fill_id] = fill_style
        elif patch is not None:
            fill_styles[resolved_fill_id] = current.merged(patch)
        else:
            fill_styles[resolved_fill_id] = current

        return replace(self, fill_styles=fill_styles)

    def without_fill_style(self, fill_id: str) -> "StudyDisplayStyle":
        resolved_fill_id = str(fill_id).strip()
        if not resolved_fill_id or resolved_fill_id not in self.fill_styles:
            return self

        fill_styles = dict(self.fill_styles)
        fill_styles.pop(resolved_fill_id, None)
        return replace(self, fill_styles=fill_styles)

    def with_style_modules(self, modules: Iterable[StudyStyleModuleState]) -> "StudyDisplayStyle":
        return replace(self, style_modules=list(modules))

    def upsert_style_module(
        self,
        module_key: str,
        *,
        enabled: Optional[bool] = None,
        config_patch: Optional[Mapping[str, Any]] = None,
    ) -> "StudyDisplayStyle":
        resolved_module_key = str(module_key).strip()
        if not resolved_module_key:
            raise ValueError("module_key must not be empty.")

        modules = list(self.style_modules)

        for idx, module in enumerate(modules):
            if module.module_key != resolved_module_key:
                continue

            patch: Dict[str, Any] = {}
            if enabled is not None:
                patch["enabled"] = bool(enabled)
            if config_patch is not None:
                patch["config"] = dict(config_patch)

            modules[idx] = module.merged(patch)
            return replace(self, style_modules=modules)

        modules.append(
            StudyStyleModuleState(
                module_key=resolved_module_key,
                enabled=True if enabled is None else bool(enabled),
                config=dict(config_patch or {}),
            )
        )
        return replace(self, style_modules=modules)

    def remove_style_module(self, module_key: str) -> "StudyDisplayStyle":
        resolved_module_key = str(module_key).strip()
        if not resolved_module_key:
            return self

        modules = [module for module in self.style_modules if module.module_key != resolved_module_key]
        if len(modules) == len(self.style_modules):
            return self
        return replace(self, style_modules=modules)


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
    pane_target: Optional[str]
    display_name: str
    computation: StudyComputationConfig
    style: StudyDisplayStyle = field(default_factory=StudyDisplayStyle)
    runtime: ChartStudyRuntimeState = field(default_factory=ChartStudyRuntimeState)
    user_metadata: StudyUserMetadata = field(default_factory=StudyUserMetadata)

    def __post_init__(self) -> None:
        family = str(self.computation.family).strip().lower()
        pane_target = str(self.pane_target).strip().lower() if self.pane_target is not None else None

        if pane_target not in {None, PANE_TARGET_PRICE, PANE_TARGET_OSCILLATOR}:
            raise ValueError(f"Invalid pane_target for ChartStudyInstance: {self.pane_target!r}")

        if family == STUDY_FAMILY_OSCILLATOR and pane_target != PANE_TARGET_OSCILLATOR:
            raise ValueError("Oscillator studies must use pane_target='oscillator'.")

        if family == STUDY_FAMILY_INDICATOR and pane_target != PANE_TARGET_PRICE:
            raise ValueError("Indicator studies must use pane_target='price'.")

        if family == STUDY_FAMILY_CONSTRUCT and pane_target not in {
            None,
            PANE_TARGET_PRICE,
            PANE_TARGET_OSCILLATOR,
        }:
            raise ValueError("Construct studies must use pane_target None, 'price', or 'oscillator'.")

    def with_display_name(self, display_name: str) -> "ChartStudyInstance":
        return replace(self, display_name=str(display_name).strip() or self.display_name)

    def with_computation(self, computation: StudyComputationConfig) -> "ChartStudyInstance":
        return replace(self, computation=computation)

    def with_style(self, style: StudyDisplayStyle) -> "ChartStudyInstance":
        return replace(self, style=style)

    def with_runtime(self, runtime: ChartStudyRuntimeState) -> "ChartStudyInstance":
        return replace(self, runtime=runtime)

    def with_user_metadata(self, user_metadata: StudyUserMetadata) -> "ChartStudyInstance":
        return replace(self, user_metadata=user_metadata)

    def is_renderable(self) -> bool:
        return bool(self.runtime.render_keys)


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
        return [item for item in self if str(item.pane_target or "").strip().lower() == pane]

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

    def update_signal_style(
        self,
        instance_id: str,
        *,
        signal_name: str,
        patch: Optional[Mapping[str, Any]] = None,
        style: Optional[StudySignalStyle] = None,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated_style = study.style.with_signal_style(signal_name, style=style, patch=patch)
        updated = study.with_style(updated_style)
        self._items[instance_id] = updated
        return updated

    def remove_signal_style(self, instance_id: str, *, signal_name: str) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_style(study.style.without_signal_style(signal_name))
        self._items[instance_id] = updated
        return updated

    def update_fill_style(
        self,
        instance_id: str,
        *,
        fill_id: str,
        patch: Optional[Mapping[str, Any]] = None,
        fill_style: Optional[StudyFillStyle] = None,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated_style = study.style.with_fill_style(fill_id, fill_style=fill_style, patch=patch)
        updated = study.with_style(updated_style)
        self._items[instance_id] = updated
        return updated

    def remove_fill_style(self, instance_id: str, *, fill_id: str) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_style(study.style.without_fill_style(fill_id))
        self._items[instance_id] = updated
        return updated

    def set_style_modules(
        self,
        instance_id: str,
        modules: Iterable[StudyStyleModuleState],
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_style(study.style.with_style_modules(modules))
        self._items[instance_id] = updated
        return updated

    def upsert_style_module(
        self,
        instance_id: str,
        *,
        module_key: str,
        enabled: Optional[bool] = None,
        config_patch: Optional[Mapping[str, Any]] = None,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated_style = study.style.upsert_style_module(
            module_key,
            enabled=enabled,
            config_patch=config_patch,
        )
        updated = study.with_style(updated_style)
        self._items[instance_id] = updated
        return updated

    def remove_style_module(self, instance_id: str, *, module_key: str) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_style(study.style.remove_style_module(module_key))
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

    def update_user_metadata(
        self,
        instance_id: str,
        user_metadata: StudyUserMetadata,
    ) -> ChartStudyInstance:
        study = self.require(instance_id)
        updated = study.with_user_metadata(user_metadata)
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
