from __future__ import annotations

from typing import Any, Mapping, Sequence

from .tokens import _slugify_token, build_source_token
from .constructs_core import (
    _normalize_construct_key,
    _normalize_construct_source,
    _normalize_construct_sources,
    _normalize_fast_slow_pair,
    _resolve_delta_pairs_from_params,
)

def build_unary_name(
    source: Any,
    suffix: str,
    *,
    trailing_params: Mapping[str, Any] | None = None,
) -> str:
    """
    Build a unary derived name.

    Format:
        <source>__<suffix>[_param1val_param2val...]

    This helper is the ground-truth builder for active unary construct outputs:

    - derivative:
        <source>__d1
        <source>__d2

    - angle:
        <source>__ang

    It intentionally does not model the older legacy ``__ang_pct`` branch as a
    canonical active unary angle output. That naming mode may still appear in
    historical data or compatibility code paths, but it is not current construct
    ground truth.
    """
    source_token = build_source_token(source)
    suffix_token = _slugify_token(suffix)

    name = f"{source_token}__{suffix_token}"

    if trailing_params:
        for key, value in sorted(trailing_params.items(), key=lambda item: str(item[0])):
            if value is None or value == "":
                continue
            key_token = _slugify_token(key)
            value_token = _slugify_token(value)
            name += f"_{key_token}{value_token}"

    return name


def build_delta_name(
    left: Any,
    rights: Sequence[Any],
    *,
    percent: bool = False,
) -> str:
    """
    Build a legacy directional delta name.

    Legacy format:
        <left>__dlt__<right>
        <left>__dlt_pct__<right>

    Important distinction
    ---------------------
    This helper is retained only for compatibility with older naming policy and
    older saved artifacts that may still rely on ``__dlt__`` style chaining.

    It is *not* the ground-truth emitted naming for the active runtime
    ``delta`` construct.

    Active runtime delta construct naming is now:
        <fast>_<slow>_delta
        <fast>_<slow>_delta_pct

    Keep this helper only where backward compatibility is intentionally useful.
    Do not use it as the canonical builder for active construct signal names.
    """
    if not rights:
        raise ValueError("build_delta_name requires at least one right-side term")

    left_token = build_source_token(left)
    op = "__dlt_pct__" if percent else "__dlt__"

    name = left_token
    for right in rights:
        name += f"{op}{build_source_token(right)}"

    return name


def build_fms_prefix(
    construct_token: str,
    *,
    fast: Any,
    mid: Any,
    slow: Any,
) -> str:
    """
    Legacy fast-mid-slow role prefix helper retained for compatibility in
    binding-style contexts.

    Output naming ground truth for active constructs now comes from the
    construct-specific helpers below, not from this role-encoded format.
    """
    return (
        f"{_slugify_token(construct_token)}"
        f"__F-{build_source_token(fast)}"
        f"__M-{build_source_token(mid)}"
        f"__S-{build_source_token(slow)}"
    )


def build_fms_name(
    construct_token: str,
    *,
    fast: Any,
    mid: Any,
    slow: Any,
    output_suffix: str,
) -> str:
    return (
        f"{build_fms_prefix(construct_token, fast=fast, mid=mid, slow=slow)}"
        f"__{output_suffix}"
    )


# ----------------------------------------------------------------------
# Construct signal naming helpers
# ----------------------------------------------------------------------


def build_derivative_signal_names(source: Any) -> tuple[str, str]:
    """
    Canonical derivative construct output names.

    Ground truth from constructs.py:
    - first derivative  -> <source>__d1
    - second derivative -> <source>__d2
    """
    return (
        build_unary_name(source, "d1"),
        build_unary_name(source, "d2"),
    )


def build_angle_signal_name(source: Any) -> str:
    """
    Canonical unary angle construct output name.

    Ground truth from constructs.py:
        <source>__ang

    Important policy note
    ---------------------
    The older ``__ang_pct`` branch is not part of the canonical active unary
    angle construct anymore. It may still exist as a legacy compatibility
    concept, but it must not remain part of emitted naming ground truth.
    """
    return build_unary_name(source, "ang")


