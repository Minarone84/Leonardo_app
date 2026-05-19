from __future__ import annotations

from typing import Any, Iterable, Mapping

from .tokens import _slugify_token
from .hashing import _short_hash
from .constructs import build_unary_name
from .constructs_core import _normalize_construct_key
from .bindings import build_binding_slug_from_params


_ACTIVE_CONSTRUCT_KEYS = {
    "dynamic_binning",
    "derivative",
    "angle",
    "braids",
    "braid_instability",
    "delta",
    "trap_area",
    "percent_span_angle",
    "angle_momentum",
}


def _is_active_construct_key(construct_key: str) -> bool:
    return _normalize_construct_key(construct_key) in _ACTIVE_CONSTRUCT_KEYS


def _identity_params_for_hash(
    params: Mapping[str, Any],
    *,
    exclude_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    excluded = {str(key) for key in (exclude_keys or ())}
    out: dict[str, Any] = {}
    for key, value in sorted(params.items(), key=lambda item: str(item[0])):
        key_text = str(key)
        if key_text in excluded:
            continue
        if value is None or value == "":
            continue
        out[key_text] = value
    return out


def _construct_identity_hash(
    *,
    construct_key: str,
    binding_slug: str,
    params: Mapping[str, Any],
    exclude_param_keys: Iterable[str] | None,
    hash_len: int,
) -> str:
    length = max(1, int(hash_len or 8))
    payload = {
        "construct_key": _normalize_construct_key(construct_key),
        "binding_slug": str(binding_slug or "default"),
        "params": _identity_params_for_hash(params, exclude_keys=exclude_param_keys),
    }
    return _short_hash(payload, length=length)




def _slugify_binding_slug(binding_slug: str) -> str:
    sentinel = "zzdbluszz"
    protected = str(binding_slug or "default").replace("__", sentinel)
    slugged = _slugify_token(protected)
    restored = slugged.replace(sentinel, "__").strip("_-")
    return restored or "default"

def _append_hash_suffix(
    readable: str,
    *,
    identity_hash: str,
    max_readable_length: int,
) -> str:
    suffix = f"__h{identity_hash}"
    max_len = max(len(suffix) + 1, int(max_readable_length or 120))
    base = str(readable).strip().rstrip("_-") or "construct"
    allowed_base_len = max(1, max_len - len(suffix))
    if len(base) > allowed_base_len:
        base = base[:allowed_base_len].rstrip("_-") or base[:allowed_base_len]
    return f"{base}{suffix}"

def build_construct_instance_key_from_params(
    *,
    construct_key: str,
    params: Mapping[str, Any] | None = None,
    exclude_param_keys: Iterable[str] | None = None,
    hash_len: int = 8,
    max_readable_length: int = 120,
) -> str:
    """
    Convenience wrapper that derives the canonical binding slug from params and
    then builds the canonical construct instance key.

    This is the preferred entrypoint for UI/controller code when construct
    identity is being derived from user-selected/runtime params rather than from
    an already-finalized external binding slug.
    """
    params_dict = dict(params or {})
    binding_slug = build_binding_slug_from_params(
        construct_key=construct_key,
        params=params_dict,
    )

    return build_construct_instance_key(
        construct_key=construct_key,
        binding_slug=binding_slug,
        params=params_dict,
        exclude_param_keys=exclude_param_keys,
        hash_len=hash_len,
        max_readable_length=max_readable_length,
    )


# ----------------------------------------------------------------------
# Canonical construct token resolution (single source of truth)
# ----------------------------------------------------------------------


def resolve_construct_token(
    *,
    construct_key: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    """
    Resolve the canonical operator / family token used by a construct for naming
    and persistence contexts.

    Important scope distinction
    ---------------------------
    This helper resolves the canonical family/operator token, not the full
    emitted signal name.

    For unary single-source constructs, that token becomes the unary suffix:
    - derivative(order=1) -> d1
    - derivative(order=2) -> d2
    - angle -> ang

    For non-unary constructs, this token is used in persistence-style contexts
    such as saved construct instance keys:
    - dynamic_binning
    - braids
    - braid_instability
    - delta
    - trap_area
    - percent_span_angle
    - angle_momentum

    Canonicality rules
    ------------------
    - ``slope`` is no longer active and must not resolve here.
    - ``angle`` resolves only to ``ang``.
    - ``percent_angle`` must normalize to ``percent_span_angle`` before token
      resolution.
    """
    key = _normalize_construct_key(construct_key)
    params = dict(params or {})

    if key == "derivative":
        order = int(params.get("order", 1))
        if order == 1:
            return "d1"
        if order == 2:
            return "d2"
        raise ValueError("derivative.order must be 1 or 2 for canonical naming")

    if key == "angle":
        return "ang"

    if key == "dynamic_binning":
        return "dynamic_binning"

    if key == "braids":
        return "braids"

    if key == "braid_instability":
        return "braid_instability"

    if key == "delta":
        return "delta"

    if key == "trap_area":
        return "trap_area"

    if key == "percent_span_angle":
        return "percent_span_angle"

    if key == "angle_momentum":
        return "angle_momentum"

    return key


def _is_unary_single_source_construct(
    *,
    construct_key: str,
    params: Mapping[str, Any] | None = None,
) -> bool:
    """
    Return whether the construct follows canonical unary source-first naming for
    saved instance keys.

    Active unary single-source construct families are now exactly:
    - derivative
    - angle

    Explicit non-rule:
    - slope is no longer active and must not be treated as unary ground truth.
    """
    key = _normalize_construct_key(construct_key)
    return key in {
        "derivative",
        "angle",
    }


# ----------------------------------------------------------------------
# Saved construct instance naming
# ----------------------------------------------------------------------


def build_param_slug(
    params: Mapping[str, Any] | None,
    *,
    exclude_keys: Iterable[str] | None = None,
) -> str:
    """
    Build a compact deterministic parameter slug.
    """
    if not params:
        return "default"

    excluded = {str(key) for key in (exclude_keys or ())}
    parts: list[str] = []

    for key, value in sorted(params.items(), key=lambda item: str(item[0])):
        if str(key) in excluded:
            continue
        if value is None or value == "":
            continue

        key_token = _slugify_token(key)
        value_token = _slugify_token(value)
        parts.append(f"{key_token}-{value_token}")

    return "__".join(parts) if parts else "default"


def build_construct_instance_key(
    *,
    construct_key: str,
    binding_slug: str,
    params: Mapping[str, Any] | None = None,
    exclude_param_keys: Iterable[str] | None = None,
    hash_len: int = 8,
    max_readable_length: int = 120,
) -> str:
    """
    Build the canonical saved construct instance key.

    Rules:
    - unary single-source constructs follow the same source-first naming policy
      as unary columns:
          <source>__<suffix>
    - for unary single-source constructs, params already encoded in the suffix
      MUST NOT be appended again
    - other constructs continue to use:
          <construct-token>__<binding-slug>
    - meaningful non-binding params, when present, are appended only for
      non-unary constructs

    Current unary construct ground truth
    ------------------------------------
    Only these active construct families currently use source-first unary saved
    instance naming:
    - derivative
    - angle

    ``slope`` is intentionally absent because it is no longer an active
    construct family.
    """
    params = dict(params or {})
    resolved_binding_slug = str(binding_slug or "default").strip() or "default"
    binding_token = _slugify_binding_slug(resolved_binding_slug)
    param_slug = build_param_slug(params, exclude_keys=exclude_param_keys)

    readable: str

    if _is_unary_single_source_construct(construct_key=construct_key, params=params):
        source_name = params.get("source", params.get("source_column"))
        if source_name is None or str(source_name).strip() == "":
            raise ValueError(
                f"{construct_key} requires 'source' or 'source_column' for canonical unary file naming"
            )

        suffix = resolve_construct_token(construct_key=construct_key, params=params)
        readable = build_unary_name(source_name, suffix)

    else:
        construct_token = resolve_construct_token(construct_key=construct_key, params=params)
        readable = f"{construct_token}__{binding_token}"

        if param_slug and param_slug != "default":
            readable += f"__{param_slug}"

    if _is_active_construct_key(construct_key):
        identity_hash = _construct_identity_hash(
            construct_key=construct_key,
            binding_slug=binding_token,
            params=params,
            exclude_param_keys=exclude_param_keys,
            hash_len=hash_len,
        )
        return _append_hash_suffix(
            readable,
            identity_hash=identity_hash,
            max_readable_length=max_readable_length,
        )

    if len(readable) > max_readable_length:
        readable = readable[:max_readable_length].rstrip("_-")

    return readable


def build_construct_filename(
    *,
    construct_key: str,
    binding_slug: str,
    params: Mapping[str, Any] | None = None,
    exclude_param_keys: Iterable[str] | None = None,
    extension: str = ".csv",
    hash_len: int = 8,
    max_readable_length: int = 120,
) -> str:
    """
    Build a filesystem-safe saved construct filename.
    """
    instance_key = build_construct_instance_key(
        construct_key=construct_key,
        binding_slug=binding_slug,
        params=params,
        exclude_param_keys=exclude_param_keys,
        hash_len=hash_len,
        max_readable_length=max_readable_length,
    )

    ext = str(extension or ".csv").strip()
    if not ext.startswith("."):
        ext = f".{ext}"

    return f"{instance_key}{ext}"
