from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
    market_to_dict,
)
from leonardo.data.naming import MarketId, canonicalize
from leonardo.financial_tools.ft_specs import (
    build_default_params,
    format_output_names,
    format_output_signals,
    get_construct_specs,
)

ConstructBatchKind = Literal["unary", "delta"]
ConstructBatchItemStatus = Literal["planned", "existing_recipe", "blocked", "error"]
DeltaFixedRole = Literal["minuend", "subtrahend"]

SUPPORTED_UNARY_CONSTRUCTS = frozenset(
    {"derivative", "angle", "percent_span_angle", "angle_momentum"}
)
SUPPORTED_DELTA_CONSTRUCT = "delta"
SUPPORTED_SOURCE_FAMILIES = frozenset(
    {"ohlc", "default", "indicator", "oscillator", "construct"}
)
_TIMESTAMP_KEYS = ("ts_ms", "time")
_DELTA_DIRECTION_LABEL = "delta = minuend - subtrahend"


@dataclass(frozen=True)
class ConstructBatchSourceRef:
    """
    Data-layer reference for one source column considered by batch planning.

    The reference is intentionally independent of GUI row objects. It carries
    source identity, market partition identity, eligibility flags, and optional
    timestamp metadata used to prove alignment without relying on row counts.
    """

    source_id: str
    display_name: str
    source_family: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    column_name: str
    source_token: str | None = None
    artifact_path: str | Path | None = None
    csv_path: str | Path | None = None
    metadata_path: str | Path | None = None
    selectable: bool = True
    analysis_usable: bool = True
    renderable: bool = True
    timestamp_key: str | None = None
    first_ts_ms: int | None = None
    last_ts_ms: int | None = None
    row_count: int | None = None
    timestamp_values: tuple[int, ...] | None = None

    @property
    def market(self) -> MarketId:
        return canonicalize(
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "display_name": self.display_name,
            "source_family": self.source_family,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "column_name": self.column_name,
            "source_token": self.source_token,
            "artifact_path": _path_text(self.artifact_path),
            "csv_path": _path_text(self.csv_path),
            "metadata_path": _path_text(self.metadata_path),
            "selectable": bool(self.selectable),
            "analysis_usable": bool(self.analysis_usable),
            "renderable": bool(self.renderable),
            "timestamp_key": self.timestamp_key,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "row_count": self.row_count,
        }


@dataclass(frozen=True)
class ConstructUnaryBatchIntent:
    """Batch intent for one-source-per-candidate construct planning."""

    construct_key: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    sources: tuple[ConstructBatchSourceRef, ...]
    params: dict[str, Any] = field(default_factory=dict)
    batch_name: str | None = None

    @property
    def market(self) -> MarketId:
        return canonicalize(
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
        )