def build_braids_signal_names(*, fast: Any, mid: Any, slow: Any) -> tuple[str, str, str]:
    """
    Canonical braids emitted signal names.

    Ground truth from constructs.py:
    - <fast>_<mid>_<slow>
    - <fast>_<mid>_<slow>_width
    - <fast>_<mid>_<slow>_compression

    These three outputs are all part of the active braids family and must be
    exposed together by the naming layer. Treating braids as a single-output
    construct is now stale and incorrect.
    """
    base = "_".join(
        (
            build_source_token(fast),
            build_source_token(mid),
            build_source_token(slow),
        )
    )
    return (
        base,
        f"{base}_width",
        f"{base}_compression",
    )


def build_braid_instability_signal_name(*, fast: Any, mid: Any, slow: Any, n: Any) -> str:
    """
    Canonical braid_instability emitted signal name.

    Ground truth from constructs.py:
        <fast>_<mid>_<slow>_inst_{n}
    """
    base = "_".join(
        (
            build_source_token(fast),
            build_source_token(mid),
            build_source_token(slow),
        )
    )
    return f"{base}_inst_{_slugify_token(n)}"


def build_delta_signal_name(*, fast: Any, slow: Any, percent: bool = False) -> str:
    """
    Canonical active delta construct emitted signal name.

    Ground truth from constructs.py:
    - absolute mode:
        <fast>_<slow>_delta
    - percent mode:
        <fast>_<slow>_delta_pct

    Important distinction
    ---------------------
    This helper is the canonical builder for the active runtime ``delta``
    construct and must not be confused with the older legacy ``__dlt__`` helper.
    """
    fast_token = build_source_token(fast)
    slow_token = build_source_token(slow)
    suffix = "delta_pct" if percent else "delta"
    return f"{fast_token}_{slow_token}_{suffix}"


def build_trap_area_signal_names(
    *,
    fast: Any,
    slow: Any,
    mid: Any | None = None,
) -> tuple[str, ...]:
    """
    Canonical trap_area emitted signal names.

    Ground truth:
    - 2-source mode:
        <fast_src>_<slow_src>_trapA
    - 3-source mode:
        <fast_src>_<mid_src>_trapA
        <fast_src>_<slow_src>_trapA
        <mid_src>_<slow_src>_trapA

    Important:
    - ``trapA`` intentionally preserves uppercase A by policy.
    """
    fast_token = build_source_token(fast)
    slow_token = build_source_token(slow)

    if mid is None or str(mid).strip() == "":
        return (f"{fast_token}_{slow_token}_trapA",)

    mid_token = build_source_token(mid)
    return (
        f"{fast_token}_{mid_token}_trapA",
        f"{fast_token}_{slow_token}_trapA",
        f"{mid_token}_{slow_token}_trapA",
    )


def build_percent_span_angle_signal_name(source: Any, window: Any) -> str:
    """
    Canonical percent_span_angle emitted signal name.

    Ground truth from constructs.py:
        <source>_ang_pct_span_{window}

    Canonical identity note
    -----------------------
    The construct identity is now ``percent_span_angle``.
    The older ``percent_angle`` name may still map here as a backward alias, but
    the emitted name itself must include the ``_span_`` token.
    """
    return f"{build_source_token(source)}_ang_pct_span_{_slugify_token(window)}"


def build_angle_momentum_signal_name(source: Any, n: Any) -> str:
    """
    Canonical angle_momentum emitted signal name.

    Format:
        <source>_ang_mtm_<n>
    """
    return f"{build_source_token(source)}_ang_mtm_{_slugify_token(n)}"


