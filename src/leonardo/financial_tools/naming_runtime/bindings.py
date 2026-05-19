from __future__ import annotations

from typing import Any, Iterable, Mapping

from .tokens import _slugify_token, build_source_token
from .constructs_core import (
    _normalize_construct_key,
    _normalize_construct_sources,
    _resolve_delta_pairs_from_params,
)

def build_src_binding_slug(source: Any) -> str:
    return f"src-{build_source_token(source)}"


def build_sources_binding_slug(sources: Iterable[Any]) -> str:
    source_tokens = [build_source_token(source) for source in sources]
    if not source_tokens:
        raise ValueError("build_sources_binding_slug requires at least one source")
    return "sources-" + "-".join(source_tokens)


def build_left_right_binding_slug(left: Any, right: Any) -> str:
    return f"left-{build_source_token(left)}__right-{build_source_token(right)}"


def build_source_reference_binding_slug(source: Any, reference: Any) -> str:
    return f"src-{build_source_token(source)}__ref-{build_source_token(reference)}"


def build_fms_binding_slug(*, fast: Any, mid: Any, slow: Any) -> str:
    return (
        f"F-{build_source_token(fast)}"
        f"__M-{build_source_token(mid)}"
        f"__S-{build_source_token(slow)}"
    )

def build_fs_binding_slug(*, fast: Any, slow: Any) -> str:
    """
    Canonical fast/slow binding slug.

    This is the canonical two-role construct binding identity used by active
    constructs such as:
    - delta
    - two-role trap_area configurations

    Important:
    - fast/slow is the current canonical role language for active construct truth
    - this helper intentionally does not preserve older left/right naming as
      canonical identity
    """
    return (
        f"F-{build_source_token(fast)}"
        f"__S-{build_source_token(slow)}"
    )


def build_binding_slug_from_params(
    *,
    construct_key: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    """
    Build the canonical construct binding slug directly from construct params.

    Purpose
    -------
    This helper centralizes role-aware binding identity so that:
    - UI preview
    - controller persistence
    - save-target existence checks

    all derive from the exact same naming-layer logic.

    Resolution policy
    -----------------
    Unary source constructs:
        src-<source>

    Fast/slow constructs:
        F-<fast>__S-<slow>

    Fast/mid/slow constructs:
        F-<fast>__M-<mid>__S-<slow>

    Multi-source constructs:
        sources-<s1>-<s2>-...

    Fallback:
        default

    Important architectural note
    ----------------------------
    This helper resolves canonical construct binding identity from current active
    construct truth. It must not mirror stale UI assumptions or legacy alias-era
    role naming.
    """
    key = _normalize_construct_key(construct_key)
    params = dict(params or {})

    if key in {"derivative", "angle"}:
        source = params.get("source", params.get("source_column"))
        if source is None or str(source).strip() == "":
            return "default"
        return build_src_binding_slug(source)

    if key == "delta":
        pairs = _resolve_delta_pairs_from_params(params)
        if len(pairs) == 1:
            fast, slow = pairs[0]
            return build_fs_binding_slug(fast=fast, slow=slow)

        return "__".join(
            build_fs_binding_slug(fast=fast, slow=slow)
            for fast, slow in pairs
        )

    if key in {"braids", "braid_instability"}:
        fast = params.get("fast")
        mid = params.get("mid")
        slow = params.get("slow")
        if all(str(value).strip() for value in (fast, mid, slow)):
            return build_fms_binding_slug(fast=fast, mid=mid, slow=slow)
        return "default"

    if key == "trap_area":
        fast = params.get("fast")
        slow = params.get("slow")
        mid = params.get("mid")

        if all(str(value).strip() for value in (fast, slow)):
            if mid is not None and str(mid).strip():
                return build_fms_binding_slug(fast=fast, mid=mid, slow=slow)
            return build_fs_binding_slug(fast=fast, slow=slow)
        return "default"

    if key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
        source_columns = params.get("source_columns", params.get("angle_columns"))
        if source_columns is None:
            return "default"

        sources = _normalize_construct_sources(
            source_columns,
            context=f"{key}.source_columns",
        )
        return build_sources_binding_slug(sources)

    # Keep the documented fallback behavior explicit.
    # This path is reached by transitional generic instance-key callers that
    # still route non-construct tools through the construct identity helper.
    return "default"

