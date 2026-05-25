from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from leonardo.data.chart_presets.study_setup_store import (
    ChartStudySetup,
    ChartStudySetupStore,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
    market_to_dict,
)
from leonardo.data.naming import MarketId, canonicalize
from leonardo.financial_tools.ft_specs import (
    OutputSignalSpec,
    format_output_names,
    format_output_signals,
    get_tool_spec,
)
from leonardo.gui.chart.study_serialization import (
    deserialize_chart_study_payload,
    deserialize_study_user_metadata_payload,
)


STUDY_EXPORT_STATUS_EXPORTABLE = "exportable"
STUDY_EXPORT_STATUS_CONDITIONAL = "conditional"
STUDY_EXPORT_STATUS_BLOCKED = "blocked"
STUDY_EXPORT_STATUS_SKIPPED = "skipped"

STUDY_EXPORT_SAVE_STATUS_SAVED = "saved"
STUDY_EXPORT_SAVE_STATUS_SKIPPED = "skipped"
STUDY_EXPORT_SAVE_STATUS_FAILED = "failed"
STUDY_EXPORT_SAVE_STATUS_BLOCKED = "blocked"

_SUPPORTED_STATUSES = {
    STUDY_EXPORT_STATUS_EXPORTABLE,
    STUDY_EXPORT_STATUS_CONDITIONAL,
    STUDY_EXPORT_STATUS_BLOCKED,
    STUDY_EXPORT_STATUS_SKIPPED,
}

_SUPPORTED_SAVE_STATUSES = {
    STUDY_EXPORT_SAVE_STATUS_SAVED,
    STUDY_EXPORT_SAVE_STATUS_SKIPPED,
    STUDY_EXPORT_SAVE_STATUS_FAILED,
    STUDY_EXPORT_SAVE_STATUS_BLOCKED,
}


@dataclass(frozen=True)
class StudyRecipeExportBlocker:
    """Structured blocker emitted by a study setup recipe export plan."""

    blocker_id: str
    study_index: int | None
    reason: str
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "study_index": self.study_index,
            "reason": self.reason,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudyRecipeExportCandidate:
    """Planning result for one serialized chart study in a setup."""

    candidate_id: str
    study_index: int
    study_display_name: str
    family: str
    tool_key: str
    important: bool
    description: str
    dataset_role: str
    status: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    recipe_payload: dict[str, Any] | None
    dependency_notes: tuple[str, ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in _SUPPORTED_STATUSES:
            raise ValueError(f"Unsupported study export status: {self.status!r}")
        object.__setattr__(self, "reasons", tuple(str(item) for item in self.reasons))
        object.__setattr__(
            self,
            "warnings",
            tuple(str(item) for item in self.warnings),
        )
        object.__setattr__(
            self,
            "dependency_notes",
            tuple(str(item) for item in self.dependency_notes),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.recipe_payload is not None:
            object.__setattr__(self, "recipe_payload", dict(self.recipe_payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "study_index": int(self.study_index),
            "study_display_name": self.study_display_name,
            "family": self.family,
            "tool_key": self.tool_key,
            "important": bool(self.important),
            "description": self.description,
            "dataset_role": self.dataset_role,
            "status": self.status,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "recipe_payload": (
                _json_safe(self.recipe_payload)
                if self.recipe_payload is not None
                else None
            ),
            "dependency_notes": list(self.dependency_notes),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudyRecipeCollectionDraft:
    """Read-only preview of a possible recipe collection export."""

    display_name: str
    source_market: dict[str, str] | None
    recipe_payloads: tuple[dict[str, Any], ...]
    dependency_edges: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "recipe_payloads",
            tuple(dict(item) for item in self.recipe_payloads),
        )
        object.__setattr__(
            self,
            "dependency_edges",
            tuple(dict(item) for item in self.dependency_edges),
        )
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "source_market": (
                dict(self.source_market) if self.source_market is not None else None
            ),
            "recipe_payloads": [_json_safe(item) for item in self.recipe_payloads],
            "dependency_edges": [_json_safe(item) for item in self.dependency_edges],
            "warnings": list(self.warnings),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudySetupRecipeExportPlan:
    """Read-only recipe export plan for a saved chart study setup."""

    plan_id: str
    created_at_utc: str
    setup_id: str
    setup_display_name: str
    source_market: dict[str, str] | None
    important_only: bool
    candidates: tuple[StudyRecipeExportCandidate, ...]
    blockers: tuple[StudyRecipeExportBlocker, ...]
    warnings: tuple[str, ...]
    collection_draft: StudyRecipeCollectionDraft | None
    summary: dict[str, int]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "summary", dict(self.summary))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "setup_id": self.setup_id,
            "setup_display_name": self.setup_display_name,
            "source_market": (
                dict(self.source_market) if self.source_market is not None else None
            ),
            "important_only": bool(self.important_only),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "warnings": list(self.warnings),
            "collection_draft": (
                self.collection_draft.to_dict()
                if self.collection_draft is not None
                else None
            ),
            "summary": dict(self.summary),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudyRecipeExportPersistenceBlocker:
    """Structured blocker emitted while persisting a study setup export plan."""

    blocker_id: str
    candidate_id: str | None
    reason: str
    message: str
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "candidate_id": self.candidate_id,
            "reason": self.reason,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudyRecipeExportSaveResult:
    """Persistence result for one selected recipe export candidate."""

    candidate_id: str
    study_index: int | None
    status: str
    recipe_id: str | None
    message: str
    error: str | None
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in _SUPPORTED_SAVE_STATUSES:
            raise ValueError(f"Unsupported study export save status: {self.status!r}")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "study_index": self.study_index,
            "status": self.status,
            "recipe_id": self.recipe_id,
            "message": self.message,
            "error": self.error,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class StudySetupRecipeExportPersistenceReport:
    """JSON-safe report returned after persisting selected export candidates."""

    report_id: str
    plan_id: str
    created_at_utc: str
    requested_candidate_ids: tuple[str, ...]
    saved_recipe_ids: tuple[str, ...]
    skipped_candidate_ids: tuple[str, ...]
    failed_candidate_ids: tuple[str, ...]
    saved_collection_id: str | None
    results: tuple[StudyRecipeExportSaveResult, ...]
    blockers: tuple[StudyRecipeExportPersistenceBlocker, ...]
    warnings: tuple[str, ...]
    summary: dict[str, int]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_candidate_ids",
            tuple(str(item) for item in self.requested_candidate_ids),
        )
        object.__setattr__(
            self,
            "saved_recipe_ids",
            tuple(str(item) for item in self.saved_recipe_ids),
        )
        object.__setattr__(
            self,
            "skipped_candidate_ids",
            tuple(str(item) for item in self.skipped_candidate_ids),
        )
        object.__setattr__(
            self,
            "failed_candidate_ids",
            tuple(str(item) for item in self.failed_candidate_ids),
        )
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "summary", dict(self.summary))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "requested_candidate_ids": list(self.requested_candidate_ids),
            "saved_recipe_ids": list(self.saved_recipe_ids),
            "skipped_candidate_ids": list(self.skipped_candidate_ids),
            "failed_candidate_ids": list(self.failed_candidate_ids),
            "saved_collection_id": self.saved_collection_id,
            "results": [result.to_dict() for result in self.results],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "warnings": list(self.warnings),
            "summary": dict(self.summary),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class _StudyRef:
    index: int
    raw_payload: dict[str, Any]
    payload: dict[str, Any] | None
    family: str
    tool_key: str
    display_name: str
    important: bool
    description: str
    dataset_role: str
    validation_error: str | None


