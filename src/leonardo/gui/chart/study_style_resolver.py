from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from leonardo.gui.chart.model import OverlayFill, Series, SeriesStyle
from leonardo.gui.chart.studies import ChartStudyInstance


def resolve_study_render_state(
    *,
    study: ChartStudyInstance,
    series_list: List[Series],
    fill_descriptors: Optional[List[OverlayFill]] = None,
) -> Tuple[List[Series], Optional[List[OverlayFill]]]:
    """
    Resolve the effective render state for one study.

    This function is purely chart-local and visual-only.
    It must not trigger computation and must not mutate the input study.

    Current phase:
    - resolves latest-state conditional style modules
    - supports HCK historical segmented conditional rendering upstream of the renderer
    - keeps signal/fill ownership anchored to existing runtime style state

    Returns:
        (resolved_series_list, resolved_fill_descriptors)

    Notes:
    - series order is preserved
    - fill order is preserved
    - if no fills are supplied, None is returned unless a future caller
      explicitly wants synthesized fills
    """
    # Series/OverlayFill are frozen dataclasses; treat them as immutable transport
    # containers and avoid rebuilding wrapper objects in the hot path.
    normalized_series: List[Series] = series_list

    normalized_fills: Optional[List[OverlayFill]] = None
    if fill_descriptors is not None:
        normalized_fills = [
            fill
            for fill in fill_descriptors
            if str(getattr(fill, "fill_id", "")).strip()
            and str(getattr(fill, "series_a", "")).strip()
            and str(getattr(fill, "series_b", "")).strip()
        ]

    if not normalized_series:
        return normalized_series, normalized_fills

    if not getattr(study, "style", None):
        return normalized_series, normalized_fills

    module_states = _normalized_module_states(getattr(study.style, "style_modules", None))
    if not module_states:
        return normalized_series, normalized_fills

    segmented_state = _resolve_hck_historical_segmented_state_if_applicable(
        study=study,
        series_list=normalized_series,
        fill_descriptors=normalized_fills,
        module_states=module_states,
    )
    if segmented_state is not None:
        return segmented_state

    series_by_signal = _series_by_signal_name(normalized_series)

    resolved_series = normalized_series
    resolved_fills = normalized_fills

    for module_state in module_states:
        if not getattr(module_state, "enabled", True):
            continue

        module_key = str(getattr(module_state, "module_key", "") or "").strip().lower()
        if not module_key:
            continue

        config = getattr(module_state, "config", {}) or {}
        if not isinstance(config, dict):
            continue

        if module_key == "conditional_line_color":
            resolved_series = _apply_conditional_line_color_module(
                series_list=resolved_series,
                series_by_signal=series_by_signal,
                config=config,
            )
            series_by_signal = _series_by_signal_name(resolved_series)
            continue

        if module_key == "conditional_fill_color":
            resolved_fills = _apply_conditional_fill_color_module(
                fill_descriptors=resolved_fills,
                series_by_signal=series_by_signal,
                config=config,
            )
            continue

    return resolved_series, resolved_fills


def _normalized_module_states(raw_modules: object) -> List[object]:
    """
    Return style modules in a normalized iterable form.

    Canonical runtime state stores style_modules as a list of
    StudyStyleModuleState objects, but older or transitional code may still
    pass a dict keyed by module id. This helper accepts both so the resolver
    remains backward-compatible while the rest of the system converges on the
    list-based model.
    """
    if raw_modules is None:
        return []

    if isinstance(raw_modules, list):
        return list(raw_modules)

    if isinstance(raw_modules, tuple):
        return list(raw_modules)

    if isinstance(raw_modules, dict):
        return [module for module in raw_modules.values()]

    return []


def _line_key_from_render_key(render_key: str) -> str:
    text = str(render_key).strip()
    if not text:
        return ""
    return text.rsplit("|", 1)[-1].strip()


def _series_by_signal_name(series_list: List[Series]) -> Dict[str, Series]:
    by_signal: Dict[str, Series] = {}
    for series in series_list:
        signal_name = _line_key_from_render_key(series.key)
        if signal_name and signal_name not in by_signal:
            by_signal[signal_name] = series
    return by_signal