@dataclass(frozen=True)
class ConstructDeltaBatchIntent:
    """Batch intent for directional delta planning."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    fixed_source: ConstructBatchSourceRef
    fixed_role: DeltaFixedRole
    variable_sources: tuple[ConstructBatchSourceRef, ...]
    params: dict[str, Any] = field(default_factory=dict)
    batch_name: str | None = None
    construct_key: str = SUPPORTED_DELTA_CONSTRUCT

    @property
    def market(self) -> MarketId:
        return canonicalize(
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
        )


@dataclass(frozen=True)
class ConstructBatchAlignmentSummary:
    """Timestamp alignment summary for one plan item or source."""

    status: str
    timestamp_key: str | None = None
    source_first_ts_ms: int | None = None
    source_last_ts_ms: int | None = None
    common_first_ts_ms: int | None = None
    common_last_ts_ms: int | None = None
    row_count: int | None = None
    aligned_row_count: int | None = None
    source_ranges: tuple[dict[str, object], ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "timestamp_key": self.timestamp_key,
            "source_first_ts_ms": self.source_first_ts_ms,
            "source_last_ts_ms": self.source_last_ts_ms,
            "common_first_ts_ms": self.common_first_ts_ms,
            "common_last_ts_ms": self.common_last_ts_ms,
            "row_count": self.row_count,
            "aligned_row_count": self.aligned_row_count,
            "source_ranges": [_json_safe(item) for item in self.source_ranges],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ConstructBatchPlanItem:
    """Read-only candidate report for one batch construct recipe preview."""

    item_id: str
    status: ConstructBatchItemStatus
    actionable: bool
    construct_key: str
    display_name: str
    source_refs: tuple[dict[str, object], ...]
    role_bindings: dict[str, str]
    params: dict[str, Any]
    expected_recipe_payload: dict[str, Any] | None
    expected_recipe_id: str | None
    expected_recipe_hash: str | None
    expected_recipe_hash_short: str | None
    existing_recipe_id: str | None
    existing_recipe_hash: str | None
    expected_outputs: tuple[str, ...]
    alignment_summary: ConstructBatchAlignmentSummary
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    direction: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "status": self.status,
            "actionable": bool(self.actionable),
            "construct_key": self.construct_key,
            "display_name": self.display_name,
            "source_refs": [_json_safe(item) for item in self.source_refs],
            "role_bindings": _json_safe(self.role_bindings),
            "params": _json_safe(self.params),
            "expected_recipe_payload": _json_safe(self.expected_recipe_payload),
            "expected_recipe_id": self.expected_recipe_id,
            "expected_recipe_hash": self.expected_recipe_hash,
            "expected_recipe_hash_short": self.expected_recipe_hash_short,
            "existing_recipe_id": self.existing_recipe_id,
            "existing_recipe_hash": self.existing_recipe_hash,
            "expected_outputs": list(self.expected_outputs),
            "alignment_summary": self.alignment_summary.to_dict(),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "direction": self.direction,
        }


@dataclass(frozen=True)
class ConstructBatchPlan:
    """JSON-safe construct batch preview report."""

    plan_id: str
    created_at_utc: str
    batch_kind: ConstructBatchKind
    construct_key: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    params: dict[str, Any]
    total_candidate_count: int
    planned_count: int
    blocked_count: int
    existing_recipe_count: int
    warning_count: int
    alignment_summary: dict[str, object]
    items: tuple[ConstructBatchPlanItem, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "batch_kind": self.batch_kind,
            "construct_key": self.construct_key,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": _json_safe(self.params),
            "total_candidate_count": int(self.total_candidate_count),
            "planned_count": int(self.planned_count),
            "blocked_count": int(self.blocked_count),
            "existing_recipe_count": int(self.existing_recipe_count),
            "warning_count": int(self.warning_count),
            "alignment_summary": _json_safe(self.alignment_summary),
            "items": [item.to_dict() for item in self.items],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


class DataManagerConstructBatchPlanner:
    """
    Build read-only construct batch previews for Data Manager workflows.

    The planner owns source eligibility checks, timestamp-safe alignment
    reporting, expected recipe payload previews, and read-only existing-recipe
    detection. It does not persist recipes, generate artifacts, modify Analysis
    Databases, or depend on GUI objects.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        recipe_store: ArtifactRecipeStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._recipe_store = recipe_store or ArtifactRecipeStore(
            historical_root=self._historical_root
        )

    def plan_unary_batch(
        self,
        intent: ConstructUnaryBatchIntent,
    ) -> ConstructBatchPlan:
        """
        Return a read-only preview for unary construct candidates.

        Unsupported construct keys and unsafe source candidates are represented
        as blocked plan items. No recipe or artifact files are written.
        """
        construct_key = _normalize_construct_key(intent.construct_key)
        items: list[ConstructBatchPlanItem] = []
        plan_blockers: list[str] = []

        if construct_key not in SUPPORTED_UNARY_CONSTRUCTS:
            plan_blockers.append(
                f"Unsupported construct for unary batch planning: {intent.construct_key}"
            )

        if not intent.sources:
            plan_blockers.append("No construct batch sources were provided.")

        for source in intent.sources:
            if construct_key not in SUPPORTED_UNARY_CONSTRUCTS:
                items.append(
                    self._blocked_item(
                        batch_kind="unary",
                        construct_key=construct_key,
                        display_name=source.display_name,
                        source_refs=(source.to_dict(),),
                        role_bindings={"source": _source_token(source)},
                        params=dict(intent.params),
                        blockers=(
                            f"Unsupported construct for unary batch planning: {intent.construct_key}",
                        ),
                    )
                )
                continue
            items.append(
                self._plan_unary_item(
                    intent=intent,
                    construct_key=construct_key,
                    source=source,
                )
            )

        return self._build_plan(
            batch_kind="unary",
            construct_key=construct_key,
            market=intent.market,
            params=dict(intent.params),
            items=tuple(items),
            blockers=tuple(plan_blockers),
        )

    def plan_delta_batch(
        self,
        intent: ConstructDeltaBatchIntent,
    ) -> ConstructBatchPlan:
        """
        Return a read-only preview for directional delta candidates.

        Report role bindings use the explicit direction
        ``delta = minuend - subtrahend``. Internally the payload maps minuend to
        the runtime ``fast`` role and subtrahend to ``slow``.
        """
        construct_key = _normalize_construct_key(intent.construct_key)
        items: list[ConstructBatchPlanItem] = []
        plan_blockers: list[str] = []

        if construct_key != SUPPORTED_DELTA_CONSTRUCT:
            plan_blockers.append(
                f"Unsupported construct for delta batch planning: {intent.construct_key}"
            )
        if intent.fixed_role not in {"minuend", "subtrahend"}:
            plan_blockers.append(f"Unsupported fixed delta role: {intent.fixed_role}")
        if not intent.variable_sources:
            plan_blockers.append("No variable delta sources were provided.")

        for variable_source in intent.variable_sources:
            if construct_key != SUPPORTED_DELTA_CONSTRUCT:
                items.append(
                    self._blocked_item(
                        batch_kind="delta",
                        construct_key=construct_key,
                        display_name=variable_source.display_name,
                        source_refs=(
                            intent.fixed_source.to_dict(),
                            variable_source.to_dict(),
                        ),
                        role_bindings={},
                        params=dict(intent.params),
                        blockers=(
                            f"Unsupported construct for delta batch planning: {intent.construct_key}",
                        ),
                        direction=_DELTA_DIRECTION_LABEL,
                    )
                )
                continue
            items.append(
                self._plan_delta_item(
                    intent=intent,
                    construct_key=construct_key,
                    variable_source=variable_source,
                )
            )

        return self._build_plan(
            batch_kind="delta",
            construct_key=construct_key,
            market=intent.market,
            params=dict(intent.params),
            items=tuple(items),
            blockers=tuple(plan_blockers),
        )

    def plan_from_intent(
        self,
        intent: ConstructUnaryBatchIntent | ConstructDeltaBatchIntent,
    ) -> ConstructBatchPlan:
        """Dispatch to the matching batch planner for the supplied intent."""
        if isinstance(intent, ConstructUnaryBatchIntent):
            return self.plan_unary_batch(intent)
        return self.plan_delta_batch(intent)

    def _plan_unary_item(
        self,
        *,
        intent: ConstructUnaryBatchIntent,
        construct_key: str,
        source: ConstructBatchSourceRef,
    ) -> ConstructBatchPlanItem:
        blockers, warnings = self._validate_source(source, market=intent.market)
        timestamp_info = self._timestamp_info(source)
        blockers.extend(timestamp_info.blockers)
        warnings.extend(timestamp_info.warnings)

        alignment = ConstructBatchAlignmentSummary(
            status="blocked" if blockers else "aligned",
            timestamp_key=timestamp_info.timestamp_key,
            source_first_ts_ms=timestamp_info.first_ts_ms,
            source_last_ts_ms=timestamp_info.last_ts_ms,
            common_first_ts_ms=timestamp_info.first_ts_ms,
            common_last_ts_ms=timestamp_info.last_ts_ms,
            row_count=timestamp_info.row_count,
            aligned_row_count=timestamp_info.row_count if not blockers else None,
            source_ranges=(timestamp_info.to_source_range(source),),
            warnings=tuple(timestamp_info.warnings),
            blockers=tuple(timestamp_info.blockers),
        )

        params = self._unary_params(
            construct_key=construct_key,
            source=source,
            user_params=intent.params,
        )
        role_bindings = {"source": _source_token(source)}
        if blockers:
            return self._blocked_item(
                batch_kind="unary",
                construct_key=construct_key,
                display_name=self._unary_display_name(construct_key, source),
                source_refs=(source.to_dict(),),
                role_bindings=role_bindings,
                params=params,
                blockers=tuple(blockers),
                warnings=tuple(warnings),
                alignment_summary=alignment,
            )

        try:
            return self._recipe_item(
                batch_kind="unary",
                construct_key=construct_key,
                market=intent.market,
                display_name=self._unary_display_name(construct_key, source),
                source_refs=(source.to_dict(),),
                role_bindings=role_bindings,
                input_bindings=self._unary_input_bindings(
                    construct_key=construct_key,
                    source=source,
                ),
                input_binding_meta=self._unary_input_binding_meta(
                    construct_key=construct_key,
                    source=source,
                ),
                params=params,
                alignment_summary=alignment,
                warnings=tuple(warnings),
            )
        except Exception as exc:
            return self._error_item(
                batch_kind="unary",
                construct_key=construct_key,
                display_name=self._unary_display_name(construct_key, source),
                source_refs=(source.to_dict(),),
                role_bindings=role_bindings,
                params=params,
                alignment_summary=alignment,
                error=exc,
            )

    def _plan_delta_item(
        self,
        *,
        intent: ConstructDeltaBatchIntent,
        construct_key: str,
        variable_source: ConstructBatchSourceRef,
    ) -> ConstructBatchPlanItem:
        fixed = intent.fixed_source
        if intent.fixed_role == "minuend":
            minuend = fixed
            subtrahend = variable_source
        else:
            minuend = variable_source
            subtrahend = fixed

        blockers: list[str] = []
        warnings: list[str] = []
        fixed_blockers, fixed_warnings = self._validate_source(fixed, market=intent.market)
        variable_blockers, variable_warnings = self._validate_source(
            variable_source,
            market=intent.market,
        )
        blockers.extend(fixed_blockers)
        blockers.extend(variable_blockers)
        warnings.extend(fixed_warnings)
        warnings.extend(variable_warnings)

        if _same_source(fixed, variable_source):
            blockers.append("Delta cannot pair a source with itself.")

        fixed_ts = self._timestamp_info(fixed)
        variable_ts = self._timestamp_info(variable_source)
        blockers.extend(fixed_ts.blockers)
        blockers.extend(variable_ts.blockers)
        warnings.extend(fixed_ts.warnings)
        warnings.extend(variable_ts.warnings)
        alignment = self._delta_alignment(
            fixed=fixed,
            fixed_ts=fixed_ts,
            variable=variable_source,
            variable_ts=variable_ts,
            existing_blockers=tuple(blockers),
        )
        blockers.extend(
            blocker
            for blocker in alignment.blockers
            if blocker not in blockers
        )

        params = self._delta_params(
            minuend=minuend,
            subtrahend=subtrahend,
            user_params=intent.params,
        )
        role_bindings = {
            "minuend": _source_token(minuend),
            "subtrahend": _source_token(subtrahend),
            "fast": _source_token(minuend),
            "slow": _source_token(subtrahend),
        }
        display_name = (
            f"Delta {_source_label(minuend)} - {_source_label(subtrahend)}"
        )

        if blockers:
            return self._blocked_item(
                batch_kind="delta",
                construct_key=construct_key,
                display_name=display_name,
                source_refs=(fixed.to_dict(), variable_source.to_dict()),
                role_bindings=role_bindings,
                params=params,
                blockers=tuple(blockers),
                warnings=tuple(warnings),
                alignment_summary=alignment,
                direction=_DELTA_DIRECTION_LABEL,
            )

        try:
            return self._recipe_item(
                batch_kind="delta",
                construct_key=construct_key,
                market=intent.market,
                display_name=display_name,
                source_refs=(fixed.to_dict(), variable_source.to_dict()),
                role_bindings=role_bindings,
                input_bindings={
                    "fast": _source_token(minuend),
                    "slow": _source_token(subtrahend),
                },
                input_binding_meta={
                    "fast": self._source_meta(minuend),
                    "slow": self._source_meta(subtrahend),
                },
                params=params,
                alignment_summary=alignment,
                warnings=tuple(warnings),
                direction=_DELTA_DIRECTION_LABEL,
            )
        except Exception as exc:
            return self._error_item(
                batch_kind="delta",
                construct_key=construct_key,
                display_name=display_name,
                source_refs=(fixed.to_dict(), variable_source.to_dict()),
                role_bindings=role_bindings,
                params=params,
                alignment_summary=alignment,
                error=exc,
                direction=_DELTA_DIRECTION_LABEL,
            )

    def _recipe_item(
        self,
        *,
        batch_kind: ConstructBatchKind,
        construct_key: str,
        market: MarketId,
        display_name: str,
        source_refs: tuple[dict[str, object], ...],
        role_bindings: dict[str, str],
        input_bindings: dict[str, Any],
        input_binding_meta: dict[str, Any],
        params: dict[str, Any],
        alignment_summary: ConstructBatchAlignmentSummary,
        warnings: tuple[str, ...] = (),
        direction: str | None = None,
    ) -> ConstructBatchPlanItem:
        spec = get_construct_specs()[construct_key]
        outputs = tuple(format_output_names(spec, params))
        if not outputs:
            raise ValueError("Construct recipe preview did not produce output names.")

        output_signals = tuple(
            _signal_to_dict(signal)
            for signal in format_output_signals(spec, params)
        )
        payload = {
            "tool_type": "construct",
            "tool_key": construct_key,
            "tool_title": spec.title,
            **market_to_dict(market),
            "params": dict(params),
            "input_bindings": _json_safe(input_bindings),
            "input_binding_meta": input_binding_meta,
            "required_inputs": [],
            "output_names": list(outputs),
            "output_signals": [dict(item) for item in output_signals],
            "recipe_display_name": display_name,
        }
        recipe = self._recipe_store.build_recipe_from_payload(
            payload,
            created_at_ms=0,
            updated_at_ms=0,
        )
        status, existing_recipe, duplicate_warnings, duplicate_blockers = (
            self._existing_recipe_status(recipe)
        )
        item_warnings = tuple(warnings) + tuple(duplicate_warnings)
        if duplicate_blockers:
            return self._blocked_item(
                batch_kind=batch_kind,
                construct_key=construct_key,
                display_name=display_name,
                source_refs=source_refs,
                role_bindings=role_bindings,
                params=params,
                blockers=tuple(duplicate_blockers),
                warnings=item_warnings,
                alignment_summary=alignment_summary,
                expected_recipe_payload=payload,
                expected_recipe_id=recipe.recipe_id,
                expected_recipe_hash=recipe.recipe_hash,
                expected_recipe_hash_short=recipe.recipe_hash_short,
                expected_outputs=outputs,
                direction=direction,
            )

        return ConstructBatchPlanItem(
            item_id=self._item_id(
                batch_kind=batch_kind,
                construct_key=construct_key,
                role_bindings=role_bindings,
            ),
            status=status,
            actionable=status == "planned",
            construct_key=construct_key,
            display_name=display_name,
            source_refs=source_refs,
            role_bindings=dict(role_bindings),
            params=dict(params),
            expected_recipe_payload=payload,
            expected_recipe_id=recipe.recipe_id,
            expected_recipe_hash=recipe.recipe_hash,
            expected_recipe_hash_short=recipe.recipe_hash_short,
            existing_recipe_id=existing_recipe.recipe_id if existing_recipe else None,
            existing_recipe_hash=existing_recipe.recipe_hash if existing_recipe else None,
            expected_outputs=outputs,
            alignment_summary=alignment_summary,
            warnings=item_warnings,
            direction=direction,
        )

    def _blocked_item(
        self,
        *,
        batch_kind: ConstructBatchKind,
        construct_key: str,
        display_name: str,
        source_refs: tuple[dict[str, object], ...],
        role_bindings: dict[str, str],
        params: dict[str, Any],
        blockers: tuple[str, ...],
        warnings: tuple[str, ...] = (),
        alignment_summary: ConstructBatchAlignmentSummary | None = None,
        expected_recipe_payload: dict[str, Any] | None = None,
        expected_recipe_id: str | None = None,
        expected_recipe_hash: str | None = None,
        expected_recipe_hash_short: str | None = None,
        expected_outputs: tuple[str, ...] = (),
        direction: str | None = None,
    ) -> ConstructBatchPlanItem:
        return ConstructBatchPlanItem(
            item_id=self._item_id(
                batch_kind=batch_kind,
                construct_key=construct_key,
                role_bindings=role_bindings,
            ),
            status="blocked",
            actionable=False,
            construct_key=construct_key,
            display_name=display_name,
            source_refs=source_refs,
            role_bindings=dict(role_bindings),
            params=dict(params),
            expected_recipe_payload=expected_recipe_payload,
            expected_recipe_id=expected_recipe_id,
            expected_recipe_hash=expected_recipe_hash,
            expected_recipe_hash_short=expected_recipe_hash_short,
            existing_recipe_id=None,
            existing_recipe_hash=None,
            expected_outputs=expected_outputs,
            alignment_summary=alignment_summary
            or ConstructBatchAlignmentSummary(status="blocked", blockers=blockers),
            warnings=warnings,
            blockers=blockers,
            direction=direction,
        )

    def _error_item(
        self,
        *,
        batch_kind: ConstructBatchKind,
        construct_key: str,
        display_name: str,
        source_refs: tuple[dict[str, object], ...],
        role_bindings: dict[str, str],
        params: dict[str, Any],
        alignment_summary: ConstructBatchAlignmentSummary,
        error: Exception,
        direction: str | None = None,
    ) -> ConstructBatchPlanItem:
        return ConstructBatchPlanItem(
            item_id=self._item_id(
                batch_kind=batch_kind,
                construct_key=construct_key,
                role_bindings=role_bindings,
            ),
            status="error",
            actionable=False,
            construct_key=construct_key,
            display_name=display_name,
            source_refs=source_refs,
            role_bindings=dict(role_bindings),
            params=dict(params),
            expected_recipe_payload=None,
            expected_recipe_id=None,
            expected_recipe_hash=None,
            expected_recipe_hash_short=None,
            existing_recipe_id=None,
            existing_recipe_hash=None,
            expected_outputs=(),
            alignment_summary=alignment_summary,
            blockers=(f"Unexpected construct batch planning failure: {error}",),
            direction=direction,
        )

    def _build_plan(
        self,
        *,
        batch_kind: ConstructBatchKind,
        construct_key: str,
        market: MarketId,
        params: dict[str, Any],
        items: tuple[ConstructBatchPlanItem, ...],
        blockers: tuple[str, ...],
    ) -> ConstructBatchPlan:
        planned_count = sum(1 for item in items if item.status == "planned")
        blocked_count = sum(1 for item in items if item.status == "blocked")
        existing_count = sum(1 for item in items if item.status == "existing_recipe")
        warning_count = sum(1 for item in items if item.warnings)
        alignment_summary = {
            "blocked_count": sum(
                1 for item in items if item.alignment_summary.blockers
            ),
            "warning_count": sum(
                1 for item in items if item.alignment_summary.warnings
            ),
        }
        return ConstructBatchPlan(
            plan_id=f"construct_batch__{batch_kind}__{construct_key}__{int(time.time() * 1000)}",
            created_at_utc=_utc_now(),
            batch_kind=batch_kind,
            construct_key=construct_key,
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            params=dict(params),
            total_candidate_count=len(items),
            planned_count=planned_count,
            blocked_count=blocked_count,
            existing_recipe_count=existing_count,
            warning_count=warning_count,
            alignment_summary=alignment_summary,
            items=items,
            blockers=blockers,
        )

    def _validate_source(
        self,
        source: ConstructBatchSourceRef,
        *,
        market: MarketId,
    ) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        family = _normalize_source_family(source.source_family)
        path = _source_path(source)

        if not source.selectable:
            blockers.append(f"Source is not selectable: {source.display_name}")
        if not source.analysis_usable:
            blockers.append(f"Source is not analysis-usable: {source.display_name}")
        if source.renderable is False and source.analysis_usable:
            warnings.append(
                f"Source is analysis-usable but not renderable: {source.display_name}"
            )
        if family not in SUPPORTED_SOURCE_FAMILIES:
            blockers.append(f"Unsupported construct source family: {source.source_family}")
        if source.market != market:
            blockers.append(
                "Source market identity does not match the batch market identity."
            )
        if not _source_token(source):
            blockers.append(f"Source token is missing: {source.display_name}")
        if path is not None and not path.exists():
            blockers.append(f"Source CSV file is missing: {path}")
        if path is not None and path.exists() and family not in {"ohlc", "default"}:
            warnings.append(
                "Source artifact freshness is not checked by construct batch planning."
            )
        metadata_path = _optional_path(source.metadata_path)
        if metadata_path is not None:
            if not metadata_path.exists():
                blockers.append(f"Source metadata sidecar is missing: {metadata_path}")
            else:
                try:
                    json.loads(metadata_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    blockers.append(
                        f"Source metadata sidecar is unreadable: {metadata_path} ({exc})"
                    )
        return blockers, warnings

    def _timestamp_info(self, source: ConstructBatchSourceRef) -> "_TimestampInfo":
        path = _source_path(source)
        key = str(source.timestamp_key or "").strip() or None
        warnings: list[str] = []
        blockers: list[str] = []

        if source.timestamp_values is not None:
            values = tuple(int(value) for value in source.timestamp_values)
            key = key or "ts_ms"
            return _timestamp_info_from_values(
                source=source,
                key=key,
                values=values,
                warnings=warnings,
            )

        if path is not None and path.exists():
            try:
                return _timestamp_info_from_csv(
                    source=source,
                    path=path,
                    requested_key=key,
                )
            except Exception as exc:
                return _TimestampInfo(
                    timestamp_key=key,
                    first_ts_ms=None,
                    last_ts_ms=None,
                    row_count=source.row_count,
                    values=None,
                    warnings=tuple(warnings),
                    blockers=(f"Timestamp inspection failed for {path}: {exc}",),
                )

        if key and source.first_ts_ms is not None and source.last_ts_ms is not None:
            first = int(source.first_ts_ms)
            last = int(source.last_ts_ms)
            if first > last:
                blockers.append("Source timestamp range is inverted.")
            return _TimestampInfo(
                timestamp_key=key,
                first_ts_ms=first,
                last_ts_ms=last,
                row_count=source.row_count,
                values=None,
                warnings=tuple(warnings),
                blockers=tuple(blockers),
            )

        if source.row_count is not None and not key:
            blockers.append(
                "Row count alone is insufficient for timestamp-safe alignment."
            )
        else:
            blockers.append(
                "Source timestamp key and timestamp range are required for safe alignment."
            )
        return _TimestampInfo(
            timestamp_key=key,
            first_ts_ms=source.first_ts_ms,
            last_ts_ms=source.last_ts_ms,
            row_count=source.row_count,
            values=None,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
        )

    def _delta_alignment(
        self,
        *,
        fixed: ConstructBatchSourceRef,
        fixed_ts: "_TimestampInfo",
        variable: ConstructBatchSourceRef,
        variable_ts: "_TimestampInfo",
        existing_blockers: tuple[str, ...],
    ) -> ConstructBatchAlignmentSummary:
        blockers: list[str] = []
        warnings: list[str] = []
        if fixed_ts.timestamp_key and variable_ts.timestamp_key:
            if fixed_ts.timestamp_key != variable_ts.timestamp_key:
                blockers.append(
                    "Delta sources do not expose the same timestamp key."
                )

        if not fixed_ts.blockers and not variable_ts.blockers:
            common_first = max(
                int(fixed_ts.first_ts_ms),
                int(variable_ts.first_ts_ms),
            )
            common_last = min(
                int(fixed_ts.last_ts_ms),
                int(variable_ts.last_ts_ms),
            )
            if common_first > common_last:
                blockers.append("Delta sources have no common timestamp range.")
            aligned_row_count = None
            if fixed_ts.values is not None and variable_ts.values is not None:
                fixed_values = set(fixed_ts.values)
                variable_values = set(variable_ts.values)
                aligned_values = fixed_values.intersection(variable_values)
                if common_first <= common_last:
                    aligned_values = {
                        value
                        for value in aligned_values
                        if common_first <= value <= common_last
                    }
                aligned_row_count = len(aligned_values)
        else:
            common_first = None
            common_last = None
            aligned_row_count = None

        blockers.extend(existing_blockers)
        status = "blocked" if blockers else "aligned"
        return ConstructBatchAlignmentSummary(
            status=status,
            timestamp_key=fixed_ts.timestamp_key or variable_ts.timestamp_key,
            common_first_ts_ms=common_first,
            common_last_ts_ms=common_last,
            aligned_row_count=aligned_row_count,
            source_ranges=(
                fixed_ts.to_source_range(fixed),
                variable_ts.to_source_range(variable),
            ),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
        )

    def _unary_params(
        self,
        *,
        construct_key: str,
        source: ConstructBatchSourceRef,
        user_params: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = get_construct_specs()[construct_key]
        params = build_default_params(spec)
        params.update(dict(user_params))
        token = _source_token(source)
        if construct_key in {"derivative", "angle"}:
            params["source"] = token
            params["source_column"] = token
        elif construct_key in {"percent_span_angle", "angle_momentum"}:
            params["source_columns"] = [token]
        return params

    def _delta_params(
        self,
        *,
        minuend: ConstructBatchSourceRef,
        subtrahend: ConstructBatchSourceRef,
        user_params: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = get_construct_specs()[SUPPORTED_DELTA_CONSTRUCT]
        params = build_default_params(spec)
        params.update(dict(user_params))
        params["fast"] = _source_token(minuend)
        params["slow"] = _source_token(subtrahend)
        return params

    def _unary_input_bindings(
        self,
        *,
        construct_key: str,
        source: ConstructBatchSourceRef,
    ) -> dict[str, Any]:
        token = _source_token(source)
        if construct_key in {"percent_span_angle", "angle_momentum"}:
            return {"source_columns": [token]}
        return {"source": token}

    def _unary_input_binding_meta(
        self,
        *,
        construct_key: str,
        source: ConstructBatchSourceRef,
    ) -> dict[str, Any]:
        meta = self._source_meta(source)
        if construct_key in {"percent_span_angle", "angle_momentum"}:
            return {"source_columns": [meta]}
        return {"source": meta}

    def _source_meta(self, source: ConstructBatchSourceRef) -> dict[str, Any]:
        family = _normalize_source_family(source.source_family)
        path = _source_path(source)
        source_kind = "default" if family in {"ohlc", "default"} else "saved"
        return {
            "source_id": source.source_id,
            "display_name": source.display_name,
            "family": "default" if family in {"ohlc", "default"} else family,
            "source_family": family,
            "source_kind": source_kind,
            "series_key": _source_token(source),
            "column_name": source.column_name,
            "artifact_path": path.as_posix() if path else "",
            "metadata_path": _path_text(source.metadata_path),
            "selectable": bool(source.selectable),
            "analysis_usable": bool(source.analysis_usable),
            "renderable": bool(source.renderable),
        }

    def _existing_recipe_status(
        self,
        recipe: ArtifactRecipe,
    ) -> tuple[ConstructBatchItemStatus, ArtifactRecipe | None, tuple[str, ...], tuple[str, ...]]:
        path = self._recipe_store.recipe_path(
            market=recipe.market,
            recipe_id=recipe.recipe_id,
        )
        if not path.exists():
            return "planned", None, (), ()
        try:
            existing = self._recipe_store.load_recipe(
                market=recipe.market,
                recipe_id=recipe.recipe_id,
            )
        except Exception as exc:
            return (
                "blocked",
                None,
                (),
                (f"Existing artifact recipe could not be read: {path} ({exc})",),
            )
        if existing.recipe_hash != recipe.recipe_hash:
            return (
                "blocked",
                existing,
                (),
                (
                    "Artifact recipe identity collision detected with a different recipe payload.",
                ),
            )
        return (
            "existing_recipe",
            existing,
            ("Equivalent artifact recipe already exists and can be reused.",),
            (),
        )

    def _unary_display_name(
        self,
        construct_key: str,
        source: ConstructBatchSourceRef,
    ) -> str:
        title = get_construct_specs()[construct_key].title
        return f"{title} - {_source_label(source)}"

    def _item_id(
        self,
        *,
        batch_kind: ConstructBatchKind,
        construct_key: str,
        role_bindings: Mapping[str, str],
    ) -> str:
        binding_part = "__".join(
            f"{_slug(key)}_{_slug(value)}"
            for key, value in sorted(role_bindings.items())
        )
        return f"cb__{batch_kind}__{_slug(construct_key)}__{binding_part or 'candidate'}"


@dataclass(frozen=True)
class _TimestampInfo:
    timestamp_key: str | None
    first_ts_ms: int | None
    last_ts_ms: int | None
    row_count: int | None
    values: tuple[int, ...] | None
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_source_range(self, source: ConstructBatchSourceRef) -> dict[str, object]:
        return {
            "source_id": source.source_id,
            "display_name": source.display_name,
            "timestamp_key": self.timestamp_key,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "row_count": self.row_count,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


def _timestamp_info_from_values(
    *,
    source: ConstructBatchSourceRef,
    key: str,
    values: tuple[int, ...],
    warnings: list[str],
) -> _TimestampInfo:
    blockers: list[str] = []
    if not values:
        blockers.append("Source timestamp values are empty.")
        return _TimestampInfo(
            timestamp_key=key,
            first_ts_ms=None,
            last_ts_ms=None,
            row_count=0,
            values=values,
            warnings=tuple(warnings),
            blockers=tuple(blockers),
        )
    if len(set(values)) != len(values):
        blockers.append("Source contains duplicate timestamp key values.")
    first = min(values)
    last = max(values)
    return _TimestampInfo(
        timestamp_key=key,
        first_ts_ms=first,
        last_ts_ms=last,
        row_count=source.row_count if source.row_count is not None else len(values),
        values=values,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )


def _timestamp_info_from_csv(
    *,
    source: ConstructBatchSourceRef,
    path: Path,
    requested_key: str | None,
) -> _TimestampInfo:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        key = _resolve_timestamp_key(fieldnames, requested_key=requested_key)
        if key is None:
            return _TimestampInfo(
                timestamp_key=requested_key,
                first_ts_ms=None,
                last_ts_ms=None,
                row_count=None,
                values=None,
                warnings=(),
                blockers=(
                    "Source CSV does not contain a supported timestamp key "
                    "('ts_ms' or 'time').",
                ),
            )
        values: list[int] = []
        for row in reader:
            values.append(_coerce_ts_ms(row.get(key)))
    return _timestamp_info_from_values(
        source=source,
        key=key,
        values=tuple(values),
        warnings=[],
    )


def _resolve_timestamp_key(
    fieldnames: Sequence[str],
    *,
    requested_key: str | None,
) -> str | None:
    fields = {str(name).strip(): str(name).strip() for name in fieldnames}
    if requested_key:
        return fields.get(requested_key)
    for key in _TIMESTAMP_KEYS:
        if key in fields:
            return key
    return None


def _coerce_ts_ms(value: object) -> int:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Timestamp value is empty.")
    try:
        return int(float(raw))
    except ValueError:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)


def _normalize_construct_key(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_source_family(value: object) -> str:
    raw = str(value or "").strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    aliases = {
        "ohlcv": "ohlc",
        "price": "ohlc",
        "prices": "ohlc",
        "default": "default",
        "indicators": "indicator",
        "saved_indicator": "indicator",
        "oscillators": "oscillator",
        "saved_oscillator": "oscillator",
        "constructs": "construct",
        "saved_construct": "construct",
    }
    if raw in aliases:
        return aliases[raw]
    if raw.endswith("s"):
        return raw[:-1]
    return raw


def _source_token(source: ConstructBatchSourceRef) -> str:
    return str(source.source_token or source.column_name or "").strip()


def _source_label(source: ConstructBatchSourceRef) -> str:
    return str(source.display_name or _source_token(source) or source.source_id).strip()


def _same_source(left: ConstructBatchSourceRef, right: ConstructBatchSourceRef) -> bool:
    if left.source_id and right.source_id and left.source_id == right.source_id:
        return True
    left_path = _source_path(left)
    right_path = _source_path(right)
    return (
        _source_token(left) == _source_token(right)
        and left_path is not None
        and right_path is not None
        and left_path == right_path
    )


def _source_path(source: ConstructBatchSourceRef) -> Path | None:
    return _optional_path(source.csv_path) or _optional_path(source.artifact_path)


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    return path


def _path_text(value: str | Path | None) -> str | None:
    path = _optional_path(value)
    if path is None:
        return None
    return path.as_posix()


def _signal_to_dict(signal: object) -> dict[str, object]:
    try:
        data = asdict(signal)  # type: ignore[arg-type]
    except TypeError:
        data = dict(getattr(signal, "__dict__", {}) or {})
    return {str(key): _json_safe(value) for key, value in data.items()}


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _slug(value: object) -> str:
    raw = str(value or "").strip().lower()
    safe = re.sub(r"[^a-z0-9_]+", "_", raw)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "item"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