class StudySetupRecipeExportPlanner:
    """Build read-only recipe export plans from saved chart study setups.

    The planner maps durable chart-study intent into Data Manager recipe payload
    previews. It does not persist recipes, persist collections, calculate
    artifacts, rebuild databases, or mutate chart preset files.
    """

    def __init__(
        self,
        *,
        historical_root: Path | None = None,
        setup_store: ChartStudySetupStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root or ".")
        self._setup_store = setup_store
        self._recipe_store = ArtifactRecipeStore(historical_root=self._historical_root)

    def plan_study_setup_export(
        self,
        setup: ChartStudySetup,
        *,
        important_only: bool = False,
        target_market: Mapping[str, str] | None = None,
    ) -> StudySetupRecipeExportPlan:
        """Return a JSON-safe read-only export plan for one study setup."""

        market, market_warning = self._resolve_market(
            setup_created_from=setup.created_from,
            target_market=target_market,
        )
        source_market = market_to_dict(market) if market is not None else None
        study_refs = tuple(
            self._study_ref(index=index, raw_payload=study)
            for index, study in enumerate(setup.studies)
        )

        blockers: list[StudyRecipeExportBlocker] = []
        warnings: list[str] = []
        if market_warning:
            warnings.append(market_warning)
        if market is None:
            blockers.append(
                StudyRecipeExportBlocker(
                    blocker_id=f"{setup.setup_id}__missing_market_identity",
                    study_index=None,
                    reason="missing_market_identity",
                    message=(
                        "Study setup export planning requires exchange, market_type, "
                        "symbol, and timeframe from setup.created_from or target_market."
                    ),
                    metadata={"setup_id": setup.setup_id},
                )
            )

        candidates: list[StudyRecipeExportCandidate] = []
        for ref in study_refs:
            candidate = self._plan_study(
                setup=setup,
                ref=ref,
                study_refs=study_refs,
                important_only=important_only,
                market=market,
            )
            candidates.append(candidate)
            if candidate.status == STUDY_EXPORT_STATUS_BLOCKED:
                for reason in candidate.reasons:
                    blockers.append(
                        StudyRecipeExportBlocker(
                            blocker_id=f"{candidate.candidate_id}__{reason}",
                            study_index=ref.index,
                            reason=reason,
                            message=self._blocker_message(reason),
                            metadata={
                                "candidate_id": candidate.candidate_id,
                                "tool_key": candidate.tool_key,
                                "family": candidate.family,
                            },
                        )
                    )

        collection_draft = self._collection_draft(
            setup=setup,
            source_market=source_market,
            candidates=tuple(candidates),
            important_only=important_only,
        )
        summary = self._summary(candidates)
        plan_metadata = {
            "source_setup_content_hash": setup.content_hash,
            "total_studies": len(study_refs),
        }

        return StudySetupRecipeExportPlan(
            plan_id=self._plan_id(
                setup=setup,
                important_only=important_only,
                source_market=source_market,
            ),
            created_at_utc=_utc_now(),
            setup_id=setup.setup_id,
            setup_display_name=setup.display_name,
            source_market=source_market,
            important_only=bool(important_only),
            candidates=tuple(candidates),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            collection_draft=collection_draft,
            summary=summary,
            metadata=plan_metadata,
        )

    def plan_study_setup_export_by_id(
        self,
        setup_id: str,
        *,
        important_only: bool = False,
        target_market: Mapping[str, str] | None = None,
    ) -> StudySetupRecipeExportPlan:
        """Load one setup by id from the configured store and plan it."""

        if self._setup_store is None:
            raise ValueError("setup_store is required for plan_study_setup_export_by_id")
        setup = self._setup_store.load_setup(setup_id)
        return self.plan_study_setup_export(
            setup,
            important_only=important_only,
            target_market=target_market,
        )

    def _plan_study(
        self,
        *,
        setup: ChartStudySetup,
        ref: _StudyRef,
        study_refs: tuple[_StudyRef, ...],
        important_only: bool,
        market: MarketId | None,
    ) -> StudyRecipeExportCandidate:
        if important_only and not ref.important:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_SKIPPED,
                reasons=("not_marked_important",),
            )

        warnings = list(self._metadata_warnings(ref))
        if ref.validation_error:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=("invalid_serialized_study",),
                warnings=tuple(warnings),
                metadata={"validation_error": ref.validation_error},
            )

        if market is None:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=("missing_market_identity",),
                warnings=tuple(warnings),
            )

        try:
            spec = get_tool_spec(ref.tool_key)
        except KeyError:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=("missing_tool_spec",),
                warnings=tuple(warnings),
            )

        tool_type = _normalize_tool_type(ref.family)
        if tool_type is None or tool_type != spec.kind:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=("unsupported_tool_for_recipe_export",),
                warnings=tuple(warnings),
                metadata={"spec_kind": spec.kind},
            )

        assert ref.payload is not None
        params = _mapping_or_empty(ref.payload.get("params"))
        try:
            _require_json_serializable(params, field_name="params")
        except TypeError as exc:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=("params_not_json_safe",),
                warnings=tuple(warnings),
                metadata={"error": str(exc)},
            )

        if ref.tool_key == "universal_trend_classifier":
            return self._plan_utc_study(
                setup=setup,
                ref=ref,
                study_refs=study_refs,
                important_only=important_only,
                warnings=tuple(warnings),
            )

        if tool_type == "construct":
            construct_status = self._construct_source_status(ref.payload)
            if construct_status.reason is not None:
                return self._candidate(
                    setup=setup,
                    ref=ref,
                    status=construct_status.status,
                    reasons=(construct_status.reason,),
                    warnings=tuple(warnings),
                    dependency_notes=construct_status.dependency_notes,
                )

        recipe_payload, recipe_metadata, payload_warnings, reason = (
            self._build_recipe_preview_payload(
                market=market,
                tool_type=tool_type,
                tool_key=ref.tool_key,
                tool_title=spec.title,
                params=params,
                input_bindings=(
                    _mapping_or_empty(ref.payload.get("input_bindings"))
                    if tool_type == "construct"
                    else {}
                ),
                input_binding_meta=(
                    _mapping_or_empty(ref.payload.get("input_binding_meta"))
                    if tool_type == "construct"
                    else {}
                ),
                required_inputs=tuple(inp.name for inp in spec.data_inputs),
                spec=spec,
            )
        )
        warnings.extend(payload_warnings)
        if reason is not None:
            return self._candidate(
                setup=setup,
                ref=ref,
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reasons=(reason,),
                warnings=tuple(warnings),
            )

        return self._candidate(
            setup=setup,
            ref=ref,
            status=STUDY_EXPORT_STATUS_EXPORTABLE,
            warnings=tuple(warnings),
            recipe_payload=recipe_payload,
            metadata=recipe_metadata,
        )

    def _plan_utc_study(
        self,
        *,
        setup: ChartStudySetup,
        ref: _StudyRef,
        study_refs: tuple[_StudyRef, ...],
        important_only: bool,
        warnings: tuple[str, ...],
    ) -> StudyRecipeExportCandidate:
        peaks_refs = tuple(
            item for item in study_refs if item.tool_key == "peaks_troughs"
        )
        selected_peaks_refs = tuple(
            item
            for item in peaks_refs
            if not important_only or item.important
        )
        if peaks_refs and not selected_peaks_refs:
            dependency_notes = (
                "Universal Trend Classifier requires Peaks & Troughs, but the "
                "available Peaks & Troughs study is not selected by important-only filtering.",
            )
            reason = "required_dependency_not_selected"
        elif peaks_refs:
            dependency_notes = (
                "Universal Trend Classifier requires a saved Peaks & Troughs artifact. "
                "The setup contains a Peaks & Troughs study, but B1 does not resolve "
                "study-to-artifact dependencies yet.",
            )
            reason = "unresolved_dependency"
        else:
            dependency_notes = (
                "Universal Trend Classifier requires a saved Peaks & Troughs artifact "
                "for the target market before save-only calculation can run.",
            )
            reason = "unresolved_dependency"
        return self._candidate(
            setup=setup,
            ref=ref,
            status=STUDY_EXPORT_STATUS_CONDITIONAL,
            reasons=(reason,),
            warnings=warnings,
            dependency_notes=dependency_notes,
        )

    def _build_recipe_preview_payload(
        self,
        *,
        market: MarketId,
        tool_type: str,
        tool_key: str,
        tool_title: str,
        params: Mapping[str, Any],
        input_bindings: Mapping[str, Any],
        input_binding_meta: Mapping[str, Any],
        required_inputs: tuple[str, ...],
        spec: Any,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], tuple[str, ...], str | None]:
        preview_params = dict(params)
        if tool_type == "construct":
            for key, value in input_bindings.items():
                preview_params.setdefault(str(key), value)

        try:
            output_names = tuple(format_output_names(spec, preview_params))
            output_signals = tuple(format_output_signals(spec, preview_params))
        except Exception as exc:
            return None, {"error": str(exc)}, (), "output_names_unavailable"

        if not output_names:
            return None, {}, (), "output_names_unavailable"

        payload = {
            "tool_type": tool_type,
            "tool_key": tool_key,
            "tool_title": tool_title,
            "exchange": market.exchange,
            "market_type": market.market_type,
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "params": _json_safe(preview_params),
            "input_bindings": _json_safe(dict(input_bindings)),
            "input_binding_meta": _json_safe(dict(input_binding_meta)),
            "required_inputs": list(required_inputs),
            "output_names": list(output_names),
            "output_signals": [
                _output_signal_payload(signal)
                for signal in output_signals
            ],
        }
        try:
            recipe = self._recipe_store.build_recipe_from_payload(
                payload,
                created_at_ms=0,
                updated_at_ms=0,
            )
        except Exception as exc:
            return None, {"error": str(exc)}, (), "unsupported_tool_for_recipe_export"

        metadata = {
            "recipe_id": recipe.recipe_id,
            "recipe_hash": recipe.recipe_hash,
            "recipe_hash_short": recipe.recipe_hash_short,
            "recipe_display_name": recipe.display_name,
        }
        return recipe.to_payload(), metadata, (), None

    def _collection_draft(
        self,
        *,
        setup: ChartStudySetup,
        source_market: dict[str, str] | None,
        candidates: tuple[StudyRecipeExportCandidate, ...],
        important_only: bool,
    ) -> StudyRecipeCollectionDraft | None:
        recipe_payloads = tuple(
            candidate.recipe_payload
            for candidate in candidates
            if candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
            and candidate.recipe_payload is not None
        )
        if not recipe_payloads:
            return None

        blocked_or_conditional = tuple(
            candidate
            for candidate in candidates
            if candidate.status
            in {STUDY_EXPORT_STATUS_BLOCKED, STUDY_EXPORT_STATUS_CONDITIONAL}
        )
        warnings = tuple(
            f"{candidate.study_display_name}: {', '.join(candidate.reasons)}"
            for candidate in blocked_or_conditional
            if candidate.reasons
        )
        return StudyRecipeCollectionDraft(
            display_name=f"{setup.display_name} recipe export preview",
            source_market=source_market,
            recipe_payloads=recipe_payloads,
            dependency_edges=(),
            warnings=warnings,
            metadata={
                "source_setup_id": setup.setup_id,
                "source_setup_display_name": setup.display_name,
                "important_only": bool(important_only),
                "candidate_ids": [
                    candidate.candidate_id
                    for candidate in candidates
                    if candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
                ],
            },
        )

    def _candidate(
        self,
        *,
        setup: ChartStudySetup,
        ref: _StudyRef,
        status: str,
        reasons: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        recipe_payload: dict[str, Any] | None = None,
        dependency_notes: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> StudyRecipeExportCandidate:
        candidate_metadata = {
            "source_setup_id": setup.setup_id,
            "source_setup_display_name": setup.display_name,
            "source_study_index": ref.index,
            "source_study_user_metadata": {
                "important": ref.important,
                "description": ref.description,
                "dataset_role": ref.dataset_role,
            },
        }
        candidate_metadata.update(dict(metadata or {}))
        return StudyRecipeExportCandidate(
            candidate_id=f"{setup.setup_id}__study_{ref.index}",
            study_index=ref.index,
            study_display_name=ref.display_name,
            family=ref.family,
            tool_key=ref.tool_key,
            important=ref.important,
            description=ref.description,
            dataset_role=ref.dataset_role,
            status=status,
            reasons=reasons,
            warnings=warnings,
            recipe_payload=recipe_payload,
            dependency_notes=dependency_notes,
            metadata=candidate_metadata,
        )

    def _study_ref(self, *, index: int, raw_payload: Mapping[str, Any]) -> _StudyRef:
        raw = dict(raw_payload)
        metadata = deserialize_study_user_metadata_payload(
            _mapping_or_empty(raw.get("user_metadata"))
        )
        family = str(raw.get("family", "") or "").strip().lower()
        tool_key = str(raw.get("tool_key", "") or "").strip().lower()
        display_name = str(raw.get("display_name", "") or "").strip() or tool_key
        try:
            payload = deserialize_chart_study_payload(raw)
            family = str(payload.get("family", family) or family).strip().lower()
            tool_key = str(payload.get("tool_key", tool_key) or tool_key).strip().lower()
            display_name = (
                str(payload.get("display_name", display_name) or display_name).strip()
                or tool_key
            )
            validation_error = None
        except ValueError as exc:
            payload = None
            validation_error = str(exc)

        return _StudyRef(
            index=index,
            raw_payload=raw,
            payload=payload,
            family=family,
            tool_key=tool_key,
            display_name=display_name,
            important=bool(metadata.important),
            description=str(metadata.description or ""),
            dataset_role=str(metadata.dataset_role or "unspecified"),
            validation_error=validation_error,
        )

    def _resolve_market(
        self,
        *,
        setup_created_from: Mapping[str, Any],
        target_market: Mapping[str, str] | None,
    ) -> tuple[MarketId | None, str | None]:
        raw_market = dict(target_market or setup_created_from or {})
        if not all(
            str(raw_market.get(key, "") or "").strip()
            for key in ("exchange", "market_type", "symbol", "timeframe")
        ):
            return None, "missing_market_identity"
        try:
            market = canonicalize(
                exchange=str(raw_market.get("exchange", "")),
                market_type=str(raw_market.get("market_type", "")),
                symbol=str(raw_market.get("symbol", "")),
                timeframe=str(raw_market.get("timeframe", "")),
            )
        except ValueError as exc:
            return None, f"invalid_market_identity: {exc}"
        return market, None

    def _construct_source_status(
        self,
        payload: Mapping[str, Any],
    ) -> "_ConstructSourceStatus":
        input_binding_meta = _mapping_or_empty(payload.get("input_binding_meta"))
        if not input_binding_meta:
            return _ConstructSourceStatus(
                status=STUDY_EXPORT_STATUS_BLOCKED,
                reason="missing_required_inputs",
                dependency_notes=(),
            )

        saw_saved = False
        for source_meta in _iter_source_metadata(input_binding_meta):
            source_kind = str(source_meta.get("source_kind", "saved") or "saved").strip().lower()
            family = str(source_meta.get("family", "") or "").strip().lower()
            if source_kind == "temporary":
                return _ConstructSourceStatus(
                    status=STUDY_EXPORT_STATUS_BLOCKED,
                    reason="temporary_source_not_exportable",
                    dependency_notes=(
                        "Temporary chart-session construct sources are not available "
                        "to the Data Manager save-only calculation path.",
                    ),
                )
            if family != "default":
                saw_saved = True

        if saw_saved:
            return _ConstructSourceStatus(
                status=STUDY_EXPORT_STATUS_CONDITIONAL,
                reason="unresolved_dependency",
                dependency_notes=(
                    "Construct source metadata references saved or upstream artifacts. "
                    "B1 reports the dependency but does not resolve source artifacts.",
                ),
            )
        return _ConstructSourceStatus(
            status=STUDY_EXPORT_STATUS_EXPORTABLE,
            reason=None,
            dependency_notes=(),
        )

    def _metadata_warnings(self, ref: _StudyRef) -> tuple[str, ...]:
        role = ref.dataset_role
        if role == "visual_only":
            return ("dataset_role_visual_only",)
        if role == "volume" and ref.tool_key != "volume":
            return ("dataset_role_volume_mismatch",)
        if role == "utc" and ref.tool_key != "universal_trend_classifier":
            return ("dataset_role_utc_mismatch",)
        if role == "peaks_troughs" and ref.tool_key != "peaks_troughs":
            return ("dataset_role_peaks_troughs_mismatch",)
        if role == "braid" and ref.tool_key not in {"braids", "braid_instability"}:
            return ("dataset_role_braid_mismatch",)
        return ()

    def _blocker_message(self, reason: str) -> str:
        messages = {
            "invalid_serialized_study": "Serialized chart study payload is invalid.",
            "missing_market_identity": "No complete market identity is available for recipe planning.",
            "missing_tool_spec": "No financial tool specification exists for this study.",
            "unsupported_tool_for_recipe_export": "Study family/tool identity cannot be mapped to a save-only recipe.",
            "params_not_json_safe": "Study parameters are not JSON-safe.",
            "output_names_unavailable": "Output names or output signals could not be derived from the tool spec.",
            "missing_required_inputs": "Required construct source bindings are missing.",
            "temporary_source_not_exportable": "Temporary chart-session sources cannot be exported as Data Manager recipes.",
        }
        return messages.get(reason, reason)

    def _summary(
        self,
        candidates: list[StudyRecipeExportCandidate],
    ) -> dict[str, int]:
        summary = {
            "total": len(candidates),
            STUDY_EXPORT_STATUS_EXPORTABLE: 0,
            STUDY_EXPORT_STATUS_CONDITIONAL: 0,
            STUDY_EXPORT_STATUS_BLOCKED: 0,
            STUDY_EXPORT_STATUS_SKIPPED: 0,
        }
        for candidate in candidates:
            summary[candidate.status] = summary.get(candidate.status, 0) + 1
        return summary

    def _plan_id(
        self,
        *,
        setup: ChartStudySetup,
        important_only: bool,
        source_market: dict[str, str] | None,
    ) -> str:
        raw = {
            "setup_id": setup.setup_id,
            "content_hash": setup.content_hash,
            "important_only": bool(important_only),
            "source_market": source_market,
        }
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"study_recipe_export_plan__{_safe_token(setup.setup_id)}__h{digest[:8]}"


class StudySetupRecipeExportPersistenceService:
    """Persist selected exportable candidates from a read-only setup export plan.

    The service delegates recipe and collection writes to their owning stores. It
    does not plan studies, calculate artifacts, execute recipe collections, or
    mutate chart study setup files.
    """

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._recipe_store = ArtifactRecipeStore(historical_root=self._historical_root)
        self._collection_store = ArtifactRecipeCollectionStore(
            historical_root=self._historical_root,
        )

    def persist_export_plan(
        self,
        plan: StudySetupRecipeExportPlan,
        *,
        selected_candidate_ids: Iterable[str] | None = None,
        save_collection: bool = False,
        collection_display_name: str | None = None,
        overwrite_recipes: bool = False,
        overwrite_collection: bool = False,
    ) -> StudySetupRecipeExportPersistenceReport:
        """Save selected exportable recipe candidates from an existing plan."""

        requested_ids = self._requested_candidate_ids(
            plan=plan,
            selected_candidate_ids=selected_candidate_ids,
        )
        candidate_by_id = {candidate.candidate_id: candidate for candidate in plan.candidates}
        requested_set = set(requested_ids)
        results: list[StudyRecipeExportSaveResult] = []
        blockers: list[StudyRecipeExportPersistenceBlocker] = []
        warnings = list(plan.warnings)
        saved_recipes: list[ArtifactRecipe] = []
        saved_candidate_ids: list[str] = []

        for candidate in plan.candidates:
            if candidate.candidate_id not in requested_set:
                continue
            result, blocker, recipe = self._persist_candidate(
                candidate=candidate,
                overwrite_recipes=overwrite_recipes,
            )
            results.append(result)
            if blocker is not None:
                blockers.append(blocker)
            if recipe is not None:
                saved_recipes.append(recipe)
                saved_candidate_ids.append(candidate.candidate_id)

        for candidate_id in requested_ids:
            if candidate_id in candidate_by_id:
                continue
            result = StudyRecipeExportSaveResult(
                candidate_id=candidate_id,
                study_index=None,
                status=STUDY_EXPORT_SAVE_STATUS_BLOCKED,
                recipe_id=None,
                message="Selected export candidate id is not present in the plan.",
                error=None,
                metadata={"reason": "unknown_candidate_id"},
            )
            blocker = StudyRecipeExportPersistenceBlocker(
                blocker_id=(
                    f"{_safe_token(plan.plan_id)}__unknown_candidate__"
                    f"{_safe_token(candidate_id)}"
                ),
                candidate_id=candidate_id,
                reason="unknown_candidate_id",
                message="Selected export candidate id is not present in the plan.",
                metadata={"plan_id": plan.plan_id},
            )
            results.append(result)
            blockers.append(blocker)

        saved_collection_id = None
        if save_collection:
            collection_id, collection_blockers, collection_warnings = self._save_collection(
                plan=plan,
                requested_candidate_ids=requested_ids,
                saved_candidate_ids=tuple(saved_candidate_ids),
                saved_recipes=tuple(saved_recipes),
                collection_display_name=collection_display_name,
                overwrite_collection=overwrite_collection,
            )
            saved_collection_id = collection_id
            blockers.extend(collection_blockers)
            warnings.extend(collection_warnings)

        saved_recipe_ids = tuple(recipe.recipe_id for recipe in saved_recipes)
        skipped_candidate_ids = tuple(
            result.candidate_id
            for result in results
            if result.status == STUDY_EXPORT_SAVE_STATUS_SKIPPED
        )
        failed_candidate_ids = tuple(
            result.candidate_id
            for result in results
            if result.status == STUDY_EXPORT_SAVE_STATUS_FAILED
        )
        blocked_candidate_count = sum(
            1
            for result in results
            if result.status == STUDY_EXPORT_SAVE_STATUS_BLOCKED
        )
        summary = self._persistence_summary(
            requested_candidate_ids=requested_ids,
            saved_recipe_ids=saved_recipe_ids,
            skipped_candidate_ids=skipped_candidate_ids,
            failed_candidate_ids=failed_candidate_ids,
            blocked_candidate_count=blocked_candidate_count,
            saved_collection_id=saved_collection_id,
        )
        return StudySetupRecipeExportPersistenceReport(
            report_id=self._report_id(
                plan=plan,
                requested_candidate_ids=requested_ids,
                saved_recipe_ids=saved_recipe_ids,
                failed_candidate_ids=failed_candidate_ids,
                saved_collection_id=saved_collection_id,
            ),
            plan_id=plan.plan_id,
            created_at_utc=_utc_now(),
            requested_candidate_ids=requested_ids,
            saved_recipe_ids=saved_recipe_ids,
            skipped_candidate_ids=skipped_candidate_ids,
            failed_candidate_ids=failed_candidate_ids,
            saved_collection_id=saved_collection_id,
            results=tuple(results),
            blockers=tuple(blockers),
            warnings=tuple(dict.fromkeys(warnings)),
            summary=summary,
            metadata={
                "source_setup_id": plan.setup_id,
                "source_setup_display_name": plan.setup_display_name,
                "important_only": bool(plan.important_only),
                "save_collection": bool(save_collection),
                "saved_candidate_ids": list(saved_candidate_ids),
            },
        )

    def _requested_candidate_ids(
        self,
        *,
        plan: StudySetupRecipeExportPlan,
        selected_candidate_ids: Iterable[str] | None,
    ) -> tuple[str, ...]:
        if selected_candidate_ids is None:
            return tuple(
                candidate.candidate_id
                for candidate in plan.candidates
                if candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
                and candidate.recipe_payload is not None
            )

        requested: list[str] = []
        for raw_candidate_id in selected_candidate_ids:
            candidate_id = str(raw_candidate_id or "").strip()
            if candidate_id not in requested:
                requested.append(candidate_id)
        return tuple(requested)

    def _persist_candidate(
        self,
        *,
        candidate: StudyRecipeExportCandidate,
        overwrite_recipes: bool,
    ) -> tuple[
        StudyRecipeExportSaveResult,
        StudyRecipeExportPersistenceBlocker | None,
        ArtifactRecipe | None,
    ]:
        if candidate.status != STUDY_EXPORT_STATUS_EXPORTABLE:
            reason = _non_exportable_persistence_reason(candidate.status)
            status = (
                STUDY_EXPORT_SAVE_STATUS_SKIPPED
                if candidate.status == STUDY_EXPORT_STATUS_SKIPPED
                else STUDY_EXPORT_SAVE_STATUS_BLOCKED
            )
            message = "Candidate is not exportable and was not persisted."
            return (
                StudyRecipeExportSaveResult(
                    candidate_id=candidate.candidate_id,
                    study_index=candidate.study_index,
                    status=status,
                    recipe_id=None,
                    message=message,
                    error=None,
                    metadata={
                        "reason": reason,
                        "candidate_status": candidate.status,
                        "candidate_reasons": list(candidate.reasons),
                    },
                ),
                StudyRecipeExportPersistenceBlocker(
                    blocker_id=f"{candidate.candidate_id}__{reason}",
                    candidate_id=candidate.candidate_id,
                    reason=reason,
                    message=message,
                    metadata={
                        "candidate_status": candidate.status,
                        "candidate_reasons": list(candidate.reasons),
                    },
                ),
                None,
            )

        if candidate.recipe_payload is None:
            message = "Exportable candidate has no recipe payload preview."
            return (
                StudyRecipeExportSaveResult(
                    candidate_id=candidate.candidate_id,
                    study_index=candidate.study_index,
                    status=STUDY_EXPORT_SAVE_STATUS_BLOCKED,
                    recipe_id=None,
                    message=message,
                    error=None,
                    metadata={"reason": "missing_recipe_payload"},
                ),
                StudyRecipeExportPersistenceBlocker(
                    blocker_id=f"{candidate.candidate_id}__missing_recipe_payload",
                    candidate_id=candidate.candidate_id,
                    reason="missing_recipe_payload",
                    message=message,
                    metadata={"candidate_status": candidate.status},
                ),
                None,
            )

        try:
            recipe = self._recipe_store.save_recipe(
                candidate.recipe_payload,
                overwrite=overwrite_recipes,
            )
        except Exception as exc:
            message = "Artifact recipe save failed."
            return (
                StudyRecipeExportSaveResult(
                    candidate_id=candidate.candidate_id,
                    study_index=candidate.study_index,
                    status=STUDY_EXPORT_SAVE_STATUS_FAILED,
                    recipe_id=None,
                    message=message,
                    error=repr(exc),
                    metadata={
                        "reason": "recipe_save_failed",
                        "tool_key": candidate.tool_key,
                        "family": candidate.family,
                    },
                ),
                None,
                None,
            )

        return (
            StudyRecipeExportSaveResult(
                candidate_id=candidate.candidate_id,
                study_index=candidate.study_index,
                status=STUDY_EXPORT_SAVE_STATUS_SAVED,
                recipe_id=recipe.recipe_id,
                message="Artifact recipe saved.",
                error=None,
                metadata={
                    "recipe_id": recipe.recipe_id,
                    "recipe_hash": recipe.recipe_hash,
                    "recipe_hash_short": recipe.recipe_hash_short,
                    "recipe_display_name": recipe.display_name,
                    "recipe_path": self._recipe_store.recipe_path(
                        market=recipe.market,
                        recipe_id=recipe.recipe_id,
                    ),
                    "tool_key": recipe.tool_key,
                    "tool_type": recipe.tool_type,
                    "market": market_to_dict(recipe.market),
                },
            ),
            None,
            recipe,
        )

    def _save_collection(
        self,
        *,
        plan: StudySetupRecipeExportPlan,
        requested_candidate_ids: tuple[str, ...],
        saved_candidate_ids: tuple[str, ...],
        saved_recipes: tuple[ArtifactRecipe, ...],
        collection_display_name: str | None,
        overwrite_collection: bool,
    ) -> tuple[
        str | None,
        tuple[StudyRecipeExportPersistenceBlocker, ...],
        tuple[str, ...],
    ]:
        if not saved_recipes:
            return (
                None,
                (
                    StudyRecipeExportPersistenceBlocker(
                        blocker_id=f"{_safe_token(plan.plan_id)}__no_saved_recipes_for_collection",
                        candidate_id=None,
                        reason="no_saved_recipes_for_collection",
                        message=(
                            "No successfully saved recipes are available for "
                            "collection persistence."
                        ),
                        metadata={"plan_id": plan.plan_id},
                    ),
                ),
                (),
            )
        if plan.collection_draft is None:
            return (
                None,
                (
                    StudyRecipeExportPersistenceBlocker(
                        blocker_id=f"{_safe_token(plan.plan_id)}__missing_collection_draft",
                        candidate_id=None,
                        reason="missing_collection_draft",
                        message="The export plan does not contain a collection draft.",
                        metadata={"plan_id": plan.plan_id},
                    ),
                ),
                (),
            )

        edge_warning, dependency_edges = self._filtered_dependency_edges(
            dependency_edges=plan.collection_draft.dependency_edges,
            saved_recipe_ids={recipe.recipe_id for recipe in saved_recipes},
        )
        warnings = list(plan.collection_draft.warnings)
        if edge_warning is not None:
            warnings.append(edge_warning)

        display_name = str(collection_display_name or "").strip()
        if not display_name:
            display_name = plan.collection_draft.display_name
        metadata = dict(plan.collection_draft.metadata)
        metadata.update(
            {
                "source_plan_id": plan.plan_id,
                "source_setup_id": plan.setup_id,
                "source_setup_display_name": plan.setup_display_name,
                "requested_candidate_ids": list(requested_candidate_ids),
                "saved_candidate_ids": list(saved_candidate_ids),
                "saved_recipe_ids": [recipe.recipe_id for recipe in saved_recipes],
                "important_only": bool(plan.important_only),
            }
        )
        source_database_id = _optional_string(metadata.get("source_database_id"))
        try:
            collection = self._collection_store.build_collection(
                market=saved_recipes[0].market,
                display_name=display_name,
                recipes=saved_recipes,
                source_database_id=source_database_id,
                dependency_edges=dependency_edges,
                metadata=metadata,
            )
            saved = self._collection_store.save_collection(
                collection,
                overwrite=overwrite_collection,
            )
        except Exception as exc:
            return (
                None,
                (
                    StudyRecipeExportPersistenceBlocker(
                        blocker_id=f"{_safe_token(plan.plan_id)}__collection_save_failed",
                        candidate_id=None,
                        reason="collection_save_failed",
                        message="Artifact recipe collection save failed.",
                        metadata={"error": repr(exc), "plan_id": plan.plan_id},
                    ),
                ),
                tuple(warnings),
            )

        return saved.collection_id, (), tuple(warnings)

    def _filtered_dependency_edges(
        self,
        *,
        dependency_edges: tuple[dict[str, Any], ...],
        saved_recipe_ids: set[str],
    ) -> tuple[str | None, tuple[dict[str, Any], ...]]:
        kept: list[dict[str, Any]] = []
        dropped = 0
        for edge in dependency_edges:
            from_recipe_id = str(edge.get("from_recipe_id", "") or "").strip()
            to_recipe_id = str(edge.get("to_recipe_id", "") or "").strip()
            if from_recipe_id in saved_recipe_ids and to_recipe_id in saved_recipe_ids:
                kept.append(dict(edge))
            else:
                dropped += 1
        warning = (
            "dropped_dependency_edge_for_excluded_recipe"
            if dropped
            else None
        )
        return warning, tuple(kept)

    def _persistence_summary(
        self,
        *,
        requested_candidate_ids: tuple[str, ...],
        saved_recipe_ids: tuple[str, ...],
        skipped_candidate_ids: tuple[str, ...],
        failed_candidate_ids: tuple[str, ...],
        blocked_candidate_count: int,
        saved_collection_id: str | None,
    ) -> dict[str, int]:
        return {
            "requested": len(requested_candidate_ids),
            STUDY_EXPORT_SAVE_STATUS_SAVED: len(saved_recipe_ids),
            STUDY_EXPORT_SAVE_STATUS_SKIPPED: len(skipped_candidate_ids),
            STUDY_EXPORT_SAVE_STATUS_BLOCKED: int(blocked_candidate_count),
            STUDY_EXPORT_SAVE_STATUS_FAILED: len(failed_candidate_ids),
            "collection_saved": 1 if saved_collection_id else 0,
        }

    def _report_id(
        self,
        *,
        plan: StudySetupRecipeExportPlan,
        requested_candidate_ids: tuple[str, ...],
        saved_recipe_ids: tuple[str, ...],
        failed_candidate_ids: tuple[str, ...],
        saved_collection_id: str | None,
    ) -> str:
        raw = {
            "plan_id": plan.plan_id,
            "requested_candidate_ids": requested_candidate_ids,
            "saved_recipe_ids": saved_recipe_ids,
            "failed_candidate_ids": failed_candidate_ids,
            "saved_collection_id": saved_collection_id,
        }
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"study_recipe_export_persistence__{_safe_token(plan.setup_id)}__h{digest[:8]}"


@dataclass(frozen=True)
class _ConstructSourceStatus:
    status: str
    reason: str | None
    dependency_notes: tuple[str, ...]


def _non_exportable_persistence_reason(candidate_status: str) -> str:
    if candidate_status == STUDY_EXPORT_STATUS_CONDITIONAL:
        return "conditional_not_persisted"
    if candidate_status == STUDY_EXPORT_STATUS_SKIPPED:
        return "candidate_skipped"
    return "candidate_not_exportable"


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_tool_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "indicator": "indicator",
        "indicators": "indicator",
        "oscillator": "oscillator",
        "oscillators": "oscillator",
        "construct": "construct",
        "constructs": "construct",
    }
    return aliases.get(normalized)