def _latest_valid_value(series: Optional[Series]) -> Optional[float]:
    if series is None:
        return None

    values = getattr(series, "values", None)
    if values is None:
        return None

    try:
        value_count = len(values)  # type: ignore[arg-type]
    except Exception:
        try:
            values = list(values)  # type: ignore[arg-type]
            value_count = len(values)
        except Exception:
            return None

    for idx in range(value_count - 1, -1, -1):
        try:
            value = values[idx]  # type: ignore[index]
        except Exception:
            continue
        try:
            numeric = float(value)
        except Exception:
            continue
        if numeric == numeric:
            return numeric
    return None



def _module_state_by_key(module_states: List[object], module_key: str) -> Optional[object]:
    resolved_module_key = str(module_key).strip().lower()
    if not resolved_module_key:
        return None

    for module_state in module_states:
        if not getattr(module_state, "enabled", True):
            continue
        current_key = str(getattr(module_state, "module_key", "") or "").strip().lower()
        if current_key == resolved_module_key:
            return module_state
    return None


def _module_config(module_state: Optional[object]) -> Dict[str, object]:
    if module_state is None:
        return {}
    config = getattr(module_state, "config", {}) or {}
    return dict(config) if isinstance(config, dict) else {}


def _condition_scope(config: Mapping[str, object]) -> str:
    condition = config.get("condition", {}) or {}
    if not isinstance(condition, dict):
        return ""
    return str(condition.get("scope", "") or "").strip().lower()


def _fill_id_suffix(fill_id: str) -> str:
    text = str(fill_id).strip()
    if not text:
        return ""
    if "|fill|" in text:
        return text.split("|fill|", 1)[-1].strip()
    return text


def _fill_matches_target(*, fill_id: str, target_fill_id: str) -> bool:
    resolved_fill_id = str(fill_id).strip()
    resolved_target_fill_id = str(target_fill_id).strip()
    if not resolved_fill_id or not resolved_target_fill_id:
        return False
    if resolved_fill_id == resolved_target_fill_id:
        return True
    return _fill_id_suffix(resolved_fill_id) == _fill_id_suffix(resolved_target_fill_id)


def _condition_outcome_for_values(
    *,
    lhs_value: float,
    rhs_value: float,
    operator: str,
) -> Optional[bool]:
    if lhs_value != lhs_value or rhs_value != rhs_value:
        return None

    normalized_operator = str(operator).strip().lower()
    if normalized_operator == "gt":
        return lhs_value > rhs_value
    if normalized_operator == "gte":
        return lhs_value >= rhs_value
    if normalized_operator == "lt":
        return lhs_value < rhs_value
    if normalized_operator == "lte":
        return lhs_value <= rhs_value
    if normalized_operator == "eq":
        return lhs_value == rhs_value
    if normalized_operator == "neq":
        return lhs_value != rhs_value
    return None


def _evaluate_historical_condition_outcomes(
    *,
    series_by_signal: Dict[str, Series],
    condition: Dict[str, object],
) -> Optional[List[Optional[bool]]]:
    lhs_signal = str(condition.get("lhs_signal", "")).strip()
    rhs_signal = str(condition.get("rhs_signal", "")).strip()
    operator = str(condition.get("operator", "")).strip().lower()
    scope = str(condition.get("scope", "")).strip().lower()

    if scope != "historical":
        return None
    if not lhs_signal or not rhs_signal or not operator:
        return None

    lhs_series = series_by_signal.get(lhs_signal)
    rhs_series = series_by_signal.get(rhs_signal)
    if lhs_series is None or rhs_series is None:
        return None

    lhs_values = getattr(lhs_series, "values", None)
    rhs_values = getattr(rhs_series, "values", None)
    if lhs_values is None:
        lhs_values = []
    if rhs_values is None:
        rhs_values = []
    try:
        lhs_len = len(lhs_values)
    except Exception:
        lhs_len = 0
    try:
        rhs_len = len(rhs_values)
    except Exception:
        rhs_len = 0
    length = max(lhs_len, rhs_len)
    if length <= 0:
        return None

    outcomes: List[Optional[bool]] = []
    for idx in range(length):
        try:
            lhs_value = float(lhs_values[idx]) if idx < lhs_len else float("nan")
        except Exception:
            lhs_value = float("nan")
        try:
            rhs_value = float(rhs_values[idx]) if idx < rhs_len else float("nan")
        except Exception:
            rhs_value = float("nan")

        outcomes.append(
            _condition_outcome_for_values(
                lhs_value=lhs_value,
                rhs_value=rhs_value,
                operator=operator,
            )
        )

    return outcomes