def _resolve_percent_span_angle_windows_from_params(params: Mapping[str, Any]) -> dict[str, int]:
    """
    Mirror the source/window resolution contract from constructs.py for the
    canonical ``percent_span_angle`` construct.

    Supported parameter shapes
    --------------------------
    - source_windows: {"col_a": 5, "col_b": 8}
    - source + window
    - source_column + window
    - source_columns + window

    Canonical identity rule
    -----------------------
    The resolved mapping belongs to ``percent_span_angle`` even when the caller
    used the backward alias name ``percent_angle`` upstream.
    """
    source_windows = params.get("source_windows")
    if source_windows is not None:
        if not isinstance(source_windows, Mapping) or not source_windows:
            raise ValueError("percent_span_angle.source_windows must be a non-empty mapping")

        resolved: dict[str, int] = {}
        for raw_source, raw_window in source_windows.items():
            source_token = _normalize_construct_source(
                raw_source,
                context="percent_span_angle.source_windows key",
            )
            window = int(raw_window)
            if window < 2:
                raise ValueError(f"percent_span_angle window for '{source_token}' must be >= 2")
            resolved[source_token] = window
        return resolved

    explicit_single = params.get("source", params.get("source_column"))
    if explicit_single is not None:
        source_token = _normalize_construct_source(explicit_single, context="percent_span_angle.source")
        window = int(params.get("window", 2))
        if window < 2:
            raise ValueError("percent_span_angle.window must be >= 2")
        return {source_token: window}

    explicit_many = params.get("source_columns")
    if explicit_many is None:
        raise ValueError(
            "percent_span_angle requires one of: source_windows, source, source_column, or source_columns"
        )

    sources = _normalize_construct_sources(explicit_many, context="percent_span_angle.source_columns")
    window = int(params.get("window", 2))
    if window < 2:
        raise ValueError("percent_span_angle.window must be >= 2")

    return {source: window for source in sources}


def get_construct_signal_names(construct_key: str, **params: Any) -> tuple[str, ...]:
    """
    Return canonical emitted output signal names for active construct families.

    Ground truth is mirrored from constructs.py, with backward aliases accepted
    only where intentionally useful for compatibility.

    Active construct families
    -------------------------
    - dynamic_binning
    - derivative
    - angle
    - braids
    - braid_instability
    - delta
    - trap_area
    - percent_span_angle
    - angle_momentum

    Explicit non-rules
    ------------------
    - ``slope`` is not an active construct family anymore and must not resolve
      as canonical construct ground truth here.
    - unary ``angle`` no longer has two canonical branches. It emits only:
          <source>__ang
    - ``percent_angle`` is not canonical. It is a backward alias for
      ``percent_span_angle``.
    """
    key = _normalize_construct_key(construct_key)

    if key == "derivative":
        source = params.get("source", params.get("source_column"))
        d1_name, d2_name = build_derivative_signal_names(source)
        order = int(params.get("order", 1))
        if order == 1:
            return (d1_name,)
        if order == 2:
            return (d2_name,)
        raise ValueError("derivative.order must be 1 or 2 for canonical signal naming")

    if key == "angle":
        source = params.get("source", params.get("source_column"))
        return (build_angle_signal_name(source),)

    if key == "dynamic_binning":
        return ()

    if key == "braids":
        fast = params.get("fast")
        mid = params.get("mid")
        slow = params.get("slow")
        return build_braids_signal_names(fast=fast, mid=mid, slow=slow)

    if key == "braid_instability":
        fast = params.get("fast")
        mid = params.get("mid")
        slow = params.get("slow")
        n = int(params.get("n", 5))
        if n < 1:
            raise ValueError("braid_instability.n must be >= 1")
        return (build_braid_instability_signal_name(fast=fast, mid=mid, slow=slow, n=n),)

    if key == "delta":
        mode = str(params.get("mode", "abs")).strip().lower()
        if mode not in {"abs", "pct"}:
            raise ValueError("delta.mode must be 'abs' or 'pct' for canonical signal naming")

        pairs = _resolve_delta_pairs_from_params(params)
        percent = mode == "pct"
        return tuple(
            build_delta_signal_name(fast=fast, slow=slow, percent=percent)
            for fast, slow in pairs
        )

    if key == "trap_area":
        fast = params.get("fast")
        slow = params.get("slow")
        mid = params.get("mid")
        return build_trap_area_signal_names(fast=fast, mid=mid, slow=slow)

    if key == "percent_span_angle":
        source_windows = _resolve_percent_span_angle_windows_from_params(params)
        return tuple(
            build_percent_span_angle_signal_name(source, window)
            for source, window in source_windows.items()
        )

    if key == "angle_momentum":
        angle_columns = params.get("angle_columns", params.get("source_columns"))
        sources = _normalize_construct_sources(
            angle_columns,
            context="angle_momentum.angle_columns",
        )
        n = int(params.get("n", 3))
        if n < 1:
            raise ValueError("angle_momentum.n must be >= 1")
        return tuple(build_angle_momentum_signal_name(source, n) for source in sources)

    raise KeyError(f"Unsupported construct key for canonical signal naming: {construct_key}")


# ----------------------------------------------------------------------