def _iter_source_metadata(
    input_binding_meta: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    entries: list[Mapping[str, Any]] = []
    for value in input_binding_meta.values():
        if isinstance(value, Mapping):
            entries.append(value)
        elif isinstance(value, (list, tuple)):
            entries.extend(item for item in value if isinstance(item, Mapping))
    return tuple(entries)


def _output_signal_payload(signal: OutputSignalSpec) -> dict[str, Any]:
    return {
        "name": signal.name,
        "signal_type": signal.signal_type,
        "renderable": signal.renderable,
        "analysis_usable": signal.analysis_usable,
        "default_visible": signal.default_visible,
        "label": signal.label,
        "description": signal.description,
    }


def _mapping_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _require_json_serializable(value: Any, *, field_name: str) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _safe_token(value: object) -> str:
    text = str(value or "").strip().lower()
    safe = "".join(char if char.isalnum() else "_" for char in text).strip("_")
    return safe or "setup"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "STUDY_EXPORT_STATUS_BLOCKED",
    "STUDY_EXPORT_STATUS_CONDITIONAL",
    "STUDY_EXPORT_STATUS_EXPORTABLE",
    "STUDY_EXPORT_STATUS_SKIPPED",
    "STUDY_EXPORT_SAVE_STATUS_BLOCKED",
    "STUDY_EXPORT_SAVE_STATUS_FAILED",
    "STUDY_EXPORT_SAVE_STATUS_SAVED",
    "STUDY_EXPORT_SAVE_STATUS_SKIPPED",
    "StudyRecipeCollectionDraft",
    "StudyRecipeExportBlocker",
    "StudyRecipeExportCandidate",
    "StudyRecipeExportPersistenceBlocker",
    "StudyRecipeExportSaveResult",
    "StudySetupRecipeExportPlan",
    "StudySetupRecipeExportPersistenceReport",
    "StudySetupRecipeExportPersistenceService",
    "StudySetupRecipeExportPlanner",
]