def _segmented_render_key(render_key: str, segment: str) -> str:
    text = str(render_key).strip()
    resolved_segment = str(segment).strip().lower()
    if not text or not resolved_segment:
        return text
    if "|" not in text:
        return f"{text}|{resolved_segment}|{text}"
    head, line_key = text.rsplit("|", 1)
    return f"{head}|{resolved_segment}|{line_key}"


def _segmented_fill_id(fill_id: str, segment: str) -> str:
    text = str(fill_id).strip()
    resolved_segment = str(segment).strip().lower()
    if not text or not resolved_segment:
        return text
    return f"{text}|{resolved_segment}"


def _series_style_with_color(series: Series, color: str) -> SeriesStyle:
    existing_style = series.style if series.style is not None else SeriesStyle()
    chosen_color = str(color or "").strip() or str(getattr(existing_style, "color", "") or "").strip()
    return SeriesStyle(
        color=chosen_color,
        line_width=max(1, int(getattr(existing_style, "line_width", 1) or 1)),
        line_style=str(getattr(existing_style, "line_style", "solid") or "solid"),
        visible=bool(getattr(existing_style, "visible", True)),
        render_mode=str(getattr(existing_style, "render_mode", "line") or "line"),
        marker_shape=getattr(existing_style, "marker_shape", None),
        marker_size=int(getattr(existing_style, "marker_size", 0) or 0),
        marker_text=str(getattr(existing_style, "marker_text", "") or ""),
        marker_text_color=getattr(existing_style, "marker_text_color", None),
        marker_offset_px=int(getattr(existing_style, "marker_offset_px", 0) or 0),
    )


class _MaskedOutcomeValues:
    """Lazy masked view over base values for segmented conditional rendering.

    This avoids allocating N-sized masked arrays for each branch while
    preserving NaN-gapped semantics for renderers and overlay UI.
    """

    __slots__ = ("_base", "_outcomes", "_truth", "_n", "_outcome_n")

    def __init__(
        self,
        base_values: object,
        outcomes: List[Optional[bool]],
        truth_value: bool,
    ) -> None:
        self._base = base_values
        self._outcomes = outcomes
        self._truth = bool(truth_value)
        try:
            self._n = len(base_values)  # type: ignore[arg-type]
        except Exception:
            self._n = 0
        self._outcome_n = len(outcomes)

    def __len__(self) -> int:
        return int(self._n)

    def __getitem__(self, idx: int) -> float:
        if idx < 0 or idx >= int(self._n):
            raise IndexError(idx)

        nan_value = float("nan")

        try:
            raw = self._base[idx]  # type: ignore[index]
        except Exception:
            return nan_value

        try:
            numeric = float(raw)
        except Exception:
            return nan_value

        if numeric != numeric:
            return nan_value

        outcome = self._outcomes[idx] if idx < self._outcome_n else None
        prev_outcome = self._outcomes[idx - 1] if idx > 0 and (idx - 1) < self._outcome_n else None
        next_outcome = self._outcomes[idx + 1] if (idx + 1) < self._outcome_n else None

        truth = self._truth
        include_point = outcome is truth

        # Crossover continuity: duplicate the boundary bar onto both
        # branches when a transition occurs so the crossover remains
        # visible without moving semantics into the renderer.
        if not include_point and outcome is not None:
            if prev_outcome is truth and prev_outcome != outcome:
                include_point = True
            elif next_outcome is truth and next_outcome != outcome:
                include_point = True

        return numeric if include_point else nan_value

    def __iter__(self):
        for i in range(int(self._n)):
            yield self[i]

