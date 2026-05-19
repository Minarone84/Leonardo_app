from __future__ import annotations

from typing import Any, Iterable, Mapping

from .tokens import _slugify_token, build_source_token

def _normalize_construct_key(construct_key: Any) -> str:
    """
    Normalize construct keys while preserving intentionally supported aliases.

    Runtime-ground-truth primary construct identities
    -------------------------------------------------
    These are the active construct families defined by constructs.py and they
    are the canonical naming identities that the rest of the project should
    use when resolving construct columns, construct tokens, and saved construct
    filenames:

    - dynamic_binning
    - derivative
    - angle
    - braids
    - braid_instability
    - delta
    - trap_area
    - percent_span_angle
    - angle_momentum

    Important policy rules
    ----------------------
    1. ``slope`` is no longer an active construct family and must not remain
       part of construct ground truth in the naming layer.

    2. ``percent_span_angle`` is the canonical construct identity.
       The older ``percent_angle`` name is accepted only as a backward alias.

    3. Alias preservation exists strictly for compatibility at public entry
       points. It must not silently redefine canonical construct identity.

    Supported compatibility aliases
    -------------------------------
    - dynamic_binning_analysis -> dynamic_binning
    - derivative_analysis -> derivative
    - angle_analysis -> angle
    - braid_state_analysis -> braids
    - trap_area_analysis -> trap_area
    - percent_angle -> percent_span_angle
    - percent_angle_analysis -> percent_span_angle
    - percent_span_angle_analysis -> percent_span_angle
    """
    key = _slugify_token(construct_key)

    aliases = {
        "dynamic_binning_analysis": "dynamic_binning",
        "derivative_analysis": "derivative",
        "angle_analysis": "angle",
        "braid_state_analysis": "braids",
        "trap_area_analysis": "trap_area",
        "percent_angle": "percent_span_angle",
        "percent_angle_analysis": "percent_span_angle",
        "percent_span_angle_analysis": "percent_span_angle",
    }
    return aliases.get(key, key)


def _normalize_construct_source(source: Any, *, context: str) -> str:
    token = build_source_token(source)
    if token == "unknown":
        raise ValueError(f"{context} requires a non-empty source")
    return token


def _normalize_construct_sources(
    sources: Iterable[Any] | str | None,
    *,
    context: str,
) -> tuple[str, ...]:
    if sources is None:
        raise ValueError(f"{context} must not be empty")

    if isinstance(sources, str):
        raw = [part.strip() for part in sources.split(",")]
    else:
        raw = [str(value).strip() for value in sources]

    tokens = tuple(build_source_token(value) for value in raw if str(value).strip())
    if not tokens:
        raise ValueError(f"{context} must not be empty")

    duplicates = sorted({token for token in tokens if tokens.count(token) > 1})
    if duplicates:
        raise ValueError(f"{context} contains duplicate sources: {duplicates}")

    return tokens


def _normalize_fast_slow_pair(*, fast: Any, slow: Any, context: str) -> tuple[str, str]:
    """
    Normalize a single fast/slow pair for active construct naming helpers.

    This mirrors the directional semantics used by the runtime ``delta``
    construct and the two-role mode of ``trap_area``:

    - ``fast`` is the minuend / leading reference
    - ``slow`` is the subtrahend / baseline reference
    """
    fast_token = _normalize_construct_source(fast, context=f"{context}.fast")
    slow_token = _normalize_construct_source(slow, context=f"{context}.slow")
    return fast_token, slow_token


def _resolve_delta_pairs_from_params(params: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """
    Mirror the supported delta pair configuration contract from constructs.py.

    Supported parameter shapes
    --------------------------
    1. Single pair:
       - fast
       - slow

    2. Multiple pairs:
       - pairs=[{"fast": "...", "slow": "..."}, ...]

    Design note
    -----------
    The active delta construct is intentionally directional and always means:

        fast - slow

    Therefore the emitted names preserve that same directional ordering.
    """
    pairs_raw = params.get("pairs")
    if pairs_raw is not None:
        if not isinstance(pairs_raw, (list, tuple)) or not pairs_raw:
            raise ValueError("delta.pairs must be a non-empty list of pair definitions")

        resolved: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for i, pair in enumerate(pairs_raw):
            if not isinstance(pair, Mapping):
                raise ValueError(f"delta.pairs[{i}] must be a mapping with 'fast' and 'slow'")

            fast_token, slow_token = _normalize_fast_slow_pair(
                fast=pair.get("fast"),
                slow=pair.get("slow"),
                context=f"delta.pairs[{i}]",
            )

            key = (fast_token, slow_token)
            if key in seen:
                raise ValueError(f"delta.pairs contains duplicate pair ({fast_token}, {slow_token})")
            seen.add(key)

            resolved.append(key)

        return tuple(resolved)

    fast_token, slow_token = _normalize_fast_slow_pair(
        fast=params.get("fast"),
        slow=params.get("slow"),
        context="delta",
    )
    return ((fast_token, slow_token),)

