from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

def _normalize_param_value(value: Any) -> Any:
    """
    Normalize values into deterministic JSON-safe primitives for hashing.

    This is intentionally conservative and avoids pulling in pandas/numpy
    dependencies at the naming layer.
    """
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_param_value(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }

    if isinstance(value, (list, tuple)):
        return [_normalize_param_value(item) for item in value]

    if isinstance(value, set):
        return [_normalize_param_value(item) for item in sorted(value, key=str)]

    if isinstance(value, (bool, int, float, str)) or value is None:
        return value

    return str(value)


def _json_signature(payload: Mapping[str, Any]) -> str:
    """
    Return a deterministic JSON signature for hashing.
    """
    normalized = _normalize_param_value(dict(payload))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _short_hash(payload: Mapping[str, Any], *, length: int = 8) -> str:
    """
    Build a short deterministic hash from a canonical signature payload.
    """
    digest = hashlib.sha256(_json_signature(payload).encode("utf-8")).hexdigest()
    return digest[:length]