def _masked_segment_series(
    *,
    series: Series,
    outcomes: List[Optional[bool]],
    truth_value: bool,
    segment: str,
    color: str,
) -> Series:
    """Return one segmented renderer-facing branch with crossover continuity.

    This avoids allocating an N-sized masked array per branch by using a
    lazy masked values view. The renderer still consumes NaN-gapped values
    so gap honesty and crossover continuity remain explicit upstream.
    """
    base_values = getattr(series, "values", None)
    if base_values is None:
        base_values = []
    masked_view = _MaskedOutcomeValues(
        base_values=base_values,
        outcomes=outcomes,
        truth_value=bool(truth_value),
    )
    return Series(
        key=_segmented_render_key(series.key, segment),
        title=str(series.title),
        values=masked_view,
        style=_series_style_with_color(series, color),
    )



def _resolve_hck_historical_segmented_state_if_applicable(
    *,
    study: ChartStudyInstance,
    series_list: List[Series],
    fill_descriptors: Optional[List[OverlayFill]],
    module_states: List[object],
) -> Optional[Tuple[List[Series], Optional[List[OverlayFill]]]]:
    """Resolve HCK as historical segmented render payload when configured.

    The panel / resolver own chart-local visual derivation for studies.
    The renderer executes the explicit segmented payload only.
    """
    tool_key = str(getattr(getattr(study, "computation", None), "tool_key", "") or "").strip().lower()
    if tool_key != "hck":
        return None

    line_module = _module_state_by_key(module_states, "conditional_line_color")
    fill_module = _module_state_by_key(module_states, "conditional_fill_color")

    line_config = _module_config(line_module)
    fill_config = _module_config(fill_module)

    line_scope = _condition_scope(line_config)
    fill_scope = _condition_scope(fill_config)
    if line_scope != "historical" and fill_scope != "historical":
        return None

    condition: Dict[str, object] = {}
    raw_line_condition = line_config.get("condition", {}) or {}
    raw_fill_condition = fill_config.get("condition", {}) or {}
    if isinstance(raw_line_condition, dict) and raw_line_condition:
        condition = dict(raw_line_condition)
    elif isinstance(raw_fill_condition, dict) and raw_fill_condition:
        condition = dict(raw_fill_condition)
    else:
        return None

    series_by_signal = _series_by_signal_name(series_list)
    outcomes = _evaluate_historical_condition_outcomes(
        series_by_signal=series_by_signal,
        condition=condition,
    )
    if outcomes is None:
        return None

    targeted_signals = {
        str(condition.get("lhs_signal", "")).strip(),
        str(condition.get("rhs_signal", "")).strip(),
    }
    targeted_signals.discard("")
    if not targeted_signals:
        return None

    line_targets = line_config.get("targets", []) or []
    target_color_by_signal: Dict[str, Dict[str, str]] = {}
    if isinstance(line_targets, list):
        for target in line_targets:
            if not isinstance(target, dict):
                continue
            signal_name = str(target.get("signal", "")).strip()
            if not signal_name:
                continue
            target_color_by_signal[signal_name] = {
                "true_color": str(target.get("true_color", "")).strip(),
                "false_color": str(target.get("false_color", "")).strip(),
            }

    resolved_series: List[Series] = []
    for series in series_list:
        signal_name = _line_key_from_render_key(series.key)
        if signal_name not in targeted_signals:
            resolved_series.append(series)
            continue

        color_spec = target_color_by_signal.get(signal_name, {})
        existing_color = str(getattr(series.style, "color", "") or "").strip() if series.style is not None else ""
        bullish_color = color_spec.get("true_color", "") or existing_color
        bearish_color = color_spec.get("false_color", "") or existing_color

        resolved_series.append(
            _masked_segment_series(
                series=series,
                outcomes=outcomes,
                truth_value=True,
                segment="bull",
                color=bullish_color,
            )
        )
        resolved_series.append(
            _masked_segment_series(
                series=series,
                outcomes=outcomes,
                truth_value=False,
                segment="bear",
                color=bearish_color,
            )
        )

    resolved_fills: Optional[List[OverlayFill]] = None if fill_descriptors is None else []
    if fill_descriptors is not None:
        if fill_scope == "historical":
            target_fill_id = str(fill_config.get("target_fill_id", "")).strip()
            true_color = str(fill_config.get("true_color", "")).strip()
            false_color = str(fill_config.get("false_color", "")).strip()
            try:
                true_opacity = float(fill_config.get("true_opacity", 0.15))
            except Exception:
                true_opacity = 0.15
            try:
                false_opacity = float(fill_config.get("false_opacity", 0.15))
            except Exception:
                false_opacity = 0.15

            for fill in fill_descriptors:
                if target_fill_id and _fill_matches_target(
                    fill_id=str(fill.fill_id).strip(),
                    target_fill_id=target_fill_id,
                ):
                    resolved_fills.append(
                        OverlayFill(
                            fill_id=_segmented_fill_id(fill.fill_id, "bull"),
                            series_a=_segmented_render_key(fill.series_a, "bull"),
                            series_b=_segmented_render_key(fill.series_b, "bull"),
                            color=true_color or fill.color,
                            opacity=max(0.0, min(1.0, true_opacity)),
                            visible=bool(fill.visible),
                        )
                    )
                    resolved_fills.append(
                        OverlayFill(
                            fill_id=_segmented_fill_id(fill.fill_id, "bear"),
                            series_a=_segmented_render_key(fill.series_a, "bear"),
                            series_b=_segmented_render_key(fill.series_b, "bear"),
                            color=false_color or fill.color,
                            opacity=max(0.0, min(1.0, false_opacity)),
                            visible=bool(fill.visible),
                        )
                    )
                    continue

                signal_a_name = _line_key_from_render_key(fill.series_a)
                signal_b_name = _line_key_from_render_key(fill.series_b)
                if signal_a_name not in targeted_signals and signal_b_name not in targeted_signals:
                    resolved_fills.append(fill)

    return resolved_series, resolved_fills


def _evaluate_latest_condition(
    *,
    series_by_signal: Dict[str, Series],
    condition: Dict[str, object],
) -> Optional[bool]:
    """
    Evaluate a latest-state signal-vs-signal condition.

    Supported operators for current phase:
    - gt
    - gte
    - lt
    - lte
    - eq
    - neq
    """
    lhs_signal = str(condition.get("lhs_signal", "")).strip()
    rhs_signal = str(condition.get("rhs_signal", "")).strip()
    operator = str(condition.get("operator", "")).strip().lower()
    scope = str(condition.get("scope", "latest")).strip().lower()

    if scope != "latest":
        return None
    if not lhs_signal or not rhs_signal or not operator:
        return None

    lhs_value = _latest_valid_value(series_by_signal.get(lhs_signal))
    rhs_value = _latest_valid_value(series_by_signal.get(rhs_signal))

    if lhs_value is None or rhs_value is None:
        return None

    return _condition_outcome_for_values(
        lhs_value=lhs_value,
        rhs_value=rhs_value,
        operator=operator,
    )


def _apply_conditional_line_color_module(
    *,
    series_list: List[Series],
    series_by_signal: Dict[str, Series],
    config: Dict[str, object],
) -> List[Series]:
    """
    Apply latest-state conditional line color overrides.

    Expected config shape:
        {
            "condition": {
                "lhs_signal": "fast_vwap",
                "operator": "gt",
                "rhs_signal": "slow_vwap",
                "scope": "latest",
            },
            "targets": [
                {
                    "signal": "fast_vwap",
                    "true_color": "#22C55E",
                    "false_color": "#EF4444",
                },
                {
                    "signal": "slow_vwap",
                    "true_color": "#22C55E",
                    "false_color": "#EF4444",
                },
            ],
        }
    """
    condition = config.get("condition", {}) or {}
    targets = config.get("targets", []) or []
    if not isinstance(condition, dict) or not isinstance(targets, list):
        return series_list

    outcome = _evaluate_latest_condition(
        series_by_signal=series_by_signal,
        condition=condition,
    )
    if outcome is None:
        return series_list

    color_by_signal: Dict[str, str] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue

        signal_name = str(target.get("signal", "")).strip()
        if not signal_name:
            continue

        true_color = str(target.get("true_color", "")).strip()
        false_color = str(target.get("false_color", "")).strip()
        chosen = true_color if outcome else false_color
        if chosen:
            color_by_signal[signal_name] = chosen

    if not color_by_signal:
        return series_list

    resolved: List[Series] = []
    for series in series_list:
        signal_name = _line_key_from_render_key(series.key)
        chosen_color = color_by_signal.get(signal_name)
        if not chosen_color:
            resolved.append(series)
            continue

        existing_style = series.style if series.style is not None else SeriesStyle()
        next_style = SeriesStyle(
            color=chosen_color,
            line_width=max(1, int(getattr(existing_style, "line_width", 1) or 1)),
            line_style=str(getattr(existing_style, "line_style", "solid") or "solid"),
            visible=bool(getattr(existing_style, "visible", True)),
            render_mode=str(getattr(existing_style, "render_mode", "line") or "line"),
            marker_shape=getattr(existing_style, "marker_shape", None),
            marker_size=int(getattr(existing_style, "marker_size", 0) or 0),
            marker_text=str(getattr(existing_style, "marker_text", "") or ""),
            marker_text_color=getattr(existing_style, "marker_text_color", None),
            marker_offset_px=int(getattr(existing_style, "marker_offset_px", 0) or 0),
        )
        if next_style == existing_style:
            resolved.append(series)
        else:
            resolved.append(
                Series(
                    key=series.key,
                    title=series.title,
                    values=series.values,
                    style=next_style,
                )
            )

    return resolved


def _apply_conditional_fill_color_module(
    *,
    fill_descriptors: Optional[List[OverlayFill]],
    series_by_signal: Dict[str, Series],
    config: Dict[str, object],
) -> Optional[List[OverlayFill]]:
    """
    Apply latest-state conditional fill overrides.

    Expected config shape:
        {
            "condition": {
                "lhs_signal": "fast_vwap",
                "operator": "gt",
                "rhs_signal": "slow_vwap",
                "scope": "latest",
            },
            "target_fill_id": "hck_band",
            "true_color": "#22C55E",
            "false_color": "#EF4444",
            "true_opacity": 0.40,
            "false_opacity": 0.40,
        }

    Important current limitation:
    - the active price-fill renderer consumes one static color/opacity per fill
      descriptor, not historical per-bar fill states
    - a latest-state HCK conditional fill would therefore tint the entire
      historical band bullish or bearish, which is visually misleading

    Until segmented historical fill rendering is requested upstream via
    ``scope='historical'``, the resolver keeps HCK latest-state fill modules
    inert unless they explicitly opt into whole-study tinting via
    ``allow_whole_study_tint=True``.
    """
    if not fill_descriptors:
        return fill_descriptors

    condition = config.get("condition", {}) or {}
    if not isinstance(condition, dict):
        return fill_descriptors

    target_fill_id = str(config.get("target_fill_id", "")).strip()
    if not target_fill_id:
        return fill_descriptors

    condition_scope = str(condition.get("scope", "latest") or "latest").strip().lower()
    if (
        condition_scope == "latest"
        and _fill_id_suffix(target_fill_id) == "hck_band"
        and not bool(config.get("allow_whole_study_tint", False))
    ):
        return fill_descriptors

    outcome = _evaluate_latest_condition(
        series_by_signal=series_by_signal,
        condition=condition,
    )
    if outcome is None:
        return fill_descriptors

    true_color = str(config.get("true_color", "")).strip()
    false_color = str(config.get("false_color", "")).strip()

    true_opacity = config.get("true_opacity", None)
    false_opacity = config.get("false_opacity", None)

    resolved: List[OverlayFill] = []
    for fill in fill_descriptors:
        if not _fill_matches_target(
            fill_id=str(fill.fill_id).strip(),
            target_fill_id=target_fill_id,
        ):
            resolved.append(fill)
            continue

        color = true_color if outcome else false_color
        opacity_value = true_opacity if outcome else false_opacity

        try:
            opacity = float(opacity_value) if opacity_value is not None else float(fill.opacity)
        except Exception:
            opacity = float(fill.opacity)

        next_color = color or fill.color
        next_opacity = max(0.0, min(1.0, opacity))
        if next_color == fill.color and next_opacity == float(fill.opacity):
            resolved.append(fill)
        else:
            resolved.append(
                OverlayFill(
                    fill_id=fill.fill_id,
                    series_a=fill.series_a,
                    series_b=fill.series_b,
                    color=next_color,
                    opacity=next_opacity,
                    visible=bool(fill.visible),
                )
            )

    return resolved
